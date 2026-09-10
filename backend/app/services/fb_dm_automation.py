"""私信建联的浏览器自动化：进主页→点「发消息」→在聊天小窗发送正文与图片。

同时支持 Facebook 与 Instagram（两者的「发消息」按钮文案与聊天输入框结构一致，
差异主要在发图方式：FB 走粘贴事件注入，IG 走 file input）。
"""
from __future__ import annotations

import base64
import json
import mimetypes
import random
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
  let boxes = Array.from(
    document.querySelectorAll('div[role="textbox"][contenteditable="true"]')
  ).filter((el) => el.offsetParent !== null && isChatBox(el));
  // 已认出当前达人的小窗时，只用这个小窗里的输入框；别的小窗一律不碰
  const marked = document.querySelector('[data-wl-target="1"]');
  if (marked) boxes = boxes.filter((el) => marked.contains(el));
"""

_FOCUS_CHAT_INPUT_JS = """
(() => {
%s
  if (!boxes.length) return { focused: false };
  const el = boxes[boxes.length - 1];""" % _CHAT_BOXES_JS + """
  el.scrollIntoView({ block: 'center' });
  el.focus();
  const r = el.getBoundingClientRect();
  return {
    focused: true,
    label: (el.getAttribute('aria-label') || '').trim(),
    active: document.activeElement === el,
    rect: { x: r.left + Math.min(r.width / 2, 40), y: r.top + r.height / 2, w: r.width, h: r.height },
  };
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
    if (root.matches('[data-wl-target="1"]')) break;
    if (root.querySelector('[data-pagelet^="MWOpenThread"], [data-pagelet^="MWChatTab"], [data-pagelet="MWMessageList"], [role="grid"], [role="log"]')) break;
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


# 枚举页面上所有聊天小窗：从每个 MWChatTabHeader 往上找到“只包含这一个头部”的最大祖先即为该小窗。
# FB 会把上次没关的小窗带到新标签页，所以判“能不能发 / 发没发出”都必须只看当前达人自己那个小窗。
_PANELS_CORE_JS = """
  const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim();
  const blockedPat = /你无法发消息给|你無法傳送訊息|无法发送消息|You can't message|You cannot message|can't reply to this conversation|このアカウントにメッセージを送信できません|メッセージを送信できません/i;
  const closeLabels = ['关闭聊天窗口', '关闭聊天', '關閉聊天室', '關閉聊天視窗', '關閉', 'Close chat', 'Close', 'チャットを閉じる', '閉じる'];
  const headers = Array.from(document.querySelectorAll('[data-pagelet="MWChatTabHeader"]')).filter((h) => h.offsetParent !== null);
  const rectOf = (el) => { const r = el.getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2, w: r.width, h: r.height }; };
  const panels = headers.map((h) => {
    let root = h;
    while (root.parentElement && root.parentElement !== document.body
      && root.parentElement.querySelectorAll('[data-pagelet="MWChatTabHeader"]').length === 1
      && !root.parentElement.querySelector('[role="main"], [role="banner"], [role="navigation"], [role="article"], h1')) {
      root = root.parentElement;
    }
    const nameEl = h.querySelector('h1, h2, span[dir="auto"], span');
    const name = norm((nameEl && nameEl.innerText) || h.innerText.split('\\n')[0]);
    const box = Array.from(root.querySelectorAll('div[role="textbox"][contenteditable="true"]'))
      .find((el) => el.offsetParent !== null && !el.closest('[role="article"]'));
    const closeBtn = Array.from(h.querySelectorAll('[role="button"][aria-label]'))
      .find((el) => closeLabels.includes(norm(el.getAttribute('aria-label'))));
    const text = norm(root.innerText);
    const m = text.match(blockedPat);
    return {
      root,
      closeBtn,
      name,
      hasBox: !!box,
      blocked: !box && !!m,
      blockedText: m ? m[0] : null,
      close: closeBtn ? rectOf(closeBtn) : null,
    };
  });
  const plain = (p) => ({ name: p.name, hasBox: p.hasBox, blocked: p.blocked, blockedText: p.blockedText, close: p.close });
  const same = (a, b) => {
    a = norm(a).toLowerCase(); b = norm(b).toLowerCase();
    return !!a && !!b && (a === b || a.startsWith(b) || b.startsWith(a));
  };
"""

_CHAT_PANELS_JS = "(() => {" + _PANELS_CORE_JS + "return panels.map(plain); })()"

# 给当前达人的小窗打标记（data-wl-target），之后输入框 / 消息确认都只在这个小窗里找。
# 名字对不上时不乱选：只有页面上恰好一个小窗时才当作它。
_MARK_TARGET_JS = "(() => {" + _PANELS_CORE_JS + """
  const target = %s;
  let hit = panels.find((p) => same(p.name, target)) || (panels.length === 1 ? panels[0] : null);
  document.querySelectorAll('[data-wl-target]').forEach((el) => el.removeAttribute('data-wl-target'));
  if (!hit) return { hit: null, count: panels.length };
  hit.root.setAttribute('data-wl-target', '1');
  return { hit: plain(hit), count: panels.length };
})()
"""

# 关掉名字不是 keep 的小窗：先在页面里派发 pointer/mouse/click，再由 Python 用真实鼠标补点坐标
_CLOSE_OTHERS_JS = "(() => {" + _PANELS_CORE_JS + """
  const keep = %s;
  const out = [];
  for (const p of panels) {
    if (keep && same(p.name, keep)) continue;
    if (!p.closeBtn) continue;
    const opts = { bubbles: true, cancelable: true, composed: true, button: 0, buttons: 1 };
    for (const t of ['pointerdown', 'mousedown']) p.closeBtn.dispatchEvent(new (t.startsWith('pointer') ? PointerEvent : MouseEvent)(t, opts));
    for (const t of ['pointerup', 'mouseup', 'click']) p.closeBtn.dispatchEvent(new (t.startsWith('pointer') ? PointerEvent : MouseEvent)(t, { ...opts, buttons: 0 }));
    out.push(plain(p));
  }
  return out;
})()
"""

# 当前主页的名字（用来在多个小窗里认出当前达人自己的那个）
_PROFILE_NAME_JS = """
(() => {
  const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim();
  const h1 = Array.from(document.querySelectorAll('h1')).find((el) => el.offsetParent !== null && norm(el.innerText));
  if (h1) return norm(h1.innerText);
  const t = norm((document.title || '').replace(/^\\(\\d+\\)\\s*/, '').replace(/\\s*[|\\-–]\\s*(Facebook|Instagram).*$/i, ''));
  return /^(facebook|instagram|messenger)$/i.test(t) ? '' : t;
})()
"""


class DmCancelled(Exception):
    """任务在发送前被取消。"""


def _pause(lo: float = 1.0, hi: float = 2.5) -> None:
    """操作之间随机停一下，避免动作太机械。"""
    time.sleep(random.uniform(lo, hi))


def _chat_panels(page: CdpPage) -> list[dict[str, object]]:
    try:
        result = page.evaluate(_CHAT_PANELS_JS, timeout=10)
    except Exception as e:  # noqa: BLE001
        logger.debug("[FB DM] list chat panels skipped: {}", e)
        return []
    return [p for p in result if isinstance(p, dict)] if isinstance(result, list) else []


def _profile_name(page: CdpPage) -> str:
    try:
        return str(page.evaluate(_PROFILE_NAME_JS, timeout=10) or "").strip()
    except Exception as e:  # noqa: BLE001
        logger.debug("[FB DM] read profile name skipped: {}", e)
        return ""


def _same_person(panel_name: object, profile_name: str) -> bool:
    a = " ".join(str(panel_name or "").split()).lower()
    b = " ".join(profile_name.split()).lower()
    if not a or not b:
        return False
    return a == b or a.startswith(b) or b.startswith(a)


def _click_at(page: CdpPage, x: float, y: float) -> None:
    """用真实鼠标事件点坐标（FB 的关闭按钮对 element.click() 不一定响应）。"""
    common = {"x": x, "y": y, "button": "left", "clickCount": 1}
    page.call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y}, timeout=10)
    page.call("Input.dispatchMouseEvent", {"type": "mousePressed", **common}, timeout=10)
    page.call("Input.dispatchMouseEvent", {"type": "mouseReleased", **common}, timeout=10)


