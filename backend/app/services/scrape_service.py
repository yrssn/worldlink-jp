"""抓取任务编排。

================ 五种任务的统一工作流抽象 ================

A) "Page 类"任务（fb_search / fb_pages）
   一步：抓 Page → [AI 评估 Page] → 暂存 page_results → 前端【建联】

B) "Post 类"任务（fb_posts_by_page / fb_posts_by_hashtag / fb_posts_by_search）
   Step1：抓 Post（按主页 URL/关键词/ID / hashtag / 任意关键词）→ 入 posts 表
   Step2：[AI 评估 Post] → 标记 ai_passed / ai_score / ai_reason（可选）
   Step3–4：若 ``extra_input.defer_homepage_scrape`` 为真 → 跳过自动抓主页，仅留空 ``page_results``，
            用户在任务详情勾选帖子后调用「从选中帖子抓主页」再跑 facebook-pages-scraper 并合并。
            否则：聚合 author_url → 抓主页 → 暂存 page_results
   Step5：前端【建联】→ 入 Influencer（帖子或主页入口均可）

整套机制保证：
  - 帖子真实入表，可以回查"达人来自哪些帖子、各自 AI 评分"
  - Page 资料先存在 task.extra_input["page_results"]，由人工审核后才落 Influencer
  - 费用受控：max_items 控制第一步上限；page_limit 控制第二步（或手动抓主页）主页上限
"""
from __future__ import annotations

from collections import defaultdict
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


def _unwrap_post_dict(item: dict[str, Any]) -> dict[str, Any]:
    """Apify 不同 actor / 版本会把帖子放在根上或嵌套在 post / data / properties 里。"""
    cur = item
    for _ in range(5):
        changed = False
        if isinstance(cur.get("post"), dict):
            inner = cur["post"]
            cur = {k: v for k, v in cur.items() if k != "post"}
            cur.update(inner)
            changed = True
        data = cur.get("data")
        if isinstance(data, dict) and (
            data.get("text")
            or data.get("url")
            or data.get("postId")
            or data.get("post_id")
        ):
            cur = data
            changed = True
        props = cur.get("properties")
        if isinstance(props, dict) and (
            props.get("text")
            or props.get("url")
            or props.get("postId")
            or props.get("permalink")
        ):
            cur = props
            changed = True
        if not changed:
            break
    return cur


def _nested_count(item: dict[str, Any], *path_keys: str) -> Any:
    """从 item['a']['b'] 取可选计数。"""
    cur: Any = item
    for k in path_keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur


def _fb_profile_url_from_id(uid: Any) -> str | None:
    if uid is None or uid == "":
        return None
    return f"https://www.facebook.com/{uid}"


def _defer_homepage_scrape(task: ScrapeTask) -> bool:
    ex = task.extra_input or {}
    return bool(ex.get("defer_homepage_scrape"))


def _norm_fb_profile_url(u: str) -> str:
    if not u or not isinstance(u, str):
        return ""
    s = u.strip().split("?", 1)[0].split("#", 1)[0].rstrip("/")
    s = s.replace("://m.facebook.com", "://www.facebook.com")
    s = s.replace("://l.facebook.com", "://www.facebook.com")
    s = s.replace("://facebook.com", "://www.facebook.com")
    if s and not s.startswith("http"):
        s = "https://" + s.lstrip("/")
    return s.lower()


