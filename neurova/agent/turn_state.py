# -*- coding: utf-8 -*-
"""轮次级请求状态门面（Phase 1，拆分方案 docs/04-plans/agent-core-decomposition-plan.md）。

职责与边界
==========
轮次级状态（本轮用户输入/身份、工具展示消息、工具事件、思考过程、
会话轮次号）的实际存储自审计 P0-B1 起就在 ``neurova.core.turn_context``
的 ContextVar 中（并发请求天然隔离，会话轮次号按会话单调）。本模块把
Agent 上那 17 个"轮次级显式 API"（P3-c）的**实现**从 agent_core 迁到
这里，成为 ``TurnState`` 门面对象：

- Agent 持有 ``self.turn_state = TurnState()``，同名方法/property 一行
  转发——对 deep modules（chat_pipeline / tool_executor / loops /
  post_chat_pipeline）与 tests 的契约名零变化；
- ``set_request_identity`` 的 user_id 缺省落 "default" 语义在此实现
  （与 P0-B1 前 chat_pipeline 写入语义一致）；
- ``session_id`` property 保持 "未设置返回空串" 的读取契约。

硬约束（方案 §4）：
- 本模块**不得** import agent_core（组合方向 agent_core -> agent/turn_state）；
- 签名冻结：方法名/参数/返回值与迁移前逐字一致（契约快照守卫锁定）。

getattr 旧契约（P0-B1 时代读取路径，由 Agent property 转发保障）：
- ``getattr(agent, "_current_user_input", "")``   — tool_executor
- ``getattr(agent, "turn_count", 0)``             — tool_executor / post_chat
- ``getattr(agent, "current_reasoning", None)``   — channels / post_chat
"""

# 注意：不用 ``from __future__ import annotations``——保持 inspect.signature
# 渲染出真实注解（与迁移前 Agent API 及契约快照逐字一致，方案硬约束 1）。
from typing import Any, Dict, List, Optional

from neurova.core.turn_context import (
    append_turn_tool_event,
    append_turn_tool_messages,
    get_turn_count,
    get_turn_reasoning,
    get_turn_session_id,
    get_turn_tool_events,
    get_turn_tool_messages_snapshot,
    get_turn_user_id,
    get_turn_user_input,
    increment_turn_count as _tc_increment,
    reset_turn_tool_messages,
    set_turn_reasoning,
    set_turn_user_input,
)


class TurnState:
    """一轮请求的状态门面（无实例字段；实存于 turn_context 的 ContextVar）。"""

    # ── 请求身份 ────────────────────────────────────────────────

    def set_request_identity(
        self,
        user_input: str,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> None:
        """记录本轮请求级身份（工具层三层隔离/蜂群事件广播依赖）。

        审计 P0-B1：轮次级状态迁 ContextVar——Agent 是单例，实例属性存储
        在并发请求下互踩（请求 B 覆盖请求 A 的身份/工具消息）。
        user_id 缺省落 "default"（与原 chat_pipeline 写入语义一致）。
        """
        from neurova.core.turn_context import set_turn_identity

        set_turn_identity(user_input, session_id, user_id)

    @property
    def current_user_input(self) -> Optional[str]:
        from neurova.core.turn_context import get_turn_user_input

        return get_turn_user_input()

    @property
    def current_session_id(self) -> Optional[str]:
        from neurova.core.turn_context import get_turn_session_id

        return get_turn_session_id()

    @property
    def current_user_id(self) -> Optional[str]:
        from neurova.core.turn_context import get_turn_user_id

        return get_turn_user_id()

    # ── 思考过程 ────────────────────────────────────────────────

    @property
    def current_reasoning(self) -> Optional[str]:
        from neurova.core.turn_context import get_turn_reasoning

        return get_turn_reasoning()

    def set_current_reasoning(self, reasoning: Optional[str]) -> None:
        """记录本轮思考过程（流式聚合 / 非流式单值共用；P0-B1 迁 ContextVar）"""
        from neurova.core.turn_context import set_turn_reasoning

        set_turn_reasoning(reasoning)

    # ── 工具展示消息（_tool_messages_list 的 ContextVar 形态）──

    def reset_tool_messages(self) -> None:
        """清空本轮工具展示记录（轮次开始时调用；P0-B1 迁 ContextVar）"""
        from neurova.core.turn_context import reset_turn_tool_messages

        reset_turn_tool_messages()

    def append_tool_messages(self, records: List[Dict[str, Any]]) -> None:
        """追加工具调用/结果展示记录（原生事件合并 + 并行回装共用入口；P0-B1 迁 ContextVar）"""
        from neurova.core.turn_context import append_turn_tool_messages

        append_turn_tool_messages(records)

    def get_tool_messages_snapshot(self) -> List[Dict[str, Any]]:
        """工具展示记录快照（副本，外部改动不回写）——公有形态"""
        from neurova.core.turn_context import get_turn_tool_messages_snapshot

        return get_turn_tool_messages_snapshot()

    def collect_tool_messages(self) -> List[Dict[str, Any]]:
        """私有名 ``_collect_tool_messages`` 的公有实现（快照语义同上）。"""
        return self.get_tool_messages_snapshot()

    # ── 工具事件（降级/异常账本）──────────────────────────────

    def append_tool_event(self, event: Dict[str, Any]) -> None:
        """追加工具降级/异常事件（openai_loop 降级路径）；损坏态自愈为列表（P0-B1 迁 ContextVar）"""
        from neurova.core.turn_context import append_turn_tool_event

        append_turn_tool_event(event)

    @property
    def tool_events(self) -> List[Dict[str, Any]]:
        """工具降级/异常事件只读视图（P0-B1 迁 ContextVar 后的对偶读 API）"""
        from neurova.core.turn_context import get_turn_tool_events

        return get_turn_tool_events()

    # ── 轮次计数与会话 ─────────────────────────────────────────

    def increment_turn_count(self) -> int:
        """轮次计数 +1，返回新值（P0-B1 迁 ContextVar）"""
        from neurova.core.turn_context import increment_turn_count

        return increment_turn_count()

    @property
    def turn_count(self) -> int:
        """当前轮次（读取方 getattr(agent,"turn_count") 的契约名；P0-2 失配修复）"""
        from neurova.core.turn_context import get_turn_count

        return get_turn_count()

    @property
    def session_id(self) -> str:
        """当前会话 id（EKB 溯源等读取方契约名；P0-B1 迁 ContextVar）"""
        from neurova.core.turn_context import get_turn_session_id

        return str(get_turn_session_id() or "")
