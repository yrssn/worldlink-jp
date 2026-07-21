"""Facebook 私信建联的浏览器自动化：进主页→点「发消息」→在聊天小窗发送正文与图片。"""
from __future__ import annotations

import base64
import json
import mimetypes
import time
from pathlib import Path
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


# 定位聊天小窗里的消息输入框（contenteditable 的 textbox）并聚焦
_FOCUS_CHAT_INPUT_JS = """
(() => {
  const boxes = Array.from(
    document.querySelectorAll('div[role="textbox"][contenteditable="true"]')
  ).filter((el) => el.offsetParent !== null);
  if (!boxes.length) return { focused: false };
  const el = boxes[boxes.length - 1];
  el.scrollIntoView({ block: 'center' });
  el.focus();
  return { focused: true, label: (el.getAttribute('aria-label') || '').trim() };
})()
"""

_CHAT_INPUT_TEXT_JS = """
(() => {
  const boxes = Array.from(
    document.querySelectorAll('div[role="textbox"][contenteditable="true"]')
  ).filter((el) => el.offsetParent !== null);
  if (!boxes.length) return null;
  return (boxes[boxes.length - 1].innerText || '').trim();
})()
"""

# 聊天小窗中的「发送」按钮（粘贴附件后出现的纸飞机图标）
_SEND_BUTTON_TEXTS = ("按 Enter 键发送", "发送", "傳送", "Press enter to send", "Send", "送信", "Enterキーを押して送信")

_CLICK_SEND_JS = """
(() => {
  const texts = %s;
  const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim();
  const candidates = Array.from(
    document.querySelectorAll('div[role="button"], span[role="button"], button')
  ).filter((el) => el.offsetParent !== null);
  for (const el of candidates) {
    const label = norm(el.getAttribute('aria-label'));
    for (const t of texts) {
      if (label === t) {
        el.click();
        return { clicked: true, matched: t };
      }
    }
  }
  return { clicked: false };
})()
"""

# 聊天小窗内是否还有待发送的附件预览（有「移除附件」的删除按钮即为存在）
_HAS_PENDING_ATTACHMENT_JS = """
(() => {
  const labels = ['移除附件', '移除', 'Remove attachment', '添付ファイルを削除'];
  const els = Array.from(document.querySelectorAll('[aria-label]')).filter(
    (el) => el.offsetParent !== null
  );
  return els.some((el) => labels.includes((el.getAttribute('aria-label') || '').trim()));
})()
"""

# 把 base64 图片以粘贴事件注入聊天输入框（FB 支持粘贴图片）
_PASTE_IMAGE_JS_TEMPLATE = """
(() => {
  const boxes = Array.from(
    document.querySelectorAll('div[role="textbox"][contenteditable="true"]')
  ).filter((el) => el.offsetParent !== null);
  if (!boxes.length) return { pasted: false, reason: 'no-textbox' };
  const el = boxes[boxes.length - 1];
  el.focus();
  const bin = atob(%(b64)s);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  const file = new File([bytes], %(name)s, { type: %(mime)s });
  const dt = new DataTransfer();
  dt.items.add(file);
  const evt = new ClipboardEvent('paste', { bubbles: true, cancelable: true, clipboardData: dt });
  el.dispatchEvent(evt);
  return { pasted: true };
})()
"""


def _message_button_js() -> str:
    return _CLICK_MESSAGE_JS % json.dumps(list(_MESSAGE_BUTTON_TEXTS), ensure_ascii=False)


