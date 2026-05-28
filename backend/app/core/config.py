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
    def CORS_ORIGINS(self) -> str:
        return f"http://localhost:{self.FRONTEND_PORT},http://127.0.0.1:{self.FRONTEND_PORT}"

    # LLM
    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    LLM_MODEL: str = "gpt-4o-mini"
    EMBEDDING_MODEL: str = "text-embedding-3-small"

    # Vector DB
    CHROMA_PERSIST_DIR: str = "./chroma_db"

    # Data
    TEXTBOOK_DIR: str = "../textbook"

    class Config:
        env_file = str(_ROOT_ENV)
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    return Settings()
