# -*- coding: utf-8 -*-
"""会话 JSONL 族的 content 块词汇：text / thinking / toolCall / tool_use / tool_result / 媒体。

这一族的调用块参数键叫 arguments 或 input，结果可能是块也可能是独立行；与表族不同名，所以
词汇在此收敛一次，块型对上层只暴露"正文段""调用""结果"三种事件外加媒体引用。
"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from neurova.memory_ingest.bundle.media import MEDIA_BLOCK_TYPES

__all__ = ("ContentEvent", "MEDIA_BLOCK_TYPES", "split_content")


@dataclass(frozen=True)
class ContentEvent:
    kind: str                      # assistant_message | tool_call | tool_result
    text: str = ""
    tool_call_id: str = ""
    tool_name: str = ""
    tool_input: str = ""
    reasoning: str = ""
    blocks: Tuple[Dict[str, Any], ...] = ()   # 已落包的媒体引用


def split_content(content: Any, sink=None) -> Tuple[List[ContentEvent], Counter]:
    """源 content → 交替的正文段、工具事件与媒体引用；第二项是申报用计数（键即 manifest 字段名）。

    块型词表按实测并集：text / thinking / toolCall（arguments）/ tool_use（input）/
    tool_result（output 块数组）/ image / file / data（媒体，交给 sink 落包）。
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
    strays: Counter = Counter()
    for block in content:
        if not isinstance(block, dict):
            strays["blocks:<非对象>"] += 1
            continue
        btype = block.get("type")
        if btype in MEDIA_BLOCK_TYPES:
            ref = _media_ref(block, sink)
            if ref is None:
                lost[0] += 1
            else:
                media.append(dict(ref, type=btype if btype != "data" else "image"))
        elif btype == "text":
            run.append(str(block.get("text") or ""))
        elif btype == "thinking":
            pending.append(str(block.get("thinking") or ""))
        elif btype in ("toolCall", "tool_use"):
            _flush(events, run, pending, media)
            arguments = block.get("arguments") if "arguments" in block else block.get("input")
            events.append(ContentEvent("tool_call",
                                       tool_call_id=str(block.get("id") or ""),
                                       tool_name=str(block.get("name") or ""),
                                       tool_input=json.dumps(arguments or {}, ensure_ascii=False),
                                       reasoning=_drain(pending)))
        elif btype == "tool_result":
            _flush(events, run, pending, media)
            events.append(ContentEvent("tool_result",
                                       tool_call_id=str(block.get("id") or ""),
                                       tool_name=str(block.get("name") or ""),
                                       text=_output_text(block.get("output")),
                                       reasoning=_drain(pending)))
        else:
            strays[f"blocks:{btype or '<无类型>'}"] += 1
    _flush(events, run, pending, media)
    if pending and events:
        events[-1] = _merge(events[-1], _drain(pending))
    if lost[0]:
        strays["media:不可达"] += lost[0]
    return events, strays


def _media_ref(block: Dict[str, Any], sink) -> Optional[Dict[str, Any]]:
    """媒体块 → 包内引用。没有 sink（或解不出字节）就返回 None，由上层申报条数。"""
    return sink.resolve(block) if sink is not None else None


def _merge(event: ContentEvent, reasoning: str) -> ContentEvent:
    return ContentEvent(event.kind, text=event.text, tool_call_id=event.tool_call_id,
                        tool_name=event.tool_name, tool_input=event.tool_input,
                        reasoning=event.reasoning + reasoning, blocks=event.blocks)


def _output_text(output: Any) -> str:
    if isinstance(output, str):
        return output
    if not isinstance(output, list):
        return ""
    return "".join(str(block.get("text") or "") for block in output if isinstance(block, dict))


def _flush(events: List[ContentEvent], run: List[str], pending: List[str],
           media: List[Dict[str, Any]]) -> None:
    text = "".join(run)
    del run[:]
    if text or pending or media:
        events.append(ContentEvent("assistant_message", text=text, reasoning=_drain(pending),
                                   blocks=tuple(media)))
        del media[:]


def _drain(items: List[str]) -> str:
    text = "".join(items)
    del items[:]
    return text
