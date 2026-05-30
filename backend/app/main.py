from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from loguru import logger

from app.api.v1.api import api_router
from app.core.config import settings
from app.db.init_db import init_db
from app.services.bitbrowser_relay import relay_manager
from app.services.fb_group_scheduler import fb_group_scheduler


@asynccontextmanager
async def lifespan(_: FastAPI):
    import asyncio
    relay_manager.set_loop(asyncio.get_event_loop())
    logger.info("Starting {} in {} mode", settings.app_name, settings.app_env)
    try:
        init_db()
    except Exception as e:  # noqa: BLE001
        logger.exception("init_db failed: {}", e)
    
    # 启动定时任务调度器
    try:
        fb_group_scheduler.start()
    except Exception as e:  # noqa: BLE001
        logger.exception("fb_group_scheduler startup failed: {}", e)
    
    yield
    
    # 关闭调度器
    try:
        fb_group_scheduler.stop()
    except Exception as e:  # noqa: BLE001
        logger.exception("fb_group_scheduler shutdown failed: {}", e)
    
    logger.info("Shutting down {}", settings.app_name)


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        debug=settings.app_debug,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router)

    dm_media_root = Path(settings.dm_upload_dir)
    dm_media_root.mkdir(parents=True, exist_ok=True)
    app.mount(
        "/api/v1/dm/media",
        StaticFiles(directory=str(dm_media_root.resolve())),
        name="dm_media",
    )

    @app.get("/healthz", tags=["meta"])
    def healthz():
        return {"status": "ok", "app": settings.app_name}

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.app_debug,
    )
