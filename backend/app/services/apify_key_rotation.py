"""Apify Key 自动轮转与可用性管理。

当某个 Key 额度不足或出错时，自动切换到下一个可用的 Key。
"""
from __future__ import annotations

from typing import Optional

from loguru import logger
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.apify_key import ApifyKey


class ApifyKeyRotation:
    """Apify Key 轮转管理器。"""

    def __init__(self) -> None:
        self._current_key_id: int | None = None

    def get_available_key(self, db: Session | None = None) -> Optional[ApifyKey]:
        """获取当前可用的 Apify Key。

        优先返回标记为 is_default=True 的可用 Key；
        若无则返回第一个 is_available=True 的 Key。
        """
        close_db = False
        if db is None:
            db = SessionLocal()
            close_db = True

        try:
            # 优先返回默认 Key（若可用）
            default_key = (
                db.query(ApifyKey)
                .filter(ApifyKey.is_default.is_(True), ApifyKey.is_available.is_(True))
                .first()
            )
            if default_key:
                return default_key

            # 否则返回第一个可用的 Key
            available_key = (
                db.query(ApifyKey)
                .filter(ApifyKey.is_available.is_(True))
                .order_by(ApifyKey.id)
                .first()
            )
            return available_key
        finally:
            if close_db:
                db.close()

    def mark_key_unavailable(self, key_id: int, reason: str = "") -> None:
        """标记某个 Key 为不可用。

        Args:
            key_id: Apify Key ID
            reason: 不可用原因（如 "额度不足" 或 "认证失败"）
        """
        db = SessionLocal()
        try:
            key = db.query(ApifyKey).filter(ApifyKey.id == key_id).first()
            if not key:
                return

            key.is_available = False
            if reason:
                key.remark = f"{key.remark or ''}\n[不可用] {reason}".strip()
            db.commit()
            logger.warning("[ApifyKeyRotation] Key#{} marked unavailable: {}", key_id, reason)
        except Exception as e:
            logger.exception("[ApifyKeyRotation] Error marking key#{} unavailable: {}", key_id, e)
        finally:
            db.close()

    def mark_key_available(self, key_id: int) -> None:
        """标记某个 Key 为可用（恢复）。"""
        db = SessionLocal()
        try:
            key = db.query(ApifyKey).filter(ApifyKey.id == key_id).first()
            if not key:
                return

            key.is_available = True
            db.commit()
            logger.info("[ApifyKeyRotation] Key#{} marked available", key_id)
        except Exception as e:
            logger.exception("[ApifyKeyRotation] Error marking key#{} available: {}", key_id, e)
        finally:
            db.close()

    def handle_key_error(self, key_id: int, error: str) -> Optional[ApifyKey]:
        """处理 Key 错误，尝试轮转到下一个可用 Key。

        Args:
            key_id: 出错的 Key ID
            error: 错误信息

        Returns:
            下一个可用的 Key，若无则返回 None
        """
        # 判断错误类型，决定是否标记为不可用
        if "memory limit" in error.lower() or "exceeded" in error.lower():
            self.mark_key_unavailable(key_id, f"额度不足: {error[:100]}")
        elif "unauthorized" in error.lower() or "invalid" in error.lower():
            self.mark_key_unavailable(key_id, f"认证失败: {error[:100]}")
        elif "rate limit" in error.lower():
            # 速率限制通常是临时的，不标记为不可用
            logger.warning("[ApifyKeyRotation] Key#{} hit rate limit: {}", key_id, error)
        else:
            logger.warning("[ApifyKeyRotation] Key#{} error: {}", key_id, error)

        # 尝试获取下一个可用的 Key
        next_key = self.get_available_key()
        if next_key and next_key.id != key_id:
            logger.info("[ApifyKeyRotation] Switched from Key#{} to Key#{}", key_id, next_key.id)
            return next_key

        return None


# 全局 Key 轮转管理器
apify_key_rotation = ApifyKeyRotation()
