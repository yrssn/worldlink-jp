"""Apify 注册流程的浏览器自动化步骤。"""
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

SIGNUP_URL = "https://console.apify.com/sign-up"


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


def start_apify_signup(
    browser_id: str,
    email: str,
    password: str,
    user: User,
    db: Session,
) -> dict[str, object]:
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
    page_ws = _create_page(http_base, SIGNUP_URL)
    with CdpPage(page_ws) as page:
        page.call("Page.enable")
        page.call("Runtime.enable")
        _wait_page_ready(page)
        time.sleep(2)
        first_url = _current_url(page)
        logged_out = False
        if _looks_logged_in_url(first_url):
            logged_out = _logout_apify(page)
            page.call("Page.navigate", {"url": SIGNUP_URL})
            _wait_page_ready(page)
            time.sleep(1)
        email_submitted = _submit_email(page, email)
        password_submitted = _submit_password(page, password)
        time.sleep(1)
        final_url = _current_url(page)

    return {
        "ok": True,
        "browser_id": browser_id,
        "signup_url": SIGNUP_URL,
        "first_url": first_url,
        "final_url": final_url,
        "logged_out": logged_out,
        "ready": password_submitted,
        "email_submitted": email_submitted,
        "password_submitted": password_submitted,
        "open_hint": open_result.get("hint"),
    }


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
        raise RuntimeError("创建 Apify 注册页失败：DevTools 未返回页面 WebSocket")
    return str(ws_url)


def _wait_page_ready(page: CdpPage, timeout: float = 20) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            state = page.evaluate("document.readyState", timeout=3)
            if state in ("interactive", "complete"):
                time.sleep(1)
                return
        except Exception as e:  # noqa: BLE001
            logger.debug("[Apify signup] wait ready skipped: {}", e)
        time.sleep(0.5)


def _current_url(page: CdpPage) -> str:
    value = page.evaluate("location.href", timeout=5)
    return str(value or "")


def _looks_logged_in_url(url: str) -> bool:
    return "console.apify.com" in url and "/sign-up" not in url and "/log-in" not in url


def _is_signup_page(page: CdpPage) -> bool:
    script = """
(() => {
  const href = location.href;
  const text = document.body ? document.body.innerText : '';
  const hasEmail = !!document.querySelector('input[type="email"], input[name*="email" i]');
  return href.includes('/sign-up') && (hasEmail || text.includes("Let's create your account"));
})()
"""
    return bool(page.evaluate(script, timeout=5))


def _submit_email(page: CdpPage, email: str) -> bool:
    if not _is_signup_page(page):
        raise RuntimeError("当前页面不是 Apify 注册页，无法填写邮箱")
    clicked = bool(page.evaluate(_fill_email_and_next_script(email), timeout=8))
    if not clicked:
        raise RuntimeError("未找到可填写的 Apify 邮箱输入框或 Next 按钮")
    if not _wait_for_password_step(page):
        raise RuntimeError("已点击 Next，但未进入 Apify 密码填写步骤")
    return True


def _submit_password(page: CdpPage, password: str) -> bool:
    clicked = bool(page.evaluate(_fill_password_and_signup_script(password), timeout=8))
    if not clicked:
        raise RuntimeError("未找到 Apify 密码输入框或 Sign up 按钮")
    return True


def _wait_for_password_step(page: CdpPage, timeout: float = 15) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if page.evaluate("!!document.querySelector('input[type=\"password\"]')", timeout=3):
                return True
        except Exception as e:  # noqa: BLE001
            logger.debug("[Apify signup] wait password skipped: {}", e)
        time.sleep(0.5)
    return False


def _fill_email_and_next_script(email: str) -> str:
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
  const different = Array.from(document.querySelectorAll('button,a,[role="button"]'))
    .filter(visible)
    .find((el) => /different email/i.test(textOf(el)));
  if (different) different.click();
  const input = Array.from(document.querySelectorAll('input'))
    .filter(visible)
    .find((el) => {{
      const hint = `${{el.type}} ${{el.name}} ${{el.placeholder}} ${{el.autocomplete}}`;
      return /email/i.test(hint) && !el.disabled && !el.readOnly;
    }});
  if (!input) return false;
  input.focus();
  setValue(input, email);
  const buttons = Array.from(document.querySelectorAll('button,[role="button"]')).filter(visible);
  const button = buttons.find((el) => /^next$/i.test(textOf(el))) || buttons.find((el) => /next/i.test(textOf(el)));
  if (!button) return false;
  setTimeout(() => button.click(), 120);
  return true;
}})()
"""


def _fill_password_and_signup_script(password: str) -> str:
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
  const buttons = Array.from(document.querySelectorAll('button,[role="button"]')).filter(visible);
  const button = buttons.find((el) => /^sign up$/i.test(textOf(el))) || buttons.find((el) => /sign up/i.test(textOf(el)));
  if (!button) return false;
  setTimeout(() => button.click(), 250);
  return true;
}})()
"""


def _logout_apify(page: CdpPage) -> bool:
    clicked_menu = bool(page.evaluate(_click_account_menu_script(), timeout=8))
    if clicked_menu:
        time.sleep(0.8)
    clicked_sign_out = bool(page.evaluate(_click_sign_out_script(), timeout=8))
    if clicked_sign_out:
        time.sleep(3)
    return clicked_sign_out


def _click_account_menu_script() -> str:
    return """
(() => {
  const visible = (el) => {
    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
  };
  const textOf = (el) => (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
  const nodes = Array.from(document.querySelectorAll('button,a,[role="button"],div,span')).filter(visible);
  const target = nodes.find((el) => {
    const rect = el.getBoundingClientRect();
    const text = textOf(el);
    return rect.left < 240 && rect.top < 130 && /(Personal|Organizations|Sign out|@)/i.test(text);
  });
  if (!target) return false;
  const clickable = target.closest('button,a,[role="button"]') || target;
  clickable.click();
  return true;
})()
"""


def _click_sign_out_script() -> str:
    return """
(() => {
  const visible = (el) => {
    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
  };
  const textOf = (el) => (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
  const nodes = Array.from(document.querySelectorAll('button,a,[role="button"],div,span')).filter(visible);
  const target = nodes.find((el) => /Sign\\s*out/i.test(textOf(el)));
  if (!target) return false;
  const clickable = target.closest('button,a,[role="button"]') || target;
  clickable.click();
  return true;
})()
"""
