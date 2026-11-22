# -*- coding: utf-8 -*-
"""P1-6 压缩迟滞双阈值（上下文工程十轴 · 轴4）。

契约：
1. 无摘要覆盖：增长门占用下限仍为基础下限 0.6（存量行为逐字不变）；
2. 池里已有摘要覆盖（last_fold_tokens>0 或调用方显式传 has_existing_summary=True）：
   占用下限提到 NEUROVA_FOLD_HYSTERESIS_FLOOR（默认 0.7，env 可覆盖，钳位
   [0.05,1.0]）——同占用 ∈ [0.6, 0.7) 从"触发"变"不折"（迟滞）；
3. 迟滞只抬高不降低：env 配得比基础下限低也不放松门槛；
4. 预算击穿 / 固定间隔 / 门关闭三路径不受迟滞影响；
5. `assessFoldTrigger` 透传并在 FoldTriggerReadout 带出 `floor_effective`；
6. 编排层把"池里已有摘要覆盖"如实传入（covered/summary/增量基线任一在场）。
"""
import os
import sys
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from neurova.context.fold_trigger import (
    REASON_BELOW_FLOOR,
    REASON_BUDGET_BREACH,
    REASON_FIXED_INTERVAL,
    REASON_GATE_DISABLED,
    REASON_GROWTH_GATE,
    assessFoldTrigger,
    decideFoldTrigger,
    foldHysteresisFloor,
)


def _decide(**kw):
    base = dict(
        total_tokens=6500,
        budget_tokens=10000,
        last_fold_tokens=0,
        last_fold_msgs=0,
        total_msgs=30,
        foldable_msgs=24,
        enabled=True,
    )
    base.update(kw)
    return decideFoldTrigger(**base)


class TestFoldHysteresisFloor:
    def test_no_summary_keeps_base_floor(self):
        """无摘要覆盖：占用 0.65 ≥ 0.6 照常触发（存量行为不变）。"""
        d = _decide()
        assert d.should_fold and d.reason == REASON_GROWTH_GATE

    def test_with_summary_same_occupancy_holds(self):
        """有摘要覆盖：同占用 0.65 ∈ [0.6, 0.7) → 不折（迟滞）。"""
        d = _decide(last_fold_tokens=3000, last_fold_msgs=20, has_existing_summary=True)
        assert not d.should_fold and d.reason == REASON_BELOW_FLOOR

    def test_baseline_alone_raises_floor(self):
        """last_fold_tokens>0（调用方未显式传）同样进入迟滞。"""
        d = _decide(last_fold_tokens=3000, last_fold_msgs=20)
        assert not d.should_fold and d.reason == REASON_BELOW_FLOOR

    def test_summary_occupancy_above_hysteresis_still_folds(self):
        """占用 0.75 ≥ 0.7：有摘要也照常折（迟滞不是禁折）。"""
        d = _decide(
            total_tokens=7500,
            last_fold_tokens=3000,
            last_fold_msgs=20,
            has_existing_summary=True,
        )
        assert d.should_fold and d.reason == REASON_GROWTH_GATE

    def test_env_overrides_hysteresis_floor(self, monkeypatch):
        """env NEUROVA_FOLD_HYSTERESIS_FLOOR 覆盖生效。"""
        monkeypatch.setenv("NEUROVA_FOLD_HYSTERESIS_FLOOR", "0.85")
        assert foldHysteresisFloor() == 0.85
        held = _decide(
            total_tokens=8000,
            last_fold_tokens=3000,
            last_fold_msgs=20,
            has_existing_summary=True,
        )
        assert not held.should_fold and held.reason == REASON_BELOW_FLOOR  # 0.8 < 0.85
        folded = _decide(
            total_tokens=9000,
            last_fold_tokens=3000,
            last_fold_msgs=20,
            has_existing_summary=True,
        )
        assert folded.should_fold and folded.reason == REASON_GROWTH_GATE  # 0.9 ≥ 0.85

    def test_env_clamped_to_legal_band(self, monkeypatch):
        """钳位 [0.05, 1.0]。"""
        monkeypatch.setenv("NEUROVA_FOLD_HYSTERESIS_FLOOR", "1.5")
        assert foldHysteresisFloor() == 1.0
        monkeypatch.setenv("NEUROVA_FOLD_HYSTERESIS_FLOOR", "0.01")
        assert foldHysteresisFloor() == 0.05

    def test_hysteresis_never_lowers_base_floor(self, monkeypatch):
        """迟滞只抬高不降低：env 低于基础下限时不放松门槛。"""
        monkeypatch.setenv("NEUROVA_FOLD_HYSTERESIS_FLOOR", "0.3")
        readout = assessFoldTrigger(
            total_tokens=6500,
            budget_tokens=10000,
            last_fold_tokens=3000,
            last_fold_msgs=20,
            total_msgs=30,
            enabled=True,
            has_existing_summary=True,
        )
        assert readout.floor_effective == 0.6, "max(基础下限 0.6, 迟滞 0.3) = 0.6"


