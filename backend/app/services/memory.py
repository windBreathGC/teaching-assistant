"""对话记忆：LangGraph checkpointer 装配 + 历史裁剪策略。

- checkpointer（AsyncSqliteSaver）：会话级短期记忆，按 thread_id 持久化
  messages / quiz_result 等状态，支撑多轮对话与"聊天内作答判分"。
  连接生命周期与 app 一致（在 main.py lifespan 的 async with 中持有）。
- trim_messages：裁剪策略（发给 LLM 的窗口），与持久化机制解耦，可独立替换。
"""
import logging

from langchain_core.messages import BaseMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.core.config import get_settings
from app.db.base import DATA_DIR

logger = logging.getLogger(__name__)
settings = get_settings()

CHECKPOINT_DB = DATA_DIR / "checkpoints.db"


def create_checkpointer() -> AsyncSqliteSaver:
    """创建 checkpointer 上下文管理器（在 lifespan 中 `async with` 持有）。

    用法：
        async with create_checkpointer() as checkpointer:
            agent = build_agent(checkpointer)
            ...
    """
    return AsyncSqliteSaver.from_conn_string(str(CHECKPOINT_DB))


def trim_messages(messages: list[BaseMessage], max_turns: int | None = None) -> list[BaseMessage]:
    """裁剪发给 LLM 的历史：保留最近 max_turns 条消息（约 max_turns/2 轮问答）。

    只控制 prompt 窗口，不影响 checkpointer 中的完整会话状态。
    """
    limit = max_turns or settings.HISTORY_MAX_MESSAGES
    return messages[-limit:] if len(messages) > limit else messages
