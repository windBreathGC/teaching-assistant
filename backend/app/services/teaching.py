"""教学回复生成服务"""
import logging
import re
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

_llm = None


def get_llm():
    global _llm
    if _llm is None:
        _llm = ChatOpenAI(
            model=settings.LLM_MODEL,
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL,
            temperature=0.5,
            # Qwen3 等思考模型默认开启 thinking，思考阶段 content 为空会导致
            # 流式响应长时间无输出；教学问答有 RAG 兜底，不需要深度推理，关闭之
            # （该 provider 认顶层 enable_thinking 参数，不认 chat_template_kwargs）
            extra_body={"enable_thinking": False},
        )
    return _llm


_system_prompt = """你是一位经验丰富、耐心细致的中学教师，正在辅导七年级学生。请严格遵循以下教学原则：

1. 循序渐进：先通过"情境导入"引发兴趣，再讲解概念，然后分析例题，最后给出练习。
2. 教材为纲：优先引用教材原文，关键定义、公式必须准确，不可自行编造。
3. 生动易懂：用生活化的比喻解释抽象概念，避免过度学术化语言。
4. 互动引导：多用提问和启发式语言，鼓励学生思考，而非直接给答案。
5. 结构化输出：使用清晰的标题、列表、分段，让学生容易阅读和理解。

当前课程信息：
- 学科：{subject}
- 章节：{chapter}
- 课文：{lesson}

重要约束：
- 只讲解当前指定的这篇课文，不要涉及其他课文或单元内容
- 不要编造"下节课"、"接下来"等引向其他课文的过渡语
- 如果检索到的内容包含其他课文，请忽略，只聚焦当前课文
"""

_reply_prompt = ChatPromptTemplate.from_messages([
    ("system", _system_prompt),
    ("human", "【检索到的教材内容】\n{context}\n\n【用户问题】\n{message}\n\n请基于教材内容，以教师的身份给出详细、生动、循序渐进的回答。"),
])


def _build_context(docs: list[dict]) -> str:
    """把检索文档拼接成上下文字符串"""
    context = "\n\n---\n\n".join(
        f"[来源: {d.get('metadata', {}).get('lesson', '教材')}]\n{d.get('content', '')[:3000]}"
        for d in docs[:2]
    )
    if not context:
        context = "（未检索到相关教材内容，请基于你的知识回答，但仍需遵循教学原则）"
    return context


def _build_suggested_actions(message: str) -> list[str]:
    """根据用户消息生成建议操作列表。"""
    actions = []
    if "例题" not in message and "题" not in message:
        actions.append("出道例题")
    if "总结" not in message:
        actions.append("总结重点")
    if "练习" not in message and "题" not in message:
        actions.append("来道练习题")
    return actions[:3]


def generate_reply(message: str, subject: str, chapter: str, lesson: str | None, docs: list[dict]) -> dict:
    """基于检索结果生成教学回复（同步版本）"""
    context = _build_context(docs)
    chain = _reply_prompt | get_llm() | StrOutputParser()
    reply = chain.invoke({
        "message": message,
        "subject": subject or "未知学科",
        "chapter": chapter or "未知章节",
        "lesson": lesson or "未指定课文",
        "context": context,
    })

    return {
        "reply": reply.strip(),
        "suggested_actions": _build_suggested_actions(message),
    }


async def agenerate_reply(message: str, subject: str, chapter: str, lesson: str | None, docs: list[dict]) -> dict:
    """基于检索结果生成教学回复（异步版本）。

    内部采用 astream 逐 token 生成并聚合：返回值与一次性调用无异，
    但当外层通过 LangGraph astream_events 消费时，LLM 的 token 事件
    （on_chat_model_stream）能冒泡出去，支撑真流式接口。"""
    context = _build_context(docs)
    chain = _reply_prompt | get_llm()
    parts: list[str] = []
    async for chunk in chain.astream({
        "message": message,
        "subject": subject or "未知学科",
        "chapter": chapter or "未知章节",
        "lesson": lesson or "未指定课文",
        "context": context,
    }):
        text = _extract_text(chunk)
        if text:
            parts.append(text)

    return {
        "reply": "".join(parts).strip(),
        "suggested_actions": _build_suggested_actions(message),
    }


def _extract_text(chunk) -> str:
    """从 AIMessageChunk 提取纯文本；兼容 content block 列表形式（部分 OpenAI 兼容平台）。"""
    content = chunk.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block.get("text", "") for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return ""


