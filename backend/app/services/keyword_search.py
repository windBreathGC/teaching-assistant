"""关键词检索：基于 bm25s 的 BM25 索引，按过滤条件缓存，入库后失效。

中文分词采用字符级 单字 + 二元组（对齐 Elasticsearch CJK analyzer 的做法），
无需词典、不怕未登录词，避免引入停更的分词库。
"""
import json
import logging
import re
import threading

import bm25s
from chromadb.api.models.Collection import Collection

logger = logging.getLogger(__name__)

# 英文单词/数字按整词保留，连续中文按 run 切出后做单字 + bigram
_TOKEN_RUN = re.compile(r"[a-zA-Z0-9]+|[\u4e00-\u9fff]+")


def tokenize(text: str) -> list[str]:
    """中英文混合分词：英文/数字按整词，中文按单字 + 二元组。"""
    tokens: list[str] = []
    for m in _TOKEN_RUN.finditer(text.lower()):
        seg = m.group(0)
        if seg.isascii():
            tokens.append(seg)
        else:
            tokens.extend(seg)
            tokens.extend(seg[i:i + 2] for i in range(len(seg) - 1))
    return tokens


# 缓存：where 条件 -> (retriever, ids, documents, metadatas)
_cache: dict[str, tuple] = {}
_lock = threading.Lock()


def _cache_key(where_filter: dict | None) -> str:
    if not where_filter:
        return ""
    return json.dumps(where_filter, sort_keys=True, ensure_ascii=False)


def _build_index(collection: Collection, where_filter: dict | None) -> tuple[bm25s.BM25, list, list, list] | None:
    """从 ChromaDB 取出满足条件的全部文档并构建 BM25 索引。"""
    results = collection.get(where=where_filter, include=["documents", "metadatas"])
    ids = results.get("ids") or []
    docs = results.get("documents") or []
    metas = results.get("metadatas") or []
    if not docs:
        return None

    retriever = bm25s.BM25()
    retriever.index([tokenize(d) for d in docs], show_progress=False)
    return retriever, ids, docs, metas


def invalidate_cache() -> None:
    """清空全部 BM25 索引缓存。教材入库/删除后必须调用。"""
    with _lock:
        _cache.clear()


def bm25_search(query: str, collection: Collection, where_filter: dict | None, top_n: int = 20) -> list[dict]:
    """对满足 where 条件的文档做 BM25 关键词检索，索引按过滤条件缓存。

    Returns:
        [{"id", "content", "metadata", "bm25": score}, ...] 按分数降序，零分结果已剔除
    """
    key = _cache_key(where_filter)
    with _lock:
        entry = _cache.get(key)

    if entry is None:
        try:
            entry = _build_index(collection, where_filter)
        except Exception as e:
            logger.warning("BM25 索引构建失败: %s", e)
            return []
        if entry is None:
            return []
        with _lock:
            _cache[key] = entry
        logger.info("BM25 索引已构建: %d 文档, filter=%s", len(entry[1]), key or "无")

    retriever, ids, docs, metas = entry
    k = min(top_n, len(docs))
    try:
        # 基于查询的tokens，获取top-k条文档；return_as默认为true，返回检索的文档和对应的得分
        indices, scores = retriever.retrieve([tokenize(query)], k=k, show_progress=False)
    except Exception as e:
        logger.warning("BM25 检索失败: %s", e)
        return []

    hits = []
    for idx, score in zip(indices[0].tolist(), scores[0].tolist()):
        if score <= 0:
            continue
        hits.append({
            "id": ids[idx],
            "content": docs[idx],
            "metadata": metas[idx],
            "bm25": float(score),
        })
    return hits
