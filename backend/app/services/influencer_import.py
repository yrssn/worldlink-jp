"""存量 Excel 导入：表头 → 字段映射与单元格解析。

表头（建联负责人 / KOL 编号 / 来源渠道 / KOL 主播名 / … / 备注 / 落地负责人）按下面的字段清单
落到 ``influencers``（人 / 建联维度）与 ``influencer_social_accounts``（账号维度）。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.models.country import Country
from app.models.influencer import InfluencerStatus


@dataclass(frozen=True)
class ImportField:
    key: str
    label: str
    #: 表头别名（小写、去空格后比对，含关键字即命中）
    aliases: tuple[str, ...]
    required: bool = False


#: 可映射字段清单；key 是 column_map 的键，target 见 apply_* 函数
IMPORT_FIELDS: tuple[ImportField, ...] = (
    ImportField("url", "账号链接（主页链接）", ("账号链接", "主页链接", "链接", "url", "主页"), required=True),
    ImportField("name", "KOL 主播名（昵称）", ("主播名", "kol名", "昵称", "达人名", "姓名", "name")),
    ImportField("title", "账号名", ("账号名", "账号名称", "页面名", "title")),
    ImportField("followers", "粉丝数量", ("粉丝", "followers")),
    ImportField("platform", "主平台", ("主平台", "平台", "platform")),
    ImportField("code", "KOL 编号", ("kol编号", "编号", "code")),
    ImportField("company", "KOL 公司名", ("公司", "company")),
    ImportField("gender", "性别", ("性别", "gender")),
    ImportField("country", "国家", ("国家", "country")),
    ImportField("city", "常居地", ("常居地", "城市", "city")),
    ImportField("address", "常居地址 / 收发地址", ("地址", "address")),
    ImportField("phone", "电话", ("电话", "手机", "phone", "tel")),
    ImportField("email", "邮箱", ("邮箱", "email", "mail")),
    ImportField("contact_owner", "建联负责人", ("建联负责人", "负责人")),
    ImportField("landing_owner", "落地负责人", ("落地负责人", "落地")),
    ImportField("source_channel", "来源渠道", ("来源渠道", "来源", "渠道")),
    ImportField("contact_started_at", "建联开始日期", ("建联开始", "开始日期")),
    ImportField("progress", "建联进度", ("建联进度", "进度")),
    ImportField("has_twitter", "是否推特", ("是否推特",)),
    ImportField("twitter_channel", "推特渠道", ("推特渠道",)),
    ImportField("group_name", "群名称", ("群名称", "群名")),
    ImportField("result", "建联结果（是否达成合作）", ("建联结果", "是否达成", "合作")),
    ImportField("planned_visit_at", "计划首次来访时间", ("来访", "首次来访")),
    ImportField("notes", "备注", ("备注", "notes", "remark")),
)

_FIELD_BY_KEY = {f.key: f for f in IMPORT_FIELDS}

#: 直接落 influencers 同名列的文本字段
INFLUENCER_TEXT_FIELDS: tuple[str, ...] = (
    "code",
    "company",
    "gender",
    "city",
    "address",
    "phone",
    "email",
    "contact_owner",
    "landing_owner",
    "source_channel",
    "progress",
    "twitter_channel",
    "group_name",
    "notes",
)
INFLUENCER_DATE_FIELDS: tuple[str, ...] = ("contact_started_at", "planned_visit_at")


def _norm_header(text: str) -> str:
    return re.sub(r"[\s\(\)（）:：/／、，,]+", "", (text or "").strip().lower())


def suggest_columns(headers: list[str]) -> dict[str, int]:
    """按表头名猜 ``{字段 key: 列下标}``；一个列只归到一个字段，别名越靠前优先级越高。

    先精确匹配（表头去空格后等于别名），再做包含匹配，避免「落地负责人」被「负责人」抢走。
    """
    normalized = [_norm_header(h) for h in headers]
    result: dict[str, int] = {}
    used: set[int] = set()
    for exact in (True, False):
        for field in IMPORT_FIELDS:
            if field.key in result:
                continue
            for idx, h in enumerate(normalized):
                if idx in used or not h:
                    continue
                hit = any(
                    (h == _norm_header(a)) if exact else (_norm_header(a) in h)
                    for a in field.aliases
                )
                if hit:
                    result[field.key] = idx
                    used.add(idx)
                    break
    return result


def parse_column_map(raw: Optional[str]) -> dict[str, int]:
    """把前端传来的 ``{"code": 0, "company": 4}`` JSON 转成字典，非法键/值丢弃。"""
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, int] = {}
    for k, v in data.items():
        if k in _FIELD_BY_KEY and isinstance(v, int) and v >= 0:
            out[k] = v
    return out


_DATE_PATTERNS = (
    "%Y/%m/%d %H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y/%m/%d %H:%M",
    "%Y-%m-%d %H:%M",
    "%Y/%m/%d",
    "%Y-%m-%d",
    "%Y.%m.%d",
    "%Y年%m月%d日",
    "%m/%d/%Y",
)


def parse_date(value: Optional[str]) -> Optional[datetime]:
    """解析表格里的日期（2026/5/26、2026-05-26、2026年5月26日、Excel 序列号…）。"""
    text = (value or "").strip()
    if not text:
        return None
    for pattern in _DATE_PATTERNS:
        try:
            return datetime.strptime(text, pattern)
        except ValueError:
            continue
    # openpyxl 未识别为日期时可能是 Excel 序列号（1900 起算）
    if re.fullmatch(r"\d{4,5}(\.\d+)?", text):
        try:
            return datetime(1899, 12, 30) + timedelta(days=float(text))
        except (ValueError, OverflowError):
            return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def parse_bool(value: Optional[str]) -> Optional[bool]:
    text = (value or "").strip().lower()
    if not text:
        return None
    if text in {"是", "有", "y", "yes", "true", "1", "已拉", "已加"}:
        return True
    if text in {"否", "无", "n", "no", "false", "0", "未拉", "未加"}:
        return False
    return text.startswith("是")


def parse_result_status(value: Optional[str]) -> Optional[InfluencerStatus]:
    """「建联结果（是否达成合作）」：以「是」开头 → 建联成功；以「否 / 放弃」开头 → 已放弃；其余不改。"""
    text = (value or "").strip()
    if not text:
        return None
    low = text.lower()
    if low.startswith(("是", "已合作", "已达成", "yes", "y")):
        return InfluencerStatus.signed
    if low.startswith(("放弃", "已放弃", "拒绝")):
        return InfluencerStatus.dropped
    if low.startswith(("否", "no", "n")):
        return InfluencerStatus.contacting
    return None


_GENDER_ALIASES = {
    "女": "女",
    "female": "女",
    "f": "女",
    "男": "男",
    "male": "男",
    "m": "男",
}


def parse_gender(value: Optional[str]) -> Optional[str]:
    text = (value or "").strip()
    if not text:
        return None
    return _GENDER_ALIASES.get(text.lower(), text[:16])


def country_lookup(db: Session) -> dict[str, Country]:
    """``{中文名/英文名/代码 小写: Country}``，导入时按「国家」列文本匹配。"""
    mapping: dict[str, Country] = {}
    for row in db.query(Country).all():
        for key in (row.name_zh, row.name_en, row.code):
            k = (key or "").strip().lower()
            if k:
                mapping.setdefault(k, row)
    return mapping


def match_country(value: Optional[str], lookup: dict[str, Country]) -> Optional[Country]:
    text = (value or "").strip().lower()
    if not text:
        return None
    if text in lookup:
        return lookup[text]
    for key, row in lookup.items():
        if key in text or text in key:
            return row
    return None
