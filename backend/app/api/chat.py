import json
import logging
import uuid

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage
from app.models.schemas import (
    ChatRequest, ChatResponse, QuizRequest, QuizResponse,
    QuizSubmitRequest, QuizGradeResponse,
)
from app.services.agent import agent as fallback_agent
from app.services.rag import aretrieve, get_lesson_name
from app.services.teaching import _extract_text, generate_quiz, parse_quiz_output, stream_quiz
from app.services import grading, learner_repo

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chat", tags=["chat"])

# 终态节点集合：这些节点的 on_chain_end 输出作为 done 事件的权威结果
_TERMINAL_NODES = ("reply", "quiz", "chat", "grade", "progress")


def _get_agent(request: Request):
    """优先使用 lifespan 装配的带 checkpointer 的工作流（多轮记忆），缺失时兜底无记忆版。"""
    return getattr(request.app.state, "agent", None) or fallback_agent


def _initial_state(request: ChatRequest) -> dict:
    """构造每轮对话的输入状态。

    历史消息由 checkpointer 按 thread_id 自动续接，这里只放本轮新消息；
    每轮会被覆盖的字段显式重置，避免陈旧值残留；quiz_result 故意不传，
    让待作答题目跨轮存活（支撑"我选B"作答判分）。
    subject/chapter/lesson 仅在请求携带时传入，否则沿用 checkpoint 旧值，
    避免某轮未携带时把上下文覆盖成 None 污染后续轮次。
    """
    state = {
        "messages": [HumanMessage(content=request.message)],
        "intent": "自由聊天",
        "retrieved_docs": [],
        "references": [],
        "retrieval_ok": True,
        "reply": "",
        "suggested_actions": [],
        "grade_result": None,
        "progress_report": None,
    }
    if request.subject is not None:
        state["subject"] = request.subject
    if request.chapter is not None:
        state["chapter"] = request.chapter
    if request.lesson is not None:
        state["lesson"] = request.lesson
    return state


