# -*- coding: utf-8 -*-
"""Ingest Bundle 的记录类型：各家落盘方言的最大公约数（设计 §3）。

字段取舍来自取证矩阵：工具调用与结果在所有被调研的 harness 里都是跨行关联，因此这里保持
扁平事件行；推理正文可能是密文或不可得，用 reasoning_state 显式区分，不用空串混淆。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

VALID_KINDS = ("user_message", "assistant_message", "tool_call", "tool_result",
               "system", "compact_summary")
VALID_ROLE_KINDS = {
    "user_message": "user", "assistant_message": "assistant", "tool_call": "assistant",
    "tool_result": "tool", "system": "system", "compact_summary": "assistant",
}
VALID_REASONING_STATES = ("text", "opaque", "absent")


@dataclass(frozen=True)
class TranscriptRecord:
    session_id: str
    seq: int
    kind: str
    ts: str
    identity_key: str
    role: str = ""
    content_blocks: Tuple[Dict[str, Any], ...] = ()
    tool_call_id: str = ""
    tool_name: str = ""
    tool_state: str = ""
    reasoning_state: str = "absent"
    reasoning_text: str = ""
    parent_seq: Optional[int] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind not in VALID_KINDS:
            raise ValueError(f"未知 kind: {self.kind!r}")
        # 包内读回是 list、内存构造是 tuple；归一后同一条记录才谈得上相等（幂等比对靠这个）
        object.__setattr__(self, "content_blocks", tuple(self.content_blocks))
        if self.reasoning_state not in VALID_REASONING_STATES:
            raise ValueError(f"未知 reasoning_state: {self.reasoning_state!r}")

    def text(self) -> str:
        return "".join(
            str(block.get("text", "")) for block in self.content_blocks
            if block.get("type") == "text"
        )


@dataclass(frozen=True)
class MemoryRecord:
    identity_key: str
    content: str
    memory_type: str
    category: str
    origin: str
    importance: float
    ts: str
    temperature: float = 100.0
    tags: Tuple[str, ...] = ()
    source_ref: str = ""
    supersedes: str = ""

    def __post_init__(self) -> None:
        # 与 TranscriptRecord 同一条规矩：包内读回是 list、内存构造是 tuple，
        # 不归一则"同一条记录"无从相等，幂等比对会漏判重复导入。
        object.__setattr__(self, "tags", tuple(self.tags))
