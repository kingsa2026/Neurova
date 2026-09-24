# -*- coding: utf-8 -*-
"""T-03b：每轮会话身份接到装配入口（Issue #90 工单 §4bis）。

## 红灯依据（改前实测，生产构造面）

`ContextOrchestrator._resolve_window_cache_key` 的回落链是
`_turn_room_id or self._session_id or "direct"`，而这两条通道在生产恒空：

- `_turn_room_id = chat_room_id or (self._session_id or "")`，`chat_room_id`
  **只在协作轮非空**（`chat_pipeline` 传参形状）；
- `agent_core` 构造编排器不传 `session_id` → `self._session_id` 恒 None。

于是键恒为 `'direct'`：两个普通单聊会话先后超预算折叠时共用同一槽，
后一个会话视图里注入了前一个会话的摘要（探针 P2 形状一）。实测：

```
sess_one -> cache keys: ['direct']
sess_two -> cache keys: ['direct']
池 session_id = None
条目 metadata.session_id = {'None'}
```

同一根因的**第二命中点**：`turn_session = chat_room_id or self._session_id or None`
→ 非协作轮把 None 写进 `pool.session_id`，连带条目 `metadata["session_id"]` 缺失、
`ContextPool.query()` 的本会话优先排序退化、写穿台账的行 `session_id` 列为 NULL。

## 修法（根因处，不新造通道）

本轮真实身份**一直存在**：`chat_pipeline` 每轮 `set_request_identity(user_input,
session_id, user_id)` 写进 `core/turn_context` 的 ContextVar，读法是
`agent.current_session_id`（后链的幂等键与落盘 session 已在用它）。
故本单不是"新增形参"，是让装配入口改读**已在跑的单源**，并在
`_turn_room_id`（群轮）→ `self._session_id`（构造期显式覆盖）之后接上它。

判据全程走生产构造面（不手工传 session_id 造功能）：身份经
`core.turn_context` 的 ContextVar 写入，与 `chat_pipeline._init_agent_state`
同型。
"""

from __future__ import annotations

import ast
import logging
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

ORCHESTRATOR_SOURCE = PROJECT_ROOT / "neurova" / "context" / "orchestrator.py"


@pytest.fixture(autouse=True)
def _isolatedDataRoot(tmp_path, monkeypatch):
    """数据根注入（唯一注入口）：本文件会走到编排器的真台账写盘路径。"""
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path / "data"))
    yield


@pytest.fixture(autouse=True)
def _clearTurnIdentity():
    from neurova.core.turn_context import set_turn_identity

    yield
    set_turn_identity("", None, None)


class _TurnIdentityAgent(MagicMock):
    """与 `agent_core.Agent` **同型**的替身：身份面是转发 `core/turn_context` 的只读属性。

    生产链是 `Agent.current_session_id` (property) → `TurnState.current_session_id`
    → `turn_context.get_turn_session_id()`（ContextVar）。替身若把该属性实现成
    一个普通可写字段，用例就会伪造出与生产不同的身份来源——那正是本条缺陷
    "装配入口读不到身份"被 74 个 context 用例漏过的原因。
    """

    @property
    def current_session_id(self):
        from neurova.core.turn_context import get_turn_session_id

        return get_turn_session_id()


def _productionAgent() -> MagicMock:
    """与 `agent_core.init_memory` 同型的 Agent 替身（成员齐备、不传 session_id）。"""
    agent = _TurnIdentityAgent()
    agent.config = MagicMock()
    agent.config.name = "t"
    agent.config.agent_id = "a1"
    agent.config.constitution = ""
    agent.config.behavior_rules = []
    agent.config.llm_model = "test-model"
    agent.memory_manager = MagicMock()
    agent.context_builder = MagicMock()
    agent.tool_router = None
    agent._skill_registry = None
    agent.soul = "测试助手"
    agent.personality = ""
    agent.conversation_history = []
    agent.growth_log_manager = MagicMock()
    agent.user_id = "u1"
    agent.agent_id = "a1"
    return agent


def _setTurnIdentity(session_id):
    """写入本轮身份（与 `chat_pipeline._init_agent_state` 同型）。"""
    from neurova.core.turn_context import set_turn_identity

    set_turn_identity("继续", session_id, "u1")


