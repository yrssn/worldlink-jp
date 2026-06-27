"""使用 CaptchaRun 图像识别服务自动求解 Apify 注册时的 reCAPTCHA 图片挑战。

接口文档：
https://captcharun.atlassian.net/wiki/spaces/captcharunnew/pages/463110445/ReCaptcha

reCAPTCHA 的勾选框(anchor)与图片挑战(bframe)都在跨域(google.com) 的 iframe 内，
普通 ``Runtime.evaluate`` 只能作用于顶层文档，因此这里通过 CDP 的
``Target.getTargets`` / ``Target.attachToTarget`` 拿到 iframe 的 sessionId，
再在该 session 内执行脚本读取题目、抓取图片、点击图块与验证按钮。

仅处理 reCAPTCHA（hcaptcha / arkose 不在本服务范围内）。
"""
from __future__ import annotations

import re
import time
from typing import TYPE_CHECKING

import httpx
from loguru import logger

from app.core.config import settings

if TYPE_CHECKING:  # 避免循环引用，仅做类型提示
    from app.services.apify_signup_automation import CdpPage


# ===== 问题 ID 对照表（英文标签 -> reCAPTCHA /m/ 编号）=====
# 来源：CaptchaRun 文档「问题 ID 对照表」。键为可能出现在题面里的关键词，
# 顺序从更具体到更宽泛，匹配时取第一个命中的关键词。
_QUESTION_KEYWORDS: list[tuple[str, str]] = [
    ("school bus", "/m/02yvhj"),
    ("fire hydrant", "/m/01pns0"),
    ("traffic light", "/m/015qff"),
    ("parking meter", "/m/015qbp"),
    ("palm tree", "/m/0cdl1"),
    ("crosswalk", "/m/014xcs"),
    ("cross walk", "/m/014xcs"),
    ("motorcycle", "/m/04_sv"),
    ("bicycle", "/m/0199g"),
    ("tractor", "/m/013xlm"),
    ("chimney", "/m/01jk_4"),
    ("mountain", "/m/09d_r"),
    ("hill", "/m/09d_r"),
    ("bridge", "/m/015kr"),
    ("stair", "/m/01lynh"),
    ("taxi", "/m/0pg52"),
    ("boat", "/m/019jd"),
    ("bus", "/m/01bjv"),
    ("car", "/m/0k4j"),
]


def _question_id_for(object_text: str) -> str | None:
    text = (object_text or "").strip().lower()
    if not text:
        return None
    text = re.sub(r"^(a|an|the)\s+", "", text)
    for keyword, qid in _QUESTION_KEYWORDS:
        if keyword in text:
            return qid
    return None


# ===== bframe 内执行的 JS =====
_READ_STATE_JS = """
(() => {
  const visible = (el) => {
    if (!el) return false;
    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
  };
  const desc = document.querySelector('.rc-imageselect-desc-no-canonical, .rc-imageselect-desc');
  const strong = desc ? desc.querySelector('strong') : null;
  const object = strong ? (strong.innerText || strong.textContent || '').trim() : '';
  const fullText = desc ? (desc.innerText || desc.textContent || '').trim() : '';
  const tiles = document.querySelectorAll('td.rc-imageselect-tile');
  let size = 0;
  if (document.querySelector('.rc-imageselect-table-44')) size = 4;
  else if (document.querySelector('.rc-imageselect-table-33')) size = 3;
  else if (tiles.length === 16) size = 4;
  else if (tiles.length === 9) size = 3;
  const dynamic = /none left|once there are none/i.test(fullText);
  const hasBigImage = !!document.querySelector('img.rc-image-tile-33, img.rc-image-tile-44');
  const singleCount = document.querySelectorAll('img.rc-image-tile-11').length;
  const verifyBtn = document.querySelector('#recaptcha-verify-button');
  const verifyText = verifyBtn ? (verifyBtn.innerText || verifyBtn.value || '').trim() : '';
  const errorMore = visible(document.querySelector('.rc-imageselect-error-select-more'))
    || visible(document.querySelector('.rc-imageselect-error-dynamic-more'))
    || visible(document.querySelector('.rc-imageselect-error-select-something'));
  const errorTryAgain = visible(document.querySelector('.rc-imageselect-incorrect-response'));
  const challengePresent = !!document.querySelector('.rc-imageselect') || tiles.length > 0;
  return {
    object, fullText, size, tileCount: tiles.length, dynamic,
    hasBigImage, singleCount, verifyText, errorMore, errorTryAgain, challengePresent,
  };
})()
"""

