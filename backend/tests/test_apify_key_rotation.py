"""Apify Key 自动轮转逻辑单元测试（不依赖外部服务）。

运行：python -m unittest tests.test_apify_key_rotation
"""
from __future__ import annotations

import importlib
import pkgutil
import unittest
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models as _models_pkg
from app.db.base import Base
from app.models.apify_key import ApifyKey
from app.services.apify_key_rotation import apify_key_rotation


def _register_all_models() -> None:
    """导入 app.models 下所有模块，确保建表时外键目标表都已注册。"""
    for mod in pkgutil.iter_modules(_models_pkg.__path__):
        importlib.import_module(f"{_models_pkg.__name__}.{mod.name}")


class ClassifyErrorTests(unittest.TestCase):
    def test_exhausted(self):
        for msg in (
            "Monthly usage hard limit exceeded",
            "Actor failed: usage limit reached",
            "402 Payment Required",
            "You are on the free plan and out of credit",
        ):
            self.assertEqual(apify_key_rotation.classify_error(msg), "exhausted", msg)

    def test_auth(self):
        for msg in (
            "401 Unauthorized",
            "Invalid token provided",
            "User was not found or token is not valid",
        ):
            self.assertEqual(apify_key_rotation.classify_error(msg), "auth", msg)

    def test_memory_is_not_key_error(self):
        # 内存超限是运行配置问题，不应触发轮转
        self.assertEqual(
            apify_key_rotation.classify_error("Actor exceeded the memory limit of 1024 MB"),
            "other",
        )

    def test_other(self):
        for msg in (
            "Apify 调用超时或失败: read timeout",
            "Invalid input: usernames is required",
            "",
        ):
            self.assertEqual(apify_key_rotation.classify_error(msg), "other", msg)


class CandidateOrderingTests(unittest.TestCase):
    def setUp(self):
        _register_all_models()
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def tearDown(self):
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def _add(self, db, label, token, is_default=False, exhausted=False):
        row = ApifyKey(
            label=label,
            token=token,
            is_default=is_default,
            exhausted_at=datetime.utcnow() if exhausted else None,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row

    def test_order_prefers_available_then_default(self):
        db = self.Session()
        try:
            self._add(db, "exhausted-default", "t1", is_default=True, exhausted=True)
            self._add(db, "available-normal", "t2")
            self._add(db, "available-default", "t3", is_default=False)
            ordered = apify_key_rotation.get_candidate_keys(db)
            labels = [k.label for k in ordered]
            # 可用的排在已用尽的前面；已用尽的默认 Key 兜底排最后
            self.assertEqual(labels[-1], "exhausted-default")
            self.assertTrue(labels.index("available-normal") < labels.index("exhausted-default"))
        finally:
            db.close()

    def test_mark_exhausted_sets_timestamp(self):
        db = self.Session()
        try:
            row = self._add(db, "k", "tok")
            self.assertIsNone(row.exhausted_at)
            apify_key_rotation.mark_exhausted(db, row.id, reason="limit exceeded")
            db.refresh(row)
            self.assertIsNotNone(row.exhausted_at)
            self.assertIn("limit exceeded", row.remark or "")
            # 标记后不再进入「可用优先」段（被排到后面）
            ordered = apify_key_rotation.get_candidate_keys(db)
            self.assertTrue(ordered[0].exhausted_at is not None)  # 只有这一个 Key
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
