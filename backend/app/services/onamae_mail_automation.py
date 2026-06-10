"""お名前.com Webmail 验证邮箱登录流程的浏览器自动化步骤。"""
from __future__ import annotations

import json
import time
from itertools import count
from urllib.parse import quote, urlparse

import httpx
from sqlalchemy.orm import Session
from websockets.sync.client import connect

from app.models.user import User
from app.services import bitbrowser_service


def open_onamae_mail_login(
    browser_id: str,
    login_url: str | None,
    email: str,
    password: str,
    user: User,
    db: Session,
) -> dict[str, object]:
    target_url = normalize_onamae_login_url(login_url)
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
    page_ws, _page_id = _create_page(http_base, target_url)
    with CdpPage(page_ws) as page:
        page.call("Page.enable")
        page.call("Runtime.enable")
        page.call("Page.bringToFront")
        page.call("Page.navigate", {"url": target_url})
        _wait_page_ready(page)
        time.sleep(1)
        login_submitted = _submit_onamae_login(page, email, password)
        final_url = _current_url(page)
    return {
        "verification_mail_opened": True,
        "verification_mail_login_url": target_url,
        "verification_mail_final_url": final_url,
        "verification_mail_login_submitted": login_submitted,
        "verification_mail_open_hint": open_result.get("hint"),
    }


def normalize_onamae_login_url(login_url: str | None) -> str:
    raw = (login_url or "").strip()
    if not raw:
        raise ValueError("请先填写验证码邮箱入口")
    if raw.startswith(("http://", "https://")):
        return raw
    return f"https://{raw}"


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


def _create_page(http_base: str, url: str) -> tuple[str, str]:
    target_url = f"{http_base.rstrip('/')}/json/new?{quote(url, safe='')}"
    with httpx.Client(timeout=15, trust_env=False) as client:
        response = client.request("PUT", target_url)
        if response.status_code in (404, 405):
            response = client.get(target_url)
        response.raise_for_status()
        data = response.json()
    ws_url = data.get("webSocketDebuggerUrl")
    if not ws_url:
        raise RuntimeError("创建お名前.com Webmail 登录页失败：DevTools 未返回页面 WebSocket")
    target_id = str(data.get("id") or "")
    return str(ws_url), target_id


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


def _submit_onamae_login(page: CdpPage, email: str, password: str) -> bool:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        submitted = bool(page.evaluate(_fill_onamae_login_script(email, password), timeout=8))
        if submitted:
            time.sleep(2)
            return True
        time.sleep(0.5)
    return False


def _fill_onamae_login_script(email: str, password: str) -> str:
    email_json = json.dumps(email)
    password_json = json.dumps(password)
    return f"""
(() => {{
  const email = {email_json};
  const password = {password_json};
  const visible = (el) => {{
    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
  }};
  const setValue = (input, value) => {{
    input.focus();
    const desc = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value');
    if (desc && desc.set) desc.set.call(input, value);
    else input.value = value;
    input.setAttribute('value', value);
    input.dispatchEvent(new InputEvent('beforeinput', {{ bubbles: true, inputType: 'insertText', data: value }}));
    input.dispatchEvent(new InputEvent('input', {{ bubbles: true, inputType: 'insertText', data: value }}));
    input.dispatchEvent(new Event('change', {{ bubbles: true }}));
    input.dispatchEvent(new KeyboardEvent('keydown', {{ bubbles: true, key: value.slice(-1) || 'a' }}));
    input.dispatchEvent(new KeyboardEvent('keyup', {{ bubbles: true, key: value.slice(-1) || 'a' }}));
  }};
  const userInput = document.querySelector('#rcmloginuser')
    || document.querySelector('input[name="_user"]')
    || Array.from(document.querySelectorAll('input[type="text"],input:not([type])'))
      .filter(visible)
      .find((el) => /user|mail|email|login/i.test(`${{el.id}} ${{el.name}} ${{el.placeholder}}`));
  const passwordInput = document.querySelector('#rcmloginpwd')
    || document.querySelector('input[name="_pass"]')
    || Array.from(document.querySelectorAll('input[type="password"]')).filter(visible)[0];
  if (!userInput || !passwordInput) return false;
  setValue(userInput, email);
  setValue(passwordInput, password);
  if (userInput.value !== email || passwordInput.value !== password) return false;
  const button = document.querySelector('#rcmloginsubmit')
    || document.querySelector('button[type="submit"]')
    || document.querySelector('input[type="submit"]');
  if (!button) return false;
  button.disabled = false;
  button.classList.remove('is-disabled');
  button.dispatchEvent(new MouseEvent('mousedown', {{ bubbles: true }}));
  button.dispatchEvent(new MouseEvent('mouseup', {{ bubbles: true }}));
  button.click();
  return true;
}})()
"""
