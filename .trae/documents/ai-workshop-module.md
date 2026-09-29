# AI 工坊模块（Agent 密钥接入 + 权限隔离 + 自动存数据）实施计划

## Context（背景与目标）

参考 Gin-Vue-Admin 的「AI 工坊」，在本项目做一套贴合自身 RBAC 的 Agent 接入模块：

1. **给每个用户暴露密钥**：用户在 Web 端自助创建/吊销 API Key（`skjw-...`，只显示一次，库存哈希）。
2. **外部智能体（Codex / Claude Code / 任意脚本）接入**：提供 **MCP Streamable HTTP** 端点（主流 Agent 原生支持）+ **普通 REST** 端点（兜底），认证方式统一为 API Key。
3. **权限隔离（核心诉求）**：Agent 的每次调用都以「密钥属主用户」身份执行，查询走现有 `owner_filter / visible_owner_ids`，写入数据 `owner_id` 记属主 —— 普通 user 的 key 只能看/写自己的数据，超管/`data_scope=all` 的 key 可见全部，与 Web 端行为完全一致。
4. **自动存数据**：`upsert_influencer` 工具按 owner 维度去重（复用 `influencer_service.find_duplicate`），存在则补全更新、不存在则新建，杜绝 Agent 重复灌数据。
5. **调用审计**：记录每次 Agent 调用（工具名/状态/结果摘要/错误），前端可见。

工具范围（本期）：达人查询/详情/upsert + 平台/国家字典 + whoami（告知 Agent 自身数据范围）。后续可按同一模式扩展更多工具（见文末「扩展路线」）。

## 后端改动

### 1. 新模型 `backend/app/models/ai_workshop.py`
- `AiApiKey(ai_api_keys)`：`owner_id`(FK users, CASCADE, idx)、`name`、`key_prefix`(显示用前 12 位)、`key_hash`(sha256, unique idx)、`is_active`、`expires_at`、`last_used_at`、`last_used_ip`。
- `AiApiCallLog(ai_api_call_logs)`：`key_id`(FK, idx)、`owner_id`(idx)、`action`、`status`(ok/error)、`error`(Text)、`detail`(JSON 摘要：参数摘要/结果数/影响到的 influencer_id)。
- 继承 `Base, TimestampMixin`（[base.py](e:\桌面归档\spider_jp_worldlink\backend\app\db\base.py)）。
- 在 [init_db.py](e:\桌面归档\spider_jp_worldlink\backend\app\db\init_db.py) 顶部追加模型 import（与其他模型一致），dev 启动 `create_all` 自动建表。

### 2. 迁移 `backend/alembic/versions/017_add_ai_workshop.py`
- `revision="017"`, `down_revision="016"`；仿 016 先 `inspector.has_table` 幂等判断再 `create_table`（列定义与模型一致）。

### 3. 密钥认证依赖 `backend/app/core/ai_auth.py`
- `extract_api_key(request)`：`Authorization: Bearer <key>` / `X-API-Key` / `?api_key=` 三种取法。
- `get_ai_agent(db, request)` 依赖：sha256 查 `key_hash` → 校验 `is_active`、`expires_at`、属主 `is_active` → 返回 `(user, key)`，失败 401。节流更新 `last_used_at`（>60s 才写库）。
- 注意：`permission_guard` 对无 JWT 的请求直接放行（[permission_guard.py](e:\桌面归档\spider_jp_worldlink\backend\app\core\permission_guard.py) L122-124），Agent 用 API Key 走自有认证，互不干扰。