async def _build(orch, *, user_input="继续", history, collab=False, room_id=""):
    with patch.object(orch, "get_tools_description", new_callable=AsyncMock) as m:
        m.return_value = "工具描述"
        return await orch.build_context(
            user_input=user_input,
            session_context=history,
            relevant_memories=[],
            chat_collab=collab,
            chat_room_id=room_id,
        )


def _longHistory(topic: str, rounds: int = 12) -> list:
    return [
        {"role": "user", "content": f"第{i}条：{topic}" + "内容" * 60}
        for i in range(rounds)
    ]


def _orchestrator(budget: int = 1200, summarizer=None):
    from neurova.context.orchestrator import ContextOrchestrator

    orch = ContextOrchestrator(_productionAgent(), use_pool=True)
    orch._window_token_budget = budget
    if summarizer is not None:
        orch._window_summarizer = summarizer
    return orch


class TestFoldCacheKeyFollowsTurnIdentity:
    """折叠摘要缓存的键必须是**本轮真实会话身份**（探针 P2 形状一）。"""

    @pytest.mark.asyncio
    async def test_two_direct_sessions_do_not_share_fold_summary(self):
        """两个普通单聊会话先后折叠：后一个视图不得带前一个的摘要。"""
        orch = _orchestrator()

        summaries: list = []

        async def summarize(dropped, previous_summary=""):
            summaries.append(previous_summary)
            return f"摘要{len(summaries)}"

        orch._window_summarizer = summarize

        _setTurnIdentity("sess_one")
        await _build(orch, history=_longHistory("量子计算"))

        _setTurnIdentity("sess_two")
        view_two = await _build(orch, history=_longHistory("火星殖民"))

        joined = "\n".join(str(m.get("content", "")) for m in view_two)
        assert "摘要1" not in joined, (
            "两个单聊会话共用了折叠摘要槽 —— 键恒 `direct`（`_resolve_window_cache_key`"
            " 不读本轮身份）"
        )
        assert len(summaries) >= 2, "第二个会话没有各自生成摘要（本用例没打到折叠路径）"

    def test_window_cache_key_falls_back_to_turn_session(self):
        """仅 turn context 有身份时，键必须是该 id 而非 `direct`。"""
        orch = _orchestrator()
        _setTurnIdentity("sess_alpha")

        assert orch._resolve_window_cache_key() == "sess_alpha", (
            "装配入口没有读本轮身份单源 `agent.current_session_id`"
        )

    def test_window_cache_key_prefers_explicit_construction_identity(self):
        """显式构造期身份优先于本轮单源（测试/运维覆盖语义保留）。"""
        from neurova.context.orchestrator import ContextOrchestrator

        orch = ContextOrchestrator(
            _productionAgent(), use_pool=True, session_id="explicit"
        )
        _setTurnIdentity("turn_wide")

        assert orch._resolve_window_cache_key() == "explicit"

    def test_room_identity_wins_over_turn_session(self):
        """群轮：房间身份优先（与 `chat_pipeline` 传参语义一致）。"""
        orch = _orchestrator()
        orch._turn_room_id = "project_roomA"
        _setTurnIdentity("sess_beta")

        assert orch._resolve_window_cache_key() == "project_roomA"

    def test_tool_clip_priority_shares_the_same_key(self):
        """工具裁剪优先级与折叠摘要**共用同一键**（不新造第二个身份口径）。"""
        orch = _orchestrator()
        _setTurnIdentity("sess_shared")
        assert orch._resolve_window_cache_key() == "sess_shared"

    @pytest.mark.asyncio
    async def test_fold_cache_bounded_across_sessions(self):
        """键开始真正增长后，槽数必须受类级上限约束（不把串台换成无界增长）。"""
        orch = _orchestrator()

        async def summarize(dropped, previous_summary=""):
            return "摘要"

        orch._window_summarizer = summarize
        for i in range(orch._WINDOW_CACHE_SLOTS + 12):
            _setTurnIdentity(f"sess_{i}")
            await _build(orch, history=_longHistory(f"话题{i}"))

        assert len(orch._window_compaction_cache) <= orch._WINDOW_CACHE_SLOTS, (
            f"折叠缓存无上限：{len(orch._window_compaction_cache)} 槽"
        )