@router.post("", response_model=ChatResponse)
async def chat(request: ChatRequest, http_request: Request):
    """对话接口（原生异步，非流式）"""
    session_id = request.session_id or uuid.uuid4().hex
    config = {"configurable": {"thread_id": session_id}}
    try:
        result = await _get_agent(http_request).ainvoke(_initial_state(request), config=config)

        return ChatResponse(
            reply=result.get("reply", ""),
            intent=result.get("intent"),
            session_id=session_id,
            references=result.get("references", []),
            suggested_actions=result.get("suggested_actions", []),
        )
    except Exception as e:
        logger.error("对话处理失败: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="智能体处理失败，请稍后重试")


@router.post("/stream")
async def chat_stream(request: ChatRequest, http_request: Request):
    """对话接口（SSE 流式，token 级实时返回）。

    与 POST /chat 共用同一个 LangGraph 工作流：通过 astream_events 把图内
    reply/progress 节点的 LLM token 事件（on_chat_model_stream）实时转发为 SSE；
    quiz/grade/chat 分支无 LLM 流，节点完成后一次性下发其文本。
    retrieve 节点完成后先下发 references 事件（教材出处 + 检索充分性）。"""
    session_id = request.session_id or uuid.uuid4().hex
    config = {"configurable": {"thread_id": session_id}}
    agent = _get_agent(http_request)

    async def event_generator():
        try:
            final_reply = ""
            suggested_actions: list[str] = []
            references: list[dict] = []
            retrieval_ok = True

            async for ev in agent.astream_events(_initial_state(request), version="v2", config=config):
                kind = ev["event"]
                name = ev.get("name", "")
                # 节点内子链（prompt|llm 等）会继承 langgraph_node 元数据，
                # 必须以事件名精确匹配节点本身，避免把子链输出当成节点结果
                node = ev.get("metadata", {}).get("langgraph_node", "")
                is_node_end = kind == "on_chain_end" and name == node

                # 意图识别完成 → 下发 intent 事件
                if is_node_end and node == "intent":
                    intent = (ev["data"].get("output") or {}).get("intent", "自由聊天")
                    yield f"data: {json.dumps({'type': 'intent', 'intent': intent}, ensure_ascii=False)}\n\n"

                # 检索完成 → 先下发教材出处与充分性（前端可提前展示引用）
                elif is_node_end and node == "retrieve":
                    output = ev["data"].get("output") or {}
                    references = output.get("references", [])
                    retrieval_ok = output.get("retrieval_ok", True)
                    yield f"data: {json.dumps({'type': 'references', 'references': references, 'retrieval_ok': retrieval_ok}, ensure_ascii=False)}\n\n"

                # reply/progress 节点内 LLM 的逐 token 事件 → 实时转发
                elif kind == "on_chat_model_stream" and node in ("reply", "progress"):
                    text = _extract_text(ev["data"]["chunk"])
                    if text:
                        yield f"data: {json.dumps({'type': 'token', 'content': text}, ensure_ascii=False)}\n\n"

                # quiz/grade/chat 分支没有 LLM 流，节点完成后一次性下发文本
                elif is_node_end and node in ("quiz", "grade", "chat"):
                    text = (ev["data"].get("output") or {}).get("reply", "")
                    if text:
                        yield f"data: {json.dumps({'type': 'token', 'content': text}, ensure_ascii=False)}\n\n"

                # 终态节点完成 → 记录权威结果，done 事件以此为准（而非本地拼接）
                if is_node_end and node in _TERMINAL_NODES:
                    output = ev["data"].get("output") or {}
                    final_reply = output.get("reply", final_reply)
                    suggested_actions = output.get("suggested_actions", suggested_actions)

            yield f"data: {json.dumps({'type': 'done', 'reply': final_reply, 'suggested_actions': suggested_actions[:3], 'references': references, 'retrieval_ok': retrieval_ok, 'session_id': session_id}, ensure_ascii=False)}\n\n"

        except Exception as e:
            logger.error("流式对话失败: %s", e, exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'detail': '服务处理失败，请稍后重试'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
    )


@router.post("/quiz", response_model=QuizResponse)
async def generate_quiz_endpoint(request: QuizRequest):
    """生成测验题（落库并返回 quiz_id，供提交答案判分关联）"""
    try:
        docs = await aretrieve(
            query=f"{request.subject} {request.chapter or ''} {request.lesson or ''} 知识点",
            subject=request.subject,
            lesson=request.lesson,
            top_k=2,
        )
        quiz = generate_quiz(
            subject=request.subject,
            chapter=request.chapter or "",
            lesson=request.lesson,
            docs=docs,
            difficulty=request.difficulty,
            question_type=request.question_type,
        )
        quiz_id = await learner_repo.create_attempt(
            subject=request.subject,
            chapter=request.chapter,
            lesson=request.lesson,
            quiz=quiz,
            difficulty=request.difficulty,
            question_type=request.question_type,
        )
        return QuizResponse(
            question=quiz["question"],
            options=None,
            correct_answer=quiz["correct_answer"],
            explanation=quiz["explanation"],
            knowledge_point=quiz["knowledge_point"],
            quiz_id=quiz_id,
        )
    except Exception as e:
        logger.error("出题失败: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="出题失败，请稍后重试")


@router.post("/quiz/stream")
async def generate_quiz_stream(request: QuizRequest):
    """流式生成测验题（SSE），done 事件携带 quiz_id 供提交判分"""
    async def event_generator():
        try:
            docs = await aretrieve(
                query=f"{request.subject} {request.chapter or ''} {request.lesson or ''} 知识点",
                subject=request.subject,
                lesson=request.lesson,
                top_k=2,
            )

            full_question = ""
            async for token in stream_quiz(
                subject=request.subject,
                chapter=request.chapter or "",
                lesson=get_lesson_name(request.lesson),
                docs=docs,
                difficulty=request.difficulty,
                question_type=request.question_type,
            ):
                full_question += token
                yield f"data: {json.dumps({'type': 'token', 'content': token}, ensure_ascii=False)}\n\n"

            parsed = parse_quiz_output(full_question)
            quiz = {
                "question": parsed["question"],
                "options": parsed["options"],
                "correct_answer": parsed["correct_answer"],
                "explanation": parsed["explanation"],
                "knowledge_point": request.chapter or "通用知识点",
            }
            quiz_id = await learner_repo.create_attempt(
                subject=request.subject,
                chapter=request.chapter,
                lesson=request.lesson,
                quiz=quiz,
                difficulty=request.difficulty,
                question_type=request.question_type,
            )
            yield f"data: {json.dumps({'type': 'done', **quiz, 'quiz_id': quiz_id}, ensure_ascii=False)}\n\n"

        except Exception as e:
            logger.error("流式出题失败: %s", e, exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'detail': '服务处理失败，请稍后重试'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
    )


@router.post("/quiz/submit", response_model=QuizGradeResponse)
async def submit_quiz(request: QuizSubmitRequest):
    """提交答案判分：选择题本地比对，填空/简答 LLM 判分 + 错因诊断，并更新掌握度。

    幂等：同一 quiz_id 重复提交直接返回首次判分结果，不重复刷掌握度。"""
    try:
        attempt = await learner_repo.get_attempt(request.quiz_id)
        if attempt is None:
            raise HTTPException(status_code=404, detail="题目不存在或已过期")

        if attempt["status"] == "submitted":
            # 幂等路径：复用已落库的判分结果，仅补取掌握度
            result = await learner_repo.submit_attempt(request.quiz_id, request.user_answer, {
                "is_correct": attempt["is_correct"],
                "score": attempt["score"] or 0.0,
                "misconception": attempt["misconception"],
                "diagnosis": attempt["diagnosis"] or "",
            })
        else:
            grade = await grading.grade_answer(
                question=attempt["question"],
                options=attempt["options"],
                correct_answer=attempt["correct_answer"],
                explanation=attempt["explanation"],
                user_answer=request.user_answer,
                question_type=attempt["question_type"],
            )
            result = await learner_repo.submit_attempt(request.quiz_id, request.user_answer, grade)

        if result is None:
            raise HTTPException(status_code=404, detail="题目不存在或已过期")
        graded = result["attempt"]
        return QuizGradeResponse(
            quiz_id=request.quiz_id,
            is_correct=bool(graded["is_correct"]),
            correct_answer=graded["correct_answer"],
            explanation=graded["explanation"],
            diagnosis=graded["diagnosis"] or "",
            misconception=graded["misconception"],
            knowledge_point=graded["knowledge_point"],
            mastery=result.get("mastery"),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("判分失败: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="判分失败，请稍后重试")
