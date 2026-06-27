"""邮箱账号管理 CRUD。"""
from __future__ import annotations

import json
import threading
from datetime import datetime

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from loguru import logger
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db
from app.core.security import decrypt_secret, encrypt_secret
from app.db.session import SessionLocal
from app.models.apify_key import ApifyKey
from app.models.apify_signup_task import ApifySignupTask
from app.models.email_account import EmailAccount
from app.models.user import User
from app.schemas.email_account import (
    ApifySignupTaskPage,
    ApifySignupTaskOut,
    EmailAccountCreate,
    EmailAccountOut,
    EmailAccountUpdate,
    EmailImportColumn,
    EmailImportField,
    EmailImportPreviewOut,
    EmailImportResultOut,
    VerificationMailLoginOut,
    ZohoMailLoginOut,
)
from app.services.apify_signup_automation import continue_apify_signup, start_apify_signup
from app.services.onamae_mail_automation import open_onamae_mail_login
from app.services.zoho_mail_automation import (
    normalize_zoho_login_url,
    open_zoho_mail_login,
    submit_zoho_verification_code,
    wait_current_zoho_inbox_ready,
)
from app.utils.spreadsheet import SpreadsheetParseError, parse_table

router = APIRouter(prefix="/email/accounts", tags=["email-accounts"])

# 导入功能支持的目标字段及其用于自动匹配表头的别名关键字（小写）。
_IMPORT_FIELDS: list[tuple[str, str, bool, tuple[str, ...]]] = [
    ("email", "注册邮箱", True, ("email", "邮箱", "注册邮箱", "mail", "account", "账号", "帐号")),
    ("email_password", "邮箱密码", False, ("password", "密码", "pwd", "邮箱密码", "pass")),
    ("provider", "邮箱服务商", False, ("provider", "服务商", "厂商", "类型")),
    ("mail_login_url", "邮箱登录地址", False, ("login_url", "登录地址", "登录链接", "邮箱地址", "url")),
    ("verification_email", "验证码邮箱", False, ("verification_email", "验证邮箱", "验证码邮箱", "备用邮箱")),
    ("verification_password", "验证邮箱密码", False, ("verification_password", "验证邮箱密码", "验证密码", "备用密码")),
    ("verification_login_url", "验证邮箱入口", False, ("verification_login_url", "验证邮箱入口", "验证邮箱地址", "webmail")),
    ("purpose", "用途", False, ("purpose", "用途", "目的")),
    ("status", "状态", False, ("status", "状态")),
    ("note", "备注", False, ("note", "备注", "remark", "说明")),
]

_MAX_IMPORT_BYTES = 5 * 1024 * 1024
_SECRET_IMPORT_FIELDS = {"email_password", "verification_password"}
_EMAIL_IMPORT_FIELDS = {"email", "verification_email"}


def _import_fields_schema() -> list[EmailImportField]:
    return [
        EmailImportField(key=key, label=label, required=required)
        for key, label, required, _ in _IMPORT_FIELDS
    ]


def _suggest_mapping(headers: list[str]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    used: set[int] = set()
    normalized = [h.strip().lower() for h in headers]
    for key, _, _, aliases in _IMPORT_FIELDS:
        for col_index, header in enumerate(normalized):
            if col_index in used or not header:
                continue
            if any(alias in header or header in alias for alias in aliases):
                mapping[key] = col_index
                used.add(col_index)
                break
    return mapping


async def _read_upload(file: UploadFile) -> bytes:
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="文件内容为空")
    if len(raw) > _MAX_IMPORT_BYTES:
        raise HTTPException(status_code=400, detail="导入文件不能超过 5MB")
    return raw


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text or None


def _clean_required(value: str) -> str:
    return value.strip()


def _clean_email(value: str | None) -> str | None:
    text = _clean_text(value)
    return text.lower() if text else None