class TestHysteresisUnaffectedPaths:
    def test_budget_breach_unaffected(self):
        """预算击穿：安全线，不受迟滞管辖。"""
        d = _decide(
            total_tokens=11000,
            last_fold_tokens=5000,
            last_fold_msgs=20,
            has_existing_summary=True,
        )
        assert d.should_fold and d.reason == REASON_BUDGET_BREACH

    def test_fixed_interval_unaffected(self, monkeypatch):
        """固定间隔臂不看占用下限：占用 0.5 也按间隔折。"""
        monkeypatch.setenv("NEUROVA_FOLD_FIXED_INTERVAL_MSGS", "5")
        d = _decide(
            total_tokens=5000,
            last_fold_tokens=2000,
            last_fold_msgs=20,
            has_existing_summary=True,
        )
        assert d.should_fold and d.reason == REASON_FIXED_INTERVAL

    def test_gate_disabled_unaffected(self):
        """门关闭路径与改前逐字一致（只有击穿才折）。"""
        d = _decide(enabled=False, has_existing_summary=True)
        assert not d.should_fold and d.reason == REASON_GATE_DISABLED


class TestAssessReadout:
    def test_floor_effective_reflects_hysteresis(self):
        """FoldTriggerReadout 带出 floor_effective；occupancy_met 按有效下限判定。"""
        base = assessFoldTrigger(
            total_tokens=6500,
            budget_tokens=10000,
            last_fold_tokens=0,
            last_fold_msgs=0,
            total_msgs=30,
            enabled=True,
        )
        assert base.floor == 0.6 and base.floor_effective == 0.6
        assert base.decision.reason == REASON_GROWTH_GATE

        hyst = assessFoldTrigger(
            total_tokens=6500,
            budget_tokens=10000,
            last_fold_tokens=3000,
            last_fold_msgs=20,
            total_msgs=30,
            enabled=True,
            has_existing_summary=True,
        )
        assert hyst.floor == 0.6, "floor 字段保持基础下限（读数契约不变）"
        assert hyst.floor_effective == 0.7
        assert hyst.decision.reason == REASON_BELOW_FLOOR
        assert hyst.occupancy_met is False

    def test_default_kwargs_keep_legacy_behavior(self):
        """不传新参 = 与改前逐字一致（无迟滞）。"""
        d = _decide()
        assert d.should_fold and d.reason == REASON_GROWTH_GATE


# ── 编排层接线：编排器把"池里已有摘要覆盖"如实传入 ────────────────────────


def _mk_agent():
    agent = MagicMock()
    agent.config = MagicMock()
    agent.config.name = "t"
    agent.config.agent_id = "a-hyst"
    agent.config.constitution = ""
    agent.config.behavior_rules = []
    agent.config.llm_model = "test-model"
    agent.config.enable_auto_tagging = False
    agent.memory_manager = MagicMock()
    agent.context_builder = MagicMock()
    agent.tool_router = None
    agent._skill_registry = None
    agent.soul = "测试助手"
    agent.personality = ""
    agent.conversation_history = []
    agent.growth_log_manager = MagicMock()
    agent.user_id = "u-hyst"
    agent.agent_id = "a-hyst"
    return agent


def _long_msg(i: int, chars: int = 900) -> dict:
    return {"role": "user", "content": f"长消息{i}: " + "测" * chars}


@pytest.fixture(autouse=True)
def _isolatedDataRoot(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("NEUROVA_CACHE_ADAPTIVE_FOLD", "0")
    from neurova.cognitive_layers.meta_cognition_layer.ledger import reset_meta_ledger
    from neurova.cognitive_layers.meta_cognition_layer.self_model import (
        reset_self_model_engine,
    )

    reset_meta_ledger()
    reset_self_model_engine()
    yield
    reset_meta_ledger()
    reset_self_model_engine()


class TestOrchestratorWiring:
    @pytest.mark.asyncio
    async def test_orchestrator_passes_summary_coverage_to_trigger(self):
        """池里已有摘要覆盖时，编排器传入 has_existing_summary：占用 0.65 → 不折。"""
        from neurova.context.orchestrator import ContextOrchestrator
        from neurova.context.window_compactor import estimate_window_tokens

        orch = ContextOrchestrator(_mk_agent(), use_pool=True, auto_tag=False)
        orch._window_hard_limit = 10**9
        msgs = [_long_msg(i) for i in range(24)]
        total = estimate_window_tokens(msgs)
        budget = orch._effectiveWindowBudget(int(total / 0.65))
        slot = orch._window_cache_slot("hyst-session")
        slot.update(
            {
                "summary": "旧摘要：早期经历已提炼。",
                "covered": {orch._windowChunkHash(msgs[0])},
                "last_fold_tokens": int(total * 0.4),
                "last_fold_msgs": 4,
            }
        )

        await orch._apply_window_budget(msgs, budget, cache_key="hyst-session")

        health = orch.get_context_health()
        assert health["fold_trigger"]["last_reason"] == REASON_BELOW_FLOOR, (
            f"有摘要覆盖 + 占用 0.65 应被迟滞按住（below_floor），实得 "
            f"{health['fold_trigger']['last_reason']}"
        )
        assert health["fold_trigger"]["should_fold"] is False
