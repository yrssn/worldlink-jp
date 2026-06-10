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
    target_url = normalize_zoho_login_url(login_url)
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
    time.sleep(1)
    closed_count = _close_zoho_pages_until_clear(http_base)
    page_ws, page_id = _create_page(http_base, target_url)
    time.sleep(0.5)
    closed_count += _close_zoho_pages_until_clear(http_base, keep_target_id=page_id)
    final_url = target_url
    email_submitted = False
    password_submitted = False
    verification_required = False
    mail_refreshed = False
    with CdpPage(page_ws) as page:
        page.call("Page.enable")
        page.call("Runtime.enable")
        page.call("Page.bringToFront")
        page.call("Page.navigate", {"url": target_url})
        _wait_page_ready(page)
        time.sleep(1)
        email_submitted = _submit_zoho_email(page, email)
        final_url = _current_url(page)
    if email_submitted and password:
        refreshed_ws = _find_zoho_page_ws(http_base, preferred_target_id=page_id) or page_ws
        with CdpPage(refreshed_ws) as page:
            page.call("Page.enable")
            page.call("Runtime.enable")
            page.call("Page.bringToFront")
            _wait_page_ready(page)
            password_submitted = _submit_zoho_password(page, password)
            if password_submitted:
                verification_required = _wait_for_zoho_email_verification_step(page)
                if not verification_required:
                    mail_refreshed = _refresh_zoho_current_page(page)
            final_url = _current_url(page)
    return {
        "mail_opened": True,
        "mail_login_url": target_url,
        "mail_final_url": final_url,
        "mail_closed_tab_count": closed_count,
        "mail_email_submitted": email_submitted,
        "mail_password_submitted": password_submitted,
        "mail_verification_required": verification_required,
        "mail_refreshed": mail_refreshed,
        "mail_open_hint": open_result.get("hint"),
    }


