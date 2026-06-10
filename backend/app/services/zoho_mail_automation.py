"""Zoho 邮箱登录流程的浏览器自动化步骤。"""
from __future__ import annotations

import json
import time
from itertools import count
from urllib.parse import quote, urlparse

import httpx
from loguru import logger
from sqlalchemy.orm import Session
from websockets.sync.client import connect

from app.models.user import User
from app.services import bitbrowser_service

DEFAULT_ZOHO_LOGIN_URL = (
    "https://accounts.zoho.com/signin?service_language=ja&servicename=VirtualOffice"
    "&signupurl=https://www.zoho.com/jp/mail/zohomail-pricing.html"
    "&serviceurl=https://mail.zoho.com"
)


def open_zoho_mail_login(
    browser_id: str,
    login_url: str | None,
    email: str,
    password: str | None,
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
    closed_count = _close_zoho_pages(http_base)
    page_ws = _create_page(http_base, target_url)
    with CdpPage(page_ws) as page:
        page.call("Page.enable")
        page.call("Runtime.enable")
        _wait_page_ready(page)
        time.sleep(1)
        email_submitted = _submit_zoho_email(page, email)
        password_submitted = False
        if email_submitted and password:
            password_submitted = _submit_zoho_password(page, password)
        final_url = _current_url(page)
    return {
        "mail_opened": True,
        "mail_login_url": target_url,
        "mail_final_url": final_url,
        "mail_closed_tab_count": closed_count,
        "mail_email_submitted": email_submitted,
        "mail_password_submitted": password_submitted,
        "mail_open_hint": open_result.get("hint"),
    }


class CdpPage:
    def __init__(self, ws_url: str):
        self.ws_url = ws_url
        self._ids = count(1)
        self._ws = None

    def __enter__(self) -> "CdpPage":
        self._ws = connect(self.ws_url, open_timeout=15)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._ws is not None:
            self._ws.close()

    def call(
        self,
        method: str,
        params: dict[str, object] | None = None,
        *,
        timeout: float = 15,
    ) -> dict[str, object]:
        if self._ws is None:
            raise RuntimeError("CDP 未连接")
        msg_id = next(self._ids)
        self._ws.send(json.dumps({"id": msg_id, "method": method, "params": params or {}}))
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError(f"CDP 调用超时: {method}")
            raw = self._ws.recv(timeout=remaining)
            parsed = json.loads(raw)
            if not isinstance(parsed, dict):
                continue
            data: dict[str, object] = parsed
            if data.get("id") != msg_id:
                continue
            if data.get("error"):
                raise RuntimeError(f"CDP 调用失败 {method}: {data['error']}")
            result = data.get("result") or {}
            return result if isinstance(result, dict) else {}

    def evaluate(self, expression: str, *, timeout: float = 15) -> object:
        result = self.call(
            "Runtime.evaluate",
            {
                "expression": expression,
                "awaitPromise": True,
                "returnByValue": True,
            },
            timeout=timeout,
        )
        remote = result.get("result") or {}
        if not isinstance(remote, dict):
            return None
        return remote.get("value")


def _normalize_login_url(login_url: str | None) -> str:
    raw = (login_url or "").strip() or DEFAULT_ZOHO_LOGIN_URL
    if "zoho.com/jp/mail" in raw and "accounts.zoho.com/signin" not in raw:
        return DEFAULT_ZOHO_LOGIN_URL
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


def _create_page(http_base: str, url: str) -> str:
    target_url = f"{http_base.rstrip('/')}/json/new?{quote(url, safe=':/?&=%')}"
    with httpx.Client(timeout=15, trust_env=False) as client:
        response = client.request("PUT", target_url)
        if response.status_code in (404, 405):
            response = client.get(target_url)
        response.raise_for_status()
        data = response.json()
    ws_url = data.get("webSocketDebuggerUrl")
    if not ws_url:
        raise RuntimeError("创建 Zoho 邮箱登录页失败：DevTools 未返回页面 WebSocket")
    return str(ws_url)


def _close_zoho_pages(http_base: str) -> int:
    closed = 0
    with httpx.Client(timeout=10, trust_env=False) as client:
        try:
            response = client.get(f"{http_base.rstrip('/')}/json/list")
            response.raise_for_status()
            targets = response.json()
        except Exception as e:  # noqa: BLE001
            logger.debug("[Zoho mail] list targets skipped: {}", e)
            return 0
        if not isinstance(targets, list):
            return 0
        for target in targets:
            if not isinstance(target, dict):
                continue
            target_id = str(target.get("id") or "")
            target_url = str(target.get("url") or "")
            if not target_id or "zoho.com" not in target_url:
                continue
            try:
                client.get(f"{http_base.rstrip('/')}/json/close/{target_id}")
                closed += 1
            except Exception as e:  # noqa: BLE001
                logger.debug("[Zoho mail] close target {} skipped: {}", target_id, e)
    return closed


def _wait_page_ready(page: CdpPage, timeout: float = 20) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = page.evaluate("document.readyState", timeout=5)
        if state in {"interactive", "complete"}:
            return
        time.sleep(0.3)


def _current_url(page: CdpPage) -> str:
    value = page.evaluate("window.location.href", timeout=5)
    return str(value or "")


def _submit_zoho_email(page: CdpPage, email: str) -> bool:
    submitted = bool(page.evaluate(_fill_zoho_email_script(email), timeout=8))
    if submitted:
        _wait_for_password_input(page)
    return submitted


def _submit_zoho_password(page: CdpPage, password: str) -> bool:
    if not _wait_for_password_input(page):
        return False
    submitted = bool(page.evaluate(_fill_zoho_password_script(password), timeout=8))
    if submitted:
        time.sleep(2)
    return submitted


def _wait_for_password_input(page: CdpPage, timeout: float = 12) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        present = page.evaluate(
            "Boolean(Array.from(document.querySelectorAll('input[type=\"password\"]')).find((el) => {"
            "const r = el.getBoundingClientRect();"
            "const s = getComputedStyle(el);"
            "return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';"
            "}))",
            timeout=5,
        )
        if bool(present):
            return True
        time.sleep(0.5)
    return False


def _fill_zoho_email_script(email: str) -> str:
    email_json = json.dumps(email)
    return f"""
(() => {{
  const email = {email_json};
  const visible = (el) => {{
    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
  }};
  const textOf = (el) => (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
  const setValue = (input, value) => {{
    const proto = Object.getPrototypeOf(input);
    const desc = Object.getOwnPropertyDescriptor(proto, 'value');
    if (desc && desc.set) desc.set.call(input, value);
    else input.value = value;
    input.dispatchEvent(new Event('input', {{ bubbles: true }}));
    input.dispatchEvent(new Event('change', {{ bubbles: true }}));
  }};
  const inputs = Array.from(document.querySelectorAll('input'))
    .filter(visible)
    .filter((el) => !el.disabled && !el.readOnly && (el.type || 'text') !== 'hidden');
  const input = inputs.find((el) => (el.type || '').toLowerCase() === 'email')
    || inputs.find((el) => /(email|mail|login|lid|identifier)/i.test(`${{el.id}} ${{el.name}} ${{el.placeholder}}`))
    || inputs[0];
  if (!input) return false;
  input.focus();
  setValue(input, email);
  const buttons = Array.from(document.querySelectorAll('button,input[type="button"],input[type="submit"],[role="button"]')).filter(visible);
  const button = buttons.find((el) => /^(次へ|Next)$/i.test(textOf(el) || el.value || ''))
    || buttons.find((el) => /(次へ|Next)/i.test(textOf(el) || el.value || ''));
  if (!button) return false;
  setTimeout(() => button.click(), 250);
  return true;
}})()
"""


def _fill_zoho_password_script(password: str) -> str:
    password_json = json.dumps(password)
    return f"""
(() => {{
  const password = {password_json};
  const visible = (el) => {{
    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
  }};
  const textOf = (el) => (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
  const setValue = (input, value) => {{
    const proto = Object.getPrototypeOf(input);
    const desc = Object.getOwnPropertyDescriptor(proto, 'value');
    if (desc && desc.set) desc.set.call(input, value);
    else input.value = value;
    input.dispatchEvent(new Event('input', {{ bubbles: true }}));
    input.dispatchEvent(new Event('change', {{ bubbles: true }}));
  }};
  const input = Array.from(document.querySelectorAll('input[type="password"]'))
    .filter(visible)
    .find((el) => !el.disabled && !el.readOnly);
  if (!input) return false;
  input.focus();
  setValue(input, password);
  const buttons = Array.from(document.querySelectorAll('button,input[type="button"],input[type="submit"],[role="button"]')).filter(visible);
  const button = buttons.find((el) => /^(サインイン|ログイン|Sign\\s*in|Next|次へ)$/i.test(textOf(el) || el.value || ''))
    || buttons.find((el) => /(サインイン|ログイン|Sign\\s*in|Next|次へ)/i.test(textOf(el) || el.value || ''));
  if (!button) return false;
  setTimeout(() => button.click(), 250);
  return true;
}})()
"""
