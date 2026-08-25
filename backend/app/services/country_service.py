"""国家字典：内置常用国家种子数据 + 存量达人国家文本回填到关联。"""
from __future__ import annotations

from loguru import logger
from sqlalchemy.orm import Session

from app.models.country import Country
from app.models.influencer import Influencer

#: (中文名, 英文名, 代码, 排序)，日本排最前（当前主战场）
COUNTRY_SEEDS: list[tuple[str, str, str, int]] = [
    ("日本", "Japan", "JP", 0),
    ("美国", "United States", "US", 10),
    ("中国", "China", "CN", 20),
    ("中国台湾", "Taiwan", "TW", 30),
    ("中国香港", "Hong Kong", "HK", 40),
    ("韩国", "South Korea", "KR", 50),
    ("新加坡", "Singapore", "SG", 60),
    ("马来西亚", "Malaysia", "MY", 70),
    ("泰国", "Thailand", "TH", 80),
    ("越南", "Vietnam", "VN", 90),
    ("印度尼西亚", "Indonesia", "ID", 100),
    ("菲律宾", "Philippines", "PH", 110),
    ("英国", "United Kingdom", "GB", 120),
    ("法国", "France", "FR", 130),
    ("德国", "Germany", "DE", 140),
    ("意大利", "Italy", "IT", 150),
    ("西班牙", "Spain", "ES", 160),
    ("加拿大", "Canada", "CA", 170),
    ("澳大利亚", "Australia", "AU", 180),
    ("阿联酋", "United Arab Emirates", "AE", 190),
]


def seed_countries(db: Session) -> int:
    """按代码幂等写入内置国家；已存在的不动，返回新建条数。"""
    existing = {
        (row.code or "").strip().upper()
        for row in db.query(Country).all()
        if (row.code or "").strip()
    }
    created = 0
    for name_zh, name_en, code, sort_order in COUNTRY_SEEDS:
        if code in existing:
            continue
        db.add(
            Country(
                name_zh=name_zh, name_en=name_en, code=code, sort_order=sort_order
            )
        )
        created += 1
    if created:
        db.commit()
        logger.info("[countries] seeded {} builtin countries", created)
    return created


def backfill_influencer_country(db: Session) -> int:
    """把存量达人的 ``country`` 自由文本（如 JP / 日本 / Japan）对齐到国家关联。"""
    countries = db.query(Country).all()
    if not countries:
        return 0
    index: dict[str, int] = {}
    for c in countries:
        for key in ((c.code or ""), (c.name_zh or ""), (c.name_en or "")):
            key = key.strip().lower()
            if key:
                index.setdefault(key, c.id)
    rows = (
        db.query(Influencer)
        .filter(Influencer.country_id.is_(None), Influencer.country.isnot(None))
        .all()
    )
    patched = 0
    for inf in rows:
        cid = index.get((inf.country or "").strip().lower())
        if cid is None:
            continue
        inf.country_id = cid
        patched += 1
    if patched:
        db.commit()
        logger.info("[countries] backfilled country_id for {} influencers", patched)
    return patched
