"""Agent API Key 认证：供 AI 工坊的 MCP / REST Agent 端点使用。

与 Web 端 JWT 认证（``app.core.deps``）互相独立：
外部智能体带 ``Authorization: Bearer skjw-...`` / ``X-API-Key`` / ``?api_key=``，
这里解析出密钥并加载属主用户；后续的数据过滤复用 RBAC 的 ``owner_filter``，
即「密钥有什么权限 = 属主用户有什么权限」。
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.models.ai_workshop import AiApiKey
from app.models.user import User

#: last_used_at 写库节流：两次更新至少间隔秒数
LAST_USED_UPDATE_INTERVAL_SEC = 60.0


def hash_api_key(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def extract_api_key(request: Request) -> str | None:
    """三种取法：``Authorization: Bearer <key>``、``X-API-Key``、``?api_key=``。"""
    auth = request.headers.get("authorization") or ""
    scheme, _, token = auth.partition(" ")
    if scheme.lower() == "bearer" and token.strip():
        return token.strip()
    header_key = (request.headers.get("x-api-key") or "").strip()
    if header_key:
        return header_key
    query_key = (request.query_params.get("api_key") or "").strip()
    return query_key or None


@dataclass
class AiAgentContext:
    """一次 Agent 调用的身份上下文：密钥 + 属主用户。"""

    key: AiApiKey
    user: User


def _touch_last_used(db: Session, key: AiApiKey, ip: str | None) -> None:
    now = datetime.utcnow()
    last = key.last_used_at
    if last is not None and (now - last).total_seconds() < LAST_USED_UPDATE_INTERVAL_SEC:
        return
    key.last_used_at = now
    if ip:
        key.last_used_ip = ip[:64]
    db.commit()


def get_ai_agent(
    request: Request,
    db: Session = Depends(get_db),
) -> AiAgentContext:
    raw = extract_api_key(request)
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="缺少 API Key（Authorization: Bearer skjw-... 或 X-API-Key）",
        )
    key = db.query(AiApiKey).filter(AiApiKey.key_hash == hash_api_key(raw)).first()
    if key is None or not key.is_active or key.is_expired:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="API Key 无效或已停用/过期"
        )
    user = db.get(User, key.owner_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="密钥属主用户不可用"
        )
    _touch_last_used(db, key, request.client.host if request.client else None)
    return AiAgentContext(key=key, user=user)
