#!/usr/bin/env python3
"""从教材知识库自动生成 Ragas 评估测试集（LLM 出题 + 标准答案）。

用法（在 backend/ 目录下运行）:
    uv run python scripts/gen_eval_testset.py
    uv run python scripts/gen_eval_testset.py --per-subject 5 --questions 4
    uv run python scripts/gen_eval_testset.py --subjects chinese_7a english_7a --out scripts/my_testset.jsonl

工作机制:
    1. 从 ChromaDB 取出全部"课文内容"chunk，按 (学科, 年级, 学期, 课文) 分组并拼接课文全文
    2. 每本教材随机抽样若干篇课文，让 LLM 基于课文原文出题并给标准答案
    3. 每篇课文的问题一半标为 A 类（带 lesson_id，走 metadata 精确匹配路径），
       一半标为 B 类（不带 lesson_id，走向量+BM25 混合检索路径），
       保证两条检索路径都被覆盖

输出 JSONL，每行一条样本:
    question    问题文本
    subject     学科ID（如 chinese_7a）
    chapter     章节名（生成回复时的上下文）
    lesson_id   课文ID；qtype=A 时有值，B 时为 null
    gold_lesson 目标课文名（用于确定性召回率判定）
    reference   标准答案
    qtype       A=指定课文 / B=开放式提问
"""
import argparse
import asyncio
import json
import logging
import os
import random
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# 显式加载项目根目录的 .env，确保脚本独立运行时环境变量正确
from dotenv import load_dotenv

_script_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(os.path.dirname(_script_dir))
load_dotenv(os.path.join(_project_root, ".env"), override=True)

from langchain_core.messages import HumanMessage

from app.services.rag import get_collection, _SUBJECT_ID_MAP, _SUBJECTS_DIR, _GENERATED_DIR
from app.services.teaching import get_llm
from app.services.textbook_parser import GRADE_SUFFIX_MAP

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# 学科中文名 -> 学科ID前缀（_SUBJECT_ID_MAP 的反转）
_SUBJECT_NAME_TO_ID = {v: k for k, v in _SUBJECT_ID_MAP.items()}


def _build_lesson_id_map() -> dict[str, str]:
    """课文名 -> 课文ID。除课文名本身外，补充 '{章节} - {课文}' 组合键：
    英语等学科的 chunk metadata lesson 是组合名（如 'Starter Unit 1 Good morning! - 1a 词汇学习'），
    而 JSON 中课文名只有后半段（'1a 词汇学习'），仅用课文名做键会查不到 lesson_id。"""
    result: dict[str, str] = {}
    for data_dir in (_SUBJECTS_DIR, _GENERATED_DIR):
        if not data_dir.exists():
            continue
        for json_file in data_dir.glob("*/*.json"):
            data = json.loads(json_file.read_text(encoding="utf-8"))
            for chapter in data.get("chapters", []):
                chapter_name = chapter.get("name", "")
                for lesson in chapter.get("lessons", []):
                    lesson_id, name = lesson.get("id"), lesson.get("name")
                    if lesson_id and name:
                        result[name] = lesson_id
                        if chapter_name:
                            result[f"{chapter_name} - {name}"] = lesson_id
    return result


_LESSON_NAME_TO_ID = _build_lesson_id_map()

_GEN_PROMPT = """你是一位中学教研员，正在为期末复习出题。请基于下面的课文内容，出 {n} 道考查学生对课文掌握情况的问题，并给出标准答案。

要求：
1. 答案必须能从课文内容中直接找到或归纳得出，不要超出课文范围
2. 题型多样：事实细节题（谁/什么/何时何地）、理解归纳题（为什么/概括主旨）、词句含义题
3. 至少 1 道题的题干不要出现课文标题，模拟学生脱离课文泛泛提问（如"什么是光合作用"而非"《光合作用》一课讲了什么"）
4. 标准答案简明准确，50~150 字
5. 严格以 JSON 数组输出，不要输出任何其他内容：[{{"question": "...", "answer": "..."}}]

【课文】{lesson_name}
{content}"""


def _chunk_order_key(chunk_id: str) -> int:
    """从 chunk ID 尾部解析序号用于排序，如 '..._chunk_12' -> 12。"""
    m = re.search(r"_(\d+)$", chunk_id or "")
    return int(m.group(1)) if m else 0


