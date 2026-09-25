# -*- coding: utf-8 -*-
"""会话内容的块词表：正文段 / 思考 / 调用 / 结果 / 媒体，一家一份的规则收敛在此。

多家落盘对同一件事用不同键名（调用块 toolCall|toolUse|tool_use|functionCall、结果关联键
五形、正文键 output|content|text），逐家各写一遍就会从第二家开始漏。这里按并集收敛一次，
对上层只暴露"正文段""调用""结果"三种事件外加已落包的媒体引用；认不出的块型一律计数申报。
"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

from neurova.memory_ingest.bundle.media import MEDIA_BLOCK_TYPES

__all__ = ("ContentEvent", "MEDIA_BLOCK_TYPES", "split_content")

# 调用块四形，参数键两形
CALL_BLOCK_TYPES = ("toolCall", "toolUse", "tool_use", "functionCall")
# 结果块：两形同名，另有 <前缀>_tool_result（工具通道各自加前缀）
RESULT_BLOCK_TYPES = ("tool_result", "toolResult")
RESULT_BLOCK_SUFFIX = "_tool_result"
# 关联键与正文键：源里用哪一形就用哪一形，缺省不代表源丢了内容
CALL_ID_KEYS = ("id", "tool_use_id", "tool_call_id", "toolUseId", "toolCallId")
RESULT_TEXT_KEYS = ("output", "content", "text")


@dataclass(frozen=True)
class ContentEvent:
    kind: str                      # assistant_message | tool_call | tool_result
    text: str = ""
    tool_call_id: str = ""
    tool_name: str = ""
    tool_input: str = ""
    tool_state: str = ""           # 源里声明的失败态（结果块 is_error）
    reasoning: str = ""
    reasoning_state: str = ""      # 源把思考落成密文时标 opaque，不与"没有思考"混为一谈
    blocks: Tuple[Dict[str, Any], ...] = ()   # 已落包的媒体引用


def split_content(content: Any, sink=None) -> Tuple[List[ContentEvent], Counter]:
    """源 content → 交替的正文段、工具事件与媒体引用；第二项是申报用计数（键即 manifest 字段名）。

    没给 sink 或取不到字节就计数申报，绝不静默丢。
    """
    if isinstance(content, str):
        return ([ContentEvent("assistant_message", text=content)] if content.strip()
                else []), Counter()
    if not isinstance(content, list):
        return [], Counter({"<非列表>": 1}) if content not in (None, "") else Counter()

    events: List[ContentEvent] = []
    run: List[str] = []
    pending: List[str] = []
    media: List[Dict[str, Any]] = []
    lost = [0]
    opaque = [False]
    strays: Counter = Counter()
    for block in content:
        if not isinstance(block, dict):
            strays["blocks:<非对象>"] += 1
            continue
        btype = block.get("type")
        if btype in MEDIA_BLOCK_TYPES:
            _collect_media(block, sink, media, lost)
        elif btype == "text":
            run.append(str(block.get("text") or ""))
        elif btype == "thinking":
            pending.append(str(block.get("thinking") or ""))
        elif btype == "redacted_thinking":
            opaque[0] = True
        elif btype in CALL_BLOCK_TYPES:
            _flush(events, run, pending, media, opaque)
            arguments = block.get("arguments") if "arguments" in block else block.get("input")
            events.append(ContentEvent("tool_call",
                                       tool_call_id=_call_id(block),
                                       tool_name=str(block.get("name") or ""),
                                       tool_input=json.dumps(arguments or {}, ensure_ascii=False),
                                       reasoning=_drain(pending),
                                       reasoning_state=_drain_state(opaque)))
        elif _is_result_block(btype):
            _flush(events, run, pending, media, opaque)
            inner: List[Dict[str, Any]] = []
            events.append(ContentEvent("tool_result",
                                       tool_call_id=_call_id(block),
                                       tool_name=str(block.get("name") or ""),
                                       text=_result_body(block, sink, inner, lost),
                                       tool_state="error" if block.get("is_error") else "",
                                       reasoning=_drain(pending),
                                       reasoning_state=_drain_state(opaque),
                                       blocks=tuple(inner)))
        else:
            strays[f"blocks:{btype or '<无类型>'}"] += 1
    _flush(events, run, pending, media, opaque)
    if pending and events:
        events[-1] = _merge(events[-1], _drain(pending))
    if lost[0]:
        strays["media:不可达"] += lost[0]
    return events, strays


def _is_result_block(btype: Any) -> bool:
    return btype in RESULT_BLOCK_TYPES or (isinstance(btype, str)
                                           and btype.endswith(RESULT_BLOCK_SUFFIX))


def _call_id(block: Dict[str, Any]) -> str:
    """调用关联键五形：判错的代价是结果找不到它的调用，链断在包外看不见的地方。"""
    for key in CALL_ID_KEYS:
        value = str(block.get(key) or "").strip()
        if value:
            return value
    return ""


def _result_body(block: Dict[str, Any], sink, media: List[Dict[str, Any]],
                 lost: List[int]) -> str:
    """结果正文三形：整段字符串，或块数组（数组里可以夹图，图要落包不能只取文字）。"""
    for key in RESULT_TEXT_KEYS:
        if key not in block:
            continue
        value = block[key]
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            return "".join(_nested_text(item, sink, media, lost) for item in value)
    return ""


def _nested_text(item: Any, sink, media: List[Dict[str, Any]], lost: List[int]) -> str:
    if isinstance(item, str):
        return item
    if not isinstance(item, dict):
        return ""
    if item.get("type") in MEDIA_BLOCK_TYPES:
        _collect_media(item, sink, media, lost)
        return ""
    return "".join(str(item.get(key) or "") for key in ("text", "thinking"))


def _collect_media(block: Dict[str, Any], sink, media: List[Dict[str, Any]],
                   lost: List[int]) -> None:
    """媒体块 → 包内引用；解不出字节就计数，交上层申报。"""
    btype = str(block.get("type"))
    ref = sink.resolve(block) if sink is not None else None
    if ref is None:
        lost[0] += 1
        return
    media.append(dict(ref, type="image" if btype == "data" else btype))


def _merge(event: ContentEvent, reasoning: str) -> ContentEvent:
    return ContentEvent(event.kind, text=event.text, tool_call_id=event.tool_call_id,
                        tool_name=event.tool_name, tool_input=event.tool_input,
                        tool_state=event.tool_state, reasoning=event.reasoning + reasoning,
                        reasoning_state=event.reasoning_state, blocks=event.blocks)


def _flush(events: List[ContentEvent], run: List[str], pending: List[str],
           media: List[Dict[str, Any]], opaque: List[bool]) -> None:
    text = "".join(run)
    del run[:]
    # 密文思考也是"有推理、读不出"：只在正文/调用/媒体上判空，这一行就整条消失
    if text or pending or media or opaque[0]:
        events.append(ContentEvent("assistant_message", text=text, reasoning=_drain(pending),
                                   reasoning_state=_drain_state(opaque), blocks=tuple(media)))
        del media[:]


def _drain(items: List[str]) -> str:
    text = "".join(items)
    del items[:]
    return text


def _drain_state(flag: List[bool]) -> str:
    value = "opaque" if flag[0] else ""
    flag[0] = False
    return value