async def stream_reply(message: str, subject: str, chapter: str, lesson: str | None, docs: list[dict]):
    """流式生成教学回复，yield 每个 token（空 chunk 已过滤）"""
    context = _build_context(docs)
    chain = _reply_prompt | get_llm()
    async for chunk in chain.astream({
        "message": message,
        "subject": subject or "未知学科",
        "chapter": chapter or "未知章节",
        "lesson": lesson or "未指定课文",
        "context": context,
    }):
        # chain 末尾没有 StrOutputParser，astream  yield 的是 AIMessageChunk
        # role/usage/finish_reason 等脚手架 chunk 的 content 为空，过滤掉避免产生空 SSE 事件
        text = _extract_text(chunk)
        if text:
            yield text


_quiz_prompt = ChatPromptTemplate.from_messages([
    ("system", "你是一位出题老师。请严格根据以下教材内容，为课文《{lesson}》生成一道{difficulty}难度的{question_type}题。\n" +
     "要求：\n1. 题目必须紧扣《{lesson}》这篇课文的内容，不得涉及其它课文\n2. 给出正确答案和详细解析\n3. 指出易错点\n\n" +
     "输出格式必须严格遵循以下模板（不要输出任何额外说明文字）：\n" +
     "【题目】（题目内容）\n" +
     "【选项】（如果是选择题，每行一个选项，格式为A. xxx、B. xxx、C. xxx、D. xxx）\n" +
     "【答案】（正确答案。选择题只写字母，如A、B、C、D；填空题写完整答案；简答题写要点）\n" +
     "【解析】（详细解析，包括解题思路和易错点分析）"),
    ("human", "【教材内容】\n{context}\n\n请为《{lesson}》生成题目。"),
])


def parse_quiz_output(text: str) -> dict:
    """从AI输出中解析测验题结构"""
    text = text.strip()

    # 提取题目
    question_match = re.search(r'【题目】\s*(.*?)(?=【选项】|【答案】|【解析】|$)', text, re.DOTALL)
    question = question_match.group(1).strip() if question_match else text

    # 提取选项
    options = None
    options_match = re.search(r'【选项】\s*(.*?)(?=【答案】|【解析】|$)', text, re.DOTALL)
    if options_match:
        options_text = options_match.group(1).strip()
        lines = [l.strip() for l in options_text.split('\n') if l.strip()]
        parsed_options = []
        for line in lines:
            m = re.match(r'^([A-D])[\.．、]\s*(.+)', line)
            if m:
                parsed_options.append(m.group(2).strip())
        if parsed_options:
            options = parsed_options

    # 提取答案
    answer_match = re.search(r'【答案】\s*([^\n【】]+)', text)
    correct_answer = answer_match.group(1).strip() if answer_match else ''

    # 提取解析
    explanation_match = re.search(r'【解析】\s*(.*?)(?=【|$)', text, re.DOTALL)
    explanation = explanation_match.group(1).strip() if explanation_match else ''

    return {
        "question": question,
        "options": options,
        "correct_answer": correct_answer,
        "explanation": explanation,
    }


def generate_quiz(subject: str, chapter: str, lesson: str | None, docs: list[dict], difficulty: str = "基础", question_type: str = "选择") -> dict:
    """基于检索结果生成测验题"""
    context = "\n\n---\n\n".join(
        f"{d.get('metadata', {}).get('lesson', '')}\n{d.get('content', '')[:2000]}"
        for d in docs[:3]
    )
    if not context:
        context = "（无特定教材内容，请生成一道通用的基础题）"

    chain = _quiz_prompt | get_llm() | StrOutputParser()
    result = chain.invoke({
        "context": context,
        "difficulty": difficulty,
        "question_type": question_type,
        "lesson": lesson or "指定课文",
    })

    parsed = parse_quiz_output(result)

    return {
        "question": parsed["question"],
        "options": parsed["options"],
        "correct_answer": parsed["correct_answer"],
        "explanation": parsed["explanation"],
        "knowledge_point": chapter or "通用知识点",
    }


async def stream_quiz(subject: str, chapter: str, lesson: str | None, docs: list[dict], difficulty: str = "基础", question_type: str = "选择"):
    """流式生成测验题，逐 token yield"""
    context = "\n\n---\n\n".join(
        f"{d.get('metadata', {}).get('lesson', '')}\n{d.get('content', '')[:2000]}"
        for d in docs[:3]
    )
    if not context:
        context = "（无特定教材内容，请生成一道通用的基础题）"

    chain = _quiz_prompt | get_llm()
    async for chunk in chain.astream({
        "context": context,
        "difficulty": difficulty,
        "question_type": question_type,
        "lesson": lesson or "指定课文",
    }):
        # 同 stream_reply：过滤 content 为空的脚手架 chunk
        text = _extract_text(chunk)
        if text:
            yield text
