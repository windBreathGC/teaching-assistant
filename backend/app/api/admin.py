"""教材管理API：支持扫描、解析、向量化、进度查询。"""
import logging
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from app.services.textbook_parser import scan_textbooks, generate_metadata
from app.services.ingest_service import ingest_single_file, get_ingest_status

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])

# 内存任务状态表（单机场景够用；多机部署需换Redis）
_tasks: dict[str, dict] = {}
_tasks_lock = threading.Lock()
_TASK_TTL_HOURS = 1  # 已完成任务的保留时长

# 文件级锁：防止同一文件被并发处理导致索引损坏
_file_locks: dict[str, threading.Lock] = {}
_file_locks_lock = threading.Lock()


def _cleanup_old_tasks() -> None:
    """清理超过 _TASK_TTL_HOURS 的已完成任务，防止内存无限增长。"""
    cutoff = datetime.now() - timedelta(hours=_TASK_TTL_HOURS)
    with _tasks_lock:
        expired = [
            tid
            for tid, t in _tasks.items()
            if t.get("status") in ("completed", "failed", "error", "partial")
            and datetime.fromisoformat(t.get("created_at", "1970-01-01T00:00:00")) < cutoff
        ]
        for tid in expired:
            del _tasks[tid]
        if expired:
            logger.info("已清理 %d 个过期任务", len(expired))


def _get_file_lock(file_path: str) -> threading.Lock:
    """获取指定文件路径的锁，用于防止并发处理同一文件。"""
    with _file_locks_lock:
        if file_path not in _file_locks:
            _file_locks[file_path] = threading.Lock()
        return _file_locks[file_path]

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
    """后台任务：执行单个文件向量化入库。"""
    lock = _get_file_lock(file_path)
    with lock:
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
            logger.exception("单文件向量化失败: %s", file_path)
            _update_task(
                task_id,
                status="failed",
                progress=100,
                message="处理失败，请查看服务器日志",
                result={"status": "error", "message": "处理失败，请查看服务器日志"},
            )


def _run_batch_ingest_task(task_id: str):
    """后台任务：批量解析+向量化所有教材文件。"""
    _update_task(task_id, status="running", progress=0, message="扫描教材文件...")

    files = scan_textbooks(str(TEXTBOOK_DIR))
    total = len(files)
    completed = 0
    skipped = 0
    failed = 0
    errors: list[str] = []

    for i, item in enumerate(files):
        filename = item["filename"]
        file_path = (TEXTBOOK_DIR / filename).resolve()
        # 安全检查：确保解析后的路径仍在 textbook/ 目录内
        if not str(file_path).startswith(str(TEXTBOOK_DIR.resolve())):
            logger.warning("非法路径，跳过: %s", filename)
            failed += 1
            errors.append(f"{filename}: 非法路径")
            continue

        progress = int(((i + 1) / total) * 100) if total > 0 else 100
        _update_task(
            task_id,
            progress=progress,
            message=f"处理中: {filename} ({i + 1}/{total})",
        )

        # 1. 生成 metadata.json
        try:
            generate_metadata(str(file_path))
        except Exception as e:
            logger.warning("生成 metadata 失败 %s: %s", filename, e)

        # 2. 向量化入库（文件级锁防止并发冲突）
        lock = _get_file_lock(str(file_path))
        with lock:
            try:
                result = ingest_single_file(str(file_path))
                if result["status"] == "success":
                    completed += 1
                elif result["status"] == "skipped":
                    skipped += 1
                else:
                    failed += 1
                    errors.append(f"{filename}: {result['message']}")
            except Exception as e:
                logger.exception("批量向量化失败: %s", file_path)
                failed += 1
                errors.append(f"{filename}: 处理失败")

    final_status = "completed" if failed == 0 else ("failed" if completed == 0 else "partial")
    _update_task(
        task_id,
        status=final_status,
        progress=100,
        message=f"完成: {completed} 成功, {skipped} 跳过, {failed} 失败",
        result={
            "total": total,
            "completed": completed,
            "skipped": skipped,
            "failed": failed,
            "errors": errors,
        },
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
    except Exception:
        logger.exception("解析教材失败: %s", req.filename)
        raise HTTPException(status_code=500, detail="解析失败，请检查文件格式或查看服务器日志")


@router.post("/textbooks/ingest")
async def ingest_textbook(req: IngestRequest, background_tasks: BackgroundTasks):
    """触发指定教材的向量化入库。
    立即返回任务ID，实际工作在后台执行（可能耗时数分钟）。"""
    file_path = TEXTBOOK_DIR / req.filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="教材文件不存在")

    _cleanup_old_tasks()
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
            "created_at": datetime.now().isoformat(),
        }

    background_tasks.add_task(_run_ingest_task, task_id, str(file_path))

    return {
        "status": "accepted",
        "task_id": task_id,
        "filename": req.filename,
        "message": "向量化任务已提交，请轮询 /admin/tasks/{task_id} 查询进度",
    }


@router.post("/batch-ingest")
async def batch_ingest(background_tasks: BackgroundTasks):
    """触发所有教材文件的批量解析+向量化入库。
    立即返回任务ID，实际工作在后台执行。"""
    _cleanup_old_tasks()
    task_id = str(uuid.uuid4())[:8]
    with _tasks_lock:
        _tasks[task_id] = {
            "task_id": task_id,
            "type": "batch-ingest",
            "filename": "批量更新",
            "status": "pending",
            "progress": 0,
            "message": "等待执行",
            "result": None,
            "created_at": datetime.now().isoformat(),
        }

    background_tasks.add_task(_run_batch_ingest_task, task_id)

    return {
        "status": "accepted",
        "task_id": task_id,
        "message": "批量更新任务已提交，请轮询 /admin/tasks/{task_id} 查询进度",
    }


@router.get("/tasks/{task_id}", response_model=TaskInfo)
async def get_task(task_id: str):
    """查询任务进度。"""
    with _tasks_lock:
        task = _tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return TaskInfo(**task)