def submit_zoho_verification_code(
    browser_id: str,
    code: str,
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
    page_ws = _find_zoho_page_ws(http_base)
    if not page_ws:
        return {
            "mail_verification_code_submitted": False,
            "mail_verification_submit_hint": "未找到 Zoho 验证页面",
        }
    with CdpPage(page_ws) as page:
        page.call("Page.enable")
        page.call("Runtime.enable")
        page.call("Page.bringToFront")
        submitted = _submit_zoho_verification_code(page, code)
        refreshed = False
        if submitted:
            refreshed = _refresh_zoho_current_page(page)
        final_url = _current_url(page)
    return {
        "mail_verification_code_submitted": submitted,
        "mail_verification_refreshed": refreshed,
        "mail_verification_final_url": final_url,
        "mail_verification_submit_hint": open_result.get("hint"),
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


def normalize_zoho_login_url(login_url: str | None) -> str:
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
        raise RuntimeError("创建 Zoho 邮箱登录页失败：DevTools 未返回页面 WebSocket")
    target_id = str(data.get("id") or "")
    return str(ws_url), target_id


def _close_zoho_pages_until_clear(
    http_base: str,
    keep_target_id: str | None = None,
    attempts: int = 3,
) -> int:
    closed = 0
    for _ in range(attempts):
        closed_now = _close_zoho_pages(http_base, keep_target_id=keep_target_id)
        closed += closed_now
        if closed_now == 0:
            return closed
        time.sleep(0.5)
    return closed


def _close_zoho_pages(http_base: str, keep_target_id: str | None = None) -> int:
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
            if not target_id or target_id == keep_target_id or "zoho.com" not in target_url:
                continue
            try:
                client.get(f"{http_base.rstrip('/')}/json/close/{target_id}")
                closed += 1
            except Exception as e:  # noqa: BLE001
                logger.debug("[Zoho mail] close target {} skipped: {}", target_id, e)
    return closed


def _find_zoho_page_ws(http_base: str, preferred_target_id: str | None = None) -> str | None:
    with httpx.Client(timeout=10, trust_env=False) as client:
        try:
            response = client.get(f"{http_base.rstrip('/')}/json/list")
            response.raise_for_status()
            targets = response.json()
        except Exception as e:  # noqa: BLE001
            logger.debug("[Zoho mail] find target skipped: {}", e)
            return None
    if not isinstance(targets, list):
        return None
    fallback_ws = None
    for target in targets:
        if not isinstance(target, dict):
            continue
        target_id = str(target.get("id") or "")
        target_url = str(target.get("url") or "")
        target_type = str(target.get("type") or "")
        ws_url = str(target.get("webSocketDebuggerUrl") or "")
        if target_type != "page" or "zoho." not in target_url or not ws_url:
            continue
        if preferred_target_id and target_id == preferred_target_id:
            return ws_url
        if "accounts.zoho." in target_url:
            fallback_ws = ws_url
    return fallback_ws


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


def _refresh_zoho_current_page(page: CdpPage) -> bool:
    page.call("Page.reload", {"ignoreCache": True}, timeout=5)
    _wait_page_ready(page)
    time.sleep(1)
    return True


def _submit_zoho_verification_code(page: CdpPage, code: str) -> bool:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        submitted = page.evaluate(_fill_zoho_verification_code_script(code), timeout=8)
        if bool(submitted):
            time.sleep(2)
            return True
        time.sleep(0.5)
    return False


def _wait_for_zoho_email_verification_step(page: CdpPage, timeout: float = 20) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _is_zoho_email_verification_step(page):
            return True
        if _is_zoho_mail_page(page):
            return False
        time.sleep(0.5)
    return False


def _fill_zoho_verification_code_script(code: str) -> str:
    code_json = json.dumps(code)
    return f"""
(() => {{
  const code = {code_json};
  const visible = (el) => {{
    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
  }};
  const textOf = (el) => (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
  const setValue = (input, value) => {{
    input.focus();
    const desc = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value');
    if (desc && desc.set) desc.set.call(input, value);
    else input.value = value;
    input.setAttribute('value', value);
    input.dispatchEvent(new InputEvent('beforeinput', {{ bubbles: true, inputType: 'insertText', data: value }}));
    input.dispatchEvent(new InputEvent('input', {{ bubbles: true, inputType: 'insertText', data: value }}));
    input.dispatchEvent(new Event('change', {{ bubbles: true }}));
    input.dispatchEvent(new KeyboardEvent('keydown', {{ bubbles: true, key: value.slice(-1) || '0' }}));
    input.dispatchEvent(new KeyboardEvent('keyup', {{ bubbles: true, key: value.slice(-1) || '0' }}));
  }};
  const setDigit = (input, digit, index) => {{
    input.focus();
    const desc = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value');
    if (desc && desc.set) desc.set.call(input, digit);
    else input.value = digit;
    input.setAttribute('value', digit);
    input.classList.remove('empty_field');
    input.dispatchEvent(new KeyboardEvent('keydown', {{ bubbles: true, key: digit, code: `Digit${{digit}}`, keyCode: 48 + Number(digit), which: 48 + Number(digit) }}));
    input.dispatchEvent(new InputEvent('beforeinput', {{ bubbles: true, inputType: 'insertText', data: digit }}));
    input.dispatchEvent(new InputEvent('input', {{ bubbles: true, inputType: 'insertText', data: digit }}));
    input.dispatchEvent(new KeyboardEvent('keyup', {{ bubbles: true, key: digit, code: `Digit${{digit}}`, keyCode: 48 + Number(digit), which: 48 + Number(digit) }}));
    input.dispatchEvent(new Event('change', {{ bubbles: true }}));
    const next = input.parentElement?.querySelectorAll('input.mfa_email_otp')[index + 1];
    if (next) next.focus();
  }};
  const emailContainer = document.querySelector('#mfa_email_container');
  const emailOtpBox = document.querySelector('#mfa_email');
  const splitInputs = Array.from(document.querySelectorAll('#mfa_email input.mfa_email_otp, #mfa_email input.splitedText'));
  if (emailContainer && visible(emailContainer) && splitInputs.length) {{
    const digits = code.split('');
    const fullValue = document.querySelector('#mfa_email_full_value') || document.querySelector('.mfa_email_full_value');
    if (fullValue) setValue(fullValue, code);
    if (emailOtpBox) {{
      emailOtpBox.classList.remove('errorborder');
      emailOtpBox.setAttribute('value', code);
      emailOtpBox.dispatchEvent(new Event('click', {{ bubbles: true }}));
    }}
    splitInputs.forEach((input, index) => setDigit(input, digits[index] || '', index));
    document.dispatchEvent(new Event('input', {{ bubbles: true }}));
    const filled = splitInputs.map((input) => input.value || '').join('').slice(0, code.length);
    if ((fullValue?.value || filled) !== code && filled !== code) return false;
  }} else {{
  const inputs = Array.from(document.querySelectorAll('input')).filter(visible);
  const input = document.querySelector('input[name="otp"]')
    || document.querySelector('input[name="OTP"]')
    || document.querySelector('input[id*="otp" i]')
    || document.querySelector('input[id*="verify" i]')
    || document.querySelector('#mfa_email_full_value')
    || document.querySelector('#mfa_email input.mfa_email_otp')
    || inputs.find((el) => /認証コード|ワンタイム|code|otp|verification/i.test(`${{el.id}} ${{el.name}} ${{el.placeholder}}`))
    || inputs.find((el) => (el.type || '').toLowerCase() === 'text');
  if (!input) return false;
  setValue(input, code);
  if (input.value !== code) return false;
  }}
  const buttons = Array.from(document.querySelectorAll('#nextbtn,#verifybtn,#login,#signin,button,input[type="button"],input[type="submit"],[role="button"],.btn,.button')).filter(visible);
  const button = buttons.find((el) => /^(認証する|確認|送信|Verify|Submit|Next|次へ)$/i.test(textOf(el) || el.value || ''))
    || buttons.find((el) => /(認証する|確認|送信|Verify|Submit|Next|次へ)/i.test(textOf(el) || el.value || ''))
    || document.querySelector('#nextbtn');
  if (!button) return false;
  button.dispatchEvent(new MouseEvent('mousedown', {{ bubbles: true }}));
  button.dispatchEvent(new MouseEvent('mouseup', {{ bubbles: true }}));
  button.click();
  return true;
}})()
"""


def _is_zoho_email_verification_step(page: CdpPage) -> bool:
    return bool(
        page.evaluate(
            """
(() => {
  const text = document.body ? document.body.innerText : '';
  const codeInput = document.querySelector('input[name="otp"]')
    || document.querySelector('input[name="OTP"]')
    || document.querySelector('#mfa_email_container input.mfa_email_otp')
    || document.querySelector('#mfa_email_full_value')
    || document.querySelector('#mfa_email')
    || document.querySelector('input[placeholder*="認証コード"]')
    || document.querySelector('input[placeholder*="ワンタイム"]')
    || document.querySelector('input[placeholder*="code" i]');
  const emailContainer = document.querySelector('#mfa_email_container');
  const visible = (el) => {
    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
  };
  return Boolean(codeInput)
    && (!emailContainer || visible(emailContainer))
    && /メールアドレスで認証|ワンタイムパスワード|認証コード|verify/i.test(text);
})()
""",
            timeout=5,
        )
    )


def _is_zoho_mail_page(page: CdpPage) -> bool:
    return bool(
        page.evaluate(
            """
(() => {
  const url = window.location.href || '';
  const text = document.body ? document.body.innerText : '';
  return /mail\\.zoho\\./i.test(url)
    || /Zoho Mail|メール|受信トレイ|Inbox/i.test(text);
})()
""",
            timeout=5,
        )
    )


def _submit_zoho_email(page: CdpPage, email: str) -> bool:
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        if _is_zoho_password_step(page):
            return True
        focused = bool(page.evaluate(_focus_zoho_email_script(), timeout=5))
        submitted = False
        if focused:
            page.call("Input.insertText", {"text": email}, timeout=5)
            submitted = bool(page.evaluate(_click_zoho_email_next_script(email), timeout=5))
        if not submitted:
            submitted = bool(page.evaluate(_fill_zoho_email_script(email), timeout=8))
        if submitted and _wait_for_password_input(page, timeout=4):
            return True
        time.sleep(0.5)
    return False


def _submit_zoho_password(page: CdpPage, password: str) -> bool:
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        if _wait_for_password_input(page, timeout=2):
            page.call("Page.bringToFront")
            focused = bool(page.evaluate(_focus_zoho_password_script(), timeout=5))
            submitted = False
            if focused:
                filled = bool(page.evaluate(_clear_zoho_password_script(), timeout=5))
                if filled:
                    _type_text(page, password)
                    filled = bool(page.evaluate(_verify_zoho_password_script(password), timeout=5))
                if not filled:
                    filled = bool(page.evaluate(_fill_zoho_password_only_script(password), timeout=8))
                if not filled:
                    filled = bool(page.evaluate(_force_submit_zoho_password_script(password, submit=False), timeout=8))
                if not filled:
                    time.sleep(0.5)
                    continue
                time.sleep(1)
                submitted = bool(page.evaluate(_click_zoho_password_submit_script(), timeout=5))
                if submitted:
                    _press_enter(page)
            if not submitted:
                submitted = bool(page.evaluate(_force_submit_zoho_password_script(password, submit=True), timeout=8))
            if not submitted:
                submitted = bool(page.evaluate(_fill_zoho_password_script(password), timeout=8))
            if submitted:
                time.sleep(2)
                return True
        time.sleep(0.5)
    return False


def _type_text(page: CdpPage, text: str) -> None:
    page.call("Input.insertText", {"text": text}, timeout=5)
    filled = page.evaluate(
        "(() => { const el = document.querySelector('#password') || document.activeElement; "
        "return Boolean(el && el.value); })()",
        timeout=5,
    )
    if bool(filled):
        return
    for char in text:
        key = char.upper() if len(char) == 1 and char.isalpha() else char
        page.call("Input.dispatchKeyEvent", {"type": "keyDown", "key": key, "text": char, "unmodifiedText": char}, timeout=5)
        page.call("Input.dispatchKeyEvent", {"type": "char", "text": char, "unmodifiedText": char}, timeout=5)
        page.call("Input.dispatchKeyEvent", {"type": "keyUp", "key": key}, timeout=5)


def _press_enter(page: CdpPage) -> None:
    page.call(
        "Input.dispatchKeyEvent",
        {"type": "keyDown", "key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13},
        timeout=5,
    )
    page.call(
        "Input.dispatchKeyEvent",
        {"type": "keyUp", "key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13},
        timeout=5,
    )


def _wait_for_password_input(page: CdpPage, timeout: float = 12) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _is_zoho_password_step(page):
            return True
        time.sleep(0.5)
    return False


def _is_zoho_password_step(page: CdpPage) -> bool:
    return bool(page.evaluate(_zoho_password_step_script(), timeout=5))


def _zoho_password_step_script() -> str:
    return """
(() => {
  const passwordContainer = document.querySelector('#password_container');
  const loginContainer = document.querySelector('#login_id_container');
  const passwordInput = document.querySelector('#password') || document.querySelector('input[name="PASSWORD"]');
  if (!passwordContainer || !passwordInput) return false;
  const passwordStyle = getComputedStyle(passwordContainer);
  const passwordRect = passwordContainer.getBoundingClientRect();
  const passwordContainerVisible = passwordStyle.display !== 'none'
    && passwordStyle.visibility !== 'hidden'
    && !passwordContainer.classList.contains('zeroheight')
    && passwordRect.width > 0
    && passwordRect.height > 0;
  if (!passwordContainerVisible) return false;
  if (!loginContainer) return true;
  const loginStyle = getComputedStyle(loginContainer);
  const loginRect = loginContainer.getBoundingClientRect();
  const loginContainerHidden = loginStyle.display === 'none'
    || loginStyle.visibility === 'hidden'
    || loginContainer.classList.contains('hide')
    || loginRect.width === 0
    || loginRect.height === 0;
  const username = (passwordContainer.querySelector('.username')?.textContent || '').trim();
  return loginContainerHidden || Boolean(username);
})()
"""


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
    const desc = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value');
    if (desc && desc.set) desc.set.call(input, value);
    else input.value = value;
    input.setAttribute('value', value);
    input.dispatchEvent(new Event('input', {{ bubbles: true }}));
    input.dispatchEvent(new Event('change', {{ bubbles: true }}));
    input.dispatchEvent(new KeyboardEvent('keyup', {{ bubbles: true, key: value.slice(-1) || 'a' }}));
  }};
  const inputs = Array.from(document.querySelectorAll('input'))
    .filter(visible)
    .filter((el) => !el.disabled && !el.readOnly && !['hidden', 'password'].includes((el.type || 'text').toLowerCase()));
  const input = document.querySelector('#login_id')
    || document.querySelector('input[name="LOGIN_ID"]')
    || document.querySelector('input[name="login_id"]')
    || inputs.find((el) => (el.type || '').toLowerCase() === 'email')
    || inputs.find((el) => /(email|mail|login|lid|identifier)/i.test(`${{el.id}} ${{el.name}} ${{el.placeholder}}`))
    || inputs[0];
  if (!input) return false;
  input.focus();
  setValue(input, email);
  if (input.value !== email) return false;
  const buttons = Array.from(document.querySelectorAll('#nextbtn,#login,#signin,button,input[type="button"],input[type="submit"],[role="button"],.btn,.button')).filter(visible);
  const button = document.querySelector('#nextbtn')
    || buttons.find((el) => /^(次へ|Next)$/i.test(textOf(el) || el.value || ''))
    || buttons.find((el) => /(次へ|Next)/i.test(textOf(el) || el.value || ''));
  if (!button) return false;
  button.dispatchEvent(new MouseEvent('mousedown', {{ bubbles: true }}));
  button.dispatchEvent(new MouseEvent('mouseup', {{ bubbles: true }}));
  setTimeout(() => button.click(), 150);
  return true;
}})()
"""


def _focus_zoho_email_script() -> str:
    return """
