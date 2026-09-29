"""AI 工坊：MCP Streamable HTTP 端点（``POST /api/v1/ai/mcp``）。

外部智能体（Codex / Claude Code / Cursor / 任意 MCP 客户端）用 API Key 即可接入：
``Authorization: Bearer skjw-...``（或 ``X-API-Key`` / ``?api_key=``）。

实现为无状态 Streamable HTTP：POST 进 JSON-RPC 请求，回 ``application/json``
响应；通知类消息回 202。工具能力与 ``/ai/agent`` REST 端点共用同一服务层，
数据范围同样按密钥属主的 RBAC 权限过滤。
"""
from __future__ import annotations

import json
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.ai_auth import AiAgentContext, get_ai_agent
from app.core.deps import get_db
from app.models.social_account import SocialPlatform
from app.services import ai_workshop

router = APIRouter(prefix="/ai/mcp", tags=["ai-mcp"])

SERVER_NAME = "spider-jp-ai-workshop"
SERVER_VERSION = "1.0.0"

#: 支持 JSON-RPC 错误码
PARSE_ERROR = -32700
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602


def _tool_schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required or []}


def _tool_definitions() -> list[dict[str, Any]]:
    return [
        {
            "name": "search_influencers",
            "description": (
                "按当前账号的数据权限搜索系统中已有的建联达人/客户。"
                "支持关键词（名称/邮箱/编号/公司/账号链接）、平台、国家、状态过滤，分页返回。"
                "先查再存，避免重复录入。"
            ),
            "inputSchema": _tool_schema(
                {
                    "keyword": {"type": "string", "description": "关键词：名称/邮箱/编号/公司/主页链接/账号名"},
                    "platform": {
                        "type": "string",
                        "enum": [p.value for p in SocialPlatform],
                        "description": "平台（facebook/instagram/tiktok/youtube/twitter/...）",
                    },
                    "country": {"type": "string", "description": "国家：代码/中文名/英文名均可（如 JP/日本/Japan）"},
                    "status": {
                        "type": "string",
                        "enum": ["pre_contact", "contacting", "signed", "dropped"],
                        "description": "建联状态",
                    },
                    "followers_min": {"type": "integer", "description": "粉丝数下限（口径=各平台账号最大粉丝数）"},
                    "followers_max": {"type": "integer", "description": "粉丝数上限"},
                    "page": {"type": "integer", "minimum": 1},
                    "page_size": {"type": "integer", "minimum": 1, "maximum": 50},
                }
            ),
        },
        {
            "name": "get_influencer",
            "description": "按 ID 查单个达人详情（含各平台账号），仅限当前账号权限内可见的数据。",
            "inputSchema": _tool_schema(
                {"influencer_id": {"type": "integer", "description": "达人 ID"}}, ["influencer_id"]
            ),
        },
        {
            "name": "upsert_influencer",
            "description": (
                "把找到的达人/客户存入系统（自动去重 upsert）：按主页链接/handle/page_id/author_id "
                "在当前账号名下查重，已存在则补全更新，不存在则新建。"
                "至少提供 display_name / url / handle / page_id / author_id 之一；"
                "platform 用枚举值（facebook/instagram/...），country 传 JP/日本/Japan 均可。"
                "数据归属当前账号，权限与网页端一致。"
            ),
            "inputSchema": _tool_schema(
                {
                    "display_name": {"type": "string", "description": "达人/客户名称"},
                    "platform": {"type": "string", "description": "平台枚举值，如 facebook"},
                    "url": {"type": "string", "description": "主页链接"},
                    "handle": {"type": "string", "description": "账号 handle/用户名"},
                    "title": {"type": "string", "description": "账号名/页面名"},
                    "followers": {"type": "integer", "description": "粉丝数"},
                    "page_id": {"type": "string", "description": "平台内页面/账号 ID"},
                    "author_id": {"type": "string", "description": "平台内作者 ID"},
                    "avatar_url": {"type": "string"},
                    "messenger": {"type": "string"},
                    "email": {"type": "string"},
                    "phone": {"type": "string"},
                    "bio": {"type": "string", "description": "简介"},
                    "company": {"type": "string"},
                    "city": {"type": "string"},
                    "address": {"type": "string"},
                    "country": {"type": "string", "description": "国家：JP/日本/Japan 均可"},
                    "status": {
                        "type": "string",
                        "enum": ["pre_contact", "contacting", "signed", "dropped"],
                        "description": "建联状态，默认 pre_contact",
                    },
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "notes": {"type": "string", "description": "备注（发现来源、线索等）"},
                    "source_channel": {"type": "string", "description": "来源渠道，如「codex 寻客」"},
                    "extra": {"type": "object", "description": "其他原始字段（存到账号 extra）"},
                }
            ),
        },
        {
            "name": "stage_urls",
            "description": (
                "把一批主页链接（Facebook/Instagram）批量塞进「抓取暂存区」，"
                "系统会自动按链接识别平台并做四层查重（本批重复/已有任务/已入库/对照账号），"
                "跳过的会带原因返回。配合 run_scrape_tasks + get_scrape_task 完成自动抓取入库。"
            ),
            "inputSchema": _tool_schema(
                {
                    "urls": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "主页链接数组，单次最多 100 条",
                    },
                    "platform": {
                        "type": "string",
                        "enum": ["facebook", "instagram"],
                        "description": "平台，留空则逐条按链接自动识别",
                    },
                    "batch": {"type": "string", "description": "批次名（如 codex-20260928），方便整批管理"},
                },
                ["urls"],
            ),
        },
        {
            "name": "run_scrape_tasks",
            "description": (
                "触发暂存任务的后台抓取（Facebook/Instagram 主页资料，自动补全名称/粉丝/分类），"
                "抓完默认自动入库建联达人（auto_save=True）。立即返回任务 ID，"
                "之后用 get_scrape_task 轮询进度（每条约几十秒）。只操作自己名下 staged 状态的任务。"
            ),
            "inputSchema": _tool_schema(
                {
                    "task_ids": {"type": "array", "items": {"type": "integer"}, "description": "要抓取的暂存任务 ID（stage_urls 返回的 created[].id）"},
                    "batch": {"type": "string", "description": "或按批次名整批抓取（与 task_ids 二选一）"},
                    "auto_save": {"type": "boolean", "description": "抓完自动入库，默认 true"},
                    "save_status": {
                        "type": "string",
                        "enum": ["pre_contact", "contacting", "signed", "dropped"],
                        "description": "入库后的建联状态（可选，默认 pre_contact）",
                    },
                }
            ),
        },
        {
            "name": "get_scrape_task",
            "description": (
                "查询抓取任务进度：status=pending/running/done/failed；"
                "done 后 result 里有抓到的主页资料，influencer_id 有值表示已入库的达人 ID。"
            ),
            "inputSchema": _tool_schema(
                {"task_id": {"type": "integer", "description": "抓取任务 ID"}},
                ["task_id"],
            ),
        },
        {
            "name": "save_homepage_screenshot",
            "description": (
                "保存达人「主页截图」到该达人的档案（达人列表里会显示缩略图）。"
                "用 influencer_id 或主页 url 定位达人（url 定位前需已 upsert 入库）；"
                "image_base64 传截图内容，支持 data:image/png;base64, 前缀，最大 6MB。"
                "另外 upsert_influencer 也支持直接带 homepage_screenshot 参数。"
            ),
            "inputSchema": _tool_schema(
                {
                    "image_base64": {"type": "string", "description": "截图 base64 内容"},
                    "influencer_id": {"type": "integer", "description": "达人 ID（与 url 二选一）"},
                    "url": {"type": "string", "description": "达人主页链接（与 influencer_id 二选一）"},
                },
                ["image_base64"],
            ),
        },
        {
            "name": "record_outreach",
            "description": (
                "记录一次 agent 自动私信的结果（自包含：私信正文直接存快照，不依赖内容库模板；"
                "可附聊天截图）。用主页 url 关联达人（需已入库），set_status 可顺带更新建联状态"
                "（如 contacting=建联中）。status=success/failed，失败时 error 传原因。"
            ),
            "inputSchema": _tool_schema(
                {
                    "url": {"type": "string", "description": "达人主页链接（必填，用于关联/追溯）"},
                    "content_text": {"type": "string", "description": "实际发出的私信正文"},
                    "influencer_id": {"type": "integer", "description": "达人 ID（可选，不传则按 url 匹配）"},
                    "screenshot_base64": {"type": "string", "description": "聊天截图 base64（可选）"},
                    "status": {"type": "string", "enum": ["success", "failed"], "description": "发送结果，默认 success"},
                    "error": {"type": "string", "description": "失败原因（status=failed 时传）"},
                    "set_status": {
                        "type": "string",
                        "enum": ["pre_contact", "contacting", "signed", "dropped"],
                        "description": "私信后把达人建联状态更新为（如 contacting）",
                    },
                },
                ["url"],
            ),
        },
        {
            "name": "list_platforms",
            "description": "列出系统支持的平台字典（社交平台枚举 + 系统登记平台）。",
            "inputSchema": _tool_schema({}),
        },
        {
            "name": "list_countries",
            "description": "列出国家字典（id/代码/中英文），upsert 时 country 参数可直接取这里的值。",
            "inputSchema": _tool_schema({}),
        },
        {
            "name": "whoami",
            "description": "查看当前密钥身份与数据范围（own=仅自己 / all=全部）。",
            "inputSchema": _tool_schema({}),
        },
    ]


