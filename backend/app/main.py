from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os
from app.core.config import get_settings
from app.api import health, subjects, chat, admin

settings = get_settings()

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="中学多课程AI学习智能体后端服务",
)

# CORS (开发环境允许所有来源，便于局域网内多设备访问)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API Routers (must be before static files)
app.include_router(health.router)
app.include_router(subjects.router)
app.include_router(chat.router)
app.include_router(admin.router)

static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "frontend", "dist")
index_path = os.path.join(static_dir, "index.html")

@app.get("/")
async def root():
    if os.path.isfile(index_path):
        return FileResponse(index_path)
    return {"message": f"欢迎使用{settings.APP_NAME}", "version": settings.APP_VERSION}

# Static files for SPA (404s fall back to index.html)
if os.path.isdir(static_dir):
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
