"""引用溯源：检索结果 → 前端引用卡片。纯函数，便于复用与单测。

distance 为 None（BM25-only 命中，RRF 融合后无距离）时省略 score，
前端弱化显示；按 lesson 去重，避免同一课文多个 chunk 刷屏。
"""


def to_references(docs: list[dict], max_snippet: int = 120) -> list[dict]:
    """把 retrieved_docs 投影为 references 列表。

    返回 [{lesson, chapter, subject, grade, semester, snippet, score?}]
    score = 1 - distance（l2 距离转相似度，仅供排序与强弱提示，非精确语义）。
    """
    seen: set[str] = set()
    refs: list[dict] = []
    for d in docs:
        meta = d.get("metadata") or {}
        lesson = meta.get("lesson") or "教材"
        if lesson in seen:
            continue
        seen.add(lesson)
        ref = {
            "lesson": lesson,
            "chapter": meta.get("chapter"),
            "subject": meta.get("subject"),
            "grade": meta.get("grade"),
            "semester": meta.get("semester"),
            "snippet": (d.get("content") or "")[:max_snippet],
        }
        distance = d.get("distance")
        if distance is not None:
            ref["score"] = round(1 - distance, 4)
        refs.append(ref)
    # 有 score 的排前面、按相似度降序；无 score 的保持相对顺序靠后
    refs.sort(key=lambda r: r.get("score", -1), reverse=True)
    return refs