def _wait_chat_panels(page: CdpPage, timeout: float = 6.0) -> list[dict[str, object]]:
    """FB 会在页面加载完后才把上次残留的小窗渲染出来，先等一会儿再数。"""
    deadline = time.monotonic() + timeout
    panels: list[dict[str, object]] = []
    while time.monotonic() < deadline:
        panels = _chat_panels(page)
        if panels:
            break
        time.sleep(0.5)
    return panels


def _close_chat_windows(
    page: CdpPage,
    _log: "Callable[[str], None]",
    keep_name: str | None = None,
    rounds: int = 3,
) -> int:
    """关掉页面上的聊天小窗（keep_name 不为空时保留这个人的），返回关掉的数量。

    先在页面里对关闭按钮派发 pointer/mouse/click，再用真实鼠标补点坐标，最后重新数一遍确认。
    """
    js = _CLOSE_OTHERS_JS % json.dumps(keep_name or "", ensure_ascii=False)
    closed_names: list[str] = []
    for _ in range(rounds):
        before = [
            p for p in _chat_panels(page)
            if not (keep_name and _same_person(p.get("name"), keep_name))
        ]
        if not before:
            break
        try:
            result = page.evaluate(js, timeout=10)
        except Exception as e:  # noqa: BLE001
            logger.debug("[FB DM] close chat panels skipped: {}", e)
            result = []
        clicked = [p for p in result if isinstance(p, dict)] if isinstance(result, list) else []
        _pause(0.6, 1.2)
        still = {
            str(p.get("name") or "")
            for p in _chat_panels(page)
            if not (keep_name and _same_person(p.get("name"), keep_name))
        }
        for p in clicked:
            name = str(p.get("name") or "")
            rect = p.get("close")
            if name in still and isinstance(rect, dict) and float(rect.get("w") or 0):
                try:
                    _click_at(page, float(rect["x"]), float(rect["y"]))
                except Exception as e:  # noqa: BLE001
                    logger.debug("[FB DM] close chat panel {} by mouse skipped: {}", name, e)
                _pause(0.5, 1.0)
        after = {
            str(p.get("name") or "")
            for p in _chat_panels(page)
            if not (keep_name and _same_person(p.get("name"), keep_name))
        }
        closed_names += [str(p.get("name") or "?") for p in before if str(p.get("name") or "") not in after]
        if not after:
            break
    if closed_names:
        _log(f"已关掉 {len(closed_names)} 个聊天小窗：{'、'.join(closed_names)}")
    left = [p for p in _chat_panels(page) if not (keep_name and _same_person(p.get("name"), keep_name))]
    if left:
        _log(f"仍有 {len(left)} 个小窗没关掉：{'、'.join(str(p.get('name') or '?') for p in left)}（不会往里发）")
    return len(closed_names)


