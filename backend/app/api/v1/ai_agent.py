"""AI 工坊：Agent REST 兜底端点（API Key 认证，数据范围 = 密钥属主用户）。

面向不便接入 MCP 的脚本 / 自动化平台；能力与 MCP 工具一致，共用服务层。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.ai_auth import AiAgentContext, get_ai_agent
from app.core.deps import get_db
from app.schemas.ai_workshop import (
    AgentInfluencerUpsertRequest,
    AgentSearchRequest,
    AgentUpsertResultOut,
)
from app.services import ai_workshop

router = APIRouter(prefix="/ai/agent", tags=["ai-agent"])


@router.post("/influencers/search")
def search_influencers(
    body: AgentSearchRequest,
    agent: AiAgentContext = Depends(get_ai_agent),
    db: Session = Depends(get_db),
):
    try:
        result = ai_workshop.search_influencers(db, agent.user, **body.model_dump())
    except ValueError as e:
        db.rollback()
        ai_workshop.log_call(
            db,
            key_id=agent.key.id,
            owner_id=agent.user.id,
            action="search_influencers",
            status="error",
            error=str(e),
            detail={"keyword": body.keyword, "platform": body.platform},
        )
        raise HTTPException(status_code=400, detail=str(e)) from e
    ai_workshop.log_call(
        db,
        key_id=agent.key.id,
        owner_id=agent.user.id,
        action="search_influencers",
        detail={
            "keyword": body.keyword,
            "platform": body.platform,
            "total": result["total"],
        },
    )
    return result


@router.get("/influencers/{influencer_id}")
def get_influencer(
    influencer_id: int,
    agent: AiAgentContext = Depends(get_ai_agent),
    db: Session = Depends(get_db),
):
    result = ai_workshop.get_influencer_detail(db, agent.user, influencer_id)
    ai_workshop.log_call(
        db,
        key_id=agent.key.id,
        owner_id=agent.user.id,
        action="get_influencer",
        detail={"influencer_id": influencer_id, "found": result is not None},
    )
    if result is None:
        raise HTTPException(status_code=404, detail="达人不存在或无权查看")
    return result


@router.post("/influencers/upsert", response_model=AgentUpsertResultOut)
def upsert_influencer(
    body: AgentInfluencerUpsertRequest,
    agent: AiAgentContext = Depends(get_ai_agent),
    db: Session = Depends(get_db),
):
    try:
        result = ai_workshop.upsert_influencer(db, agent.user, body.model_dump())
    except ValueError as e:
        db.rollback()
        ai_workshop.log_call(
            db,
            key_id=agent.key.id,
            owner_id=agent.user.id,
            action="upsert_influencer",
            status="error",
            error=str(e),
            detail={"display_name": body.display_name, "url": body.url},
        )
        raise HTTPException(status_code=400, detail=str(e)) from e
    ai_workshop.log_call(
        db,
        key_id=agent.key.id,
        owner_id=agent.user.id,
        action="upsert_influencer",
        detail={
            "action": result["action"],
            "influencer_id": result["influencer_id"],
            "matched_by": result["matched_by"],
        },
    )
    return result


# --------------------------------------------------------------------------- #
# 抓取暂存链路（与 MCP 工具同能力，供不支持 MCP 的 bot 走纯 HTTP）
# --------------------------------------------------------------------------- #
@router.post("/scrape/stage")
def agent_stage_urls(
    body: dict,
    agent: AiAgentContext = Depends(get_ai_agent),
    db: Session = Depends(get_db),
):
    """批量把主页链接塞进抓取暂存区（四层查重：本批/暂存任务/达人库/对照账号）。"""
    urls = body.get("urls")
    if not isinstance(urls, list) or not [u for u in urls if str(u).strip()]:
        raise HTTPException(status_code=400, detail="urls 必须是主页链接数组")
    try:
        result = ai_workshop.stage_urls(
            db,
            agent.user,
            [str(u) for u in urls],
            platform=body.get("platform"),
            batch=body.get("batch"),
        )
    except ValueError as e:
        db.rollback()
        ai_workshop.log_call(
            db,
            key_id=agent.key.id,
            owner_id=agent.user.id,
            action="stage_urls",
            status="error",
            error=str(e),
        )
        raise HTTPException(status_code=400, detail=str(e)) from e
    ai_workshop.log_call(
        db,
        key_id=agent.key.id,
        owner_id=agent.user.id,
        action="stage_urls",
        detail={
            "created": len(result.get("created") or []),
            "skipped": len(result.get("skipped") or []),
        },
    )
    return result


@router.post("/scrape/run")
def agent_run_scrape(
    body: dict,
    agent: AiAgentContext = Depends(get_ai_agent),
    db: Session = Depends(get_db),
):
    """触发暂存任务后台抓取（auto_save 默认 true，抓完自动入库）。"""
    task_ids = body.get("task_ids")
    if task_ids is not None and not isinstance(task_ids, list):
        raise HTTPException(status_code=400, detail="task_ids 必须是整数数组")
    try:
        result = ai_workshop.run_scrape_tasks(
            db,
            agent.user,
            task_ids=task_ids,
            batch=body.get("batch"),
            auto_save=bool(body.get("auto_save", True)),
            save_status=body.get("save_status"),
        )
    except ValueError as e:
        db.rollback()
        ai_workshop.log_call(
            db,
            key_id=agent.key.id,
            owner_id=agent.user.id,
            action="run_scrape_tasks",
            status="error",
            error=str(e),
        )
        raise HTTPException(status_code=400, detail=str(e)) from e
    ai_workshop.log_call(
        db,
        key_id=agent.key.id,
        owner_id=agent.user.id,
        action="run_scrape_tasks",
        detail={"affected": result["affected"], "task_ids": result["task_ids"]},
    )
    return result


@router.get("/scrape/tasks/{task_id}")
def agent_get_scrape_task(
    task_id: int,
    agent: AiAgentContext = Depends(get_ai_agent),
    db: Session = Depends(get_db),
):
    """轮询抓取任务状态；done 且已入库时 influencer_id 即达人 ID。"""
    result = ai_workshop.get_scrape_task(db, agent.user, task_id)
    if result is None:
        raise HTTPException(status_code=404, detail="任务不存在或无权查看")
    ai_workshop.log_call(
        db,
        key_id=agent.key.id,
        owner_id=agent.user.id,
        action="get_scrape_task",
        detail={
            "task_id": task_id,
            "status": result.get("status"),
            "influencer_id": result.get("influencer_id"),
        },
    )
    return result


# --------------------------------------------------------------------------- #
# 私信记录 / 主页截图
# --------------------------------------------------------------------------- #
@router.post("/outreach/record")
def agent_record_outreach(
    body: dict,
    agent: AiAgentContext = Depends(get_ai_agent),
    db: Session = Depends(get_db),
):
    """记录一次自动私信：正文 + 多张截图 + 私信日期，挂到达人档案的私信记录。"""
    link = str(body.get("url") or "").strip()
    if not link:
        raise HTTPException(status_code=400, detail="url（达人主页链接）必填")
    shots = []
    if body.get("screenshot_base64"):
        shots.append(str(body["screenshot_base64"]))
    if isinstance(body.get("screenshots_base64"), list):
        shots.extend(str(s) for s in body["screenshots_base64"] if s)
    try:
        result = ai_workshop.record_outreach(
            db,
            agent.user,
            url=link,
            content_text=body.get("content_text"),
            influencer_id=body.get("influencer_id"),
            screenshots_base64=shots or None,
            status=str(body.get("status") or "success"),
            error=body.get("error"),
            set_status=body.get("set_status"),
            dm_at=body.get("dm_at"),
        )
    except ValueError as e:
        db.rollback()
        ai_workshop.log_call(
            db,
            key_id=agent.key.id,
            owner_id=agent.user.id,
            action="record_outreach",
            status="error",
            error=str(e),
        )
        raise HTTPException(status_code=400, detail=str(e)) from e
    ai_workshop.log_call(
        db,
        key_id=agent.key.id,
        owner_id=agent.user.id,
        action="record_outreach",
        detail={
            "outreach_log_id": result["outreach_log_id"],
            "influencer_id": result["influencer_id"],
            "screenshots": len(result.get("screenshots") or []),
        },
    )
    return result


@router.post("/screenshots/homepage")
def agent_save_homepage_screenshot(
    body: dict,
    agent: AiAgentContext = Depends(get_ai_agent),
    db: Session = Depends(get_db),
):
    """保存达人主页截图（influencer_id 或 url 定位达人）。"""
    image = body.get("image_base64")
    if not image or not str(image).strip():
        raise HTTPException(status_code=400, detail="image_base64 必填")
    try:
        result = ai_workshop.save_homepage_screenshot(
            db,
            agent.user,
            str(image),
            influencer_id=body.get("influencer_id"),
            url=body.get("url"),
        )
    except ValueError as e:
        db.rollback()
        ai_workshop.log_call(
            db,
            key_id=agent.key.id,
            owner_id=agent.user.id,
            action="save_homepage_screenshot",
            status="error",
            error=str(e),
        )
        raise HTTPException(status_code=400, detail=str(e)) from e
    ai_workshop.log_call(
        db,
        key_id=agent.key.id,
        owner_id=agent.user.id,
        action="save_homepage_screenshot",
        detail={
            "influencer_id": result["influencer_id"],
            "homepage_screenshot": result["homepage_screenshot"],
        },
    )
    return result
