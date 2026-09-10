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


def test_job_picks_random_content_per_target(monkeypatch):
    """多选内容时每条随机挑一条发，日志里记的是实际用的那条。"""
    factory = _session_factory()
    monkeypatch.setattr(dm_api, "SessionLocal", factory)
    db = factory()
    user = User(username="bob", password_hash="x", role=UserRole.admin)
    db.add(user)
    db.flush()
    c1 = DmContent(owner_id=user.id, title="文案一", content="hi one", images=[])
    c2 = DmContent(owner_id=user.id, title="文案二", content="hi two", images=[])
    db.add_all([c1, c2])
    db.flush()
    targets = [
        {"influencer_id": None, "url": f"https://facebook.com/{i}", "display_name": str(i)}
        for i in range(6)
    ]
    job = DmOutreachJob(
        owner_id=user.id,
        platform="facebook",
        browser_id="win-1",
        content_id=c1.id,
        content_title=f"{c1.title} 等 2 条（随机）",
        content_ids=[c1.id, c2.id],
        targets=targets,
        interval_min=0,
        interval_max=0,
        total=len(targets),
        status="pending",
    )
    db.add(job)
    db.commit()
    job_id = job.id

    sent_texts: list[str] = []

    def fake_send(browser_id, url, user, db, **kw):
        sent_texts.append(kw["message_text"])
        return {"text_sent": True, "images_sent": 0}

    monkeypatch.setattr(dm_api, "open_profile_and_message", fake_send)
    monkeypatch.setattr(dm_api.random, "choice", lambda seq: seq[len(sent_texts) % len(seq)])
    dm_api._run_dm_outreach_job_bg(job_id)

    db.expire_all()
    assert sent_texts == ["hi one", "hi two"] * 3
    logs = (
        db.query(DmOutreachLog)
        .filter(DmOutreachLog.job_id == job_id)
        .order_by(DmOutreachLog.id)
        .all()
    )
    assert [l.content_text for l in logs] == sent_texts
    assert [l.content_id for l in logs] == [c1.id, c2.id] * 3


def test_job_contents_falls_back_to_single_content_id():
    factory = _session_factory()
    db = factory()
    user = User(username="carol", password_hash="x", role=UserRole.admin)
    db.add(user)
    db.flush()
    content = DmContent(owner_id=user.id, title="老任务", content="legacy", images=[])
    db.add(content)
    db.flush()
    job = DmOutreachJob(
        owner_id=user.id, platform="facebook", browser_id="w", content_id=content.id, total=0
    )
    db.add(job)
    db.commit()
    assert [c.id for c in dm_api._job_contents(db, job)] == [content.id]
