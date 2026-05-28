"""意图识别服务"""
import logging
import re
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

INTENT_TYPES = ["知识问答", "课程讲解", "测验请求", "进度查询", "自由聊天"]

# 关键词快速匹配规则（作为LLM的fallback，提升准确率和速度）
KEYWORD_RULES = [
    ("测验请求", ["出题", "考考", "测验", "测试", "quiz", "做题", "题目", "练习", "题"]),
    ("课程讲解", ["讲解", "教教我", "怎么学", "给我讲", "介绍一下", "什么是", "学学"]),
    ("知识问答", ["为什么", "怎么", "多少", "什么是", "什么叫", "怎么算", "如何", "等于", "公式", "定义"]),
    ("进度查询", ["进度", "学到哪", "掌握", "成绩", "报告", "统计"]),
]

_llm = None


def get_llm():
    global _llm
    if _llm is None:
        _llm = ChatOpenAI(
            model=settings.LLM_MODEL,
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL,
            temperature=0.0,
        )
    return _llm


_intent_prompt = ChatPromptTemplate.from_messages([
    ("system", "你是意图识别专家。请严格只输出以下5种意图之一，不要有任何解释：\n" +
     "- 知识问答：用户问具体知识点（如什么是绝对值、怎么计算）\n" +
     "- 课程讲解：用户要求系统讲解某个章节或概念\n" +
     "- 测验请求：用户要求出题或测试\n" +
     "- 进度查询：用户查询学习进度\n" +
     "- 自由聊天：其他闲聊或 greetings"),
    ("human", "用户输入：{message}\n意图："),
])


def classify_intent(message: str) -> str:
    """识别用户意图：先关键词匹配，再用LLM确认"""
    msg = message.strip().lower()

    # 关键词快速匹配
    for intent, keywords in KEYWORD_RULES:
        for kw in keywords:
            if kw in msg:
                logger.info("意图(关键词): %s -> %s", msg[:30], intent)
                return intent

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
