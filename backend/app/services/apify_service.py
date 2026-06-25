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

import re
import threading
from typing import Any, Optional

from loguru import logger
from sqlalchemy.orm import Session

from app.core.config import settings
from app.services.apify_key_rotation import apify_key_rotation

# 全局排队锁：所有 Apify Actor 调用共用此信号量，同时最多运行 1 个（防止超出免费计划 8192 MB 总内存限额）
_apify_semaphore = threading.Semaphore(1)


# ---------- 内部工具 ----------
def _candidate_tokens(db: Session | None = None) -> list[tuple[str, int | None]]:
    """构造本次调用要尝试的 (token, key_id) 列表。

    - 有数据库 Key 时：按「未用尽优先、默认优先」排序，依次尝试，支持自动轮转。
    - 没有数据库 Key 时：回退到 ``settings.apify_token``（key_id=None，不参与轮转）。
    """
    tokens: list[tuple[str, int | None]] = []
    if db is not None:
        for key in apify_key_rotation.get_candidate_keys(db):
            if key.token:
                tokens.append((key.token, key.id))
    if tokens:
        return tokens
    if settings.apify_token:
        return [(settings.apify_token, None)]
    raise RuntimeError(
        "未配置可用的 Apify Token（请在「Apify Key 管理」中添加并设置默认 Key）"
    )


def _make_client(token: str):
    from apify_client import ApifyClient

    return ApifyClient(token)


def _resolve_token(db: Session | None = None) -> str:
    """返回首选 Apify Token（默认 / 未用尽优先），无可用时回退 settings。

    保留此函数仅为兼容旧调用；实际抓取走 :func:`_run_actor` 的轮转逻辑。
    """
    return _candidate_tokens(db)[0][0]


def _get_client(db: Session | None = None):
    return _make_client(_resolve_token(db))


def _call_actor_once(
    token: str,
    actor_id: str,
    run_input: dict[str, Any],
    timeout_secs: int,
    memory_mbytes: int,
) -> dict[str, Any]:
    """用指定 token 跑一次 Actor 并把 dataset 全部拉回来。失败抛 RuntimeError。"""
    client = _make_client(token)
    logger.info(
        "[Apify] Start {} timeout={}s memory={}MB input={}",
        actor_id, timeout_secs, memory_mbytes, run_input,
    )
    try:
        # wait_secs：客户端最长等待时间；timeout_secs：Actor 单次运行上限
        # memory_mbytes：限制单次 Actor 内存占用，避免超出免费计划总额（8192 MB）
        run = client.actor(actor_id).call(
            run_input=run_input,
            wait_secs=timeout_secs,
            timeout_secs=timeout_secs,
            memory_mbytes=memory_mbytes,
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
        actor_id, run_id, status or "SUCCEEDED", len(items),
    )
    return {
        "run_id": run_id,
        "dataset_id": dataset_id,
        "items": items,
        "status": status or "SUCCEEDED",
    }


def _run_actor(
    actor_id: str,
    run_input: dict[str, Any],
    *,
    timeout_secs: int = 600,
    memory_mbytes: int = 1024,
    db: Session | None = None,
) -> dict[str, Any]:
    """统一调用 Actor（全局排队，一次只跑一个）。

    遇到额度耗尽 / 认证失败时，自动把该 Key 标记为已用尽并切换到下一个可用 Key 重试；
    其余错误（输入错误、内存超限、超时等）不轮转，原样抛出。
    """
    candidates = _candidate_tokens(db)
    queue_timeout = timeout_secs + 60  # 等锁最长比 Actor 超时多 60s
    logger.info(
        "[Apify] Queued {} (waiting for semaphore, timeout={}s memory={}MB, keys={})",
        actor_id, timeout_secs, memory_mbytes, len(candidates),
    )
    acquired = _apify_semaphore.acquire(timeout=queue_timeout)
    if not acquired:
        raise RuntimeError(
            f"Apify 任务排队超时（等待 {queue_timeout}s 仍未获得执行槽），"
            "请稍后重试或等待前序任务完成"
        )
    try:
        last_err: Exception | None = None
        for idx, (token, key_id) in enumerate(candidates):
            try:
                return _call_actor_once(
                    token, actor_id, run_input, timeout_secs, memory_mbytes
                )
            except RuntimeError as e:
                msg = str(e)
                kind = apify_key_rotation.classify_error(msg)
                # 只有数据库 Key 且属于额度 / 认证类错误，才标记并轮转
                if key_id is not None and kind in ("exhausted", "auth"):
                    apify_key_rotation.mark_exhausted(db, key_id, reason=msg[:150])
                    last_err = e
                    if idx + 1 < len(candidates):
                        logger.warning(
                            "[Apify] Key#{} {}，切换到下一个 Key 重试：{}",
                            key_id, kind, msg,
                        )
                        continue
                    logger.error("[Apify] 所有 Key 均不可用，最后错误：{}", msg)
                # 非 Key 类错误，或已无可切换的 Key：直接抛出
                raise
        # 理论上不会走到这里（candidates 至少 1 个）
        raise last_err or RuntimeError("没有可用的 Apify Key")
    finally:
        _apify_semaphore.release()


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


# ---------- 8) Instagram Profile Scraper ----------
def normalize_ig_username(value: str) -> str | None:
    """把 IG 用户名 / 主页 URL 归一化为纯用户名（actor 也接受数字 id）。

    支持：``nasa`` / ``@nasa`` / ``https://www.instagram.com/nasa/`` /
    ``instagram.com/nasa?hl=en``。无法识别时返回 None。
    """
    if not value or not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if "instagram.com" in s.lower():
        m = re.search(r"instagram\.com/+([^/?#]+)", s, flags=re.IGNORECASE)
        if not m:
            return None
        s = m.group(1)
    s = s.lstrip("@").strip().strip("/")
    if not s or s.lower() in {"p", "reel", "reels", "explore", "stories"}:
        return None
    return s


def run_ig_profile(
    usernames: list[str],
    include_about: bool = False,
    extra: Optional[dict[str, Any]] = None,
    db: Session | None = None,
) -> dict[str, Any]:
    """Instagram 用户名（或主页 URL）→ 主页公开资料（apify/instagram-profile-scraper）。

    官方 input-schema：
      - usernames: array<string>  用户名列表（也支持数字 id），必填
      - includeAboutSection: boolean  额外抓 about 信息（付费功能，默认 False）
    """
    names: list[str] = []
    for u in usernames or []:
        n = normalize_ig_username(u)
        if n and n not in names:
            names.append(n)
    if not names:
        raise ValueError("instagram-profile-scraper 需要至少一个用户名或主页 URL")
    run_input: dict[str, Any] = {"usernames": names}
    if include_about:
        run_input["includeAboutSection"] = True
    if extra:
        run_input.update(extra)
    return _run_actor(settings.apify_ig_profile_actor, run_input, db=db)
