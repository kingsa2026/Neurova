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
    "toOpenAIToolCalls",
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

def toOpenAIToolCalls(blocks: typing.List[dict]) -> typing.Optional[typing.List[dict]]:
    """原生协议工具块 → `LLMResponse.tool_calls` 契约（OpenAI 形态）。

    转换经 `tool_layers/openai_schema.py` 的 `ToolCallParser`（本仓既有的
    OpenAI↔Anthropic↔Google 归一器）完成 —— 它是这条链路上**唯一的**转换实现，
    不在此另写一份解包逻辑（单一事实源）。无工具块时返回 None（与
    `llm_client` 的既有契约一致：无调用即 None，不是空列表）。
    """
    if not blocks:
        return None
    from neurova.tool_layers.openai_schema import ToolCallParser

    parser = ToolCallParser()
    out: typing.List[dict] = []
    for i, block in enumerate(blocks):
        parsed = parser.parse_tool_call(block)
        name = str(parsed.get("name") or "")
        if not name:
            continue
        out.append(
            {
                "id": str(parsed.get("id") or "") or f"call_{i}",
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": json.dumps(parsed.get("arguments") or {}, ensure_ascii=False),
                },
            }
        )
    return out or None



def normalize_anthropic_response(data: dict) -> LLMResponse:
    """非流式 /v1/messages 响应 → LLMResponse。

    content 数组按顺序拼接：type=text → content；type=thinking → reasoning_content；
    type=redacted_thinking 是加密占位（不可展示）跳过。
    """
    blocks = data.get("content") or []
    texts: list = []
    thinkings: list = []
    tool_blocks: list = []
    for block in blocks:
        btype = block.get("type")
        if btype == "text":
            texts.append(block.get("text") or "")
        elif btype == "thinking":
            thinkings.append(block.get("thinking") or "")
        elif btype == "tool_use":
            # 原实现把 tool_use 一并归入「不进展示」而**静默丢弃**：配了原生
            # Anthropic provider 时函数调用能力直接消失，没有日志、没有报错。
            # 现按契约归一为 LLMResponse.tool_calls。
            tool_blocks.append(block)
        # redacted_thinking 是加密占位（不可展示），仍跳过

    stop = _ANTHROPIC_STOP_REASON_MAP.get(data.get("stop_reason") or "")
    usage_raw = data.get("usage") or {}
    usage = {
        "prompt_tokens": usage_raw.get("input_tokens", 0),
        "completion_tokens": usage_raw.get("output_tokens", 0),
    }
    resp = _llm_response(
        content="".join(texts),
        reasoning_content="".join(thinkings) or None,
        model=str(data.get("model") or ""),
        finish_reason=stop,
        usage=usage,
    )
    resp.tool_calls = toOpenAIToolCalls(tool_blocks)
    return resp


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
    - tool_use 起始块 + input_json_delta 分片 → 累积后按 index 合并成一条
      tool_call（首片带 id/name，与 OpenAI 流式形态一致）——原实现直接跳过
      content_block_start(tool_use) 与 input_json_delta，工具调用被静默丢弃
    """
    model = ""
    pending: dict = {}
    for ev in events:
        data = _coerce_sse_line(ev) if isinstance(ev, str) else ev
        if not isinstance(data, dict):
            continue
        chunks, model = _handle_anthropic_event(data, model, pending)
        for chunk in chunks:
            yield chunk
        # content_block_delta(ping/其它无载荷类型) 跳过


def _toolCallFragment(index, state: dict, model: str, arguments: str) -> LLMResponse:
    """构造一条 tool_call 流式分片（形态与 OpenAI 兼容流一致）。

    首片携带 id/name（arguments 可为空），后续片只带 arguments 增量 ——
    `openai_loop._merge_tool_call_delta` 按 index 定位并累加，故此分片
    在两条原生/兼容链路上是**同一种可合并单元**，不另立契约。
    """
    # id 只在**首片**（携带 name 的那一片）上给：下游 `_merge_tool_call_delta`
    # 见到非空 id 就覆盖，后续片带 id 会把首片声明的真实调用 id 冲掉。
    name = state.get("name") or ""
    chunk = _llm_response(model=model)
    chunk.tool_calls = [
        {
            "index": index,
            "id": (state.get("id") or "") or (f"call_{index}" if name else ""),
            "type": "function",
            "function": {"name": name, "arguments": arguments},
        }
    ]
    return chunk


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
    data: dict, model: str, pending: typing.Optional[dict] = None
) -> typing.Tuple[typing.List[LLMResponse], str]:
    """单个 Anthropic 事件 → (0..n 个 LLMResponse, 更新后的 model)

    pending（可选）是流式 tool_use 块的累积槽：index → {id, name, partial_json}。
    传入时，tool_use 起始块与 input_json_delta 分片会产出可合并的 tool_call 分片。
    """
    etype = data.get("type")
    if etype == "message_start":
        message = data.get("message") or {}
        model = str(message.get("model") or "")
        return [_llm_response(model=model)], model
    if etype == "content_block_start" and pending is not None:
        block = data.get("content_block") or {}
        if block.get("type") == "tool_use":
            # 分片的 index 必须是「第几条工具调用」的序号（下游
            # `_merge_tool_call_delta` 的定位键），而不是 content block 下标 ——
            # 二者在「前面还有 thinking/text 块」时并不相等。
            blocks = pending.setdefault("blocks", {})
            ordinal = len(pending.setdefault("order", []))
            state = {
                "id": block.get("id") or "",
                "name": block.get("name") or "",
                "partial_json": "",
                "ordinal": ordinal,
            }
            blocks[data.get("index")] = state
            pending["order"].append(data.get("index"))
            # 首片：带 id/name 声明这条调用的身份
            return [_toolCallFragment(ordinal, state, model, "")], model
        return [], model
    if etype == "content_block_stop" and pending is not None:
        # 工具块收束：身份与参数均已在前面的分片中发出，此处只清累积槽，
        # 不重复发一条完整调用（否则下游按 index 合并会重复拼接参数）。
        state = (pending.get("blocks") or {}).pop(data.get("index"), None)
        if state is not None and data.get("index") in (pending.get("order") or []):
            pending["order"].remove(data.get("index"))
        return [], model
    if etype == "content_block_delta" and pending is not None:
        delta = data.get("delta") or {}
        if delta.get("type") == "input_json_delta":
            state = (pending.get("blocks") or {}).get(data.get("index"))
            if state is not None:
                piece = delta.get("partial_json") or ""
                state["partial_json"] = (state["partial_json"] or "") + piece
                # 后续片：id/name 留空（避免下游重复拼接），只带 arguments 增量
                return [
                    _toolCallFragment(state.get("ordinal", 0), {"id": "", "name": ""}, model, piece)
                ], model
            return [], model
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
    pending: dict = {}
    async for ev in events:
        data = _coerce_sse_line(ev) if isinstance(ev, str) else ev
        if not isinstance(data, dict):
            continue
        chunks, model = _handle_anthropic_event(data, model, pending)
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
    tool_blocks: list = []
    for part in parts:
        if isinstance(part.get("functionCall"), dict):
            # 原实现按「无 text 即跳过」把 functionCall part 一并丢弃：配了原生
            # Gemini provider 时函数调用能力消失且无任何痕迹。现按契约归一。
            tool_blocks.append(part)
            continue
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
    tool_calls = toOpenAIToolCalls(tool_blocks)
    if tool_calls and finish == "stop":
        # 与 OpenAI 兼容链路同一契约：带工具调用时的 finish_reason 是 tool_calls
        finish = "tool_calls"
    resp = _llm_response(
        content="".join(texts),
        reasoning_content="".join(thinkings) or None,
        model=str(data.get("modelVersion") or ""),
        finish_reason=finish,
        usage=usage,
    )
    resp.tool_calls = tool_calls
    return resp
