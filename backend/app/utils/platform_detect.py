"""按链接正则识别所属平台。

批量导入达人链接时不用再手选平台：一行一个链接，按域名/路径特征判断平台，
并把结果对齐到「平台管理」里维护的平台代码（如 ig / fb / rednote / tk）。
"""
from __future__ import annotations

import re

#: 抓取任务当前支持自动抓资料的平台（对应 Apify actor）
SCRAPABLE_PLATFORMS: tuple[str, ...] = ("facebook", "instagram")

#: 可识别/可暂存的平台规范名（不在 SCRAPABLE_PLATFORMS 里的只能暂存，不能自动抓资料）
KNOWN_PLATFORMS: tuple[str, ...] = (
    "facebook",
    "instagram",
    "tiktok",
    "xiaohongshu",
    "youtube",
    "twitter",
    "line",
)


def _domain_pattern(*domains: str) -> re.Pattern[str]:
    """匹配「任意子域 + 目标域名」的正则，兼容不带协议、带 www/m 前缀、带查询串的写法。"""
    alt = "|".join(d.replace(".", r"\.") for d in domains)
    return re.compile(rf"(?<![\w.-])(?:[a-z0-9-]+\.)*(?:{alt})(?![a-z0-9-])", re.I)


#: 平台规范名 -> 链接正则（按顺序匹配，先命中先返回）
PLATFORM_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("instagram", _domain_pattern("instagram.com", "instagr.am")),
    ("facebook", _domain_pattern("facebook.com", "fb.com", "fb.watch", "fb.me")),
    ("tiktok", _domain_pattern("tiktok.com", "douyin.com")),
    ("xiaohongshu", _domain_pattern("xiaohongshu.com", "xhslink.com")),
    ("youtube", _domain_pattern("youtube.com", "youtu.be")),
    ("twitter", _domain_pattern("twitter.com", "x.com")),
    ("line", _domain_pattern("line.me")),
)

#: 平台规范名 -> 「平台管理」里常见的平台代码/名称别名（小写，按顺序优先匹配）
PLATFORM_CODE_ALIASES: dict[str, tuple[str, ...]] = {
    "instagram": ("ig", "instagram", "insta"),
    "facebook": ("fb", "facebook", "脸书"),
    "tiktok": ("tk", "tiktok", "tiktop", "douyin", "抖音"),
    "xiaohongshu": ("rednote", "xhs", "xiaohongshu", "小红书"),
    "youtube": ("yt", "youtube", "油管"),
    "twitter": ("x", "tw", "twitter"),
    "line": ("line",),
}


def detect_platform(url: str | None) -> str | None:
    """从链接识别平台规范名；识别不出返回 ``None``。

    纯用户名（不带域名，如 ``nasa``）识别不出平台，交由调用方决定默认值。
    """
    text = (url or "").strip()
    if not text:
        return None
    for name, pattern in PLATFORM_PATTERNS:
        if pattern.search(text):
            return name
    return None


def platform_code_candidates(platform: str) -> tuple[str, ...]:
    """平台规范名对应的平台代码别名，用于匹配「平台管理」里的记录。"""
    return PLATFORM_CODE_ALIASES.get(platform, (platform,))


def canonical_platform(*texts: str | None) -> str | None:
    """反查：把「平台管理」里的代码/名称（如 ig、小红书）对回平台规范名。"""
    for text in texts:
        key = (text or "").strip().lower()
        if not key:
            continue
        if key in KNOWN_PLATFORMS:
            return key
        for name, aliases in PLATFORM_CODE_ALIASES.items():
            if key in aliases:
                return name
    return None


def match_platform_code(platform: str, codes: dict[str, int]) -> int | None:
    """在 ``{平台代码小写: 平台id}`` 里找该平台对应的记录 id。"""
    for alias in platform_code_candidates(platform):
        if alias in codes:
            return codes[alias]
    return None
