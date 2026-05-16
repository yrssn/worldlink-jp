# spider_jp_worldlink

日本红人 / Facebook 抓取 & 建联系统。详细需求见 [REQUIREMENTS.md](./REQUIREMENTS.md)。

技术栈：FastAPI + Vue3 + MySQL + Redis + JWT + LangChain + Apify

## 一、目录结构

```
spider_jp_worldlink/
├── REQUIREMENTS.md           # 详细需求 / 接口 / 数据模型
├── environment.yml           # conda 环境定义
├── docker-compose.yml        # 后端 + 前端 + 内置 Redis
├── docker/redis/             # 可选：单独起 Redis
├── backend/
│   ├── requirements.txt
│   ├── .env.example / .env.docker.example / .env.server.example
│   ...
└── frontend/
```

## 二、后端：用 Conda 启动

> 需要预先在本机安装 **MySQL 8.x** 和 **Redis 7.x**，并创建空库 `spider_jp_worldlink`（utf8mb4）。

```powershell
# 1. 创建并激活环境
conda env create -f environment.yml
conda activate spider_jp_worldlink

# 2. 复制环境变量
cd backend
copy .env.example .env
# 编辑 .env，至少填好 MySQL/Redis 连接，强烈建议设置 SECRET_KEY 与 FERNET_KEY
# 生成 FERNET_KEY:
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# 3. 启动（首次启动会自动建表 + 创建默认 admin）
#    任选其一即可：
python run.py                 # 推荐：跨平台启动脚本（支持参数）
# 或在 cmd 下：
run.bat
# 或在 PowerShell 下：
.\run.ps1
# 或直接：
python -m app.main
# 或：
uvicorn app.main:app --reload --port 8000
```

`run.py` 常用参数：

```powershell
python run.py --port 9000          # 改端口
python run.py --no-reload          # 关闭热重载
python run.py --init-db-only       # 只建表 + 创建默认 admin 后退出
python run.py --skip-init-db       # 启动时跳过 init_db
python run.py --workers 4 --no-reload   # 生产多 worker
```

启动后接口默认在 `http://127.0.0.1:8000`，自动生成的 Swagger 文档在 `http://127.0.0.1:8000/docs`。

**默认管理员账号**：`admin / admin123`（在 `.env` 中可修改，首次启动后请尽快改密码）。

### 数据库迁移（推荐生产使用 Alembic）

```powershell
cd backend
alembic revision --autogenerate -m "init"
alembic upgrade head
```

开发模式下 `app.main` 启动时会调用 `init_db()` 直接 `create_all()` 建表，方便快速跑通。

## 三、前端：Vue3 + Vite

```powershell
cd frontend
npm install        # 或 pnpm i / yarn
npm run dev
```

默认监听 `http://127.0.0.1:5173`，已配置代理把 `/api` 转发到后端 `http://127.0.0.1:8000`。

用 `admin / admin123` 登录后即可看到三大模块：

- **大模型** → 厂商配置 / 提示词模板
- **抓取器** → 抓取任务（新建 FB Search / FB Pages 任务，查看抓回来的帖子并点【建联】入库）
- **建联达人** → 已建联或手工新增的达人，可补充各平台社交账号

## 四、模块说明（与 REQUIREMENTS.md 对齐）

| 模块 | 入口 | 说明 |
|------|------|------|
| 大模型配置 | `/llm/providers` | 支持 OpenAI / Azure / DeepSeek / Claude / Qwen / Ollama / 自定义；API Key 用 Fernet 加密入库 |
| 提示词模板 | `/llm/prompts` | 系统提示词由用户书写，不锁死业务；可配置关键词、过滤规则、输出 schema |
| 抓取任务 | `/scraper/tasks` | 创建 FB Search / FB Pages 任务；可选是否启用 AI 过滤（绑定提示词模板 + 大模型） |
| 任务详情 | `/scraper/tasks/:id` | 查看帖子列表（含 AI 通过/不通过标记），点【建联】入库；FB Pages 任务直接对主页结果点【建联】 |
| 建联达人 | `/influencers` | 列表 + 手工新增；按 owner_id 权限隔离 |
| 达人详情 | `/influencers/:id` | 维护多平台社交账号（FB/IG/TT/YT/X/WeChat/小红书/Line/其他） |

