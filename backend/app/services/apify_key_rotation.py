"""Apify Key 自动轮转与可用性管理。

当某个 Key 额度不足 / 认证失败时，自动标记为已用尽（``exhausted_at``）并切换到
下一个可用 Key。被 :func:`app.services.apify_service._run_actor` 调用，对所有抓取
（Facebook + Instagram）统一生效。

可用性以 ``ApifyKey.exhausted_at`` 为准：``NULL`` 表示可用，非空表示本月已用尽
（与「Apify Key 管理」里手动标记 / 解除的逻辑一致）。
"""
from __future__ import annotations

from datetime import datetime

from loguru import logger
from sqlalchemy.orm import Session

from app.models.apify_key import ApifyKey

# 触发 Key 轮转的错误特征（额度耗尽 / 认证失败）。
# 注意：内存超限（memory limit）是单次运行配置问题，不代表 Key 不可用，故不在此列。
_EXHAUSTED_PATTERNS = (
    "usage hard limit",
    "monthly usage",
    "usage limit",
    "out of credit",
    "insufficient credit",
    "not enough",
    "quota",
    "payment required",
    "platform usage",
    "free plan",
    "trial",
    "402",
)
_AUTH_PATTERNS = (
    "unauthorized",
    "authentication",
    "invalid token",
    "invalid api",
    "user was not found",
    "token is not valid",
    "401",
)


class ApifyKeyRotation:
    """Apify Key 轮转管理器（基于 ``exhausted_at``）。"""

    @staticmethod
    def classify_error(error: str) -> str:
        """把错误信息归类为 ``exhausted`` / ``auth`` / ``other``。

        只有 ``exhausted`` 与 ``auth`` 会触发标记不可用 + 轮转下一个 Key；
        其余（输入错误、内存超限、超时、限流等）一律不轮转，原样抛出。
        """
        if not error:
            return "other"
        low = error.lower()
        # 内存超限是运行配置问题，明确排除
        if "memory" in low and ("limit" in low or "exceeded" in low):
            return "other"
        if any(p in low for p in _AUTH_PATTERNS):
            return "auth"
        if any(p in low for p in _EXHAUSTED_PATTERNS):
            return "exhausted"
        return "other"

    @staticmethod
    def get_candidate_keys(db: Session) -> list[ApifyKey]:
        """返回所有 Key，可用（未用尽）的排前面，默认 Key 再优先。

        排序键：(已用尽?, 非默认?, id)，因此顺序为：
        未用尽+默认 → 未用尽+其它 → 已用尽+默认 → 已用尽+其它。
        即便全部已用尽，也会作为「最后兜底」返回，避免误标记导致彻底无法抓取。
        """
        try:
            rows = db.query(ApifyKey).filter(ApifyKey.token.isnot(None)).all()
        except Exception as e:  # noqa: BLE001
            logger.warning("[ApifyKeyRotation] 读取 Key 列表失败: {}", e)
            return []
        rows = [r for r in rows if r.token]
        rows.sort(key=lambda k: (k.exhausted_at is not None, not k.is_default, k.id))
        return rows

    @staticmethod
    def mark_exhausted(db: Session, key_id: int, reason: str = "") -> None:
        """标记某个 Key 已用尽（``exhausted_at`` = now），并把原因追加到备注。"""
        try:
            key = db.get(ApifyKey, key_id)
            if not key:
                return
            key.exhausted_at = datetime.utcnow()
            if reason:
                tag = f"[自动标记不可用] {reason}"
                key.remark = f"{(key.remark or '').strip()}\n{tag}".strip()
            db.commit()
            logger.warning(
                "[ApifyKeyRotation] Key#{} 标记为已用尽: {}", key_id, reason
            )
        except Exception as e:  # noqa: BLE001
            db.rollback()
            logger.exception(
                "[ApifyKeyRotation] 标记 Key#{} 已用尽失败: {}", key_id, e
            )


# 全局 Key 轮转管理器
apify_key_rotation = ApifyKeyRotation()