def _create_apify_key_from_result(
    row: EmailAccount,
    result: dict[str, object],
    db: Session,
) -> dict[str, object]:
    token = result.get("apify_token")
    if not isinstance(token, str) or not token.strip():
        logger.info("[Apify signup] skip ApifyKey create: token missing email_account_id={}", row.id)
        return result
    has_default = db.query(ApifyKey).filter(ApifyKey.is_default.is_(True)).first() is not None
    logger.info(
        "[Apify signup] creating ApifyKey email_account_id={} email={} is_default={}",
        row.id,
        row.email,
        not has_default,
    )
    key = ApifyKey(
        label=f"{row.email} Apify",
        token=token.strip(),
        is_default=not has_default,
        remark="邮箱管理自动注册采集",
        email_account_id=row.id,
        apify_full_name=_clean_text(str(result.get("apify_full_name") or "")),
        apify_username=_clean_text(str(result.get("apify_username") or "")),
        apify_user_id=_clean_text(str(result.get("apify_user_id") or "")),
        apify_registered_at=result.get("apify_registered_at"),
    )
    db.add(key)
    db.commit()
    db.refresh(key)
    result["apify_key_created"] = True
    result["apify_key_id"] = key.id
    result["apify_key_is_default"] = key.is_default
    logger.info("[Apify signup] ApifyKey created email_account_id={} apify_key_id={}", row.id, key.id)
    return result


def _json_safe(value: object) -> object:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def _append_apify_task_log(
    task: ApifySignupTask,
    db: Session,
    node: str,
    message: str,
) -> None:
    task.current_node = node
    task.node_started_at = datetime.utcnow()
    entries: list[dict[str, object]] = []
    if task.logs:
        try:
            loaded = json.loads(task.logs)
            if isinstance(loaded, list):
                entries = [item for item in loaded if isinstance(item, dict)]
        except json.JSONDecodeError:
            entries = []
    entries.append(
        {
            "time": datetime.utcnow().isoformat(),
            "node": node,
            "message": message,
        }
    )
    task.logs = json.dumps(entries[-200:], ensure_ascii=False)
    db.add(task)
    db.commit()
    logger.info("[ApifySignupTask#{}] {} - {}", task.id, node, message)


