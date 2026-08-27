import json
import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage
from app.models.schemas import ChatRequest, ChatResponse, QuizRequest, QuizResponse
from app.services.agent import agent
from app.services.intent import aclassify_intent
from app.services.rag import aretrieve, get_lesson_name
from app.services.teaching import generate_quiz, parse_quiz_output, stream_quiz, stream_reply

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """对话接口（原生异步，非流式）"""
    try:
        messages = []
        for m in request.history or []:
            if m.get("role") == "user":
                messages.append(HumanMessage(content=m["content"]))
        messages.append(HumanMessage(content=request.message))

        result = await agent.ainvoke({
            "messages": messages,
            "subject": request.subject,
            "chapter": request.chapter,
            "lesson": request.lesson,
            "intent": "自由聊天",
            "retrieved_docs": [],
            "reply": "",
            "suggested_actions": [],
            "quiz_result": None,
        })

        return ChatResponse(
            reply=result.get("reply", ""),
            intent=result.get("intent"),
            suggested_actions=result.get("suggested_actions", []),
        )
    except Exception as e:
        logger.error("对话处理失败: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="智能体处理失败，请稍后重试")


@router.post("/stream")
async def chat_stream(request: ChatRequest):
    """对话接口（SSE 流式，token 级实时返回）"""
    async def event_generator():
        try:
            # 1. 意图识别（异步，避免同步 LLM 调用阻塞事件循环）
            intent = await aclassify_intent(request.message)
            yield f"data: {json.dumps({'type': 'intent', 'intent': intent})}\n\n"

            # 2. 检索教材内容（讲解/问答场景）
            docs = []
            if intent in ("知识问答", "课程讲解"):
                lesson_name = get_lesson_name(request.lesson)
                query = f"{lesson_name} {request.message}" if lesson_name else request.message
                docs = await aretrieve(query=query, subject=request.subject, lesson=request.lesson, top_k=2)

            # 3. 流式生成回复（逐 token yield）
            full_reply = ""
            async for token in stream_reply(
                message=request.message,
                subject=request.subject or "未知学科",
                chapter=request.chapter or "未知章节",
                lesson=get_lesson_name(request.lesson),
                docs=docs,
            ):
                full_reply += token
                yield f"data: {json.dumps({'type': 'token', 'content': token})}\n\n"

            # 4. 建议操作
            suggested_actions = []
            if "例题" not in request.message and "题" not in request.message:
                suggested_actions.append("出道例题")
            if "总结" not in request.message:
                suggested_actions.append("总结重点")

            yield f"data: {json.dumps({'type': 'done', 'reply': full_reply, 'suggested_actions': suggested_actions[:3]})}\n\n"

        except Exception as e:
            logger.error("流式对话失败: %s", e, exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'detail': '服务处理失败，请稍后重试'})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
    )


@router.post("/quiz", response_model=QuizResponse)
async def generate_quiz_endpoint(request: QuizRequest):
    """生成测验题"""
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
        return QuizResponse(
            question=quiz["question"],
            options=None,
            correct_answer=quiz["correct_answer"],
            explanation=quiz["explanation"],
            knowledge_point=quiz["knowledge_point"],
        )
    except Exception as e:
        logger.error("出题失败: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="出题失败，请稍后重试")


@router.post("/quiz/stream")
async def generate_quiz_stream(request: QuizRequest):
    """流式生成测验题（SSE）"""
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
                yield f"data: {json.dumps({'type': 'token', 'content': token})}\n\n"

            parsed = parse_quiz_output(full_question)
            yield f"data: {json.dumps({'type': 'done', 'question': parsed['question'], 'options': parsed['options'], 'correct_answer': parsed['correct_answer'], 'explanation': parsed['explanation'], 'knowledge_point': request.chapter or '通用知识点'})}\n\n"

        except Exception as e:
            logger.error("流式出题失败: %s", e, exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'detail': '服务处理失败，请稍后重试'})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
    )