(() => {
  const visible = (el) => {
    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
  };
  const inputs = Array.from(document.querySelectorAll('input'))
    .filter(visible)
    .filter((el) => !el.disabled && !el.readOnly && !['hidden', 'password'].includes((el.type || 'text').toLowerCase()));
  const input = document.querySelector('#login_id')
    || document.querySelector('input[name="LOGIN_ID"]')
    || document.querySelector('input[name="login_id"]')
    || inputs.find((el) => (el.type || '').toLowerCase() === 'email')
    || inputs.find((el) => /(email|mail|login|lid|identifier)/i.test(`${el.id} ${el.name} ${el.placeholder}`));
  if (!input) return false;
  input.focus();
  input.value = '';
  input.setAttribute('value', '');
  input.dispatchEvent(new Event('input', { bubbles: true }));
  input.dispatchEvent(new Event('change', { bubbles: true }));
  return document.activeElement === input;
})()
"""


def _click_zoho_email_next_script(email: str) -> str:
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
  const input = document.querySelector('#login_id') || document.querySelector('input[name="LOGIN_ID"]');
  if (!input || input.value !== email) return false;
  input.dispatchEvent(new Event('input', {{ bubbles: true }}));
  input.dispatchEvent(new Event('change', {{ bubbles: true }}));
  input.dispatchEvent(new KeyboardEvent('keyup', {{ bubbles: true, key: email.slice(-1) || 'a' }}));
  const buttons = Array.from(document.querySelectorAll('#nextbtn,#login,#signin,button,input[type="button"],input[type="submit"],[role="button"],.btn,.button')).filter(visible);
  const button = document.querySelector('#nextbtn')
    || buttons.find((el) => /^(次へ|Next)$/i.test(textOf(el) || el.value || ''))
    || buttons.find((el) => /(次へ|Next)/i.test(textOf(el) || el.value || ''));
  if (!button) return false;
  button.dispatchEvent(new MouseEvent('mousedown', {{ bubbles: true }}));
  button.dispatchEvent(new MouseEvent('mouseup', {{ bubbles: true }}));
  button.click();
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
    const desc = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value');
    if (desc && desc.set) desc.set.call(input, value);
    else input.value = value;
    input.setAttribute('value', value);
    input.dispatchEvent(new Event('input', {{ bubbles: true }}));
    input.dispatchEvent(new Event('change', {{ bubbles: true }}));
  }};
  const inputMeta = (el) => `${{el.id}} ${{el.name}} ${{el.placeholder}} ${{el.type}} ${{el.autocomplete}}`;
  const input = document.querySelector('#password')
    || document.querySelector('input[name="PASSWORD"]')
    || document.querySelector('input[name="password"]')
    || Array.from(document.querySelectorAll('input'))
    .filter(visible)
    .find((el) => !el.disabled && !el.readOnly && /password|passwd|pwd|パスワード/i.test(inputMeta(el)));
  if (!input) return false;
  input.focus();
  setValue(input, password);
  input.dispatchEvent(new KeyboardEvent('keyup', {{ bubbles: true, key: 'a' }}));
  input.blur();
  input.focus();
  if (!input.value) return false;
  const buttons = Array.from(document.querySelectorAll('#nextbtn,#login,#signin,button,input[type="button"],input[type="submit"],[role="button"]')).filter(visible);
  const button = buttons.find((el) => /^(サインインする|サインイン|ログイン|Sign\\s*in|Log\\s*in|Next|次へ)$/i.test(textOf(el) || el.value || ''))
    || buttons.find((el) => /(サインインする|サインイン|ログイン|Sign\\s*in|Log\\s*in|Next|次へ)/i.test(textOf(el) || el.value || ''))
    || document.querySelector('#nextbtn');
  if (!button) return false;
  button.dispatchEvent(new MouseEvent('mousedown', {{ bubbles: true }}));
  button.dispatchEvent(new MouseEvent('mouseup', {{ bubbles: true }}));
  setTimeout(() => button.click(), 150);
  return true;
}})()
"""