### 4. 服务层 `backend/app/services/ai_workshop.py`
- Key 生成/校验/CRUD 辅助 + `log_call(...)`。
- 工具实现（全部以 key 属主 `User` 执行）：
  - `search_influencers(db, user, ...)`：`owner_filter(db.query(Influencer), Influencer, user)` + keyword/platform/country/status 过滤 + 软删除过滤，返回紧凑字段（id/display_name/平台/url/粉丝/email/phone/country/status/progress）。
  - `get_influencer(db, user, id)`：`can_view` 校验。
  - `upsert_influencer(db, user, payload)`：按 `find_duplicate(db, owner_id=user.id, ...)`（[influencer_service.py L166](e:\桌面归档\spider_jp_worldlink\backend\app\services\influencer_service.py#L166)）去重 → 命中则补全空字段/更新，未命中则新建（`owner_id=user.id`、`source=manual`），并 `upsert_social_account` 思路落账号维度（platform/url/handle/followers/page_id/author_id 等）。只写属主自己的数据，绝不改他人记录。
  - `list_platforms`（BitBrowserPlatform + SocialPlatform 枚举）、`list_countries`（SHARED 表，直接查）、`whoami`（用户名 + 数据范围 own/all + 可见人数）。

### 5. API 路由
- `backend/app/api/v1/ai_workshop.py`（Web 端，JWT + 菜单权限）：
  - `GET/POST /ai/keys`、`PUT/DELETE /ai/keys/{id}`（只能操作自己的 key）；`POST` 返回完整明文 key（仅此一次）。
  - `GET /ai/logs`：自己的调用记录，分页，可按 key_id 过滤。
- `backend/app/api/v1/ai_agent.py`（Agent REST 兜底，API Key）：
  - `POST /ai/agent/influencers/search`、`GET /ai/agent/influencers/{id}`、`POST /ai/agent/influencers/upsert`。
- `backend/app/api/v1/ai_mcp.py`（MCP Streamable HTTP）：
  - `POST /ai/mcp`：JSON-RPC，支持 `initialize` / `notifications/initialized`(202) / `ping` / `tools/list` / `tools/call`；响应 `application/json`；无状态（不下发 Mcp-Session-Id）；未认证 HTTP 401。GET/DELETE → 405。
  - 5 个工具与 REST 同一服务层，`tools/call` 结果为 `content:[{type:"text", text: JSON}]`；调用写审计日志。
- [api.py](e:\桌面归档\spider_jp_worldlink\backend\app\api\v1\api.py) 注册三个 router。

### 6. 菜单种子 [core/rbac.py](e:\桌面归档\spider_jp_worldlink\backend\app\core\rbac.py)
- `MENU_SEEDS` 新增目录节点 `ai`「AI 工坊」(icon=MagicStick)，子菜单 `ai:workshop`「Agent 接入」path=`/ai/workshop`，`api_prefixes=["/api/v1/ai/keys", "/api/v1/ai/logs"]`。
- 普通用户通过 `DEFAULT_USER_MENU_CODES` 自动获得；`init_db → seed_rbac` 重启即自动落库。
- `/ai/mcp`、`/ai/agent` 不配 api_prefixes → 不走菜单校验，由 API Key 认证兜底。

## 前端改动

- `frontend/src/api/aiWorkshop.ts`：Key/Log 类型 + CRUD（仿 [apifyKey.ts](e:\桌面归档\spider_jp_worldlink\frontend\src\api\apifyKey.ts)）。
- `frontend/src/views/ai/WorkshopView.vue`（仿现有 el-card + el-table 页面风格）：
  - **密钥管理**：列表（名称/前缀/启用开关/过期时间/最近使用/操作），新建弹窗（名称+可选过期时间）→ 创建成功弹窗展示完整密钥（可复制 + 「仅显示一次」警示）。
  - **Agent 接入说明**：MCP 端点地址 + Codex `config.toml` 片段、Claude Code `claude mcp add` 命令、通用 curl 示例（search/upsert）。
  - **调用记录**：最近调用表格（时间/密钥/工具/状态/摘要/错误）。
- [router/index.ts](e:\桌面归档\spider_jp_worldlink\frontend\src\router\index.ts) 新增 `ai/workshop` 路由（meta.code=`ai:workshop`）。

## 关键设计取舍

- 密钥只存 sha256 哈希，创建时一次性返回明文（业界标准做法）。
- Agent 身份 = key 属主这个「真实 User」，数据范围复用 `rbac_service.visible_owner_ids`，与 Web 端语义零偏差（这就是"按用户权限"的保证）。
- upsert 只在属主自己名下查重/更新，不跨用户改数据（与 Web 端新建行为一致，行为可预期）。
- 无状态 MCP（不下发 session id），Codex/Claude/Cursor 均可直接接。

## 验证方式（不跑测试框架，手工验证）

1. 启动后端（dev 自动建表 + 菜单种子落库），登录 Web → 出现「AI 工坊」菜单。
2. 创建密钥 → 复制；`curl -H "Authorization: Bearer skjw-xxx" POST /api/v1/ai/agent/influencers/search` 验证查询。
3. `curl ... /upsert` 提交一条新达人 → Web「建联达人」列表可见（owner=当前用户）；重复提交 → 不产生重复（返回 updated）。
4. 用普通用户/超管两个账号各建 key，验证数据范围差异（普通用户查不到超管的数据）。
5. `POST /api/v1/ai/mcp`（initialize → tools/list → tools/call）手工走一遍 JSON-RPC。
6. 调用记录页面能看到上述调用；停用 key 后再调用 → 401。

## 扩展路线（本期不做，仅说明架构预留）

- **更多工具**：在 `ai_workshop.py` 服务层加函数 + `ai_mcp.py` 工具表加一项即可暴露给 Agent，如：`search_posts`（查已抓帖子）、`create_scrape_task`（让 Agent 下发抓取任务）、`query_dm_contents`（读私信文案库）。
- **更细的工具级授权**：`ai_api_keys` 加 `allowed_tools` JSON 列，即可按密钥限制可用工具（当前所有工具都开放，数据范围已由 RBAC 兜底）。
- **Skills/提示词管理**等 GVA 式子页面：均为「前端新页面 + 菜单种子 + 密钥工具」三件套的组合，可按需追加。
