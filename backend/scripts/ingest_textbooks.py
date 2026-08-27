#!/usr/bin/env python3
"""教材向量化入库脚本（chunk 级增量更新）

用法:
    python backend/scripts/ingest_textbooks.py

机制:
    1. 自动扫描 textbook/ 目录下的所有 .md 文件（排除 TEMPLATE.md）
    2. 通过文件名正则解析出版本、年份、年级、学期、学科
    3. 文件 sha256 未变更时完全跳过；变更时按 chunk 粒度 diff：
       - chunk ID = {文件名}_h{内容哈希}，与切分顺序无关
       - 内容未变的 chunk 复用旧向量，只 embedding 真正变更的 chunk
       - 先 embedding 后写库（upsert 新增 -> delete 过期），失败时旧数据保留
    4. 磁盘上已删除的文件会自动从向量库中清理
    5. 任一文件处理失败不影响其他文件，脚本最终以非零退出码报告失败

共享逻辑见 app/services/ingest_core.py（与管理后台 ingest 服务共用）。
"""
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# 显式加载项目根目录的 .env，确保脚本独立运行时环境变量正确
from dotenv import load_dotenv
_script_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(os.path.dirname(_script_dir))
_env_path = os.path.join(_project_root, ".env")
load_dotenv(_env_path, override=True)

# 强制 ChromaDB 使用 backend/chroma_db 绝对路径，避免因工作目录不同导致数据分离
os.environ["CHROMA_PERSIST_DIR"] = os.path.join(_script_dir, "..", "chroma_db")

from app.core.config import get_settings
from app.services.keyword_search import invalidate_cache as invalidate_bm25_cache
from app.services.ingest_core import (
    assign_chunk_ids,
    compute_sha256,
    diff_chunks,
    embed_with_retry,
    entry_chunk_ids,
    load_index,
    make_index_entry,
    save_index,
)
from app.services.rag import get_collection
from app.services.textbook_parser import generate_metadata, parse_filename
from app.utils.text_splitter import load_and_split
from langchain_openai import OpenAIEmbeddings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

settings = get_settings()

# 脚本在 backend/scripts/，教材在同级目录的 textbook/
BASE_DIR = os.path.join(os.path.dirname(__file__), "..", "..")
TEXTBOOK_DIR = os.path.join(BASE_DIR, "textbook")
DATA_DIR = os.path.join(BASE_DIR, "backend", "data")
INDEX_PATH = os.path.join(DATA_DIR, "ingest_index.json")


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _file_stem(file_path: str) -> str:
    """提取文件名（不含扩展名），用于生成 chunk_id 前缀。"""
    return os.path.splitext(os.path.basename(file_path))[0]


