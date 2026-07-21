"""Facebook 私信建联的浏览器自动化步骤（第一步：进主页并点「发消息」）。"""
from __future__ import annotations

import json
import time
from typing import Callable

from loguru import logger
from sqlalchemy.orm import Session

from app.models.user import User
from app.services import bitbrowser_service, cdp_transport
from app.services.zoho_mail_automation import CdpConnectionClosed, CdpPage

# 「发消息」按钮的多语言文案（简体/繁体/英文/日文）
_MESSAGE_BUTTON_TEXTS = ("发消息", "發送訊息", "发讯息", "Message", "メッセージ", "メッセージを送信")

_CLICK_MESSAGE_JS = """
(() => {
  const texts = %s;
  const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim();
  const candidates = Array.from(
    document.querySelectorAll('div[role="button"], a[role="button"], a[role="link"], button')
  );
  for (const el of candidates) {
    const label = norm(el.getAttribute('aria-label'));
    const text = norm(el.innerText);
    for (const t of texts) {
      if (label === t || text === t) {
        el.scrollIntoView({ block: 'center' });
        el.click();
        return { clicked: true, matched: t };
      }
    }
  }
  return { clicked: false, matched: null };
})()
"""


def _message_button_js() -> str:
    return _CLICK_MESSAGE_JS % json.dumps(list(_MESSAGE_BUTTON_TEXTS), ensure_ascii=False)


def open_fb_profile_and_message(
    browser_id: str,
    profile_url: str,
    user: User,
    db: Session,
    progress: "Callable[[str], None] | None" = None,
) -> dict[str, object]:
    """在指定 BitBrowser 窗口中打开达人主页并点击「发消息」按钮。

    返回 dict：page_opened / message_clicked / matched_text / final_url。
    """

    def _log(message: str) -> None:
        logger.info("[FB DM] {}", message)
        if progress is not None:
            try:
                progress(message)
            except Exception as e:  # noqa: BLE001
                logger.debug("[FB DM] progress 回调失败: {}", e)

    url = (profile_url or "").strip()
    if not url:
        raise ValueError("达人主页链接不能为空")
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"

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

    browser_ws = cdp_transport.extract_browser_ws(open_data)
    _log(f"窗口已打开，新建标签页进入主页：{url}")
    page_ws, target_id = cdp_transport.create_page(browser_ws, url, user.id)
    try:
        cdp_transport.activate_target(browser_ws, target_id, user.id)
    except Exception as e:  # noqa: BLE001
        logger.debug("[FB DM] activate target {} skipped: {}", target_id, e)

    time.sleep(1)
    message_clicked = False
    matched_text: str | None = None
    final_url = url
    with CdpPage(page_ws, user_id=user.id) as page:
        page.call("Page.enable")
        page.call("Runtime.enable")
        page.call("Page.bringToFront")
        _wait_page_ready(page)
        _log("主页加载完成，查找「发消息」按钮")
        message_clicked, matched_text = _click_message_button(page)
        if message_clicked:
            _log(f"已点击「{matched_text}」按钮，等待对话框打开")
            time.sleep(2)
        else:
            _log("未找到「发消息」按钮（可能未登录 Facebook，或对方未开放私信）")
        final_url = str(page.evaluate("window.location.href", timeout=5) or url)
    return {
        "page_opened": True,
        "message_clicked": message_clicked,
        "matched_text": matched_text,
        "final_url": final_url,
        "open_hint": open_result.get("hint"),
    }


def _wait_page_ready(page: CdpPage, timeout: float = 20) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if page.closed:
            return
        try:
            state = page.evaluate("document.readyState", timeout=5)
        except CdpConnectionClosed:
            return
        except Exception as e:  # noqa: BLE001
            logger.debug("[FB DM] wait page ready skipped: {}", e)
            time.sleep(0.3)
            continue
        if state in ("interactive", "complete"):
            return
        time.sleep(0.3)


def _click_message_button(
    page: CdpPage, attempts: int = 10, interval: float = 1.0
) -> tuple[bool, str | None]:
    """轮询查找并点击「发消息」按钮（页面内容为异步渲染）。"""
    js = _message_button_js()
    for _ in range(attempts):
        try:
            result = page.evaluate(js, timeout=10)
        except Exception as e:  # noqa: BLE001
            logger.debug("[FB DM] click message attempt skipped: {}", e)
            result = None
        if isinstance(result, dict) and result.get("clicked"):
            matched = result.get("matched")
            return True, str(matched) if matched else None
        time.sleep(interval)
    return False, None
