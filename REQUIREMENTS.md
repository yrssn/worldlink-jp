# 日本红人 / Facebook 抓取 & 建联系统 需求文档

> 项目代号：`spider_jp_worldlink`
>
> 技术栈：FastAPI + Vue3 + MySQL + Redis + JWT + LangChain + Apify
>
> 运行环境：Conda 虚拟环境

---

## 1. 项目概述

本系统面向"日本市场达人建联"业务场景，核心目标是：

1. 通过 **Apify Facebook Scrapers**（Facebook Search Scraper + Facebook Pages Scraper）根据关键词 / 地址抓取相关 **帖子**；
2. 可选地用 **大模型（LangChain 接入）** 对抓取到的帖子做语义过滤（如：必须是合作邀约类、必须达到一定粉丝/点赞/评论门槛等）；
3. 抓取通过过滤的帖子对应的 **博主主页信息**（Facebook Page）；
4. 人工审核后点击 **"建联"** 按钮，把帖子 + 博主信息存入 **建联模块**，作为"预建联达人"；
5. 建联模块支持权限隔离：不同账号只能看到自己抓取或新增的达人；
6. 字段层面预留 Instagram、TikTok、WeChat、小红书等多平台社交账号字段，便于后续扩展。

---

## 2. 技术栈与运行环境

| 类别 | 选型 | 备注 |
|------|------|------|
| 后端框架 | FastAPI | 异步 API |
| ORM | SQLAlchemy 2.x | + Alembic 做迁移 |
| 数据库 | MySQL 8.x | 业务主存 |
| 缓存 / 队列 | Redis 7.x | 缓存 + 任务队列（可选 RQ / Celery） |
| 鉴权 | JWT (python-jose) | access + refresh token |
| 大模型编排 | LangChain | 适配多家厂商 |
| 抓取服务 | Apify Client | facebook-search-scraper / facebook-pages-scraper |
| 前端框架 | Vue3 + Vite | Composition API |
| UI 组件库 | Element Plus | 中后台风格 |
| 状态管理 | Pinia | |
| 路由 | Vue Router 4 | |
| HTTP 客户端 | Axios | |
| 环境管理 | Conda | `environment.yml` |

---

## 3. 功能模块总览

```
┌──────────────────────────────────────────────────────┐
│                   spider_jp_worldlink                │
├──────────────────────────────────────────────────────┤
│  1. 账号 / 权限模块（auth）                          │
│  2. 大模型配置模块（llm）                            │
│     ├─ 厂商 / 模型 / Key 配置                        │
│     └─ 提示词（关键词）配置                          │
│  3. 抓取器模块（scraper）                            │
│     ├─ Facebook Search Scraper（按关键词/地址抓帖子）│
│     ├─ Facebook Pages Scraper（按主页抓博主）        │
│     ├─ 抓取任务管理（条数/是否启用 AI 分析）         │
│     └─ 帖子库 & 帖子 ↔ 博主 关联                     │
│  4. 建联模块（contact / influencer）                 │
│     ├─ 预建联达人（来源：抓取或手工新增）            │
│     ├─ 多平台社交账号（FB/IG/TT/WX/XHS/...）         │
│     ├─ 帖子-达人关联追溯                             │
│     ├─ 删除（预建联失败可移除）                      │
│     └─ 权限隔离：仅看到自己创建或抓取入库的          │
└──────────────────────────────────────────────────────┘
```

---

## 4. 模块详细需求

### 4.1 账号 / 权限模块（auth）

- 用户注册（管理员开通，默认不开放公开注册）/ 登录 / 修改密码；
- JWT 鉴权：`access_token`（短期） + `refresh_token`（长期，存 Redis 黑/白名单）；
- 角色：`admin`（可看所有） / `user`（只看自己的）；
- 建联模块、抓取任务等业务表都带 `owner_id`，普通用户查询自动按 `owner_id = current_user.id` 过滤；
- 接口：
  - `POST /api/auth/login`
  - `POST /api/auth/refresh`
  - `POST /api/auth/logout`
  - `GET  /api/auth/me`

### 4.2 大模型配置模块（llm）

#### 4.2.1 厂商 / 模型配置（LLM Provider）
- 可配置多家厂商：OpenAI / Azure OpenAI / DeepSeek / 通义 / Claude / 本地 Ollama 等；
- 字段：
  - `provider`（openai / azure / deepseek / ollama / claude / custom）
  - `name`（自定义名称，方便区分）
  - `base_url`（可选，兼容 OpenAI 协议的可填）
  - `api_key`（加密存储）
  - `model`（如 gpt-4o-mini、deepseek-chat 等）
  - `temperature` / `max_tokens` / `extra_params(JSON)`
  - `is_default` 是否默认
  - `enabled` 是否启用