def _clear_zoho_password_script() -> str:
    return """
(() => {
  const input = document.querySelector('#password')
    || document.querySelector('input[name="PASSWORD"]')
    || document.querySelector('input[name="password"]')
    || document.querySelector('input[type="password"]');
  if (!input) return false;
  input.focus();
  input.value = '';
  input.setAttribute('value', '');
  input.dispatchEvent(new Event('input', { bubbles: true }));
  input.dispatchEvent(new Event('change', { bubbles: true }));
  return document.activeElement === input;
})()
"""


def _verify_zoho_password_script(password: str) -> str:
    password_json = json.dumps(password)
    return f"""
(() => {{
  const password = {password_json};
  const input = document.querySelector('#password')
    || document.querySelector('input[name="PASSWORD"]')
    || document.querySelector('input[name="password"]')
    || document.querySelector('input[type="password"]');
  return Boolean(input && input.value === password);
}})()
"""


def _fill_zoho_password_only_script(password: str) -> str:
    password_json = json.dumps(password)
    return f"""
(() => {{
  const password = {password_json};
  const input = document.querySelector('#password')
    || document.querySelector('input[name="PASSWORD"]')
    || document.querySelector('input[name="password"]')
    || document.querySelector('input[type="password"]');
  if (!input) return false;
  input.focus();
  input.value = '';
  for (const ch of password) {{
    const before = input.value;
    const next = before + ch;
    const desc = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value');
    if (desc && desc.set) desc.set.call(input, next);
    else input.value = next;
    input.setAttribute('value', next);
    input.dispatchEvent(new KeyboardEvent('keydown', {{ bubbles: true, key: ch }}));
    input.dispatchEvent(new InputEvent('beforeinput', {{ bubbles: true, inputType: 'insertText', data: ch }}));
    input.dispatchEvent(new InputEvent('input', {{ bubbles: true, inputType: 'insertText', data: ch }}));
    input.dispatchEvent(new KeyboardEvent('keyup', {{ bubbles: true, key: ch }}));
  }}
  input.dispatchEvent(new Event('change', {{ bubbles: true }}));
  return input.value === password;
}})()
"""


