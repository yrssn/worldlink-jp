"""AI 过滤：调用 LLM + PromptTemplate 对 Facebook Page 做评分/过滤。

为避免在系统提示词里"锁死"业务关键字，本服务只做拼装：
  - system_prompt：来自 PromptTemplate.system_prompt（用户自由书写）
  - user_prompt：把 Page 结构化字段喂给 LLM，并按 output_schema 返回 JSON
"""
from __future__ import annotations

import json
import re
from typing import Any, Optional

from loguru import logger

from app.models.llm import LlmProvider
from app.models.prompt import PromptTemplate
from app.services import llm_service


DEFAULT_OUTPUT_SCHEMA: dict[str, Any] = {
    "passed": "boolean，是否通过过滤",
    "score": "0-1 之间的浮点分，越大越匹配",
    "reason": "简短中文理由",
}


def _build_user_prompt(payload: dict[str, Any], template: PromptTemplate) -> str:
    schema = template.output_schema or DEFAULT_OUTPUT_SCHEMA
    keywords = template.keywords or []
    rules = template.filter_rules or {}

    lines = [
        "请根据以下规则，对给定的 Facebook Page 做评估，并严格按 JSON 返回结果。",
        f"关键词列表：{json.dumps(keywords, ensure_ascii=False)}",
        f"结构化筛选规则：{json.dumps(rules, ensure_ascii=False)}",
        f"返回 JSON 的字段说明：{json.dumps(schema, ensure_ascii=False)}",
        "===== Page 数据（JSON） =====",
        json.dumps(payload, ensure_ascii=False, default=str),
        "===== 严格输出 JSON，无任何额外解释 =====",
    ]
    return "\n".join(lines)


def _parse_json(text: str) -> Optional[dict[str, Any]]:
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            return None
    return None


def evaluate_page(
    provider: LlmProvider,
    template: PromptTemplate,
    page_payload: dict[str, Any],
) -> dict[str, Any]:
    """对单个 Page 做 AI 评估。返回 {passed: bool, score: float|None, reason: str|None}。"""
    user_prompt = _build_user_prompt(page_payload, template)
    try:
        raw = llm_service.chat(
            provider=provider,
            user_prompt=user_prompt,
            system_prompt=template.system_prompt,
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("AI evaluate failed: {}", e)
        return {"passed": False, "score": None, "reason": f"LLM error: {e}"}

    data = _parse_json(raw) or {}
    return {
        "passed": bool(data.get("passed", False)),
        "score": data.get("score"),
        "reason": data.get("reason"),
        "raw": raw,
    }


# 兼容旧调用名
def evaluate_post(provider: LlmProvider, template: PromptTemplate, payload: dict[str, Any]) -> dict[str, Any]:
    return evaluate_page(provider, template, payload)
