"""达人列表的「私信结果 / 私信时间」筛选与最近一次私信标注。"""

from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.v1.influencer import _apply_outreach_filters, _mark_outreach_state
import app.db.init_db  # noqa: F401  导入后所有模型才注册到 Base.metadata
from app.db.base import Base
from app.models.dm import DmOutreachLog
from app.models.influencer import Influencer
from app.models.user import User


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def _seed(db):
    user = User(username="cindy", password_hash="x")
    db.add(user)
    db.flush()
    names = ["成功的", "失败的", "先失败后成功的", "没私信的"]
    infs = [Influencer(display_name=n, owner_id=user.id) for n in names]
    db.add_all(infs)
    db.flush()
    ok, bad, retried, _none = infs
    db.add_all(
        [
            DmOutreachLog(
                owner_id=user.id, influencer_id=ok.id, url="u1", status="success",
                created_at=datetime(2026, 1, 10, 9, 0, 0),
            ),
            DmOutreachLog(
                owner_id=user.id, influencer_id=bad.id, url="u2", status="failed",
                error="窗口没打开", created_at=datetime(2026, 1, 12, 9, 0, 0),
            ),
            DmOutreachLog(
                owner_id=user.id, influencer_id=retried.id, url="u3", status="failed",
                error="超时", created_at=datetime(2026, 1, 11, 9, 0, 0),
            ),
            DmOutreachLog(
                owner_id=user.id, influencer_id=retried.id, url="u3", status="success",
                created_at=datetime(2026, 1, 13, 9, 0, 0),
            ),
        ]
    )
    db.commit()
    return infs


def _names(db, **kw):
    q = _apply_outreach_filters(db.query(Influencer), **kw)
    return sorted(i.display_name for i in q.all())


def test_filter_by_outreach_status(db):
    _seed(db)
    assert _names(db, outreach_status="failed", outreach_start=None, outreach_end=None) == ["失败的"]
    assert _names(db, outreach_status="success", outreach_start=None, outreach_end=None) == [
        "先失败后成功的",
        "成功的",
    ]
    assert _names(db, outreach_status="none", outreach_start=None, outreach_end=None) == ["没私信的"]


def test_filter_by_outreach_time(db):
    _seed(db)
    # 时间口径同样是最后一条：先失败后成功的那条落在 1-13
    assert _names(db, outreach_status=None, outreach_start="2026-01-12", outreach_end="2026-01-12") == [
        "失败的"
    ]
    assert _names(db, outreach_status=None, outreach_start="2026-01-13", outreach_end=None) == [
        "先失败后成功的"
    ]
    assert _names(
        db, outreach_status="failed", outreach_start="2026-01-01", outreach_end="2026-01-11"
    ) == []


def test_mark_outreach_state_uses_latest_log(db):
    infs = _seed(db)
    _mark_outreach_state(db, infs)
    ok, bad, retried, none = infs
    assert (ok.has_outreach, ok.outreach_status, ok.outreach_error) == (True, "success", None)
    assert (bad.outreach_status, bad.outreach_error) == ("failed", "窗口没打开")
    assert bad.outreach_at == datetime(2026, 1, 12, 9, 0, 0)
    assert (retried.outreach_status, retried.outreach_error) == ("success", None)
    assert (none.has_outreach, none.outreach_status, none.outreach_at) == (False, None, None)
