"""批量私信任务：成功/失败每条都落库，任务计数正确。"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.db.init_db  # noqa: F401  注册全部模型
from app.api.v1 import dm as dm_api
from app.db.base import Base
from app.models.dm import DmContent, DmOutreachJob, DmOutreachLog
from app.models.influencer import Influencer
from app.models.user import User, UserRole


def _session_factory():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def test_job_records_success_and_failure(monkeypatch):
    factory = _session_factory()
    monkeypatch.setattr(dm_api, "SessionLocal", factory)
    db = factory()
    user = User(username="alice", password_hash="x", role=UserRole.admin)
    db.add(user)
    db.flush()
    content = DmContent(owner_id=user.id, title="合作邀请", content="hello", images=[])
    inf_a = Influencer(owner_id=user.id, display_name="A", fb_page_url="https://facebook.com/a")
    inf_b = Influencer(owner_id=user.id, display_name="B", fb_page_url="https://facebook.com/b")
    db.add_all([content, inf_a, inf_b])
    db.flush()
    job = DmOutreachJob(
        owner_id=user.id,
        platform="facebook",
        browser_id="win-1",
        content_id=content.id,
        content_title=content.title,
        targets=[
            {"influencer_id": inf_a.id, "url": inf_a.fb_page_url, "display_name": "A"},
            {"influencer_id": inf_b.id, "url": inf_b.fb_page_url, "display_name": "B"},
        ],
        interval_min=0,
        interval_max=0,
        total=2,
        status="pending",
    )
    db.add(job)
    db.commit()
    job_id = job.id

    def fake_send(browser_id, url, user, db, **kw):
        if url.endswith("/a"):
            return {"text_sent": True, "images_sent": 0}
        raise RuntimeError("未找到「发消息」按钮")

    monkeypatch.setattr(dm_api, "open_profile_and_message", fake_send)
    dm_api._run_dm_outreach_job_bg(job_id)

    db.expire_all()
    job = db.get(DmOutreachJob, job_id)
    assert job.status == "done"
    assert (job.sent, job.failed) == (1, 1)
    logs = db.query(DmOutreachLog).filter(DmOutreachLog.job_id == job_id).order_by(DmOutreachLog.id).all()
    assert len(logs) == 2
    ok, bad = logs
    assert ok.status == "success" and ok.text_sent and ok.influencer_id == inf_a.id
    assert bad.status == "failed" and "发消息" in bad.error and bad.influencer_id == inf_b.id
    assert {l.browser_id for l in logs} == {"win-1"}
    assert {l.content_text for l in logs} == {"hello"}
