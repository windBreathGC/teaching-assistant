"""教材向量化服务：支持单文件入库和进度回调。

与 scripts/ingest_textbooks.py 共用 app/services/ingest_core.py 的
chunk ID 规则、索引格式与增量 diff 逻辑，两条入库路径行为一致。
"""
import logging
import os
import sys
from pathlib import Path

from typing import Callable

logger = logging.getLogger(__name__)

# 确保能导入 backend/app 下的模块
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.config import get_settings
from app.services.ingest_core import (
    assign_chunk_ids,
    compute_sha256,
    diff_chunks,
    embed_with_retry,
    entry_chunk_count,
    entry_chunk_ids,
    load_index,
    make_index_entry,
    save_index,
)
from app.services.keyword_search import invalidate_cache as invalidate_bm25_cache
from app.services.rag import get_collection
from app.utils.text_splitter import load_and_split
from langchain_openai import OpenAIEmbeddings

settings = get_settings()

BASE_DIR = Path(__file__).parent.parent.parent.parent
TEXTBOOK_DIR = BASE_DIR / "textbook"
DATA_DIR = BASE_DIR / "backend" / "data"
INDEX_PATH = DATA_DIR / "ingest_index.json"


def _file_stem(file_path: str) -> str:
    return Path(file_path).stem


def _parse_filename(filename: str) -> dict | None:
    """从文件名解析教材元数据（与 textbook_parser 保持一致）。"""
    from app.services.textbook_parser import parse_filename as _parser
    return _parser(filename)


def _make_embeddings() -> OpenAIEmbeddings:
    return OpenAIEmbeddings(
        model=settings.EMBEDDING_MODEL,
        api_key=settings.OPENAI_API_KEY,
        base_url=settings.OPENAI_BASE_URL,
        # SiliconFlow 等 OpenAI 兼容接口不支持 token 数组输入和base64 编码格式
        check_embedding_ctx_length=False,
        model_kwargs={"encoding_format": "float"},
    )


def ingest_single_file(
    file_path: str,
    task_id: str | None = None,
    progress_callback: Callable | None =None,
) -> dict:
    """对单个教材文件执行解析、分块、Embedding、入库全流程（chunk 级增量）。

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
    sha = compute_sha256(file_path)
    index = load_index(INDEX_PATH)
    existing = index["files"].get(rel_path)
    stem = _file_stem(file_path)

    # sha 未变且向量库数据完整 -> 跳过；sha 未变但库数据缺失 -> 强制全量修复
    force_full = False
    if existing and existing.get("sha256") == sha:
        # 如果向量化的文件已经存在，需要收集已存在的chunk id，同时抽取前3个判断向量库是否已经存在
        old_ids = entry_chunk_ids(existing, stem)
        if _verify_chromadb_data(old_ids):
            _report(100, "文件未变更，跳过")
            return {"status": "skipped", "chunks": len(old_ids), "message": "文件未变更"}
        force_full = True
        _report(5, "索引存在但向量库数据缺失，执行全量修复")

    collection = get_collection()
    embeddings = _make_embeddings()

    # 分块（在任何删除操作之前完成）
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

    # 生成稳定 chunk ID，与库中旧数据 diff
    assigned = assign_chunk_ids(stem, chunks)
    old_ids = entry_chunk_ids(existing, stem) if existing else []
    # 逐块比对，基于块的维度刷新向量库，而不是基于整份文档全部刷新，减少开销和提升效率
    to_add, to_delete = diff_chunks(assigned, old_ids, force_full=force_full)
    reused = len(assigned) - len(to_add)
    _report(32, f"增量对比: 复用 {reused}，新增/变更 {len(to_add)}，删除 {len(to_delete)}")

    # 先 embedding 变更的 chunk；失败则旧数据原样保留
    _report(35, "正在生成 Embedding...")
    try:
        vectors = embed_with_retry(
            embeddings,
            [c.content for _, _, c in to_add],
            progress=lambda done, total: _report(
                35 + 40 * done // max(total, 1), f"Embedding 进度: {done}/{total}"
            ),
        )
    except Exception as e:
        return {"status": "error", "chunks": 0, "message": f"Embedding 失败（旧数据已保留）: {e}"}

    _report(80, "Embedding 完成，正在入库...")

    # 入库
    try:
        # 先 upsert 新 chunk，再删除过期 chunk，防止先删除导致同步查询时获取空内容
        if to_add:
            collection.upsert(
                ids=[cid for cid, _, _ in to_add],
                embeddings=vectors,
                documents=[c.content for _, _, c in to_add],
                metadatas=[c.metadata for _, _, c in to_add],
            )
        if to_delete:
            collection.delete(ids=to_delete)
            _report(90, f"已清理过期数据: {len(to_delete)} chunks")
    except Exception as e:
        return {"status": "error", "chunks": 0, "message": f"入库失败: {e}"}

    # 向量库已变更，BM25 关键词索引缓存需重建
    if to_add or to_delete:
        invalidate_bm25_cache()

    # 更新索引
    index["files"][rel_path] = make_index_entry(sha, meta, assigned)
    save_index(INDEX_PATH, index)

    _report(100, f"完成: 新增/变更 {len(to_add)}，复用 {reused} chunks")
    return {
        "status": "success",
        "chunks": len(assigned),
        "message": f"已入库 {len(assigned)} chunks（新增/变更 {len(to_add)}，复用 {reused}）",
    }


def _verify_chromadb_data(chunk_ids: list[str]) -> bool:
    """验证 ChromaDB collection 中是否确实存在对应的数据（抽样前 3 个 chunk id）。"""
    if not chunk_ids:
        return False
    try:
        collection = get_collection()
        result = collection.get(ids=chunk_ids[:3])
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
    index = load_index(INDEX_PATH)
    rel_path = os.path.relpath(str(path), BASE_DIR)
    in_index = rel_path in index["files"]
    sha_match = False
    chunks_in_db = False
    chunk_count = 0
    if in_index:
        entry = index["files"][rel_path]
        current_sha = compute_sha256(str(path))
        sha_match = entry.get("sha256") == current_sha
        chunk_count = entry_chunk_count(entry)
        stem = _file_stem(str(path))
        chunks_in_db = _verify_chromadb_data(entry_chunk_ids(entry, stem))

    ingested = in_index and sha_match and chunks_in_db
    outdated = in_index and (not sha_match or not chunks_in_db)

    return {
        "exists": True,
        "parsed": parsed,
        "ingested": ingested,
        "outdated": outdated,
        "chunks": chunk_count if in_index else None,
    }
