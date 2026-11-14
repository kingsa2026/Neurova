# -*- coding: utf-8 -*-
"""窗口自适应折叠时机（对照改进追问批）：触发参数随模型窗口缩放。

契约：
1. 增长门增量门槛随预算缩放：有效门槛 = max(静态下限, 预算×份额)——
   大窗口模型要积累更多增量才主动折，小窗口模型更早折；
2. microcompact 绝对臂随模型窗口缩放：max(8000, 模型窗口×10%)——
   大窗口模型容忍更大的工具结果原文驻留；
3. 视图预算钳顶 env 可调（NEUROVA_WINDOW_BUDGET_CAP，默认 100000）——
   大窗口模型可放开到窗口的既定份额以上。
"""
import os
import sys
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from neurova.context.fold_trigger import decideFoldTrigger
from neurova.context.orchestrator import ContextOrchestrator


def _mk_agent(agent_id="a-adaptive"):
    agent = MagicMock()
    agent.config = MagicMock()
    agent.config.name = "t"
    agent.config.constitution = ""
    agent.config.behavior_rules = []
    agent.config.llm_model = "test-model"
    agent.memory_manager = MagicMock()
    agent.context_builder = MagicMock()
    agent.tool_router = None
    agent._skill_registry = None
    agent.soul = "s"
    agent.personality = ""
    agent.conversation_history = []
    agent.growth_log_manager = MagicMock()
    agent.user_id = "u-adaptive"
    agent.agent_id = agent_id
    return agent


class TestGrowthGateScalesWithBudget:
    def _decide(self, budget, growth):
        # 占用钉在预算的 0.7（≥ 下限 0.6，先过占用门），growth 是再往上长的增量
        base = int(budget * 0.7)
        return decideFoldTrigger(
            total_tokens=base + growth,
            budget_tokens=budget,
            last_fold_tokens=base,
            last_fold_msgs=100,
            total_msgs=110,
            foldable_msgs=10,
            enabled=True,
        )

    def test_big_window_demands_bigger_growth(self, monkeypatch):
        """同增量下：大预算不折（门槛随预算放大）、小预算折。"""
        monkeypatch.delenv("NEUROVA_FOLD_GROWTH_BUDGET_SHARE", raising=False)
        monkeypatch.delenv("NEUROVA_FOLD_GROWTH_MIN_TOKENS", raising=False)
        big = self._decide(budget=100000, growth=10908)   # 门槛 = max(2000, 25000)
        small = self._decide(budget=10000, growth=4000)   # 门槛 = max(2000, 2500)
        assert not big.should_fold, "大预算下 1.1 万增量不够门槛，不应主动折"
        assert small.should_fold, "小预算下同比例增量应触发"

    def test_share_env_overridable(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_FOLD_GROWTH_BUDGET_SHARE", "0.05")
        big = self._decide(budget=100000, growth=10908)   # 门槛 = max(2000, 5000)
        assert big.should_fold, "放宽份额后应触发"

    def test_floor_keeps_small_windows_viable(self, monkeypatch):
        """小预算：份额算出的门槛低于静态下限时，取静态下限。"""
        monkeypatch.delenv("NEUROVA_FOLD_GROWTH_BUDGET_SHARE", raising=False)
        small = self._decide(budget=10000, growth=1500)   # 门槛 = max(2000, 2500) = 2500
        assert not small.should_fold, "1500 < 门槛 2500，不折"
        ok = self._decide(budget=10000, growth=3000)      # 3000 ≥ 2500
        assert ok.should_fold


class TestMicrocompactScalesWithModelWindow:
    def _orch(self):
        orch = ContextOrchestrator(_mk_agent(), use_pool=False, auto_tag=False)
        return orch

    def test_absolute_arm_scales_with_model_window(self):
        orch = self._orch()
        small = orch._toolPayloadTrigger(30000, model_window_tokens=32768)
        big = orch._toolPayloadTrigger(30000, model_window_tokens=131072)
        assert small == 8000, "32K 窗口：绝对臂仍为 8000（max(8000, 3277)）"
        assert big == 13107, f"128K 窗口：绝对臂应放大到窗口×10%（13107），实得 {big}"

    def test_clear_old_tool_results_uses_model_window(self):
        """同一视图：32K 窗口触发微压缩换指针；128K 窗口（绝对臂放大）不触发。"""
        orch = self._orch()
        msgs = [
            {"role": "user", "content": "问：" + "测" * 26000},   # ≈26k token，撑起窗口实占
            {"role": "assistant", "content": "答", "tool_calls": [
                {"id": "tc-1", "type": "function", "function": {"name": "web_fetch", "arguments": "{}"}}
            ]},
            {"role": "tool", "tool_call_id": "tc-1", "name": "web_fetch", "content": "测" * 5000},
            {"role": "assistant", "content": "再答", "tool_calls": [
                {"id": "tc-2", "type": "function", "function": {"name": "web_fetch", "arguments": "{}"}}
            ]},
            {"role": "tool", "tool_call_id": "tc-2", "name": "web_fetch", "content": "测" * 5000},
        ]
        # 载荷合计 ≈10k token：32K 窗口（绝对臂 8000）触发换指针；
        # 128K 窗口（绝对臂 13107）未过触发线，两条工具结果都保留原文。
        kept_big = orch._clear_old_tool_results(msgs, model_window_tokens=131072)
        assert kept_big[2]["content"] == msgs[2]["content"], "128K 窗口：未过触发线应保留原文"
        assert kept_big[4]["content"] == msgs[4]["content"]
        kept_small = orch._clear_old_tool_results(msgs, model_window_tokens=32768)
        assert "已移出上下文" in str(kept_small[2].get("content", "")), (
            "32K 窗口：超触发线的旧工具结果应被换指针"
        )
        assert kept_small[4]["content"] == msgs[4]["content"], "最新一条仍在保留窗（份额内）"


class TestWindowBudgetCapEnv:
    def _orch(self):
        return ContextOrchestrator(_mk_agent(), use_pool=False, auto_tag=False)

    def test_cap_default_100k(self, monkeypatch):
        monkeypatch.delenv("NEUROVA_WINDOW_BUDGET_CAP", raising=False)
        import neurova.context_pool as cp_mod

        orch = self._orch()
        with patch_model_window(400000):
            assert orch._resolve_window_token_budget() == 100000, "默认钳顶 100000"

    def test_cap_env_raises_for_big_models(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_WINDOW_BUDGET_CAP", "300000")
        orch = self._orch()
        with patch_model_window(400000):
            budget = orch._resolve_window_token_budget()
        assert budget == 144000, (
            f"钳顶放开后应取 144000（=400000×0.6 池系数 ×0.6 窗口份额），实得 {budget}"
        )


class _PatchModelWindow:
    """把模型窗口解析钉到指定值的语境（真单源函数不打桩，改其数据源）。"""

    def __init__(self, window: int):
        self.window = window

    def __enter__(self):
        from neurova.llm import llm_router

        self._orig = llm_router.resolve_model_context_window
        llm_router.resolve_model_context_window = lambda name: self.window
        return self

    def __exit__(self, *exc):
        from neurova.llm import llm_router

        llm_router.resolve_model_context_window = self._orig
        return False


def patch_model_window(window: int):
    return _PatchModelWindow(window)