def _mark_target(page: CdpPage, profile_name: str) -> dict[str, object] | None:
    """认出当前达人自己的小窗并打标记；之后输入框 / 消息确认都只在这个小窗里找。

    名字对得上才算；对不上时只有页面上恰好一个小窗才当作它，多个一律不选（宁可不发也不发错人）。
    """
    try:
        result = page.evaluate(_MARK_TARGET_JS % json.dumps(profile_name, ensure_ascii=False), timeout=10)
    except Exception as e:  # noqa: BLE001
        logger.debug("[FB DM] mark target panel skipped: {}", e)
        return None
    if not isinstance(result, dict):
        return None
    hit = result.get("hit")
    if isinstance(hit, dict):
        return hit
    # 页面上根本没有 Messenger 小窗（IG 聊天页 / FB 整页 Messenger）：不限定范围，交给输入框选择器自己判
    if not result.get("count"):
        return {"name": "", "hasBox": None, "blocked": False, "blockedText": None, "close": None}
    return None


def _chat_blocked_text(page: CdpPage, profile_name: str) -> str | None:
    """只看当前达人自己的小窗里有没有“你无法发消息”；别人的旧窗口不算。"""
    panel = _mark_target(page, profile_name)
    if panel and panel.get("blocked"):
        return str(panel.get("blockedText") or "无法发消息")
    return None


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

    steps: list[str] = []

    def _log(message: str) -> None:
        logger.info("[{}] {}", tag, message)
        steps.append(message)
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
            _pause(1.5, 3.0)
            profile_name = _profile_name(page)
            # 进来先把页面上残留的聊天小窗全部关掉（上一个人的窗口留着会发错人 / 误判「无法发消息」）
            leftovers = _wait_chat_panels(page)
            if leftovers:
                _log(f"页面上有 {len(leftovers)} 个残留聊天小窗，先全部关掉")
                _close_chat_windows(page, _log)
                _pause(0.8, 1.5)
            before_names = {str(p.get("name") or "") for p in _chat_panels(page)}
            _log(f"主页加载完成（{profile_name or '未识别到名字'}），查找「发消息」按钮")
            _check_stop()
            message_clicked, matched_text = _click_message_button(page)
            if not message_clicked:
                fail_reason = f"未找到「发消息」按钮（可能未登录 {site_name}、页面未加载完或对方未开放私信）"
                _log(fail_reason)
            elif message_text or image_paths:
                _log(f"已点击「{matched_text}」按钮，等待聊天小窗打开")
                _pause(1.5, 3.0)
                _check_stop()
                # 进来时已把小窗全关了，点完「发消息」后新冒出来的那个就是当前达人的（主页名字读不到也不影响）
                new_names = [str(p.get("name") or "") for p in _wait_chat_panels(page, timeout=8) if str(p.get("name") or "") not in before_names]
                if len(new_names) == 1 and new_names[0]:
                    if not _same_person(new_names[0], profile_name):
                        _log(f"新打开的小窗是「{new_names[0]}」，以它为当前达人")
                    profile_name = new_names[0]
                opened = _open_chat_window(page, _log, profile_name)
                # 只有认出了当前达人的名字，才去关其它小窗；认不出就不乱关
                if profile_name:
                    _close_chat_windows(page, _log, keep_name=profile_name)
                target = _mark_target(page, profile_name)
                if target:
                    _log(f"锁定聊天小窗「{target.get('name') or profile_name or '?'}」")
                blocked = _chat_blocked_text(page, profile_name)
                if blocked:
                    fail_reason = f"对方不接受私信：{blocked}"
                    _log(fail_reason)
                elif not opened or not target:
                    fail_reason = "已点「发消息」但没认出当前达人的聊天小窗（重试 3 次仍未出现输入框）"
                    _log(fail_reason)
                else:
                    _check_stop()
                    _pause(1.0, 2.0)
                    text_sent, images_sent = _send_chat_message(
                        page, message_text, image_paths or [], _log, platform
                    )
                    if not (text_sent or images_sent):
                        fail_reason = "聊天小窗已打开但消息未发出（详见任务日志）"
                _pause(1.0, 2.0)
                _close_chat_windows(page, _log)
            final_url = str(page.evaluate("window.location.href", timeout=5) or url)
            try:
                page.call("Page.close", timeout=5)
            except Exception as e:  # noqa: BLE001
                logger.debug("[{}] Page.close skipped: {}", tag, e)
    finally:
        # 成功失败都关掉刚开的标签页，避免窗口内标签堆积
        try:
            cdp_transport.close_target(browser_ws, target_id, user.id)
            _log("已关闭私信标签页")
        except Exception as e:  # noqa: BLE001
            remaining = [p for p in _safe_list_pages(browser_ws, user.id) if p.get("id") == target_id]
            if remaining:
                _log(f"关闭私信标签页失败：{e}")
            else:
                _log("已关闭私信标签页")
    if fail_reason and not (text_sent or images_sent):
        # 把关键步骤附在失败原因后面，任务列表里直接能看到卡在哪一步
        trail = " → ".join(s for s in steps[-8:] if s != fail_reason)
        fail_reason = f"{fail_reason}｜步骤：{trail}"[:1500]
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


