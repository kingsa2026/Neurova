"""Anthropic 原生协议客户端（/v1/messages）

2026-09-09：Claude 原生通道接入聊天链。此前 anthropic provider 只有
langchain 壳（模型目录/连接测试），聊天主链（multi_model_client →
LLMClient）只说 OpenAI 协议，Claude 官方 API（原生 /v1/messages）
根本走不通。

接口对齐 LLMClient（chat/chat_stream_async/count_message_tokens），
multi_model_client 鸭子类型零改动。思考内容经 protocol_thinking 归一为
LLMResponse.reasoning_content —— Router 以上零改动。
（B-11：原同步 chat_stream 的 async→sync 桥已删除 —— multi_model_client
流式主链只走 chat_stream_async，同步桥零调用方且每 chunk 新建事件循环。）

thinking 映射（前端深度选择器）：
- light/未开启 → 不带 thinking 参数（普通模式）
- standard → budget 4096；deep → budget 16384
- Anthropic 约束：启用 thinking 时 temperature 必须 =1，max_tokens 必须
  > budget_tokens（自动抬高）
"""
from __future__ import annotations

import json
import typing

import aiohttp

from neurova.core.logger import get_logger
from neurova.llm.providers.protocol_thinking import (
    aiter_anthropic_stream_events,
    normalize_anthropic_response,
)
from neurova.llm.providers.tool_transport import toAnthropicToolChoice, toAnthropicTools

logger = get_logger(__name__)

__all__ = ["build_anthropic_body", "AnthropicNativeClient", "anthropic_endpoint_url"]

_THINKING_BUDGET_BY_EFFORT = {"standard": 4096, "deep": 16384}

_DEFAULT_MAX_TOKENS = 4096


def anthropic_endpoint_url(base_url: str) -> str:
    """base_url → /v1/messages 端点（兼容 base 已带 /v1 的网关，如 AMD /radeon/api/v1）"""
    base = (base_url or "https://api.anthropic.com").rstrip("/")
    if base.endswith("/v1"):
        return f"{base}/messages"
    return f"{base}/v1/messages"


def build_anthropic_body(
    messages: typing.List[dict],
    model: str,
    max_tokens: typing.Optional[int] = None,
    thinking_effort: typing.Optional[str] = None,
    tools: typing.Optional[typing.List[dict]] = None,
    tool_choice: typing.Optional[str] = None,
    **kwargs,
) -> dict:
    """OpenAI 风格 messages → Anthropic /v1/messages 请求体（纯函数）。

    - system 消息抽取到顶层 system 字段；其余仅保留 user/assistant 轮
    - thinking_effort（light/standard/deep）→ thinking budget；
      light/None 不启用 thinking（Anthropic 无"关闭"参数，缺省即关）
    - 启用 thinking 时强制 temperature=1、max_tokens > budget_tokens
    - tools/tool_choice → Anthropic `tools`（`input_schema` 形态）与
      `tool_choice`（auto/any/none）。原实现在此**静默丢弃**工具，
      使原生链路上的函数调用能力消失（Issue #177）
    """
    system_parts: list = []
    convo: list = []
    for msg in messages or []:
        role = str(msg.get("role") or "")
        content = msg.get("content")
        if content is None:
            continue
        if role == "system":
            if isinstance(content, str) and content.strip():
                system_parts.append(content)
            continue
        if role in ("user", "assistant"):
            convo.append({"role": role, "content": str(content)})

    body: dict = {
        "model": model,
        "messages": convo or [{"role": "user", "content": "hello"}],
        "max_tokens": int(max_tokens or _DEFAULT_MAX_TOKENS),
    }
    if system_parts:
        body["system"] = "\n\n".join(system_parts)

    anthropic_tools = toAnthropicTools(tools)
    if anthropic_tools:
        body["tools"] = anthropic_tools
        choice = toAnthropicToolChoice(tool_choice)
        if choice is not None:
            body["tool_choice"] = choice

    budget = _THINKING_BUDGET_BY_EFFORT.get((thinking_effort or "").strip().lower())
    if budget:
        if body["max_tokens"] <= budget:
            body["max_tokens"] = budget + 1024
        body["thinking"] = {"type": "enabled", "budget_tokens": budget}
        body["temperature"] = 1
    elif "temperature" in kwargs and kwargs["temperature"] is not None:
        body["temperature"] = kwargs["temperature"]

    return body