- 通过 LangChain 的 `ChatOpenAI` / `ChatAnthropic` / `ChatOllama` 等适配；
- 不在系统提示词里写死任何业务关键字（避免锁死），系统提示词由"关键词/提示词配置模块"动态拼接。

#### 4.2.2 关键词 / 提示词配置（Prompt Template）
- 用户可创建多套提示词模板，用于不同业务场景（如"招募 KOL"、"美妆类博主"、"东京地区餐饮"）；
- 字段：
  - `name`
  - `description`
  - `system_prompt`（系统提示词，用户自由书写）
  - `keywords`（关键词列表，JSON / 逗号分隔）
  - `filter_rules`（结构化过滤条件，如最低粉丝数、最低点赞数、最低评论数、地区等）
  - `output_schema`（约束 LLM 返回的 JSON 结构，便于解析）
  - `is_active`
- 抓取任务可以选择"使用哪套提示词模板"。

#### 4.2.3 接口（示例）
- `GET /api/llm/providers` 列出可用大模型配置
- `POST /api/llm/providers` 新增
- `PUT /api/llm/providers/{id}`
- `DELETE /api/llm/providers/{id}`
- `POST /api/llm/providers/{id}/test` 连通性测试
- `GET /api/llm/prompts` 提示词模板
- `POST /api/llm/prompts`
- `PUT /api/llm/prompts/{id}`
- `DELETE /api/llm/prompts/{id}`

### 4.3 抓取器模块（scraper）

#### 4.3.0 五种获客维度（任务类型）

> ⚠️ 重要：`apify/facebook-search-scraper` 实际返回的是 Pages，不是 Posts。本系统据此把任务拆成五种。

| task_type | Actor | 输入 | 输出 | 工作流 | 费用 | 适用场景 |
|-----------|-------|------|------|--------|------|----------|
| `fb_search` | apify/facebook-search-scraper | categories + locations | Pages | 一步：抓 Page → [AI 评估 Page] → 待审核 | ~$10/1000 pages | 关键词+地区直接拿 Page，最省钱 |
| `fb_pages` | apify/facebook-pages-scraper | startUrls | Pages | 一步：抓 Page 详情 → [AI 评估] → 待审核 | ~$6.6/1000 pages | 已知 URL 批量入库 |
| `fb_posts_by_page` | facebook-posts-scraper + facebook-pages-scraper | startUrls + posts_per_page | Posts → Pages | Step1 抓帖子 → Step2 AI 评估帖子 → Step3 聚合作者 → Step4 抓主页 → 待审核 | posts $10/1000 + pages $6.6/1000 + LLM | 已知主页，要看帖子内容判断 |
| `fb_posts_by_hashtag` | facebook-hashtag-scraper + facebook-pages-scraper | hashtags | Posts → Pages | 同上，但用 hashtag 找帖子 | posts $10/1000 + pages $6.6/1000 + LLM | 按话题找活跃博主 |
| `fb_posts_by_search` | scrapeforge/facebook-search-posts + facebook-pages-scraper | keywords | Posts → Pages | 同上，但用任意关键词搜帖子 | posts ~$10-15/1000 + pages $6.6/1000 + LLM | 关键词最灵活；第三方 actor |

**两阶段流程（仅 `fb_posts_*` 三种任务）**：

```
Step1: 抓帖子（按主页 / hashtag / 任意关键词）
        ↓ 入 posts 表（带 task_id, owner_id）
Step2: 若启用 AI → 逐条调用 LLM 评估帖子（text/likes/comments/...）
        ↓ 标记 ai_passed / ai_score / ai_reason
Step3: 聚合"AI 通过"帖子的 author_url 去重（不超过 page_limit）
Step4: 用 facebook-pages-scraper 抓这些主页详情
        ↓ 写入 task.extra_input["page_results"]，每条带 _source_post_ids
Step5: 前端【建联】→ 入 Influencer + 把源帖子全部 influencer_id 回写
```

**费用控制**：
- `max_items`：第一步上限（actor `resultsLimit`）
- `posts_per_page`：fb_posts_by_page 每个主页抓多少条帖子
- `page_limit`：AI 过滤后第二步抓主页的 URL 数上限

#### 4.3.1 抓取任务（ScrapeTask）
- 类型：见上表 5 种
- 关键字段：
  - `task_type`
  - `keywords` / `address` / `start_urls` （根据 type 填）
  - `max_items`（抓取条数）
  - `enable_ai_filter`（是否启用 AI 过滤）
  - `llm_provider_id`（启用 AI 时绑定的大模型）
  - `prompt_template_id`（启用 AI 时绑定的提示词模板）
  - `status`（pending / running / success / failed / partial）
  - `apify_run_id`（关联 Apify run）
  - `result_count` / `filtered_count` / `error`
  - `owner_id` 创建人
