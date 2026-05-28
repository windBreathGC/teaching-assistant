"""RAG服务：知识库检索"""
import re

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

# 课文ID -> 课文名称（用于query增强）
_LESSON_NAME_MAP = {
    "c1_l1": "春",
    "c1_l2": "济南的冬天",
    "c1_l3": "雨的四季",
    "c1_l4": "古代诗歌四首",
    "c2_l1": "秋天的怀念",
    "c2_l2": "散步",
    "c2_l3": "散文诗二首",
    "c2_l4": "《世说新语》二则",
    "c3_l1": "从百草园到三味书屋",
    "c3_l2": "再塑生命的人",
    "c3_l3": "《论语》十二章",
    "c3_l4": "写作：如何突出中心",
    "c3_l5": "名著导读：《朝花夕拾》",
    "c4_l1": "纪念白求恩",
    "c4_l2": "植树的牧羊人",
    "c4_l3": "走一步，再走一步",
    "c4_l4": "诫子书",
    "c5_l1": "猫",
    "c5_l2": "动物笑谈",
    "c5_l3": "狼",
    "c6_l1": "皇帝的新装",
    "c6_l2": "天上的街市",
    "c6_l3": "女娲造人",
    "c6_l4": "寓言四则",
    "c3_poem": "课外古诗词4首（一）",
    "c6_poem": "课外古诗词4首（二）",
    # 数学
    "m1_l1": "1.1 从自然数到有理数",
    "m1_l2": "1.2 数轴",
    "m1_l3": "1.3 绝对值",
    "m1_l4": "1.4 有理数的大小比较",
    "m2_l1": "2.1 有理数的加法",
    "m2_l2": "2.2 有理数的减法",
    "m2_l3": "2.3 有理数的乘法",
    "m2_l4": "2.4 有理数的除法",
    "m2_l5": "2.5 有理数的乘方",
    "m2_l6": "2.6 有理数的混合运算",
    "m2_l7": "2.7 近似数",
    "m3_l1": "3.1 平方根",
    "m3_l2": "3.2 算术平方根",
    "m3_l3": "3.3 立方根",
    "m3_l4": "3.4 实数",
    "m4_l1": "4.1 用字母表示数",
    "m4_l2": "4.2 代数式",
    "m4_l3": "4.3 整式",
    "m4_l4": "4.4 合并同类项",
    "m4_l5": "4.5 整式的加减",
    "m5_l1": "5.1 一元一次方程",
    "m5_l2": "5.2 等式的基本性质",
    "m5_l3": "5.3 一元一次方程的解法",
    "m5_l4": "5.4 一元一次方程的应用",
    "m6_l1": "6.1 几何图形",
    "m6_l2": "6.2 直线、射线、线段",
    "m6_l3": "6.3 角",
    "m6_l4": "6.4 余角和补角",
    "m6_l5": "6.5 直线的相交",
    # 英语（加章节前缀以区分不同单元）
    "e_s1_l1": "Starter Unit 1 Good morning! - Section A",
    "e_s1_l2": "Starter Unit 1 Good morning! - Self Check",
    "e_s2_l1": "Starter Unit 2 What's this in English? - Section A",
    "e_s2_l2": "Starter Unit 2 What's this in English? - Self Check",
    "e_s3_l1": "Starter Unit 3 What color is it? - Section A",
    "e_s3_l2": "Starter Unit 3 What color is it? - Self Check",
    "e1_l1": "Unit 1 My name's Gina. - Section A",
    "e1_l2": "Unit 1 My name's Gina. - Section B",
    "e1_l3": "Unit 1 My name's Gina. - Self Check",
    "e2_l1": "Unit 2 This is my sister. - Section A",
    "e2_l2": "Unit 2 This is my sister. - Section B",
    "e2_l3": "Unit 2 This is my sister. - Self Check",
    "e3_l1": "Unit 3 Is this your pencil? - Section A",
    "e3_l2": "Unit 3 Is this your pencil? - Section B",
    "e3_l3": "Unit 3 Is this your pencil? - Self Check",
    "e4_l1": "Unit 4 Where's my schoolbag? - Section A",
    "e4_l2": "Unit 4 Where's my schoolbag? - Section B",
    "e4_l3": "Unit 4 Where's my schoolbag? - Self Check",
    "e5_l1": "Unit 5 Do you have a soccer ball? - Section A",
    "e5_l2": "Unit 5 Do you have a soccer ball? - Section B",
    "e5_l3": "Unit 5 Do you have a soccer ball? - Self Check",
    "e6_l1": "Unit 6 Do you like bananas? - Section A",
    "e6_l2": "Unit 6 Do you like bananas? - Section B",
    "e6_l3": "Unit 6 Do you like bananas? - Self Check",
    "e7_l1": "Unit 7 How much are these socks? - Section A",
    "e7_l2": "Unit 7 How much are these socks? - Section B",
    "e7_l3": "Unit 7 How much are these socks? - Self Check",
    "e8_l1": "Unit 8 When is your birthday? - Section A",
    "e8_l2": "Unit 8 When is your birthday? - Section B",
    "e8_l3": "Unit 8 When is your birthday? - Self Check",
    "e9_l1": "Unit 9 My favorite subject is science. - Section A",
    "e9_l2": "Unit 9 My favorite subject is science. - Section B",
    "e9_l3": "Unit 9 My favorite subject is science. - Self Check",
    # 科学
    "s1_l1": "1.1 科学并不神秘",
    "s1_l2": "1.2 走进科学实验室",
    "s1_l3": "1.3 科学观察",
    "s1_l4": "1.4 科学测量",
    "s1_l5": "1.5 科学探究",
    "s2_l1": "2.1 生物与非生物",
    "s2_l2": "2.2 细胞",
    "s2_l3": "2.3 生物体的结构层次",
    "s2_l4": "2.4 常见的动物",
    "s2_l5": "2.5 常见的植物",
    "s3_l1": "3.1 地球的形状和内部结构",
    "s3_l2": "3.2 地球仪和地图",
    "s3_l3": "3.3 地球的运动",
    "s4_l1": "4.1 物质的构成",
    "s4_l2": "4.2 质量的测量",
    "s4_l3": "4.3 物质的密度",
    "s4_l4": "4.4 物质的比热",
    "s4_l5": "4.5 熔化与凝固",
    "s4_l6": "4.6 汽化与液化",
    "s4_l7": "4.7 升华与凝华",
    # 社会（教材小节标题带冒号）
    "so1_l1": "第一课：我的家在哪里",
    "so1_l2": "第二课：在社会中成长",
    "so1_l3": "第三课：社会规则与秩序",
    "so2_l1": "第四课：大洲和大洋",
    "so2_l2": "第五课：世界地形与气候",
    "so2_l3": "第六课：世界的人口与人种",
    "so2_l4": "第七课：世界的语言与宗教",
    "so2_l5": "第八课：世界的发展差异",
    "so3_l1": "第九课：疆域与行政区划",
    "so3_l2": "第十课：自然环境",
    "so3_l3": "第十一课：自然资源",
    "so3_l4": "第十二课：人口与民族",
    "so4_l1": "第十三课：北方地区",
    "so4_l2": "第十四课：南方地区",
    "so4_l3": "第十五课：西北地区",
    "so4_l4": "第十六课：青藏地区",
    "so5_l1": "第十七课：认识区域",
    "so5_l2": "第十八课：区域发展",
    "so5_l3": "第十九课：区域联系",
    "so5_l4": "第二十课：走进家乡",
}


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
