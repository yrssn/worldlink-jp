from fastapi import APIRouter, Depends

from app.api.v1 import (
    apify_key,
    auth,
    bitbrowser,
    country,
    dm,
    email_account,
    fb_group_scrape,
    influencer,
    llm,
    prompt,
    scrape,
    system,
)
from app.core.permission_guard import enforce_route_permission

# 路由级权限统一在这里校验（菜单 -> API 前缀映射见 menus.api_prefixes）
api_router = APIRouter(
    prefix="/api/v1", dependencies=[Depends(enforce_route_permission)]
)
api_router.include_router(auth.router)
api_router.include_router(bitbrowser.router)
api_router.include_router(country.router)
api_router.include_router(dm.router)
api_router.include_router(llm.router)
api_router.include_router(prompt.router)
api_router.include_router(scrape.router)
api_router.include_router(fb_group_scrape.router)
api_router.include_router(influencer.router)
api_router.include_router(apify_key.router)
api_router.include_router(email_account.router)
api_router.include_router(system.router)