def open_fb_profile_and_message(
    browser_id: str,
    profile_url: str,
    user: User,
    db: Session,
    message_text: str | None = None,
    image_paths: "list[Path] | None" = None,
    progress: "Callable[[str], None] | None" = None,
) -> dict[str, object]:
    """在指定 BitBrowser 窗口中打开达人主页、点「发消息」，并在聊天小窗发送正文/图片。

    返回 dict：page_opened / message_clicked / matched_text / text_sent /
    images_sent / final_url。
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
    text_sent = False
    images_sent = 0
    final_url = url
    with CdpPage(page_ws, user_id=user.id) as page:
        page.call("Page.enable")
        page.call("Runtime.enable")
        page.call("Page.bringToFront")
        _wait_page_ready(page)
        _log("主页加载完成，查找「发消息」按钮")
        message_clicked, matched_text = _click_message_button(page)
        if message_clicked:
            _log(f"已点击「{matched_text}」按钮，等待聊天小窗打开")
            time.sleep(2)
            if message_text or image_paths:
                text_sent, images_sent = _send_chat_message(
                    page, message_text, image_paths or [], _log
                )
        else:
            _log("未找到「发消息」按钮（可能未登录 Facebook，或对方未开放私信）")
        final_url = str(page.evaluate("window.location.href", timeout=5) or url)
    return {
        "page_opened": True,
        "message_clicked": message_clicked,
        "matched_text": matched_text,
        "text_sent": text_sent,
        "images_sent": images_sent,
        "final_url": final_url,
        "open_hint": open_result.get("hint"),
    }


def _send_chat_message(
    page: CdpPage,
    message_text: str | None,
    image_paths: "list[Path]",
    _log: "Callable[[str], None]",
) -> tuple[bool, int]:
    """在已打开的聊天小窗里发送正文与图片，返回 (text_sent, images_sent)。"""
    if not _focus_chat_input(page):
        _log("未找到聊天输入框，无法自动发送（小窗可能未打开）")
        return False, 0
    text_sent = False
    images_sent = 0
    text = (message_text or "").strip()
    if text:
        _log("输入私信正文")
        page.call("Input.insertText", {"text": text}, timeout=15)
        time.sleep(0.5)
        _press_enter(page)
        time.sleep(1.5)
        remaining = page.evaluate(_CHAT_INPUT_TEXT_JS, timeout=5)
        text_sent = not str(remaining or "").strip()
        _log(f"正文发送{'成功' if text_sent else '可能失败（输入框未清空）'}")
    for path in image_paths:
        try:
            raw = path.read_bytes()
        except OSError as e:
            _log(f"读取图片失败，跳过 {path.name}: {e}")
            continue
        mime = mimetypes.guess_type(path.name)[0] or "image/png"
        js = _PASTE_IMAGE_JS_TEMPLATE % {
            "b64": json.dumps(base64.b64encode(raw).decode("ascii")),
            "name": json.dumps(path.name, ensure_ascii=False),
            "mime": json.dumps(mime),
        }
        result = page.evaluate(js, timeout=30)
        if not (isinstance(result, dict) and result.get("pasted")):
            _log(f"图片粘贴失败，跳过 {path.name}")
            continue
        _log(f"已粘贴图片 {path.name}，等待附件预览就绪")
        if not _wait_pending_attachment(page, appear=True):
            _log(f"未检测到附件预览，跳过 {path.name}")
            continue
        time.sleep(1.5)
        if _submit_attachment(page, _log):
            images_sent += 1
            _log(f"图片 {path.name} 已发送")
        else:
            _log(f"图片 {path.name} 发送未确认（附件预览未消失），请在窗口内检查")
    return text_sent, images_sent


def _wait_pending_attachment(
    page: CdpPage, *, appear: bool, timeout: float = 30
) -> bool:
    """等待附件预览出现（appear=True）或发送后消失（appear=False）。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            present = bool(page.evaluate(_HAS_PENDING_ATTACHMENT_JS, timeout=5))
        except Exception as e:  # noqa: BLE001
            logger.debug("[FB DM] check attachment skipped: {}", e)
            present = not appear
        if present == appear:
            return True
        time.sleep(0.5)
    return False


def _submit_attachment(page: CdpPage, _log: "Callable[[str], None]") -> bool:
    """发送已粘贴的附件：重新聚焦后回车，失败则点「发送」按钮兜底。"""
    _focus_chat_input(page, attempts=3)
    _press_enter(page)
    if _wait_pending_attachment(page, appear=False, timeout=8):
        return True
    js = _CLICK_SEND_JS % json.dumps(list(_SEND_BUTTON_TEXTS), ensure_ascii=False)
    try:
        result = page.evaluate(js, timeout=10)
    except Exception as e:  # noqa: BLE001
        logger.debug("[FB DM] click send button skipped: {}", e)
        result = None
    if isinstance(result, dict) and result.get("clicked"):
        _log("回车未生效，已改点「发送」按钮")
    return _wait_pending_attachment(page, appear=False, timeout=10)


def _focus_chat_input(page: CdpPage, attempts: int = 8, interval: float = 1.0) -> bool:
    for _ in range(attempts):
        try:
            result = page.evaluate(_FOCUS_CHAT_INPUT_JS, timeout=10)
        except Exception as e:  # noqa: BLE001
            logger.debug("[FB DM] focus chat input skipped: {}", e)
            result = None
        if isinstance(result, dict) and result.get("focused"):
            return True
        time.sleep(interval)
    return False


def _press_enter(page: CdpPage) -> None:
    common = {
        "key": "Enter",
        "code": "Enter",
        "windowsVirtualKeyCode": 13,
        "nativeVirtualKeyCode": 13,
    }
    page.call("Input.dispatchKeyEvent", {"type": "keyDown", "text": "\r", **common}, timeout=10)
    page.call("Input.dispatchKeyEvent", {"type": "keyUp", **common}, timeout=10)


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
