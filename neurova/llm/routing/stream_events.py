# -*- coding: utf-8 -*-
"""流分片载荷归一（R4，参照系 ad 追平批二）。

流分片有两种形态并存：LLMResponse 样对象（getattr 可取）与裸 dict
（网关/桩直出）。载荷判类与取值收敛到本模块单一入口，消费方
（multi_model_client 的计数/空响应判定/后续事件面）不再各写一份
getattr + dict 兜底。

事件词表按本仓消费方实际需要取最小集（不追对方 15 类全量）：
TEXT / REASONING / TOOL_CALLS / USAGE / STOP / ERROR / STATUS / OTHER。
"""
from __future__ import annotations

import enum
from typing import Any, Set


class StreamEventKind(enum.Enum):
    """流分片载荷类别（最小集）。"""

    TEXT = "text"
    REASONING = "reasoning"
    TOOL_CALLS = "tool_calls"
    USAGE = "usage"
    STOP = "stop"
    ERROR = "error"
    STATUS = "status"
    OTHER = "other"


def chunkField(chunk: Any, key: str, default: Any = None) -> Any:
    """dict/对象双形态取值（流分片单一取值入口）。"""
    if isinstance(chunk, dict):
        return chunk.get(key, default)
    return getattr(chunk, key, default)


def chunkPayloadKinds(chunk: Any) -> Set[StreamEventKind]:
    """判定一个分片携带的载荷类别集合（可多载：内容+usage 同片）。"""
    kinds: Set[StreamEventKind] = set()
    if chunkField(chunk, "tool_calls"):
        kinds.add(StreamEventKind.TOOL_CALLS)
    if chunkField(chunk, "content"):
        kinds.add(StreamEventKind.TEXT)
    if chunkField(chunk, "reasoning_content"):
        kinds.add(StreamEventKind.REASONING)
    if chunkField(chunk, "usage"):
        kinds.add(StreamEventKind.USAGE)
    if chunkField(chunk, "finish_reason"):
        kinds.add(StreamEventKind.STOP)
    return kinds
