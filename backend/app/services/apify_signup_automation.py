"""Apify 注册流程的浏览器自动化步骤。"""
from __future__ import annotations

import json
import time
from collections.abc import Callable
from datetime import datetime
from urllib.parse import quote, urljoin, urlparse

from loguru import logger
from sqlalchemy.orm import Session

from app.models.user import User
from app.services import bitbrowser_service
from app.services.cdp_relay import CdpPage, devtools_request
from app.services.zoho_mail_automation import open_latest_apify_verification_link

SIGNUP_URL = "https://console.apify.com/sign-up"
LOGIN_URL = "https://console.apify.com/log-in"
SIGNIN_URL = "https://console.apify.com/sign-in"
SETTINGS_INTEGRATIONS_URL = "https://console.apify.com/settings/integrations"
HUMAN_VERIFICATION_TIMEOUT = 600
ProgressCallback = Callable[[str, str], None]


def _emit_progress(progress_callback: ProgressCallback | None, node: str, message: str) -> None:
    if progress_callback is not None:
        progress_callback(node, message)


def start_apify_signup(
    browser_id: str,
    email: str,
    password: str,
    user: User,
    db: Session,
    mail_login_url: str | None = None,
    progress_callback: ProgressCallback | None = None,
    mail_already_logged_in: bool = False,
) -> dict[str, object]:
    logger.info("[Apify signup] start flow browser_id={} email={}", browser_id, email)
    if mail_already_logged_in:
        _emit_progress(progress_callback, "open_browser", "复用已登录邮箱的 BitBrowser 窗口，保留 Zoho Cookie")
        profile_clear_result: dict[str, object] = {}
        restart_browser = False
    else:
        _emit_progress(progress_callback, "open_browser", "启动并清理 BitBrowser/Apify 会话")
        bitbrowser_service.close_browser_window(browser_id, user)
        time.sleep(1)
        profile_clear_result = bitbrowser_service.clear_browser_profile_cookies(browser_id, user)
        time.sleep(0.5)
        restart_browser = True
    open_result = bitbrowser_service.open_browser_window(
        browser_id,
        user,
        db,
        headless=False,
        restart=restart_browser,
        ignore_default_urls=True,
    )
    open_data = open_result.get("data") or {}
    if not isinstance(open_data, dict) or not open_data:
        raise RuntimeError("BitBrowser 已打开，但未返回 CDP 连接信息；请先关再开该环境后重试")

    http_base = _extract_devtools_http(open_data)
    _close_apify_pages(http_base, user_id=user.id)
    page_ws = _create_page(http_base, SIGNUP_URL, user_id=user.id)
    with CdpPage(page_ws, user_id=user.id) as page:
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
        if _looks_logged_in_url(post_clear_url) and not mail_already_logged_in:
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
                "profile_submitted": False,
                "captcha_required": False,
                "open_hint": open_result.get("hint"),
            }
        logger.info("[Apify signup] submitting signup email browser_id={} email={}", browser_id, email)
        _emit_progress(progress_callback, "submit_email", "填写 Apify 注册邮箱")
        email_submitted = _submit_email(page, email)
        logger.info("[Apify signup] submitting signup password browser_id={} email={}", browser_id, email)
        _emit_progress(progress_callback, "submit_password", "填写 Apify 注册密码并提交")
        password_submitted = _submit_password(page, password)
        _wait_for_apify_post_submit_state(page)
        email_already_taken = _has_email_already_taken_error(page)
        captcha_required = False if email_already_taken else _wait_for_captcha(page)
        profile_submitted = False
        apify_login_attempted = False
        apify_logged_in = False
        email_verification_required = False
        login_result: dict[str, object] = {}
        profile_details: dict[str, object] = {
            "submitted": False,
            "full_name": _profile_name_from_email(email),
            "username": None,
        }
        if captcha_required:
            logger.info(
                "[Apify signup] human verification required; waiting browser_id={} email={}",
                browser_id,
                email,
            )
            _emit_progress(progress_callback, "human_verification", "等待人工完成人机验证")
            post_human_state = _wait_for_human_verification_result(
                page,
                browser_id,
                email,
                progress_callback=progress_callback,
            )
            email_already_taken = bool(post_human_state.get("email_already_taken"))
            email_verification_required = bool(post_human_state.get("email_verification_required"))
            captcha_required = bool(post_human_state.get("captcha_required"))
            logger.info(
                "[Apify signup] human verification wait finished browser_id={} email={} captcha_required={} email_already_taken={} email_verification_required={}",
                browser_id,
                email,
                captcha_required,
                email_already_taken,
                email_verification_required,
            )
        if email_already_taken and not captcha_required:
            logger.info("[Apify signup] email already taken; switching to login browser_id={} email={}", browser_id, email)
            _emit_progress(progress_callback, "login_existing_account", "邮箱已注册，切换到 Apify 登录")
            apify_login_attempted = True
            login_result = _login_existing_apify_account(page, email, password)
            apify_logged_in = bool(login_result.get("logged_in"))
            captcha_required = bool(login_result.get("captcha_required"))
            email_verification_required = bool(login_result.get("email_verification_required"))
            logger.info(
                "[Apify signup] login fallback finished browser_id={} email={} email_submitted={} password_submitted={} logged_in={} captcha_required={} email_verification_required={} final_url={}",
                browser_id,
                email,
                bool(login_result.get("email_submitted")),
                bool(login_result.get("password_submitted")),
                apify_logged_in,
                captcha_required,
                email_verification_required,
                str(login_result.get("final_url") or ""),
            )
        elif password_submitted and not email_already_taken and not captcha_required:
            logger.info("[Apify signup] completing welcome profile browser_id={} email={}", browser_id, email)
            _emit_progress(progress_callback, "welcome_profile", "填写 Apify 欢迎页资料")
            profile_details = _complete_welcome_profile_details(page, email)
            profile_submitted = bool(profile_details.get("submitted"))
            if profile_submitted:
                _wait_after_profile_continue(page)
            email_verification_required = _is_email_verification_page(page)
        final_url = _current_url(page)

    mail_result: dict[str, object] = {}
    email_verified = False
    token_result: dict[str, object] = {}
    if apify_login_attempted:
        ready = (apify_logged_in or email_verification_required) and not captcha_required
    else:
        ready = (password_submitted or apify_logged_in or email_verification_required) and not captcha_required
    if email_verification_required and password:
        logger.info("[Apify signup] opening Zoho verification mail browser_id={} email={}", browser_id, email)
        _emit_progress(progress_callback, "email_verification", "打开 Zoho 邮箱并点击 Apify 验证链接")
        mail_result = open_latest_apify_verification_link(
            browser_id,
            mail_login_url,
            email,
            password,
            user,
            db,
            ensure_login=not mail_already_logged_in,
        )
        email_verified = bool(mail_result.get("apify_verification_link_clicked"))
        logger.info(
            "[Apify signup] Zoho verification result browser_id={} email={} inbox_ready={} mail_opened={} link_clicked={}",
            browser_id,
            email,
            bool(mail_result.get("apify_mail_inbox_ready")),
            bool(mail_result.get("apify_mail_opened")),
            email_verified,
        )

    if email_verification_required:
        can_collect_token = not captcha_required and email_verified
    else:
        can_collect_token = not captcha_required and (apify_logged_in or ready)
    if can_collect_token:
        logger.info("[Apify signup] collecting Apify token browser_id={} email={}", browser_id, email)
        _emit_progress(progress_callback, "collect_token", "进入 Apify integrations 采集默认 API token")
        refreshed_ws = _find_apify_page(http_base, user_id=user.id) or _create_page(
            http_base, SETTINGS_INTEGRATIONS_URL, user_id=user.id
        )
        with CdpPage(refreshed_ws, user_id=user.id) as page:
            page.call("Page.enable")
            page.call("Network.enable")
            page.call("Runtime.enable")
            page.call("Page.bringToFront")
            if email_verified:
                _refresh_apify_after_email_verification(page)
                _wait_for_apify_email_verified(page)
            token_result = _collect_apify_token_from_settings(page)
            if token_result.get("apify_token"):
                ready = True
                final_url = str(token_result.get("final_url") or final_url)
        logger.info(
            "[Apify signup] token collection finished browser_id={} email={} token_collected={} user_id_present={}",
            browser_id,
            email,
            bool(token_result.get("apify_token")),
            bool(token_result.get("apify_user_id")),
        )

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
        "ready": ready,
        "email_submitted": email_submitted,
        "password_submitted": password_submitted,
        "profile_submitted": profile_submitted,
        "captcha_required": captcha_required,
        "email_verification_required": email_verification_required,
        "email_verified": email_verified,
        "email_already_taken": email_already_taken,
        "apify_login_attempted": apify_login_attempted,
        "apify_logged_in": apify_logged_in,
        "apify_login_email_submitted": bool(login_result.get("email_submitted")),
        "apify_login_password_submitted": bool(login_result.get("password_submitted")),
        "apify_login_page_not_found": bool(login_result.get("page_not_found")),
        "apify_login_url": login_result.get("login_url"),
        "apify_full_name": profile_details.get("full_name"),
        "apify_username": profile_details.get("username"),
        "apify_user_id": token_result.get("apify_user_id"),
        "apify_token": token_result.get("apify_token"),
        "apify_token_collected": bool(token_result.get("apify_token")),
        "apify_token_collection_attempted": can_collect_token,
        "apify_registered_at": token_result.get("apify_registered_at"),
        "apify_settings_final_url": token_result.get("final_url"),
        **mail_result,
        "open_hint": open_result.get("hint"),
    }


