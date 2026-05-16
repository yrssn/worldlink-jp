"""抓取任务编排。

================ 五种任务的统一工作流抽象 ================

A) "Page 类"任务（fb_search / fb_pages）
   一步：抓 Page → [AI 评估 Page] → 暂存 page_results → 前端【建联】

B) "Post 类"任务（fb_posts_by_page / fb_posts_by_hashtag / fb_posts_by_search）
   Step1：抓 Post（按主页 / hashtag / 任意关键词）→ 入 posts 表
   Step2：[AI 评估 Post] → 标记 ai_passed / ai_score / ai_reason
   Step3：聚合"AI 通过"帖子的 author_url 去重（不超过 page_limit）
   Step4：用 facebook-pages-scraper 抓这些主页详情 → 暂存 page_results
          page_result 中冗余字段 _source_post_ids 指回触发它的帖子 id
   Step5：前端【建联】→ 入 Influencer。建联后所有源帖子的 influencer_id 一起回写。

整套机制保证：
  - 帖子真实入表，可以回查"达人来自哪些帖子、各自 AI 评分"
  - Page 资料先存在 task.extra_input["page_results"]，由人工审核后才落 Influencer
  - 费用受控：max_items 控制第一步上限；page_limit 控制第二步主页上限
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from loguru import logger
from sqlalchemy.orm import Session

from app.models.llm import LlmProvider
from app.models.post import Post
from app.models.prompt import PromptTemplate
from app.models.scrape import ScrapeTask, ScrapeTaskStatus, ScrapeTaskType
from app.services import ai_filter_service, apify_service


# =============================================================
# 通用工具
# =============================================================
def _parse_dt(v: Any) -> datetime | None:
    if not v:
        return None
    if isinstance(v, datetime):
        return v
    try:
        if isinstance(v, (int, float)):
            return datetime.fromtimestamp(int(v))
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except Exception:
        return None


def _to_int(v: Any, default: int = 0) -> int:
    try:
        if v is None or v == "":
            return default
        return int(float(v))
    except Exception:
        return default


def _get_first(d: dict[str, Any], *keys: str) -> Any:
    for k in keys:
        v = d.get(k)
        if v is not None and v != "":
            return v
    return None


# =============================================================
# Post 字段映射（兼容多个 actor 的输出差异）
# =============================================================
def _map_post_item(item: dict[str, Any]) -> dict[str, Any]:
    """统一映射 posts-scraper / hashtag-scraper / search-posts 的输出到我们 Post 表。"""
    user_obj = item.get("user") if isinstance(item.get("user"), dict) else {}
    author_obj = item.get("author") if isinstance(item.get("author"), dict) else {}

    author_name = (
        user_obj.get("name")
        or author_obj.get("name")
        or item.get("authorName")
        or item.get("pageName")
        or _get_first(item, "ownerName", "userName")
    )
    author_url = (
        user_obj.get("profileUrl")
        or user_obj.get("url")
        or author_obj.get("profileUrl")
        or author_obj.get("url")
        or item.get("authorUrl")
        or item.get("pageUrl")
        or item.get("ownerUrl")
    )
    author_page_id = (
        user_obj.get("id")
        or author_obj.get("id")
        or item.get("pageId")
        or item.get("authorId")
        or item.get("ownerId")
    )

    return {
        "post_id": str(_get_first(item, "postId", "id", "postID", "post_id") or "") or None,
        "url": _get_first(item, "url", "postUrl", "permalink"),
        "text": _get_first(item, "text", "message", "content", "caption"),
        "published_at": _parse_dt(_get_first(item, "time", "date", "publishedTime", "timestamp", "createdTime")),
        "likes": _to_int(_get_first(item, "likesCount", "likes", "reactionsCount")),
        "comments_count": _to_int(_get_first(item, "commentsCount", "comments", "commentCount")),
        "shares": _to_int(_get_first(item, "sharesCount", "shares", "shareCount")),
        "reactions": item.get("reactions"),
        "media": _get_first(item, "media", "attachments", "images"),
        "author_name": author_name,
        "author_url": author_url,
        "author_page_id": str(author_page_id) if author_page_id else None,
        "raw": item,
    }


# =============================================================
# 主入口
# =============================================================
def run_scrape_task(db_factory, task_id: int) -> None:
    """后台运行入口。db_factory 是 SessionLocal。"""
    db: Session = db_factory()
    try:
        task = db.get(ScrapeTask, task_id)
        if not task:
            logger.warning("ScrapeTask {} not found", task_id)
            return
        task.status = ScrapeTaskStatus.running
        db.commit()

        tt = task.task_type
        if tt == ScrapeTaskType.fb_search:
            _run_fb_search(db, task)
        elif tt == ScrapeTaskType.fb_pages:
            _run_fb_pages(db, task)
        elif tt == ScrapeTaskType.fb_posts_by_page:
            _run_fb_posts_by_page(db, task)
        elif tt == ScrapeTaskType.fb_posts_by_hashtag:
            _run_fb_posts_by_hashtag(db, task)
        elif tt == ScrapeTaskType.fb_posts_by_search:
            _run_fb_posts_by_search(db, task)
        else:
            raise ValueError(f"Unsupported task_type: {tt}")

    except Exception as e:  # noqa: BLE001
        logger.exception("Run scrape task failed: {}", e)
        try:
            task = db.get(ScrapeTask, task_id)
            if task:
                task.status = ScrapeTaskStatus.failed
                task.error = str(e)
                db.commit()
        except Exception:
            pass
    finally:
        db.close()


# =============================================================
# A 类 - Page 任务：直接抓 Page 资料
# =============================================================
def _persist_page_results(
    db: Session,
    task: ScrapeTask,
    items: list[dict[str, Any]],
    run_id: str | None,
    dataset_id: str | None,
) -> None:
    """把抓到的 Page items 和 AI 过滤结果存到 task.extra_input。"""
    task.apify_run_id = run_id
    task.apify_dataset_id = dataset_id
    task.result_count = len(items)
    db.commit()

    passed_count = 0
    if task.enable_ai_filter and task.llm_provider_id and task.prompt_template_id:
        provider = db.get(LlmProvider, task.llm_provider_id)
        template = db.get(PromptTemplate, task.prompt_template_id)
        if provider and template:
            for item in items:
                r = ai_filter_service.evaluate_page(provider, template, _page_to_eval_input(item))
                item["_ai_passed"] = bool(r.get("passed"))
                item["_ai_score"] = r.get("score")
                item["_ai_reason"] = r.get("reason")
                if item["_ai_passed"]:
                    passed_count += 1
            task.filtered_count = passed_count

    new_extra = dict(task.extra_input or {})
    new_extra["page_results"] = items
    task.extra_input = new_extra
    task.status = ScrapeTaskStatus.success
    db.commit()


def _page_to_eval_input(item: dict[str, Any]) -> dict[str, Any]:
    about_me = item.get("about_me") if isinstance(item.get("about_me"), dict) else {}
    return {
        "title": item.get("title") or item.get("pageName"),
        "pageUrl": item.get("pageUrl") or item.get("facebookUrl"),
        "categories": item.get("categories"),
        "intro": item.get("intro") or about_me.get("text"),
        "followers": item.get("followers"),
        "likes": item.get("likes"),
        "website": item.get("website"),
        "email": item.get("email"),
        "phone": item.get("phone"),
        "address": item.get("address"),
        "rating": item.get("rating") or item.get("ratingOverall"),
        "ratingCount": item.get("ratingCount"),
        "ad_status": item.get("ad_status"),
        "creation_date": item.get("creation_date"),
    }


def _run_fb_search(db: Session, task: ScrapeTask) -> None:
    locations: list[str] = []
    extra_in = task.extra_input or {}
    if isinstance(extra_in.get("locations"), list):
        locations = [str(x) for x in extra_in["locations"] if x]
    if task.address:
        locations.append(task.address)

    result = apify_service.run_fb_search(
        keywords=task.keywords or [],
        locations=locations or None,
        max_items=task.max_items,
        extra={k: v for k, v in extra_in.items() if k not in ("locations", "page_results")},
    )
    _persist_page_results(db, task, result.get("items") or [],
                          result.get("run_id"), result.get("dataset_id"))


def _run_fb_pages(db: Session, task: ScrapeTask) -> None:
    urls = task.start_urls or []
    if not urls:
        raise ValueError("fb_pages 任务需要 start_urls")
    result = apify_service.run_fb_pages(
        start_urls=urls,
        max_items=task.max_items,
        extra={k: v for k, v in (task.extra_input or {}).items() if k != "page_results"},
    )
    _persist_page_results(db, task, result.get("items") or [],
                          result.get("run_id"), result.get("dataset_id"))


# =============================================================
# B 类 - Post 任务：抓帖子 → AI 过滤 → 抓主页
# =============================================================
def _run_post_pipeline(
    db: Session,
    task: ScrapeTask,
    post_items: list[dict[str, Any]],
    run_id: str | None,
    dataset_id: str | None,
) -> None:
    """抓到 posts 后的统一后处理：入库 → AI → 抓 Page → 暂存 page_results。"""
    task.apify_run_id = run_id
    task.apify_dataset_id = dataset_id
    task.result_count = len(post_items)
    db.commit()

    # --- Step1: posts 入表 ---
    posts: list[Post] = []
    for raw in post_items:
        mapped = _map_post_item(raw)
        post = Post(task_id=task.id, owner_id=task.owner_id, **mapped)
        db.add(post)
        posts.append(post)
    db.commit()

    # --- Step2: AI 评估帖子 ---
    passed_posts: list[Post] = []
    if task.enable_ai_filter and task.llm_provider_id and task.prompt_template_id:
        provider = db.get(LlmProvider, task.llm_provider_id)
        template = db.get(PromptTemplate, task.prompt_template_id)
        if provider and template:
            for post in posts:
                eval_input = {
                    "text": post.text,
                    "author_name": post.author_name,
                    "author_url": post.author_url,
                    "likes": post.likes,
                    "comments_count": post.comments_count,
                    "shares": post.shares,
                    "url": post.url,
                }
                r = ai_filter_service.evaluate_post(provider, template, eval_input)
                post.ai_passed = bool(r.get("passed"))
                post.ai_score = r.get("score")
                post.ai_reason = r.get("reason")
                if post.ai_passed:
                    passed_posts.append(post)
            db.commit()
            task.filtered_count = len(passed_posts)
            db.commit()
    else:
        # 未启用 AI：默认全部进入下一步
        passed_posts = [p for p in posts if p.author_url]

    # --- Step3: 聚合主页 URL（去重） ---
    seen: dict[str, list[int]] = {}
    for p in passed_posts:
        if not p.author_url:
            continue
        seen.setdefault(p.author_url, []).append(p.id)
    page_urls = list(seen.keys())[: max(1, task.page_limit)]

    # --- Step4: 抓主页详情 ---
    page_results: list[dict[str, Any]] = []
    if page_urls:
        try:
            pages_res = apify_service.run_fb_pages(
                start_urls=page_urls,
                max_items=len(page_urls),
            )
            for item in pages_res.get("items") or []:
                url = item.get("pageUrl") or item.get("facebookUrl")
                if url and url in seen:
                    item["_source_post_ids"] = seen[url]
                page_results.append(item)
        except Exception as e:  # noqa: BLE001
            logger.exception("Step4 facebook-pages-scraper failed: {}", e)
            task.error = (task.error or "") + f"\nstep4 failed: {e}"

    # --- 暂存 page_results 到 task.extra_input ---
    new_extra = dict(task.extra_input or {})
    new_extra["page_results"] = page_results
    task.extra_input = new_extra
    task.status = ScrapeTaskStatus.success
    db.commit()


def _run_fb_posts_by_page(db: Session, task: ScrapeTask) -> None:
    urls = task.start_urls or []
    if not urls:
        raise ValueError("fb_posts_by_page 任务需要 start_urls")
    result = apify_service.run_fb_posts(
        start_urls=urls,
        posts_per_page=task.posts_per_page,
        total_limit=task.max_items,
        extra={k: v for k, v in (task.extra_input or {}).items() if k != "page_results"},
    )
    _run_post_pipeline(db, task, result.get("items") or [],
                       result.get("run_id"), result.get("dataset_id"))


def _run_fb_posts_by_hashtag(db: Session, task: ScrapeTask) -> None:
    tags = task.hashtags or []
    if not tags:
        raise ValueError("fb_posts_by_hashtag 任务需要 hashtags")
    result = apify_service.run_fb_hashtag(
        hashtags=tags,
        max_items=task.max_items,
        extra={k: v for k, v in (task.extra_input or {}).items() if k != "page_results"},
    )
    _run_post_pipeline(db, task, result.get("items") or [],
                       result.get("run_id"), result.get("dataset_id"))


def _run_fb_posts_by_search(db: Session, task: ScrapeTask) -> None:
    kws = task.keywords or []
    if not kws:
        raise ValueError("fb_posts_by_search 任务需要 keywords")

    extra_in = task.extra_input or {}
    # 已知的可选过滤参数（来自 actor input-schema）
    known_keys = {"location_uid", "search_type", "start_date", "end_date", "recent_posts"}
    passthrough = {k: extra_in[k] for k in known_keys if k in extra_in}

    result = apify_service.run_fb_search_posts(
        keywords=kws,
        max_items=task.max_items,
        location_uid=passthrough.pop("location_uid", None),
        search_type=passthrough.pop("search_type", "posts"),
        start_date=passthrough.pop("start_date", None),
        end_date=passthrough.pop("end_date", None),
        recent_posts=bool(passthrough.pop("recent_posts", False)),
        # 其余未知字段透传（例如 actor 升级后增加的可选字段）
        extra={k: v for k, v in extra_in.items()
               if k not in known_keys and k != "page_results"},
    )
    _run_post_pipeline(db, task, result.get("items") or [],
                       result.get("run_id"), result.get("dataset_id"))