class TestPoolOwnershipFollowsTurnIdentity:
    """同一根因的第二命中点：池归属与持久台账的 session 列。"""

    @pytest.mark.asyncio
    async def test_pool_session_id_follows_turn_identity_on_direct_turns(self):
        """非协作轮：池 session_id 与本轮身份同值（改前恒 None）。"""
        orch = _orchestrator(budget=100000)
        _setTurnIdentity("sess_pool")

        await _build(orch, history=[{"role": "user", "content": "普通单聊一轮"}])

        assert orch.context_pool.session_id == "sess_pool", (
            "非协作轮把 None 写进池归属 —— 条目 metadata 与持久台账的会话列双双失去依据"
        )

    @pytest.mark.asyncio
    async def test_archived_entries_carry_the_turn_session(self):
        """条目 `metadata["session_id"]` 必须随本轮身份落库（query 分区据此生效）。"""
        orch = _orchestrator(budget=100000)
        _setTurnIdentity("sess_meta")

        await _build(
            orch,
            history=[{"role": "user", "content": "会话身份落 metadata 的探针内容"}],
        )

        entries = [
            c for c in orch.context_pool.get_contexts()
            if "会话身份落 metadata" in str(c.content)
        ]
        assert entries, "本轮历史未入池（本用例没打到归档路径）"
        for entry in entries:
            assert entry.metadata.get("session_id") == "sess_meta", (
                f"条目的会话归属缺失：metadata={entry.metadata}"
            )

    @pytest.mark.asyncio
    async def test_persistent_ledger_rows_carry_the_turn_session(self):
        """持久台账行的 session 列同值（跨重启召回按会话过滤才有依据）。"""
        orch = _orchestrator(budget=100000)
        _setTurnIdentity("sess_ledger")

        await _build(
            orch,
            history=[{"role": "user", "content": "持久台账会话列探针内容"}],
        )

        ledger = orch.context_pool._ledger_db
        assert ledger is not None, "编排器未装配持久台账（本用例前提不成立）"
        rows = [
            dict(row) for row in ledger.recentRows(50)
            if "持久台账会话列探针内容" in row["content"]
        ]
        assert rows, "归档未写穿持久台账（本用例没打到落库路径）"
        for row in rows:
            assert row["session_id"] == "sess_ledger", (
                f"台账行 session 列为 {row['session_id']!r} —— 会话过滤形同虚设"
            )


class TestBudgetReadoutFollowsTheSameIdentityChain:
    """同一根因的第三命中点：预算读数的"本轮实测"也按 `self._session_id` 单独取数。

    `get_token_budget` 的 `used_tokens` 取 compose 侧最近一次实测快照，而快照
    是按会话分桶的（`composition._last_session_composition`）。改前传入的是
    `self._session_id or None` —— 构造期恒 None → 退到 **agent 级**快照，
    也就是"别的会话的最近一轮"。实测（两个会话各测一轮）：

    ```
    本轮 sess_mine 实测 1 token，另一会话 sess_other 稍后实测 2000 token
    get_token_budget()["used_tokens"] → 2000   ← 面板显示的是别的会话的规模
    ```

    身份推导只允许一处（`_turnSessionIdentity`）：本命中点与缓存键、池归属
    取同一条回落链，否则三处各退化为 `None` 的形态会各自看起来正常。
    """

    def test_used_tokens_reads_this_sessions_snapshot(self):
        from neurova.context.composition import measure_composition

        orch = _orchestrator(budget=100000)
        _setTurnIdentity("sess_mine")
        measure_composition(
            agent_id="a1",
            messages=[{"role": "user", "content": "z"}],
            tools=None,
            session_id="sess_mine",
        )
        measure_composition(
            agent_id="a1",
            messages=[{"role": "user", "content": "y" * 8000}],
            tools=None,
            session_id="sess_other",
        )

        used = orch.get_token_budget()["used_tokens"]
        mine = __import__(
            "neurova.context.composition", fromlist=["x"]
        )._last_session_composition["a1"]["sess_mine"]["total_tokens"]

        assert used == int(mine), (
            f"预算读数取了别的会话的实测快照：used_tokens={used}，本轮真值={mine}"
            "（身份推导第二处 —— `get_token_budget` 仍只认 `self._session_id`）"
        )


