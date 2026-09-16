"""意图识别服务"""
import logging
import re
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

INTENT_TYPES = ["知识问答", "课程讲解", "测验请求", "作答判分", "进度查询", "自由聊天"]

# 关键词快速匹配规则（作为LLM的fallback，提升准确率和速度）
# 顺序即优先级：进度查询最前——"我的学习进度怎么样"含"怎么"，若知识问答在前会被误判。
# 注意关键词须用强信号：
# - "掌握"太宽泛（"掌握这个知识点"是学习问题而非查进度）→ 用"掌握度/掌握得"
# - "统计/报告"是学科内容词（"什么是统计图""怎么写实验报告"）→ 用"学习统计/学情报告"
KEYWORD_RULES = [
    ("进度查询", ["进度", "学到哪", "掌握度", "掌握得", "学情", "学得怎么样", "学的怎么样",
                  "成绩", "学习报告", "学情报告", "答题统计", "学习统计"]),
    ("测验请求", ["出题", "考考", "测验", "测试", "quiz", "做题", "题目", "练习", "题"]),
    ("课程讲解", ["讲解", "教教我", "怎么学", "给我讲", "介绍一下", "什么是", "学学"]),
    ("知识问答", ["为什么", "怎么", "多少", "什么是", "什么叫", "怎么算", "如何", "等于", "公式", "定义"]),
]

# 作答判分走显式作答模式（不进关键词表，避免"我选哪篇课文""这道题的答案是什么"误伤）：
# 单字母作答（"A"/"b"/"C."等），或"我选A/答案是B/答案选C"等带明确选项字母的表述
_CHOICE_ANSWER_RE = re.compile(r'^[abcd][.、。]?$')
_EXPLICIT_ANSWER_RE = re.compile(r'(我选|答案是|答案选)\s*[abcd][.、。]?$')

_llm = None


def get_llm():
    global _llm
    if _llm is None:
        _llm = ChatOpenAI(
            model=settings.LLM_MODEL,
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL,
            temperature=0.0,
            # 关闭 Qwen3 等模型的 thinking，意图分类无需推理且要避免思考延迟
            # （该 provider 认顶层 enable_thinking 参数，不认 chat_template_kwargs）
            extra_body={"enable_thinking": False},
        )
    return _llm


_intent_prompt = ChatPromptTemplate.from_messages([
    ("system", "你是意图识别专家。请严格只输出以下6种意图之一，不要有任何解释：\n" +
     "- 知识问答：用户问具体知识点（如什么是绝对值、怎么计算）\n" +
     "- 课程讲解：用户要求系统讲解某个章节或概念\n" +
     "- 测验请求：用户要求出题或测试\n" +
     "- 作答判分：用户在对之前出的题作答（如我选B、答案是A）\n" +
     "- 进度查询：用户查询学习进度\n" +
     "- 自由聊天：其他闲聊或 greetings"),
    ("human", "用户输入：{message}\n意图："),
])


def _match_keywords(msg: str) -> str | None:
    """关键词快速匹配，命中则返回意图，否则返回 None。"""
    # 显式作答模式优先：单字母或"我选X/答案是X"
    if _CHOICE_ANSWER_RE.match(msg) or _EXPLICIT_ANSWER_RE.search(msg):
        logger.info("意图(显式作答): %s -> 作答判分", msg[:30])
        return "作答判分"
    for intent, keywords in KEYWORD_RULES:
        for kw in keywords:
            if kw in msg:
                logger.info("意图(关键词): %s -> %s", msg[:30], intent)
                return intent
    return None


def classify_intent(message: str) -> str:
    """识别用户意图：先关键词匹配，再用LLM确认（同步版本）"""
    msg = message.strip().lower()

    # 关键词快速匹配
    matched = _match_keywords(msg)
    if matched:
        return matched

    # LLM兜底分类
    try:
        chain = _intent_prompt | get_llm() | StrOutputParser()
        result = chain.invoke({"message": message}).strip()
        for intent in INTENT_TYPES:
            if intent in result:
                logger.info("意图(LLM): %s -> %s", msg[:30], intent)
                return intent
    except Exception as e:
        logger.warning("LLM意图识别失败: %s, fallback到自由聊天", e)

    return "自由聊天"


async def aclassify_intent(message: str) -> str:
    """识别用户意图（异步版本）：逻辑同 classify_intent，但 LLM 兜底走 ainvoke，
    避免在 async 端点中阻塞事件循环。"""
    msg = message.strip().lower()

    # 关键词快速匹配
    matched = _match_keywords(msg)
    if matched:
        return matched

    # LLM兜底分类
    try:
        chain = _intent_prompt | get_llm() | StrOutputParser()
        result = (await chain.ainvoke({"message": message})).strip()
        for intent in INTENT_TYPES:
            if intent in result:
                logger.info("意图(LLM): %s -> %s", msg[:30], intent)
                return intent
    except Exception as e:
        logger.warning("LLM意图识别失败: %s, fallback到自由聊天", e)

    return "自由聊天"
