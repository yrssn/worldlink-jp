# 独立 Redis

与仓库根目录 `docker-compose.yml` 里自带的 `redis` 二选一：

- **默认**：根目录 `docker compose up` 已包含 Redis，无需本目录。
- **单独镜像**：MySQL 一样单独维护时，可用本目录只起 Redis。

## 步骤

1. 创建 Docker 网络（若尚未创建）：

   ```bash
   docker network create worldlink-redis-net
   ```

2. 把 **backend 容器** 也接入该网络（若使用根目录 compose，在 `docker-compose.yml` 里给 `backend` 增加 `worldlink-redis-net`，并删除内置 `redis` 服务；或 `docker network connect worldlink-redis-net worldlink-backend`）。

3. 在本目录配置密码并启动：

   ```bash
   cd docker/redis
   cp .env.example .env
   # 编辑 REDIS_PASSWORD
   docker compose up -d
   ```

4. 应用环境变量 `backend/.env`：

   - `REDIS_HOST=redis`（与上面 compose 的 service 名一致）
   - `REDIS_PORT=6379`
   - `REDIS_PASSWORD=` 与 `docker/redis/.env` 中完全一致

数据持久化在卷 `docker_redis_redis-data`（名称随项目目录前缀可能略有不同，以 `docker volume ls` 为准）。
