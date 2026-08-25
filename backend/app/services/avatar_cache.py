"""头像本地化：把抓到的远端头像下载到服务器，前端直接读本机地址。

IG / FB 的 CDN 在国内访问不稳定（要开代理才看得到图），所以抓取时由后端把图片
下载到 ``settings.avatar_cache_dir``，库里只存 ``/api/v1/influencers/avatars/xxx.jpg``
这种本机地址；下载失败则保留原始远端地址，不影响入库。
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Optional

import httpx
from loguru import logger

from app.core.config import settings

#: 对外访问路径前缀（无需登录，供 <img> 直接加载；文件名是 URL 的 sha1，不可枚举）
AVATAR_URL_PREFIX = "/api/v1/influencers/avatars/"

ALLOWED_SUFFIX = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
_MAX_BYTES = 8 * 1024 * 1024
_TIMEOUT_SEC = 20.0

_CONTENT_TYPE_SUFFIX = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/bmp": ".bmp",
}


def avatar_root() -> Path:
    root = Path(settings.avatar_cache_dir)
    root.mkdir(parents=True, exist_ok=True)
    return root


def is_local_avatar(url: Optional[str]) -> bool:
    return bool(url) and str(url).startswith(AVATAR_URL_PREFIX)


def avatar_path(filename: str) -> Optional[Path]:
    """把对外文件名映射到磁盘路径，非法文件名返回 None。"""
    name = Path(filename).name
    if name != filename or Path(name).suffix.lower() not in ALLOWED_SUFFIX:
        return None
    return avatar_root() / name


def _suffix_for(url: str, content_type: str) -> str:
    suffix = Path(url.split("?", 1)[0]).suffix.lower()
    if suffix in ALLOWED_SUFFIX:
        return suffix
    return _CONTENT_TYPE_SUFFIX.get(content_type.split(";", 1)[0].strip().lower(), ".jpg")


def localize_avatar(url: Optional[str]) -> Optional[str]:
    """下载远端头像并返回本机地址；已是本机地址、空值或下载失败时返回原值。"""
    raw = (url or "").strip()
    if not raw or is_local_avatar(raw) or not raw.startswith(("http://", "https://")):
        return url
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()
    root = avatar_root()
    for suffix in ALLOWED_SUFFIX:
        cached = root / f"{digest}{suffix}"
        if cached.is_file():
            return f"{AVATAR_URL_PREFIX}{cached.name}"
    try:
        with httpx.Client(timeout=_TIMEOUT_SEC, follow_redirects=True) as client:
            resp = client.get(raw)
            resp.raise_for_status()
            content = resp.content
            content_type = resp.headers.get("content-type", "")
    except Exception as e:  # noqa: BLE001
        logger.warning("[avatar] 下载头像失败，保留远端地址：{} {}", raw, e)
        return url
    if not content or len(content) > _MAX_BYTES:
        logger.warning("[avatar] 头像为空或超过 {} 字节，保留远端地址：{}", _MAX_BYTES, raw)
        return url
    dest = root / f"{digest}{_suffix_for(raw, content_type)}"
    dest.write_bytes(content)
    return f"{AVATAR_URL_PREFIX}{dest.name}"


def localize_form_avatar(form: dict) -> dict:
    """就地把表单里的 ``avatar_url`` 换成本机地址（抓取结果 / 入库前调用）。"""
    if isinstance(form.get("avatar_url"), str):
        form["avatar_url"] = localize_avatar(form["avatar_url"])
    return form
