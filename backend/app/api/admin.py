"""教材管理API：支持扫描、解析、向量化、进度查询。"""
import logging
import threading
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel

from app.core.auth import verify_admin_token
from app.services.textbook_parser import scan_textbooks, generate_metadata
from app.services.ingest_service import ingest_single_file, get_ingest_status
from app.services.textbook_generator import generate_outline, generate_textbook
from app.services.textbook_analyzer import analyze_textbook
from app.services import model_config_service as model_svc
from app.services import task_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(verify_admin_token)])


# ── 异步桥接：BackgroundTasks 在线程池中运行，而 aiosqlite 需要事件循环 ──

def _run_async(coro):
    """在线程池上下文中执行异步协程（用于 BackgroundTasks）。"""
    import asyncio
    return asyncio.run(coro)


def _progress_callback(task_id: str, progress: int, message: str):
    _run_async(task_service.update_task(task_id, progress=progress, message=message))

# 文件级锁：防止同一文件被并发处理导致索引损坏
_file_locks: dict[str, threading.Lock] = {}
_file_locks_lock = threading.Lock()


def _get_file_lock(file_path: str) -> threading.Lock:
    """获取指定文件路径的锁，用于防止并发处理同一文件。"""
    with _file_locks_lock:
        if file_path not in _file_locks:
            _file_locks[file_path] = threading.Lock()
        return _file_locks[file_path]


BASE_DIR = Path(__file__).parent.parent.parent.parent
TEXTBOOK_DIR = BASE_DIR / "textbook"


def _resolve_textbook_path(filename: str) -> Path:
    """将教材文件名解析为绝对路径，并确保其位于 textbook/ 目录内。

    防止 filename 中包含 ../ 等路径遍历，对目录外文件触发解析/向量化。
    """
    file_path = (TEXTBOOK_DIR / filename).resolve()
    if TEXTBOOK_DIR.resolve() not in file_path.parents:
        raise HTTPException(status_code=400, detail="非法文件路径")
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="教材文件不存在")
    return file_path


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
    created_at: str = ""
    updated_at: str = ""


class ParseRequest(BaseModel):
    filename: str


class IngestRequest(BaseModel):
    filename: str


class LLMConfig(BaseModel):
    base_url: str
    api_key: str
    model_name: str
    temperature: float = 0.3


class GenerateOutlineRequest(BaseModel):
    subject: str
    grade: str
    semester: str
    publisher: str
    version_year: str
    region: str = ""
    notes: str = ""
    model_id: str


class GenerateTextbookRequest(BaseModel):
    outline: dict
    subject: str
    grade: str
    semester: str
    publisher: str
    version_year: str
    region: str = ""
    model_id: str


class AnalyzeRequest(BaseModel):
    filename: str


# ── 模型配置管理 ──

class ModelConfigCreate(BaseModel):
    name: str
    base_url: str
    api_key: str
    model_name: str
    temperature: float = 0.3
    is_default: bool = False


class ModelConfigUpdate(BaseModel):
    name: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    model_name: str | None = None
    temperature: float | None = None
    is_default: bool | None = None


def _run_ingest_task(task_id: str, file_path: str):
    """后台任务：执行单个文件向量化入库。"""
    lock = _get_file_lock(file_path)
    with lock:
        _run_async(task_service.update_task(task_id, status="running", progress=0, message="任务启动"))
        try:
            result = ingest_single_file(
                file_path,
                task_id=task_id,
                progress_callback=_progress_callback,
            )
            _run_async(task_service.update_task(
                task_id,
                status="completed" if result["status"] == "success" else result["status"],
                progress=100,
                message=result["message"],
                result=result,
            ))
        except Exception as e:
            logger.exception("单文件向量化失败: %s", file_path)
            _run_async(task_service.update_task(
                task_id,
                status="failed",
                progress=100,
                message="处理失败，请查看服务器日志",
                result={"status": "error", "message": "处理失败，请查看服务器日志"},
            ))


def _run_batch_ingest_task(task_id: str):
    """后台任务：批量解析+向量化所有教材文件。"""
    _run_async(task_service.update_task(task_id, status="running", progress=0, message="扫描教材文件..."))

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
        if TEXTBOOK_DIR.resolve() not in file_path.parents:
            logger.warning("非法路径，跳过: %s", filename)
            failed += 1
            errors.append(f"{filename}: 非法路径")
            continue

        progress = int(((i + 1) / total) * 100) if total > 0 else 100
        _run_async(task_service.update_task(
            task_id,
            progress=progress,
            message=f"处理中: {filename} ({i + 1}/{total})",
        ))

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
    _run_async(task_service.update_task(
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
    ))


