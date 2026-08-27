"""管理接口鉴权：校验 X-Admin-Token 请求头。

行为：
- 配置了 ADMIN_TOKEN：所有 /admin/* 请求必须携带匹配的 X-Admin-Token 头，否则 401。
- 未配置 ADMIN_TOKEN：放行（本地开发模式），启动后首次请求时输出一次警告日志。
"""
import logging

from fastapi import Header, HTTPException

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_warned_no_token = False


async def verify_admin_token(x_admin_token: str | None = Header(default=None)) -> None:
    settings = get_settings()

    if not settings.ADMIN_TOKEN:
        global _warned_no_token
        if not _warned_no_token:
            logger.warning(
                "未配置 ADMIN_TOKEN，管理接口处于无鉴权开发模式；"
                "生产环境请在 .env 中设置 ADMIN_TOKEN"
            )
            _warned_no_token = True
        return

    if x_admin_token != settings.ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="无效或缺失的管理令牌")
