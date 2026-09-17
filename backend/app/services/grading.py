"""判分服务：提交答案 → 判分 → 错因诊断。

策略分两层：
- 选择题：字母提取后本地精确比对，不调 LLM 判对错（确定性场景不浪费 token、
  不受 LLM 波动影响）；仅答错时调一次 LLM 生成错因诊断。
- 填空/简答：LLM 判分（允许等价表述），解析失败时降级为规范化字符串比对。
"""
import logging
import re

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

from app.services.teaching import get_llm, _extract_text  # noqa: F401  (复用同一 LLM 实例)

logger = logging.getLogger(__name__)

# 错因标签集合（与 prompt 约定一致，解析时做白名单校验）
MISCONCEPTION_TYPES = {"概念不清", "审题偏差", "计算失误", "表达不完整", "知识遗忘", "无"}

_GRADE_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "你是一位经验丰富的中学判分老师。请判定学生作答并诊断错因。\n"
     "判分宽松合理：意思等价、表述不同也算正确；部分正确给部分分。\n"
     "严格按以下模板输出，不要输出任何额外说明：\n"
     "【判定】正确|部分正确|错误\n"
     "【得分】（0.0到1.0之间的小数，正确为1.0，错误为0.0）\n"
     "【错因】（仅从以下标签选一个：概念不清|审题偏差|计算失误|表达不完整|知识遗忘|无）\n"
     "【诊断】（面向学生的鼓励式讲解：错在哪一步、根源概念是什么、如何改正；答对时写一句肯定与拓展，150字内）"),
    ("human",
     "【题目】{question}\n【选项】{options}\n【标准答案】{correct_answer}\n"
     "【参考解析】{explanation}\n【学生作答】{user_answer}"),
])

_DIAGNOSIS_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "你是一位经验丰富的中学老师。学生答错了一道选择题，请诊断错因。\n"
     "严格按以下模板输出：\n"
     "【错因】（仅从以下标签选一个：概念不清|审题偏差|计算失误|知识遗忘）\n"
     "【诊断】（面向学生的鼓励式讲解：为什么错、正确思路是什么，120字内）"),
    ("human",
     "【题目】{question}\n【选项】{options}\n【标准答案】{correct_answer}\n【学生作答】{user_answer}"),
])


# 显式作答模式（按优先级）：避免"A不对，应该选B"这类表述提取到错误字母
# 注意：匹配前文本已 upper()，英文模式需大写
_EXPLICIT_LETTER_PATTERNS = [
    re.compile(r'选\s*([A-D])'),                    # 应该选B / 我选A
    re.compile(r'答案是\s*[：:]?\s*([A-D])'),       # 答案是B
    re.compile(r'^\s*([A-D])\s*[.、．]?$'),         # 整句只有一个字母
    # 英文作答：the answer is B / I choose B（取紧跟在关键词后的字母）
    re.compile(r'(?:ANSWER|CHOOSE|CHOICE|PICK)\s*(?:IS\s*)?[：:\s]\s*([A-D])(?![A-Z])'),
]

# 兜底：仅匹配独立成词的字母（前后不是其他大写字母），
# 避免从英文作答的 "CHOOSE""BECAUSE" 等单词中误取首字母
_STANDALONE_LETTER_RE = re.compile(r'(?<![A-Z])([A-D])(?![A-Z])')


def _extract_choice_letter(text: str) -> str | None:
    """从作答/答案文本中提取选项字母：先显式模式，兜底只认独立成词的字母。

    返回 None 表示无法可靠提取，调用方应降级 LLM 判分而非当成答错。"""
    t = (text or '').strip().upper()
    for pattern in _EXPLICIT_LETTER_PATTERNS:
        m = pattern.search(t)
        if m:
            return m.group(1)
    m = _STANDALONE_LETTER_RE.search(t)
    return m.group(1) if m else None


def _normalize(text: str) -> str:
    """规范化答案用于兜底比对：去空白与句末标点。"""
    return re.sub(r'[\s。．.！!？?，,]+', '', text or '')


