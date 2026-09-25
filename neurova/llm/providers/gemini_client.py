"""Gemini 原生协议客户端（generateContent / streamGenerateContent?alt=sse）

2026-09-09：Gemini 原生通道接入聊天链。thought parts（Gemini 2.5 thinking
摘要）经 protocol_thinking 归一为 LLMResponse.reasoning_content —— 与
AnthropicNativeClient 同一统一契约，Router 以上零改动。

鉴权：x-goog-api-key 头（官方推荐，兼容 vertex-proxy 类网关）。
thinking 开关：thinkingConfig.thinkingBudget（Gemini 2.5）——
standard→2048 / deep→8192；light/None 不传（模型默认行为）。
"""
from __future__ import annotations

import json
import typing

import aiohttp

from neurova.core.logger import get_logger
from neurova.llm.providers.protocol_thinking import normalize_gemini_response
from neurova.llm.providers.tool_transport import toGeminiToolChoice, toGeminiTools

logger = get_logger(__name__)

__all__ = ["build_gemini_body", "GeminiNativeClient", "gemini_endpoint_urls"]

_THINKING_BUDGET_BY_EFFORT = {"standard": 2048, "deep": 8192}

_DEFAULT_MAX_TOKENS = 4096

#: 每条消息的固定开销（与 `LLMClient._PER_MESSAGE_OVERHEAD` 同源口径）。
_PER_MESSAGE_OVERHEAD = 4