- 接口：
  - `POST /api/scraper/tasks` 创建任务（异步触发）
  - `GET  /api/scraper/tasks` 任务列表（按 owner 过滤）
  - `GET  /api/scraper/tasks/{id}` 任务详情 + 进度
  - `POST /api/scraper/tasks/{id}/cancel`
  - `GET  /api/scraper/tasks/{id}/posts` 抓到的帖子（含 AI 过滤结果）

#### 4.3.2 帖子库（Post）
- 帖子表存储 Facebook Search Scraper 抓回来的结果；
- 字段（参考 apify facebook-search-scraper 输出）：
  - `post_id`（FB pageId+postId）
  - `url`
  - `text` / `content`
  - `created_time`
  - `likes` / `comments_count` / `shares` / `reactions`
  - `media`（JSON：图片/视频列表）
  - `author_name` / `author_url` / `author_page_id`
  - `keywords_hit`（命中的关键词）
  - `ai_score` / `ai_passed`（AI 过滤是否通过）
  - `ai_reason`（AI 给出的过滤理由）
  - `raw`（原始 JSON，方便后续兼容字段变化）
  - `task_id` 来源抓取任务
  - `influencer_id` 关联到的达人（建联后回写）
  - `owner_id`

#### 4.3.3 主页抓取（Page Profile / Influencer Source）
- AI 过滤通过后，自动 / 手动触发 Pages Scraper，按帖子的 `author_url` 抓取博主主页；
- Pages Scraper 字段对照（apify facebook-pages-scraper）：
  - Page title / Page URL
  - Address / Contact details (phone)
  - Website / Messenger link
  - Intro (bio / description)
  - Number of check-ins and mentions
  - Rating / Rating count
  - Page creation date
  - Page Ad Library ID / Ad status
  - Number of followers / Number of likes
  - Categories / Profile and cover photo URL
- 抓回来的资料先存入"待审核博主"队列；
- 列表行后面提供 **【建联】** 按钮 → 走 4.4 流程入库；

#### 4.3.4 工作流（核心）
```
用户创建 Search 任务（关键词 + 是否启用 AI）
        ▼
Apify Facebook Search Scraper 抓帖子
        ▼
入库 Post（task_id 关联，owner_id = 当前用户）
        ▼
若启用 AI：调用 LangChain，使用绑定的提示词模板进行打分/过滤
        ▼ 通过的帖子
聚合作者 Page URL，去重
        ▼
Apify Facebook Pages Scraper 抓博主资料
        ▼
入库到 "待审核博主" 列表（同 owner）
        ▼
人工审核：列表每行有【建联】按钮
        ▼
点击建联 → 4.4 流程
```

### 4.4 建联模块（contact / influencer）

#### 4.4.1 达人（Influencer）
- 来源：
  - 抓取后人工点击【建联】入库；
  - 手工新增；
- **入库前去重**：根据「Facebook page_id」/「page_url」/「主邮箱」等关键字段查重，存在则不再新增，只把当前帖子追加关联到已有达人上；
- 字段（基础）：
  - `id`
  - `display_name`（昵称 / 页面名称）
  - `real_name`（备注用真实姓名，可空）
  - `country` / `region` / `city`（默认日本相关）
  - `language`
  - `categories`（分类标签 JSON）
  - `bio`
  - `avatar_url` / `cover_url`
  - `email` / `phone` / `messenger`
  - `address`
  - `website`
  - `rating` / `rating_count`
  - `page_created_at`
  - `ad_library_id` / `ad_status`
  - `followers` / `likes`
  - `checkins_mentions`
  - `notes`（自定义备注，建联进度、合作意向等）
  - `status`（pre_contact / contacting / signed / dropped）
  - `owner_id`
- 社交账号字段（多平台，单独一张表 `InfluencerSocialAccount` 1:N，便于未来扩展）：
  - `platform` 枚举：`facebook` / `instagram` / `tiktok` / `youtube` / `twitter` / `wechat` / `xiaohongshu` / `line` / `other`
  - `handle`（用户名）
  - `url`
  - `followers`
  - `extra`（JSON，平台特有字段）

#### 4.4.2 帖子-达人关联（PostInfluencerLink）
- 一个达人可关联多条来源帖子；
- 一条帖子可能只对应一个达人（作者）；
- 在建联模块的达人详情里能看到："此达人来自哪些抓取任务、哪些帖子"。

#### 4.4.3 权限
- 普通账号：仅能看到 `owner_id == self.id` 的达人 / 帖子 / 任务；
- 管理员：可看全部；
- 抓取入库的达人 `owner_id` = 触发任务的用户；
- 手工新增的达人 `owner_id` = 当前登录用户；

