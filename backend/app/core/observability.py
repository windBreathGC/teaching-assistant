"""Langfuse 可观测性接入（SDK v3+/v4，基于 OpenTelemetry）。

设计要点：
- 密钥未配置时所有能力自动降级为 no-op，业务模块无需关心 Langfuse 是否启用；
- LangChain/LangGraph 流量通过 CallbackHandler（挂在 RunnableConfig.callbacks）自动记录
  prompt、completion、token 用量与耗时；
- 非 LangChain 代码（RAG 检索、后台任务）用 observe 装饰器埋 span，
  与 callback 产生的 span 基于 OTel 上下文嵌套进同一条 trace；
- v3 事件走 OTLP 异步批量上报，进程退出或后台线程结束前必须 flush_langfuse()。
"""
import logging
import os
from contextlib import contextmanager
from functools import lru_cache

from app.core.config import get_settings

logger = logging.getLogger(__name__)


def langfuse_enabled() -> bool:
    s = get_settings()
    return bool(s.LANGFUSE_ENABLED and s.LANGFUSE_PUBLIC_KEY and s.LANGFUSE_SECRET_KEY)


def _apply_env() -> None:
    """把 Settings 写入 langfuse SDK 读取的环境变量（SDK 单例只认 env）。

    HOST 必须去掉末尾斜杠：SDK 直接拼接路径，双斜杠会触发服务端 308 跳转，
    经代理转发时跳转后的请求会 500。
    """
    s = get_settings()
    os.environ["LANGFUSE_PUBLIC_KEY"] = s.LANGFUSE_PUBLIC_KEY
    os.environ["LANGFUSE_SECRET_KEY"] = s.LANGFUSE_SECRET_KEY
    os.environ["LANGFUSE_HOST"] = s.LANGFUSE_HOST.rstrip("/")


@lru_cache
def get_langfuse_handler():
    """LangChain CallbackHandler 单例；未启用时返回 None。

    挂到 LangGraph/LangChain 调用的 config.callbacks 上即可自动追踪全图。
    """
    if not langfuse_enabled():
        return None
    _apply_env()
    from langfuse.langchain import CallbackHandler
    return CallbackHandler()


def callback_config(tags: list[str] | None = None, session_id: str | None = None,
                    trace_name: str | None = None) -> dict:
    """构造带 Langfuse callback 的 RunnableConfig 片段；未启用时返回空 dict（可直接作 config 传入）。

    trace_name 经 metadata.langfuse_trace_name 传递给 handler：当本次调用是 trace 根时
    （如无外层 span 包裹），Langfuse 用它命名整条 trace（默认取 Runnable 名，如 LangGraph）。
    """
    handler = get_langfuse_handler()
    if not handler:
        return {}
    metadata: dict = {"langfuse_tags": tags or []}
    if session_id:
        metadata["langfuse_session_id"] = session_id
    if trace_name:
        metadata["langfuse_trace_name"] = trace_name
    return {"callbacks": [handler], "metadata": metadata}


def observe(*args, **kwargs):
    """@observe 的安全包装：未启用时透传原函数，支持 @observe 与 @observe(...) 两种用法。"""
    if langfuse_enabled():
        _apply_env()
        from langfuse import observe as _observe
        return _observe(*args, **kwargs)
    if args and callable(args[0]) and not kwargs:
        return args[0]

    def _noop(func):
        return func

    return _noop


@contextmanager
def trace_span(name: str, as_type: str = "span", **kwargs):
    """开启一个 Langfuse 当前观测 span；未启用时退化为空上下文（yield None）。

    在 span 内执行的 LangChain 调用（config 带 callback）会嵌套进该 span 所属 trace，
    且 create_score 能定位到它。
    """
    if langfuse_enabled():
        _apply_env()
        from langfuse import get_client
        with get_client().start_as_current_observation(as_type=as_type, name=name, **kwargs) as span:
            yield span
    else:
        yield None


def create_score(name: str, value, data_type: str | None = None, comment: str | None = None) -> None:
    """向当前活动 trace 回写评分（如判分对错）；无活动 trace 或未启用时静默跳过。"""
    if not langfuse_enabled():
        return
    try:
        from langfuse import get_client
        client = get_client()
        # v4 SDK：get_current_trace_id 取代 v3 的 get_trace_context
        if not client.get_current_trace_id():
            return
        client.score_current_trace(name=name, value=value, data_type=data_type, comment=comment)
    except Exception as e:
        logger.warning("Langfuse 回写评分失败: %s", e)


def flush_langfuse() -> None:
    """排空 OTLP 上报队列。进程关闭、脚本或后台线程结束前必须调用，否则丢尾部数据。"""
    if not langfuse_enabled():
        return
    try:
        from langfuse import get_client
        get_client().flush()
    except Exception as e:
        logger.warning("Langfuse flush 失败: %s", e)
