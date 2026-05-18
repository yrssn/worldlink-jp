from __future__ import annotations

from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db, is_admin
from app.db.session import SessionLocal
from app.models.post import Post
from app.models.scrape import ScrapeTask, ScrapeTaskStatus, ScrapeTaskType
from app.models.user import User
from app.schemas.common import Msg, Page
from app.schemas.post import PostOut
from app.schemas.scrape import ScrapeAuthorPagesBody, ScrapeTaskCreate, ScrapeTaskOut
from app.services import scrape_service
from app.utils.csv_export import build_csv, csv_response

router = APIRouter(prefix="/scraper/tasks", tags=["scraper"])


@router.post("", response_model=ScrapeTaskOut)
def create_task(
    payload: ScrapeTaskCreate,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if payload.enable_ai_filter and not (payload.llm_provider_id and payload.prompt_template_id):
        raise HTTPException(
            status_code=400,
            detail="启用 AI 过滤时，必须同时选择 llm_provider_id 与 prompt_template_id",
        )
    task = ScrapeTask(
        owner_id=user.id,
        **payload.model_dump(),
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    background.add_task(scrape_service.run_scrape_task, SessionLocal, task.id)
    return task


@router.get("", response_model=list[ScrapeTaskOut])
def list_tasks(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = db.query(ScrapeTask)
    if not is_admin(user):
        q = q.filter(ScrapeTask.owner_id == user.id)
    return q.order_by(ScrapeTask.id.desc()).all()


@router.get("/{tid}", response_model=ScrapeTaskOut)
def get_task(
    tid: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    task = db.get(ScrapeTask, tid)
    if not task or (task.owner_id != user.id and not is_admin(user)):
        raise HTTPException(status_code=404, detail="task not found")
    return task


@router.post("/{tid}/cancel", response_model=Msg)
def cancel_task(
    tid: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    task = db.get(ScrapeTask, tid)
    if not task or (task.owner_id != user.id and not is_admin(user)):
        raise HTTPException(status_code=404, detail="task not found")
    if task.status in (ScrapeTaskStatus.success, ScrapeTaskStatus.failed):
        return Msg(msg="already finished")
    task.status = ScrapeTaskStatus.canceled
    db.commit()
    return Msg()


@router.post("/{tid}/scrape-author-pages", response_model=Msg)
def scrape_author_pages_from_posts(
    tid: int,
    body: ScrapeAuthorPagesBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """勾选帖子后，按作者主页 URL 抓 facebook-pages-scraper 并合并到 page_results。"""
    task = db.get(ScrapeTask, tid)
    if not task or (task.owner_id != user.id and not is_admin(user)):
        raise HTTPException(status_code=404, detail="task not found")
    if task.task_type not in (
        ScrapeTaskType.fb_posts_by_page,
        ScrapeTaskType.fb_posts_by_hashtag,
        ScrapeTaskType.fb_posts_by_search,
    ):
        raise HTTPException(status_code=400, detail="仅 fb_posts_* 任务支持此操作")
    if task.status not in (ScrapeTaskStatus.success, ScrapeTaskStatus.partial):
        raise HTTPException(status_code=400, detail="请等任务成功完成后再抓主页")
    try:
        info = scrape_service.append_author_pages_for_selected_posts(db, task, body.post_ids)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    n = int(info.get("pages_count") or 0)
    return Msg(msg=f"已更新主页列表，当前共 {n} 条 Page 记录（与历史结果已按 URL 合并）")


@router.get("/{tid}/posts", response_model=Page[PostOut])
def list_task_posts(
    tid: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    only_passed: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """返回该任务抓回来的帖子（仅 fb_posts_* 任务有数据）。"""
    task = db.get(ScrapeTask, tid)
    if not task or (task.owner_id != user.id and not is_admin(user)):
        raise HTTPException(status_code=404, detail="task not found")
    q = db.query(Post).filter(Post.task_id == tid)
    if only_passed:
        q = q.filter(Post.ai_passed.is_(True))
    total = q.count()
    items = (
        q.order_by(Post.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return Page[PostOut](total=total, page=page, page_size=page_size, items=items)


# ==========================================================
# 导出（CSV）
# ==========================================================
POST_CSV_COLUMNS = [
    ("ID", "id"),
    ("任务ID", "task_id"),
    ("作者", "author_name"),
    ("作者主页", "author_url"),
    ("帖子URL", "url"),
    ("文本", "text"),
    ("点赞", "likes"),
    ("评论", "comments_count"),
    ("分享", "shares"),
    ("发布时间", "published_at"),
    ("AI通过", "ai_passed"),
    ("AI得分", "ai_score"),
    ("AI理由", "ai_reason"),
    ("已建联达人ID", "influencer_id"),
]

PAGE_CSV_COLUMNS = [
    ("名称", lambda r: r.get("title") or r.get("pageName")),
    ("分类", "categories"),
    ("主页URL", lambda r: r.get("pageUrl") or r.get("facebookUrl")),
    ("PageID", "pageId"),
    ("粉丝", "followers"),
    ("点赞", "likes"),
    ("评分%", "ratingOverall"),
    ("评分数", "ratingCount"),
    ("评分原文", "rating"),
    ("简介", lambda r: r.get("intro") or (r.get("about_me") or {}).get("text") if isinstance(r.get("about_me"), dict) else r.get("intro")),
    ("地址", "address"),
    ("邮箱", "email"),
    ("电话", "phone"),
    ("网站", "website"),
    ("Messenger", "messenger"),
    ("创建日期", "creation_date"),
    ("广告状态", "ad_status"),
    ("广告库ID", "pageAdLibrary.id"),
    ("头像", "profilePictureUrl"),
    ("封面", "coverPhotoUrl"),
    ("AI通过", "_ai_passed"),
    ("AI得分", "_ai_score"),
    ("AI理由", "_ai_reason"),
    ("来源帖子IDs", lambda r: r.get("_source_post_ids") or []),
]


@router.get("/{tid}/posts/export")
def export_task_posts(
    tid: int,
    only_passed: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """导出某任务抓到的帖子（CSV）。"""
    task = db.get(ScrapeTask, tid)
    if not task or (task.owner_id != user.id and not is_admin(user)):
        raise HTTPException(status_code=404, detail="task not found")
    q = db.query(Post).filter(Post.task_id == tid)
    if only_passed:
        q = q.filter(Post.ai_passed.is_(True))
    rows = q.order_by(Post.id.desc()).all()
    data = build_csv(rows, POST_CSV_COLUMNS)
    return csv_response(f"task_{tid}_posts.csv", data)


@router.get("/{tid}/pages/export")
def export_task_pages(
    tid: int,
    only_passed: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """导出某任务抓到的主页结果（CSV）。"""
    task = db.get(ScrapeTask, tid)
    if not task or (task.owner_id != user.id and not is_admin(user)):
        raise HTTPException(status_code=404, detail="task not found")
    items: list[dict[str, Any]] = []
    if task.extra_input and isinstance(task.extra_input, dict):
        items = list(task.extra_input.get("page_results") or [])
    if only_passed:
        items = [it for it in items if it.get("_ai_passed")]
    data = build_csv(items, PAGE_CSV_COLUMNS)
    return csv_response(f"task_{tid}_pages.csv", data)


@router.get("/{tid}/pages")
def list_task_pages(
    tid: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    only_passed: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """返回该任务抓回来的 Page 列表（待审核博主）。"""
    task = db.get(ScrapeTask, tid)
    if not task or (task.owner_id != user.id and not is_admin(user)):
        raise HTTPException(status_code=404, detail="task not found")

    items: list[dict[str, Any]] = []
    if task.extra_input and isinstance(task.extra_input, dict):
        items = list(task.extra_input.get("page_results") or [])

    if only_passed:
        items = [it for it in items if it.get("_ai_passed")]

    total = len(items)
    start = (page - 1) * page_size
    end = start + page_size
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": items[start:end],
    }
