#!/usr/bin/env python3
"""教材向量化入库脚本（支持增量更新）

用法:
    python backend/scripts/ingest_textbooks.py

机制:
    1. 自动扫描 textbook/ 目录下的所有 .md 文件（排除 TEMPLATE.md）
    2. 通过文件名正则解析出版本、年份、年级、学期、学科
    3. 维护 ingest_index.json 记录每个文件的 sha256 和 chunk 数量
    4. 文件未变更时完全跳过；变更时先删旧 chunk 再重新入库
    5. 磁盘上已删除的文件会自动从向量库中清理
"""
import hashlib
import json
import logging
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.config import get_settings
from app.services.rag import get_collection
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

# 文件名解析正则:
# 示例: 部编版2024七年级上册语文_完整教材内容.md
FILENAME_PATTERN = re.compile(
    r"^(?P<version>[^0-9]+)"
    r"(?P<year>\d{4})"
    r"(?P<grade>七年级|八年级|九年级|高一|高二|高三)"
    r"(?P<semester>上册|下册)"
    r"(?P<subject>语文|数学|英语|科学|社会)"
    r"_(?P<content_type>.+)\.md$"
)


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _compute_sha256(file_path: str) -> str:
    """计算文件 SHA256，用于检测内容是否变更。"""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_index() -> dict:
    if os.path.exists(INDEX_PATH):
        with open(INDEX_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"version": 1, "files": {}}


def _save_index(index: dict) -> None:
    with open(INDEX_PATH, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)


def _parse_filename(filename: str) -> dict | None:
    """从文件名解析教材元数据。"""
    m = FILENAME_PATTERN.match(filename)
    if not m:
        return None
    return {
        "version": m.group("version"),
        "year": m.group("year"),
        "grade": m.group("grade"),
        "semester": m.group("semester"),
        "subject": m.group("subject"),
        "content_type": m.group("content_type"),
    }


def _file_stem(file_path: str) -> str:
    """提取文件名（不含扩展名），用于生成 chunk_id 前缀。"""
    return os.path.splitext(os.path.basename(file_path))[0]


def _make_chunk_ids(stem: str, count: int) -> list[str]:
    """生成可预测的 chunk_id 列表，格式: {stem}_chunk_{seq}。"""
    return [f"{stem}_chunk_{i}" for i in range(count)]


def main():
    if not settings.OPENAI_API_KEY:
        logger.error("请设置 OPENAI_API_KEY 环境变量")
        sys.exit(1)

    _ensure_dir(DATA_DIR)
    logger.info("教材目录: %s", TEXTBOOK_DIR)
    logger.info("索引文件: %s", INDEX_PATH)

    collection = get_collection()
    embeddings = OpenAIEmbeddings(
        model=settings.EMBEDDING_MODEL,
        api_key=settings.OPENAI_API_KEY,
        base_url=settings.OPENAI_BASE_URL,
    )
    index = _load_index()

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
    total_new = 0

    for file_path in sorted(md_files):
        rel_path = os.path.relpath(file_path, BASE_DIR)
        current_files.add(rel_path)
        basename = os.path.basename(file_path)

        meta = _parse_filename(basename)
        if not meta:
            logger.warning("文件名格式不匹配，跳过: %s", basename)
            continue

        sha = _compute_sha256(file_path)
        existing = index["files"].get(rel_path)

        if existing and existing.get("sha256") == sha:
            logger.info("未变更，跳过: %s", basename)
            continue

        stem = _file_stem(file_path)

        # 2a. 有旧数据则先删除
        if existing:
            old_ids = _make_chunk_ids(stem, existing["chunk_count"])
            try:
                collection.delete(ids=old_ids)
                logger.info("  删除旧数据: %d chunks", len(old_ids))
            except Exception as e:
                logger.warning("  删除旧数据失败: %s", e)

        # 2b. 解析新内容
        logger.info(
            "处理: %s (%s %s %s %s)...",
            basename,
            meta["subject"],
            meta["version"],
            meta["grade"],
            meta["semester"],
        )
        chunks = load_and_split(
            file_path,
            subject=meta["subject"],
            publisher=meta["version"],
            grade=meta["grade"],
            semester=meta["semester"],
        )
        logger.info("  分块数: %d", len(chunks))

        if not chunks:
            logger.warning("  无内容可分块，跳过入库")
            continue

        # 2c. 生成 Embedding 并入库
        texts = [c.content for c in chunks]
        metas = [c.metadata for c in chunks]
        ids = _make_chunk_ids(stem, len(chunks))
        vectors = embeddings.embed_documents(texts)
        collection.add(ids=ids, embeddings=vectors, documents=texts, metadatas=metas)

        # 2d. 更新索引
        index["files"][rel_path] = {
            "sha256": sha,
            "chunk_count": len(chunks),
            "metadata": meta,
        }
        total_new += len(chunks)
        logger.info("  已入库: %d chunks", len(chunks))

    # 3. 清理磁盘上已删除的文件
    removed = []
    for rel_path in list(index["files"].keys()):
        if rel_path not in current_files:
            # 构造 chunk_ids（basename 可从 rel_path 解析）
            basename = os.path.basename(rel_path)
            stem = os.path.splitext(basename)[0]
            old = index["files"][rel_path]
            old_ids = _make_chunk_ids(stem, old["chunk_count"])
            try:
                collection.delete(ids=old_ids)
                removed.append(rel_path)
                logger.info("清理已删除文件: %s (%d chunks)", rel_path, len(old_ids))
            except Exception as e:
                logger.warning("清理已删除文件失败 %s: %s", rel_path, e)

    for rp in removed:
        del index["files"][rp]

    # 4. 保存索引
    if total_new > 0 or removed:
        _save_index(index)
        logger.info("索引已更新")

    logger.info(
        "处理完成。新增/更新: %d chunks, 清理: %d 个文件",
        total_new,
        len(removed),
    )


if __name__ == "__main__":
    main()
