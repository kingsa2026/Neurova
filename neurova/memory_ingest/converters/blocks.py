# -*- coding: utf-8 -*-
"""会话 JSONL 族的 content 块词汇：text / thinking / toolCall。

这一族的调用块没有结果块（1.x 日志只记调用），参数键叫 arguments；与表族的 tool_call/input
不同名，所以词汇在此收敛一次，块型对上层只暴露"正文段"和"调用"两种事件。
"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from typing import Any, List, Tuple


@dataclass(frozen=True)
class ContentEvent:
    kind: str                      # assistant_message | tool_call
    text: str = ""
    tool_call_id: str = ""
    tool_name: str = ""
    tool_input: str = ""
    reasoning: str = ""


def split_content(content: Any) -> Tuple[List[ContentEvent], Counter]:
    """源 content → 交替的正文段与工具事件，外加装不下的块型计数。

    块型词表按实测并集：text / thinking / toolCall（arguments）/ tool_use（input）/
    tool_result（output 块数组）。file 与 image 需要包内 media 存储，先申报不落包。
    """
    if isinstance(content, str):
        return ([ContentEvent("assistant_message", text=content)] if content.strip()
                else []), Counter()
    if not isinstance(content, list):
        return [], Counter({"<非列表>": 1}) if content not in (None, "") else Counter()

    events: List[ContentEvent] = []
    run: List[str] = []
    pending: List[str] = []
    strays: Counter = Counter()
    for block in content:
        if not isinstance(block, dict):
            strays["<非对象>"] += 1
            continue
        btype = block.get("type")
        if btype == "text":
            run.append(str(block.get("text") or ""))
        elif btype == "thinking":
            pending.append(str(block.get("thinking") or ""))
        elif btype in ("toolCall", "tool_use"):
            _flush(events, run, pending)
            arguments = block.get("arguments") if "arguments" in block else block.get("input")
            events.append(ContentEvent("tool_call",
                                       tool_call_id=str(block.get("id") or ""),
                                       tool_name=str(block.get("name") or ""),
                                       tool_input=json.dumps(arguments or {}, ensure_ascii=False),
                                       reasoning=_drain(pending)))
        elif btype == "tool_result":
            _flush(events, run, pending)
            events.append(ContentEvent("tool_result",
                                       tool_call_id=str(block.get("id") or ""),
                                       tool_name=str(block.get("name") or ""),
                                       text=_output_text(block.get("output")),
                                       reasoning=_drain(pending)))
        else:
            strays[str(btype or "<无类型>")] += 1
    _flush(events, run, pending)
    if pending and events:
        last = events[-1]
        events[-1] = ContentEvent(last.kind, text=last.text, tool_call_id=last.tool_call_id,
                                  tool_name=last.tool_name, tool_input=last.tool_input,
                                  reasoning=last.reasoning + _drain(pending))
    return events, strays


def _output_text(output: Any) -> str:
    if isinstance(output, str):
        return output
    if not isinstance(output, list):
        return ""
    return "".join(str(block.get("text") or "") for block in output if isinstance(block, dict))


def _flush(events: List[ContentEvent], run: List[str], pending: List[str]) -> None:
    text = "".join(run)
    del run[:]
    if text or pending:
        events.append(ContentEvent("assistant_message", text=text, reasoning=_drain(pending)))


def _drain(items: List[str]) -> str:
    text = "".join(items)
    del items[:]
    return text
