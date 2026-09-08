"""原生协议思考归一层（Router 层统一契约）

2026-09-09：各协议的"思考内容"在 provider 解析处统一归一为
LLMResponse.reasoning_content / .content —— Loop/Pipeline/SSE/前端
只认 LLMResponse 单一形状，新接协议不再波及上层。

覆盖：
- Anthropic Messages API（/v1/messages）：非流式 thinking block + 流式
  content_block_delta(thinking_delta) 事件流（含原始 SSE 行解析）
- Gemini generateContent：parts[] 中 thought=true 的 part
"""
from __future__ import annotations

import json
import typing

from neurova.core.logger import get_logger
from neurova.llm_client import LLMResponse

logger = get_logger(__name__)

__all__ = [
    "normalize_anthropic_response",
    "iter_anthropic_stream_events",
    "normalize_gemini_response",
]

_ANTHROPIC_STOP_REASON_MAP = {
    "end_turn": "stop",
    "stop_sequence": "stop",
    "max_tokens": "length",
    "tool_use": "tool_calls",
}


def _llm_response(
    content: str = "",
    reasoning_content: typing.Optional[str] = None,
    model: str = "",
    finish_reason: typing.Optional[str] = None,
    usage: typing.Optional[dict] = None,
) -> LLMResponse:
    return LLMResponse(
        content=content,
        role="assistant",
        model=model,
        reasoning_content=reasoning_content,
        usage=usage or {},
        finish_reason=finish_reason,
    )


# ---------------------------------------------------------------------------
# Anthropic Messages API
# ---------------------------------------------------------------------------


def normalize_anthropic_response(data: dict) -> LLMResponse:
    """非流式 /v1/messages 响应 → LLMResponse。

    content 数组按顺序拼接：type=text → content；type=thinking → reasoning_content；
    type=redacted_thinking 是加密占位（不可展示）跳过。
    """
    blocks = data.get("content") or []
    texts: list = []
    thinkings: list = []
    for block in blocks:
        btype = block.get("type")
        if btype == "text":
            texts.append(block.get("text") or "")
        elif btype == "thinking":
            thinkings.append(block.get("thinking") or "")
        # redacted_thinking / tool_use 等其余类型不进思考/正文展示

    stop = _ANTHROPIC_STOP_REASON_MAP.get(data.get("stop_reason") or "")
    usage_raw = data.get("usage") or {}
    usage = {
        "prompt_tokens": usage_raw.get("input_tokens", 0),
        "completion_tokens": usage_raw.get("output_tokens", 0),
    }
    return _llm_response(
        content="".join(texts),
        reasoning_content="".join(thinkings) or None,
        model=str(data.get("model") or ""),
        finish_reason=stop,
        usage=usage,
    )


def iter_anthropic_stream_events(
    events: typing.Iterable[typing.Union[dict, str]],
) -> typing.Iterator[LLMResponse]:
    """流式 /v1/messages 事件流 → 增量 LLMResponse 序列。

    events 元素可以是已解析的 dict，或原始 SSE 文本行（自动剥 "data: " 前缀，
    忽略 event:/注释行/空行/[DONE]/非法 JSON）。

    契约：
    - thinking_delta → reasoning_content 增量
    - text_delta → content 增量
    - message_start → 携带 model 的空 chunk（首块元数据）
    - message_delta → finish_reason/usage
    """
    model = ""
    for ev in events:
        data = _coerce_sse_line(ev) if isinstance(ev, str) else ev
        if not isinstance(data, dict):
            continue
        chunks, model = _handle_anthropic_event(data, model)
        for chunk in chunks:
            yield chunk
        # content_block_start / content_block_stop / ping 无载荷，跳过


def _coerce_sse_line(line: str) -> typing.Optional[dict]:
    """原始 SSE 文本行 → 事件 dict；event:/注释/空行/[DONE]/非法 JSON → None"""
    line = line.strip()
    if not line or line.startswith("event:") or line.startswith(":"):
        return None
    if line.startswith("data:"):
        line = line[5:].strip()
    if not line or line == "[DONE]":
        return None
    try:
        data = json.loads(line)
    except (ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def _handle_anthropic_event(
    data: dict, model: str
) -> typing.Tuple[typing.List[LLMResponse], str]:
    """单个 Anthropic 事件 → (0..n 个 LLMResponse, 更新后的 model)"""
    etype = data.get("type")
    if etype == "message_start":
        message = data.get("message") or {}
        model = str(message.get("model") or "")
        return [_llm_response(model=model)], model
    if etype == "content_block_delta":
        delta = data.get("delta") or {}
        dtype = delta.get("type")
        if dtype == "thinking_delta":
            text = delta.get("thinking") or ""
            if text:
                return [_llm_response(reasoning_content=text, model=model)], model
        elif dtype == "text_delta":
            text = delta.get("text") or ""
            if text:
                return [_llm_response(content=text, model=model)], model
        return [], model
    if etype == "message_delta":
        delta = data.get("delta") or {}
        stop = _ANTHROPIC_STOP_REASON_MAP.get(delta.get("stop_reason") or "")
        usage_raw = data.get("usage") or {}
        usage = {"completion_tokens": usage_raw.get("output_tokens", 0)}
        return [_llm_response(model=model, finish_reason=stop, usage=usage)], model
    if etype == "message_stop":
        return [_llm_response(model=model, finish_reason="stop")], model
    return [], model


async def aiter_anthropic_stream_events(
    events: typing.AsyncIterator[typing.Union[dict, str]],
) -> typing.AsyncIterator[LLMResponse]:
    """异步版事件流归一：消费 async 迭代（原始 SSE 行/事件 dict），产出同契约 chunk"""
    model = ""
    async for ev in events:
        data = _coerce_sse_line(ev) if isinstance(ev, str) else ev
        if not isinstance(data, dict):
            continue
        chunks, model = _handle_anthropic_event(data, model)
        for chunk in chunks:
            yield chunk


# ---------------------------------------------------------------------------
# Gemini generateContent
# ---------------------------------------------------------------------------

_GEMINI_FINISH_MAP = {
    "STOP": "stop",
    "MAX_TOKENS": "length",
    "SAFETY": "content_filter",
    "RECITATION": "content_filter",
}


def normalize_gemini_response(data: dict) -> LLMResponse:
    """Gemini generateContent 响应 → LLMResponse。

    candidates[0].content.parts[] 中 thought=true 的 part 是思考摘要
    （Gemini 2.5 thinking），归一为 reasoning_content；其余 part 拼 content。
    """
    candidates = data.get("candidates") or []
    first = candidates[0] if candidates else {}
    parts = (first.get("content") or {}).get("parts") or []
    texts: list = []
    thinkings: list = []
    for part in parts:
        text = part.get("text") or ""
        if not text:
            continue
        if part.get("thought"):
            thinkings.append(text)
        else:
            texts.append(text)

    finish = _GEMINI_FINISH_MAP.get((first.get("finishReason") or ""))
    usage_raw = data.get("usageMetadata") or {}
    usage = {
        "prompt_tokens": usage_raw.get("promptTokenCount", 0),
        "completion_tokens": usage_raw.get("candidatesTokenCount", 0),
    }
    return _llm_response(
        content="".join(texts),
        reasoning_content="".join(thinkings) or None,
        model=str(data.get("modelVersion") or ""),
        finish_reason=finish,
        usage=usage,
    )