def _parse_grade_output(text: str) -> dict:
    """解析 LLM 判分输出，失败时返回 None 由调用方兜底。"""
    verdict_m = re.search(r'【判定】\s*(正确|部分正确|错误)', text)
    score_m = re.search(r'【得分】\s*([01](?:\.\d+)?)', text)
    cause_m = re.search(r'【错因】\s*([^\n【】]+)', text)
    diag_m = re.search(r'【诊断】\s*(.*?)(?=【|$)', text, re.DOTALL)
    if not (verdict_m and score_m):
        return None
    verdict = verdict_m.group(1)
    try:
        score = max(0.0, min(1.0, float(score_m.group(1))))
    except ValueError:
        return None
    cause = cause_m.group(1).strip() if cause_m else "无"
    if cause not in MISCONCEPTION_TYPES:
        cause = "无" if verdict == "正确" else "概念不清"
    return {
        "is_correct": verdict == "正确",
        "score": score if verdict != "正确" else 1.0,
        "misconception": None if verdict == "正确" else cause,
        "diagnosis": diag_m.group(1).strip() if diag_m else "",
    }


async def _llm_grade(question, options, correct_answer, explanation, user_answer) -> dict | None:
    """LLM 判分（填空/简答），astream 聚合（与 teaching 一致，保证事件可冒泡）。"""
    chain = _GRADE_PROMPT | get_llm()
    options_text = "\n".join(f"{chr(65 + i)}. {o}" for i, o in enumerate(options or [])) or "（无选项）"
    parts: list[str] = []
    async for chunk in chain.astream({
        "question": question,
        "options": options_text,
        "correct_answer": correct_answer,
        "explanation": explanation or "（无）",
        "user_answer": user_answer,
    }):
        text = _extract_text(chunk)
        if text:
            parts.append(text)
    return _parse_grade_output("".join(parts))


async def _llm_diagnosis(question, options, correct_answer, user_answer) -> dict:
    """选择题答错时的错因诊断。失败时返回空诊断。"""
    chain = _DIAGNOSIS_PROMPT | get_llm() | StrOutputParser()
    options_text = "\n".join(f"{chr(65 + i)}. {o}" for i, o in enumerate(options or [])) or "（无选项）"
    try:
        text = await chain.ainvoke({
            "question": question,
            "options": options_text,
            "correct_answer": correct_answer,
            "user_answer": user_answer,
        })
        cause_m = re.search(r'【错因】\s*([^\n【】]+)', text)
        diag_m = re.search(r'【诊断】\s*(.*?)$', text, re.DOTALL)
        cause = cause_m.group(1).strip() if cause_m else "概念不清"
        if cause not in MISCONCEPTION_TYPES:
            cause = "概念不清"
        return {"misconception": cause, "diagnosis": diag_m.group(1).strip() if diag_m else ""}
    except Exception as e:
        logger.warning("错因诊断失败: %s", e)
        return {"misconception": None, "diagnosis": ""}


async def grade_answer(
    question: str,
    options: list[str] | None,
    correct_answer: str,
    explanation: str,
    user_answer: str,
    question_type: str = "选择",
) -> dict:
    """判分入口。返回 {is_correct, score, misconception, diagnosis}。"""
    is_choice = question_type == "选择" or bool(options)
    correct_letter = _extract_choice_letter(correct_answer) if is_choice else None

    if is_choice and correct_letter is not None:
        # 标准路径：字母本地精确比对，不调 LLM 判对错
        student_letter = _extract_choice_letter(user_answer)
        if student_letter is not None:
            is_correct = student_letter == correct_letter
            if is_correct:
                return {"is_correct": True, "score": 1.0, "misconception": None, "diagnosis": ""}
            diag = await _llm_diagnosis(question, options, correct_answer, user_answer)
            return {"is_correct": False, "score": 0.0, **diag}
        # 自由表述的作答（如英文解释）无法可靠提取字母，误判为错会污染掌握度，
        # 降级 LLM 判分让模型按作答内容语义判定
        logger.info("选择题作答未提取到选项字母，降级LLM判分: %s", user_answer[:50])

    if is_choice:
        # 出题未遵守"答案只写字母"（如解析性文本），本地比对不可用，降级 LLM 判分
        logger.warning("选择题标准答案非字母格式，降级LLM判分: %s", correct_answer[:50])

    # 填空 / 简答 / 非常规选择题：LLM 判分，失败兜底规范化比对
    try:
        result = await _llm_grade(question, options, correct_answer, explanation, user_answer)
    except Exception as e:
        logger.warning("LLM判分失败，降级字符串比对: %s", e)
        result = None
    if result is None:
        is_correct = _normalize(user_answer) == _normalize(correct_answer)
        return {"is_correct": is_correct, "score": 1.0 if is_correct else 0.0,
                "misconception": None, "diagnosis": ""}
    return result
