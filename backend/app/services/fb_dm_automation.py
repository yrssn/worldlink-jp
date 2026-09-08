"""私信建联的浏览器自动化：进主页→点「发消息」→在聊天小窗发送正文与图片。

同时支持 Facebook 与 Instagram（两者的「发消息」按钮文案与聊天输入框结构一致，
差异主要在发图方式：FB 走粘贴事件注入，IG 走 file input）。
"""
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

# 「发消息」按钮的多语言文案（简体/繁体/英文/日文，FB 与 IG 通用）
_MESSAGE_BUTTON_TEXTS = (
    "发消息", "發送訊息", "发讯息", "发私信", "私信",
    "Message", "Send message", "メッセージ", "メッセージを送信",
)

_CLICK_MESSAGE_JS = """
(() => {
  const texts = %s;
  const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim();
  // 只认主页头部的按钮：帖子（role=article）里的「Message / 私信」链接不算
  const candidates = Array.from(
    document.querySelectorAll('div[role="button"], a[role="button"], a[role="link"], button')
  ).filter((el) => el.offsetParent !== null && !el.closest('[role="article"], [role="feed"], [data-pagelet^="MW"]'));
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


# 只取聊天小窗（Messenger 组合框 MWComposer / aria-label「发消息给…」/ 占位符 Aa）里的输入框，
# 绝不能落到主页帖子下面的「写评论…」框上。
_CHAT_BOXES_JS = """
  const isChatBox = (el) => {
    if (el.closest('[role="article"]')) return false;
    if (el.closest('[data-pagelet="MWComposer"], [data-pagelet^="MWChat"], [data-pagelet^="MWOpenThread"]')) return true;
    const label = (el.getAttribute('aria-label') || '').trim();
    const ph = (el.getAttribute('aria-placeholder') || '').trim();
    if (/评论|評論|comment|コメント|reply|回复|回覆/i.test(label + ' ' + ph)) return false;
    if (ph === 'Aa') return true;
    // FB 小窗：aria-label「发消息给 xxx」；IG 聊天页：aria-label「消息」/ 占位符「Message...」
    return /^(发消息给|發送訊息給|发讯息给|Message |メッセージ)/.test(label)
      || /^(消息|訊息|Message|メッセージ|メッセージを送信)$/.test(label)
      || /Message\\.{3}|发消息|發送訊息|メッセージ/.test(ph);
  };
  const boxes = Array.from(
    document.querySelectorAll('div[role="textbox"][contenteditable="true"]')
  ).filter((el) => el.offsetParent !== null && isChatBox(el));
