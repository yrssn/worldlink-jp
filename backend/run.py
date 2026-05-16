"""后端启动脚本。

用法（在已激活 conda 环境的前提下）：

  python run.py                         # 开发模式，自动 reload，默认 0.0.0.0:8000
  python run.py --no-reload             # 关闭热重载
  python run.py --host 127.0.0.1 --port 8080
  python run.py --workers 4 --no-reload # 生产多 worker（reload 与 workers 互斥）
  python run.py --init-db-only          # 仅初始化数据库（建表 + 默认 admin）后退出
  python run.py --log-level debug
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# 让脚本既能 `python run.py` 也能 `python backend/run.py` 跑起来
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="spider_jp_worldlink backend launcher")
    parser.add_argument("--host", default=None, help="监听地址（默认读 .env APP_HOST）")
    parser.add_argument("--port", type=int, default=None, help="监听端口（默认读 .env APP_PORT）")
    parser.add_argument(
        "--reload",
        dest="reload",
        action="store_true",
        default=None,
        help="启用热重载（默认根据 .env APP_DEBUG 决定）",
    )
    parser.add_argument(
        "--no-reload",
        dest="reload",
        action="store_false",
        help="禁用热重载",
    )
    parser.add_argument("--workers", type=int, default=1, help="worker 数量（与 reload 互斥）")
    parser.add_argument(
        "--log-level",
        default="info",
        choices=["critical", "error", "warning", "info", "debug", "trace"],
        help="uvicorn 日志级别",
    )
    parser.add_argument(
        "--init-db-only",
        action="store_true",
        help="只初始化数据库（建表 + 默认 admin）后退出，不启动 web 服务",
    )
    parser.add_argument(
        "--skip-init-db",
        action="store_true",
        help="启动时跳过 init_db（默认会调用）",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    os.chdir(BASE_DIR)
    # 加载 .env（pydantic-settings 默认从工作目录的 .env 读，cd 到 backend 即可）
    if not (BASE_DIR / ".env").exists():
        print("[run.py] 未发现 backend/.env，将使用 .env.example 中的默认值，建议先复制并填写：")
        print("         copy .env.example .env")

    from app.core.config import settings

    host = args.host or settings.app_host
    port = args.port or settings.app_port
    reload = settings.app_debug if args.reload is None else args.reload

    if args.init_db_only:
        from app.db.init_db import init_db

        print("[run.py] 仅初始化数据库...")
        init_db()
        print("[run.py] 完成")
        return

    if not args.skip_init_db:
        try:
            from app.db.init_db import init_db

            print("[run.py] 初始化数据库（建表 + 默认 admin）...")
            init_db()
        except Exception as e:  # noqa: BLE001
            print(f"[run.py] init_db 失败（可能 MySQL 还没起，可用 --skip-init-db 跳过）：{e}")

    if reload and args.workers > 1:
        print("[run.py] reload 模式下 workers 强制为 1（uvicorn 限制）")
        workers = 1
    else:
        workers = args.workers

    import uvicorn

    print(
        f"[run.py] Starting uvicorn on http://{host}:{port}  "
        f"reload={reload} workers={workers} log_level={args.log_level}"
    )

    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        reload=reload,
        workers=workers,
        log_level=args.log_level,
    )


if __name__ == "__main__":
    main()