def _rpc_result(msg_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _rpc_error(msg_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def _call_tool(
    db: Session,
    agent: AiAgentContext,
    name: str,
    args: dict[str, Any],
) -> dict[str, Any]:
    """执行工具并写审计日志；返回 MCP tools/call 的 result 结构。"""
    svc = ai_workshop

    def _text(payload: Any) -> dict[str, Any]:
        return {
            "content": [
                {"type": "text", "text": json.dumps(payload, ensure_ascii=False, default=str)}
            ],
            "isError": False,
        }

    try:
        if name == "search_influencers":
            allowed = {
                k: args[k]
                for k in (
                    "keyword",
                    "platform",
                    "country",
                    "status",
                    "followers_min",
                    "followers_max",
                    "page",
                    "page_size",
                )
                if k in args
            }
            result = svc.search_influencers(db, agent.user, **allowed)
        elif name == "get_influencer":
            influencer_id = args.get("influencer_id")
            if influencer_id is None:
                raise ValueError("缺少参数 influencer_id")
            result = svc.get_influencer_detail(db, agent.user, int(influencer_id))
        elif name == "upsert_influencer":
            result = svc.upsert_influencer(db, agent.user, dict(args))
        elif name == "stage_urls":
            urls = args.get("urls")
            if not isinstance(urls, list) or not urls:
                raise ValueError("缺少参数 urls（主页链接字符串数组）")
            result = svc.stage_urls(
                db,
                agent.user,
                [str(u) for u in urls],
                platform=args.get("platform"),
                batch=args.get("batch"),
            )
        elif name == "run_scrape_tasks":
            task_ids = args.get("task_ids")
            if task_ids is not None and not isinstance(task_ids, list):
                raise ValueError("task_ids 必须是整数数组")
            result = svc.run_scrape_tasks(
                db,
                agent.user,
                task_ids=task_ids,
                batch=args.get("batch"),
                auto_save=bool(args.get("auto_save", True)),
                save_status=args.get("save_status"),
            )
        elif name == "get_scrape_task":
            tid = args.get("task_id")
            if tid is None:
                raise ValueError("缺少参数 task_id")
            result = svc.get_scrape_task(db, agent.user, int(tid))
            if result is None:
                raise ValueError(f"任务 {tid} 不存在或无权查看")
        elif name == "save_homepage_screenshot":
            image = args.get("image_base64")
            if not image or not str(image).strip():
                raise ValueError("缺少参数 image_base64（截图 base64，支持 data:image/png;base64, 前缀）")
            result = svc.save_homepage_screenshot(
                db,
                agent.user,
                str(image),
                influencer_id=args.get("influencer_id"),
                url=args.get("url"),
            )
        elif name == "record_outreach":
            link = args.get("url")
            if not link or not str(link).strip():
                raise ValueError("缺少参数 url（达人主页链接）")
            result = svc.record_outreach(
                db,
                agent.user,
                url=str(link),
                content_text=args.get("content_text"),
                influencer_id=args.get("influencer_id"),
                screenshot_base64=args.get("screenshot_base64"),
                status=str(args.get("status") or "success"),
                error=args.get("error"),
                set_status=args.get("set_status"),
            )
        elif name == "list_platforms":
            result = svc.list_platforms(db)
        elif name == "list_countries":
            result = svc.list_countries(db)
        elif name == "whoami":
            result = svc.whoami(db, agent.user, agent.key)
        else:
            raise ValueError(f"未知工具: {name}")
    except ValueError as e:
        db.rollback()
        svc.log_call(
            db,
            key_id=agent.key.id,
            owner_id=agent.user.id,
            action=name,
            status="error",
            error=str(e),
            detail={"args_digest": _args_digest(args)},
        )
        return {
            "content": [{"type": "text", "text": f"参数错误: {e}"}],
            "isError": True,
        }
    except HTTPException as e:
        db.rollback()
        svc.log_call(
            db,
            key_id=agent.key.id,
            owner_id=agent.user.id,
            action=name,
            status="error",
            error=str(e.detail),
            detail={"args_digest": _args_digest(args)},
        )
        return {
            "content": [{"type": "text", "text": f"请求被拒绝: {e.detail}"}],
            "isError": True,
        }
    except Exception as e:  # noqa: BLE001
        db.rollback()
        svc.log_call(
            db,
            key_id=agent.key.id,
            owner_id=agent.user.id,
            action=name,
            status="error",
            error=str(e),
            detail={"args_digest": _args_digest(args)},
        )
        return {
            "content": [{"type": "text", "text": f"执行失败: {e}"}],
            "isError": True,
        }

    detail: dict[str, Any] = {"args_digest": _args_digest(args)}
    if isinstance(result, dict):
        if "total" in result:
            detail["total"] = result["total"]
        if "influencer_id" in result:
            detail["influencer_id"] = result["influencer_id"]
        if "action" in result:
            detail["action"] = result["action"]
    svc.log_call(
        db,
        key_id=agent.key.id,
        owner_id=agent.user.id,
        action=name,
        detail=detail,
    )
    return _text(result)


def _args_digest(args: dict[str, Any]) -> dict[str, Any]:
    """参数摘要（截断长文本），仅用于审计展示。"""
    digest: dict[str, Any] = {}
    for k, v in list(args.items())[:8]:
        text = json.dumps(v, ensure_ascii=False, default=str) if not isinstance(v, str) else v
        digest[k] = text[:120] if isinstance(text, str) else text
    return digest


def _handle_message(db: Session, agent: AiAgentContext, msg: dict[str, Any]) -> Optional[dict[str, Any]]:
    method = msg.get("method") or ""
    msg_id = msg.get("id")

    # 通知类消息无需响应
    if method.startswith("notifications/"):
        return None

    if method == "initialize":
        params = msg.get("params") or {}
        return _rpc_result(
            msg_id,
            {
                "protocolVersion": params.get("protocolVersion") or "2024-11-05",
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        )
    if method == "ping":
        return _rpc_result(msg_id, {})
    if method == "tools/list":
        return _rpc_result(msg_id, {"tools": _tool_definitions()})
    if method == "tools/call":
        params = msg.get("params") or {}
        name = params.get("name") or ""
        args = params.get("arguments") or {}
        if name not in ai_workshop.AGENT_TOOLS:
            return _rpc_error(msg_id, INVALID_PARAMS, f"未知工具: {name}")
        return _rpc_result(msg_id, _call_tool(db, agent, name, args))
    return _rpc_error(msg_id, METHOD_NOT_FOUND, f"未知方法: {method}")


@router.post("")
async def mcp_post(
    request: Request,
    agent: AiAgentContext = Depends(get_ai_agent),
    db: Session = Depends(get_db),
):
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return JSONResponse(
            status_code=400,
            content=_rpc_error(None, PARSE_ERROR, "Invalid JSON"),
        )

    if isinstance(body, list):
        responses = [
            r for item in body if isinstance(item, dict)
            for r in [_handle_message(db, agent, item)]
            if r is not None
        ]
        if not responses:
            return Response(status_code=202)
        return JSONResponse(content=responses)

    if not isinstance(body, dict):
        return JSONResponse(status_code=400, content=_rpc_error(None, PARSE_ERROR, "Invalid JSON-RPC message"))

    response = _handle_message(db, agent, body)
    if response is None:
        return Response(status_code=202)
    return JSONResponse(content=response)


@router.api_route("", methods=["GET", "DELETE"], include_in_schema=False)
async def mcp_unsupported():
    return JSONResponse(
        status_code=405,
        content={"jsonrpc": "2.0", "error": {"code": -32000, "message": "Method Not Allowed. Use POST."}},
        headers={"Allow": "POST"},
    )
