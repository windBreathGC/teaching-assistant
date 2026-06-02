"""后台任务管理服务：持久化存储任务状态到 SQLite 数据库。

使用 SQLAlchemy 2.0 async ORM + aiosqlite。
"""

import logging
from datetime import datetime, timedelta

from sqlalchemy import select, delete, func

from app.db.base import AsyncSessionLocal
from app.db.models import Task

logger = logging.getLogger(__name__)


async def create_task(task_id: str, task_type: str, filename: str, **extra) -> dict:
    """创建新任务。"""
    now = datetime.utcnow()
    task = Task(
        task_id=task_id,
        type=task_type,
        filename=filename,
        status=extra.get("status", "pending"),
        progress=extra.get("progress", 0),
        message=extra.get("message", "等待执行"),
        result=extra.get("result"),
        created_at=now,
        updated_at=now,
    )
    async with AsyncSessionLocal() as session:
        session.add(task)
        await session.commit()
    logger.info("创建任务: %s (%s)", task_id, task_type)
    return task.to_dict()


async def update_task(task_id: str, **kwargs) -> dict | None:
    """更新任务状态。"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Task).where(Task.task_id == task_id))
        task = result.scalar_one_or_none()
        if task is None:
            return None

        allowed = {"status", "progress", "message", "result", "type", "filename"}
        for key, value in kwargs.items():
            if key in allowed:
                setattr(task, key, value)
        task.updated_at = datetime.utcnow()

        await session.commit()
        await session.refresh(task)
        return task.to_dict()


async def get_task(task_id: str) -> dict | None:
    """获取单个任务。"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Task).where(Task.task_id == task_id))
        task = result.scalar_one_or_none()
        return task.to_dict() if task else None


async def list_tasks(offset: int = 0, limit: int = 50) -> list[dict]:
    """返回任务列表，按创建时间倒序，支持分页。"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Task).order_by(Task.created_at.desc()).offset(offset).limit(limit)
        )
        tasks = result.scalars().all()
        return [t.to_dict() for t in tasks]


async def count_tasks() -> int:
    """返回任务总数。"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(func.count()).select_from(Task))
        return result.scalar() or 0


async def cleanup_old_tasks(hours: int = 24) -> int:
    """清理超过指定小时数的已完成/失败任务。返回清理数量。"""
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            delete(Task).where(
                Task.status.in_(["completed", "failed"]),
                Task.created_at < cutoff,
            )
        )
        await session.commit()
        deleted = result.rowcount or 0
        if deleted:
            logger.info("清理 %d 个过期任务", deleted)
        return deleted
