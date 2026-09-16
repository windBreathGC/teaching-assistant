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

    class Config:
        env_file = str(_ROOT_ENV)
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    return Settings()
