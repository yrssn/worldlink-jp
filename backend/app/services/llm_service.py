"""大模型服务：基于 LangChain 适配多家厂商。

由于业务侧"AI 过滤帖子"的提示词完全由用户在 PromptTemplate 中书写，
本服务只负责：
  1. 根据 LlmProvider 配置构造 LangChain ChatModel；
  2. 提供一个统一的 chat(prompt, system) 接口；
  3. 提供一个 test() 连通性测试。
"""
from __future__ import annotations

from typing import Optional

from loguru import logger

from app.core.security import decrypt_secret
from app.models.llm import LlmProvider, LlmProviderType


def _build_chat_model(provider: LlmProvider):
    """根据 LlmProvider 返回一个 LangChain ChatModel。"""
    api_key = decrypt_secret(provider.api_key)
    base_url = provider.base_url
    temperature = provider.temperature or 0.0
    max_tokens = provider.max_tokens
    model = provider.model
    extra = provider.extra_params or {}

    ptype = provider.provider
    if ptype in (
        LlmProviderType.openai,
        LlmProviderType.deepseek,
        LlmProviderType.qwen,
        LlmProviderType.custom,
    ):
        # 兼容 OpenAI 协议
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=model,
            api_key=api_key,
            base_url=base_url,
            temperature=temperature,
            max_tokens=max_tokens,
            **extra,
        )
    if ptype == LlmProviderType.azure_openai:
        from langchain_openai import AzureChatOpenAI

        return AzureChatOpenAI(
            azure_endpoint=base_url,
            api_key=api_key,
            deployment_name=model,
            temperature=temperature,
            max_tokens=max_tokens,
            **extra,
        )
    if ptype == LlmProviderType.ollama:
        try:
            from langchain_community.chat_models import ChatOllama
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("ChatOllama not installed") from e
        return ChatOllama(
            model=model,
            base_url=base_url or "http://localhost:11434",
            temperature=temperature,
            **extra,
        )
    if ptype == LlmProviderType.claude:
        try:
            from langchain_anthropic import ChatAnthropic  # type: ignore
        except ImportError as e:  # pragma: no cover
            raise RuntimeError(
                "langchain-anthropic 未安装，需要额外 pip install langchain-anthropic"
            ) from e
        return ChatAnthropic(
            model=model,
            api_key=api_key,
            temperature=temperature,
            max_tokens=max_tokens,
            **extra,
        )

    raise ValueError(f"Unsupported provider type: {ptype}")


def chat(
    provider: LlmProvider,
    user_prompt: str,
    system_prompt: Optional[str] = None,
) -> str:
    """统一调用大模型对话。"""
    from langchain_core.messages import HumanMessage, SystemMessage

    chat_model = _build_chat_model(provider)
    messages = []
    if system_prompt:
        messages.append(SystemMessage(content=system_prompt))
    messages.append(HumanMessage(content=user_prompt))

    resp = chat_model.invoke(messages)
    content = getattr(resp, "content", None)
    if isinstance(content, list):
        # 某些模型返回 list[part]
        return "".join(
            str(part.get("text", "")) if isinstance(part, dict) else str(part)
            for part in content
        )
    return str(content or "")


def test_provider(provider: LlmProvider, prompt: str) -> tuple[bool, Optional[str], Optional[str]]:
    """对 LlmProvider 进行连通性测试。"""
    try:
        out = chat(provider, prompt)
        return True, out, None
    except Exception as e:  # noqa: BLE001
        logger.exception("LLM provider test failed: {}", e)
        return False, None, str(e)