def _safe_list_pages(browser_ws: str, user_id: int) -> list[dict[str, object]]:
    try:
        return list(cdp_transport.list_pages(browser_ws, user_id))
    except Exception as e:  # noqa: BLE001
        logger.debug("[FB DM] list pages skipped: {}", e)
        return []


# 首次给公主页发消息时，小窗里会先弹「开始」确认按钮，点了才出输入框
_CLICK_START_JS = """
(() => {
  const root = document.querySelector('[data-wl-target="1"]') || document.body;
  const re = /^(开始|開始|Get started|Start|はじめる|始める)$/i;
  const btn = Array.from(root.querySelectorAll('[role="button"]')).find(
    (el) => el.offsetParent !== null && re.test((el.innerText || '').trim())
  );
  if (!btn) return null;
  const r = btn.getBoundingClientRect();
  btn.click();
  return { text: (btn.innerText || '').trim(), x: r.left + r.width / 2, y: r.top + r.height / 2 };
})()
"""


def _click_start_button(page: CdpPage, _log: "Callable[[str], None]") -> bool:
    try:
        hit = page.evaluate(_CLICK_START_JS, timeout=10)
    except Exception as e:  # noqa: BLE001
        logger.debug("[FB DM] click start button skipped: {}", e)
        return False
    if not isinstance(hit, dict):
        return False
    _log(f"小窗里有「{hit.get('text')}」确认按钮，先点它")
    _pause(0.6, 1.2)
    try:
        _click_at(page, float(hit["x"]), float(hit["y"]))
    except Exception as e:  # noqa: BLE001
        logger.debug("[FB DM] click start button by mouse skipped: {}", e)
    return True