# 抓取大图（3x3 / 4x4 共用的一张拼图）并转为 base64（不含 data: 前缀）
_FETCH_BIG_IMAGE_JS = """
(async () => {
  const img = document.querySelector('img.rc-image-tile-33, img.rc-image-tile-44');
  if (!img || !img.src) return null;
  try {
    const resp = await fetch(img.src);
    const buf = await resp.arrayBuffer();
    const bytes = new Uint8Array(buf);
    let binary = '';
    const chunk = 0x8000;
    for (let i = 0; i < bytes.length; i += chunk) {
      binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
    }
    return btoa(binary);
  } catch (e) {
    return null;
  }
})()
"""

# 抓取动态刷新出来的 1x1 小图，返回 [{index, b64}]
_FETCH_SINGLE_TILES_JS = """
(async () => {
  const tiles = Array.from(document.querySelectorAll('td.rc-imageselect-tile'));
  const out = [];
  for (let i = 0; i < tiles.length; i++) {
    const img = tiles[i].querySelector('img.rc-image-tile-11');
    if (!img || !img.src) continue;
    try {
      const resp = await fetch(img.src);
      const buf = await resp.arrayBuffer();
      const bytes = new Uint8Array(buf);
      let binary = '';
      const chunk = 0x8000;
      for (let j = 0; j < bytes.length; j += chunk) {
        binary += String.fromCharCode.apply(null, bytes.subarray(j, j + chunk));
      }
      out.push({ index: i, b64: btoa(binary) });
    } catch (e) { /* 跳过该图块 */ }
  }
  return out;
})()
"""


def _click_tile_js(index: int) -> str:
    return f"""
(() => {{
  const tiles = document.querySelectorAll('td.rc-imageselect-tile');
  const tile = tiles[{index}];
  if (!tile) return false;
  tile.dispatchEvent(new MouseEvent('mousedown', {{ bubbles: true }}));
  tile.dispatchEvent(new MouseEvent('mouseup', {{ bubbles: true }}));
  tile.click();
  return true;
}})()
"""


_CLICK_VERIFY_JS = """
(() => {
  const btn = document.querySelector('#recaptcha-verify-button');
  if (!btn) return false;
  btn.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
  btn.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
  btn.click();
  return true;
})()
"""

_CLICK_CHECKBOX_JS = """
(() => {
  const box = document.querySelector('.recaptcha-checkbox, #recaptcha-anchor');
  if (!box) return false;
  box.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
  box.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
  box.click();
  return true;
})()
"""

_ANCHOR_CHECKED_JS = """
(() => {
  const box = document.querySelector('.recaptcha-checkbox, #recaptcha-anchor');
  if (!box) return false;
  return box.getAttribute('aria-checked') === 'true'
    || box.classList.contains('recaptcha-checkbox-checked');
})()
"""


