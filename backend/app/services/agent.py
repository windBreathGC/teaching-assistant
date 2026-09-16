"""LangGraph 智能体工作流编排

工作流：intent → 条件路由 → retrieve/reply、quiz、grade、progress、chat 分支。
通过 build_agent(checkpointer) 工厂装配：传入 AsyncSqliteSaver 即可按 thread_id
持久化会话状态（多轮记忆 + 聊天内"我选B"作答判分的前提）。
模块级的 `agent` 为无 checkpointer 的兼容默认（不跨轮记忆），仅作兜底。
"""
import asyncio
import logging
from typing import TypedDict, Annotated
from langchain_core.messages import BaseMessage, AIMessage
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages

from app.services.intent import classify_intent
from app.services.rag import aretrieve_checked, get_lesson_name, resolve_subject_name
from app.services.teaching import agenerate_reply, generate_quiz, arender_progress_report
from app.services.citations import to_references
from app.services.memory import trim_messages
from app.services import grading, learner_repo

logger = logging.getLogger(__name__)


class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    subject: str | None
    chapter: str | None
    lesson: str | None
    intent: str
    retrieved_docs: list[dict]
    references: list[dict]
    retrieval_ok: bool
    reply: str
    suggested_actions: list[str]
    quiz_result: dict | None       # {"quiz_id": ...}，跨轮存活的待作答题目
    grade_result: dict | None
    progress_report: dict | None


# ---------- 节点函数（只返回需要更新的字段） ----------

def intent_node(state: AgentState) -> dict:
    """识别用户意图"""
    last_msg = state["messages"][-1].content if state["messages"] else ""
    intent = classify_intent(last_msg)
    return {"intent": intent}


async def retrieve_node(state: AgentState) -> dict:
    """RAG检索（含充分性判定与引用溯源）"""
    last_msg = state["messages"][-1].content if state["messages"] else ""
    lesson_name = get_lesson_name(state.get("lesson"))
    query = f"{lesson_name} {last_msg}" if lesson_name else last_msg
    result = await aretrieve_checked(
        query=query,
        subject=state.get("subject"),
        lesson=state.get("lesson"),
        top_k=2,
    )
    docs = result["docs"]
    logger.info("检索到 %d 条知识 (sufficient=%s)", len(docs), result["sufficient"])
    return {
        "retrieved_docs": docs,
        "retrieval_ok": result["sufficient"],
        "references": to_references(docs),
    }


async def reply_node(state: AgentState) -> dict:
    """生成教学回复（注入多轮历史与检索充分性）"""
    messages = state["messages"]
    last_msg = messages[-1].content if messages else ""
    # 历史不含当前这条问题本身，裁剪到配置窗口控制 token
    history = trim_messages(messages[:-1])
    result = await agenerate_reply(
        message=last_msg,
        subject=state.get("subject") or "未知学科",
        chapter=state.get("chapter") or "未知章节",
        lesson=get_lesson_name(state.get("lesson")),
        docs=state.get("retrieved_docs", []),
        history=history,
        retrieval_ok=state.get("retrieval_ok", True),
    )
    ai_msg = AIMessage(content=result["reply"])
    return {
        "reply": result["reply"],
        "suggested_actions": result["suggested_actions"],
        "messages": [ai_msg],
    }


async def quiz_node(state: AgentState) -> dict:
    """生成测验题并落库（quiz_id 跨轮存活，支撑"我选B"作答判分）"""
    quiz = await asyncio.to_thread(
        generate_quiz,
        subject=state.get("subject") or "未知学科",
        chapter=state.get("chapter") or "",   # 留空让 generate_quiz 回退到"通用知识点"
        lesson=get_lesson_name(state.get("lesson")),
        docs=state.get("retrieved_docs", []),
        difficulty="基础",
        question_type="选择",
    )
    quiz_id = await learner_repo.create_attempt(
        subject=state.get("subject") or "未知学科",
        chapter=state.get("chapter"),
        lesson=state.get("lesson"),
        quiz=quiz,
        difficulty="基础",
        question_type="选择",
    )
    options_text = ""
    if quiz.get("options"):
        options_text = "\n\n" + "\n".join(
            f"{chr(65 + i)}. {opt}" for i, opt in enumerate(quiz["options"])
        )
    reply_text = f"📝 测验题\n\n{quiz['question']}{options_text}\n\n（请直接回复你的答案，如：我选A）"
    ai_msg = AIMessage(content=reply_text)
    return {
        "reply": reply_text,
        "quiz_result": {"quiz_id": quiz_id},
        "suggested_actions": ["我选A", "我选B", "再来一题"],
        "messages": [ai_msg],
    }


async def grade_node(state: AgentState) -> dict:
    """作答判分：取出待作答题目，判分 + 错因诊断 + 更新掌握度"""
    last_msg = state["messages"][-1].content if state["messages"] else ""
    quiz = state.get("quiz_result") or {}
    quiz_id = quiz.get("quiz_id")

    if not quiz_id:
        reply = "你还没有待作答的题目哦～先让我出一道题吧！"
        return {
            "reply": reply,
            "grade_result": None,
            "suggested_actions": ["出道题考考我"],
            "messages": [AIMessage(content=reply)],
        }

    attempt = await learner_repo.get_attempt(quiz_id)
    if attempt is None:
        reply = "这道题找不到了，我们重新出一道吧～"
        return {
            "reply": reply,
            "quiz_result": None,
            "grade_result": None,
            "suggested_actions": ["出道题考考我"],
            "messages": [AIMessage(content=reply)],
        }

    if attempt["status"] == "submitted":
        verdict = "✅ 回答正确" if attempt["is_correct"] else "❌ 回答错误"
        reply = f"这道题你已经作答过了：{verdict}\n\n**正确答案**：{attempt['correct_answer']}"
        return {
            "reply": reply,
            "quiz_result": None,
            "grade_result": None,
            "suggested_actions": ["再来一题", "出道题考考我"],
            "messages": [AIMessage(content=reply)],
        }

    grade = await grading.grade_answer(
        question=attempt["question"],
        options=attempt["options"],
        correct_answer=attempt["correct_answer"],
        explanation=attempt["explanation"],
        user_answer=last_msg,
        question_type=attempt["question_type"],
    )
    result = await learner_repo.submit_attempt(quiz_id, last_msg, grade)
    mastery = (result or {}).get("mastery")

    reply = _render_grade_reply(attempt, grade, mastery)
    return {
        "reply": reply,
        "quiz_result": None,          # 清除待作答题目
        "grade_result": {**grade, "knowledge_point": attempt["knowledge_point"]},
        "suggested_actions": ["再来一题", "出道题考考我", "我的学习进度怎么样"],
        "messages": [AIMessage(content=reply)],
    }


