"""安全相关：密码哈希、JWT、敏感字段对称加密。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from cryptography.fernet import Fernet, InvalidToken
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

# ----- 密码哈希 -----
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _truncate_for_bcrypt(password: str) -> str:
    """bcrypt 仅取前 72 字节，超出会在新版 bcrypt 中直接抛错。
    这里按字节截断（不是字符），避免 utf-8 多字节字符被切坏。
    """
    encoded = password.encode("utf-8")
    if len(encoded) <= 72:
        return password
    truncated = encoded[:72]
    while True:
        try:
            return truncated.decode("utf-8")
        except UnicodeDecodeError:
            truncated = truncated[:-1]


def hash_password(password: str) -> str:
    return pwd_context.hash(_truncate_for_bcrypt(password))


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(_truncate_for_bcrypt(plain), hashed)


# ----- JWT -----
ALGORITHM = "HS256"


def _create_token(subject: str | int, expires_delta: timedelta, token_type: str) -> str:
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "iat": int(now.timestamp()),
        "exp": int((now + expires_delta).timestamp()),
        "type": token_type,
    }
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def create_access_token(subject: str | int) -> str:
    return _create_token(
        subject,
        timedelta(minutes=settings.access_token_expire_minutes),
        "access",
    )


def create_refresh_token(subject: str | int) -> str:
    return _create_token(
        subject,
        timedelta(days=settings.refresh_token_expire_days),
        "refresh",
    )


def decode_token(token: str) -> Optional[dict[str, Any]]:
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    except JWTError:
        return None


# ----- 敏感字段对称加密（API Key 等） -----
def _get_fernet() -> Optional[Fernet]:
    key = settings.fernet_key
    if not key:
        return None
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except Exception:
        return None


def encrypt_secret(plain: Optional[str]) -> Optional[str]:
    if plain is None or plain == "":
        return plain
    f = _get_fernet()
    if f is None:
        # 未配置 fernet_key 时退化为明文存储；生产环境务必配置
        return plain
    return f.encrypt(plain.encode()).decode()


def decrypt_secret(cipher: Optional[str]) -> Optional[str]:
    if cipher is None or cipher == "":
        return cipher
    f = _get_fernet()
    if f is None:
        return cipher
    try:
        return f.decrypt(cipher.encode()).decode()
    except (InvalidToken, ValueError):
        return cipher
