"""SQLAlchemy ORM models."""

from datetime import datetime
from typing import Any

from sqlalchemy import String, Integer, Float, Boolean, DateTime, Text, JSON, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Task(Base):
    __tablename__ = "tasks"

    task_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "type": self.type,
            "filename": self.filename,
            "status": self.status,
            "progress": self.progress,
            "message": self.message,
            "result": self.result,
            "created_at": self.created_at.isoformat() if self.created_at else "",
            "updated_at": self.updated_at.isoformat() if self.updated_at else "",
        }


class ModelConfig(Base):
    __tablename__ = "model_configs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    base_url: Mapped[str] = mapped_column(String(255), nullable=False)
    api_key: Mapped[str] = mapped_column(String(255), nullable=False)
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    temperature: Mapped[float] = mapped_column(Float, nullable=False, default=0.3)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    def to_dict(self, mask_api_key: bool = False) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "base_url": self.base_url,
            "api_key": "" if mask_api_key else self.api_key,
            "model_name": self.model_name,
            "temperature": self.temperature,
            "is_default": self.is_default,
        }


class QuizAttempt(Base):
    """一次出题-作答尝试（学习记忆的事实表，只增不改）。

    出题时落库（status=pending），提交答案后回填判分结果（status=submitted）。
    错题本即 `is_correct=False` 的已提交记录，不单独建表。
    """

    __tablename__ = "quiz_attempts"

    quiz_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    subject: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    chapter: Mapped[str | None] = mapped_column(String(100), nullable=True)
    lesson: Mapped[str | None] = mapped_column(String(100), nullable=True)
    knowledge_point: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    difficulty: Mapped[str] = mapped_column(String(10), nullable=False, default="基础")
    question_type: Mapped[str] = mapped_column(String(10), nullable=False, default="选择")
    question: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[list | None] = mapped_column(JSON, nullable=True)
    correct_answer: Mapped[str] = mapped_column(Text, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # 以下字段提交答案后回填
    user_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    misconception: Mapped[str | None] = mapped_column(String(50), nullable=True)
    diagnosis: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    def to_dict(self) -> dict:
        return {
            "quiz_id": self.quiz_id,
            "subject": self.subject,
            "chapter": self.chapter,
            "lesson": self.lesson,
            "knowledge_point": self.knowledge_point,
            "difficulty": self.difficulty,
            "question_type": self.question_type,
            "question": self.question,
            "options": self.options,
            "correct_answer": self.correct_answer,
            "explanation": self.explanation,
            "user_answer": self.user_answer,
            "is_correct": self.is_correct,
            "score": self.score,
            "misconception": self.misconception,
            "diagnosis": self.diagnosis,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else "",
            "submitted_at": self.submitted_at.isoformat() if self.submitted_at else "",
        }


class KnowledgeMastery(Base):
    """知识点掌握度（由 quiz_attempts 聚合出的物化视图，可从事实表重建）。

    掌握度算法见 services/learner.py（EMA + 时间遗忘衰减）。
    """

    __tablename__ = "knowledge_mastery"
    __table_args__ = (UniqueConstraint("subject", "knowledge_point", name="uq_mastery_subject_kp"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    subject: Mapped[str] = mapped_column(String(50), nullable=False)
    knowledge_point: Mapped[str] = mapped_column(String(200), nullable=False)
    mastery: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    total_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    correct_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_practiced_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "subject": self.subject,
            "knowledge_point": self.knowledge_point,
            "mastery": self.mastery,
            "total_attempts": self.total_attempts,
            "correct_attempts": self.correct_attempts,
            "last_practiced_at": self.last_practiced_at.isoformat() if self.last_practiced_at else "",
        }
