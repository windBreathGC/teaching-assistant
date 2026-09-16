"""学习画像领域逻辑：掌握度更新（EMA + 时间遗忘衰减）与学情汇总。

纯函数为主，不碰数据库（持久化在 repositories/learner_repo.py），便于单测。
选 EMA + 指数遗忘而非 IRT/贝叶斯知识追踪：单机场景可解释性优先，
教师/家长能看懂"最近表现权重更高、两周不练会衰减"。
"""
from datetime import datetime

# EMA 平滑系数：新一次作答的权重（0.4 = 最近一次占四成，历史占六成）
EMA_ALPHA = 0.4
# 遗忘半衰期（天）：距上次练习每过 14 天，旧掌握度衰减一半
DECAY_HALF_LIFE_DAYS = 14


def update_mastery(old: float, score: float, days_since_last: float) -> float:
    """计算新掌握度：先让旧掌握度随时间遗忘，再与本次得分做指数加权平均。

    mastery_new = decay(old) * (1-α) + score * α
    decay(old)  = old * 0.5 ** (days_since_last / HALF_LIFE)
    """
    decayed = old * (0.5 ** (max(days_since_last, 0.0) / DECAY_HALF_LIFE_DAYS))
    return round(decayed * (1 - EMA_ALPHA) + score * EMA_ALPHA, 4)


def days_between(last: datetime | None, now: datetime) -> float:
    """距上次练习的天数；从未练习过返回 0（首次作答不衰减）。"""
    if last is None:
        return 0.0
    return max((now - last).total_seconds() / 86400.0, 0.0)


def summarize_progress(masteries: list[dict], attempts: list[dict]) -> dict:
    """把掌握度与作答记录聚合为学情报告 payload（供 LLM 包装或 API 直接返回）。

    - masteries: KnowledgeMastery.to_dict() 列表
    - attempts:  QuizAttempt.to_dict() 列表（仅已提交的）
    """
    total = len(attempts)
    correct = sum(1 for a in attempts if a.get("is_correct"))
    accuracy = round(correct / total, 4) if total else 0.0

    # 按掌握度升序：薄弱在前，便于报告先讲弱项
    sorted_mastery = sorted(masteries, key=lambda m: m.get("mastery", 0.0))
    weak_points = [m for m in sorted_mastery if m.get("mastery", 0.0) < 0.6]
    strong_points = [m for m in sorted_mastery if m.get("mastery", 0.0) >= 0.8]

    recent_mistakes = [a for a in attempts if a.get("is_correct") is False][:5]

    return {
        "total_attempts": total,
        "accuracy": accuracy,
        "practiced_points": len(masteries),
        "weak_points": weak_points[:5],
        "strong_points": strong_points[-5:],
        "recent_mistakes": recent_mistakes,
    }
