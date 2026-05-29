"""RAG服务：知识库检索"""
import json
import re
from pathlib import Path

import chromadb
from chromadb.config import Settings as ChromaSettings
from langchain_openai import OpenAIEmbeddings
from app.core.config import get_settings

settings = get_settings()

_chroma_client = None
_collection = None
_embeddings = None


def get_chroma_client():
    global _chroma_client
    if _chroma_client is None:
        _chroma_client = chromadb.PersistentClient(
            path=settings.CHROMA_PERSIST_DIR,
            settings=ChromaSettings(anonymized_telemetry=False)
        )
    return _chroma_client


def get_embeddings():
    global _embeddings
    if _embeddings is None:
        _embeddings = OpenAIEmbeddings(
            model=settings.EMBEDDING_MODEL,
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL,
        )
    return _embeddings


def get_collection(name: str = "textbooks"):
    global _collection
    if _collection is None:
        client = get_chroma_client()
        _collection = client.get_or_create_collection(name=name)
    return _collection


# 前端传的学科ID -> 入库时存的学科中文名
_SUBJECT_ID_MAP = {
    "chinese": "语文",
    "math": "数学",
    "english": "英语",
    "science": "科学",
    "social": "社会",
}

# 从 JSON 配置文件动态构建课文ID -> 课文名称映射
_DATA_DIR = Path(Path(__file__).parent.parent.parent, "data", "subjects")


def _build_lesson_name_map() -> dict[str, str]:
    """扫描所有学科JSON配置文件，构建课文ID到名称的映射。"""
    result: dict[str, str] = {}
    if not _DATA_DIR.exists():
        return result
    for json_file in _DATA_DIR.glob("*/*.json"):
        data = json.loads(json_file.read_text(encoding="utf-8"))
        for chapter in data.get("chapters", []):
            for lesson in chapter.get("lessons", []):
                lesson_id = lesson.get("id")
                lesson_name = lesson.get("name")
                if lesson_id and lesson_name:
                    result[lesson_id] = lesson_name
    return result


_LESSON_NAME_MAP = _build_lesson_name_map()


def get_lesson_name(lesson_id: str | None) -> str | None:
    return _LESSON_NAME_MAP.get(lesson_id) if lesson_id else None


def _extract_sub_lesson(doc: str, lesson_name: str) -> str:
    """从包含多个子课文的 chunk 中截取出目标课文的内容。
    适用于古诗词等以 #### 《名称》/作者 格式组织的子课文。"""
    pattern = re.compile(rf'^####\s+《{re.escape(lesson_name)}》.*$', re.MULTILINE)
    match = pattern.search(doc)
    if not match:
        return doc
    start = match.start()
    next_header = re.search(r'^#{2,4}\s+', doc[start + 1 :], re.MULTILINE)
    if next_header:
        end = start + 1 + next_header.start()
    else:
        end = len(doc)
    return doc[start:end].strip()


def _resolve_subject_name(subject_id: str) -> str:
    """将带年级后缀的学科ID解析为中文名称，如 chinese_7a -> 语文"""
    base = subject_id.split("_")[0]
    return _SUBJECT_ID_MAP.get(base, subject_id)


def _get_doc_by_lesson_name(subject: str, lesson_name: str) -> list[dict]:
    """通过 metadata 中的 lesson 字段做精确子串匹配，直接定位到目标课文。
    当用户明确选了某篇课文时，这比纯向量检索更可靠（长文本 embedding 会被稀释）。"""
    collection = get_collection()
    subject_name = _resolve_subject_name(subject)
    results = collection.get(where={"subject": subject_name})
    metadatas = results.get("metadatas") or []
    documents = results.get("documents") or []

    for i, meta in enumerate(metadatas):
        if lesson_name in meta.get("lesson", ""):
            return [{
                "content": documents[i],
                "metadata": meta,
                "distance": 0.0,
            }]

    # fallback：在文档内容中搜索（如课外古诗词等没有独立 lesson metadata 的情况）
    for i, doc in enumerate(documents):
        if f"《{lesson_name}》" in doc:
            return [{
                "content": _extract_sub_lesson(doc, lesson_name),
                "metadata": metadatas[i],
                "distance": 0.0,
            }]
    return []


def _build_where_filter(
    subject: str | None,
    grade: str | None,
    semester: str | None,
) -> dict | None:
    """构建 ChromaDB where 过滤条件。"""
    where_clauses = []
    if subject:
        subject_name = _resolve_subject_name(subject)
        where_clauses.append({"subject": subject_name})
    if grade:
        where_clauses.append({"grade": grade})
    if semester:
        where_clauses.append({"semester": semester})
    where_clauses.append({"content_type": "课文内容"})

    if len(where_clauses) == 1:
        return where_clauses[0]
    return {"$and": where_clauses}


def retrieve(
    query: str,
    subject: str | None = None,
    chapter: str | None = None,
    lesson: str | None = None,
    grade: str | None = None,
    semester: str | None = None,
    top_k: int = 5
) -> list[dict]:
    """检索相关知识块。
    若指定了具体课文（lesson 非空），优先通过 metadata 精确匹配取出该课文，
    不依赖易被长文本稀释的向量相似度。"""
    lesson_name = get_lesson_name(lesson)
    if lesson_name and subject:
        direct = _get_doc_by_lesson_name(subject, lesson_name)
        if direct:
            return direct

    # fallback：纯向量语义检索（未选具体课文时）
    collection = get_collection()
    embeddings = get_embeddings()
    query_vector = embeddings.embed_query(query)
    where_filter = _build_where_filter(subject, grade, semester)

    results = collection.query(
        query_embeddings=[query_vector],
        n_results=top_k,
        where=where_filter,
    )

    docs = []
    if results and results["documents"]:
        for i, doc in enumerate(results["documents"][0]):
            docs.append({
                "content": doc,
                "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                "distance": results["distances"][0][i] if results["distances"] else None,
            })
    return docs


async def aretrieve(
    query: str,
    subject: str | None = None,
    chapter: str | None = None,
    lesson: str | None = None,
    grade: str | None = None,
    semester: str | None = None,
    top_k: int = 5
) -> list[dict]:
    """异步检索相关知识块。
    若指定了具体课文，优先通过 metadata 精确匹配取出该课文。"""
    lesson_name = get_lesson_name(lesson)
    if lesson_name and subject:
        direct = _get_doc_by_lesson_name(subject, lesson_name)
        if direct:
            return direct

    # fallback：纯向量语义检索
    collection = get_collection()
    embeddings = get_embeddings()
    query_vector = await embeddings.aembed_query(query)
    where_filter = _build_where_filter(subject, grade, semester)

    results = collection.query(
        query_embeddings=[query_vector],
        n_results=top_k,
        where=where_filter,
    )

    docs = []
    if results and results["documents"]:
        for i, doc in enumerate(results["documents"][0]):
            docs.append({
                "content": doc,
                "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                "distance": results["distances"][0][i] if results["distances"] else None,
            })
    return docs


# Public alias for API layer usage
get_doc_by_lesson_name = _get_doc_by_lesson_name