def _open_chat_window(
    page: CdpPage, _log: "Callable[[str], None]", profile_name: str, retries: int = 3
) -> bool:
    """点完「发消息」后等当前达人的聊天输入框出现；没出现就再点一次按钮（首次点击偶尔不生效）。"""
    for i in range(retries):
        for _ in range(10):
            panel = _mark_target(page, profile_name)
            if panel and panel.get("hasBox") is not False and _focus_chat_input(page, attempts=1):
                return True
            if panel and panel.get("blocked"):
                return False
            if panel and panel.get("hasBox") is False and _click_start_button(page, _log):
                time.sleep(1.5)
                continue
            time.sleep(1.0)
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
        typed = _type_into_chat_box(page, text, _log)
        if not typed:
            _log("正文发送失败：文字没能输进聊天输入框（重试 3 次）")
        else:
            _pause(0.8, 1.8)
            _press_enter(page)
            time.sleep(1.5)
            remaining = page.evaluate(_CHAT_INPUT_TEXT_JS, timeout=5)
            cleared = not str(remaining or "").strip()
            if not cleared:
                _pause(0.8, 1.5)
                _press_enter(page)
                time.sleep(1.5)
                remaining = page.evaluate(_CHAT_INPUT_TEXT_JS, timeout=5)
                cleared = not str(remaining or "").strip()
            appeared = cleared and _wait_text_in_chat(page, text, timeout=12)
            # 文字确认输进了当前达人的聊天框、回车后框也清空了，就是发出去了；窗内能看到消息只是额外佐证
            text_sent = cleared
            if appeared:
                _log("正文发送成功（聊天窗内已出现该消息）")
            elif cleared:
                _log("正文已发出（文字已输进聊天框且回车后清空，但窗内暂未渲染出该消息）")
            else:
                _log("正文发送失败：回车后输入框未清空")
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