def _render_grade_reply(attempt: dict, grade: dict, mastery: dict | None) -> str:
    """把判分结果渲染成教师口吻的 Markdown 回复。"""
    parts = ["✅ 回答正确！很棒！" if grade["is_correct"] else "❌ 回答错误，别灰心，我们一起来看看。"]
    parts.append(f"\n**正确答案**：{attempt['correct_answer']}")
    if grade.get("misconception"):
        parts.append(f"\n**错因标签**：{grade['misconception']}")
    if grade.get("diagnosis"):
        parts.append(f"\n**错因诊断**：{grade['diagnosis']}")
    if attempt.get("explanation"):
        parts.append(f"\n**解析**：{attempt['explanation']}")
    if mastery:
        pct = round(mastery["mastery"] * 100)
        parts.append(f"\n**知识点「{mastery['knowledge_point']}」掌握度**：{pct}%"
                     f"（{mastery['correct_attempts']}/{mastery['total_attempts']} 题正确）")
    return "\n".join(parts)


async def progress_node(state: AgentState) -> dict:
    """学情查询：聚合学习数据，LLM 包装成教师口吻的报告（astream 真流式）"""
    subject = state.get("subject") or ""
    subject_name = resolve_subject_name(subject) if subject else "当前课程"
    report = await learner_repo.get_subject_report(subject)
    text = await arender_progress_report(report, subject_name)
    return {
        "reply": text,
        "progress_report": report,
        "suggested_actions": ["出道题考考我", "给我讲解薄弱知识点", "总结一下重点"],
        "messages": [AIMessage(content=text)],
    }


def chat_node(state: AgentState) -> dict:
    """自由聊天回复"""
    subject_name = resolve_subject_name(state.get("subject")) if state.get("subject") else "未选择课程"
    reply = (
        f"你好！我是你的AI学习助手。\n\n"
        f"你可以这样跟我互动：\n"
        f"• 📖 「给我讲解第一章」—— 系统教学\n"
        f"• ❓ 「什么是绝对值」—— 知识问答\n"
        f"• ✏️ 「出道题考考我」—— 随堂测验（答完我帮你判分）\n"
        f"• 📊 「我的学习进度怎么样」—— 学情报告\n"
        f"• 📝 「总结一下重点」—— 知识总结\n\n"
        f"当前课程：{subject_name}"
    )
    ai_msg = AIMessage(content=reply)
    return {
        "reply": reply,
        "suggested_actions": ["给我讲解这个单元", "出道题考考我", "我的学习进度怎么样"],
        "messages": [ai_msg],
    }


# ---------- 条件路由 ----------

def route_by_intent(state: AgentState) -> str:
    intent = state.get("intent", "自由聊天")
    logger.info("路由决策: intent=%s", intent)
    if intent == "作答判分":
        return "grade"
    elif intent == "进度查询":
        return "progress"
    elif intent in ("知识问答", "课程讲解", "测验请求"):
        # 测验也先走检索：出题必须基于教材内容，不能脱离课文自由发挥
        return "retrieve"
    else:
        return "chat"


def route_after_retrieve(state: AgentState) -> str:
    """检索后的分流：测验意图去出题，其余去生成教学回复"""
    return "quiz" if state.get("intent") == "测验请求" else "reply"


# ---------- 构建工作流 ----------

def build_agent(checkpointer=None):
    """工厂函数：装配并编译工作流。

    传入 checkpointer（AsyncSqliteSaver）即开启会话级持久化记忆；
    需要在 async 资源就绪后调用（main.py lifespan），故不能在模块顶层编译。
    """
    builder = StateGraph(AgentState)
    builder.add_node("intent", intent_node)
    builder.add_node("retrieve", retrieve_node)
    builder.add_node("reply", reply_node)
    builder.add_node("quiz", quiz_node)
    builder.add_node("grade", grade_node)
    builder.add_node("progress", progress_node)
    builder.add_node("chat", chat_node)

    builder.set_entry_point("intent")
    builder.add_conditional_edges(
        "intent",
        route_by_intent,
        {
            "retrieve": "retrieve",
            "grade": "grade",
            "progress": "progress",
            "chat": "chat",
        },
    )
    builder.add_conditional_edges(
        "retrieve",
        route_after_retrieve,
        {
            "quiz": "quiz",
            "reply": "reply",
        },
    )
    builder.add_edge("reply", END)
    builder.add_edge("quiz", END)
    builder.add_edge("grade", END)
    builder.add_edge("progress", END)
    builder.add_edge("chat", END)

    return builder.compile(checkpointer=checkpointer)


# 无 checkpointer 的兼容默认（不跨轮记忆），仅在 lifespan 装配失败等场景兜底
agent = build_agent()
