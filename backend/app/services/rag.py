"""RAG服务：知识库检索"""
import json
import re
from pathlib import Path

import chromadb
from chromadb.config import Settings as ChromaSettings
from chromadb.api.models.Collection import Collection
from langchain_openai import OpenAIEmbeddings

from app.core.config import get_settings
from app.services.keyword_search import bm25_search
from app.services.textbook_parser import GRADE_SUFFIX_MAP

settings = get_settings()

# 学科ID后缀 -> 年级学期，如 "7a" -> "七年级上册"（由 GRADE_SUFFIX_MAP 反转而来）
_SUFFIX_TO_GRADE_FULL = {v: k for k, v in GRADE_SUFFIX_MAP.items()}

_chroma_client = None
_collection = None
_embeddings = None


def get_chroma_client():
    """采用本地向量数据库的方式"""
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
            # SiliconFlow 等 OpenAI 兼容接口不支持 token 数组输入和base64 编码格式，按 langchain 官方建议关闭
            check_embedding_ctx_length=False,
            model_kwargs={"encoding_format": "float"},
        )
    return _embeddings


def get_collection(name: str = "textbooks") -> Collection:
    """获取向量集合，默认名称为textbooks，必须要唯一"""
    global _collection
    if _collection is None:
        client = get_chroma_client()
        # metadata不指定的情况下，默认{"hnsw:space": "l2"}，可选 l2（欧几里得距离）、cosine（余弦相似度）、ip（内积）
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
# generated/ 优先，fallback 到 subjects/
_SUBJECTS_DIR = Path(Path(__file__).parent.parent.parent, "data", "subjects")
_GENERATED_DIR = Path(Path(__file__).parent.parent.parent, "data", "generated")


def _build_lesson_name_map() -> dict[str, str]:
    """扫描所有学科JSON配置文件，构建课文ID到名称的映射。
    优先使用 generated/ 目录的自动解析结果，fallback 到 subjects/ 手工数据。"""
    result: dict[str, str] = {}
    for data_dir in (_SUBJECTS_DIR, _GENERATED_DIR):
        if not data_dir.exists():
            continue
        for json_file in data_dir.glob("*/*.json"):
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


def _resolve_grade_semester(subject_id: str | None) -> tuple[str | None, str | None]:
    """从学科ID后缀推导年级/学期，如 chinese_7a -> ("七年级", "上册")。
    调用方一般只传 subject，grade/semester 由此补齐，避免跨年级内容混排。"""
    if not subject_id or "_" not in subject_id:
        return None, None
    suffix = subject_id.rsplit("_", 1)[1]
    full = _SUFFIX_TO_GRADE_FULL.get(suffix)
    if not full:
        return None, None
    return full[:-2], full[-2:]


def _get_doc_by_lesson_name(subject: str, 
                            lesson_name: str, 
                            grade: str | None = None, 
                            semester: str | None = None) -> list[dict]:
    """通过 metadata 中的 lesson 字段做精确子串匹配，直接定位到目标课文。
    当用户明确选了某篇课文时，这比向量检索更可靠（长文本 embedding 会被稀释）。"""
    collection = get_collection()
    where_clauses = [{"subject": _resolve_subject_name(subject)}]
    if grade:
        where_clauses.append({"grade": grade})
    if semester:
        where_clauses.append({"semester": semester})
    where = where_clauses[0] if len(where_clauses) == 1 else {"$and": where_clauses}
    results = collection.get(where=where)
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


def _vector_search(query_vector: list[float], where_filter: dict | None, n_results: int) -> list[dict]:
    """向量语义检索（召回阶段，n_results 应大于最终返回的 top_k）。"""
    collection = get_collection()
    results = collection.query(
        query_embeddings=[query_vector],
        n_results=n_results,
        where=where_filter,
    )

    docs = []
    if results and results["documents"]:
        for i, doc in enumerate(results["documents"][0]):
            docs.append({
                "id": results["ids"][0][i] if results["ids"] else None,
                "content": doc,
                "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                "distance": results["distances"][0][i] if results["distances"] else None,
            })
    return docs


