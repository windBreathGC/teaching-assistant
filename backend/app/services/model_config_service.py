"""模型配置管理服务：持久化存储用户添加的大模型提供商配置。

使用 SQLAlchemy 2.0 async ORM + aiosqlite。
api_key 字段在数据库中以 Fernet 对称加密存储。
"""

import base64
import hashlib
import logging
import os
import uuid
from pathlib import Path

from cryptography.fernet import Fernet
from sqlalchemy import select

from app.db.base import AsyncSessionLocal
from app.db.models import ModelConfig

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent.parent / "data"
KEY_FILE = DATA_DIR / ".encryption_key"


# ── 加密工具 ──


def _derive_fernet_key(raw: str) -> bytes:
    """从任意字符串派生 32 字节 Fernet 密钥。"""
    return base64.urlsafe_b64encode(hashlib.sha256(raw.encode()).digest())


def _get_encryption_key() -> bytes | None:
    """获取或创建加密密钥。

    优先级：
    1. 环境变量 API_KEY_ENCRYPTION_KEY
    2. backend/data/.encryption_key 文件（不存在则自动生成）
    """
    env_key = os.environ.get("API_KEY_ENCRYPTION_KEY")
    if env_key:
        try:
            Fernet(env_key.encode())
            return env_key.encode()
        except ValueError:
            return _derive_fernet_key(env_key)

    if KEY_FILE.exists():
        return KEY_FILE.read_bytes().strip()

    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        logger.warning("无法创建数据目录，api_key 将以明文存储")
        return None

    key = Fernet.generate_key()
    KEY_FILE.write_bytes(key)
    logger.info("已自动生成 api_key 加密密钥: %s", KEY_FILE)
    return key


def _get_fernet() -> Fernet | None:
    key = _get_encryption_key()
    if not key:
        return None
    try:
        return Fernet(key)
    except Exception:
        return None


def encrypt_api_key(value: str) -> str:
    """加密 api_key；若加密不可用或值为空，原样返回。"""
    f = _get_fernet()
    if not f or not value:
        return value
    return f.encrypt(value.encode()).decode()


def decrypt_api_key(value: str) -> str:
    """解密 api_key；若解密失败（旧明文数据），原样返回。"""
    f = _get_fernet()
    if not f or not value:
        return value
    try:
        return f.decrypt(value.encode()).decode()
    except Exception:
        # 兼容旧数据：解密失败说明是明文，直接返回
        return value


def _model_to_raw_dict(model: ModelConfig) -> dict:
    """将 ORM 模型转为 dict，并解密 api_key（供内部服务使用）。"""
    d = model.to_dict(mask_api_key=False)
    d["api_key"] = decrypt_api_key(d["api_key"])
    return d


# ── CRUD ──


async def list_models() -> list[dict]:
    """返回所有模型配置列表（api_key 已脱敏）。"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(ModelConfig))
        models = result.scalars().all()
        return [m.to_dict(mask_api_key=True) for m in models]


async def get_model(model_id: str) -> dict | None:
    """根据ID获取单个模型配置（api_key 已脱敏）。"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(ModelConfig).where(ModelConfig.id == model_id)
        )
        model = result.scalar_one_or_none()
        return model.to_dict(mask_api_key=True) if model else None


async def get_model_raw(model_id: str) -> dict | None:
    """根据ID获取单个模型配置的原始数据（包含真实 api_key，仅用于后端服务内部调用）。"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(ModelConfig).where(ModelConfig.id == model_id)
        )
        model = result.scalar_one_or_none()
        return _model_to_raw_dict(model) if model else None


async def get_default_model() -> dict | None:
    """获取默认模型配置的原始数据（包含真实 api_key）。"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(ModelConfig).where(ModelConfig.is_default == True)
        )
        model = result.scalar_one_or_none()
        if model:
            return _model_to_raw_dict(model)

        result = await session.execute(select(ModelConfig).limit(1))
        model = result.scalar_one_or_none()
        return _model_to_raw_dict(model) if model else None


