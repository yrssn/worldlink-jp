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

3) ``run_fb_posts``  Page URL → 帖子
   - Actor: apify/facebook-posts-scraper
   - Input: startUrls=[{url}, ...], resultsLimit
            （也支持每个主页限制条数：每个 startUrl 自带 resultsLimit）
   - Output: text/likes/comments/shares/reactions/media/url/author/...
   - 费用: ~$10 / 1000 posts
   - Docs: https://apify.com/apify/facebook-posts-scraper

4) ``run_fb_hashtag``  hashtag → 帖子
   - Actor: apify/facebook-hashtag-scraper
   - Input: hashtags=[ "tokyo", "cafe" ]  (不带 # 前缀), resultsLimit
   - Output: 与 posts-scraper 类似
   - 费用: ~$10 / 1000 posts
   - Docs: https://apify.com/apify/facebook-hashtag-scraper

5) ``run_fb_search_posts``  任意关键词 → 帖子 (第三方 actor，更灵活)
   - Actor: scrapeforge/facebook-search-posts
   - Input: searchQueries=[...], resultsLimit
   - Output: post 数据
   - 费用: ~$10-15 / 1000 posts (按 actor 主页为准)
   - Docs: https://apify.com/scrapeforge/facebook-search-posts
"""
from __future__ import annotations

from typing import Any, Optional

from loguru import logger

from app.core.config import settings


# ---------- 内部工具 ----------
def _get_client():
    if not settings.apify_token:
        raise RuntimeError("APIFY_TOKEN 未配置")
    from apify_client import ApifyClient

    return ApifyClient(settings.apify_token)


def _run_actor(actor_id: str, run_input: dict[str, Any]) -> dict[str, Any]:
    """统一调用 Actor 并把 dataset 全部拉回来。"""
    client = _get_client()
    logger.info("[Apify] Run {} input={}", actor_id, run_input)
    run = client.actor(actor_id).call(run_input=run_input)
    if not run:
        raise RuntimeError(f"Apify run {actor_id} returned empty")

    dataset_id = run.get("defaultDatasetId")
    items: list[dict[str, Any]] = []
    if dataset_id:
        items = list(client.dataset(dataset_id).iterate_items())

    logger.info("[Apify] Run {} done. items={}", actor_id, len(items))
    return {
        "run_id": run.get("id"),
        "dataset_id": dataset_id,
        "items": items,
    }


# ---------- 1) Facebook Search Scraper ----------
def run_fb_search(
    keywords: list[str] | None = None,
    locations: list[str] | None = None,
    max_items: int = 50,
    extra: Optional[dict[str, Any]] = None,
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
    return _run_actor(settings.apify_fb_search_actor, run_input)


# ---------- 2) Facebook Pages Scraper ----------
def run_fb_pages(
    start_urls: list[str],
    max_items: int = 50,
    extra: Optional[dict[str, Any]] = None,
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
    return _run_actor(settings.apify_fb_pages_actor, run_input)


# ---------- 3) Facebook Posts Scraper ----------
def run_fb_posts(
    start_urls: list[str],
    posts_per_page: int = 10,
    total_limit: Optional[int] = None,
    extra: Optional[dict[str, Any]] = None,
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
    return _run_actor(settings.apify_fb_posts_actor, run_input)


# ---------- 4) Facebook Hashtag Scraper ----------
def run_fb_hashtag(
    hashtags: list[str],
    max_items: int = 50,
    extra: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """按 hashtag 抓帖子。

    输入字段（官方 facebook-hashtag-scraper）：
      - hashtags: array<string>  不带 # 前缀，例如 ["tokyo", "cafe"]
      - resultsLimit: integer
    """
    tags = [t.lstrip("#").strip() for t in (hashtags or []) if t and t.strip()]
    if not tags:
        raise ValueError("facebook-hashtag-scraper 需要至少一个 hashtag")
    run_input: dict[str, Any] = {
        "hashtags": tags,
        "resultsLimit": int(max_items),
    }
    if extra:
        run_input.update(extra)
    return _run_actor(settings.apify_fb_hashtag_actor, run_input)


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
        r = _run_actor(settings.apify_fb_search_posts_actor, run_input)
        merged_items.extend(r.get("items") or [])
        last_run_id = r.get("run_id") or last_run_id
        last_dataset_id = r.get("dataset_id") or last_dataset_id

    return {
        "run_id": last_run_id,
        "dataset_id": last_dataset_id,
        "items": merged_items,
    }
