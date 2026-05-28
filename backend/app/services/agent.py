"""LangGraph 智能体工作流编排"""
import logging
from typing import TypedDict, Annotated
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
from langgraph.graph import StateGraph, END
import operator

from app.services.intent import classify_intent
from app.services.rag import retrieve, aretrieve, get_lesson_name
from app.services.teaching import generate_reply, agenerate_reply, generate_quiz

logger = logging.getLogger(__name__)


class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], operator.add]
    subject: str | None
    chapter: str | None
    lesson: str | None
    intent: str
    retrieved_docs: list[dict]
    reply: str
    suggested_actions: list[str]
    quiz_result: dict | None


# ---------- 节点函数（只返回需要更新的字段） ----------

def intent_node(state: AgentState) -> dict:
    """识别用户意图"""
    last_msg = state["messages"][-1].content if state["messages"] else ""
    intent = classify_intent(last_msg)
    return {"intent": intent}


async def retrieve_node(state: AgentState) -> dict:
    """RAG检索"""
    last_msg = state["messages"][-1].content if state["messages"] else ""
    lesson_name = get_lesson_name(state.get("lesson"))
    query = f"{lesson_name} {last_msg}" if lesson_name else last_msg
    docs = await aretrieve(
        query=query,
        subject=state.get("subject"),
        lesson=state.get("lesson"),
        top_k=2,
    )
    logger.info("检索到 %d 条知识", len(docs))
    return {"retrieved_docs": docs}


async def reply_node(state: AgentState) -> dict:
    """生成教学回复"""
    last_msg = state["messages"][-1].content if state["messages"] else ""
    result = await agenerate_reply(
        message=last_msg,
        subject=state.get("subject") or "未知学科",
        chapter=state.get("chapter") or "未知章节",
        lesson=get_lesson_name(state.get("lesson")),
        docs=state.get("retrieved_docs", []),
    )
    ai_msg = AIMessage(content=result["reply"])
    return {
        "reply": result["reply"],
        "suggested_actions": result["suggested_actions"],
        "messages": [ai_msg],
    }


def quiz_node(state: AgentState) -> dict:
    """生成测验题"""
    docs = state.get("retrieved_docs", [])
    quiz = generate_quiz(
        subject=state.get("subject") or "未知学科",
        chapter=state.get("chapter") or "未知章节",
        lesson=get_lesson_name(state.get("lesson")),
        docs=docs,
        difficulty="基础",
        question_type="选择",
    )
    reply_text = f"📝 测验题\n\n{quiz['question']}\n\n（请作答后，我会为你解析）"
    ai_msg = AIMessage(content=reply_text)
    return {
        "reply": reply_text,
        "quiz_result": quiz,
        "suggested_actions": ["查看解析", "再来一题", "继续学习"],
        "messages": [ai_msg],
    }


def chat_node(state: AgentState) -> dict:
    """自由聊天回复"""
    subject_name = state.get("subject") or "未选择课程"
    reply = (
        f"你好！我是你的AI学习助手。\n\n"
        f"你可以这样跟我互动：\n"
        f"• 📖 「给我讲解第一章」—— 系统教学\n"
        f"• ❓ 「什么是绝对值」—— 知识问答\n"
        f"• ✏️ 「出道题考考我」—— 随堂测验\n"
        f"• 📝 「总结一下重点」—— 知识总结\n\n"
        f"当前课程：{subject_name}"
    )
    ai_msg = AIMessage(content=reply)
    return {
        "reply": reply,
        "suggested_actions": ["给我讲解这个单元", "出道题考考我", "总结一下重点"],
        "messages": [ai_msg],
    }


# ---------- 条件路由 ----------

def route_by_intent(state: AgentState) -> str:
    intent = state.get("intent", "自由聊天")
    logger.info("路由决策: intent=%s", intent)
    if intent == "测验请求":
        return "quiz"
    elif intent in ("知识问答", "课程讲解"):
        return "retrieve"
    else:
        return "chat"


# ---------- 构建工作流 ----------

builder = StateGraph(AgentState)
builder.add_node("intent", intent_node)
builder.add_node("retrieve", retrieve_node)
builder.add_node("reply", reply_node)
builder.add_node("quiz", quiz_node)
builder.add_node("chat", chat_node)

builder.set_entry_point("intent")
builder.add_conditional_edges(
    "intent",
    route_by_intent,
    {
        "retrieve": "retrieve",
        "quiz": "quiz",
        "chat": "chat",
    },
)
builder.add_edge("retrieve", "reply")
builder.add_edge("reply", END)
builder.add_edge("quiz", END)
builder.add_edge("chat", END)

agent = builder.compile()