def _run_generate_outline_task(task_id: str, req_data: dict):
    """后台任务：执行教材大纲生成。"""
    model = _run_async(model_svc.get_model_raw(req_data["model_id"]))
    if not model:
        _run_async(task_service.update_task(
            task_id,
            status="failed",
            progress=100,
            message="模型配置不存在",
            result={"status": "error", "message": "模型配置不存在"},
        ))
        return

    model_config = {
        "base_url": model["base_url"],
        "api_key": model["api_key"],
        "model_name": model["model_name"],
        "temperature": model.get("temperature", 0.3),
    }

    _run_async(task_service.update_task(task_id, status="running", progress=0, message="开始生成大纲..."))

    try:
        outline = generate_outline(
            subject=req_data["subject"],
            grade=req_data["grade"],
            semester=req_data["semester"],
            publisher=req_data["publisher"],
            version_year=req_data["version_year"],
            region=req_data.get("region", ""),
            notes=req_data.get("notes", ""),
            model_config=model_config,
        )
        _run_async(task_service.update_task(
            task_id,
            status="completed",
            progress=100,
            message=f"大纲生成完成: {outline.get('title', '')}",
            result={
                "outline": outline,
                "subject": req_data["subject"],
                "grade": req_data["grade"],
                "semester": req_data["semester"],
                "publisher": req_data["publisher"],
                "version_year": req_data["version_year"],
                "region": req_data.get("region", ""),
            },
        ))
    except ValueError as e:
        logger.warning("生成大纲失败: %s", e)
        _run_async(task_service.update_task(
            task_id,
            status="failed",
            progress=100,
            message=str(e),
            result={"status": "error", "message": str(e)},
        ))
    except Exception:
        logger.exception("生成大纲任务失败: %s", task_id)
        _run_async(task_service.update_task(
            task_id,
            status="failed",
            progress=100,
            message="生成大纲失败，请查看服务器日志",
            result={"status": "error", "message": "生成大纲失败，请查看服务器日志"},
        ))


def _run_generate_task(task_id: str, outline: dict, meta: dict, model_id: str):
    """后台任务：执行教材生成。"""
    model = _run_async(model_svc.get_model_raw(model_id))
    if not model:
        _run_async(task_service.update_task(
            task_id,
            status="failed",
            progress=100,
            message="模型配置不存在",
            result={"status": "error", "message": "模型配置不存在"},
        ))
        return

    model_config = {
        "base_url": model["base_url"],
        "api_key": model["api_key"],
        "model_name": model["model_name"],
        "temperature": model.get("temperature", 0.3),
    }

    def progress_callback(current: int, total: int, message: str):
        progress = int((current / total) * 100) if total > 0 else 100
        _run_async(task_service.update_task(task_id, progress=progress, message=message))

    _run_async(task_service.update_task(task_id, status="running", progress=0, message="开始生成教材..."))

    try:
        file_path = generate_textbook(
            outline=outline,
            meta=meta,
            model_config=model_config,
            progress_callback=progress_callback,
        )
        _run_async(task_service.update_task(
            task_id,
            status="completed",
            progress=100,
            message=f"教材生成完成: {file_path.name}",
            result={
                "status": "success",
                "file_path": str(file_path),
                "filename": file_path.name,
            },
        ))
    except Exception:
        logger.exception("教材生成任务失败: %s", task_id)
        _run_async(task_service.update_task(
            task_id,
            status="failed",
            progress=100,
            message="教材生成失败，请查看服务器日志",
            result={"status": "error", "message": "教材生成失败，请查看服务器日志"},
        ))


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
    file_path = _resolve_textbook_path(req.filename)

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
    file_path = _resolve_textbook_path(req.filename)

    task_id = str(uuid.uuid4())
    await task_service.create_task(
        task_id=task_id,
        task_type="ingest",
        filename=req.filename,
    )

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
    task_id = str(uuid.uuid4())
    await task_service.create_task(
        task_id=task_id,
        task_type="batch-ingest",
        filename="批量更新",
    )

    background_tasks.add_task(_run_batch_ingest_task, task_id)

    return {
        "status": "accepted",
        "task_id": task_id,
        "message": "批量更新任务已提交，请轮询 /admin/tasks/{task_id} 查询进度",
    }