def _profile_name_from_email(email: str) -> str:
    local = (email.split("@", 1)[0] or "").strip()
    cleaned = " ".join(part for part in local.replace(".", " ").replace("_", " ").split() if part)
    return cleaned or local or "Apify User"


def _complete_welcome_profile(page: CdpPage, email: str) -> bool:
    return bool(_complete_welcome_profile_details(page, email).get("submitted"))


def _complete_welcome_profile_details(page: CdpPage, email: str) -> dict[str, object]:
    display_name = _profile_name_from_email(email)
    result = page.evaluate(_fill_welcome_profile_script(display_name), timeout=8)
    details: dict[str, object]
    if isinstance(result, dict):
        details = result
    else:
        details = {"submitted": bool(result), "full_name": display_name, "username": None}
    submitted = bool(details.get("submitted"))
    if submitted:
        time.sleep(2)
    if not details.get("full_name"):
        details["full_name"] = display_name
    return details


def _wait_after_profile_continue(page: CdpPage, timeout: float = 10) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if not bool(page.evaluate(_welcome_profile_present_script(), timeout=3)):
                return
        except Exception as e:  # noqa: BLE001
            logger.debug("[Apify signup] wait profile continue skipped: {}", e)
        time.sleep(0.5)


def continue_apify_signup(
    browser_id: str,
    email: str,
    user: User,
    db: Session,
    email_password: str | None = None,
    mail_login_url: str | None = None,
    progress_callback: ProgressCallback | None = None,
    mail_already_logged_in: bool = False,
) -> dict[str, object]:
    logger.info("[Apify signup] continue flow browser_id={} email={}", browser_id, email)
    _emit_progress(progress_callback, "resume_browser", "打开现有 BitBrowser 窗口并恢复 Apify 流程")
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
    page_ws = _find_apify_page(http_base, user_id=user.id) or _create_page(http_base, SIGNUP_URL, user_id=user.id)
    profile_details: dict[str, object] = {
        "submitted": False,
        "full_name": _profile_name_from_email(email),
        "username": None,
    }
    email_verification_required = False
    email_already_taken = False
    apify_login_attempted = False
    apify_logged_in = False
    login_result: dict[str, object] = {}
    with CdpPage(page_ws, user_id=user.id) as page:
        page.call("Page.enable")
        page.call("Network.enable")
        page.call("Runtime.enable")
        _wait_page_ready(page)
        time.sleep(1)
        first_url = _current_url(page)
        profile_submitted = False
        email_already_taken = _has_email_already_taken_error(page)
        captcha_required = False if email_already_taken else _has_captcha(page)
        if captcha_required:
            logger.info(
                "[Apify signup] continue found human verification; waiting browser_id={} email={}",
                browser_id,
                email,
            )
            _emit_progress(progress_callback, "human_verification", "继续等待人工完成人机验证")
            post_human_state = _wait_for_human_verification_result(
                page,
                browser_id,
                email,
                progress_callback=progress_callback,
            )
            email_already_taken = bool(post_human_state.get("email_already_taken"))
            email_verification_required = bool(post_human_state.get("email_verification_required"))
            captcha_required = bool(post_human_state.get("captcha_required"))
        if email_already_taken and email_password and not captcha_required:
            logger.info("[Apify signup] continue email already taken; switching to login browser_id={} email={}", browser_id, email)
            _emit_progress(progress_callback, "login_existing_account", "邮箱已注册，切换到 Apify 登录")
            apify_login_attempted = True
            login_result = _login_existing_apify_account(page, email, str(email_password))
            apify_logged_in = bool(login_result.get("logged_in"))
            captcha_required = bool(login_result.get("captcha_required"))
            email_verification_required = bool(login_result.get("email_verification_required"))
            logger.info(
                "[Apify signup] continue login fallback finished browser_id={} email={} email_submitted={} password_submitted={} logged_in={} captcha_required={} email_verification_required={} final_url={}",
                browser_id,
                email,
                bool(login_result.get("email_submitted")),
                bool(login_result.get("password_submitted")),
                apify_logged_in,
                captcha_required,
                email_verification_required,
                str(login_result.get("final_url") or ""),
            )
        elif not email_already_taken and not captcha_required:
            logger.info("[Apify signup] continue checking welcome profile/email verification browser_id={} email={}", browser_id, email)
            _emit_progress(progress_callback, "resume_apify_state", "识别当前 Apify 页面状态")
            profile_details = _complete_welcome_profile_details(page, email)
            profile_submitted = bool(profile_details.get("submitted"))
            if profile_submitted:
                _wait_after_profile_continue(page)
            email_verification_required = _is_email_verification_page(page)
        final_url = _current_url(page)
        signed_in = _is_apify_logged_in(page)
        ready = (
            signed_in
            or apify_logged_in
            or profile_submitted
            or email_verification_required
        ) and not captcha_required

    mail_result: dict[str, object] = {}
    email_verified = False
    token_result: dict[str, object] = {}
    should_open_mail = email_verification_required and bool(email_password)
    if should_open_mail:
        logger.info("[Apify signup] continue opening Zoho verification mail browser_id={} email={}", browser_id, email)
        _emit_progress(progress_callback, "email_verification", "打开 Zoho 邮箱并点击 Apify 验证链接")
        mail_result = open_latest_apify_verification_link(
            browser_id,
            mail_login_url,
            email,
            str(email_password),
            user,
            db,
            ensure_login=not mail_already_logged_in,
        )
        email_verified = bool(mail_result.get("apify_verification_link_clicked"))
        logger.info(
            "[Apify signup] continue Zoho verification result browser_id={} email={} inbox_ready={} mail_opened={} link_clicked={}",
            browser_id,
            email,
            bool(mail_result.get("apify_mail_inbox_ready")),
            bool(mail_result.get("apify_mail_opened")),
            email_verified,
        )

    if email_verification_required:
        can_collect_token = not captcha_required and email_verified
    else:
        can_collect_token = not captcha_required and (apify_logged_in or ready)
    if can_collect_token:
        logger.info("[Apify signup] continue collecting Apify token browser_id={} email={}", browser_id, email)
        _emit_progress(progress_callback, "collect_token", "进入 Apify integrations 采集默认 API token")
        refreshed_ws = _find_apify_page(http_base, user_id=user.id) or _create_page(
            http_base, SETTINGS_INTEGRATIONS_URL, user_id=user.id
        )
        with CdpPage(refreshed_ws, user_id=user.id) as page:
            page.call("Page.enable")
            page.call("Network.enable")
            page.call("Runtime.enable")
            page.call("Page.bringToFront")
            if email_verified:
                _refresh_apify_after_email_verification(page)
                _wait_for_apify_email_verified(page)
            token_result = _collect_apify_token_from_settings(page)
            if token_result.get("apify_token"):
                ready = True
                final_url = str(token_result.get("final_url") or final_url)
        logger.info(
            "[Apify signup] continue token collection finished browser_id={} email={} token_collected={} user_id_present={}",
            browser_id,
            email,
            bool(token_result.get("apify_token")),
            bool(token_result.get("apify_user_id")),
        )

    return {
        "ok": True,
        "browser_id": browser_id,
        "signup_url": SIGNUP_URL,
        "first_url": first_url,
        "final_url": final_url,
        "logged_out": False,
        "session_cleared": False,
        "profile_cookies_cleared": False,
        "profile_cookie_config_cleared": False,
        "cleared_cookie_count": 0,
        "all_cookies_cleared": False,
        "still_logged_in": False,
        "ready": ready,
        "email_submitted": False,
        "password_submitted": ready,
        "profile_submitted": profile_submitted,
        "captcha_required": captcha_required,
        "email_verification_required": email_verification_required,
        "email_verified": email_verified,
        "email_already_taken": email_already_taken,
        "apify_login_attempted": apify_login_attempted,
        "apify_logged_in": apify_logged_in,
        "apify_login_email_submitted": bool(login_result.get("email_submitted")),
        "apify_login_password_submitted": bool(login_result.get("password_submitted")),
        "apify_login_page_not_found": bool(login_result.get("page_not_found")),
        "apify_login_url": login_result.get("login_url"),
        "apify_full_name": profile_details.get("full_name"),
        "apify_username": profile_details.get("username"),
        "apify_user_id": token_result.get("apify_user_id"),
        "apify_token": token_result.get("apify_token"),
        "apify_token_collected": bool(token_result.get("apify_token")),
        "apify_token_collection_attempted": can_collect_token,
        "apify_registered_at": token_result.get("apify_registered_at"),
        "apify_settings_final_url": token_result.get("final_url"),
        **mail_result,
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


def _create_page(http_base: str, url: str, *, user_id: int | None = None) -> str:
    path = f"/json/new?{quote(url, safe=':/?&=%')}"
    try:
        data = devtools_request(http_base, path, method="PUT", user_id=user_id)
    except Exception:
        data = devtools_request(http_base, path, method="GET", user_id=user_id)
    if not isinstance(data, dict):
        raise RuntimeError("创建 Apify 注册页失败：DevTools 返回格式异常")
    ws_url = data.get("webSocketDebuggerUrl")
    if not ws_url:
        raise RuntimeError("创建 Apify 注册页失败：DevTools 未返回页面 WebSocket")
    return str(ws_url)


def _find_apify_page(http_base: str, *, user_id: int | None = None) -> str | None:
    try:
        targets = devtools_request(http_base, "/json/list", user_id=user_id, timeout=10)
    except Exception as e:  # noqa: BLE001
        logger.debug("[Apify signup] find target skipped: {}", e)
        return None
    if not isinstance(targets, list):
        return None
    for target in targets:
        if not isinstance(target, dict):
            continue
        url = str(target.get("url") or "")
        ws_url = str(target.get("webSocketDebuggerUrl") or "")
        if "console.apify.com" in url and ws_url:
            return ws_url
    return None


def _close_apify_pages(http_base: str, *, user_id: int | None = None) -> int:
    closed = 0
    try:
        targets = devtools_request(http_base, "/json/list", user_id=user_id, timeout=10)
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
            devtools_request(
                http_base,
                f"/json/close/{quote(target_id, safe='')}",
                user_id=user_id,
                timeout=10,
            )
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


def _is_email_verification_page(page: CdpPage) -> bool:
    return bool(
        page.evaluate(
            """
(() => {
  const text = document.body ? document.body.innerText : '';
  return /Check your email|Confirm your email address|verification email/i.test(text);
})()
""",
            timeout=5,
        )
    )


def _has_email_already_taken_error(page: CdpPage) -> bool:
    return bool(
        page.evaluate(
            """
(() => {
  const text = document.body ? document.body.innerText : '';
  return /This email is already taken|email\\s+is\\s+already\\s+taken/i.test(text);
})()
""",
            timeout=5,
        )
    )


def _wait_for_apify_post_submit_state(page: CdpPage, timeout: float = 15) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if (
                _has_email_already_taken_error(page)
                or _has_captcha(page)
                or _is_email_verification_page(page)
                or bool(page.evaluate(_welcome_profile_present_script(), timeout=3))
                or _is_apify_logged_in(page)
            ):
                return
        except Exception as e:  # noqa: BLE001
            logger.debug("[Apify signup] wait post submit skipped: {}", e)
        time.sleep(0.5)


def _wait_for_human_verification_result(
    page: CdpPage,
    browser_id: str,
    email: str,
    timeout: float = HUMAN_VERIFICATION_TIMEOUT,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, bool]:
    deadline = time.monotonic() + timeout
    next_log_at = 0.0
    last_state: dict[str, bool] = {
        "captcha_required": True,
        "email_already_taken": False,
        "email_verification_required": False,
        "welcome_profile_present": False,
        "logged_in": False,
    }
    while time.monotonic() < deadline:
        try:
            email_already_taken = _has_email_already_taken_error(page)
            email_verification_required = _is_email_verification_page(page)
            welcome_profile_present = bool(page.evaluate(_welcome_profile_present_script(), timeout=3))
            logged_in = _is_apify_logged_in(page)
            captcha_required = _has_captcha(page)
            last_state = {
                "captcha_required": captcha_required,
                "email_already_taken": email_already_taken,
                "email_verification_required": email_verification_required,
                "welcome_profile_present": welcome_profile_present,
                "logged_in": logged_in,
            }
            if email_already_taken or email_verification_required or welcome_profile_present or logged_in:
                last_state["captcha_required"] = False
                return last_state
            now = time.monotonic()
            if now >= next_log_at:
                logger.info(
                    "[Apify signup] waiting human verification browser_id={} email={} captcha_required={} final_url={}",
                    browser_id,
                    email,
                    captcha_required,
                    _current_url(page),
                )
                _emit_progress(
                    progress_callback,
                    "human_verification",
                    "仍在等待人工验证完成，浏览器窗口不要关闭",
                )
                next_log_at = now + 15
        except Exception as e:  # noqa: BLE001
            logger.debug("[Apify signup] wait human verification skipped: {}", e)
        time.sleep(2)
    logger.info(
        "[Apify signup] human verification wait timed out browser_id={} email={} captcha_required={} email_already_taken={} email_verification_required={}",
        browser_id,
        email,
        last_state.get("captcha_required"),
        last_state.get("email_already_taken"),
        last_state.get("email_verification_required"),
    )
    return last_state


def _wait_for_apify_email_verified(page: CdpPage, timeout: float = 30) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            text = str(page.evaluate("document.body ? document.body.innerText : ''", timeout=5) or "")
            if "Email verified" in text or _is_apify_logged_in(page):
                return True
        except Exception as e:  # noqa: BLE001
            logger.debug("[Apify signup] wait email verified skipped: {}", e)
        time.sleep(1)
    return False


def _collect_apify_token_from_settings(page: CdpPage) -> dict[str, object]:
    page.call("Page.navigate", {"url": SETTINGS_INTEGRATIONS_URL}, timeout=8)
    _wait_page_ready(page)
    time.sleep(2)
    last_info: dict[str, object] = {}
    for _ in range(15):
        try:
            page.evaluate(_reveal_apify_token_script(), timeout=5)
            time.sleep(0.5)
            info = page.evaluate(_read_apify_settings_info_script(), timeout=8)
            if isinstance(info, dict):
                last_info = info
                if info.get("apify_token"):
                    break
        except Exception as e:  # noqa: BLE001
            logger.debug("[Apify signup] collect token skipped: {}", e)
        time.sleep(1)
    return {
        "apify_token": last_info.get("apify_token"),
        "apify_user_id": last_info.get("apify_user_id"),
        "apify_registered_at": datetime.utcnow(),
        "final_url": last_info.get("final_url") or _current_url(page),
    }


def _looks_logged_in_url(url: str) -> bool:
    lowered = url.lower()
    return (
        "console.apify.com" in lowered
        and "/sign-up" not in lowered
        and "/log-in" not in lowered
        and "/sign-in" not in lowered
        and "/login" not in lowered
        and "/page-not-found" not in lowered
    )


def _is_apify_page_not_found(page: CdpPage) -> bool:
    try:
        return bool(
            page.evaluate(
                """
(() => {
  const href = location.href;
  const text = document.body ? document.body.innerText : '';
  return href.includes('/page-not-found') || /Houston,\\s+we\\s+have\\s+a\\s+problem|page you.*wasn't found/i.test(text);
})()
""",
                timeout=5,
            )
        )
    except Exception as e:  # noqa: BLE001
        logger.debug("[Apify signup] page-not-found check skipped: {}", e)
        return False


def _has_apify_auth_form(page: CdpPage) -> bool:
    return bool(
        page.evaluate(
            """
(() => {
  const form = document.querySelector('[data-test="sign-in-form"],[data-test="sign-up-form"]');
  if (form) return true;
  const text = document.body ? document.body.innerText : '';
  return /Log\\s+in\\s+to\\s+Apify|Sign\\s+up\\s+for\\s+Apify|Welcome\\s+back/i.test(text);
})()
""",
            timeout=5,
        )
    )


def _is_apify_logged_in(page: CdpPage) -> bool:
    final_url = _current_url(page)
    if not _looks_logged_in_url(final_url):
        return False
    try:
        return not _has_apify_auth_form(page)
    except Exception as e:  # noqa: BLE001
        logger.debug("[Apify signup] logged-in DOM check skipped: {}", e)
        return False


def _login_existing_apify_account(page: CdpPage, email: str, password: str) -> dict[str, object]:
    login_href = _read_login_link_href(page)
    login_url = _open_apify_login_page(page, login_href)
    if not _is_login_page(page):
        final_url = _current_url(page)
        return {
            "email_submitted": False,
            "password_submitted": False,
            "logged_in": False,
            "email_verification_required": False,
            "captcha_required": _has_captcha(page),
            "final_url": final_url,
            "login_url": login_url,
            "page_not_found": _is_apify_page_not_found(page),
        }
    email_submitted = bool(page.evaluate(_fill_login_email_script(email), timeout=8))
    if email_submitted:
        _wait_for_password_step(page)
    password_submitted = bool(page.evaluate(_fill_login_password_script(password), timeout=8))
    if password_submitted:
        _wait_for_login_result(page)
    final_url = _current_url(page)
    email_verification_required = _is_email_verification_page(page)
    logged_in = bool(email_submitted and password_submitted and not email_verification_required and _is_apify_logged_in(page))
    return {
        "email_submitted": email_submitted,
        "password_submitted": password_submitted,
        "logged_in": logged_in,
        "email_verification_required": email_verification_required,
        "captcha_required": _has_captcha(page),
        "final_url": final_url,
        "login_url": login_url,
        "page_not_found": _is_apify_page_not_found(page),
    }


def _refresh_apify_after_email_verification(page: CdpPage) -> None:
    if not _is_email_verification_page(page):
        return
    page.call("Page.reload", {"ignoreCache": True}, timeout=8)
    _wait_page_ready(page)
    time.sleep(2)


def _open_apify_login_page(page: CdpPage, login_href: str | None) -> str | None:
    candidates: list[str] = []
    if login_href:
        candidates.append(urljoin("https://console.apify.com", login_href))
    candidates.extend([LOGIN_URL, SIGNIN_URL])
    seen: set[str] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        page.call("Page.navigate", {"url": candidate}, timeout=8)
        _wait_page_ready(page)
        time.sleep(1)
        if _is_login_page(page) and not _is_apify_page_not_found(page):
            return candidate
    return candidates[0] if candidates else None


def _read_login_link_href(page: CdpPage) -> str | None:
    try:
        href = page.evaluate(_login_link_href_script(), timeout=5)
    except Exception as e:  # noqa: BLE001
        logger.debug("[Apify signup] read login href skipped: {}", e)
        return None
    return str(href).strip() if href else None


def _is_login_page(page: CdpPage) -> bool:
    return bool(
        page.evaluate(
            """
(() => {
  const href = location.href;
  if (href.includes('/page-not-found')) return false;
  if (document.querySelector('[data-test="sign-in-form"]')) return true;
  const text = document.body ? document.body.innerText : '';
  return href.includes('/log-in') || href.includes('/sign-in') || /Log\\s+in\\s+to\\s+Apify|Welcome\\s+back/i.test(text);
})()
""",
            timeout=5,
        )
    )


def _wait_for_login_result(page: CdpPage, timeout: float = 20) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if _is_apify_logged_in(page) or _is_email_verification_page(page) or _has_captcha(page):
                return
        except Exception as e:  # noqa: BLE001
            logger.debug("[Apify signup] wait login result skipped: {}", e)
        time.sleep(0.5)


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
  const visible = (el) => {
    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return rect.width > 80 && rect.height > 60 && style.display !== 'none' && style.visibility !== 'hidden';
  };
  const frames = Array.from(document.querySelectorAll('iframe')).filter(visible).map((el) => {
    return `${el.src || ''} ${el.title || ''} ${el.name || ''}`;
  }).join(' ');
  const scripts = Array.from(document.querySelectorAll('script')).map((el) => el.src || '').join(' ');
  const text = `${bodyText} ${frames} ${scripts}`;
  return /hcaptcha|arkose|challenge|Select all squares|verify\\s+you\\s+are\\s+human|I'm not a robot/i.test(text);
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
  const buttons = Array.from(document.querySelectorAll('button,[role="button"]'))
    .filter(visible)
    .filter((el) => !/google|github/i.test(textOf(el)));
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
  const buttons = Array.from(document.querySelectorAll('button,[role="button"]'))
    .filter(visible)
    .filter((el) => !/google|github/i.test(textOf(el)));
  const button = buttons.find((el) => /^sign up$/i.test(textOf(el))) || buttons.find((el) => /sign up/i.test(textOf(el)));
  if (!button) return false;
  setTimeout(() => button.click(), 250);
  return true;
}})()
"""


def _fill_login_email_script(email: str) -> str:
    email_json = json.dumps(email)
    return f"""
