"""教材向量化服务：支持单文件入库和进度回调。"""
import hashlib
import json
import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

# 确保能导入 backend/app 下的模块
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.config import get_settings
from app.services.rag import get_collection
from app.utils.text_splitter import load_and_split
from langchain_openai import OpenAIEmbeddings

settings = get_settings()

BASE_DIR = Path(__file__).parent.parent.parent.parent
TEXTBOOK_DIR = BASE_DIR / "textbook"
DATA_DIR = BASE_DIR / "backend" / "data"
INDEX_PATH = DATA_DIR / "ingest_index.json"


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _compute_sha256(file_path: str) -> str:
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_index() -> dict:
    if INDEX_PATH.exists():
        with open(INDEX_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"version": 1, "files": {}}


def _save_index(index: dict) -> None:
    _ensure_dir(DATA_DIR)
    with open(INDEX_PATH, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)


def _file_stem(file_path: str) -> str:
    return Path(file_path).stem


def _make_chunk_ids(stem: str, count: int) -> list[str]:
    return [f"{stem}_chunk_{i}" for i in range(count)]


def _parse_filename(filename: str) -> dict | None:
    """从文件名解析教材元数据（与 textbook_parser 保持一致）。"""
    from app.services.textbook_parser import parse_filename as _parser
    return _parser(filename)


def ingest_single_file(
    file_path: str,
    task_id: str | None = None,
    progress_callback=None,
) -> dict:
    """对单个教材文件执行解析、分块、Embedding、入库全流程。

    Args:
        file_path: Markdown文件绝对路径
        task_id: 可选任务ID，用于进度回调
        progress_callback: 可选回调函数 fn(task_id, progress_pct, message)

    Returns:
        {"status": "success"|"skipped"|"error", "chunks": int, "message": str}
    """

    def _report(progress: int, message: str):
        logger.info("[%s] %d%% - %s", task_id or "-", progress, message)
        if progress_callback and task_id:
            progress_callback(task_id, progress, message)

    _report(0, "开始处理")

    if not settings.OPENAI_API_KEY:
        return {"status": "error", "chunks": 0, "message": "未配置 OPENAI_API_KEY"}

    path = Path(file_path)
    if not path.exists():
        return {"status": "error", "chunks": 0, "message": f"文件不存在: {file_path}"}

    rel_path = os.path.relpath(file_path, BASE_DIR)
    basename = path.name

    meta = _parse_filename(basename)
    if not meta:
        return {"status": "error", "chunks": 0, "message": f"文件名格式不匹配: {basename}"}

    _report(5, "计算文件哈希")
    sha = _compute_sha256(file_path)
    index = _load_index()
    existing = index["files"].get(rel_path)

    if existing and existing.get("sha256") == sha:
        stem = _file_stem(file_path)
        chunk_count = existing.get("chunk_count", 0)
        if _verify_chromadb_data(stem, chunk_count):
            _report(100, "文件未变更，跳过")
            return {"status": "skipped", "chunks": chunk_count, "message": "文件未变更"}
        _report(5, "索引存在但向量库数据缺失，重新入库")
    else:
        stem = _file_stem(file_path)

    collection = get_collection()
    embeddings = OpenAIEmbeddings(
        model=settings.EMBEDDING_MODEL,
        api_key=settings.OPENAI_API_KEY,
        base_url=settings.OPENAI_BASE_URL,
    )

    # 删除旧数据
    if existing:
        old_ids = _make_chunk_ids(stem, existing["chunk_count"])
        try:
            collection.delete(ids=old_ids)
            _report(10, f"已删除旧数据: {len(old_ids)} chunks")
        except Exception as e:
            logger.warning("删除旧数据失败: %s", e)

    # 分块
    _report(15, "正在分块...")
    chunks = load_and_split(
        file_path,
        subject=meta["subject"],
        publisher=meta["version"],
        grade=meta["grade"],
        semester=meta["semester"],
    )
    _report(30, f"分块完成: {len(chunks)} chunks")

    if not chunks:
        return {"status": "error", "chunks": 0, "message": "无内容可分块"}

    # 生成 Embedding
    _report(35, "正在生成 Embedding...")
    texts = [c.content for c in chunks]
    metas = [c.metadata for c in chunks]
    ids = _make_chunk_ids(stem, len(chunks))

    try:
        vectors = embeddings.embed_documents(texts)
    except Exception as e:
        return {"status": "error", "chunks": 0, "message": f"Embedding 失败: {e}"}

    _report(80, "Embedding 完成，正在入库...")

    # 入库
    try:
        collection.add(ids=ids, embeddings=vectors, documents=texts, metadatas=metas)
    except Exception as e:
        return {"status": "error", "chunks": 0, "message": f"入库失败: {e}"}

    # 更新索引
    index["files"][rel_path] = {
        "sha256": sha,
        "chunk_count": len(chunks),
        "metadata": meta,
    }
    _save_index(index)

    _report(100, f"完成: {len(chunks)} chunks 已入库")
    return {"status": "success", "chunks": len(chunks), "message": f"已入库 {len(chunks)} chunks"}


def _verify_chromadb_data(stem: str, chunk_count: int) -> bool:
    """验证 ChromaDB collection 中是否确实存在对应的数据。"""
    if chunk_count <= 0:
        return False
    try:
        collection = get_collection()
        # 抽样检查前 3 个 chunk id，避免全量查询
        sample_ids = [f"{stem}_chunk_{i}" for i in range(min(3, chunk_count))]
        result = collection.get(ids=sample_ids)
        docs = result.get("documents") or []
        return any(d is not None and d != "" for d in docs)
    except Exception:
        return False


def get_ingest_status(filename: str) -> dict:
    """查询指定教材的入库状态。"""
    path = TEXTBOOK_DIR / filename
    if not path.exists():
        return {"exists": False, "parsed": False, "ingested": False}

    # 检查是否已解析
    meta = _parse_filename(filename)
    parsed = False
    if meta:
        grade_full = meta["grade"] + meta["semester"]
        from app.services.textbook_parser import GRADE_SUFFIX_MAP
        grade_suffix = GRADE_SUFFIX_MAP.get(grade_full, "")
        subject_id_map = {"语文": "chinese", "数学": "math", "英语": "english", "科学": "science", "社会": "social"}
        subject_id = subject_id_map.get(meta["subject"], meta["subject"])
        generated_path = DATA_DIR / "generated" / grade_suffix / f"{subject_id}.json"
        parsed = generated_path.exists()

    # 检查是否已向量化
    index = _load_index()
    rel_path = os.path.relpath(str(path), BASE_DIR)
    in_index = rel_path in index["files"]
    sha_match = False
    chunks_in_db = False
    chunk_count = 0
    if in_index:
        current_sha = _compute_sha256(str(path))
        sha_match = index["files"][rel_path].get("sha256") == current_sha
        chunk_count = index["files"][rel_path].get("chunk_count", 0)
        stem = _file_stem(str(path))
        chunks_in_db = _verify_chromadb_data(stem, chunk_count)

    ingested = in_index and sha_match and chunks_in_db
    outdated = in_index and (not sha_match or not chunks_in_db)

    return {
        "exists": True,
        "parsed": parsed,
        "ingested": ingested,
        "outdated": outdated,
        "chunks": chunk_count if in_index else None,
    }
