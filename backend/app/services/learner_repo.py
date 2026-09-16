"""学习画像数据访问层：出题落库、提交判分、掌握度更新、学情聚合。

遵循 task_service 的范式：每个函数自管 AsyncSessionLocal 会话，返回 dict。
掌握度"怎么算"在 services/learner.py，本层只负责存取。
"""
import logging
import uuid
from datetime import datetime, timedelta

from sqlalchemy import select, update, func

from app.db.base import AsyncSessionLocal
from app.db.models import QuizAttempt, KnowledgeMastery
from app.services import learner

logger = logging.getLogger(__name__)


async def create_attempt(
    subject: str,
    chapter: str | None,
    lesson: str | None,
    quiz: dict,
    difficulty: str,
    question_type: str,
) -> str:
    """出题即落库（status=pending），返回 quiz_id。正确答案不出库、不经前端流转。"""
    quiz_id = uuid.uuid4().hex
    attempt = QuizAttempt(
        quiz_id=quiz_id,
        subject=subject,
        chapter=chapter,
        lesson=lesson,
        knowledge_point=quiz.get("knowledge_point") or chapter or "通用知识点",
        difficulty=difficulty,
        question_type=question_type,
        question=quiz.get("question", ""),
        options=quiz.get("options"),
        correct_answer=quiz.get("correct_answer", ""),
        explanation=quiz.get("explanation", ""),
        status="pending",
    )
    async with AsyncSessionLocal() as session:
        session.add(attempt)
        await session.commit()
    logger.info("出题落库: %s (%s)", quiz_id, subject)
    return quiz_id


async def get_attempt(quiz_id: str) -> dict | None:
    """按 quiz_id 取作答记录。"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(QuizAttempt).where(QuizAttempt.quiz_id == quiz_id)
        )
        attempt = result.scalar_one_or_none()
        return attempt.to_dict() if attempt else None


async def submit_attempt(quiz_id: str, user_answer: str, grade: dict) -> dict | None:
    """回填判分结果并同事务更新知识点掌握度（EMA + 遗忘衰减）。

    grade: grading.grade_answer 的返回 {is_correct, score, misconception, diagnosis}
    返回 {"attempt": ..., "mastery": ...}；quiz_id 不存在返回 None。

    幂等与并发安全：判重用条件更新（WHERE status='pending'）在写事务内完成——
    双击提交/并发请求时只有一方能完成认领（rowcount=1），另一方 rowcount=0
    直接读取既有结果返回，掌握度绝不会被重复累计，也不会触发唯一键冲突。
    """
    async with AsyncSessionLocal() as session:
        now = datetime.utcnow()
        result = await session.execute(
            update(QuizAttempt)
            .where(QuizAttempt.quiz_id == quiz_id, QuizAttempt.status == "pending")
            .values(
                user_answer=user_answer,
                is_correct=grade["is_correct"],
                score=grade["score"],
                misconception=grade.get("misconception"),
                diagnosis=grade.get("diagnosis"),
                status="submitted",
                submitted_at=now,
            )
        )

        if result.rowcount == 0:
            # 已被并发提交（或 quiz_id 不存在）：幂等读取既有结果
            attempt = (
                await session.execute(
                    select(QuizAttempt).where(QuizAttempt.quiz_id == quiz_id)
                )
            ).scalar_one_or_none()
            if attempt is None:
                return None
            mastery = await _get_mastery(session, attempt.subject, attempt.knowledge_point)
            return {"attempt": attempt.to_dict(), "mastery": mastery.to_dict() if mastery else None}

        # 认领成功：同事务更新掌握度（仅此一方会执行，EMA 不会重复累计）
        attempt = (
            await session.execute(
                select(QuizAttempt).where(QuizAttempt.quiz_id == quiz_id)
            )
        ).scalar_one()

        mastery = await _get_mastery(session, attempt.subject, attempt.knowledge_point)
        if mastery is None:
            mastery = KnowledgeMastery(
                subject=attempt.subject,
                knowledge_point=attempt.knowledge_point,
                mastery=0.0,
                total_attempts=0,
                correct_attempts=0,
                last_practiced_at=now,
            )
            session.add(mastery)

        days = learner.days_between(mastery.last_practiced_at if mastery.total_attempts else None, now)
        mastery.mastery = learner.update_mastery(mastery.mastery, grade["score"], days)
        mastery.total_attempts += 1
        if grade["is_correct"]:
            mastery.correct_attempts += 1
        mastery.last_practiced_at = now

        await session.commit()
        await session.refresh(attempt)
        await session.refresh(mastery)
        logger.info(
            "判分落库: %s correct=%s mastery=%.2f (%s)",
            quiz_id, grade["is_correct"], mastery.mastery, attempt.knowledge_point,
        )
        return {"attempt": attempt.to_dict(), "mastery": mastery.to_dict()}


async def _get_mastery(session, subject: str, knowledge_point: str) -> KnowledgeMastery | None:
    result = await session.execute(
        select(KnowledgeMastery).where(
            KnowledgeMastery.subject == subject,
            KnowledgeMastery.knowledge_point == knowledge_point,
        )
    )
    return result.scalar_one_or_none()


async def get_subject_report(subject: str) -> dict:
    """聚合某学科的学情数据：掌握度列表 + 已提交作答 → 学情 payload。"""
    async with AsyncSessionLocal() as session:
        mastery_rows = (
            await session.execute(
                select(KnowledgeMastery).where(KnowledgeMastery.subject == subject)
            )
        ).scalars().all()
        attempt_rows = (
            await session.execute(
                select(QuizAttempt)
                .where(QuizAttempt.subject == subject, QuizAttempt.status == "submitted")
                .order_by(QuizAttempt.submitted_at.desc())
            )
        ).scalars().all()

        # 近 7 天作答数
        cutoff = datetime.utcnow() - timedelta(days=7)
        recent_7d = (
            await session.execute(
                select(func.count())
                .select_from(QuizAttempt)
                .where(
                    QuizAttempt.subject == subject,
                    QuizAttempt.status == "submitted",
                    QuizAttempt.submitted_at >= cutoff,
                )
            )
        ).scalar() or 0

    report = learner.summarize_progress(
        [m.to_dict() for m in mastery_rows],
        [a.to_dict() for a in attempt_rows],
    )
    report["subject"] = subject
    report["recent_7d_attempts"] = recent_7d
    return report


async def list_mistakes(subject: str | None = None, limit: int = 20) -> list[dict]:
    """错题本：已提交且答错的记录，按提交时间倒序。"""
    clauses = [QuizAttempt.status == "submitted", QuizAttempt.is_correct == False]  # noqa: E712
    if subject:
        clauses.append(QuizAttempt.subject == subject)
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(QuizAttempt)
            .where(*clauses)
            .order_by(QuizAttempt.submitted_at.desc())
            .limit(limit)
        )
        return [a.to_dict() for a in result.scalars().all()]