(async () => {{
  const email = {email_json};
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
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
    input.dispatchEvent(new InputEvent('input', {{ bubbles: true, data: value, inputType: 'insertText' }}));
    input.dispatchEvent(new Event('change', {{ bubbles: true }}));
  }};
  const form = document.querySelector('[data-test="sign-in-form"]') || document;
  const input = Array.from(form.querySelectorAll('input'))
    .filter(visible)
    .find((el) => {{
      const hint = `${{el.type}} ${{el.name}} ${{el.placeholder}} ${{el.autocomplete}}`;
      return /email/i.test(hint) && !el.disabled && !el.readOnly;
    }});
  if (!input) return false;
  input.focus();
  setValue(input, email);
  input.blur();
  input.focus();
  for (let i = 0; i < 20; i += 1) {{
    const buttons = Array.from(form.querySelectorAll('button,[role="button"]'))
      .filter(visible)
      .filter((el) => !/google|github/i.test(textOf(el)));
    const button = buttons.find((el) => /^(continue|next|log in|sign in)$/i.test(textOf(el)))
    || buttons.find((el) => /continue|next|log in|sign in/i.test(textOf(el)));
    if (button && !button.disabled && button.getAttribute('aria-disabled') !== 'true') {{
      button.click();
      return true;
    }}
    await sleep(250);
  }}
  return false;
}})()
"""


def _fill_login_password_script(password: str) -> str:
    password_json = json.dumps(password)
    return f"""