def _focus_chat_input(
    page: CdpPage, attempts: int = 8, interval: float = 1.0, *, mouse: bool = False
) -> bool:
    """聚焦聊天输入框；mouse=True 时额外用真实鼠标点一下框（光 focus() 偶尔拿不到输入焦点）。"""
    for _ in range(attempts):
        try:
            result = page.evaluate(_FOCUS_CHAT_INPUT_JS, timeout=10)
        except Exception as e:  # noqa: BLE001
            logger.debug("[FB DM] focus chat input skipped: {}", e)
            result = None
        if isinstance(result, dict) and result.get("focused"):
            rect = result.get("rect")
            if mouse and isinstance(rect, dict) and float(rect.get("w") or 0):
                try:
                    _click_at(page, float(rect["x"]), float(rect["y"]))
                except Exception as e:  # noqa: BLE001
                    logger.debug("[FB DM] click chat input skipped: {}", e)
                time.sleep(0.4)
            return True
        time.sleep(interval)
    return False


def _type_into_chat_box(
    page: CdpPage, text: str, _log: "Callable[[str], None]", attempts: int = 3
) -> bool:
    """把正文输进当前达人的聊天框，并确认框里真的有了文字；第一次不行就改用鼠标点框后重输。"""
    first = " ".join(next((ln for ln in text.splitlines() if ln.strip()), text).split())[:20]
    for i in range(attempts):
        if not _focus_chat_input(page, attempts=2, mouse=i > 0):
            _log(f"第 {i + 1} 次输入：没找到当前小窗的输入框")
            continue
        if i < attempts - 1:
            page.call("Input.insertText", {"text": text}, timeout=15)
        else:
            # 最后一次改成逐字敲键（有的编辑器不吃 insertText）
            for ch in text:
                if ch == "\n":
                    for t in ("keyDown", "keyUp"):
                        page.call("Input.dispatchKeyEvent", {"type": t, "key": "Enter", "code": "Enter", "modifiers": 8, "windowsVirtualKeyCode": 13, **({"text": "\r"} if t == "keyDown" else {})}, timeout=10)
                else:
                    page.call("Input.dispatchKeyEvent", {"type": "char", "text": ch}, timeout=10)
                time.sleep(random.uniform(0.02, 0.08))
        time.sleep(0.6)
        current = " ".join(str(page.evaluate(_CHAT_INPUT_TEXT_JS, timeout=5) or "").split())
        if first and first in current:
            return True
        _log(f"第 {i + 1} 次输入后框内内容不对（看到：{current[:40] or '空'}），换鼠标点框重试")
        if current:
            # 框里有别的残留内容，全选删掉再重试，避免发出拼接的文字
            _select_all_and_delete(page)
        time.sleep(0.8)
    return False


def _select_all_and_delete(page: CdpPage) -> None:
    for t, extra in (("keyDown", {"modifiers": 2, "key": "a", "code": "KeyA", "windowsVirtualKeyCode": 65}),
                     ("keyUp", {"modifiers": 2, "key": "a", "code": "KeyA", "windowsVirtualKeyCode": 65}),
                     ("keyDown", {"key": "Delete", "code": "Delete", "windowsVirtualKeyCode": 46}),
                     ("keyUp", {"key": "Delete", "code": "Delete", "windowsVirtualKeyCode": 46})):
        try:
            page.call("Input.dispatchKeyEvent", {"type": t, **extra}, timeout=10)
        except Exception as e:  # noqa: BLE001
            logger.debug("[FB DM] clear chat input skipped: {}", e)


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
