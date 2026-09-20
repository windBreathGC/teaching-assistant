import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.core.config import get_settings
from app.core.observability import flush_langfuse
from app.api import health, subjects, chat, admin
from app.services.model_config_service import init_default_model_from_env
from app.services.agent import build_agent
from app.services.memory import create_checkpointer
from app.db import init_db, close_db

settings = get_settings()

# 应用生命周期管理
@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理，处理启动和关闭事件"""
    # 服务启动时：初始化数据库、创建默认模型
    await init_db()
    await init_default_model_from_env()
    # 装配带 checkpointer 的对话工作流（多轮记忆）：连接生命周期与 app 一致，
    # 必须在 lifespan 的 async with 中持有，请求间不可开关
    async with create_checkpointer() as checkpointer:
        app.state.agent = build_agent(checkpointer)
        yield
    # 服务关闭时：排空 Langfuse 上报队列、清理数据库连接
    flush_langfuse()
    await close_db()

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="中学多课程AI学习智能体后端服务",
    lifespan=lifespan
)

# CORS：生产模式前后端同源（FastAPI 托管 dist），仅需放行开发环境的 Vite dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 必须在静态文件加载之前导入路由
app.include_router(health.router)
app.include_router(subjects.router)
app.include_router(chat.router)
app.include_router(admin.router)
# 加载前端静态文件
static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "frontend", "dist")
index_path = os.path.join(static_dir, "index.html")

@app.get("/")
async def root():
    if os.path.isfile(index_path):
        return FileResponse(index_path)
    return {"message": f"欢迎使用{settings.APP_NAME}", "version": settings.APP_VERSION}

# 重定向首页默认指向
if os.path.isdir(static_dir):
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