def _rrf_merge(vector_hits: list[dict], bm25_hits: list[dict], k: int = 60) -> list[dict]:
    """RRF（Reciprocal Rank Fusion）融合两路召回。
    只按各自排名打分（1/(k+rank)），避开向量距离与 BM25 分数的量纲差异。"""
    scores: dict[str, float] = {}
    docs: dict[str, dict] = {}
    # 分别对向量召回和BM25召回的数据进行遍历，分别从0开始
    for hits in (vector_hits, bm25_hits):
        for rank, hit in enumerate(hits):
            # 分别基于id或者content，取出关键字
            key = hit.get("id") or hit["content"][:64]
            # 去重，如果1份chunk在向量召回和BM25召回都存在，只取第1次出现并设置它的值
            docs.setdefault(key, hit)
            # 基于RRF算法核心：计算对每篇文档 d，它在所有检索器 r 上的融合得分为 Σ 1 / (k + rank_r(d))，k按照管理取60
            scores[key] = scores.get(key, 0.0) + 1 / (k + rank + 1)
    # 基于得分，获取降序的文档结果
    return [docs[key] for key in sorted(scores, key=scores.get, reverse=True)]


def _hybrid_retrieve(query: str, 
                     query_vector: list[float], 
                     where_filter: dict | None, 
                     top_k: int, 
                     fetch_k: int) -> list[dict]:
    """混合检索：向量 + BM25 双路召回，RRF 融合后截断到 top_k"""
    # 向量检索，通过余弦相似度找到最相似的，并降序返回
    vector_hits = _vector_search(query_vector, where_filter, fetch_k)
    # bm25精确检索，找到得分最高的，并降序返回
    bm25_hits = bm25_search(query, get_collection(), where_filter, top_n=fetch_k)
    if not bm25_hits:
        return vector_hits[:top_k]
    # RRF融合
    return _rrf_merge(vector_hits, bm25_hits)[:top_k]


def retrieve(
    query: str,
    subject: str | None = None,
    chapter: str | None = None,
    lesson: str | None = None,
    grade: str | None = None,
    semester: str | None = None,
    top_k: int = 5,
    fetch_k: int = 20,
) -> list[dict]:
    """检索相关知识块（混合检索：向量 + BM25 双路召回，RRF 融合）。
    若指定了具体课文（lesson 非空），优先通过 metadata 精确匹配取出该课文。"""
    if subject and (not grade or not semester):
        d_grade, d_semester = _resolve_grade_semester(subject)
        grade = grade or d_grade
        semester = semester or d_semester

    lesson_name = get_lesson_name(lesson)
    # 如果传递了课文名称，就采用精确查找的方式
    if lesson_name and subject:
        direct = _get_doc_by_lesson_name(subject, lesson_name, grade, semester)
        if direct:
            return direct

    embeddings = get_embeddings()
    # 对查询内容query先完成向量化处理
    query_vector = embeddings.embed_query(query)
    where_filter = _build_where_filter(subject, grade, semester)
    # 采用混合检索、RRF融合的方式处理检索结果
    return _hybrid_retrieve(query, query_vector, where_filter, top_k, fetch_k)


async def aretrieve(
    query: str,
    subject: str | None = None,
    chapter: str | None = None,
    lesson: str | None = None,
    grade: str | None = None,
    semester: str | None = None,
    top_k: int = 5,
    fetch_k: int = 20,
) -> list[dict]:
    """异步检索相关知识块，逻辑同 retrieve（仅 query 向量化使用异步调用）。"""
    if subject and (not grade or not semester):
        d_grade, d_semester = _resolve_grade_semester(subject)
        grade = grade or d_grade
        semester = semester or d_semester

    lesson_name = get_lesson_name(lesson)
    # 如果同时存在课文名称和第几章，那么直接通过chromaDB的metadata筛选读取，精确检索
    if lesson_name and subject:
        direct = _get_doc_by_lesson_name(subject, lesson_name, grade, semester)
        if direct:
            return direct

    # 否则走向量的相似度+BM25精确查询的混合检索
    embeddings = get_embeddings()
    # 异步方式查询，防止阻塞主线程事件循环体；先对query通过调用embedding大模型完成向量化
    query_vector = await embeddings.aembed_query(query)
    where_filter = _build_where_filter(subject, grade, semester)
    return _hybrid_retrieve(query, query_vector, where_filter, top_k, fetch_k)


# Public alias for API layer usage
get_doc_by_lesson_name = _get_doc_by_lesson_name
