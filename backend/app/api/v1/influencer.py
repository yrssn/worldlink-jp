from __future__ import annotations

import threading
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger
from sqlalchemy.orm import Session, joinedload

from app.core.deps import get_current_user, get_db, is_admin
from app.db.session import SessionLocal
from app.models.bitbrowser import BitBrowserPlatform
from app.models.influencer import Influencer
from app.models.influencer_scrape_task import InfluencerScrapeTask
from app.models.post import Post
from app.models.social_account import InfluencerSocialAccount
from app.models.user import User
from app.schemas.common import Msg, Page
from app.schemas.influencer import (
    InfluencerCreate,
    InfluencerDetailOut,
    InfluencerFromScrapeRequest,
    InfluencerOut,
    InfluencerScrapeTaskCreate,
    InfluencerScrapeTaskOut,
    InfluencerScrapeTaskSaveRequest,
    InfluencerUpdate,
    SocialAccountCreate,
    SocialAccountOut,
)
from app.services import apify_service, influencer_service
from app.utils.csv_export import build_csv, csv_response

router = APIRouter(prefix="/influencers", tags=["influencer"])


def _ensure_platform_access(db: Session, owner_id: int, platform_id: int | None) -> None:
    if platform_id is None:
        return
    exists = (
        db.query(BitBrowserPlatform.id)
        .filter(BitBrowserPlatform.id == platform_id, BitBrowserPlatform.owner_id == owner_id)
        .first()
    )
    if not exists:
        raise HTTPException(status_code=400, detail="达人类型不存在或无权使用")


def _scrape_task_out(db: Session, task: InfluencerScrapeTask) -> InfluencerScrapeTaskOut:
    """把任务序列化为输出，并补上「该主页是否已入库达人」的 influencer_id。"""
    out = InfluencerScrapeTaskOut.model_validate(task)
    result = task.result if isinstance(task.result, dict) else None
    if result:
        existing = influencer_service.find_duplicate(
            db,
            owner_id=task.owner_id,
            fb_page_id=result.get("fb_page_id"),
            fb_page_url=result.get("fb_page_url"),
            email=result.get("email"),
        )
        out.influencer_id = existing.id if existing else None
    return out


def _run_scrape_profile_bg(task_id: int) -> None:
    """后台线程：按主页 URL 跑 facebook-pages-scraper 抓资料，映射成可填充表单字段。"""
    db = SessionLocal()
    try:
        task: InfluencerScrapeTask | None = db.get(InfluencerScrapeTask, task_id)
        if not task:
            return
        task.status = "running"
        task.started_at = datetime.utcnow()
        db.commit()

        scrape_url = influencer_service.normalize_fb_profile_url(task.url)
        result = apify_service.run_fb_pages([scrape_url], max_items=1, db=db)
        items = result.get("items") or []
        if not items or not isinstance(items[0], dict):
            task.status = "failed"
            task.error = "未抓取到主页资料，请确认链接是否为有效的 Facebook 主页"
            task.finished_at = datetime.utcnow()
            db.commit()
            return

        form = influencer_service.page_profile_to_form(items[0])
        # 表单回填的主页链接统一用规整后的标准链接，避免回填群组上下文链接
        form["fb_page_url"] = influencer_service.normalize_fb_profile_url(
            form.get("fb_page_url") or scrape_url
        )
        task.result = form
        task.status = "done"
        task.finished_at = datetime.utcnow()
        db.commit()
        logger.info("[InfluencerScrape task#{}] done for {}", task_id, task.url)
    except Exception as e:  # noqa: BLE001
        logger.exception("[InfluencerScrape task#{}] failed: {}", task_id, e)
        try:
            task = db.get(InfluencerScrapeTask, task_id)
            if task:
                task.status = "failed"
                task.error = str(e)[:2000]
                task.finished_at = datetime.utcnow()
                db.commit()
        except Exception:  # noqa: BLE001
            pass
    finally:
        db.close()


INFLUENCER_CSV_COLUMNS = [
    ("ID", "id"),
    ("名称", "display_name"),
    ("真实姓名", "real_name"),
    ("简介", "bio"),
    ("国家", "country"),
    ("地区", "region"),
    ("城市", "city"),
    ("语言", "language"),
    ("地址", "address"),
    ("邮箱", "email"),
    ("电话", "phone"),
    ("Messenger", "messenger"),
    ("网站", "website"),
    ("FB主页URL", "fb_page_url"),
    ("FB标题", "fb_page_title"),
    ("FB分类", "fb_categories"),
    ("FB粉丝", "fb_followers"),
    ("FB点赞", "fb_likes"),
    ("FB评分", "fb_rating"),
    ("FB评分数", "fb_rating_count"),
    ("打卡/标记", "fb_checkins_mentions"),
    ("主页创建", "fb_page_created_at"),
    ("广告库ID", "fb_ad_library_id"),
    ("广告状态", "fb_ad_status"),
    ("状态", lambda r: r.status.value if r.status else ""),
    ("来源", lambda r: r.source.value if r.source else ""),
    ("类型", lambda r: r.platform_name or ""),
    ("标签", "tags"),
    ("备注", "notes"),
    ("创建时间", "created_at"),
]


