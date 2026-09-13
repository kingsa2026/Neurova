# -*- coding: utf-8 -*-
"""SSE 事件 item 化映射器（P1-1，Codex item 语义对齐）。

设计（docs/Neurova_Codex代码级对比_2026-09-14.md §2.1/P1-1）：
- 事件按 item 建模：item_started / item_delta / item_completed，每事件携带
  thread_id / turn_id / item_id / item_type —— 前端分区渲染与历史重放的
  结构地基；旧事件流原样保留（本映射器是旁路增强，兼容别名=零破坏）。
- item_type：agent_message（content delta）/ reasoning（reasoning delta）/
  tool_call / tool_result。
- 生命周期：首个 delta 开启 item（started 携带首片文本）；工具调用开启时
  收口未完成的 message/reasoning（Codex 语义：消息在工具前结束）；
  done/stopped/error 收口所有未闭合 item。
- usage/memory_progress/retry/approval_required/artifact 不进 item 语义
  （瞬态/记账类），映射为空。
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List

_STREAM_ITEM_TYPES = ("agent_message", "reasoning")
_TERMINAL_TYPES = ("done", "stopped", "error")


class ItemEventMapper:
    """(kind, data) 发射器事件 → item 结构事件的纯状态机（无 IO）。"""

    def __init__(self, thread_id: str, turn_id: str = "turn-1") -> None:
        self._thread_id = str(thread_id or "")
        self._turn_id = str(turn_id or "turn-1")
        self._seq = 0
        # 进行中的流式 item：item_type -> item_id
        self._open: Dict[str, str] = {}

    # ── 内部 ──────────────────────────────────────────────────────

    def _next_item_id(self) -> str:
        self._seq += 1
        return f"item-{self._seq}"

    def _make(
        self, ev_type: str, item_type: str, item_id: str, data: Dict[str, Any]
    ) -> Dict[str, Any]:
        return {
            "type": ev_type,
            "thread_id": self._thread_id,
            "turn_id": self._turn_id,
            "item_id": item_id,
            "item_type": item_type,
            "data": data,
        }

    def _close_open(self, out: List[dict], only: Iterable[str] = None) -> None:
        targets = tuple(only) if only else tuple(self._open.keys())
        for item_type in targets:
            item_id = self._open.pop(item_type, None)
            if item_id:
                out.append(self._make("item_completed", item_type, item_id, {}))

    def _stream_delta(self, out: List[dict], item_type: str, text: str) -> None:
        item_id = self._open.get(item_type)
        if item_id is None:
            item_id = self._next_item_id()
            self._open[item_type] = item_id
            out.append(self._make("item_started", item_type, item_id, {"text": text}))
        else:
            out.append(self._make("item_delta", item_type, item_id, {"text": text}))

    # ── 对外接口 ──────────────────────────────────────────────────

    def on_legacy_events(self, events: Iterable[Any]) -> List[dict]:
        """消费一批旧形态 SSE 事件，返回对应 item 事件（可能为空）。"""
        out: List[dict] = []
        for ev in events or []:
            if not isinstance(ev, dict):
                continue
            ev_type = str(ev.get("type") or "")
            if ev_type == "chunk":
                text = str(ev.get("content") or "")
                if text:
                    self._stream_delta(out, "agent_message", text)
            elif ev_type == "reasoning":
                text = str(ev.get("content") or "")
                if text:
                    self._stream_delta(out, "reasoning", text)
            elif ev_type == "tool_call":
                # 工具开始：收口未完成的流式 item（Codex：消息在工具前结束）
                self._close_open(out, only=_STREAM_ITEM_TYPES)
                data = {
                    "name": str(ev.get("name") or ""),
                    "arguments": str(ev.get("arguments") or "{}"),
                }
                if ev.get("task_name"):
                    data["task_name"] = str(ev["task_name"])
                out.append(self._make("item_started", "tool_call", self._next_item_id(), data))
            elif ev_type == "tool_result":
                out.append(
                    self._make(
                        "item_completed",
                        "tool_result",
                        self._next_item_id(),
                        {"name": str(ev.get("name") or ""), "result": ev.get("result")},
                    )
                )
            elif ev_type in _TERMINAL_TYPES:
                self._close_open(out)
        return out
