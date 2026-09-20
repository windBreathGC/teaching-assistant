from pathlib import Path
from pydantic_settings import BaseSettings
from functools import lru_cache

_ROOT_ENV = Path(__file__).parent.parent.parent.parent / ".env"


class Settings(BaseSettings):
    APP_NAME: str = "中学伴学助教"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True

    BACKEND_PORT: int = 8000
    FRONTEND_PORT: int = 5173

    @property
    def CORS_ORIGINS(self) -> list[str]:
        return [
            f"http://localhost:{self.FRONTEND_PORT}",
            f"http://127.0.0.1:{self.FRONTEND_PORT}",
        ]

    # 管理接口令牌（X-Admin-Token 头）。为空时管理接口无鉴权（仅限本地开发），
    # 生产环境必须设置，否则任何人可操作模型配置、触发付费向量化任务。
    ADMIN_TOKEN: str = ""

    # LLM
    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    LLM_MODEL: str = "gpt-4o-mini"
    EMBEDDING_MODEL: str = "text-embedding-3-small"

    # Vector DB
    CHROMA_PERSIST_DIR: str = "./chroma_db"

    # Data
    TEXTBOOK_DIR: str = "../textbook"

    # bge-large-zh 等模型上限 512 tokens（中文 1 字 ≈ 1 token），超限会被拒绝，留安全边际
    MAX_CHUNK_CHARS: int = 480

    # RAG 检索充分性阈值：向量路 l2 距离，top1 超过该值视为"教材中未找到足够依据"，
    # reply 走兜底提示分支。依 embedding 模型分布而异，需结合 INFO 日志中的 top1 距离调参
    RAG_DISTANCE_THRESHOLD: float = 1.2

    # 发给 LLM 的对话历史窗口（条数，约条数/2 轮问答），控制 prompt token
    HISTORY_MAX_MESSAGES: int = 12

    # Langfuse 可观测性（远端服务）。密钥留空时自动关闭，全部埋点退化为 no-op
    LANGFUSE_PUBLIC_KEY: str = ""
    LANGFUSE_SECRET_KEY: str = ""
    LANGFUSE_HOST: str = "https://cloud.langfuse.com"  # 自托管时改为你的服务地址
    LANGFUSE_ENABLED: bool = True

    # LLM 韧性：重试 / 熔断 / 限流
    # openai SDK 层对 429/超时/连接失败/5xx 的自动重试次数（指数退避，封顶防 retry storm）
    LLM_MAX_RETRIES: int = 3
    # 连续瞬时故障达到该次数后熔断 fail-fast；冷却期后半开试探，成功自动恢复
    LLM_CIRCUIT_FAILURE_THRESHOLD: int = 3
    LLM_CIRCUIT_RECOVERY_SECONDS: float = 60
    # 对话接口按 session 滑动窗口限流（防误触连发/脚本刷量打爆供应商配额）
    CHAT_RATE_LIMIT_MAX_CALLS: int = 20
    CHAT_RATE_LIMIT_WINDOW_SECONDS: float = 60

    class Config:
        env_file = str(_ROOT_ENV)
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    return Settings()
