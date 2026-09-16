#!/usr/bin/env python3
"""Ragas 评估脚本：检索召回率（确定性指标）+ 生成准确率（Ragas LLM 裁判）。

用法（在 backend/ 目录下运行）:
    uv run python scripts/eval_ragas.py                     # 全量评估
    uv run python scripts/eval_ragas.py --limit 5           # 小规模冒烟
    uv run python scripts/eval_ragas.py --skip-ragas        # 只跑确定性检索指标（不调裁判，零成本）
    uv run python scripts/eval_ragas.py --top-k 5           # 对比不同 top_k 下的召回/精度

指标说明:
    确定性检索指标（利用 chunk 的 lesson metadata，无需 LLM，准确且免费）:
        hit_rate@k  检索结果中是否包含目标课文的 chunk
        mrr         目标课文首个命中 chunk 的排名倒数均值
    Ragas 指标（LLM 裁判）:
        faithfulness        回答是否完全由检索内容支撑（防幻觉，核心指标）
        answer_correctness  回答与标准答案的一致程度
        context_precision   检索到的内容与问题的相关度
        context_recall      检索内容对标准答案的覆盖度

输出:
    eval_report_YYYYMMDD_HHMMSS.csv   逐样本指标 + 元信息（对比实验存档用）
    eval_debug_YYYYMMDD_HHMMSS.jsonl  逐样本完整 response 与检索上下文（失败分析用）
"""
import argparse
import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# 显式加载项目根目录的 .env，确保脚本独立运行时环境变量正确
from dotenv import load_dotenv

_script_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(os.path.dirname(_script_dir))
load_dotenv(os.path.join(_project_root, ".env"), override=True)

from langchain_openai import ChatOpenAI

from app.core.config import get_settings
from app.services.rag import aretrieve, get_embeddings, get_lesson_name
from app.services.teaching import agenerate_reply

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)
settings = get_settings()


def _is_gold_hit(meta_lesson: str, gold_lesson: str) -> bool:
    """判定 chunk 的 lesson metadata 是否命中目标课文（双向子串，容忍命名差异）。"""
    meta_lesson = meta_lesson or ""
    return bool(gold_lesson) and (gold_lesson in meta_lesson or (meta_lesson and meta_lesson in gold_lesson))


async def run_pipeline(item: dict, top_k: int, sem: asyncio.Semaphore) -> dict:
    """复现 agent 中 retrieve -> reply 的调用链（agent.py retrieve_node / reply_node）。"""
    question = item["question"]
    lesson_name = get_lesson_name(item.get("lesson_id"))
    async with sem:
        # 与线上 agent 一致：指定课文时把课文名拼进 query
        query = f"{lesson_name} {question}" if lesson_name else question
        docs = await aretrieve(
            query=query,
            subject=item.get("subject"),
            lesson=item.get("lesson_id"),
            top_k=top_k,
        )
        result = await agenerate_reply(
            message=question,
            subject=item.get("subject") or "未知学科",
            chapter=item.get("chapter") or "未知章节",
            lesson=lesson_name,
            docs=docs,
        )

    lessons = [d.get("metadata", {}).get("lesson", "") for d in docs]
    gold_rank = next((i + 1 for i, l in enumerate(lessons) if _is_gold_hit(l, item["gold_lesson"])), None)
    return {
        "user_input": question,
        "retrieved_contexts": [d.get("content", "") for d in docs],
        "retrieved_lessons": lessons,
        "response": result["reply"],
        "reference": item["reference"],
        "subject": item["subject"],
        "qtype": item["qtype"],
        "gold_lesson": item["gold_lesson"],
        "gold_hit": gold_rank is not None,
        "gold_rank": gold_rank or 0,
    }


def report_retrieval(results: list[dict]) -> None:
    """打印确定性检索指标：整体 + 按 A/B 路径分组。"""
    def _stats(rows: list[dict]) -> str:
        if not rows:
            return "n=0"
        hit = sum(r["gold_hit"] for r in rows) / len(rows)
        mrr = sum(1.0 / r["gold_rank"] for r in rows if r["gold_rank"]) / len(rows)
        return f"n={len(rows)}  hit_rate={hit:.3f}  mrr={mrr:.3f}"

    print("\n===== 确定性检索指标（基于 lesson metadata）=====")
    print(f"整体          {_stats(results)}")
    print(f"A类(精确匹配) {_stats([r for r in results if r['qtype'] == 'A'])}")
    print(f"B类(混合检索) {_stats([r for r in results if r['qtype'] == 'B'])}")