def load_lessons_from_kb(min_chars: int = 300) -> list[dict]:
    """从 ChromaDB 读取全部课文 chunk，按课文分组拼接全文。"""
    collection = get_collection()
    res = collection.get(where={"content_type": "课文内容"}, include=["metadatas", "documents"])
    groups: dict[tuple, dict] = {}
    for doc_id, meta, doc in zip(res["ids"], res["metadatas"], res["documents"]):
        lesson = (meta or {}).get("lesson") or ""
        if not lesson:
            continue
        key = (meta.get("subject"), meta.get("grade"), meta.get("semester"), lesson)
        g = groups.setdefault(key, {"meta": meta, "chunks": []})
        g["chunks"].append((_chunk_order_key(doc_id), doc))

    lessons = []
    for (subject, grade, semester, lesson), g in groups.items():
        base = _SUBJECT_NAME_TO_ID.get(subject)
        suffix = GRADE_SUFFIX_MAP.get(f"{grade}{semester}")
        if not base or not suffix:
            continue
        chunks = [doc for _, doc in sorted(g["chunks"], key=lambda x: x[0])]
        content = "\n".join(chunks)
        if len(content) < min_chars:
            continue
        lessons.append({
            "subject_id": f"{base}_{suffix}",
            "chapter": g["meta"].get("chapter", ""),
            "lesson_name": lesson,
            "lesson_id": _LESSON_NAME_TO_ID.get(lesson),  # 可能为 None（如未解析 JSON 的 7b）
            "content": content,
        })
    return lessons


def _parse_qa_json(text: str) -> list[dict]:
    """从 LLM 输出中解析 JSON 数组，容忍 Markdown 代码块包裹。"""
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1:
        return []
    try:
        items = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return []
    return [it for it in items if isinstance(it, dict) and it.get("question") and it.get("answer")]


async def gen_questions_for_lesson(lesson: dict, n: int, max_chars: int, sem: asyncio.Semaphore) -> list[dict]:
    """对一篇课文调用 LLM 生成 n 条 QA，输出测试集样本。"""
    prompt = _GEN_PROMPT.format(n=n, lesson_name=lesson["lesson_name"], content=lesson["content"][:max_chars])
    async with sem:
        for attempt in range(2):  # JSON 解析失败时重试一次
            resp = await get_llm().ainvoke([HumanMessage(content=prompt)])
            qa_list = _parse_qa_json(resp.content if isinstance(resp.content, str) else str(resp.content))
            if qa_list:
                break
        else:
            logger.warning("出题失败，跳过: %s %s", lesson["subject_id"], lesson["lesson_name"])
            return []

    samples = []
    for i, qa in enumerate(qa_list[:n]):
        # 一半 A 类（指定课文，测精确匹配路径），一半 B 类（开放提问，测混合检索路径）
        is_type_a = i % 2 == 0 and lesson["lesson_id"] is not None
        samples.append({
            "question": qa["question"].strip(),
            "subject": lesson["subject_id"],
            "chapter": lesson["chapter"],
            "lesson_id": lesson["lesson_id"] if is_type_a else None,
            "gold_lesson": lesson["lesson_name"],
            "reference": qa["answer"].strip(),
            "qtype": "A" if is_type_a else "B",
        })
    return samples


async def main():
    parser = argparse.ArgumentParser(description="生成 Ragas 评估测试集")
    parser.add_argument("--per-subject", type=int, default=3, help="每本教材抽样课文数（默认 3）")
    parser.add_argument("--questions", type=int, default=3, help="每篇课文出题数（默认 3）")
    parser.add_argument("--subjects", nargs="*", default=None, help="只生成指定学科ID，如 chinese_7a")
    parser.add_argument("--out", default=os.path.join(_script_dir, "eval_testset.jsonl"), help="输出文件路径")
    parser.add_argument("--seed", type=int, default=42, help="抽样随机种子")
    parser.add_argument("--concurrency", type=int, default=4, help="LLM 并发数")
    parser.add_argument("--max-chars", type=int, default=6000, help="喂给 LLM 的课文最大字符数")
    args = parser.parse_args()

    lessons = load_lessons_from_kb()
    if args.subjects:
        lessons = [l for l in lessons if l["subject_id"] in args.subjects]
    logger.info("知识库中可用课文 %d 篇", len(lessons))

    # 按教材分组后组内抽样，保证每本教材都有覆盖
    by_book: dict[str, list[dict]] = {}
    for l in lessons:
        by_book.setdefault(l["subject_id"], []).append(l)
    rng = random.Random(args.seed)
    sampled = []
    for book, items in sorted(by_book.items()):
        take = items if len(items) <= args.per_subject else rng.sample(items, args.per_subject)
        logger.info("%s: 共 %d 篇课文，抽样 %d 篇", book, len(items), len(take))
        sampled.extend(take)

    sem = asyncio.Semaphore(args.concurrency)
    results = await asyncio.gather(*(
        gen_questions_for_lesson(l, args.questions, args.max_chars, sem) for l in sampled
    ))
    samples = [s for batch in results for s in batch]

    with open(args.out, "w", encoding="utf-8") as f:
        for s in samples:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
    n_a = sum(1 for s in samples if s["qtype"] == "A")
    logger.info("已写入 %s：共 %d 题（A类 %d / B类 %d）", args.out, len(samples), n_a, len(samples) - n_a)


if __name__ == "__main__":
    asyncio.run(main())