"""

_FOCUS_CHAT_INPUT_JS = """
(() => {
%s
  if (!boxes.length) return { focused: false };
  const el = boxes[boxes.length - 1];""" % _CHAT_BOXES_JS + """
  el.scrollIntoView({ block: 'center' });
  el.focus();
  return { focused: true, label: (el.getAttribute('aria-label') || '').trim() };
})()
"""

# 确认消息真的发进了聊天窗：在输入框所在的聊天容器（包含 Messenger 面板的最近祖先）里找正文开头
_CHAT_HAS_TEXT_JS = """
(() => {
%s
  if (!boxes.length) return { found: false, reason: 'no-textbox' };
  const needle = %%s;
  const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim();
  let root = boxes[boxes.length - 1];
  for (let i = 0; i < 12 && root.parentElement; i++) {
    root = root.parentElement;
    if (root.querySelector('[data-pagelet^="MWOpenThread"], [data-pagelet^="MWChatTab"], [role="grid"], [role="log"]')) break;
    if (root.matches('[role="dialog"], [role="complementary"], [role="main"]')) break;
  }
  const hay = norm(root.innerText);
  return { found: hay.includes(needle), scoped: root !== document.body };
})()
""" % _CHAT_BOXES_JS

_CHAT_INPUT_TEXT_JS = """
(() => {
%s
  if (!boxes.length) return null;""" % _CHAT_BOXES_JS + """
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
""" + _CHAT_BOXES_JS.replace("%", "%%") + """
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

# Instagram 用 file input 发图：找到聊天区可接受图片的 <input type=file>，
# 用 DataTransfer 直接注入 File 并触发 change（无需真实文件路径，纯页面内完成）。
_SET_FILE_INPUT_JS_TEMPLATE = """
(() => {
  const inputs = Array.from(document.querySelectorAll('input[type="file"]')).filter((i) => {
    const a = (i.getAttribute('accept') || '').toLowerCase();
    return a.includes('.png') || a.includes('.jpg') || a.includes('.jpeg') || a.includes('image');
  });
  if (!inputs.length) return { set: false, reason: 'no-input' };
  const input = inputs[inputs.length - 1];
  const bin = atob(%(b64)s);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  const file = new File([bytes], %(name)s, { type: %(mime)s });
  const dt = new DataTransfer();
  dt.items.add(file);
  input.files = dt.files;
  input.dispatchEvent(new Event('change', { bubbles: true }));
  return { set: true };
})()
"""


class DmCancelled(Exception):
    """任务在发送前被取消。"""


def _message_button_js() -> str:
    return _CLICK_MESSAGE_JS % json.dumps(list(_MESSAGE_BUTTON_TEXTS), ensure_ascii=False)


def open_profile_and_message(
    browser_id: str,
    profile_url: str,
    user: User,
    db: Session,
    message_text: str | None = None,
    image_paths: "list[Path] | None" = None,
    progress: "Callable[[str], None] | None" = None,
    platform: str = "facebook",
    should_stop: "Callable[[], bool] | None" = None,
) -> dict[str, object]:
    """在指定 BitBrowser 窗口中打开达人主页、点「发消息」，并在聊天小窗发送正文/图片。

    platform: "facebook" 或 "instagram"，仅影响发图方式与日志文案。
    should_stop: 每个关键步骤前调用，返回 True 则招 DmCancelled（不会发出消息）。
    返回 dict：page_opened / message_clicked / matched_text / text_sent /
    images_sent / final_url。
    """
    platform = (platform or "facebook").strip().lower()
    tag = "IG DM" if platform == "instagram" else "FB DM"
    site_name = "Instagram" if platform == "instagram" else "Facebook"

    def _log(message: str) -> None:
        logger.info("[{}] {}", tag, message)
        if progress is not None:
            try:
                progress(message)
            except Exception as e:  # noqa: BLE001
                logger.debug("[{}] progress 回调失败: {}", tag, e)

    def _check_stop() -> None:
        if should_stop is not None and should_stop():
            raise DmCancelled("任务已取消，未发送")

    url = (profile_url or "").strip()
    if not url:
        raise ValueError("达人主页链接不能为空")
    _check_stop()
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
        logger.debug("[{}] activate target {} skipped: {}", tag, target_id, e)

    time.sleep(1)
    message_clicked = False
    matched_text: str | None = None
    text_sent = False
    images_sent = 0
    final_url = url
    fail_reason: str | None = None
    try:
        with CdpPage(page_ws, user_id=user.id) as page:
            page.call("Page.enable")
            page.call("Runtime.enable")
            page.call("Page.bringToFront")
            _wait_page_ready(page)
            _log("主页加载完成，查找「发消息」按钮")
            _check_stop()
            message_clicked, matched_text = _click_message_button(page)
            if not message_clicked:
                fail_reason = f"未找到「发消息」按钮（可能未登录 {site_name}、页面未加载完或对方未开放私信）"
                _log(fail_reason)
            elif message_text or image_paths:
                _log(f"已点击「{matched_text}」按钮，等待聊天小窗打开")
                _check_stop()
                if not _open_chat_window(page, _log):
                    fail_reason = "已点「发消息」但聊天小窗未打开（重试 3 次仍未出现输入框）"
                    _log(fail_reason)
                else:
                    _check_stop()
                    text_sent, images_sent = _send_chat_message(
                        page, message_text, image_paths or [], _log, platform
                    )
                    if not (text_sent or images_sent):
                        fail_reason = "聊天小窗已打开但消息未发出（聊天窗内未看到该消息）"
            final_url = str(page.evaluate("window.location.href", timeout=5) or url)
    finally:
        # 成功失败都关掉刚开的标签页，避免窗口内标签堆积
        try:
            cdp_transport.close_target(browser_ws, target_id, user.id)
            _log("已关闭私信标签页")
        except Exception as e:  # noqa: BLE001
            logger.debug("[{}] close target {} skipped: {}", tag, target_id, e)
    return {
        "page_opened": True,
        "message_clicked": message_clicked,
        "matched_text": matched_text,
        "text_sent": text_sent,
        "images_sent": images_sent,
        "final_url": final_url,
        "fail_reason": fail_reason,
        "open_hint": open_result.get("hint"),
    }


def _open_chat_window(page: CdpPage, _log: "Callable[[str], None]", retries: int = 3) -> bool:
    """点完「发消息」后等聊天输入框出现；没出现就再点一次按钮（首次点击偶尔不生效）。"""
    for i in range(retries):
        if _focus_chat_input(page, attempts=10, interval=1.0):
            return True
        if i < retries - 1:
            _log(f"聊天小窗未打开，再点一次「发消息」（第 {i + 2} 次）")
            _click_message_button(page, attempts=5)
    return False


# 兼容旧调用方（历史代码里叫 open_fb_profile_and_message）
open_fb_profile_and_message = open_profile_and_message


def _send_chat_message(
    page: CdpPage,
    message_text: str | None,
    image_paths: "list[Path]",
    _log: "Callable[[str], None]",
    platform: str = "facebook",
) -> tuple[bool, int]:
    """在已打开的聊天小窗里发送正文与图片，返回 (text_sent, images_sent)。"""
    if not _focus_chat_input(page, attempts=3):
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
        cleared = not str(remaining or "").strip()
        appeared = cleared and _wait_text_in_chat(page, text)
        text_sent = cleared and appeared
        if text_sent:
            _log("正文发送成功（聊天窗内已出现该消息）")
        elif not cleared:
            _log("正文发送失败：输入框未清空")
        else:
            _log("正文发送未确认：输入框已清空但聊天窗内未看到该消息，按失败记录，请在窗口内核对")
    if platform == "instagram":
        images_sent = _send_images_ig(page, image_paths, _log)
        return text_sent, images_sent
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


def _send_images_ig(
    page: CdpPage,
    image_paths: "list[Path]",
    _log: "Callable[[str], None]",
) -> int:
    """Instagram 发图：逐张注入 file input → 等预览 → 回车/点发送。返回已发张数。

    IG 聊天区加图后会进入预览态，按回车或点发送按钮即可发出；因无稳定的
    「附件预览」标识，这里以时间兜底 + 输入框状态做尽力确认。
    """
    images_sent = 0
    for path in image_paths:
        try:
            raw = path.read_bytes()
        except OSError as e:
            _log(f"读取图片失败，跳过 {path.name}: {e}")
            continue
        mime = mimetypes.guess_type(path.name)[0] or "image/png"
        js = _SET_FILE_INPUT_JS_TEMPLATE % {
            "b64": json.dumps(base64.b64encode(raw).decode("ascii")),
            "name": json.dumps(path.name, ensure_ascii=False),
            "mime": json.dumps(mime),
        }
        try:
            result = page.evaluate(js, timeout=30)
        except Exception as e:  # noqa: BLE001
            logger.debug("[IG DM] set file input skipped: {}", e)
            result = None
        if not (isinstance(result, dict) and result.get("set")):
            _log(f"未找到图片上传入口，跳过 {path.name}")
            continue
        _log(f"已选择图片 {path.name}，等待预览就绪")
        time.sleep(3)
        # IG 预览态回车发送；兜底再点「发送」按钮
        _press_enter(page)
        time.sleep(1.5)
        js_send = _CLICK_SEND_JS % json.dumps(list(_SEND_BUTTON_TEXTS), ensure_ascii=False)
        try:
            page.evaluate(js_send, timeout=10)
        except Exception as e:  # noqa: BLE001
            logger.debug("[IG DM] click send button skipped: {}", e)
        time.sleep(1.5)
        images_sent += 1
        _log(f"图片 {path.name} 已发送")
    return images_sent


def _wait_text_in_chat(page: CdpPage, text: str, timeout: float = 8) -> bool:
    """发送后在聊天容器里等到正文开头出现（排除帖子评论区）。"""
    first_line = next((ln.strip() for ln in text.splitlines() if ln.strip()), text.strip())
    needle = " ".join(first_line.split())[:60]
    if not needle:
        return True
    js = _CHAT_HAS_TEXT_JS % json.dumps(needle, ensure_ascii=False)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            result = page.evaluate(js, timeout=5)
        except Exception as e:  # noqa: BLE001
            logger.debug("[FB DM] check sent text skipped: {}", e)
            result = None
        if isinstance(result, dict) and result.get("found"):
            return True
        time.sleep(0.5)
    return False


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
    page: CdpPage, attempts: int = 25, interval: float = 1.0
) -> tuple[bool, str | None]:
    """轮询查找并点击「发消息」按钮（页面内容为异步渲染，慢的主页要等 20 秒以上）。"""
    js = _message_button_js()
    for i in range(attempts):
        if i and i % 5 == 0:
            try:
                page.evaluate("window.scrollTo(0, 0)", timeout=5)
            except Exception as e:  # noqa: BLE001
                logger.debug("[FB DM] scroll top skipped: {}", e)
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
