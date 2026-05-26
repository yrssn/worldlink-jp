"""Apify 客户端封装。

仅做"调用 Actor + 取 dataset"这一层薄封装；具体业务流程在 scrape_service 中编排。

============================================================
五种获客场景与对应 Apify Actor 一览
============================================================

1) ``run_fb_search``  关键词 → Pages（一步到位）
   - Actor: apify/facebook-search-scraper
   - Input: categories[], locations[], resultsLimit
   - Output: 匹配的 Page/Profile 资料（同 Pages Scraper 输出）
   - 费用: ~$10 / 1000 pages
   - Docs: https://apify.com/apify/facebook-search-scraper

2) ``run_fb_pages``  Page URL → 主页详情
   - Actor: apify/facebook-pages-scraper
   - Input: startUrls=[{url}, ...], resultsLimit
   - Output: title/pageUrl/likes/followers/email/phone/address/rating/...
   - 费用: ~$6.6 / 1000 pages
   - Docs: https://apify.com/apify/facebook-pages-scraper

3) ``run_fb_posts``  Page URL → 帖子（官方 actor，备用）
   - Actor: apify/facebook-posts-scraper
   - Input: startUrls=[{url}, ...], resultsLimit
   - 费用: ~$10 / 1000 posts

3b) ``run_fb_profile_posts``  主页 URL / 数字 ID / 关键词 → 帖子（fb_posts_by_page 默认用此）
   - Actor: cleansyntax/facebook-profile-posts-scraper
   - Input: endpoint + urls_text | ids_text | keywords_text + max_posts + 可选日期
   - 费用: ~$6 / 1000 results（以 Apify 定价页为准）
   - Docs: https://apify.com/cleansyntax/facebook-profile-posts-scraper

4) ``run_fb_hashtag``  hashtag → 帖子
   - Actor: apify/facebook-hashtag-scraper
   - Input: keywordList=[ "tokyo", "cafe" ]  (官方字段名；不带 #), resultsLimit
   - Output: 与 posts-scraper 类似
   - 费用: ~$10 / 1000 posts
   - Docs: https://apify.com/apify/facebook-hashtag-scraper

5) ``run_fb_search_posts``  任意关键词 → 帖子 (第三方 actor，更灵活)

6) ``run_fb_groups``  群组 URL → 帖子
   - Actor: apify/facebook-groups-scraper
   - Input: startUrls, resultsLimit, viewOption, searchGroupKeyword, searchGroupYear, onlyPostsNewerThan
   - Docs: https://apify.com/apify/facebook-groups-scraper
   - Actor: scrapeforge/facebook-search-posts
   - Input: searchQueries=[...], resultsLimit
   - Output: post 数据
   - 费用: ~$10-15 / 1000 posts (按 actor 主页为准)
   - Docs: https://apify.com/scrapeforge/facebook-search-posts
"""
from __future__ import annotations

from typing import Any, Optional

from loguru import logger
from sqlalchemy.orm import Session

from app.core.config import settings


# ---------- 内部工具 ----------
def _resolve_token(db: Session | None = None) -> str:
    """优先从 DB 中取 is_default=True 的 Key，否则回退到 settings.apify_token。"""
    if db is not None:
        try:
            from app.models.apify_key import ApifyKey
            row = db.query(ApifyKey).filter(ApifyKey.is_default.is_(True)).first()
            if row and row.token:
                return row.token
        except Exception:  # noqa: BLE001
            pass
    if settings.apify_token:
        return settings.apify_token
    raise RuntimeError("未配置可用的 Apify Token（请在「Apify Key 管理」中添加并设置默认 Key）")


def _get_client(db: Session | None = None):
    token = _resolve_token(db)
    from apify_client import ApifyClient

    return ApifyClient(token)


