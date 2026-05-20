"""按登录用户 + 窗口 ID + 模式（无头/可见）缓存 BitBrowser ``/browser/open`` 返回。"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from loguru import logger

from app.core.redis_client import get_redis

_PREFIX = "bb:open:"


def _hash_key(owner_id: int) -> str:
    return f"{_PREFIX}{owner_id}"


def field_key(browser_id: str, headless: bool) -> str:
    bid = (browser_id or "").strip()
    return f"{bid}:{'headless' if headless else 'visible'}"


def _browser_id_from_field(field: str) -> str:
    if ":headless" in field or field.endswith(":visible"):
        return field.rsplit(":", 1)[0]
    return field


def save_open_result(
    owner_id: int,
    browser_id: str,
    *,
    data: dict[str, Any],
    pid: int | None = None,
    headless: bool = False,
    hint: str | None = None,
) -> None:
    bid = (browser_id or "").strip()
    if not bid:
        return
    payload = {
        "browser_id": bid,
        "pid": pid,
        "headless": headless,
        "hint": hint,
        "data": data if isinstance(data, dict) else {},
        "opened_at": datetime.now(timezone.utc).isoformat(),
    }
    fk = field_key(bid, headless)
    try:
        r = get_redis()
        r.hset(_hash_key(owner_id), fk, json.dumps(payload, ensure_ascii=False))
        # 清理旧版仅按 browser_id 存的字段
        if fk != bid:
            r.hdel(_hash_key(owner_id), bid)
    except Exception as e:  # noqa: BLE001
        logger.warning("[BitBrowser] open cache save failed owner={} field={}: {}", owner_id, fk, e)


def get_open_result(owner_id: int, browser_id: str, *, headless: bool) -> dict[str, Any] | None:
    bid = (browser_id or "").strip()
    if not bid:
        return None
    fk = field_key(bid, headless)
    try:
        raw = get_redis().hget(_hash_key(owner_id), fk)
        if not raw:
            raw = get_redis().hget(_hash_key(owner_id), bid)
    except Exception as e:  # noqa: BLE001
        logger.warning("[BitBrowser] open cache get failed: {}", e)
        return None
    if not raw:
        return None
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None


def get_any_open_result(owner_id: int, browser_id: str) -> dict[str, Any] | None:
    """返回该窗口任一模式的最近缓存（用于判断当前运行模式）。"""
    for headless in (True, False):
        c = get_open_result(owner_id, browser_id, headless=headless)
        if c:
            return c
    return None


def list_open_results(owner_id: int) -> dict[str, dict[str, Any]]:
    """field_key -> 缓存条目。"""
    try:
        raw_map = get_redis().hgetall(_hash_key(owner_id))
    except Exception as e:  # noqa: BLE001
        logger.warning("[BitBrowser] open cache list failed: {}", e)
        return {}
    out: dict[str, dict[str, Any]] = {}
    for fk, raw in (raw_map or {}).items():
        try:
            obj = json.loads(raw)
            if isinstance(obj, dict):
                out[str(fk)] = obj
        except json.JSONDecodeError:
            continue
    return out


def remove_open_result(owner_id: int, browser_id: str, *, headless: bool | None = None) -> None:
    """``headless=None`` 时删除该窗口两种模式缓存。"""
    bid = (browser_id or "").strip()
    if not bid:
        return
    try:
        r = get_redis()
        key = _hash_key(owner_id)
        if headless is None:
            r.hdel(key, field_key(bid, True), field_key(bid, False), bid)
        else:
            r.hdel(key, field_key(bid, headless), bid)
    except Exception as e:  # noqa: BLE001
        logger.warning("[BitBrowser] open cache remove failed: {}", e)


def prune_stale(owner_id: int, running_browser_ids: set[str]) -> None:
    try:
        r = get_redis()
        key = _hash_key(owner_id)
        for fk in r.hkeys(key) or []:
            bid = _browser_id_from_field(str(fk))
            if bid not in running_browser_ids:
                r.hdel(key, fk)
    except Exception as e:  # noqa: BLE001
        logger.warning("[BitBrowser] open cache prune failed: {}", e)