@router.get("/tasks")
async def list_tasks(skip: int = 0, limit: int = 50):
    """查询所有后台任务列表（支持分页）。"""
    tasks = await task_service.list_tasks(offset=skip, limit=limit)
    total = await task_service.count_tasks()
    return {"tasks": [TaskInfo(**t) for t in tasks], "total": total}


@router.get("/tasks/{task_id}", response_model=TaskInfo)
async def get_task(task_id: str):
    """查询单个任务进度。"""
    task = await task_service.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return TaskInfo(**task)


@router.post("/generate-outline")
async def api_generate_outline(req: GenerateOutlineRequest, background_tasks: BackgroundTasks):
    """触发教材大纲生成任务。立即返回任务ID，实际工作在后台执行（可能耗时数分钟）。"""
    if not await model_svc.get_model(req.model_id):
        raise HTTPException(status_code=404, detail="模型配置不存在")

    task_id = str(uuid.uuid4())
    await task_service.create_task(
        task_id=task_id,
        task_type="generate-outline",
        filename=f"{req.publisher}{req.version_year}{req.grade}{req.semester}{req.subject}大纲",
    )

    background_tasks.add_task(
        _run_generate_outline_task,
        task_id,
        req.model_dump(),
    )

    return {
        "status": "accepted",
        "task_id": task_id,
        "message": "大纲生成任务已提交，请轮询 /admin/tasks/{task_id} 查询进度",
    }


@router.post("/generate-textbook")
async def api_generate_textbook(req: GenerateTextbookRequest, background_tasks: BackgroundTasks):
    """触发完整教材生成任务。立即返回任务ID，实际工作在后台执行（可能耗时数分钟）。"""
    if not await model_svc.get_model(req.model_id):
        raise HTTPException(status_code=404, detail="模型配置不存在")

    task_id = str(uuid.uuid4())

    meta = {
        "subject": req.subject,
        "grade": req.grade,
        "semester": req.semester,
        "publisher": req.publisher,
        "version_year": req.version_year,
        "region": req.region,
    }

    await task_service.create_task(
        task_id=task_id,
        task_type="generate",
        filename=f"{req.publisher}{req.version_year}{req.grade}{req.semester}{req.subject}",
    )

    background_tasks.add_task(
        _run_generate_task,
        task_id,
        req.outline,
        meta,
        req.model_id,
    )

    return {
        "status": "accepted",
        "task_id": task_id,
        "message": "教材生成任务已提交，请轮询 /admin/tasks/{task_id} 查询进度",
    }


@router.post("/analyze-textbook")
async def api_analyze_textbook(req: AnalyzeRequest):
    """分析指定教材文件，返回结构完整性和内容质量报告。"""
    file_path = _resolve_textbook_path(req.filename)

    try:
        report = analyze_textbook(str(file_path))
        return {
            "status": "success",
            "report": report,
        }
    except Exception:
        logger.exception("分析教材失败: %s", req.filename)
        raise HTTPException(status_code=500, detail="分析失败，请查看服务器日志") from None


# ── 模型配置管理端点 ──

@router.get("/models")
async def api_list_models():
    """获取所有模型配置列表。"""
    return {"status": "success", "models": await model_svc.list_models()}


@router.get("/models/{model_id}")
async def api_get_model(model_id: str):
    """获取单个模型配置。"""
    model = await model_svc.get_model(model_id)
    if not model:
        raise HTTPException(status_code=404, detail="模型配置不存在")
    return {"status": "success", "model": model}


@router.post("/models")
async def api_add_model(req: ModelConfigCreate):
    """添加新模型配置。"""
    model = await model_svc.add_model(req.model_dump())
    return {"status": "success", "model": model}


@router.put("/models/{model_id}")
async def api_update_model(model_id: str, req: ModelConfigUpdate):
    """更新模型配置。"""
    model = await model_svc.update_model(model_id, req.model_dump(exclude_unset=True))
    if not model:
        raise HTTPException(status_code=404, detail="模型配置不存在")
    return {"status": "success", "model": model}


@router.delete("/models/{model_id}")
async def api_delete_model(model_id: str):
    """删除模型配置。"""
    if not await model_svc.delete_model(model_id):
        raise HTTPException(status_code=404, detail="模型配置不存在")
    return {"status": "success", "message": "已删除"}


@router.post("/models/{model_id}/default")
async def api_set_default_model(model_id: str):
    """设置默认模型。"""
    if not await model_svc.set_default(model_id):
        raise HTTPException(status_code=404, detail="模型配置不存在")
    return {"status": "success", "message": "已设为默认"}
