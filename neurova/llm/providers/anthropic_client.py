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

#: 每条消息的固定开销（与 `LLMClient._PER_MESSAGE_OVERHEAD` 同源口径 —— 两条链路
#: 对同一输入必须给出同一读数，不另立第二把尺子）。
_PER_MESSAGE_OVERHEAD = 4


def anthropic_endpoint_url(base_url: str) -> str:
    """base_url → /v1/messages 端点（兼容 base 已带 /v1 的网关，如 AMD /radeon/api/v1）"""
    base = (base_url or "https://api.anthropic.com").rstrip("/")
    if base.endswith("/v1"):
        return f"{base}/messages"
    return f"{base}/v1/messages"


def _imageBlockFromUrl(url: str) -> typing.Optional[dict]:
    """OpenAI `image_url.url` → Anthropic `image` 源块。

    `data:<media>;base64,<payload>` 拆成 source 三元组；其余形态按远程 URL 交。
    """
    if not url:
        return None
    if url.startswith("data:"):
        header, _, payload = url.partition(",")
        media_type = header[5:].split(";")[0].strip() or "image/png"
        return {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": payload}}
    return {"type": "image", "source": {"type": "url", "url": url}}


def _contentBlocks(content: typing.Any) -> list:
    """一条消息的 content → Anthropic 内容块。

    三种进料都认：纯文本、OpenAI 多模态数组（`text` / `image_url`）、以及已是 Anthropic
    数组的历史调用方。这里**不许**用 `str(content)` 收口——拍平后模型收到的是 Python
    repr 字面量，块里的图与工具声明一并变成噪声（本轮实测到的形态）。
    """
    if isinstance(content, str):
        return [{"type": "text", "text": content}] if content else []
    if content is None:
        return []  # assistant 只声明工具时 content 为 None，别把 None 拍成 "None"
    if not isinstance(content, list):
        text = str(content)
        return [{"type": "text", "text": text}] if text else []

    blocks: list = []
    for part in content:
        if not isinstance(part, dict):
            continue
        kind = part.get("type")
        if kind == "text":
            text = str(part.get("text") or "")
            if text:
                blocks.append({"type": "text", "text": text})
        elif kind == "image_url":
            block = _imageBlockFromUrl(str((part.get("image_url") or {}).get("url") or ""))
            if block is not None:
                blocks.append(block)
        elif kind in ("image", "tool_result", "tool_use", "document"):
            blocks.append(dict(part))  # 已是线形状，原样收下不再转一遍
    return blocks


def _toolUseBlocks(tool_calls: typing.Any) -> list:
    """OpenAI `assistant.tool_calls` → Anthropic `tool_use` 块。

    `input` 必须是对象：坏 JSON 参数诚实落成 `{"raw": 原文}`，不抛异常也不静默丢调用
    （与 `ToolCallParser` 侧同一口径——解析失败要看得见，不能装作没有这次调用）。
    """
    blocks: list = []
    for call in tool_calls or []:
        if not isinstance(call, dict):
            continue
        func = call.get("function") or {}
        args = func.get("arguments", "{}")
        try:
            parsed = json.loads(args) if isinstance(args, str) else args
        except (ValueError, TypeError):
            parsed = {"raw": args}
        if not isinstance(parsed, dict):
            parsed = {"value": parsed}
        blocks.append({
            "type": "tool_use",
            "id": str(call.get("id") or ""),
            "name": str(func.get("name") or ""),
            "input": parsed,
        })
    return blocks


def toAnthropicMessages(messages: typing.List[dict]) -> typing.List[dict]:
    """OpenAI 形态 messages → Anthropic `messages`（system 由调用方另抽顶层字段）。

    §6-76 修法 A：协议转换的**唯一落点**在 provider 层。此前 `AnthropicLoop` 自带一份
    同名转换，于是同一份请求被转两遍——环转成内容块后，这里又把 `content` 拍成
    `str(...)`，模型收到的是 repr 字面量；而走 OpenAI 兼容网关时环内那份预转直接让
    校验回 400。两处只能留一处，且留下的这处必须认 OpenAI 形态（三家客户端共用的中间语言）。

    三条 Anthropic 硬约束在此实现（缺一即请求被判非法）：
    1. `tool` 角色的结果挂到 **user** 轮；
    2. `tool_result` 必须紧随声明它的 assistant `tool_use`；
    3. 同批多个结果合进**同一条** user 消息的多个块。
    """
    out: list = []
    for msg in messages or []:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role") or "")
        content = msg.get("content")
        if role == "system":
            continue

        if role == "tool":
            result = {
                "type": "tool_result",
                "tool_use_id": str(msg.get("tool_call_id") or ""),
                "content": content if isinstance(content, str) else json.dumps(
                    content if content is not None else "", ensure_ascii=False),
            }
            tail = out[-1] if out else None
            tailBlocks = tail.get("content") if isinstance(tail, dict) else None
            if (
                isinstance(tailBlocks, list)
                and tail.get("role") == "user"
                and tailBlocks
                and all(isinstance(b, dict) and b.get("type") == "tool_result" for b in tailBlocks)
            ):
                tailBlocks.append(result)
            else:
                out.append({"role": "user", "content": [result]})
            continue

        blocks = _contentBlocks(content)
        if role == "assistant":
            blocks.extend(_toolUseBlocks(msg.get("tool_calls")))
        if role not in ("user", "assistant"):
            continue  # Anthropic 只认这两种轮；别的原样送上去必被判非法，不如点名不送
        out.append({"role": role, "content": blocks or [{"type": "text", "text": ""}]})
    return out


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
    turnMessages: list = []
    for msg in messages or []:
        if not isinstance(msg, dict):
            continue
        if str(msg.get("role") or "") == "system":
            content = msg.get("content")
            if isinstance(content, str) and content.strip():
                system_parts.append(content)
            continue
        turnMessages.append(msg)
    convo = toAnthropicMessages(turnMessages)

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
        """输入 token 总量。

        原实现只累加消息正文，把 `tools` 形参**收下就丢** —— 而工具目录占上下文
        预算，真消费方 `multi_model_client` 的工具轮记账路径正是
        `count_message_tokens(messages, tools=kwargs.get("tools"))`。少算即预算
        闸门偏松（与 `tool_choice` 同型的「接受但不读」死参）。
        口径与 `LLMClient.count_message_tokens` 逐字一致：单一事实源，不另立尺子。
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
