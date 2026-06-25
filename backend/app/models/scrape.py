from __future__ import annotations

import enum

from sqlalchemy import JSON, Boolean, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class ScrapeTaskType(str, enum.Enum):
    """抓取任务类型。

    五种获客维度，对应不同 Apify Actor 与不同业务流程：

    - ``fb_search``：
        Actor = apify/facebook-search-scraper
        机制 = 关键词(categories) + 位置(locations) → 直接返回匹配的 Pages
        流程 = 一步到位，[可选 AI 过滤 Page 资料] → 待审核博主 → 建联
        费用 ≈ $10 / 1000 pages
        适用 = 只关心"某领域+某地区"有哪些 Page，最省钱

    - ``fb_pages``：
        Actor = apify/facebook-pages-scraper
        机制 = 给定 Page URL → 抓主页完整资料
        流程 = 已知 URL 批量入库/补全 → [可选 AI] → 建联
        费用 ≈ $6.6 / 1000 pages
        适用 = 手上已有一批主页 URL（例如从其他渠道导出）

    - ``fb_posts_by_page``：
        Actor1 = cleansyntax/facebook-profile-posts-scraper  （主页 URL / ID / 关键词搜帖）
        Actor2 = apify/facebook-pages-scraper
        机制 = 给定主页 URL（或关键词 / profile id）→ 抓帖子 → AI 看帖子内容打分
              → 通过的帖子对应的 author Page URL 去重 → 抓主页详情 → 建联
        费用 ≈ profile-posts ~$6/1000 results + pages $6.6/1000 + LLM token
        适用 = 已知 Page 或想按关键词搜公开帖，再评估作者是否契合

    - ``fb_posts_by_hashtag``：
        Actor1 = apify/facebook-hashtag-scraper  （hashtag 找帖子）
        Actor2 = apify/facebook-pages-scraper
        机制 = 给定 hashtag(不含 #) → 找带该 hashtag 的帖子 → AI 评估
              → 提取作者 Page URL → 抓主页详情 → 建联
        费用 ≈ posts $10/1000 + pages $6.6/1000 + LLM
        适用 = 按话题获客（"#tokyocafe"、"#美妆"），相对官方稳定

    - ``fb_posts_by_search``：
        Actor1 = scrapeforge/facebook-search-posts  （任意关键词搜帖子，第三方）
        Actor2 = apify/facebook-pages-scraper
        机制 = 任意关键词 → 直接搜匹配帖子 → AI 评估
              → 提取作者 Page URL → 抓主页详情 → 建联
        费用 ≈ posts ~$10-15/1000 + pages $6.6/1000 + LLM
        适用 = 不想被 hashtag 限制，关键词最灵活；但第三方稳定性弱一些

    - ``ig_profile``：
        Actor = apify/instagram-profile-scraper
        机制 = 给定 Instagram 用户名（或主页 URL）→ 抓取公开主页资料
              （fullName / biography / followersCount / 头像 / 外链 / 最新帖子等）
        流程 = 一步到位，[可选 AI 过滤主页资料] → 待审核博主 → 建联（Instagram 平台账号）
        费用 ≈ 见 actor 定价页
        适用 = 已有一批 IG 用户名 / 主页链接，想直接拉资料进建联模块
    """

    fb_search = "fb_search"
    fb_pages = "fb_pages"
    fb_posts_by_page = "fb_posts_by_page"
    fb_posts_by_hashtag = "fb_posts_by_hashtag"
    fb_posts_by_search = "fb_posts_by_search"
    fb_posts_scraper = "fb_posts_scraper"
    fb_search_cb = "fb_search_cb"
    ig_profile = "ig_profile"


class ScrapeTaskStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    success = "success"
    failed = "failed"
    partial = "partial"
    canceled = "canceled"


class ScrapeTask(Base, TimestampMixin):
    __tablename__ = "scrape_tasks"

    name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    task_type: Mapped[ScrapeTaskType] = mapped_column(Enum(ScrapeTaskType), nullable=False)
    status: Mapped[ScrapeTaskStatus] = mapped_column(
        Enum(ScrapeTaskStatus), default=ScrapeTaskStatus.pending, nullable=False
    )

    # ===== 输入参数（按 task_type 不同含义不同）=====
    # keywords / hashtags / start_urls 都是数组；hashtags 单独留一列，不和关键词混淆
    keywords: Mapped[list | None] = mapped_column(JSON, nullable=True)
    hashtags: Mapped[list | None] = mapped_column(JSON, nullable=True)
    address: Mapped[str | None] = mapped_column(String(255), nullable=True)  # 兼容旧字段，新版用 extra_input.locations
    start_urls: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # 一次任务抓帖子/Pages 的上限（actor resultsLimit）
    max_items: Mapped[int] = mapped_column(Integer, default=50, nullable=False)
    # 每个 Page 抓多少条帖子（仅 fb_posts_by_page 使用）
    posts_per_page: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    # 第二阶段抓主页的上限（即 AI 过滤后去重的 Page URL 数）
    page_limit: Mapped[int] = mapped_column(Integer, default=50, nullable=False)
    extra_input: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # AI 过滤相关
    enable_ai_filter: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    llm_provider_id: Mapped[int | None] = mapped_column(
        ForeignKey("llm_providers.id", ondelete="SET NULL"), nullable=True
    )
    prompt_template_id: Mapped[int | None] = mapped_column(
        ForeignKey("prompt_templates.id", ondelete="SET NULL"), nullable=True
    )

    # Apify run 追踪
    apify_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    apify_dataset_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # 结果统计
    result_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    filtered_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
