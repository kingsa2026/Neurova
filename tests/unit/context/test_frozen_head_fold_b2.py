# -*- coding: utf-8 -*-
"""B2 冻结已折叠区（增量折叠）＋ B5 增长门 —— 编排层接线契约。

场景（真 build_context 链路，真折叠器，受控摘要器）：
1. 首折（预算击穿）→ 摘要行入视图；
2. 再折（继续增长）→ 旧代摘要行**逐字节**保留（冻结头），新代摘要只覆盖尾部增量；
3. 尾部未超份额 → 本轮零折叠（摘要器调用数不增，头部行与上一轮全等）；
4. B5 增长门开启时：未超预算但占用与增量过限 → 主动折；默认关 → 不折。
"""
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from neurova.context.orchestrator import ContextOrchestrator


def _mk_agent(model: str = "test-model"):
    mock_agent = MagicMock()
    mock_agent.config = MagicMock()
    mock_agent.config.name = "test_agent"
    mock_agent.config.constitution = ""
    mock_agent.config.behavior_rules = []
    mock_agent.config.llm_model = model
    mock_agent.memory_manager = MagicMock()
    mock_agent.context_builder = MagicMock()
    mock_agent.tool_router = None
    mock_agent._skill_registry = None
    mock_agent.soul = "你是测试助手"
    mock_agent.personality = ""
    mock_agent.conversation_history = []
    mock_agent.growth_log_manager = MagicMock()
    mock_agent.user_id = "u-b2-iso"
    mock_agent.agent_id = "a-b2-iso"
    return mock_agent


def _long_msg(i: int, chars: int = 900) -> dict:
    return {"role": "user", "content": f"长消息{i}: " + "测" * chars}


def _tiny_msg(i: int) -> dict:
    return {"role": "user", "content": f"小消息{i}: 好的"}


def _summary_rows(view):
    return [m for m in view if m.get("role") == "system" and "早期对话摘要" in str(m.get("content", ""))]


@pytest.fixture(autouse=True)
def _isolatedDataRoot(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path / "data"))
    yield


class TestFrozenHeadFold:
    def _mk_orchestrator(self, budget: int = 8000):
        orch = ContextOrchestrator(_mk_agent(), use_pool=True, auto_tag=False)
        orch._window_token_budget = budget
        return orch

    async def _build(self, orch, session_context, user_input="你好"):
        with patch.object(orch, "get_tools_description", new_callable=AsyncMock) as m:
            m.return_value = "工具描述占位"
            return await orch.build_context(
                user_input=user_input,
                session_context=session_context,
                relevant_memories=[],
            )

    @pytest.mark.asyncio
    async def test_second_fold_keeps_old_generation_bytes(self):
        """再折时旧代摘要行逐字节保留（冻结头），新代只覆盖尾部。"""
        orch = self._mk_orchestrator(budget=8000)
        calls = {"n": 0}

        async def scripted_summarize(chunks, previous_summary=""):
            calls["n"] += 1
            return f"摘要第{calls['n']}批：主题X。" if calls["n"] == 1 else f"摘要第{calls['n']}批：主题Y。"

        orch._window_summarizer = scripted_summarize

        view1 = await self._build(orch, [_long_msg(i) for i in range(30)])
        rows1 = _summary_rows(view1)
        assert any("主题X" in r["content"] for r in rows1), "首折应产出主题X摘要行"

        view2 = await self._build(orch, [_long_msg(i) for i in range(40)], user_input="继续")
        rows2 = _summary_rows(view2)
        assert any("主题Y" in r["content"] for r in rows2), "再折应产出主题Y摘要行（只覆盖尾部增量）"
        x_rows_1 = [r["content"] for r in rows1 if "主题X" in r["content"]]
        x_rows_2 = [r["content"] for r in rows2 if "主题X" in r["content"]]
        assert x_rows_1 and x_rows_2 and x_rows_1 == x_rows_2, (
            "旧代摘要行在再折后必须逐字节不变（冻结头契约）"
        )
        assert calls["n"] == 2

    @pytest.mark.asyncio
    async def test_tail_within_share_skips_fold(self):
        """尾部未超份额：本轮零折叠——摘要调用数不增，头部行与上一轮全等。"""
        orch = self._mk_orchestrator(budget=8000)
        calls = {"n": 0}

        async def counting_summarize(chunks, previous_summary=""):
            calls["n"] += 1
            return f"摘要第{calls['n']}批：主题X。"

        orch._window_summarizer = counting_summarize

        view1 = await self._build(orch, [_long_msg(i) for i in range(30)])
        head1 = _summary_rows(view1)
        # 追加 2 条小消息：冻结头不动，尾部仍在份额内 → 零折叠
        view2 = await self._build(
            orch,
            [_long_msg(i) for i in range(30)] + [_tiny_msg(i) for i in range(2)],
            user_input="继续",
        )
        head2 = _summary_rows(view2)
        assert calls["n"] == 1, f"尾部未超份额不得再调摘要（实际 {calls['n']} 次）"
        assert head1 == head2, "零折叠轮的头部摘要行必须与上一轮逐字节全等"
        joined = "".join(m["content"] for m in view2)
        assert "小消息1" in joined, "新增小消息应保留在尾部视图"

    @pytest.mark.asyncio
    async def test_new_generation_covers_only_tail(self):
        """增量折叠：新一轮 covered 只增尾部 hash，且旧覆盖不丢。"""
        orch = self._mk_orchestrator(budget=8000)

        async def fake_summarize(chunks, previous_summary=""):
            return "摘要：主题X。"

        orch._window_summarizer = fake_summarize
        await self._build(orch, [_long_msg(i) for i in range(30)])
        cache_key = orch._resolve_window_cache_key()
        covered1 = set(orch._window_compaction_cache[cache_key]["covered"])
        assert covered1, "首折应登记覆盖"

        await self._build(orch, [_long_msg(i) for i in range(40)], user_input="继续")
        covered2 = set(orch._window_compaction_cache[cache_key]["covered"])
        assert covered1 <= covered2, "旧覆盖不得被丢弃"
        assert len(covered2) > len(covered1), "再折应新增尾部覆盖"


