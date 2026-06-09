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

    def click(self, x: float, y: float) -> None:
        params = {"x": x, "y": y, "button": "left", "clickCount": 1}
        self.call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y}, timeout=5)
        self.call("Input.dispatchMouseEvent", {"type": "mousePressed", **params}, timeout=5)
        self.call("Input.dispatchMouseEvent", {"type": "mouseReleased", **params}, timeout=5)


def start_apify_signup(
    browser_id: str,
    email: str,
    password: str,
    user: User,
    db: Session,
) -> dict[str, object]:
    bitbrowser_service.close_browser_window(browser_id, user)
    time.sleep(1)
    profile_clear_result = bitbrowser_service.clear_browser_profile_cookies(browser_id, user)
    time.sleep(0.5)
    open_result = bitbrowser_service.open_browser_window(
        browser_id,
        user,
        db,
        headless=False,
        restart=True,
    )
    open_data = open_result.get("data") or {}
    if not isinstance(open_data, dict) or not open_data:
        raise RuntimeError("BitBrowser 已打开，但未返回 CDP 连接信息；请先关再开该环境后重试")

    http_base = _extract_devtools_http(open_data)
    _close_apify_pages(http_base)
    page_ws = _create_page(http_base, SIGNUP_URL)
    with CdpPage(page_ws) as page:
        page.call("Page.enable")
        page.call("Network.enable")
        page.call("Runtime.enable")
        _wait_page_ready(page)
        time.sleep(2)
        first_url = _current_url(page)
        cleared_cookie_count = _clear_apify_session(page)
        page.call("Page.navigate", {"url": SIGNUP_URL})
        _wait_page_ready(page)
        time.sleep(1)
        logged_out = False
        all_cookies_cleared = False
        post_clear_url = _current_url(page)
        if _looks_logged_in_url(post_clear_url):
            logged_out = _logout_apify(page)
            page.call("Page.navigate", {"url": SIGNUP_URL})
            _wait_page_ready(page)
            time.sleep(1)
            post_clear_url = _current_url(page)
        if _looks_logged_in_url(post_clear_url):
            _clear_all_browser_session(page)
            all_cookies_cleared = True
            page.call("Page.navigate", {"url": SIGNUP_URL})
            _wait_page_ready(page)
            time.sleep(1)
            post_clear_url = _current_url(page)
        still_logged_in = _looks_logged_in_url(post_clear_url)
        if still_logged_in:
            final_url = _current_url(page)
            return {
                "ok": True,
                "browser_id": browser_id,
                "signup_url": SIGNUP_URL,
                "first_url": first_url,
                "final_url": final_url,
                "logged_out": logged_out,
                "session_cleared": True,
                "profile_cookies_cleared": bool(profile_clear_result.get("cookies_cleared")),
                "profile_cookie_config_cleared": bool(
                    profile_clear_result.get("profile_cookie_cleared")
                ),
                "cleared_cookie_count": cleared_cookie_count,
                "all_cookies_cleared": all_cookies_cleared,
                "still_logged_in": True,
                "ready": False,
                "email_submitted": False,
                "password_submitted": False,
                "captcha_required": False,
                "open_hint": open_result.get("hint"),
            }
        email_submitted = _submit_email(page, email)
        password_submitted = _submit_password(page, password)
        captcha_required = _wait_for_captcha(page)
        final_url = _current_url(page)

    return {
        "ok": True,
        "browser_id": browser_id,
        "signup_url": SIGNUP_URL,
        "first_url": first_url,
        "final_url": final_url,
        "logged_out": logged_out,
        "session_cleared": True,
        "profile_cookies_cleared": bool(profile_clear_result.get("cookies_cleared")),
        "profile_cookie_config_cleared": bool(profile_clear_result.get("profile_cookie_cleared")),
        "cleared_cookie_count": cleared_cookie_count,
        "all_cookies_cleared": all_cookies_cleared,
        "still_logged_in": False,
        "ready": password_submitted,
        "email_submitted": email_submitted,
        "password_submitted": password_submitted,
        "captcha_required": captcha_required,
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


def _close_apify_pages(http_base: str) -> int:
    closed = 0
    with httpx.Client(timeout=10, trust_env=False) as client:
        try:
            response = client.get(f"{http_base.rstrip('/')}/json/list")
            response.raise_for_status()
            targets = response.json()
        except Exception as e:  # noqa: BLE001
            logger.debug("[Apify signup] list targets skipped: {}", e)
            return 0
        if not isinstance(targets, list):
            return 0
        for target in targets:
            if not isinstance(target, dict):
                continue
            url = str(target.get("url") or "")
            target_id = str(target.get("id") or "")
            if "apify.com" not in url or not target_id:
                continue
            try:
                client.get(f"{http_base.rstrip('/')}/json/close/{quote(target_id, safe='')}")
                closed += 1
            except Exception as e:  # noqa: BLE001
                logger.debug("[Apify signup] close target skipped {}: {}", target_id, e)
    return closed


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


def _clear_apify_session(page: CdpPage) -> int:
    cleared_cookie_count = _delete_apify_cookies(page)
    _clear_apify_storage(page)
    try:
        page.call("Network.clearBrowserCache", timeout=8)
    except Exception as e:  # noqa: BLE001
        logger.debug("[Apify signup] clear cache skipped: {}", e)
    return cleared_cookie_count


def _clear_all_browser_session(page: CdpPage) -> None:
    try:
        page.call("Network.clearBrowserCookies", timeout=8)
    except Exception as e:  # noqa: BLE001
        logger.debug("[Apify signup] clear all cookies skipped: {}", e)
    try:
        page.call("Network.clearBrowserCache", timeout=8)
    except Exception as e:  # noqa: BLE001
        logger.debug("[Apify signup] clear all cache skipped: {}", e)
    _clear_apify_storage(page)


def _delete_apify_cookies(page: CdpPage) -> int:
    result = page.call("Network.getAllCookies", timeout=8)
    raw_cookies = result.get("cookies")
    if not isinstance(raw_cookies, list):
        return 0
    deleted = 0
    for raw_cookie in raw_cookies:
        if not isinstance(raw_cookie, dict):
            continue
        name = str(raw_cookie.get("name") or "").strip()
        domain = str(raw_cookie.get("domain") or "").strip()
        path = str(raw_cookie.get("path") or "/").strip() or "/"
        if not name or "apify.com" not in domain:
            continue
        host = domain.lstrip(".")
        try:
            page.call("Network.deleteCookies", {"name": name, "domain": domain, "path": path}, timeout=5)
            page.call("Network.deleteCookies", {"name": name, "url": f"https://{host}{path}"}, timeout=5)
            deleted += 1
        except Exception as e:  # noqa: BLE001
            logger.debug("[Apify signup] delete cookie skipped {} {}: {}", domain, name, e)
    return deleted


def _clear_apify_storage(page: CdpPage) -> None:
    for origin in ("https://apify.com", "https://console.apify.com"):
        try:
            page.call(
                "Storage.clearDataForOrigin",
                {"origin": origin, "storageTypes": "all"},
                timeout=8,
            )
        except Exception as e:  # noqa: BLE001
            logger.debug("[Apify signup] clear storage skipped {}: {}", origin, e)


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


def _wait_for_captcha(page: CdpPage, timeout: float = 8) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if _has_captcha(page):
                return True
        except Exception as e:  # noqa: BLE001
            logger.debug("[Apify signup] captcha detection skipped: {}", e)
        time.sleep(0.5)
    return False


def _has_captcha(page: CdpPage) -> bool:
    script = """
(() => {
  const bodyText = document.body ? document.body.innerText : '';
  const frames = Array.from(document.querySelectorAll('iframe')).map((el) => {
    return `${el.src || ''} ${el.title || ''} ${el.name || ''}`;
  }).join(' ');
  const scripts = Array.from(document.querySelectorAll('script')).map((el) => el.src || '').join(' ');
  const text = `${bodyText} ${frames} ${scripts}`;
  return /captcha|hcaptcha|recaptcha|arkose|challenge|Select all squares/i.test(text);
})()
"""
    return bool(page.evaluate(script, timeout=5))


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
    for _ in range(3):
        if not _click_point_from_script(page, _account_menu_point_script()):
            time.sleep(0.5)
            continue
        time.sleep(1)
        for _ in range(8):
            if _click_point_from_script(page, _sign_out_point_script()):
                return _wait_until_logged_out(page)
            time.sleep(0.5)
    return False


def _click_point_from_script(page: CdpPage, script: str) -> bool:
    point = page.evaluate(script, timeout=8)
    if not isinstance(point, dict):
        return False
    raw_x = point.get("x")
    raw_y = point.get("y")
    if not isinstance(raw_x, (int, float)) or not isinstance(raw_y, (int, float)):
        return False
    page.click(float(raw_x), float(raw_y))
    return True


def _wait_until_logged_out(page: CdpPage, timeout: float = 8) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if not _looks_logged_in_url(_current_url(page)):
                return True
        except Exception as e:  # noqa: BLE001
            logger.debug("[Apify signup] wait logout skipped: {}", e)
        time.sleep(0.5)
    return False


def _account_menu_point_script() -> str:
    return """
(() => {
  const visible = (el) => {
    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
  };
  const textOf = (el) => (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
  const clickable = (el) => {
    let cur = el;
    while (cur && cur !== document.body) {
      const style = getComputedStyle(cur);
      if (cur.matches('button,a,[role="button"],[aria-haspopup="menu"],[aria-expanded], [tabindex]') || style.cursor === 'pointer') return cur;
      cur = cur.parentElement;
    }
    return el;
  };
  const nodes = Array.from(document.querySelectorAll('button,a,[role="button"],[aria-haspopup],div,span'))
    .filter(visible)
    .filter((el) => {
      const rect = el.getBoundingClientRect();
      const text = textOf(el);
      return rect.left < 340 && rect.top < 180 && rect.width >= 40 && rect.height >= 18
        && /(Personal|Organizations|@)/i.test(text);
    })
    .sort((a, b) => {
      const ar = a.getBoundingClientRect();
      const br = b.getBoundingClientRect();
      return (ar.width * ar.height) - (br.width * br.height);
    });
  const target = nodes.find((el) => {
    const rect = el.getBoundingClientRect();
    const text = textOf(el);
    return rect.top < 170 && /(Personal|Organizations|@)/i.test(text);
  });
  const el = target ? clickable(target) : null;
  if (!el) return null;
  const rect = el.getBoundingClientRect();
  return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
})()
"""


def _sign_out_point_script() -> str:
    return """
(() => {
  const visible = (el) => {
    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
  };
  const textOf = (el) => (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
  const clickable = (el) => el.closest('button,a,[role="button"],[tabindex]') || el;
  const nodes = Array.from(document.querySelectorAll('button,a,[role="button"],[tabindex],div,span'))
    .filter(visible)
    .filter((el) => /^(Sign\\s*out|Log\\s*out)$/i.test(textOf(el)) || /Sign\\s*out|Log\\s*out/i.test(textOf(el)))
    .sort((a, b) => {
      const ar = a.getBoundingClientRect();
      const br = b.getBoundingClientRect();
      return (ar.width * ar.height) - (br.width * br.height);
    });
  const target = nodes[0] ? clickable(nodes[0]) : null;
  if (!target) return null;
  const rect = target.getBoundingClientRect();
  return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
})()
"""