def _classify_image(
    image_b64: str,
    question_id: str,
    resize: int,
    token: str,
    base_url: str,
) -> dict[str, object]:
    """调用 CaptchaRun /v2/tasks 同步识别一张图。返回 result 字典。"""
    url = f"{base_url.rstrip('/')}/v2/tasks"
    payload = {
        "captchaType": "ReCaptchaV2Classification",
        "image": image_b64,
        "question": question_id,
        "resize": resize,
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    with httpx.Client(timeout=30, trust_env=False) as client:
        resp = client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
    result = data.get("result") if isinstance(data, dict) else None
    return result if isinstance(result, dict) else {}


def _find_recaptcha_session(page: "CdpPage", needle: str) -> str | None:
    """在所有 target 中找到 url 同时包含 'recaptcha' 与 needle 的 iframe，attach 后返回 sessionId。"""
    try:
        targets = page.list_all_targets()
    except Exception as e:  # noqa: BLE001
        logger.debug("[reCAPTCHA] list targets skipped: {}", e)
        return None
    for target in targets:
        url = str(target.get("url") or "").lower()
        target_type = str(target.get("type") or "").lower()
        if target_type not in {"iframe", "page"}:
            continue
        if "recaptcha" in url and needle in url:
            target_id = str(target.get("targetId") or "")
            if not target_id:
                continue
            try:
                return page.attach_to_target(target_id)
            except Exception as e:  # noqa: BLE001
                logger.debug("[reCAPTCHA] attach target skipped: {}", e)
                return None
    return None


def _is_solved(page: "CdpPage", anchor_sid: str | None) -> bool:
    if not anchor_sid:
        return False
    try:
        return bool(page.evaluate(_ANCHOR_CHECKED_JS, timeout=5, session_id=anchor_sid))
    except Exception as e:  # noqa: BLE001
        logger.debug("[reCAPTCHA] anchor checked check skipped: {}", e)
        return False


def solve_recaptcha(page: "CdpPage", *, log=logger.info) -> dict[str, object]:
    """尝试自动求解当前页面上的 reCAPTCHA 图片挑战。

    返回包含 ``solved`` 等字段的字典，不抛异常（失败时回落人工处理）。
    """
    token = (settings.captcharun_api_token or "").strip()
    base_url = settings.captcharun_api_base
    max_attempts = max(1, int(settings.captcharun_max_attempts or 8))
    if not token:
        return {"attempted": False, "solved": False, "reason": "未配置 CAPTCHARUN_API_TOKEN"}

    anchor_sid = _find_recaptcha_session(page, "anchor")
    bframe_sid = _find_recaptcha_session(page, "bframe")

    # 只有勾选框、挑战还没弹出时，先点一下勾选框触发图片挑战
    if not bframe_sid and anchor_sid:
        try:
            page.evaluate(_CLICK_CHECKBOX_JS, timeout=5, session_id=anchor_sid)
        except Exception as e:  # noqa: BLE001
            logger.debug("[reCAPTCHA] click checkbox skipped: {}", e)
        for _ in range(10):
            time.sleep(1)
            if _is_solved(page, anchor_sid):
                return {"attempted": True, "solved": True, "reason": "勾选即通过"}
            bframe_sid = _find_recaptcha_session(page, "bframe")
            if bframe_sid:
                break

    if not bframe_sid:
        return {"attempted": True, "solved": False, "reason": "未找到 reCAPTCHA 图片挑战 iframe"}

    question_id: str | None = None
    last_object = ""
    for attempt in range(1, max_attempts + 1):
        if _is_solved(page, anchor_sid):
            return {"attempted": True, "solved": True, "attempts": attempt - 1}
        try:
            state = page.evaluate(_READ_STATE_JS, timeout=8, session_id=bframe_sid)
        except Exception as e:  # noqa: BLE001
            logger.debug("[reCAPTCHA] read state skipped: {}", e)
            time.sleep(1)
            continue
        if not isinstance(state, dict):
            time.sleep(1)
            continue
        if not state.get("challengePresent") and not state.get("tileCount"):
            # 挑战已消失，认定通过
            return {"attempted": True, "solved": _is_solved(page, anchor_sid) or True, "attempts": attempt - 1}

        object_text = str(state.get("object") or "")
        last_object = object_text or last_object
        question_id = _question_id_for(object_text) or question_id
        if not question_id:
            return {
                "attempted": True,
                "solved": False,
                "reason": f"题目无法映射到 CaptchaRun 问题ID：{object_text!r}",
                "object": object_text,
            }

        size = int(state.get("size") or 3)
        clicked_any = False

        if state.get("hasBigImage"):
            try:
                image_b64 = page.evaluate(_FETCH_BIG_IMAGE_JS, timeout=20, session_id=bframe_sid)
            except Exception as e:  # noqa: BLE001
                logger.debug("[reCAPTCHA] fetch big image skipped: {}", e)
                image_b64 = None
            if isinstance(image_b64, str) and image_b64:
                resize = 4 if size == 4 else 3
                try:
                    result = _classify_image(image_b64, question_id, resize, token, base_url)
                except Exception as e:  # noqa: BLE001
                    log(f"[reCAPTCHA] CaptchaRun 识别失败：{e}")
                    return {"attempted": True, "solved": False, "reason": f"CaptchaRun 识别失败：{e}"}
                objects = result.get("objects")
                indices = [int(i) for i in objects if isinstance(i, (int, float))] if isinstance(objects, list) else []
                for index in indices:
                    try:
                        if bool(page.evaluate(_click_tile_js(index), timeout=5, session_id=bframe_sid)):
                            clicked_any = True
                            time.sleep(0.3)
                    except Exception as e:  # noqa: BLE001
                        logger.debug("[reCAPTCHA] click tile skipped: {}", e)
        elif state.get("singleCount"):
            try:
                singles = page.evaluate(_FETCH_SINGLE_TILES_JS, timeout=25, session_id=bframe_sid)
            except Exception as e:  # noqa: BLE001
                logger.debug("[reCAPTCHA] fetch single tiles skipped: {}", e)
                singles = None
            if isinstance(singles, list):
                for item in singles:
                    if not isinstance(item, dict):
                        continue
                    b64 = item.get("b64")
                    index = item.get("index")
                    if not isinstance(b64, str) or not b64 or not isinstance(index, (int, float)):
                        continue
                    try:
                        result = _classify_image(b64, question_id, 1, token, base_url)
                    except Exception as e:  # noqa: BLE001
                        log(f"[reCAPTCHA] CaptchaRun 识别失败：{e}")
                        return {"attempted": True, "solved": False, "reason": f"CaptchaRun 识别失败：{e}"}
                    if bool(result.get("hasObject")):
                        try:
                            if bool(page.evaluate(_click_tile_js(int(index)), timeout=5, session_id=bframe_sid)):
                                clicked_any = True
                                time.sleep(0.3)
                        except Exception as e:  # noqa: BLE001
                            logger.debug("[reCAPTCHA] click single tile skipped: {}", e)

        is_dynamic = bool(state.get("dynamic"))
        if clicked_any and is_dynamic:
            # 动态挑战：点击后图块会刷新，等待新图加载再进入下一轮
            log(f"[reCAPTCHA] 第 {attempt} 轮已点击匹配图块（动态刷新），继续识别")
            time.sleep(2)
            continue

        # 静态挑战，或动态挑战已无可点 → 提交验证
        try:
            page.evaluate(_CLICK_VERIFY_JS, timeout=5, session_id=bframe_sid)
        except Exception as e:  # noqa: BLE001
            logger.debug("[reCAPTCHA] click verify skipped: {}", e)
        time.sleep(2.5)

        if _is_solved(page, anchor_sid):
            log(f"[reCAPTCHA] 验证通过（共 {attempt} 轮）")
            return {"attempted": True, "solved": True, "attempts": attempt}
        # 未通过：可能提示「请再试一次」或「请选择更多」，继续下一轮重新识别
        log(f"[reCAPTCHA] 第 {attempt} 轮提交后未通过，重试")
        time.sleep(1)

    return {
        "attempted": True,
        "solved": _is_solved(page, anchor_sid),
        "reason": "超过最大识别轮数仍未通过",
        "object": last_object,
        "attempts": max_attempts,
    }