def append_author_pages_for_selected_posts(
    db: Session, task: ScrapeTask, post_ids: list[int]
) -> dict[str, Any]:
    """从已入库帖子中选题，按 author_url 去重后抓主页并合并进 ``extra_input.page_results``。"""
    if task.task_type not in (
        ScrapeTaskType.fb_posts_by_page,
        ScrapeTaskType.fb_posts_by_hashtag,
        ScrapeTaskType.fb_posts_by_search,
    ):
        raise ValueError("仅支持 fb_posts_* 任务")

    ids = sorted({int(x) for x in post_ids if x is not None})
    if not ids:
        raise ValueError("请至少选择一条帖子")

    posts = db.query(Post).filter(Post.task_id == task.id, Post.id.in_(ids)).all()
    if len(posts) != len(ids):
        raise ValueError("存在无效的 post_id（须属于本任务）")

    seen: dict[str, list[int]] = defaultdict(list)
    for p in posts:
        au = (p.author_url or "").strip()
        if not au:
            continue
        seen[au].append(p.id)

    page_urls = list(seen.keys())
    if not page_urls:
        raise ValueError("所选帖子均没有作者主页 URL")

    cap = max(1, int(task.page_limit or 50))
    page_urls = page_urls[:cap]

    pages_res = apify_service.run_fb_pages(
        start_urls=page_urls, max_items=len(page_urls), db=db
    )
    new_items: list[dict[str, Any]] = list(pages_res.get("items") or [])

    norm_to_pids: dict[str, list[int]] = defaultdict(list)
    for au, pids in seen.items():
        norm_to_pids[_norm_fb_profile_url(au)].extend(pids)

    def post_ids_for_page_row(item: dict[str, Any]) -> list[int]:
        pk = _norm_fb_profile_url(str(item.get("pageUrl") or item.get("facebookUrl") or ""))
        if not pk:
            return []
        acc: set[int] = set()
        for au_n, pids in norm_to_pids.items():
            if not au_n:
                continue
            if pk == au_n or pk.startswith(au_n + "/") or au_n.startswith(pk + "/"):
                acc.update(pids)
        return sorted(acc)

    existing = list((task.extra_input or {}).get("page_results") or [])
    by_key: dict[str, dict[str, Any]] = {}
    order: list[str] = []

    def row_key(it: dict[str, Any]) -> str:
        return _norm_fb_profile_url(str(it.get("pageUrl") or it.get("facebookUrl") or ""))

    for it in existing:
        k = row_key(it)
        if not k:
            continue
        if k not in by_key:
            by_key[k] = dict(it)
            order.append(k)
        else:
            a = by_key[k].get("_source_post_ids")
            b = it.get("_source_post_ids")
            if isinstance(a, list) or isinstance(b, list):
                merged_ids = list(a or []) + list(b or [])
                by_key[k]["_source_post_ids"] = sorted({int(x) for x in merged_ids if x is not None})

    for it in new_items:
        k = row_key(it)
        if not k:
            continue
        pids = post_ids_for_page_row(it)
        if k not in by_key:
            row = dict(it)
            row["_source_post_ids"] = pids
            by_key[k] = row
            order.append(k)
        else:
            cur = list(by_key[k].get("_source_post_ids") or [])
            for pid in pids:
                if pid not in cur:
                    cur.append(pid)
            by_key[k]["_source_post_ids"] = sorted(cur)

    merged = [by_key[k] for k in order]

    new_extra = dict(task.extra_input or {})
    new_extra["page_results"] = merged
    task.extra_input = new_extra
    db.commit()
    return {"pages_count": len(merged), "run_id": pages_res.get("run_id")}


def _map_facebook_video_reel_item(item: dict[str, Any]) -> dict[str, Any]:
    """facebook-hashtag-scraper 新版常返回 GraphQL Video/Reel 节点，无 text/user/likesCount。"""
    vo = item.get("video_owner") if isinstance(item.get("video_owner"), dict) else {}
    ow = item.get("owner") if isinstance(item.get("owner"), dict) else {}
    uid = vo.get("id") or ow.get("id")
    author_name = vo.get("name") or ow.get("name")
    author_url = _fb_profile_url_from_id(uid)
    url = item.get("permalink_url") or item.get("canonical_uri_with_fallback")
    hashtag = item.get("hashtag")
    cap = item.get("animated_image_caption")
    play = item.get("play_count")
    lines: list[str] = []
    if cap:
        lines.append(str(cap))
    lines.append("Facebook Reel / 视频帖子")
    if author_name:
        lines.append(f"作者: {author_name}")
    if hashtag:
        lines.append(f"Hashtag: #{hashtag}")
    if play is not None:
        lines.append(f"播放量: {play}")
    text = "\n".join(lines)
    post_id = str(item.get("id")) if item.get("id") is not None else None
    return {
        "post_id": post_id,
        "url": url,
        "text": text,
        "published_at": None,
        "likes": 0,
        "comments_count": 0,
        "shares": 0,
        "reactions": None,
        "media": item.get("image") if isinstance(item.get("image"), dict) else None,
        "author_name": author_name,
        "author_url": author_url,
        "author_page_id": str(uid) if uid else None,
        "raw": item,
    }


