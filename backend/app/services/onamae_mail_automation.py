"""お名前.com Webmail 验证邮箱登录流程的浏览器自动化步骤。"""
from __future__ import annotations

import json
import time
from urllib.parse import quote, urlparse

from sqlalchemy.orm import Session

from app.models.user import User
from app.services import bitbrowser_service
from app.services.cdp_relay import CdpPage, devtools_request


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
        ignore_default_urls=True,
    )
    open_data = open_result.get("data") or {}
    if not isinstance(open_data, dict) or not open_data:
        raise RuntimeError("BitBrowser 已打开，但未返回 CDP 连接信息；请先关再开该环境后重试")

    http_base = _extract_devtools_http(open_data)
    page_ws, _page_id = _create_page(http_base, target_url, user_id=user.id)
    with CdpPage(page_ws, user_id=user.id) as page:
        page.call("Page.enable")
        page.call("Runtime.enable")
        page.call("Page.bringToFront")
        page.call("Page.navigate", {"url": target_url})
        _wait_page_ready(page)
        time.sleep(1)
        login_submitted = _submit_onamae_login(page, email, password)
        inbox_ready = _wait_for_onamae_inbox(page)
        verification_code = None
        code_extracted = False
        if inbox_ready and _open_latest_zoho_otp_message(page):
            verification_code = _extract_zoho_otp_code(page)
            code_extracted = bool(verification_code)
        final_url = _current_url(page)
    return {
        "verification_mail_opened": True,
        "verification_mail_login_url": target_url,
        "verification_mail_final_url": final_url,
        "verification_mail_login_submitted": login_submitted,
        "verification_mail_inbox_ready": inbox_ready,
        "verification_mail_code_extracted": code_extracted,
        "verification_code": verification_code,
        "verification_mail_open_hint": open_result.get("hint"),
    }


def normalize_onamae_login_url(login_url: str | None) -> str:
    raw = (login_url or "").strip()
    if not raw:
        raise ValueError("请先填写验证码邮箱入口")
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


def _create_page(http_base: str, url: str, *, user_id: int | None = None) -> tuple[str, str]:
    path = f"/json/new?{quote(url, safe='')}"
    try:
        data = devtools_request(http_base, path, method="PUT", user_id=user_id)
    except Exception:
        data = devtools_request(http_base, path, method="GET", user_id=user_id)
    if not isinstance(data, dict):
        raise RuntimeError("创建お名前.com Webmail 登录页失败：DevTools 返回格式异常")
    target_id = str(data.get("id") or "")
    if target_id:
        try:
            devtools_request(http_base, f"/json/activate/{target_id}", user_id=user_id)
        except Exception:
            pass
    ws_url = data.get("webSocketDebuggerUrl")
    if not ws_url:
        raise RuntimeError("创建お名前.com Webmail 登录页失败：DevTools 未返回页面 WebSocket")
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
        if bool(page.evaluate("Boolean(document.querySelector('#messagelist'))", timeout=5)):
            return True
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


def _wait_for_onamae_inbox(page: CdpPage, timeout: float = 30) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        ready = page.evaluate(
            "Boolean(document.querySelector('#messagelist tbody tr.message') || document.querySelector('#messagelist'))",
            timeout=5,
        )
        if bool(ready):
            return True
        time.sleep(0.5)
    return False


def _open_latest_zoho_otp_message(page: CdpPage, timeout: float = 20) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        opened = page.evaluate(
            """
(() => {
  const rows = Array.from(document.querySelectorAll('#messagelist tbody tr.message'));
  const row = rows.find((item) => {
    const text = item.innerText || '';
    const from = item.querySelector('.rcmContactAddress')?.getAttribute('title') || '';
    return /Zoho Team|zohoaccounts/i.test(`${text} ${from}`)
      && /ワンタイムパスワード|認証コード|sign\\s*in|one\\s*time/i.test(text);
  });
  if (!row) return false;
  const link = row.querySelector('a[href*="_action=show"]') || row.querySelector('a') || row;
  link.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
  link.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
  link.click();
  return true;
})()
""",
            timeout=5,
        )
        if bool(opened):
            time.sleep(1.5)
            return True
        time.sleep(0.5)
    return False


def _extract_zoho_otp_code(page: CdpPage, timeout: float = 30) -> str | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = page.evaluate(
            """
(() => {
  const readFrame = (frame) => {
    try {
      return frame.contentDocument?.body?.innerText || frame.contentDocument?.body?.textContent || '';
    } catch {
      return '';
    }
  };
  const parts = [
    document.querySelector('#messagebody')?.innerText || '',
    document.querySelector('#messagepreview')?.innerText || '',
    document.querySelector('#mailview-right')?.innerText || '',
    document.querySelector('#messagecontframe') ? readFrame(document.querySelector('#messagecontframe')) : '',
    document.body?.innerText || '',
  ];
  const text = parts.join('\\n');
  if (!/Zoho|ワンタイムパスワード|認証コード|one\\s*time/i.test(text)) return null;
  const matches = Array.from(text.matchAll(/\\b\\d{6,8}\\b/g)).map((match) => match[0]);
  return matches[0] || null;
})()
""",
            timeout=5,
        )
        if isinstance(value, str) and value:
            return value
        time.sleep(0.5)
    return None