#### 4.4.4 接口
- `GET    /api/influencers` 列表（带筛选：平台、状态、关键词、粉丝区间……）
- `POST   /api/influencers` 手工新增
- `GET    /api/influencers/{id}` 详情（含社交账号 + 来源帖子）
- `PUT    /api/influencers/{id}` 编辑
- `DELETE /api/influencers/{id}` 删除（仅预建联状态可直接删）
- `POST   /api/influencers/from-scrape` 从抓取的「待审核博主」点击建联 → 入库（含查重）
- `POST   /api/influencers/{id}/social-accounts` 添加社交账号
- `DELETE /api/influencers/{id}/social-accounts/{sid}`

---

## 5. 数据模型 ER 草图

```
User 1───* ScrapeTask 1───* Post *───1 Influencer 1───* InfluencerSocialAccount
                                  ▲
                                  │ owner_id
User 1────────────────────────────┘

User 1───* LlmProvider
User 1───* PromptTemplate
```

主要表：
- `users`
- `llm_providers`
- `prompt_templates`
- `scrape_tasks`
- `posts`
- `influencers`
- `influencer_social_accounts`
- `post_influencer_links`（如需要 N:M 可拆，目前先用 `posts.influencer_id` 外键）

---

## 6. 目录结构（规划）

```
spider_jp_worldlink/
├── REQUIREMENTS.md
├── README.md
├── environment.yml                     # conda 环境
├── backend/
│   ├── pyproject.toml / requirements.txt
│   ├── alembic.ini
│   ├── alembic/                        # 迁移脚本
│   ├── .env.example
│   └── app/
│       ├── main.py                     # FastAPI 入口
│       ├── core/                       # 配置、安全、JWT、日志、依赖
│       │   ├── config.py
│       │   ├── security.py
│       │   ├── deps.py
│       │   └── redis_client.py
│       ├── db/
│       │   ├── base.py                 # Base = declarative_base
│       │   ├── session.py              # engine / SessionLocal
│       │   └── init_db.py
│       ├── models/                     # SQLAlchemy ORM
│       │   ├── user.py
│       │   ├── llm.py
│       │   ├── prompt.py
│       │   ├── scrape.py
│       │   ├── post.py
│       │   ├── influencer.py
│       │   └── social_account.py
│       ├── schemas/                    # Pydantic
│       │   ├── user.py
│       │   ├── llm.py
│       │   ├── prompt.py
│       │   ├── scrape.py
│       │   ├── post.py
│       │   └── influencer.py
│       ├── api/
│       │   └── v1/
│       │       ├── api.py              # router 聚合
│       │       ├── auth.py
│       │       ├── llm.py
│       │       ├── prompt.py
│       │       ├── scrape.py
│       │       ├── post.py
│       │       └── influencer.py
│       └── services/
│           ├── auth_service.py
│           ├── llm_service.py          # LangChain 适配
│           ├── apify_service.py        # Apify 客户端封装
│           ├── scrape_service.py       # 任务编排
│           ├── ai_filter_service.py    # AI 过滤帖子
│           └── influencer_service.py   # 查重 / 建联
└── frontend/
    ├── package.json
    ├── vite.config.ts
    ├── index.html
    ├── tsconfig.json
    └── src/
        ├── main.ts
        ├── App.vue
        ├── router/
        ├── store/                      # Pinia
        ├── api/                        # axios 封装
        ├── layouts/
        ├── views/
        │   ├── login/
        │   ├── llm/                    # 大模型配置
        │   ├── prompt/                 # 关键词/提示词
        │   ├── scraper/                # 抓取任务
        │   ├── posts/                  # 抓取的帖子列表
        │   ├── review/                 # 待审核博主（带建联按钮）
        │   └── influencer/             # 建联模块
        └── components/
```

---

## 7. 里程碑

| 阶段 | 目标 | 产出 |
|------|------|------|
| M0 | 需求文档 & 骨架 | 本文件、可启动的 FE/BE 骨架 |
| M1 | 鉴权 + 大模型配置 + 提示词 | 完整 CRUD + 联通性测试 |
| M2 | Apify 抓取任务 + 帖子库 | 抓帖子、看帖子、列表 |
| M3 | AI 过滤 + Pages 抓取 + 待审核 | 过滤、抓博主、待审核列表 |
| M4 | 建联模块（查重 / 关联 / 权限） | 完整建联流程 |
| M5 | 多平台社交账号扩展 + 优化 | IG/TT/WX/XHS 字段接入 |

---

## 8. 备注 & 后续可扩展

- 抓取任务执行可选 Celery / RQ / FastAPI BackgroundTasks，**当前骨架先用 BackgroundTasks**，后续可平滑替换；
- 大模型调用统一走 `LlmService.get_chat_model(provider_id)` 返回 LangChain Chat Model，方便切换；
- 所有「敏感字段」（API Key）入库前用对称加密（Fernet），密钥放环境变量；
- 后续接入 Instagram / TikTok 等抓取器时，只需新增 `task_type` + 相应 service，不动核心数据模型。