def _run_actor(
    actor_id: str,
    run_input: dict[str, Any],
    *,
    timeout_secs: int = 600,
    db: Session | None = None,
) -> dict[str, Any]:
    """统一调用 Actor 并把 dataset 全部拉回来。"""
    client = _get_client(db)
    logger.info("[Apify] Start {} timeout={}s input={}", actor_id, timeout_secs, run_input)
    try:
        # wait_secs：客户端最长等待时间；timeout_secs：Actor 单次运行上限
        run = client.actor(actor_id).call(
            run_input=run_input,
            wait_secs=timeout_secs,
            timeout_secs=timeout_secs,
        )
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"Apify 调用超时或失败 ({actor_id}): {e}") from e
    if not run:
        raise RuntimeError(f"Apify run {actor_id} returned empty")

    status = str(run.get("status") or "").upper()
    run_id = run.get("id")
    if status and status != "SUCCEEDED":
        msg = (
            run.get("statusMessage")
            or (run.get("meta") or {}).get("errorMessage")
            or status
        )
        raise RuntimeError(
            f"Apify run 未成功 (id={run_id}, status={status}): {msg}"
        )

    dataset_id = run.get("defaultDatasetId")
    items: list[dict[str, Any]] = []
    if dataset_id:
        items = list(client.dataset(dataset_id).iterate_items())

    logger.info(
        "[Apify] Run {} finished run_id={} status={} items={}",
        actor_id,
        run_id,
        status or "SUCCEEDED",
        len(items),
    )
    return {
        "run_id": run_id,
        "dataset_id": dataset_id,
        "items": items,
        "status": status or "SUCCEEDED",
    }


# ---------- 1) Facebook Search Scraper ----------
def run_fb_search(
    keywords: list[str] | None = None,
    locations: list[str] | None = None,
    max_items: int = 50,
    extra: Optional[dict[str, Any]] = None,
    db: Session | None = None,
) -> dict[str, Any]:
    """关键词 + 位置 → 匹配的 Pages。

    官方输入字段：
      - categories  array<string>  关键词列表 (必填)
      - locations   array<string>  地区列表
      - resultsLimit  integer      返回上限
    """
    cats = [k for k in (keywords or []) if k]
    if not cats:
        raise ValueError("facebook-search-scraper 需要至少一个关键词 (categories)")
    run_input: dict[str, Any] = {
        "categories": cats,
        "resultsLimit": int(max_items),
    }
    locs = [l for l in (locations or []) if l]
    if locs:
        run_input["locations"] = locs
    if extra:
        run_input.update(extra)
    return _run_actor(settings.apify_fb_search_actor, run_input, db=db)


# ---------- 2) Facebook Pages Scraper ----------
def run_fb_pages(
    start_urls: list[str],
    max_items: int = 50,
    extra: Optional[dict[str, Any]] = None,
    db: Session | None = None,
) -> dict[str, Any]:
    """主页 URL → 主页完整资料。"""
    urls = [u for u in (start_urls or []) if u]
    if not urls:
        raise ValueError("facebook-pages-scraper 需要至少一个 startUrls")
    run_input: dict[str, Any] = {
        "startUrls": [{"url": u} for u in urls],
        "resultsLimit": int(max_items),
    }
    if extra:
        run_input.update(extra)
    return _run_actor(settings.apify_fb_pages_actor, run_input, db=db)


# ---------- 3) Facebook Posts Scraper ----------
def run_fb_posts(
    start_urls: list[str],
    posts_per_page: int = 10,
    total_limit: Optional[int] = None,
    extra: Optional[dict[str, Any]] = None,
    db: Session | None = None,
) -> dict[str, Any]:
    """按 Page URL 抓帖子。

    输入字段（官方 facebook-posts-scraper）：
      - startUrls: array<{url, resultsLimit?}>  目标主页（可单独限定每页帖子数）
      - resultsLimit: integer  全局总条数上限（部分 actor 版本支持）
    """
    urls = [u for u in (start_urls or []) if u]
    if not urls:
        raise ValueError("facebook-posts-scraper 需要至少一个 startUrls")

    start_url_objs = [{"url": u, "resultsLimit": int(posts_per_page)} for u in urls]
    run_input: dict[str, Any] = {"startUrls": start_url_objs}
    if total_limit:
        run_input["resultsLimit"] = int(total_limit)
    if extra:
        run_input.update(extra)
    return _run_actor(settings.apify_fb_posts_actor, run_input, db=db)


