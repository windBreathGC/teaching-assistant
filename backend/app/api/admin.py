"""教材管理API：支持扫描、解析、向量化、进度查询。"""
import threading
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from app.services.textbook_parser import scan_textbooks, generate_metadata
from app.services.ingest_service import ingest_single_file, get_ingest_status

router = APIRouter(prefix="/admin", tags=["admin"])

# 内存任务状态表（单机场景够用；多机部署需换Redis）
_tasks: dict[str, dict] = {}
_tasks_lock = threading.Lock()

BASE_DIR = Path(__file__).parent.parent.parent.parent
TEXTBOOK_DIR = BASE_DIR / "textbook"


class TextbookItem(BaseModel):
    filename: str
    subject: str
    grade: str
    semester: str
    parsed: bool
    ingested: bool
    outdated: bool
    chunks: int | None


class TaskInfo(BaseModel):
    task_id: str
    type: str
    filename: str
    status: str
    progress: int
    message: str
    result: dict | None


class ParseRequest(BaseModel):
    filename: str


class IngestRequest(BaseModel):
    filename: str


def _update_task(task_id: str, **kwargs):
    with _tasks_lock:
        if task_id not in _tasks:
            return
        _tasks[task_id].update(kwargs)


def _progress_callback(task_id: str, progress: int, message: str):
    _update_task(task_id, progress=progress, message=message)


def _run_ingest_task(task_id: str, file_path: str):
    """后台任务：执行向量化入库。"""
    _update_task(task_id, status="running", progress=0, message="任务启动")
    try:
        result = ingest_single_file(
            file_path,
            task_id=task_id,
            progress_callback=_progress_callback,
        )
        _update_task(
            task_id,
            status="completed" if result["status"] == "success" else result["status"],
            progress=100,
            message=result["message"],
            result=result,
        )
    except Exception as e:
        _update_task(
            task_id,
            status="failed",
            progress=100,
            message=str(e),
            result={"status": "error", "message": str(e)},
        )


@router.get("/textbooks", response_model=list[TextbookItem])
async def list_textbooks():
    """扫描 textbook/ 目录，返回所有教材文件及其解析/向量化状态。"""
    results = []
    scanned = scan_textbooks(str(TEXTBOOK_DIR))
    for item in scanned:
        filename = item["filename"]
        meta = item["meta"]
        status = get_ingest_status(filename)
        results.append(TextbookItem(
            filename=filename,
            subject=meta["subject"],
            grade=meta["grade"],
            semester=meta["semester"],
            parsed=status["parsed"],
            ingested=status["ingested"],
            outdated=status["outdated"],
            chunks=status["chunks"],
        ))
    return results


@router.post("/textbooks/parse")
async def parse_textbook(req: ParseRequest):
    """解析指定教材Markdown，生成 metadata.json。
    同步执行，通常几秒完成。"""
    file_path = TEXTBOOK_DIR / req.filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="教材文件不存在")

    try:
        out_path = generate_metadata(str(file_path))
        return {
            "status": "success",
            "filename": req.filename,
            "metadata_path": str(out_path),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"解析失败: {e}")


@router.post("/textbooks/ingest")
async def ingest_textbook(req: IngestRequest, background_tasks: BackgroundTasks):
    """触发指定教材的向量化入库。
    立即返回任务ID，实际工作在后台执行（可能耗时数分钟）。"""
    file_path = TEXTBOOK_DIR / req.filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="教材文件不存在")

    task_id = str(uuid.uuid4())[:8]
    with _tasks_lock:
        _tasks[task_id] = {
            "task_id": task_id,
            "type": "ingest",
            "filename": req.filename,
            "status": "pending",
            "progress": 0,
            "message": "等待执行",
            "result": None,
        }

    background_tasks.add_task(_run_ingest_task, task_id, str(file_path))

    return {
        "status": "accepted",
        "task_id": task_id,
        "filename": req.filename,
        "message": "向量化任务已提交，请轮询 /admin/tasks/{task_id} 查询进度",
    }


@router.get("/tasks/{task_id}", response_model=TaskInfo)
async def get_task(task_id: str):
    """查询任务进度。"""
    with _tasks_lock:
        task = _tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return TaskInfo(**task)