async def add_model(data: dict) -> dict:
    """添加新模型配置。"""
    model_id = str(uuid.uuid4())[:8]
    new_model = ModelConfig(
        id=model_id,
        name=data.get("name", ""),
        base_url=data.get("base_url", ""),
        api_key=encrypt_api_key(data.get("api_key", "")),
        model_name=data.get("model_name", ""),
        temperature=float(data.get("temperature", 0.3)),
        is_default=bool(data.get("is_default", False)),
    )

    async with AsyncSessionLocal() as session:
        # 如果设为默认，取消其他默认
        if new_model.is_default:
            others = await session.execute(
                select(ModelConfig).where(ModelConfig.is_default == True)
            )
            for m in others.scalars().all():
                m.is_default = False

        # 第一个自动设为默认
        count_result = await session.execute(select(ModelConfig))
        if not count_result.scalars().first():
            new_model.is_default = True

        session.add(new_model)
        await session.commit()
        await session.refresh(new_model)

    logger.info("添加模型配置: %s (%s)", new_model.name, model_id)
    return new_model.to_dict(mask_api_key=True)


async def update_model(model_id: str, data: dict) -> dict | None:
    """更新模型配置。"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(ModelConfig).where(ModelConfig.id == model_id)
        )
        model = result.scalar_one_or_none()
        if model is None:
            return None

        if data.get("is_default"):
            others = await session.execute(
                select(ModelConfig).where(
                    ModelConfig.is_default == True,
                    ModelConfig.id != model_id,
                )
            )
            for m in others.scalars().all():
                m.is_default = False

        allowed_fields = {
            "name", "base_url", "api_key", "model_name", "temperature", "is_default"
        }
        for key, value in data.items():
            if key not in allowed_fields:
                continue
            if key == "temperature":
                model.temperature = float(value)
            elif key == "is_default":
                model.is_default = bool(value)
            elif key == "api_key":
                if value:
                    model.api_key = encrypt_api_key(value)
            else:
                setattr(model, key, value)

        await session.commit()
        await session.refresh(model)
        logger.info("更新模型配置: %s", model_id)
        return model.to_dict(mask_api_key=True)


async def delete_model(model_id: str) -> bool:
    """删除模型配置。"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(ModelConfig).where(ModelConfig.id == model_id)
        )
        model = result.scalar_one_or_none()
        if model is None:
            return False

        was_default = model.is_default
        await session.delete(model)

        if was_default:
            remaining = await session.execute(select(ModelConfig).limit(1))
            first = remaining.scalar_one_or_none()
            if first:
                first.is_default = True

        await session.commit()
        logger.info("删除模型配置: %s", model_id)
        return True


async def set_default(model_id: str) -> bool:
    """设置默认模型。"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(ModelConfig).where(ModelConfig.id == model_id)
        )
        target = result.scalar_one_or_none()
        if target is None:
            return False

        all_models = await session.execute(select(ModelConfig))
        for m in all_models.scalars().all():
            m.is_default = False

        target.is_default = True
        await session.commit()
        logger.info("设置默认模型: %s", model_id)
        return True


async def init_default_model_from_env() -> dict | None:
    """首次启动时，若数据库为空且 .env 中配置了 LLM 参数，自动创建默认模型配置。

    Returns:
        新创建的模型配置（已脱敏），或 None（已有配置或 .env 未配置）
    """
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(ModelConfig))
        if result.scalars().first():
            logger.info("已有模型配置，跳过 .env 默认模型初始化")
            return None

    try:
        from app.core.config import get_settings

        settings = get_settings()
    except Exception as e:
        logger.warning("加载配置失败，跳过默认模型初始化: %s", e)
        return None

    api_key = settings.OPENAI_API_KEY
    base_url = settings.OPENAI_BASE_URL
    model_name = settings.LLM_MODEL

    if not api_key:
        logger.info(".env 未配置 OPENAI_API_KEY，跳过默认模型初始化")
        return None

    display_name = f"默认-{model_name}"
    new_model = await add_model({
        "name": display_name,
        "base_url": base_url,
        "api_key": api_key,
        "model_name": model_name,
        "temperature": 0.3,
        "is_default": True,
    })
    logger.info("已从 .env 自动创建默认模型配置: %s", display_name)
    return new_model