def gemini_endpoint_urls(base_url: str, model: str) -> typing.Tuple[str, str]:
    """base_url → (非流式 URL, 流式 SSE URL)。

    兼容 base 已带 /v1beta 与裸域两种写法；模型名剥掉 "models/" 前缀。
    """
    base = (base_url or "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
    if "/v1beta" not in base:
        base = f"{base}/v1beta"
    short = model.split("/")[-1]
    return (
        f"{base}/models/{short}:generateContent",
        f"{base}/models/{short}:streamGenerateContent?alt=sse",
    )


def build_gemini_body(
    messages: typing.List[dict],
    max_tokens: typing.Optional[int] = None,
    thinking_effort: typing.Optional[str] = None,
    tools: typing.Optional[typing.List[dict]] = None,
    tool_choice: typing.Optional[str] = None,
    **kwargs,
) -> dict:
    """OpenAI 风格 messages → Gemini generateContent 请求体（纯函数）。

    - system 消息 → systemInstruction；其余仅保留 user/assistant 轮
    - thinking_effort（standard/deep）→ thinkingConfig.thinkingBudget；
      light/None 不传（保持模型默认）
    - tools/tool_choice → `tools[].functionDeclarations[]` 与 `toolConfig`
      （AUTO/ANY/NONE）。原实现**静默丢弃**工具，使原生链路上的函数调用
      能力消失（Issue #177）
    """
    system_parts: list = []
    contents: list = []
    for msg in messages or []:
        role = str(msg.get("role") or "")
        text = msg.get("content")
        if text is None:
            continue
        if role == "system":
            if isinstance(text, str) and text.strip():
                system_parts.append(text)
            continue
        if role in ("user", "assistant"):
            gemini_role = "model" if role == "assistant" else "user"
            contents.append({"role": gemini_role, "parts": [{"text": str(text)}]})

    body: dict = {
        "contents": contents or [{"role": "user", "parts": [{"text": "hello"}]}],
        "generationConfig": {"maxOutputTokens": int(max_tokens or _DEFAULT_MAX_TOKENS)},
    }
    if system_parts:
        body["systemInstruction"] = {"parts": [{"text": "\n\n".join(system_parts)}]}

    gemini_tools = toGeminiTools(tools)
    if gemini_tools:
        body["tools"] = gemini_tools
        tool_config = toGeminiToolChoice(tool_choice)
        if tool_config is not None:
            body["toolConfig"] = tool_config

    budget = _THINKING_BUDGET_BY_EFFORT.get((thinking_effort or "").strip().lower())
    if budget:
        body["generationConfig"]["thinkingConfig"] = {"thinkingBudget": budget}
    elif kwargs.get("temperature") is not None:
        body["generationConfig"]["temperature"] = kwargs["temperature"]

    return body


class GeminiNativeClient:
    """Gemini 原生协议聊天客户端（aiohttp generateContent）。

    与 LLMClient 接口鸭子兼容（chat/chat_stream/chat_stream_async/
    count_tokens/count_message_tokens），multi_model_client 零改动消费。
    """

    def __init__(self, config, provider_id: str = "google"):
        self.config = config
        self.provider_id = provider_id
        self.logger = logger

    def _headers(self) -> dict:
        return {
            "x-goog-api-key": self.config.api_key or "",
            "Content-Type": "application/json",
        }

    # ── HTTP 薄层（测试可注入覆盖） ─────────────────────────────

    async def _post_json(self, url: str, body: dict) -> dict:
        timeout = aiohttp.ClientTimeout(total=600)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, headers=self._headers(), json=body) as resp:
                text = await resp.text()
                if resp.status != 200:
                    raise RuntimeError(f"Gemini API {resp.status}: {text[:300]}")
                return json.loads(text)

    async def _stream_sse_lines(self, url: str, body: dict) -> typing.AsyncIterator[str]:
        timeout = aiohttp.ClientTimeout(total=600)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, headers=self._headers(), json=body) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise RuntimeError(f"Gemini API {resp.status}: {text[:300]}")
                async for raw in resp.content:
                    yield raw.decode("utf-8", errors="replace")

    # ── 请求体组装 ───────────────────────────────────────────

    def _body(self, messages, **kwargs) -> dict:
        """请求体组装，工具键先过声明位（未声明即剔除并点名 not_supported）。"""
        compat = getattr(self.config, "compat", None)
        if compat is not None:
            from neurova.llm.provider_compat import dropUnsupportedToolKeys

            dropUnsupportedToolKeys(compat, kwargs, self.logger, where=f"{self.provider_id}._body")
        return build_gemini_body(
            messages,
            max_tokens=kwargs.get("max_tokens", self.config.max_tokens),
            thinking_effort=kwargs.get("thinking_effort"),
            tools=kwargs.get("tools"),
            tool_choice=kwargs.get("tool_choice"),
            temperature=kwargs.get("temperature", self.config.temperature),
        )

    # ── LLMClient 兼容接口 ───────────────────────────────────

    async def chat(self, messages, **kwargs):
        url, _ = gemini_endpoint_urls(self.config.base_url, self.config.model)
        data = await self._post_json(url, self._body(messages, **kwargs))
        return normalize_gemini_response(data)

    async def _stream_data_events(self, messages, **kwargs):
        """streamGenerateContent?alt=sse 的 data 行 → 每行一个完整响应 JSON"""
        _, url = gemini_endpoint_urls(self.config.base_url, self.config.model)
        body = self._body(messages, **kwargs)
        async for line in self._stream_sse_lines(url, body):
            line = line.strip()
            if line.startswith("data:"):
                line = line[5:].strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except (ValueError, TypeError):
                continue

    async def chat_stream_async(self, messages, **kwargs):
        # streamGenerateContent?alt=sse 每帧为增量片段（与 Anthropic
        # text_delta 同语义），逐帧归一后直接透传
        async for data in self._stream_data_events(messages, **kwargs):
            chunk = normalize_gemini_response(data)
            if chunk.content or chunk.reasoning_content or chunk.finish_reason:
                yield chunk

    def count_tokens(self, text: str) -> int:
        """估算 token 数（走全仓唯一尺子）。"""
        from neurova.context.token_estimator import estimate_tokens

        return max(1, estimate_tokens(text))

    def count_message_tokens(self, messages, tools=None) -> int:
        """输入 token 总量（含 `messages` 里的 tool_calls 与 `tools` 目录）。

        与 `LLMClient.count_message_tokens` 逐字同口径：单一事实源，不另立尺子。
        原实现把 `tools` 形参收下就丢，工具目录不进预算（与 `tool_choice`
        同型的「接受但不读」死参）。
        """
        total = 0
        for msg in messages or []:
            content = msg.get("content") or ""
            total += self.count_tokens(str(content)) + _PER_MESSAGE_OVERHEAD
            for tc in (msg.get("tool_calls") or []) if isinstance(msg, dict) else []:
                fn = tc.get("function", {}) if isinstance(tc, dict) else {}
                total += self.count_tokens(str(fn.get("arguments", ""))) + self.count_tokens(
                    str(fn.get("name", ""))
                )
        for tool in tools or []:
            total += self.count_tokens(str(tool))
        return total
