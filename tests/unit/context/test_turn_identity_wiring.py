# -*- coding: utf-8 -*-
"""T-03b：装配入口必须读**已在跑**的每轮会话身份单源（Issue #90 工单 §4bis）。

症状（探针 P2 形状一，实测）：两个普通单聊会话先后超预算折叠时，后一个会话的
视图首条仍是前一个会话的摘要；同一条轨迹换成两个不同协作房间则不串台
（形状二 = False）→ 键机制本身有效，坏在**身份来源**。

根因不是"漏传一个参数"，是**造了第二条通道却没用现成的那条**：

| 环节 | 现状 |
|---|---|
| 构造期身份 | `ContextOrchestrator(a, use_pool=..., auto_tag=...)` 不传 session_id |
| 形参入口 | `build_context(chat_collab, chat_room_id)` 无 session_id 形参 |
| 轮内赋值 | `_turn_room_id = chat_room_id or (self._session_id or "")`，而 `chat_room_id` **只在协作轮非空** |

三条通道全空 → 键恒 `direct`。而本轮真实的会话身份一直存在：`ChatPipeline`
每轮把身份写进 `core.turn_context` 的 ContextVar，读法就是
`agent.current_session_id`（真 Agent 的 `TurnState` 契约名），后链已在用它。

所以本单的修法是**让装配入口改读已在跑的单源**，不是新增形参造第二条通道
（修复教义第 6 条：参数与口径只允许一处定义）。

同一根因的第二命中点（必须同批，否则半接）：`turn_session` 在非协作轮把
`None` 写进 `pool.session_id`，连带三处失效 —— 条目 `metadata["session_id"]`
缺失、`ContextPool.query()` 的"本会话优先"退化、写穿持久台账的行 `session_id`
列为 NULL。

防回归纪律：用例走**生产构造面**（与 `agent_core` 同型，不传 session_id），
身份只经生产单源 `turn_context.set_turn_identity` 给；**禁止**测试手工传
`session_id=` 建构造器 —— 那正是掩盖本缺陷的写法。
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from neurova.core.turn_context import get_turn_session_id, set_turn_identity  # noqa: E402


class _ProductionShapedAgent:
    """与 `agent_core` 构造编排器时同型：不传 session_id。

    `current_session_id` 经**生产同一份** ContextVar 读取（真 Agent 的
    `TurnState.current_session_id` 就是这一行），而不是本文件自造的字段。
    """

    def __init__(self):
        self.config = MagicMock()
        self.config.name = "t"
        self.config.agent_id = "a1"
        self.config.constitution = ""
        self.config.behavior_rules = []
        self.config.llm_model = "test-model"
        self.config.enable_auto_tagging = False
        self.memory_manager = MagicMock()
        self.context_builder = MagicMock()
        self.tool_router = None
        self._skill_registry = None
        self.soul = "测试助手"
        self.personality = ""
        self.conversation_history = []
        self.growth_log_manager = MagicMock()
        self.user_id = "u1"
        self.agent_id = "a1"

    @property
    def current_session_id(self):
        return get_turn_session_id()


def _orchestrator():
    from neurova.context.orchestrator import ContextOrchestrator

    return ContextOrchestrator(_ProductionShapedAgent(), use_pool=True)


async def _build(orch, *, user_input, history, collab=False, room_id=""):
    with patch.object(orch, "get_tools_description", new_callable=AsyncMock) as tools:
        tools.return_value = "工具描述"
        return await orch.build_context(
            user_input=user_input,
            session_context=history,
            relevant_memories=[],
            chat_collab=collab,
            chat_room_id=room_id,
        )


def _long_history(topic: str):
    return [
        {"role": "user", "content": f"{topic}第{i}条：" + topic * 40}
        for i in range(12)
    ]


class TestWindowCacheKeyReadsTurnIdentity:
    """折叠摘要缓存键必须读每轮身份单源，而不是恒退化到 `direct`。"""

    def test_window_cache_key_falls_back_to_turn_session(self):
        orch = _orchestrator()
        assert orch._resolve_window_cache_key() == "direct", (
            "无任何身份时才落 direct（本用例的前提）"
        )

        set_turn_identity("你好", session_id="sess-single-1", user_id="u1")
        assert orch._resolve_window_cache_key() == "sess-single-1", (
            "装配入口没读每轮身份单源 —— 键仍退化："
            f"{orch._resolve_window_cache_key()!r}。`agent.current_session_id` "
            "一直在跑（ChatPipeline 每轮把它写进 turn_context）"
        )

    def test_construct_time_identity_still_wins_over_turn_source(self):
        """回落链次序：房间 id → 构造期显式覆盖 → 每轮身份单源 → direct。"""
        from neurova.context.orchestrator import ContextOrchestrator

        orch = ContextOrchestrator(
            _ProductionShapedAgent(), use_pool=True, session_id="sess-explicit"
        )
        set_turn_identity("你好", session_id="sess-turn", user_id="u1")
        assert orch._resolve_window_cache_key() == "sess-explicit", (
            "构造期显式覆盖（测试/运维入口）被每轮身份单源盖掉——回落链次序错了"
        )

    @pytest.mark.asyncio
    async def test_two_direct_sessions_do_not_share_fold_summary(self):
        """探针 P2 形状一转绿：两个普通单聊会话不得共用一条摘要。"""
        orch = _orchestrator()
        orch._window_token_budget = 1200
        calls: list = []

        async def summarize(dropped, previous_summary=""):
            calls.append(len(dropped))
            return f"摘要{len(calls)}"

        orch._window_summarizer = summarize

        set_turn_identity("问 A", session_id="sess-one", user_id="u1")
        await _build(orch, user_input="继续 A", history=_long_history("量子计算"))

        set_turn_identity("问 B", session_id="sess-two", user_id="u1")
        view_b = await _build(orch, user_input="继续 B", history=_long_history("火星殖民"))

        keys = set(orch._window_compaction_cache)
        assert "sess-one" in keys and "sess-two" in keys, (
            f"两个单聊会话未分槽，缓存键={sorted(keys)} —— 身份没进装配入口"
        )
        joined = "\n".join(str(m.get("content", "")) for m in view_b)
        assert "量子计算" not in joined, "单聊 B 的视图注入了单聊 A 的折叠摘要（跨会话串台）"

    @pytest.mark.asyncio
    async def test_fold_cache_bounded_across_sessions(self):
        """键数自此真正开始增长 → 槽位上限必须同批生效（否则把串台换成无界增长）。"""
        orch = _orchestrator()
        orch._window_token_budget = 1200

        async def summarize(dropped, previous_summary=""):
            return "摘要"

        orch._window_summarizer = summarize
        for index in range(orch._WINDOW_CACHE_SLOTS + 4):
            set_turn_identity("继续", session_id=f"sess-{index}", user_id="u1")
            await _build(orch, user_input="继续", history=_long_history(f"会话{index}"))

        assert len(orch._window_compaction_cache) <= orch._WINDOW_CACHE_SLOTS, (
            f"缓存槽无上限：{len(orch._window_compaction_cache)}"
        )


class TestPoolIdentityFollowsTurnSession:
    """第二命中点：`pool.session_id` 与条目 metadata 必须随每轮身份。"""

    @pytest.mark.asyncio
    async def test_pool_session_id_follows_turn_identity_on_direct_turns(self):
        orch = _orchestrator()
        set_turn_identity("你好", session_id="sess-pool-1", user_id="u1")

        await _build(
            orch,
            user_input="普通单聊问题",
            history=[{"role": "user", "content": "单聊内容：家里地址是某某路"}],
            collab=False,
        )

        assert orch.context_pool.session_id == "sess-pool-1", (
            "非协作轮把 None 写进 pool.session_id —— 条目 metadata / query 的本会话优先 / "
            "持久台账 session 列三处同时失效"
        )
        archived = [
            c for c in orch.context_pool.get_contexts() if "家里地址" in str(c.content)
        ]
        assert archived, "单聊内容未入池——本用例没打到归档路径"
        assert (archived[0].metadata or {}).get("session_id") == "sess-pool-1"

    @pytest.mark.asyncio
    async def test_room_turn_keeps_room_identity_over_turn_session(self):
        """正向锁：协作轮的房间身份优先于每轮 session（不得被覆盖成单聊 id）。"""
        orch = _orchestrator()
        set_turn_identity("群聊", session_id="sess-plain", user_id="u1")

        await _build(
            orch,
            user_input="继续",
            history=[{"role": "user", "content": "群内容：项目代号是 ZEPHYR-9"}],
            collab=True,
            room_id="project_roomB",
        )

        assert orch.context_pool.session_id == "project_roomB", (
            "协作轮的房间身份被每轮 turn session 覆盖"
        )


class TestIdentitylessTurnIsVisible:
    """落到 `direct` 必须可见：静默共用槽就是本缺陷的形态，不能再犯。"""

    @pytest.mark.asyncio
    async def test_identityless_turn_is_counted_not_silent(self):
        orch = _orchestrator()

        await _build(
            orch,
            user_input="无身份轮",
            history=[{"role": "user", "content": "没有身份的两条消息"}],
            collab=False,
        )

        readout = orch.get_context_health()["turn_identity"]
        assert readout["identityless"] >= 1, (
            f"无身份轮未被计数：{readout} —— 静默共用 direct 槽正是本缺陷的形态"
        )
        assert readout["last_key"] == "direct"

    @pytest.mark.asyncio
    async def test_identified_turn_is_not_counted_as_identityless(self):
        orch = _orchestrator()
        set_turn_identity("你好", session_id="sess-visible-1", user_id="u1")

        await _build(
            orch,
            user_input="有身份轮",
            history=[{"role": "user", "content": "有身份的消息"}],
            collab=False,
        )

        readout = orch.get_context_health()["turn_identity"]
        assert readout["identityless"] == 0, f"有身份轮被误报为无身份：{readout}"
        assert readout["last_key"] == "sess-visible-1"


class TestBudgetReadoutUsesTurnIdentity:
    """放大视角：同一身份契约的**其他消费方**一并收口（教义第 5 条）。

    `get_token_budget()` 的 `used_tokens` 原先按构造期初值 `self._session_id`
    取会话快照，而该初值在生产恒 `None` → 读到 agent 级快照（别的会话的上下文），
    面板显示的是串了会话的数字。身份消费方只允许一处解析，故同批改指回落链。
    """

    def test_budget_readout_reads_turn_session_snapshot(self):
        from neurova.context.composition import measure_composition

        orch = _orchestrator()
        # 会话 B 自己的快照（消息多 → token 多）
        measure_composition(
            "a1",
            [{"role": "user", "content": "会话 B 的 prompt 正文 " * 40}],
            [],
            session_id="sess-budget-b",
        )
        # 再用**另一个会话**（agent 级）写一份更小的快照，把两条路读数拉开
        measure_composition("a1", [{"role": "user", "content": "短"}], [], session_id=None)
        others = orch.get_token_budget()["used_tokens"]

        set_turn_identity("你好", session_id="sess-budget-b", user_id="u1")
        mine = orch.get_token_budget()["used_tokens"]
        assert mine != others and mine > others, (
            "预算读数没按本轮身份取快照 —— 读的是构造期初值（生产恒 None）→ "
            f"拿到的是别的会话的数字：{mine} vs 他会话 {others}"
        )
