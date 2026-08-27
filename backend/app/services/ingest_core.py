"""教材向量化共享核心逻辑：稳定 chunk ID、内容指纹、增量 diff、索引读写。

ingest_textbooks.py（批量脚本）与 ingest_service.py（后台单文件）都通过本模块
操作向量库与 ingest_index.json，保证两条入库路径行为一致。

核心机制（v2）：
    1. chunk ID 由「文件名 + 内容哈希」生成（{stem}_h{hash[:12]}），与切分顺序无关，
       修改文档某一行只改变该 chunk 的哈希，其余 chunk ID 稳定可复用。
    2. 索引按 chunk 粒度记录 {id, hash}，入库时新旧 diff：
       哈希未变的 chunk 不动（复用旧向量），只 embedding 真正变更的 chunk。
    3. 先 embedding、后写库（upsert 新增 -> delete 过期）：embedding 失败时旧数据
       原样保留，不会出现「删了新数据没进」的丢失窗口。
    4. 兼容 v1 索引（按序号 ID）：文件下次变更时自动删除旧序号 ID 并迁移到 v2。
"""
import hashlib
import json
import logging
import os
import time

logger = logging.getLogger(__name__)

INDEX_VERSION = 2

# embedding 批量与重试参数（SiliconFlow 等兼容接口单次 batch 不宜过大）
EMBED_BATCH_SIZE = 32
EMBED_MAX_RETRIES = 3


def compute_sha256(file_path: str) -> str:
    """计算文件 SHA256，用于检测文件整体是否变更（决定是否进入 diff 流程）。"""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for buf in iter(lambda: f.read(8192), b""):
            h.update(buf)
    return h.hexdigest()


def load_index(index_path) -> dict:
    """读取入库索引；文件缺失或损坏时按空索引降级。

    索引损坏（如写盘途中进程被杀）不应让整个入库子系统瘫痪：
    返回空索引后，管理后台入口的「库数据自愈」会触发全量修复，
    脚本入口也会因 sha 对不上而重新入库。损坏文件备份为 .corrupt 以便排查。
    """
    path = str(index_path)
    if not os.path.exists(path):
        return {"version": INDEX_VERSION, "files": {}}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        backup = path + ".corrupt"
        logger.error("入库索引损坏（%s），按空索引降级，原文件备份为 %s", e, backup)
        try:
            os.replace(path, backup)
        except OSError:
            pass
        return {"version": INDEX_VERSION, "files": {}}


def save_index(index_path, index: dict) -> None:
    """原子写入入库索引：先写临时文件再 os.replace，避免写盘途中损坏。"""
    index["version"] = INDEX_VERSION
    path = str(index_path)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


def chunk_content_hash(content: str, metadata: dict) -> str:
    """chunk 内容指纹。

    除正文外混入 chapter / lesson：这两个字段会写入 chunk 的 metadata，
    若标题改名而正文未动，metadata 需要更新，对应 chunk 必须重新入库，
    因此标题变化也应改变指纹。
    """
    h = hashlib.sha256()
    h.update(content.encode("utf-8"))
    h.update(b"\x00")
    h.update(str(metadata.get("chapter", "")).encode("utf-8"))
    h.update(b"\x00")
    h.update(str(metadata.get("lesson", "")).encode("utf-8"))
    return h.hexdigest()


def assign_chunk_ids(stem: str, chunks) -> list[tuple[str, str, object]]:
    """为分块结果生成稳定 chunk ID，格式: {stem}_h{内容哈希[:12]}。

    同一文件内正文完全相同的 chunk（如重复出现的 boilerplate）会得到相同基础
    ID，按出现顺序追加 _1/_2 后缀保证唯一。

    Returns:
        [(chunk_id, content_hash, chunk), ...]，顺序与 chunks 一致。
    """
    seen: dict[str, int] = {}
    result: list[tuple[str, str, object]] = []
    for c in chunks:
        ch = chunk_content_hash(c.content, c.metadata)
        base = f"{stem}_h{ch[:12]}"
        n = seen.get(base, 0)
        seen[base] = n + 1
        cid = base if n == 0 else f"{base}_{n}"
        result.append((cid, ch, c))
    return result


def legacy_chunk_ids(stem: str, count: int) -> list[str]:
    """v1 按序号生成的 chunk ID（{stem}_chunk_{i}），仅用于迁移期清理旧数据。"""
    return [f"{stem}_chunk_{i}" for i in range(count)]


def entry_chunk_ids(entry: dict, stem: str) -> list[str]:
    """从索引条目还原该文件当前在向量库中的全部 chunk ID（兼容 v1/v2 两种格式）。"""
    chunks = entry.get("chunks")
    if chunks:
        return [c["id"] for c in chunks]
    return legacy_chunk_ids(stem, entry.get("chunk_count", 0))


def entry_chunk_count(entry: dict) -> int:
    """索引条目记录的 chunk 数量（兼容 v1/v2）。"""
    chunks = entry.get("chunks")
    if chunks:
        return len(chunks)
    return entry.get("chunk_count", 0)


def make_index_entry(sha: str, meta: dict, assigned: list[tuple[str, str, object]]) -> dict:
    """构建 v2 索引条目。chunk_count 冗余保留，便于旧版状态查询代码读取。"""
    return {
        "sha256": sha,
        "chunk_count": len(assigned),
        "metadata": meta,
        "chunks": [{"id": cid, "hash": ch} for cid, ch, _ in assigned],
    }


def diff_chunks(
    assigned: list[tuple[str, str, object]],
    old_ids: list[str],
    force_full: bool = False,
) -> tuple[list[tuple[str, str, object]], list[str]]:
    """对比新分块结果与库中旧 chunk，得出需要新增与需要删除的部分。

    Args:
        assigned: assign_chunk_ids 的结果。
        old_ids: 该文件当前在库中的 chunk ID（entry_chunk_ids）。
        force_full: True 时无视旧数据，全部视为新增（用于「索引在但向量库数据
            缺失」的修复场景；此时旧 ID 仍会被列入删除以清理残留）。

    Returns:
        (to_add, to_delete): to_add 为需要 embedding + upsert 的
        [(chunk_id, hash, chunk)]，to_delete 为需要从库中删除的旧 ID。
    """
    new_ids = {cid for cid, _, _ in assigned}
    baseline = set() if force_full else set(old_ids)
    to_add = [(cid, ch, c) for cid, ch, c in assigned if cid not in baseline]
    to_delete = [oid for oid in old_ids if oid not in new_ids]
    return to_add, to_delete


def embed_with_retry(embeddings, texts: list[str], progress=None) -> list[list[float]]:
    """分批 embedding，失败按指数退避重试；最终失败抛异常。

    调用方必须保证：只有本函数成功返回后才改动向量库（先 embedding 后写库），
    这样 embedding 失败时旧数据原样保留。
    """
    vectors: list[list[float]] = []
    total = len(texts)
    for i in range(0, total, EMBED_BATCH_SIZE):
        batch = texts[i:i + EMBED_BATCH_SIZE]
        for attempt in range(1, EMBED_MAX_RETRIES + 1):
            try:
                vectors.extend(embeddings.embed_documents(batch))
                break
            except Exception:
                if attempt >= EMBED_MAX_RETRIES:
                    raise
                wait = 2 ** attempt
                logger.warning(
                    "embedding 批次 %d-%d 第 %d 次失败，%ds 后重试",
                    i, i + len(batch), attempt, wait,
                )
                time.sleep(wait)
        if progress:
            progress(min(i + EMBED_BATCH_SIZE, total), total)
    return vectors