class TestGrowthGateWiring:
    def _mk_orchestrator(self, budget: int = 8000):
        orch = ContextOrchestrator(_mk_agent(), use_pool=True, auto_tag=False)
        orch._window_token_budget = budget
        return orch

    async def _build(self, orch, session_context, user_input="你好"):
        with patch.object(orch, "get_tools_description", new_callable=AsyncMock) as m:
            m.return_value = "工具描述占位"
            return await orch.build_context(
                user_input=user_input,
                session_context=session_context,
                relevant_memories=[],
            )

    @pytest.mark.asyncio
    async def test_gate_off_no_proactive_fold(self, monkeypatch):
        """默认（门关）：未超预算不折——与改前行为一致。"""
        monkeypatch.delenv("NEUROVA_FOLD_GROWTH_GATE", raising=False)
        orch = self._mk_orchestrator(budget=100000)  # 预算极大，永不击穿
        orch._window_hard_limit = 1000000  # 摘除硬顶钳（否则 test-model 钳到 14400）
        # 12 条 ≈ 10.9k token < 100000 → 未击穿；门关 → 不折
        view = await self._build(orch, [_long_msg(i) for i in range(12)])
        assert _summary_rows(view) == []

    @pytest.mark.asyncio
    async def test_gate_on_proactive_fold_under_budget(self, monkeypatch):
        """门开：占用与增量过限即主动折（未超预算也折）。"""
        monkeypatch.setenv("NEUROVA_FOLD_GROWTH_GATE", "1")
        monkeypatch.setenv("NEUROVA_FOLD_GROWTH_FLOOR", "0.1")
        monkeypatch.setenv("NEUROVA_FOLD_GROWTH_MIN_TOKENS", "1000")
        # 份额也放宽（门槛随预算缩放后 = max(2000, 预算×份额)，100000×0.25=25000
        # 会盖过本用例的增量）——本用例验证的是"门开即按门折叠"的接线，
        # 不是份额刻度本身。
        monkeypatch.setenv("NEUROVA_FOLD_GROWTH_BUDGET_SHARE", "0.01")
        orch = self._mk_orchestrator(budget=100000)  # 永不击穿
        orch._window_hard_limit = 1000000
        # 12 条 ≈ 10.9k token，占用 0.11 ≥ 0.1，增量 10.9k ≥ max(1000, 1000)，
        # 可折 6 条 ≥ keep_min → 主动折（未超预算）
        async def fake_summarize(chunks, previous_summary=""):
            return "摘要：主动折叠主题Z。"

        orch._window_summarizer = fake_summarize
        view = await self._build(orch, [_long_msg(i) for i in range(12)])
        rows = _summary_rows(view)
        assert rows, "增长门应主动折叠"
        assert any("主题Z" in r["content"] for r in rows)