def main():
    # 确保脚本无论从哪个目录运行，都使用后端统一的 ChromaDB 路径
    backend_dir = os.path.join(os.path.dirname(__file__), "..")
    os.environ.setdefault("CHROMA_PERSIST_DIR", os.path.join(backend_dir, "chroma_db"))

    # 重新加载 settings 以应用上述环境变量覆盖
    from app.core.config import Settings
    settings = Settings()

    if not settings.OPENAI_API_KEY:
        logger.error("请设置 OPENAI_API_KEY 环境变量")
        sys.exit(1)

    _ensure_dir(DATA_DIR)
    logger.info("教材目录: %s", TEXTBOOK_DIR)
    logger.info("索引文件: %s", INDEX_PATH)
    logger.info("向量库路径: %s", settings.CHROMA_PERSIST_DIR)

    collection = get_collection()
    embeddings = OpenAIEmbeddings(
        model=settings.EMBEDDING_MODEL,
        api_key=settings.OPENAI_API_KEY,
        base_url=settings.OPENAI_BASE_URL,
        # SiliconFlow 等 OpenAI 兼容接口不支持 token 数组输入和base64 编码格式（openai SDK 2.x 默认 encoding_format=base64，
        # 会触发 400 / code 20015），按 langchain 官方建议关闭
        check_embedding_ctx_length=False,
        model_kwargs={"encoding_format": "float"},
    )
    index = load_index(INDEX_PATH)
    METADATA_DIR = os.path.join(DATA_DIR, "generated")
    _ensure_dir(METADATA_DIR)

    # 1. 扫描目录
    md_files = []
    if os.path.isdir(TEXTBOOK_DIR):
        for name in os.listdir(TEXTBOOK_DIR):
            if not name.endswith(".md"):
                continue
            if name.startswith("TEMPLATE"):
                continue
            full = os.path.join(TEXTBOOK_DIR, name)
            if os.path.isfile(full):
                md_files.append(full)

    if not md_files:
        logger.warning("textbook/ 目录下没有找到 .md 教材文件")
        return

    logger.info("扫描到 %d 个教材文件", len(md_files))

    # 2. 逐个处理
    current_files: set[str] = set()
    total_added = 0
    total_reused = 0
    total_deleted = 0
    failed_files: list[str] = []
    index_dirty = False

    for file_path in sorted(md_files):
        rel_path = os.path.relpath(file_path, BASE_DIR)
        current_files.add(rel_path)
        basename = os.path.basename(file_path)

        meta = parse_filename(basename)
        if not meta:
            logger.warning("文件名格式不匹配，跳过: %s", basename)
            continue

        sha = compute_sha256(file_path)
        existing = index["files"].get(rel_path)

        if existing and existing.get("sha256") == sha:
            logger.info("未变更，跳过: %s", basename)
            continue

        logger.info(
            "处理: %s (%s %s %s %s)...",
            basename,
            meta["subject"],
            meta["version"],
            meta["grade"],
            meta["semester"],
        )

        # 2a. 分块（在任何删除操作之前完成）
        chunks = load_and_split(
            file_path,
            subject=meta["subject"],
            publisher=meta["version"],
            grade=meta["grade"],
            semester=meta["semester"],
        )
        if not chunks:
            logger.warning("  无内容可分块，跳过入库")
            continue

        # 2b. 生成稳定 chunk ID，并与库中旧数据 diff
        stem = _file_stem(file_path)
        assigned = assign_chunk_ids(stem, chunks)
        old_ids = entry_chunk_ids(existing, stem) if existing else []
        to_add, to_delete = diff_chunks(assigned, old_ids)
        reused = len(assigned) - len(to_add)
        logger.info(
            "  分块数: %d（复用 %d，新增/变更 %d，删除 %d）",
            len(assigned), reused, len(to_add), len(to_delete),
        )

        # 2c. 先 embedding 变更的 chunk；失败则保留旧数据、跳过本文件
        try:
            vectors = embed_with_retry(embeddings, [c.content for _, _, c in to_add])
        except Exception as e:
            logger.error("  embedding 失败，旧数据已保留，跳过本文件: %s", e)
            failed_files.append(basename)
            continue

        # 2d. 先 upsert 新 chunk，再删除过期 chunk（任何时刻库中都有完整数据）
        try:
            if to_add:
                collection.upsert(
                    ids=[cid for cid, _, _ in to_add],
                    embeddings=vectors,
                    documents=[c.content for _, _, c in to_add],
                    metadatas=[c.metadata for _, _, c in to_add],
                )
            if to_delete:
                collection.delete(ids=to_delete)
        except Exception as e:
            logger.error("  写入向量库失败，旧数据基本保留，跳过本文件: %s", e)
            failed_files.append(basename)
            continue

        # 2e. 更新 metadata.json 与索引
        try:
            meta_path = generate_metadata(file_path, output_dir=METADATA_DIR)
            logger.info("  已更新 metadata: %s", os.path.basename(meta_path))
        except Exception as e:
            logger.warning("  生成 metadata 失败: %s", e)

        index["files"][rel_path] = make_index_entry(sha, meta, assigned)
        index_dirty = True
        total_added += len(to_add)
        total_reused += reused
        total_deleted += len(to_delete)
        logger.info("  已入库: 新增/变更 %d chunks", len(to_add))

    # 3. 清理磁盘上已删除的文件
    removed = []
    for rel_path in list(index["files"].keys()):
        if rel_path not in current_files:
            basename = os.path.basename(rel_path)
            stem = os.path.splitext(basename)[0]
            old_ids = entry_chunk_ids(index["files"][rel_path], stem)
            try:
                if old_ids:
                    collection.delete(ids=old_ids)
                removed.append(rel_path)
                logger.info("清理已删除文件: %s (%d chunks)", rel_path, len(old_ids))
            except Exception as e:
                logger.warning("清理已删除文件失败 %s: %s", rel_path, e)

    for rp in removed:
        del index["files"][rp]

    # 4. 保存索引
    if index_dirty or removed:
        save_index(INDEX_PATH, index)
        # 向量库已变更，BM25 关键词索引缓存需重建
        invalidate_bm25_cache()
        logger.info("索引已更新")

    logger.info(
        "处理完成。新增/变更: %d chunks, 复用: %d chunks, 删除: %d chunks, 清理文件: %d 个, 失败: %d 个",
        total_added, total_reused, total_deleted, len(removed), len(failed_files),
    )
    if failed_files:
        logger.error("以下文件处理失败: %s", ", ".join(failed_files))
        sys.exit(1)


if __name__ == "__main__":
    main()