def _force_submit_zoho_password_script(password: str, *, submit: bool) -> str:
    password_json = json.dumps(password)
    submit_json = json.dumps(submit)
    return f"""
(() => {{
  const password = {password_json};
  const shouldSubmit = {submit_json};
  const visible = (el) => {{
    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
  }};
  const textOf = (el) => (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
  const input = document.querySelector('#password')
    || document.querySelector('input[name="PASSWORD"]')
    || document.querySelector('input[name="password"]')
    || Array.from(document.querySelectorAll('input[type="password"]')).find(visible);
  if (!input) return false;
  input.focus();
  input.value = '';
  const desc = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value');
  if (desc && desc.set) desc.set.call(input, password);
  else input.value = password;
  input.setAttribute('value', password);
  input.dispatchEvent(new InputEvent('beforeinput', {{ bubbles: true, inputType: 'insertText', data: password }}));
  input.dispatchEvent(new InputEvent('input', {{ bubbles: true, inputType: 'insertText', data: password }}));
  input.dispatchEvent(new Event('change', {{ bubbles: true }}));
  input.dispatchEvent(new KeyboardEvent('keydown', {{ bubbles: true, key: password.slice(-1) || 'a' }}));
  input.dispatchEvent(new KeyboardEvent('keyup', {{ bubbles: true, key: password.slice(-1) || 'a' }}));
  if (input.value !== password) return false;
  if (!shouldSubmit) return true;
  const buttons = Array.from(document.querySelectorAll('#nextbtn,#login,#signin,button,input[type="button"],input[type="submit"],[role="button"],.btn,.button')).filter(visible);
  const button = document.querySelector('#nextbtn')
    || buttons.find((el) => /^(サインインする|サインイン|ログイン|Sign\\s*in|Log\\s*in|Next|次へ)$/i.test(textOf(el) || el.value || ''))
    || buttons.find((el) => /(サインインする|サインイン|ログイン|Sign\\s*in|Log\\s*in|Next|次へ)/i.test(textOf(el) || el.value || ''));
  if (button) {{
    button.dispatchEvent(new MouseEvent('mousedown', {{ bubbles: true }}));
    button.dispatchEvent(new MouseEvent('mouseup', {{ bubbles: true }}));
    button.click();
    return true;
  }}
  const form = input.closest('form') || document.querySelector('form#login') || document.querySelector('form');
  if (!form) return false;
  if (form.requestSubmit) form.requestSubmit();
  else form.submit();
  return true;
}})()
"""