@router.get("", response_model=Page[InfluencerOut])
def list_influencers(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    keyword: str | None = None,
    status_eq: str | None = Query(None, alias="status"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = db.query(Influencer).options(joinedload(Influencer.platform))
    if not is_admin(user):
        q = q.filter(Influencer.owner_id == user.id)
    if keyword:
        like = f"%{keyword}%"
        q = q.filter(
            (Influencer.display_name.like(like))
            | (Influencer.real_name.like(like))
            | (Influencer.email.like(like))
            | (Influencer.fb_page_url.like(like))
        )
    if status_eq:
        q = q.filter(Influencer.status == status_eq)
    total = q.count()
    items = (
        q.order_by(Influencer.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return Page[InfluencerOut](total=total, page=page, page_size=page_size, items=items)


@router.get("/export")
def export_influencers(
    keyword: str | None = None,
    status_eq: str | None = Query(None, alias="status"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """按当前过滤条件导出达人列表（CSV）。"""
    q = db.query(Influencer).options(joinedload(Influencer.platform))
    if not is_admin(user):
        q = q.filter(Influencer.owner_id == user.id)
    if keyword:
        like = f"%{keyword}%"
        q = q.filter(
            (Influencer.display_name.like(like))
            | (Influencer.real_name.like(like))
            | (Influencer.email.like(like))
            | (Influencer.fb_page_url.like(like))
        )
    if status_eq:
        q = q.filter(Influencer.status == status_eq)
    rows = q.order_by(Influencer.id.desc()).all()
    data = build_csv(rows, INFLUENCER_CSV_COLUMNS)
    return csv_response("influencers.csv", data)


@router.post("", response_model=InfluencerOut)
def create_influencer(
    payload: InfluencerCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    data = payload.model_dump(exclude={"social_accounts"})
    _ensure_platform_access(db, user.id, data.get("platform_id"))
    inf = Influencer(**data, owner_id=user.id)
    db.add(inf)
    db.flush()
    for sa in payload.social_accounts or []:
        db.add(
            InfluencerSocialAccount(influencer_id=inf.id, **sa.model_dump())
        )
    db.commit()
    db.refresh(inf)
    return inf


@router.post("/scrape-profile", response_model=InfluencerScrapeTaskOut)
def start_scrape_profile(
    payload: InfluencerScrapeTaskCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """手工新增达人时「自动抓取」：按主页 URL 异步跑 facebook-pages-scraper。

    主页抓取较慢，放后台线程执行；前端轮询任务状态，done 后用 result 自动填充表单。
    """
    url = (payload.url or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="请填写主页链接")
    task = InfluencerScrapeTask(owner_id=user.id, url=url, status="pending")
    db.add(task)
    db.commit()
    db.refresh(task)
    threading.Thread(
        target=_run_scrape_profile_bg, args=(task.id,), daemon=True
    ).start()
    return _scrape_task_out(db, task)


@router.get("/scrape-profile", response_model=list[InfluencerScrapeTaskOut])
def list_scrape_profiles(
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """抓取任务列表：按创建时间倒序返回当前用户最近的自动抓取任务。"""
    q = db.query(InfluencerScrapeTask)
    if not is_admin(user):
        q = q.filter(InfluencerScrapeTask.owner_id == user.id)
    tasks = q.order_by(InfluencerScrapeTask.id.desc()).limit(limit).all()
    return [_scrape_task_out(db, t) for t in tasks]


@router.get("/scrape-profile/{task_id}", response_model=InfluencerScrapeTaskOut)
def get_scrape_profile(
    task_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """轮询自动抓取任务状态/结果。"""
    task = db.get(InfluencerScrapeTask, task_id)
    if not task or (task.owner_id != user.id and not is_admin(user)):
        raise HTTPException(status_code=404, detail="task not found")
    return _scrape_task_out(db, task)


@router.post("/scrape-profile/{task_id}/save", response_model=InfluencerOut)
def save_scrape_profile(
    task_id: int,
    payload: InfluencerScrapeTaskSaveRequest | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """把某个已完成的抓取任务结果存入建联达人库（按主页ID/邮箱去重）。"""
    task = db.get(InfluencerScrapeTask, task_id)
    if not task or (task.owner_id != user.id and not is_admin(user)):
        raise HTTPException(status_code=404, detail="task not found")
    if task.status != "done" or not isinstance(task.result, dict) or not task.result:
        raise HTTPException(status_code=400, detail="该任务尚未抓取完成，无法存入")
    inf, _created = influencer_service.create_influencer_from_form(
        db,
        owner_id=task.owner_id,
        form=task.result,
        notes=(payload.notes if payload else None),
    )
    return inf


@router.get("/{iid}", response_model=InfluencerDetailOut)
def get_influencer(
    iid: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    inf = db.get(Influencer, iid)
    if not inf or (inf.owner_id != user.id and not is_admin(user)):
        raise HTTPException(status_code=404, detail="influencer not found")
    socials = (
        db.query(InfluencerSocialAccount)
        .filter(InfluencerSocialAccount.influencer_id == iid)
        .all()
    )
    post_ids = [
        p.id for p in db.query(Post.id).filter(Post.influencer_id == iid).all()
    ]
    out = InfluencerDetailOut.model_validate(inf)
    out.social_accounts = [SocialAccountOut.model_validate(s) for s in socials]
    out.source_post_ids = post_ids
    return out


@router.get("/{iid}/posts")
def list_influencer_posts(
    iid: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """返回该达人所有来源帖子（含 AI 评分、原帖链接）。"""
    inf = db.get(Influencer, iid)
    if not inf or (inf.owner_id != user.id and not is_admin(user)):
        raise HTTPException(status_code=404, detail="influencer not found")
    rows = (
        db.query(Post)
        .filter(Post.influencer_id == iid)
        .order_by(Post.id.desc())
        .all()
    )
    return [
        {
            "id": p.id,
            "task_id": p.task_id,
            "url": p.url,
            "text": p.text,
            "author_name": p.author_name,
            "likes": p.likes,
            "comments_count": p.comments_count,
            "shares": p.shares,
            "ai_passed": p.ai_passed,
            "ai_score": p.ai_score,
            "ai_reason": p.ai_reason,
            "published_at": p.published_at,
        }
        for p in rows
    ]


@router.put("/{iid}", response_model=InfluencerOut)
def update_influencer(
    iid: int,
    payload: InfluencerUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    inf = db.get(Influencer, iid)
    if not inf or (inf.owner_id != user.id and not is_admin(user)):
        raise HTTPException(status_code=404, detail="influencer not found")
    data = payload.model_dump(exclude_unset=True)
    _ensure_platform_access(db, inf.owner_id, data.get("platform_id"))
    for k, v in data.items():
        setattr(inf, k, v)
    db.commit()
    db.refresh(inf)
    return inf


@router.delete("/{iid}", response_model=Msg)
def delete_influencer(
    iid: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    inf = db.get(Influencer, iid)
    if not inf or (inf.owner_id != user.id and not is_admin(user)):
        raise HTTPException(status_code=404, detail="influencer not found")
    db.delete(inf)
    db.commit()
    return Msg()


@router.post("/from-scrape", response_model=InfluencerOut)
def create_from_scrape(
    payload: InfluencerFromScrapeRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """从抓取的【待审核博主】列表点击【建联】入库。"""
    post: Post | None = None
    if payload.post_id:
        post = db.get(Post, payload.post_id)
        if not post or (post.owner_id != user.id and not is_admin(user)):
            raise HTTPException(status_code=404, detail="post not found")
    elif payload.author_url:
        post = (
            db.query(Post)
            .filter(Post.owner_id == user.id, Post.author_url == payload.author_url)
            .order_by(Post.id.desc())
            .first()
        )

    # page_profile 中可能带 _source_post_ids（来自抓取 step4 时回写的源帖子）
    src_ids = list(payload.source_post_ids or [])
    if payload.page_profile and isinstance(payload.page_profile, dict):
        extra_ids = payload.page_profile.get("_source_post_ids")
        if isinstance(extra_ids, list):
            src_ids.extend(int(x) for x in extra_ids if x)

    inf = influencer_service.create_from_scrape(
        db=db,
        owner_id=user.id,
        post=post,
        page_profile=payload.page_profile,
        notes=payload.notes,
        source_post_ids=src_ids or None,
    )
    return inf


@router.post("/{iid}/social-accounts", response_model=SocialAccountOut)
def add_social_account(
    iid: int,
    payload: SocialAccountCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    inf = db.get(Influencer, iid)
    if not inf or (inf.owner_id != user.id and not is_admin(user)):
        raise HTTPException(status_code=404, detail="influencer not found")
    sa = InfluencerSocialAccount(influencer_id=iid, **payload.model_dump())
    db.add(sa)
    db.commit()
    db.refresh(sa)
    return sa


@router.delete("/{iid}/social-accounts/{sid}", response_model=Msg)
def delete_social_account(
    iid: int,
    sid: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    inf = db.get(Influencer, iid)
    if not inf or (inf.owner_id != user.id and not is_admin(user)):
        raise HTTPException(status_code=404, detail="influencer not found")
    sa = db.get(InfluencerSocialAccount, sid)
    if not sa or sa.influencer_id != iid:
        raise HTTPException(status_code=404, detail="social account not found")
    db.delete(sa)
    db.commit()
    return Msg()