(async () => {{
  const password = {password_json};
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
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
    input.dispatchEvent(new InputEvent('input', {{ bubbles: true, data: value, inputType: 'insertText' }}));
    input.dispatchEvent(new Event('change', {{ bubbles: true }}));
  }};
  const form = document.querySelector('[data-test="sign-in-form"]') || document;
  const input = Array.from(form.querySelectorAll('input[type="password"]'))
    .filter(visible)
    .find((el) => !el.disabled && !el.readOnly);
  if (!input) return false;
  input.focus();
  setValue(input, password);
  input.blur();
  input.focus();
  for (let i = 0; i < 20; i += 1) {{
    const buttons = Array.from(form.querySelectorAll('button,[role="button"]'))
      .filter(visible)
      .filter((el) => !/google|github/i.test(textOf(el)));
    const button = buttons.find((el) => /^(log in|sign in|continue)$/i.test(textOf(el)))
    || buttons.find((el) => /log in|sign in|continue/i.test(textOf(el)));
    if (button && !button.disabled && button.getAttribute('aria-disabled') !== 'true') {{
      button.click();
      return true;
    }}
    await sleep(250);
  }}
  return false;
}})()
"""


def _login_link_href_script() -> str:
    return """
(() => {
  const visible = (el) => {
    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
  };
  const textOf = (el) => (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
  const nodes = Array.from(document.querySelectorAll('a,button,[role="button"],[tabindex],div,span'))
    .filter(visible)
    .filter((el) => /^log\\s*in$/i.test(textOf(el)) || /already\\s+have\\s+an\\s+account.*log\\s*in/i.test(textOf(el)));
  const target = nodes.find((el) => !/google|github/i.test(textOf(el)));
  const clickable = target ? (target.closest('a,button,[role="button"],[tabindex]') || target) : null;
  if (!clickable) return null;
  const href = clickable.getAttribute && clickable.getAttribute('href');
  if (href) return href;
  const anchor = clickable.closest && clickable.closest('a[href]');
  return anchor ? anchor.getAttribute('href') : null;
})()
"""


def _login_link_point_script() -> str:
    return """
(() => {
  const visible = (el) => {
    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
  };
  const textOf = (el) => (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
  const clickable = (el) => el.closest('a,button,[role="button"],[tabindex]') || el;
  const nodes = Array.from(document.querySelectorAll('a,button,[role="button"],[tabindex],div,span'))
    .filter(visible)
    .filter((el) => /^log\\s*in$/i.test(textOf(el)) || /already\\s+have\\s+an\\s+account.*log\\s*in/i.test(textOf(el)));
  const target = nodes.find((el) => !/google|github/i.test(textOf(el)));
  const el = target ? clickable(target) : null;
  if (!el) return null;
  const rect = el.getBoundingClientRect();
  return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
})()
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


def _welcome_profile_present_script() -> str:
    return """
(() => /Welcome\\s+to\\s+Apify/i.test(document.body?.innerText || '')
  && /Your\\s+full\\s+name/i.test(document.body?.innerText || ''))()
"""


def _reveal_apify_token_script() -> str:
    return """
(() => {
  const visible = (el) => {
    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
  };
  const textOf = (el) => (el.innerText || el.textContent || el.value || '').replace(/\\s+/g, ' ').trim();
  const inputs = Array.from(document.querySelectorAll('input,textarea')).filter(visible);
  const masked = inputs.find((el) => /^\\*{8,}$/.test(el.value || '') || el.type === 'password');
  if (!masked) return false;
  let cur = masked.parentElement;
  for (let i = 0; cur && i < 5; i += 1, cur = cur.parentElement) {
    const buttons = Array.from(cur.querySelectorAll('button,[role="button"]')).filter(visible)
      .filter((el) => !/Create a new token|Delete|新規|削除/i.test(textOf(el)));
    if (buttons.length) {
      buttons[0].click();
      return true;
    }
  }
  return false;
})()
"""


def _read_apify_settings_info_script() -> str:
    return """
(() => {
  const text = document.body ? document.body.innerText : '';
  const values = Array.from(document.querySelectorAll('input,textarea'))
    .map((el) => el.value || '')
    .filter(Boolean);
  const joined = `${text}\\n${values.join('\\n')}`;
  const tokenMatch = joined.match(/apify_api_[A-Za-z0-9_-]+/);
  const userIdMatch = joined.match(/Apify\\s+user\\s+ID\\s*:?\\s*([A-Za-z0-9_-]+)/i);
  return {
    apify_token: tokenMatch ? tokenMatch[0] : null,
    apify_user_id: userIdMatch ? userIdMatch[1] : null,
    final_url: location.href,
  };
})()
"""


def _fill_welcome_profile_script(display_name: str) -> str:
    display_name_json = json.dumps(display_name)
    return f"""
(() => {{
  const displayName = {display_name_json};
  const visible = (el) => {{
    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
  }};
  const textOf = (el) => (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
  const bodyText = textOf(document.body);
  if (!/Welcome\\s+to\\s+Apify/i.test(bodyText) || !/Your\\s+full\\s+name/i.test(bodyText)) return false;
  const setValue = (input, value) => {{
    const proto = Object.getPrototypeOf(input);
    const desc = Object.getOwnPropertyDescriptor(proto, 'value');
    if (desc && desc.set) desc.set.call(input, value);
    else input.value = value;
    input.dispatchEvent(new Event('input', {{ bubbles: true }}));
    input.dispatchEvent(new Event('change', {{ bubbles: true }}));
    input.dispatchEvent(new KeyboardEvent('keyup', {{ bubbles: true }}));
  }};
  const inputs = Array.from(document.querySelectorAll('input'))
    .filter(visible)
    .filter((el) => !el.disabled && !el.readOnly && (el.type || 'text') !== 'hidden');
  const fullNameInput = inputs[0];
  if (!fullNameInput) return false;
  fullNameInput.focus();
  setValue(fullNameInput, displayName);
  const usernameInput = inputs.find((el) => /username/i.test(`${{el.id}} ${{el.name}} ${{el.placeholder}}`));
  const username = usernameInput ? usernameInput.value : '';
  const buttons = Array.from(document.querySelectorAll('button,[role="button"]')).filter(visible);
  const button = buttons.find((el) => /^continue$/i.test(textOf(el))) || buttons.find((el) => /continue/i.test(textOf(el)));
  if (!button) return false;
  setTimeout(() => button.click(), 700);
  return {{ submitted: true, full_name: displayName, username }};
}})()
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