def _run_apify_signup_task_bg(task_id: int) -> None:
    db = SessionLocal()
    try:
        task = db.query(ApifySignupTask).filter(ApifySignupTask.id == task_id).first()
        if not task:
            return
        task.status = "running"
        task.started_at = datetime.utcnow()
        task.error = None
        db.add(task)
        db.commit()
        _append_apify_task_log(task, db, "task_started", f"开始执行 Apify {task.action} 任务")

        row = db.query(EmailAccount).filter(EmailAccount.id == task.email_account_id).first()
        user = db.query(User).filter(User.id == task.owner_id).first()
        if not row or not user:
            task.status = "failed"
            task.error = "邮箱账号或用户不存在"
            task.finished_at = datetime.utcnow()
            db.commit()
            return
        if not row.browser_id:
            task.status = "failed"
            task.error = "请先为该邮箱选择指纹浏览器"
            task.finished_at = datetime.utcnow()
            db.commit()
            return
        email_password = decrypt_secret(row.email_password)
        if not email_password:
            task.status = "failed"
            task.error = "请先为该邮箱填写邮箱密码"
            task.finished_at = datetime.utcnow()
            db.commit()
            return
        linked = db.query(ApifyKey).filter(ApifyKey.email_account_id == row.id).first()
        if linked:
            task.status = "done"
            task.current_node = "already_linked"
            task.result = {"ok": True, "apify_key_created": True, "apify_key_id": linked.id}
            task.finished_at = datetime.utcnow()
            db.commit()
            return
        task.current_node = "mail_login"
        db.add(task)
        db.commit()
        _append_apify_task_log(task, db, "mail_login", "先登录注册邮箱，确保可以读取 Apify 验证邮件")
        mail_login_result = open_zoho_mail_login(
            row.browser_id,
            row.mail_login_url,
            row.email,
            email_password,
            user,
            db,
        )
        verification_required = bool(mail_login_result.get("mail_verification_required"))
        _append_apify_task_log(
            task,
            db,
            "mail_login",
            "Zoho 登录：邮箱输入={} 密码提交={} 需要邮箱验证码={}".format(
                "成功" if mail_login_result.get("mail_email_submitted") else "失败",
                "成功" if mail_login_result.get("mail_password_submitted") else "失败",
                "是" if verification_required else "否",
            ),
        )
        if verification_required:
            _append_apify_task_log(
                task, db, "mail_login", "Zoho 要求邮箱验证码，尝试从验证码邮箱读取并自动填写"
            )
        mail_login_result = _open_verification_mail_if_needed(mail_login_result, row, user, db)
        if verification_required:
            _append_apify_task_log(
                task,
                db,
                "mail_login",
                "验证码处理：验证码邮箱收件箱={} 读取验证码={} 提交验证码={}".format(
                    "就绪" if mail_login_result.get("verification_mail_inbox_ready") else "未就绪",
                    "成功" if mail_login_result.get("verification_mail_code_extracted") else "失败",
                    "成功" if mail_login_result.get("mail_verification_code_submitted") else "失败",
                ),
            )
        inbox_result = wait_current_zoho_inbox_ready(row.browser_id, user, db)
        mail_login_result = {**mail_login_result, **inbox_result}
        mail_ready = bool(mail_login_result.get("mail_inbox_ready"))
        zoho_verification_blocked = bool(mail_login_result.get("mail_verification_required")) and not bool(
            mail_login_result.get("mail_verification_code_submitted")
        )
        if not mail_ready or zoho_verification_blocked:
            task.status = "paused"
            task.current_node = "mail_login"
            task.error = _describe_mail_login_failure(mail_login_result, row)
            task.result = {"ok": False, "mail_login": _json_safe(mail_login_result)}
            task.finished_at = datetime.utcnow()
            db.add(task)
            db.commit()
            _append_apify_task_log(task, db, "mail_login", task.error)
            return
        _append_apify_task_log(task, db, "mail_login", "注册邮箱已登录，继续执行 Apify 注册任务")

        def progress(node: str, message: str) -> None:
            fresh_task = db.query(ApifySignupTask).filter(ApifySignupTask.id == task_id).first()
            if fresh_task:
                _append_apify_task_log(fresh_task, db, node, message)

        try:
            if task.action == "continue":
                result = continue_apify_signup(
                    row.browser_id,
                    row.email,
                    user,
                    db,
                    email_password,
                    row.mail_login_url,
                    progress,
                    mail_already_logged_in=True,
                )
            else:
                result = start_apify_signup(
                    row.browser_id,
                    row.email,
                    email_password,
                    user,
                    db,
                    row.mail_login_url,
                    progress,
                    mail_already_logged_in=True,
                )
            result = _create_apify_key_from_result(row, result, db)
        except Exception as e:  # noqa: BLE001
            fresh_task = db.query(ApifySignupTask).filter(ApifySignupTask.id == task_id).first()
            if fresh_task:
                fresh_task.status = "failed"
                fresh_task.error = str(e)[:4000]
                fresh_task.finished_at = datetime.utcnow()
                db.add(fresh_task)
                db.commit()
                _append_apify_task_log(fresh_task, db, "failed", str(e)[:1000])
            logger.exception("[ApifySignupTask#{}] failed", task_id)
            return

        fresh_task = db.query(ApifySignupTask).filter(ApifySignupTask.id == task_id).first()
        if not fresh_task:
            return
        fresh_task.result = _json_safe(result)
        fresh_task.finished_at = datetime.utcnow()
        if bool(result.get("captcha_required")):
            fresh_task.status = "paused"
            fresh_task.current_node = "human_verification"
            fresh_task.error = "人机验证超过 10 分钟未完成，任务已暂停；人工处理后点击继续注册"
            _append_apify_task_log(
                fresh_task,
                db,
                "human_verification",
                "人机验证等待超过 10 分钟，任务暂停",
            )
        elif bool(result.get("apify_key_created")):
            fresh_task.status = "done"
            _append_apify_task_log(fresh_task, db, "done", "已采集 token 并写入 Apify Key")
        elif bool(result.get("apify_token_collected")):
            fresh_task.status = "done"
            _append_apify_task_log(fresh_task, db, "done", "已采集 Apify token")
        elif bool(result.get("apify_token_collection_attempted")):
            fresh_task.status = "paused"
            fresh_task.current_node = "collect_token"
            fresh_task.error = "Apify token 采集失败，未写入 Apify Key；请查看 integrations 页面和任务日志"
            _append_apify_task_log(fresh_task, db, "collect_token", fresh_task.error)
        elif (
            bool(result.get("apify_login_attempted"))
            and not bool(result.get("apify_logged_in"))
            and not bool(result.get("email_verification_required"))
        ):
            fresh_task.status = "paused"
            if bool(result.get("apify_login_page_not_found")):
                fresh_task.error = "Apify 登录入口跳到了 page-not-found，任务已暂停"
            else:
                fresh_task.error = "Apify 登录未完成，请查看登录页是否已填写邮箱和密码"
            _append_apify_task_log(fresh_task, db, "login_existing_account", fresh_task.error)
        elif bool(result.get("email_verification_required")) and not bool(result.get("email_verified")):
            fresh_task.status = "paused"
            fresh_task.error = "Apify 需要邮箱验证，但验证流程未完成"
            _append_apify_task_log(fresh_task, db, "email_verification", fresh_task.error)
        elif bool(result.get("ready")) or bool(result.get("email_verified")):
            fresh_task.status = "paused"
            fresh_task.error = "Apify 已进入可继续状态，但未采集到 token，不能判定完成"
            _append_apify_task_log(fresh_task, db, fresh_task.current_node or "paused", fresh_task.error)
        else:
            fresh_task.status = "paused"
            fresh_task.error = "流程未完成，请查看浏览器窗口和任务日志"
            _append_apify_task_log(fresh_task, db, fresh_task.current_node or "paused", fresh_task.error)
        db.add(fresh_task)
        db.commit()
    finally:
        db.close()