def _focus_zoho_password_script() -> str:
    return """
(() => {
  const visible = (el) => {
    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
  };
  const inputMeta = (el) => `${el.id} ${el.name} ${el.placeholder} ${el.type} ${el.autocomplete}`;
  const input = document.querySelector('#password')
    || document.querySelector('input[name="PASSWORD"]')
    || document.querySelector('input[name="password"]')
    || Array.from(document.querySelectorAll('input'))
      .filter(visible)
      .find((el) => !el.disabled && !el.readOnly && /password|passwd|pwd|パスワード/i.test(inputMeta(el)));
  if (!input) return false;
  input.focus();
  input.value = '';
  input.setAttribute('value', '');
  input.dispatchEvent(new Event('input', { bubbles: true }));
  input.dispatchEvent(new Event('change', { bubbles: true }));
  return document.activeElement === input;
})()
"""


def _click_zoho_password_submit_script() -> str:
    return """
(() => {
  const visible = (el) => {
    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
  };
  const textOf = (el) => (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
  const input = document.querySelector('#password') || document.querySelector('input[name="PASSWORD"]');
  if (!input || !input.value) return false;
  input.dispatchEvent(new Event('input', { bubbles: true }));
  input.dispatchEvent(new Event('change', { bubbles: true }));
  input.dispatchEvent(new KeyboardEvent('keydown', { bubbles: true, key: input.value.slice(-1) || 'a' }));
  input.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true, key: input.value.slice(-1) || 'a' }));
  const buttons = Array.from(document.querySelectorAll('#nextbtn,#login,#signin,button,input[type="button"],input[type="submit"],[role="button"],.btn,.button')).filter(visible);
  const button = document.querySelector('#nextbtn')
    || buttons.find((el) => /^(サインインする|サインイン|ログイン|Sign\\s*in|Log\\s*in|Next|次へ)$/i.test(textOf(el) || el.value || ''))
    || buttons.find((el) => /(サインインする|サインイン|ログイン|Sign\\s*in|Log\\s*in|Next|次へ)/i.test(textOf(el) || el.value || ''));
  if (!button) return false;
  button.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
  button.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
  button.click();
  return true;
})()
"""
