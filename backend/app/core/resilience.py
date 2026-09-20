"""LLM 调用的韧性层：错误分类、熔断、限流。

设计动机：LLM 供应商的故障分两类——
- 瞬时故障（429 限流、超时、连接失败、5xx）：供应商过载，稍后自愈。
  值得 SDK 层有限重试；持续发生时熔断 fail-fast，避免用户白等 + 重试加剧拥塞；
- 永久错误（400 参数错误、401 鉴权失败）：重试无意义，按普通异常暴露。

三个组件：
- is_transient_llm_error：区分两类故障，决定提示语、HTTP 状态码与是否计入熔断；
- CircuitBreaker：连续瞬时故障达阈值后开启，冷却期内直接拒绝请求（不调供应商），
  冷却后半开试探，成功即恢复闭合；
- RateLimiter：按 session 滑动窗口限流，防误触/脚本刷量打爆供应商配额。
"""
import logging
import threading
import time
from collections import deque

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# 瞬时故障时面向用户的统一提示
BUSY_MESSAGE = "模型繁忙，请稍后重试"
# 触发限流时面向用户的统一提示
RATE_LIMIT_MESSAGE = "提问过于频繁，请稍等片刻"


def is_transient_llm_error(exc: BaseException) -> bool:
    """判定是否为 LLM 供应商侧的瞬时故障（限流/超时/连接失败/5xx）。"""
    try:
        import openai
    except ImportError:  # pragma: no cover
        return False
    return isinstance(exc, (
        openai.RateLimitError,
        openai.APITimeoutError,
        openai.APIConnectionError,
        openai.InternalServerError,
    ))


class CircuitBreaker:
    """针对 LLM 供应商的简易熔断器（线程安全）。

    状态机：
        closed ──连续 transient 失败达阈值──▶ open（fail-fast，不调供应商）
        open ──冷却时间到──▶ half-open（放行一次试探）
        half-open ──试探成功──▶ closed；试探失败──▶ open（重新冷却）
    """

    def __init__(self, failure_threshold: int, recovery_seconds: float):
        self._failure_threshold = failure_threshold
        self._recovery_seconds = recovery_seconds
        self._failures = 0
        self._opened_at: float | None = None
        self._lock = threading.Lock()

    def allow_request(self) -> bool:
        """请求前调用：熔断开启且未过冷却期时返回 False（fail-fast）。"""
        with self._lock:
            if self._opened_at is None:
                return True
            # 冷却期到：进入半开，放行试探请求（由其结果决定闭合或重新熔断）
            return time.monotonic() - self._opened_at >= self._recovery_seconds

    def record_success(self) -> None:
        with self._lock:
            if self._opened_at is not None:
                logger.info("LLM 熔断器恢复闭合：试探请求成功")
            self._failures = 0
            self._opened_at = None

    def record_failure(self, exc: BaseException) -> None:
        """仅瞬时故障计入熔断；永久错误（代码 bug、参数错误）不熔断，
        否则一个坏请求会把所有用户挡在门外。"""
        if not is_transient_llm_error(exc):
            return
        with self._lock:
            self._failures += 1
            if self._failures >= self._failure_threshold and self._opened_at is None:
                self._opened_at = time.monotonic()
                logger.warning(
                    "LLM 熔断器开启：连续 %d 次供应商瞬时故障，%.0f 秒内 fail-fast",
                    self._failures, self._recovery_seconds,
                )


class RateLimiter:
    """按 key 的滑动窗口限流器（线程安全，内存实现，单机部署适用）。"""

    def __init__(self, max_calls: int, window_seconds: float):
        self._max_calls = max_calls
        self._window = window_seconds
        self._hits: dict[str, deque] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and now - hits[0] >= self._window:
                hits.popleft()
            if len(hits) >= self._max_calls:
                return False
            hits.append(now)
            return True


_settings = get_settings()

# LLM 供应商熔断器：对话/出题/判分等交互链路共用
llm_circuit = CircuitBreaker(
    failure_threshold=_settings.LLM_CIRCUIT_FAILURE_THRESHOLD,
    recovery_seconds=_settings.LLM_CIRCUIT_RECOVERY_SECONDS,
)

# 对话接口限流器：按 session_id 计，防误触连发/脚本刷量
chat_rate_limiter = RateLimiter(
    max_calls=_settings.CHAT_RATE_LIMIT_MAX_CALLS,
    window_seconds=_settings.CHAT_RATE_LIMIT_WINDOW_SECONDS,
)
