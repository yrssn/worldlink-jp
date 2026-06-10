"""Zoho 邮箱登录流程的浏览器自动化步骤。"""
from __future__ import annotations

from urllib.parse import quote, urlparse

import httpx
from sqlalchemy.orm import Session

from app.models.user import User
from app.services import bitbrowser_service

DEFAULT_ZOHO_LOGIN_URL = "https://www.zoho.com/jp/mail/"


def open_zoho_mail_login(
    browser_id: str,
    login_url: str | None,
    user: User,
    db: Session,
) -> dict[str, object]:
    target_url = _normalize_login_url(login_url)
    open_result = bitbrowser_service.open_browser_window(
        browser_id,
        user,
        db,
        headless=False,
        restart=False,
    )
    open_data = open_result.get("data") or {}
    if not isinstance(open_data, dict) or not open_data:
        raise RuntimeError("BitBrowser 已打开，但未返回 CDP 连接信息；请先关再开该环境后重试")

    http_base = _extract_devtools_http(open_data)
    _create_page(http_base, target_url)
    return {
        "mail_opened": True,
        "mail_login_url": target_url,
        "mail_open_hint": open_result.get("hint"),
    }


def _normalize_login_url(login_url: str | None) -> str:
    raw = (login_url or "").strip() or DEFAULT_ZOHO_LOGIN_URL
    if raw.startswith(("http://", "https://")):
        return raw
    return f"https://{raw}"


def _extract_devtools_http(open_data: dict[str, object]) -> str:
    raw_http = str(open_data.get("http") or "").strip()
    if raw_http:
        return raw_http if raw_http.startswith(("http://", "https://")) else f"http://{raw_http}"
    raw_ws = str(open_data.get("ws") or "").strip()
    if raw_ws:
        parsed = urlparse(raw_ws)
        if parsed.netloc:
            return f"http://{parsed.netloc}"
    raise RuntimeError("BitBrowser /browser/open 返回中缺少 http/ws CDP 地址")


def _create_page(http_base: str, url: str) -> None:
    target_url = f"{http_base.rstrip('/')}/json/new?{quote(url, safe=':/?&=%')}"
    with httpx.Client(timeout=15, trust_env=False) as client:
        response = client.request("PUT", target_url)
        if response.status_code in (404, 405):
            response = client.get(target_url)
        response.raise_for_status()