## 五、关键约定

- **权限**：每张业务表都有 `owner_id`；普通用户只能看到自己创建/抓取入库的数据，admin 可看全部。
- **建联查重**：从抓取入库时，按 `fb_page_id` / `fb_page_url` / `email` 任一命中即视为重复，命中后只把新的 `Post` 关联到已有达人，不再新增。
- **AI 过滤**：在抓帖子时启用，调用 `LangChain` 适配的大模型，对每条帖子返回 `passed/score/reason`，前端可只看通过项再决定是否建联。
- **抓取执行**：当前使用 FastAPI `BackgroundTasks` 异步执行；后续可平滑替换为 Celery / RQ。
- **API Key 加密**：通过 `FERNET_KEY` 对 `llm_providers.api_key` 做对称加密；未配置时退化为明文（仅限本地开发）。

## 六、Docker 部署

> 镜像组成：`backend`（FastAPI/uvicorn）、`frontend`（nginx + 反代 `/api`）、`redis`（compose 内置）。
> MySQL 走 **外部容器**（你已有），通过外部网络 `mysql-net` 互通，不在本 compose 内启动。

### 1. 准备 MySQL（如未启动）

确保已有 MySQL 容器，并加入了名为 `mysql-net` 的网络。例如另一仓库里的 `mysql/docker-compose.yml`：

```bash
cd mysql && docker-compose up -d
# 在 MySQL 内创建数据库（utf8mb4）
docker exec -it mysql mysql -uroot -p<password> \
  -e "CREATE DATABASE IF NOT EXISTS spider_jp_worldlink DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
```

如果 `mysql-net` 不存在，可手动建：

```bash
docker network create mysql-net
# 再把 mysql 容器接入：docker network connect mysql-net <mysql-container-name>
```

### 2. 准备后端 .env

服务器可参考 **`backend/.env.server.example`**（字段与本地 `backend/.env` 对齐，无真实密钥）。复制后改名：

```bash
cp backend/.env.server.example backend/.env
# 按服务器实际修改 MYSQL_*、REDIS_*、SECRET_KEY、FERNET_KEY、APIFY_TOKEN 等
```

### 2.1 可选：单独起 Redis 镜像

根目录 `docker-compose.yml` 已包含 Redis；若你希望与 MySQL 一样**单独维护 Redis**，见 **[docker/redis/README.md](./docker/redis/README.md)**（`docker network create worldlink-redis-net` + `docker/redis/docker-compose.yml`），并在主 compose 中去掉内置 `redis`、让 `backend` 加入同一网络。

### 3. 启动

```bash
docker-compose up -d --build
docker-compose ps
docker-compose logs -f backend
```

- 前端：`http://<服务器IP>:9278`
- 后端：`http://<服务器IP>:8009/docs`（Swagger）
- 默认登录：`admin / admin123`

### 4. 常用维护

```bash
# 更新代码后重建
docker-compose up -d --build

# 单独重启
docker-compose restart backend

# 查看日志
docker-compose logs -f backend
docker-compose logs -f frontend

# 停掉
docker-compose down

# 完全清空（含 redis 数据 / 上传文件）
docker-compose down -v
```

### 5. 端口冲突修改

`docker-compose.yml` 中的 `ports`：
- `backend`: `8009:8009`（宿主:容器）
- `frontend`: `9278:80`

改宿主端口即可，例如 `19278:80`。

## 七、后续可扩展

- 多平台抓取（Instagram / TikTok 等）：新增 `ScrapeTaskType` 与对应 service 即可，业务模型不动。
- 抓取调度：把 `scrape_service.run_scrape_task` 接到 Celery + Redis 即可拿到重试 / 进度。
- 数据导出：已支持任务帖子 / 待审核博主 / 建联达人 CSV 导出，可继续扩展 Excel。
- 操作日志、消息提醒。