class AnthropicNativeClient:
    """Anthropic 原生协议聊天客户端（aiohttp /v1/messages）。

    与 LLMClient 接口鸭子兼容：chat / chat_stream_async /
    count_message_tokens / count_tokens —— multi_model_client 零改动消费。
    """

    def __init__(self, config, provider_id: str = "anthropic"):
        self.config = config
        self.provider_id = provider_id
        self.logger = logger

    # ── HTTP 薄层（测试可注入覆盖） ─────────────────────────────

    async def _post_json(self, body: dict) -> dict:
        url = anthropic_endpoint_url(self.config.base_url)
        headers = {
            "x-api-key": self.config.api_key or "",
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        timeout = aiohttp.ClientTimeout(total=600)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, headers=headers, json=body) as resp:
                text = await resp.text()
                if resp.status != 200:
                    raise RuntimeError(f"Anthropic API {resp.status}: {text[:300]}")
                return json.loads(text)

    async def _stream_sse_lines(self, body: dict) -> typing.AsyncIterator[str]:
        url = anthropic_endpoint_url(self.config.base_url)
        headers = {
            "x-api-key": self.config.api_key or "",
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        timeout = aiohttp.ClientTimeout(total=600)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, headers=headers, json=body) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise RuntimeError(f"Anthropic API {resp.status}: {text[:300]}")
                async for raw in resp.content:
                    yield raw.decode("utf-8", errors="replace")

    # ── 请求体组装 ───────────────────────────────────────────

    def _body(self, messages, **kwargs) -> dict:
        """请求体组装。

        工具键先过声明位（`compat.supports_tools` / `supports_tool_choice`）：
        未声明的网关一律剔除并留一行点名 `not_supported` 的日志 —— 原实现是
        「形参根本没有 tools」，静默丢弃、无日志无报错（Issue #177 的诚实化）。
        """
        compat = getattr(self.config, "compat", None)
        if compat is not None:
            from neurova.llm.provider_compat import dropUnsupportedToolKeys

            dropUnsupportedToolKeys(compat, kwargs, self.logger, where=f"{self.provider_id}._body")
        return build_anthropic_body(
            messages,
            model=self.config.model,
            max_tokens=kwargs.get("max_tokens", self.config.max_tokens),
            thinking_effort=kwargs.get("thinking_effort"),
            tools=kwargs.get("tools"),
            tool_choice=kwargs.get("tool_choice"),
            temperature=kwargs.get("temperature", self.config.temperature),
        )

    # ── LLMClient 兼容接口 ───────────────────────────────────

    async def chat(self, messages, **kwargs):
        body = self._body(messages, **kwargs)
        data = await self._post_json(body)
        return normalize_anthropic_response(data)

    async def chat_stream_async(self, messages, **kwargs):
        body = self._body(messages, **kwargs)
        body["stream"] = True
        lines = self._stream_sse_lines(body)
        async for chunk in aiter_anthropic_stream_events(lines):
            yield chunk

    def count_tokens(self, text: str) -> int:
        """估算 token 数（走全仓唯一尺子；Anthropic 无本地分词器，按类别上界）。"""
        from neurova.context.token_estimator import estimate_tokens

        return max(1, estimate_tokens(text))

    def count_message_tokens(self, messages, tools=None) -> int:
        total = 0
        for msg in messages or []:
            content = msg.get("content") or ""
            total += self.count_tokens(str(content)) + 4
        return total