# =============================================================
# Post 字段映射（兼容多个 actor 的输出差异）
# =============================================================
def _map_post_item(item: dict[str, Any]) -> dict[str, Any]:
    """统一映射 posts-scraper / hashtag-scraper / search-posts 的输出到我们 Post 表。"""
    item = _unwrap_post_dict(dict(item))

    # 新版 hashtag scraper：dataset 多为 GraphQL Video（Reel），字段集与「经典帖子」完全不同
    tn = item.get("__typename")
    if tn == "Video" or (isinstance(tn, str) and "Video" in tn):
        return _map_facebook_video_reel_item(item)

    user_obj = item.get("user") if isinstance(item.get("user"), dict) else {}
    author_obj = item.get("author") if isinstance(item.get("author"), dict) else {}
    from_obj = item.get("from") if isinstance(item.get("from"), dict) else {}
    owner_obj = item.get("owner") if isinstance(item.get("owner"), dict) else {}
    page_obj = item.get("page") if isinstance(item.get("page"), dict) else {}
    profile_obj = item.get("profile") if isinstance(item.get("profile"), dict) else {}
    video_owner_obj = item.get("video_owner") if isinstance(item.get("video_owner"), dict) else {}

    author_name = (
        user_obj.get("name")
        or author_obj.get("name")
        or video_owner_obj.get("name")
        or from_obj.get("name")
        or owner_obj.get("name")
        or page_obj.get("name")
        or profile_obj.get("name")
        or item.get("authorName")
        or item.get("pageName")
        or item.get("userName")
        or _get_first(item, "ownerName", "username", "displayName")
    )
    author_url = (
        user_obj.get("profileUrl")
        or user_obj.get("url")
        or author_obj.get("profileUrl")
        or author_obj.get("url")
        or (video_owner_obj.get("profileUrl") or _fb_profile_url_from_id(video_owner_obj.get("id")))
        or from_obj.get("profileUrl")
        or from_obj.get("url")
        or from_obj.get("link")
        or owner_obj.get("url")
        or page_obj.get("url")
        or page_obj.get("link")
        or profile_obj.get("url")
        or item.get("authorUrl")
        or item.get("pageUrl")
        or item.get("ownerUrl")
    )
    author_page_id = (
        user_obj.get("id")
        or author_obj.get("id")
        or video_owner_obj.get("id")
        or from_obj.get("id")
        or owner_obj.get("id")
        or page_obj.get("id")
        or profile_obj.get("id")
        or item.get("pageId")
        or item.get("authorId")
        or item.get("ownerId")
    )

    msg = item.get("message")
    msg_text: str | None = None
    if isinstance(msg, dict):
        msg_text = msg.get("text") or msg.get("message") or msg.get("story")

    text = (
        _get_first(
            item,
            "text",
            "content",
            "caption",
            "body",
            "snippet",
            "postText",
            "story",
            "message",
        )
        or msg_text
    )

    likes = _get_first(
        item,
        "likesCount",
        "likes",
        "reactionsCount",
        "reactions_count",
        "like_count",
        "likeCount",
        "likes_count",
    )
    if likes is None:
        likes = _nested_count(item, "stats", "likes") or _nested_count(item, "stats", "like_count")
    if likes is None and isinstance(item.get("reactions"), dict):
        rx = item["reactions"]
        likes = rx.get("totalCount") or rx.get("total_count")
        summ = rx.get("summary")
        if isinstance(summ, dict):
            likes = likes or summ.get("total_count")

    comments = _get_first(
        item,
        "commentsCount",
        "comments",
        "commentCount",
        "comment_count",
        "comments_count",
    )
    if comments is None:
        comments = _nested_count(item, "stats", "comments")

    shares = _get_first(
        item,
        "sharesCount",
        "shares",
        "shareCount",
        "share_count",
        "shares_count",
        "reshare_count",
    )
    if shares is None:
        shares = _nested_count(item, "stats", "shares")

    return {
        "post_id": str(_get_first(item, "postId", "post_id", "fbid", "id", "postID") or "")
        or None,
        "url": _get_first(
            item,
            "url",
            "postUrl",
            "permalink",
            "permalink_url",
            "link",
            "permalinkUrl",
            "post_link",
            "storyUrl",
            "canonical_uri_with_fallback",
        ),
        "text": text,
        "published_at": _parse_dt(
            _get_first(
                item,
                "time",
                "date",
                "publishedTime",
                "published_at",
                "timestamp",
                "createdTime",
                "created_at",
                "postedAt",
            )
        ),
        "likes": _to_int(likes),
        "comments_count": _to_int(comments),
        "shares": _to_int(shares),
        "reactions": item.get("reactions"),
        "media": _get_first(item, "media", "attachments", "images", "image"),
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
        elif tt == ScrapeTaskType.fb_posts_scraper:
            _run_fb_posts_scraper(db, task)
        elif tt == ScrapeTaskType.fb_search_cb:
            _run_fb_search_cb(db, task)
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
        db=db,
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
        db=db,
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

    if _defer_homepage_scrape(task):
        new_extra = dict(task.extra_input or {})
        new_extra["page_results"] = []
        task.extra_input = new_extra
        task.status = ScrapeTaskStatus.success
        db.commit()
        return

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
                db=db,
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
    """按主页抓帖：默认 ``cleansyntax/facebook-profile-posts-scraper``（profile_posts_by_url）。

    可选 ``extra_input``：
      - ``fb_profile_endpoint``：``profile_posts_by_url``（默认）| ``profile_posts`` | ``search_posts_by_keyword``
      - ``start_date`` / ``end_date``：``YYYY-MM-DD``，actor 侧过滤
      - ``ids_text``：仅当 endpoint=``profile_posts`` 时必填，每行一个 profile id
      - 其它键透传给 actor（勿放 ``page_results``）
    """
    extra_in = dict(task.extra_input or {})
    endpoint = str(extra_in.pop("fb_profile_endpoint", None) or "profile_posts_by_url").strip()

    start_date = extra_in.pop("start_date", None)
    end_date = extra_in.pop("end_date", None)
    ids_text_val = extra_in.pop("ids_text", None)
    extra_in.pop("defer_homepage_scrape", None)
    extra_in.pop("page_results", None)

    max_posts = max(0, int(task.posts_per_page or 0))

    if endpoint == "search_posts_by_keyword":
        kws = [str(k).strip() for k in (task.keywords or []) if k and str(k).strip()]
        if not kws:
            raise ValueError("fb_posts_by_page 使用 search_posts_by_keyword 时请在「关键词」中填写搜索词（每行/逗号分隔）")
        result = apify_service.run_fb_profile_posts(
            endpoint=endpoint,
            keywords_text="\n".join(kws),
            max_posts=max_posts,
            start_date=str(start_date).strip() if start_date else None,
            end_date=str(end_date).strip() if end_date else None,
            extra=extra_in or None,
            db=db,
        )
    elif endpoint == "profile_posts":
        ids_text = ids_text_val if isinstance(ids_text_val, str) and ids_text_val.strip() else None
        if not ids_text:
            raise ValueError(
                "fb_posts_by_page 使用 profile_posts（按数字 ID）时请在 extra_input 中提供 ids_text（字符串，每行一个 id）"
            )
        result = apify_service.run_fb_profile_posts(
            endpoint=endpoint,
            ids_text=ids_text,
            max_posts=max_posts,
            start_date=str(start_date).strip() if start_date else None,
            end_date=str(end_date).strip() if end_date else None,
            extra=extra_in or None,
            db=db,
        )
    else:
        urls = [str(u).strip() for u in (task.start_urls or []) if u and str(u).strip()]
        if not urls:
            raise ValueError("fb_posts_by_page（profile_posts_by_url）需要 start_urls（主页 URL，每行一个）")
        result = apify_service.run_fb_profile_posts(
            endpoint="profile_posts_by_url",
            urls_text="\n".join(urls),
            max_posts=max_posts,
            start_date=str(start_date).strip() if start_date else None,
            end_date=str(end_date).strip() if end_date else None,
            extra=extra_in or None,
            db=db,
        )

    _run_post_pipeline(
        db,
        task,
        result.get("items") or [],
        result.get("run_id"),
        result.get("dataset_id"),
    )


def _run_fb_search_cb(db: Session, task: ScrapeTask) -> None:
    """crawlerbros/facebook-search-scraper：关键词 → Pages/People。

    extra_input 可选键：
      - ``cb_search_type``：``pages``（默认）| ``people``
    """
    kws = [str(k).strip() for k in (task.keywords or []) if k and str(k).strip()]
    if not kws:
        raise ValueError("fb_search_cb 任务需要至少一个关键词")

    extra_in = dict(task.extra_input or {})
    search_type = str(extra_in.pop("cb_search_type", None) or "pages").strip()
    extra_in.pop("page_results", None)

    result = apify_service.run_fb_search_cb(
        keywords=kws,
        search_type=search_type,
        max_results=task.max_items,
        extra=extra_in or None,
        db=db,
    )
    _persist_page_results(
        db, task,
        result.get("items") or [],
        result.get("run_id"),
        result.get("dataset_id"),
    )


def _run_fb_posts_scraper(db: Session, task: ScrapeTask) -> None:
    """apify/facebook-posts-scraper：给定主页 URL 列表抓帖子。

    Input mapping:
      - ``start_urls``        → startUrls[].url
      - ``posts_per_page``    → per-URL resultsLimit (0 = actor default)
      - ``max_items``         → global resultsLimit (optional)
      - ``extra_input``       → 透传给 actor（除保留键外）
    """
    urls = [str(u).strip() for u in (task.start_urls or []) if u and str(u).strip()]
    if not urls:
        raise ValueError("fb_posts_scraper 任务需要至少一个主页 URL（start_urls）")

    extra_in = dict(task.extra_input or {})
    extra_in.pop("defer_homepage_scrape", None)
    extra_in.pop("page_results", None)

    result = apify_service.run_fb_posts(
        start_urls=urls,
        posts_per_page=max(1, int(task.posts_per_page or 10)),
        total_limit=task.max_items or None,
        extra=extra_in or None,
        db=db,
    )
    _run_post_pipeline(
        db,
        task,
        result.get("items") or [],
        result.get("run_id"),
        result.get("dataset_id"),
    )


def _run_fb_posts_by_hashtag(db: Session, task: ScrapeTask) -> None:
    tags = task.hashtags or []
    if not tags:
        raise ValueError("fb_posts_by_hashtag 任务需要 hashtags")
    result = apify_service.run_fb_hashtag(
        hashtags=tags,
        max_items=task.max_items,
        extra={k: v for k, v in (task.extra_input or {}).items() if k not in ("page_results", "defer_homepage_scrape")},
        db=db,
    )
    _run_post_pipeline(db, task, result.get("items") or [],
                       result.get("run_id"), result.get("dataset_id"))


def _run_fb_posts_by_search(db: Session, task: ScrapeTask) -> None:
    kws = task.keywords or []
    if not kws:
        raise ValueError("fb_posts_by_search 任务需要 keywords")

    extra_in = task.extra_input or {}
    # 已知的可选过滤参数（来自 actor input-schema）
    known_keys = {"location_uid", "search_type", "start_date", "end_date", "recent_posts", "defer_homepage_scrape"}
    passthrough = {k: extra_in[k] for k in known_keys if k in extra_in}

    result = apify_service.run_fb_search_posts(
        keywords=kws,
        max_items=task.max_items,
        location_uid=passthrough.pop("location_uid", None),
        search_type=passthrough.pop("search_type", "posts"),
        start_date=passthrough.pop("start_date", None),
        end_date=passthrough.pop("end_date", None),
        recent_posts=bool(passthrough.pop("recent_posts", False)),
        extra={k: v for k, v in extra_in.items()
               if k not in known_keys and k != "page_results"},
        db=db,
    )
    _run_post_pipeline(db, task, result.get("items") or [],
                       result.get("run_id"), result.get("dataset_id"))