# ---------- 3b) Facebook Profile & Posts (cleansyntax) ----------
def run_fb_profile_posts(
    endpoint: str,
    urls_text: str | None = None,
    ids_text: str | None = None,
    keywords_text: str | None = None,
    max_posts: int = 0,
    start_date: str | None = None,
    end_date: str | None = None,
    extra: Optional[dict[str, Any]] = None,
    db: Session | None = None,
) -> dict[str, Any]:
    """cleansyntax/facebook-profile-posts-scraper：按 endpoint 选用 urls_text / ids_text / keywords_text。

    官方 input-schema 枚举（节选）：
      - profile_posts_by_url, profile_posts, search_posts_by_keyword, details_by_id, ...
    """
    ep = (endpoint or "").strip()
    if not ep:
        raise ValueError("facebook-profile-posts-scraper 需要 endpoint")

    run_input: dict[str, Any] = {
        "endpoint": ep,
        "max_posts": int(max_posts),
    }
    if urls_text and urls_text.strip():
        run_input["urls_text"] = urls_text.strip()
    if ids_text and ids_text.strip():
        run_input["ids_text"] = ids_text.strip()
    if keywords_text and keywords_text.strip():
        run_input["keywords_text"] = keywords_text.strip()
    if start_date:
        run_input["start_date"] = str(start_date).strip()
    if end_date:
        run_input["end_date"] = str(end_date).strip()
    if extra:
        run_input.update(extra)
    return _run_actor(settings.apify_fb_profile_posts_actor, run_input, db=db)


# ---------- 4) Facebook Hashtag Scraper ----------
def run_fb_hashtag(
    hashtags: list[str],
    max_items: int = 50,
    extra: Optional[dict[str, Any]] = None,
    db: Session | None = None,
) -> dict[str, Any]:
    """按 hashtag 抓帖子。

    官方 input-schema 必填字段为 ``keywordList``（不是 hashtags）：
      - keywordList: array<string>  单个词作 hashtag，不要含空格/特殊符号
      - resultsLimit: integer  每个关键词结果上限
    """
    tags = [t.lstrip("#").strip() for t in (hashtags or []) if t and t.strip()]
    if not tags:
        raise ValueError("facebook-hashtag-scraper 需要至少一个 hashtag")
    run_input: dict[str, Any] = {
        "keywordList": tags,
        "resultsLimit": int(max_items),
    }
    if extra:
        run_input.update(extra)
    return _run_actor(settings.apify_fb_hashtag_actor, run_input, db=db)


