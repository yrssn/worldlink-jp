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