async def run_ragas(results: list[dict], concurrency: int):
    """调用 Ragas LLM 裁判评估生成质量。裁判模型独立构造，temperature=0 保证评分稳定。"""
    from ragas import EvaluationDataset, RunConfig, SingleTurnSample, evaluate
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from ragas.llms import LangchainLLMWrapper
    from ragas.metrics import AnswerCorrectness, ContextPrecision, ContextRecall, Faithfulness

    judge_llm = ChatOpenAI(
        model=settings.LLM_MODEL,
        api_key=settings.OPENAI_API_KEY,
        base_url=settings.OPENAI_BASE_URL,
        temperature=0,
        request_timeout=120,
        # 与 teaching.py 一致：Qwen3 等思考模型关闭 thinking，否则裁判调用极易超时
        extra_body={"enable_thinking": False},
    )
    samples = [
        SingleTurnSample(
            user_input=r["user_input"],
            retrieved_contexts=r["retrieved_contexts"],
            response=r["response"],
            reference=r["reference"],
        )
        for r in results
    ]
    return evaluate(
        dataset=EvaluationDataset(samples=samples),
        # AnswerCorrectness 用 weights=[1.0, 0.0] 关掉语义相似度子项：该项要把完整回答
        # 送去 embedding，而 bge-large-zh-v1.5 上限 512 tokens，长回答会被 SiliconFlow
        # 直接 400 拒绝。若以后换用 bge-m3 等长文本 embedding，可恢复默认 [0.75, 0.25]。
        metrics=[Faithfulness(), AnswerCorrectness(weights=[1.0, 0.0]), ContextPrecision(), ContextRecall()],
        llm=LangchainLLMWrapper(judge_llm),
        embeddings=LangchainEmbeddingsWrapper(get_embeddings()),
        # raise_exceptions=False：个别样本裁判失败记 NaN，不拖垮整轮评估
        run_config=RunConfig(max_workers=concurrency, timeout=300, max_retries=5),
        raise_exceptions=False,
    )


async def main():
    parser = argparse.ArgumentParser(description="Ragas 评估：检索召回率 + 生成准确率")
    parser.add_argument("--testset", default=os.path.join(_script_dir, "eval_testset.jsonl"), help="测试集路径")
    parser.add_argument("--limit", type=int, default=0, help="只评估前 N 条（冒烟用）")
    parser.add_argument("--top-k", type=int, default=2, help="检索返回条数，与线上 agent 一致为 2")
    parser.add_argument("--skip-ragas", action="store_true", help="只跑确定性检索指标，不调 LLM 裁判")
    parser.add_argument("--concurrency", type=int, default=4, help="并发数（受 API 限流约束）")
    args = parser.parse_args()

    with open(args.testset, encoding="utf-8") as f:
        testset = [json.loads(line) for line in f if line.strip()]
    if args.limit:
        testset = testset[: args.limit]
    logger.info("测试集 %d 条，top_k=%d", len(testset), args.top_k)

    sem = asyncio.Semaphore(args.concurrency)
    t0 = time.time()
    results = await asyncio.gather(*(run_pipeline(it, args.top_k, sem) for it in testset))
    logger.info("检索+生成完成，耗时 %.1fs", time.time() - t0)

    report_retrieval(results)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    debug_path = os.path.join(_script_dir, f"eval_debug_{ts}.jsonl")
    with open(debug_path, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    if args.skip_ragas:
        logger.info("已跳过 Ragas 裁判评估，明细见 %s", debug_path)
        return

    scores = await run_ragas(results, args.concurrency)
    df = scores.to_pandas()
    # 合并 Ragas 逐样本分数与我们自己的元信息（dataset 保序，按行号对齐）
    for col in ("subject", "qtype", "gold_lesson", "gold_hit", "gold_rank"):
        df[col] = [r[col] for r in results]
    report_path = os.path.join(_script_dir, f"eval_report_{ts}.csv")
    df.to_csv(report_path, index=False, encoding="utf-8-sig")

    metric_cols = ["faithfulness", "answer_correctness", "context_precision", "context_recall"]
    print("\n===== Ragas 指标（LLM 裁判，均值）=====")
    print(df[metric_cols].mean(numeric_only=True).round(4).to_string())
    print("\n===== 按 A/B 路径分组 =====")
    print(df.groupby("qtype")[metric_cols].mean(numeric_only=True).round(4).to_string())
    logger.info("报告已保存: %s；明细: %s", report_path, debug_path)


if __name__ == "__main__":
    asyncio.run(main())