# ---------- 5) Facebook Search Posts (第三方) ----------
def run_fb_search_posts(
    keywords: list[str],
    max_items: int = 50,
    location_uid: Optional[str] = None,
    search_type: str = "posts",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    recent_posts: bool = False,
    extra: Optional[dict[str, Any]] = None,
    db: Session | None = None,
) -> dict[str, Any]:
    """任意关键词 → 直接搜帖子（第三方 actor）。

    输入字段（scrapeforge/facebook-search-posts，已对齐官方 input schema）：
      - query: string (必填) - 单个查询关键词
      - search_type: posts / pages / groups / people / videos / events  默认 posts
      - max_results: 1-1000  默认 5
      - start_date / end_date: "YYYY-MM-DD"
      - recent_posts: bool  按最新排序
      - location_uid: string  Facebook 内部 location UID（不是国家名字符串）
          如何获取：在 Facebook 搜索某地点 → URL 上会有 ID；
          或调用别的工具（如 apify/facebook-url-to-id）解析。

    本函数：因 actor 只支持单个 query，多关键词时会循环跑并合并 items。
    """
    queries = [k for k in (keywords or []) if k]
    if not queries:
        raise ValueError("facebook-search-posts 需要至少一个关键词")

    per_query_limit = max(1, int(max_items) // len(queries)) if max_items else 5

    merged_items: list[dict[str, Any]] = []
    last_run_id: Optional[str] = None
    last_dataset_id: Optional[str] = None

    for q in queries:
        run_input: dict[str, Any] = {
            "query": q,
            "search_type": search_type or "posts",
            "max_results": int(per_query_limit),
            "recent_posts": bool(recent_posts),
        }
        if location_uid:
            run_input["location_uid"] = str(location_uid)
        if start_date:
            run_input["start_date"] = start_date
        if end_date:
            run_input["end_date"] = end_date
        if extra:
            run_input.update(extra)
        r = _run_actor(settings.apify_fb_search_posts_actor, run_input, db=db)
        merged_items.extend(r.get("items") or [])
        last_run_id = r.get("run_id") or last_run_id
        last_dataset_id = r.get("dataset_id") or last_dataset_id

    return {
        "run_id": last_run_id,
        "dataset_id": last_dataset_id,
        "items": merged_items,
    }


# ---------- 6) Facebook Groups Scraper ----------
def run_fb_groups(
    group_url: str,
    *,
    results_limit: int = 20,
    view_option: str = "CHRONOLOGICAL",
    search_group_keyword: str | None = None,
    search_group_year: str | None = None,
    only_posts_newer_than: str | None = None,
    timeout_secs: int = 600,
    extra: Optional[dict[str, Any]] = None,
    db: Session | None = None,
) -> dict[str, Any]:
    """公开 Facebook 群组 URL → 帖子列表（Apify facebook-groups-scraper）。"""
    url = (group_url or "").strip()
    if not url:
        raise ValueError("facebook-groups-scraper 需要群组 URL (startUrls)")
    run_input: dict[str, Any] = {
        "startUrls": [{"url": url}],
        "viewOption": view_option or "CHRONOLOGICAL",
    }
    if results_limit and int(results_limit) > 0:
        run_input["resultsLimit"] = int(results_limit)
    if search_group_keyword and str(search_group_keyword).strip():
        run_input["searchGroupKeyword"] = str(search_group_keyword).strip()
    if search_group_year and str(search_group_year).strip():
        run_input["searchGroupYear"] = str(search_group_year).strip()
    if only_posts_newer_than and str(only_posts_newer_than).strip():
        run_input["onlyPostsNewerThan"] = str(only_posts_newer_than).strip()
    if extra:
        run_input.update(extra)
    return _run_actor(settings.apify_fb_groups_actor, run_input, timeout_secs=timeout_secs, db=db)


# ---------- 7) Facebook Search Scraper (crawlerbros) ----------
def run_fb_search_cb(
    keywords: list[str],
    search_type: str = "pages",
    max_results: int = 20,
    extra: Optional[dict[str, Any]] = None,
    db: Session | None = None,
) -> dict[str, Any]:
    """关键词 → Pages / People（crawlerbros/facebook-search-scraper）。

    官方 input-schema：
      - searchQueries  array<string>  搜索关键词列表（必填）
      - searchType     string         "pages" | "people"（默认 "pages"）
      - maxResults     integer        每次运行最大结果数（默认 20）
    """
    queries = [k for k in (keywords or []) if k and str(k).strip()]
    if not queries:
        raise ValueError("crawlerbros/facebook-search-scraper 需要至少一个关键词 (searchQueries)")
    run_input: dict[str, Any] = {
        "searchQueries": queries,
        "searchType": search_type or "pages",
        "maxResults": int(max_results),
    }
    if extra:
        run_input.update(extra)
    return _run_actor(settings.apify_fb_search_cb_actor, run_input, db=db)