def _create_apify_signup_task(row: EmailAccount, user: User, action: str, db: Session) -> ApifySignupTask:
    task = ApifySignupTask(
        owner_id=user.id,
        email_account_id=row.id,
        action=action,
        status="pending",
        current_node="pending",
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    threading.Thread(target=_run_apify_signup_task_bg, args=(task.id,), daemon=True).start()
    return task


def _to_out(row: EmailAccount) -> EmailAccountOut:
    return EmailAccountOut(
        id=row.id,
        owner_id=row.owner_id,
        email=row.email,
        email_password=decrypt_secret(row.email_password),
        provider=row.provider,
        mail_login_url=normalize_zoho_login_url(row.mail_login_url),
        verification_email=row.verification_email,
        verification_password=decrypt_secret(row.verification_password),
        verification_login_url=row.verification_login_url,
        purpose=row.purpose,
        status=row.status,
        browser_id=row.browser_id,
        last_verification_code=row.last_verification_code,
        last_verification_at=row.last_verification_at,
        note=row.note,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _describe_mail_login_failure(result: dict[str, object], row: EmailAccount) -> str:
    """根据 mail_login 各步骤结果给出可操作的失败原因。"""
    verification_required = bool(result.get("mail_verification_required"))
    code_submitted = bool(result.get("mail_verification_code_submitted"))
    if verification_required and not code_submitted:
        has_verification_config = bool(
            row.verification_email
            and row.verification_login_url
            and decrypt_secret(row.verification_password)
        )
        if not has_verification_config:
            return (
                "Zoho 登录需要邮箱验证码，但该账号未配置验证码邮箱/入口/密码；"
                "请补全验证码邮箱信息后重试，或在浏览器中手动输入验证码完成登录后点击“继续注册”"
            )
        if not bool(result.get("verification_mail_inbox_ready")):
            return (
                "Zoho 登录需要邮箱验证码，但验证码邮箱未能登录/打开收件箱；"
                "请检查验证码邮箱账号密码，或手动完成验证码后点击“继续注册”"
            )
        if not bool(result.get("verification_mail_code_extracted")):
            return (
                "Zoho 登录需要邮箱验证码，但未能在验证码邮箱中读取到验证码邮件；"
                "请稍后重试，或手动完成验证码后点击“继续注册”"
            )
        return "Zoho 登录验证码已读取但提交后仍未通过；请手动确认验证码后点击“继续注册”"
    if not bool(result.get("mail_email_submitted")):
        return "注册邮箱登录失败：未能在 Zoho 登录页填写邮箱；请检查登录入口/指纹浏览器后重试"
    if not bool(result.get("mail_password_submitted")):
        return "注册邮箱登录失败：未能提交 Zoho 密码；请检查邮箱密码是否正确后重试"
    return "注册邮箱未登录成功，请先处理邮箱登录/邮箱自身验证后继续注册"


def _open_verification_mail_if_needed(
    result: dict[str, object],
    row: EmailAccount,
    user: User,
    db: Session,
) -> dict[str, object]:
    if not bool(result.get("mail_verification_required")):
        return result
    if not row.verification_email or not row.verification_login_url:
        return result
    verification_password = decrypt_secret(row.verification_password)
    if not verification_password:
        return result
    verification_result = open_onamae_mail_login(
        row.browser_id or "",
        row.verification_login_url,
        row.verification_email,
        verification_password,
        user,
        db,
    )
    verification_code = verification_result.get("verification_code")
    submit_result: dict[str, object] = {}
    if isinstance(verification_code, str) and verification_code:
        row.last_verification_code = verification_code
        row.last_verification_at = datetime.utcnow()
        db.add(row)
        db.commit()
        submit_result = submit_zoho_verification_code(
            row.browser_id or "",
            verification_code,
            user,
            db,
        )
    return {**result, **verification_result, **submit_result}


@router.get("", response_model=list[EmailAccountOut])
def list_email_accounts(
    q: str | None = Query(None, description="按注册邮箱/验证邮箱搜索"),
    purpose: str | None = Query(None),
    status: str | None = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = db.query(EmailAccount).filter(EmailAccount.owner_id == user.id)
    keyword = _clean_text(q)
    if keyword:
        like = f"%{keyword}%"
        query = query.filter(
            EmailAccount.email.like(like)
            | EmailAccount.verification_email.like(like)
        )
    purpose_clean = _clean_text(purpose)
    if purpose_clean:
        query = query.filter(EmailAccount.purpose == purpose_clean)
    status_clean = _clean_text(status)
    if status_clean:
        query = query.filter(EmailAccount.status == status_clean)
    rows = query.order_by(EmailAccount.created_at.desc(), EmailAccount.id.desc()).all()
    return [_to_out(row) for row in rows]


@router.post("", response_model=EmailAccountOut)
def create_email_account(
    body: EmailAccountCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    email = _clean_email(body.email)
    if not email:
        raise HTTPException(status_code=400, detail="请填写注册邮箱")
    exists = (
        db.query(EmailAccount)
        .filter(EmailAccount.owner_id == user.id, EmailAccount.email == email)
        .first()
    )
    if exists:
        raise HTTPException(status_code=400, detail="该邮箱已存在")
    row = EmailAccount(
        owner_id=user.id,
        email=email,
        email_password=encrypt_secret(_clean_text(body.email_password)),
        provider=_clean_text(body.provider),
        mail_login_url=normalize_zoho_login_url(body.mail_login_url),
        verification_email=_clean_email(body.verification_email),
        verification_password=encrypt_secret(_clean_text(body.verification_password)),
        verification_login_url=_clean_text(body.verification_login_url),
        purpose=_clean_required(body.purpose),
        status=_clean_required(body.status),
        browser_id=_clean_text(body.browser_id),
        last_verification_code=_clean_text(body.last_verification_code),
        last_verification_at=body.last_verification_at,
        note=_clean_text(body.note),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _to_out(row)


@router.post("/import/preview", response_model=EmailImportPreviewOut)
async def preview_email_import(
    file: UploadFile = File(...),
    sample_size: int = Query(5, ge=1, le=20),
    user: User = Depends(get_current_user),
):
    """解析上传的 CSV/XLSX，返回识别到的表头、样例数据与可映射字段。"""
    raw = await _read_upload(file)
    try:
        headers, rows = parse_table(file.filename, raw)
    except SpreadsheetParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not headers:
        raise HTTPException(status_code=400, detail="未识别到表头，请检查文件内容")
    return EmailImportPreviewOut(
        columns=[EmailImportColumn(index=i, name=name) for i, name in enumerate(headers)],
        sample_rows=rows[:sample_size],
        total_rows=len(rows),
        fields=_import_fields_schema(),
        suggested_mapping=_suggest_mapping(headers),
    )


@router.post("/import", response_model=EmailImportResultOut)
async def import_email_accounts(
    file: UploadFile = File(...),
    mapping: str = Form(..., description="字段到列索引的 JSON，例如 {\"email\": 0}"),
    skip_duplicates: bool = Form(True),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """按表头映射导入邮箱账号。

    mapping 形如 ``{"email": 0, "email_password": 1}``，值为预览返回的列索引。
    """
    raw = await _read_upload(file)
    try:
        column_map = json.loads(mapping)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="字段映射格式错误")
    if not isinstance(column_map, dict):
        raise HTTPException(status_code=400, detail="字段映射格式错误")

    valid_keys = {key for key, _, _, _ in _IMPORT_FIELDS}
    normalized_map: dict[str, int] = {}
    for key, col in column_map.items():
        if key not in valid_keys or col is None or col == "":
            continue
        try:
            normalized_map[key] = int(col)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail=f"字段「{key}」的列索引无效")
    if "email" not in normalized_map:
        raise HTTPException(status_code=400, detail="请将「注册邮箱」字段映射到某一列")

    try:
        headers, rows = parse_table(file.filename, raw)
    except SpreadsheetParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not headers:
        raise HTTPException(status_code=400, detail="未识别到表头，请检查文件内容")

    width = len(headers)
    for key, col in normalized_map.items():
        if col < 0 or col >= width:
            raise HTTPException(status_code=400, detail=f"字段「{key}」映射的列超出范围")

    existing = {
        row[0]
        for row in db.query(EmailAccount.email)
        .filter(EmailAccount.owner_id == user.id)
        .all()
    }
    created = 0
    skipped = 0
    failed = 0
    errors: list[str] = []
    seen_in_file: set[str] = set()

    for offset, row in enumerate(rows):
        line_no = offset + 2  # 含表头，便于用户对照行号
        values: dict[str, str | None] = {}
        for key, col in normalized_map.items():
            cell = row[col] if col < len(row) else ""
            if key in _EMAIL_IMPORT_FIELDS:
                values[key] = _clean_email(cell)
            else:
                values[key] = _clean_text(cell)

        email = values.get("email")
        if not email:
            failed += 1
            errors.append(f"第 {line_no} 行：缺少注册邮箱，已跳过")
            continue
        if email in seen_in_file:
            skipped += 1
            errors.append(f"第 {line_no} 行：文件内重复邮箱 {email}，已跳过")
            continue
        if email in existing:
            if skip_duplicates:
                skipped += 1
                errors.append(f"第 {line_no} 行：邮箱 {email} 已存在，已跳过")
                continue
            failed += 1
            errors.append(f"第 {line_no} 行：邮箱 {email} 已存在")
            continue

        try:
            account = EmailAccount(
                owner_id=user.id,
                email=email,
                email_password=encrypt_secret(values.get("email_password")),
                provider=values.get("provider"),
                mail_login_url=normalize_zoho_login_url(values.get("mail_login_url")),
                verification_email=values.get("verification_email"),
                verification_password=encrypt_secret(values.get("verification_password")),
                verification_login_url=values.get("verification_login_url"),
                purpose=values.get("purpose") or "registration",
                status=values.get("status") or "available",
                note=values.get("note"),
            )
            db.add(account)
            db.flush()
        except Exception as exc:  # 单行失败不影响整体导入
            db.rollback()
            failed += 1
            errors.append(f"第 {line_no} 行：写入失败 {exc}")
            continue
        existing.add(email)
        seen_in_file.add(email)
        created += 1

    db.commit()
    return EmailImportResultOut(
        total=len(rows),
        created=created,
        skipped=skipped,
        failed=failed,
        errors=errors[:100],
    )


@router.post("/{account_id}/apify-signup/start", response_model=ApifySignupTaskOut)
def start_email_apify_signup(
    account_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = (
        db.query(EmailAccount)
        .filter(EmailAccount.id == account_id, EmailAccount.owner_id == user.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="邮箱账号不存在")
    if not row.browser_id:
        raise HTTPException(status_code=400, detail="请先为该邮箱选择指纹浏览器")
    email_password = decrypt_secret(row.email_password)
    if not email_password:
        raise HTTPException(status_code=400, detail="请先为该邮箱填写邮箱密码")
    linked = db.query(ApifyKey).filter(ApifyKey.email_account_id == row.id).first()
    if linked:
        raise HTTPException(status_code=400, detail="该邮箱已关联 Apify Key，无需重复注册")
    task = _create_apify_signup_task(row, user, "start", db)
    return task


@router.post("/{account_id}/apify-signup/continue", response_model=ApifySignupTaskOut)
def continue_email_apify_signup(
    account_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = (
        db.query(EmailAccount)
        .filter(EmailAccount.id == account_id, EmailAccount.owner_id == user.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="邮箱账号不存在")
    if not row.browser_id:
        raise HTTPException(status_code=400, detail="请先为该邮箱选择指纹浏览器")
    email_password = decrypt_secret(row.email_password)
    if not email_password:
        raise HTTPException(status_code=400, detail="请先为该邮箱填写邮箱密码")
    linked = db.query(ApifyKey).filter(ApifyKey.email_account_id == row.id).first()
    if linked:
        raise HTTPException(status_code=400, detail="该邮箱已关联 Apify Key，无需重复注册")
    task = _create_apify_signup_task(row, user, "continue", db)
    return task


@router.get("/{account_id}/apify-signup/tasks/latest", response_model=ApifySignupTaskOut | None)
def get_latest_apify_signup_task(
    account_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = (
        db.query(EmailAccount)
        .filter(EmailAccount.id == account_id, EmailAccount.owner_id == user.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="邮箱账号不存在")
    return (
        db.query(ApifySignupTask)
        .filter(ApifySignupTask.email_account_id == row.id, ApifySignupTask.owner_id == user.id)
        .order_by(ApifySignupTask.id.desc())
        .first()
    )


@router.get("/apify-signup/tasks", response_model=ApifySignupTaskPage)
def list_apify_signup_tasks(
    account_id: int | None = None,
    status: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(5, ge=1, le=50),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = db.query(ApifySignupTask).filter(ApifySignupTask.owner_id == user.id)
    if account_id:
        query = query.filter(ApifySignupTask.email_account_id == account_id)
    if status:
        query = query.filter(ApifySignupTask.status == status)
    total = query.count()
    items = (
        query.order_by(ApifySignupTask.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return ApifySignupTaskPage(total=total, page=page, page_size=page_size, items=items)


@router.get("/apify-signup/tasks/{task_id}", response_model=ApifySignupTaskOut)
def get_apify_signup_task(
    task_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    task = (
        db.query(ApifySignupTask)
        .filter(ApifySignupTask.id == task_id, ApifySignupTask.owner_id == user.id)
        .first()
    )
    if not task:
        raise HTTPException(status_code=404, detail="Apify 注册任务不存在")
    return task


@router.post("/{account_id}/mail-login/zoho", response_model=ZohoMailLoginOut)
def start_email_zoho_mail_login(
    account_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = (
        db.query(EmailAccount)
        .filter(EmailAccount.id == account_id, EmailAccount.owner_id == user.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="邮箱账号不存在")
    if not row.browser_id:
        raise HTTPException(status_code=400, detail="请先为该邮箱选择指纹浏览器")
    email_password = decrypt_secret(row.email_password)
    if not email_password:
        raise HTTPException(status_code=400, detail="请先为该邮箱填写邮箱密码")
    try:
        result = open_zoho_mail_login(
            row.browser_id,
            row.mail_login_url,
            row.email,
            email_password,
            user,
            db,
        )
        result = _open_verification_mail_if_needed(result, row, user, db)
        return {"ok": True, "browser_id": row.browser_id, **result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"连接 BitBrowser/CDP 失败: {e}") from e
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@router.post("/{account_id}/mail-login/verification", response_model=VerificationMailLoginOut)
def start_email_verification_mail_login(
    account_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = (
        db.query(EmailAccount)
        .filter(EmailAccount.id == account_id, EmailAccount.owner_id == user.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="邮箱账号不存在")
    if not row.browser_id:
        raise HTTPException(status_code=400, detail="请先为该邮箱选择指纹浏览器")
    if not row.verification_email:
        raise HTTPException(status_code=400, detail="请先填写验证码邮箱")
    if not row.verification_login_url:
        raise HTTPException(status_code=400, detail="请先填写验证码邮箱入口")
    verification_password = decrypt_secret(row.verification_password)
    if not verification_password:
        raise HTTPException(status_code=400, detail="请先填写验证码邮箱密码")
    try:
        result = open_onamae_mail_login(
            row.browser_id,
            row.verification_login_url,
            row.verification_email,
            verification_password,
            user,
            db,
        )
        verification_code = result.get("verification_code")
        if isinstance(verification_code, str) and verification_code:
            row.last_verification_code = verification_code
            row.last_verification_at = datetime.utcnow()
            db.add(row)
            db.commit()
        return {"ok": True, "browser_id": row.browser_id, **result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"连接 BitBrowser/CDP 失败: {e}") from e
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@router.put("/{account_id}", response_model=EmailAccountOut)
def update_email_account(
    account_id: int,
    body: EmailAccountUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = (
        db.query(EmailAccount)
        .filter(EmailAccount.id == account_id, EmailAccount.owner_id == user.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="邮箱账号不存在")
    data = body.model_dump(exclude_unset=True)
    if "email" in data:
        email = _clean_email(body.email)
        if not email:
            raise HTTPException(status_code=400, detail="请填写注册邮箱")
        duplicate = (
            db.query(EmailAccount)
            .filter(
                EmailAccount.owner_id == user.id,
                EmailAccount.email == email,
                EmailAccount.id != row.id,
            )
            .first()
        )
        if duplicate:
            raise HTTPException(status_code=400, detail="该邮箱已存在")
        row.email = email
    if "email_password" in data:
        row.email_password = encrypt_secret(_clean_text(body.email_password))
    if "provider" in data:
        row.provider = _clean_text(body.provider)
    if "mail_login_url" in data:
        row.mail_login_url = normalize_zoho_login_url(body.mail_login_url)
    if "verification_email" in data:
        row.verification_email = _clean_email(body.verification_email)
    if "verification_password" in data:
        row.verification_password = encrypt_secret(_clean_text(body.verification_password))
    if "verification_login_url" in data:
        row.verification_login_url = _clean_text(body.verification_login_url)
    if "purpose" in data and body.purpose is not None:
        row.purpose = _clean_required(body.purpose)
    if "status" in data and body.status is not None:
        row.status = _clean_required(body.status)
    if "browser_id" in data:
        row.browser_id = _clean_text(body.browser_id)
    if "last_verification_code" in data:
        row.last_verification_code = _clean_text(body.last_verification_code)
    if "last_verification_at" in data:
        row.last_verification_at = body.last_verification_at
    if "note" in data:
        row.note = _clean_text(body.note)
    db.commit()
    db.refresh(row)
    return _to_out(row)


@router.delete("/{account_id}")
def delete_email_account(
    account_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = (
        db.query(EmailAccount)
        .filter(EmailAccount.id == account_id, EmailAccount.owner_id == user.id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="邮箱账号不存在")
    db.delete(row)
    db.commit()
    return {"ok": True}