class TestIdentitylessTurnIsVisible:
    """落到 `direct` 时必须**可见**：静默共用槽就是本次缺陷的形态。"""

    def test_identityless_turn_is_counted_not_silent(self, caplog):
        orch = _orchestrator()
        _setTurnIdentity(None)

        with caplog.at_level(logging.WARNING):
            key = orch._resolve_window_cache_key()

        assert key == "direct", "无身份轮应落 direct（回落链的终点）"
        report = orch.get_context_health()["session_identity"]
        assert report["identityless_turns"] >= 1, (
            "无身份轮没有被计数 —— 共用槽静默发生，与改前无法区分"
        )
        assert any(
            "会话身份" in record.getMessage() or "direct" in record.getMessage()
            for record in caplog.records
        ), "无身份轮没有点名 warning（教义第 2 条：不许静默）"

    def test_health_readout_shape_is_single_source(self):
        """读数面形状由编排器一处给出，健康态也必须可观测。"""
        orch = _orchestrator()
        _setTurnIdentity("sess_ok")
        orch._resolve_window_cache_key()

        report = orch.get_context_health()["session_identity"]
        assert set(report) >= {"identityless_turns", "last_error"}, report


class TestNoSecondIdentityChannel:
    """禁止的假修复：给 `build_context` 新增 `session_id` 形参 = 第二份定义。"""

    def test_build_context_has_no_session_id_parameter(self):
        tree = ast.parse(ORCHESTRATOR_SOURCE.read_text(encoding="utf-8"))
        found = None
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "build_context":
                found = node
                break
        assert found is not None, "ContextOrchestrator.build_context 不见了"
        names = [a.arg for a in found.args.args] + [a.arg for a in found.args.kwonlyargs]
        assert "session_id" not in names, (
            "`build_context` 新增了 `session_id` 形参 —— 本轮身份的真源是 "
            "`agent.current_session_id`（`core/turn_context`），并存两条通道必然漂移"
            "（教义第 6 条：单一事实源）"
        )

class TestGuardIsInProtectedSubset:
    """本守卫必须在受保护子集内（否则 CI 不跑它，判据只在本地成立）。"""

    def test_listed_in_protected_tests(self):
        listed = {
            line.split("#", 1)[0].strip()
            for line in (
                PROJECT_ROOT / "scripts" / "ci" / "protected_tests.txt"
            ).read_text(encoding="utf-8").splitlines()
            if line.split("#", 1)[0].strip()
        }
        rel = "tests/unit/context/test_turn_session_identity.py"
        assert rel in listed, f"{rel} 不在受保护子集 —— 本守卫的判据在 CI 上不会执行"


class TestFoldCacheEvictsLeastRecentlyUsed:
    """工单 §4bis 要求 3：上限策略是 **LRU / 最近使用**，不是插入序。

    键数此前恒 1（身份取不到），上限无从触发；T-03b 接通身份后槽数才开始真增长，
    故上限策略必须与接线同批落地——而"插入序"与"最近使用"在稳态下会给出**不同**
    的淘汰对象：被反复引用的老会话不该因为"建得早"先被丢弃（那会让它的摘要原地
    重算，等于把"串台"换成"反复失忆"）。
    """

    @pytest.mark.asyncio
    async def test_recently_used_slot_survives_while_older_insertions_are_evicted(self):
        orch = _orchestrator()

        async def summarize(dropped, previous_summary=""):
            return "摘要"

        orch._window_summarizer = summarize

        # 先建满一池子会话，再回到最早那个会话（它成为「最近使用」）
        for i in range(orch._WINDOW_CACHE_SLOTS):
            _setTurnIdentity(f"sess_{i}")
            await _build(orch, history=_longHistory(f"话题{i}"))
        oldest = "sess_0"
        assert oldest in orch._window_compaction_cache, "首个会话没有分槽——本用例没打到折叠路径"

        _setTurnIdentity(oldest)
        await _build(orch, history=_longHistory("回到最早那轮"))

        # 再来一个新会话：该淘汰的是「最久未使用」，不是「最早插入」
        _setTurnIdentity("sess_brand_new")
        await _build(orch, history=_longHistory("新会话"))

        keys = set(orch._window_compaction_cache)
        assert oldest in keys, (
            f"刚用过的槽 `{oldest}` 被淘汰了 —— 淘汰口径是插入序（建得早先丢），"
            f"不是工单 §4bis 要求的最近使用：{sorted(keys)}"
        )
        assert "sess_brand_new" in keys, f"新会话没分到槽：{sorted(keys)}"
        assert len(keys) <= orch._WINDOW_CACHE_SLOTS, f"槽数超上限：{len(keys)}"
