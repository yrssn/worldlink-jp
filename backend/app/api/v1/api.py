from fastapi import APIRouter

from app.api.v1 import apify_key, auth, bitbrowser, dm, fb_group_scrape, influencer, llm, prompt, scrape

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(bitbrowser.router)
api_router.include_router(dm.router)
api_router.include_router(llm.router)
api_router.include_router(prompt.router)
api_router.include_router(scrape.router)
api_router.include_router(fb_group_scrape.router)
api_router.include_router(influencer.router)
api_router.include_router(apify_key.router)
