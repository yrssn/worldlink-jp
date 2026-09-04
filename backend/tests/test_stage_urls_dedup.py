"""批量导入暂存时按链接查重：本次重复 / 本账号任务 / 本账号达人库 / 对照账号 都跳过并给原因。"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.db.init_db  # noqa: F401  注册全部模型
from app.api.v1 import influencer as inf_api
from app.db.base import Base
from app.models.influencer import Influencer
from app.models.influencer_scrape_task import InfluencerScrapeTask
from app.models.user import User, UserRole


def _db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)()


def test_stage_urls_skips_duplicates_by_link():
    db = _db()
    user = User(username="alice", password_hash="x", role=UserRole.admin)
    db.add(user)
    db.flush()
    saved = Influencer(
        owner_id=user.id,
        display_name="Saved",
        fb_page_url="https://www.facebook.com/profile.php?id=100001",
    )
    task = InfluencerScrapeTask(
        owner_id=user.id,
        platform="facebook",
        url="https://facebook.com/luxefinds/",
        batch="b1",
        status="staged",
    )
    db.add_all([saved, task])
    db.commit()

    res = inf_api._stage_urls(
        db,
        user,
        [
            "https://www.facebook.com/profile.php?id=100001",  # 达人库已有
            "http://www.facebook.com/luxefinds",  # 暂存任务已有（写法不同）
            "https://www.facebook.com/profile.php?id=100002",  # 新的
            "https://www.facebook.com/profile.php?id=100002/",  # 本次重复
            "https://www.facebook.com/profile.php?id=100003",  # 新的
        ],
        platform="auto",
        fallback_platform="facebook",
        batch=None,
    )

    assert res.total == 5
    assert [t.url for t in res.created] == [
        "https://www.facebook.com/profile.php?id=100002",
        "https://www.facebook.com/profile.php?id=100003",
    ]
    kinds = {s.url: s.kind for s in res.skipped}
    assert kinds == {
        "https://www.facebook.com/profile.php?id=100001": "self_influencer",
        "http://www.facebook.com/luxefinds": "self_task",
        "https://www.facebook.com/profile.php?id=100002/": "batch",
    }
    by_url = {s.url: s for s in res.skipped}
    assert by_url["https://www.facebook.com/profile.php?id=100001"].influencer_id == saved.id
    assert by_url["http://www.facebook.com/luxefinds"].task_id == task.id
    assert db.query(InfluencerScrapeTask).count() == 3
