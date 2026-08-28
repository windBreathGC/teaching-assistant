import json
import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage
from app.models.schemas import ChatRequest, ChatResponse, QuizRequest, QuizResponse
from app.services.agent import agent
from app.services.rag import aretrieve, get_lesson_name
from app.services.teaching import _extract_text, generate_quiz, parse_quiz_output, stream_quiz

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
    """对话接口（SSE 流式，token 级实时返回）。

    与 POST /chat 共用同一个 LangGraph 工作流：通过 astream_events 把图内
    reply 节点的 LLM token 事件（on_chat_model_stream）实时转发为 SSE；
    quiz/chat 分支无 LLM 流，节点完成后一次性下发其文本。"""
    async def event_generator():
        try:
            messages = []
            for m in request.history or []:
                if m.get("role") == "user":
                    messages.append(HumanMessage(content=m["content"]))
            messages.append(HumanMessage(content=request.message))

            initial_state = {
                "messages": messages,
                "subject": request.subject,
                "chapter": request.chapter,
                "lesson": request.lesson,
                "intent": "自由聊天",
                "retrieved_docs": [],
                "reply": "",
                "suggested_actions": [],
                "quiz_result": None,
            }

            final_reply = ""
            suggested_actions: list[str] = []

            async for ev in agent.astream_events(initial_state, version="v2"):
                kind = ev["event"]
                name = ev.get("name", "")
                # 节点内子链（prompt|llm 等）会继承 langgraph_node 元数据，
                # 必须以事件名精确匹配节点本身，避免把子链输出当成节点结果
                node = ev.get("metadata", {}).get("langgraph_node", "")
                is_node_end = kind == "on_chain_end" and name == node

                # 意图识别完成 → 下发 intent 事件
                if is_node_end and node == "intent":
                    intent = (ev["data"].get("output") or {}).get("intent", "自由聊天")
                    yield f"data: {json.dumps({'type': 'intent', 'intent': intent})}\n\n"

                # reply 节点内 LLM 的逐 token 事件 → 实时转发
                elif kind == "on_chat_model_stream" and node == "reply":
                    text = _extract_text(ev["data"]["chunk"])
                    if text:
                        yield f"data: {json.dumps({'type': 'token', 'content': text})}\n\n"

                # quiz/chat 分支没有 LLM 流，节点完成后一次性下发文本
                elif is_node_end and node in ("quiz", "chat"):
                    text = (ev["data"].get("output") or {}).get("reply", "")
                    if text:
                        yield f"data: {json.dumps({'type': 'token', 'content': text})}\n\n"

                # 终态节点完成 → 记录权威结果，done 事件以此为准（而非本地拼接）
                if is_node_end and node in ("reply", "quiz", "chat"):
                    output = ev["data"].get("output") or {}
                    final_reply = output.get("reply", final_reply)
                    suggested_actions = output.get("suggested_actions", suggested_actions)

            yield f"data: {json.dumps({'type': 'done', 'reply': final_reply, 'suggested_actions': suggested_actions[:3]})}\n\n"

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
