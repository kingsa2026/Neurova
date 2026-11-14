# -*- coding: utf-8 -*-
"""A1（对照改进追问批）：token 尺子按模型校准。

契约（两步走：观测面常开；预算校准只在证据足够时生效）：
1. 采样：recordOutputSample(model, output_text, billed_completion) 记录
   「尺子估算 / 账单真值」对——完成侧文本与账单一一对应，是纯净的
   分词偏差信号（不含 system/工具描述混杂）；
2. 观测面：factorFor(model) 在样本不足（<5）或偏差 ≤±15% 时返回 1.0
   （中性，不改判据）；样本足够且偏差超带才返回实测因子（钳 [0.5, 2.0]）；
3. 模型间独立；
4. 开关：NEUROVA_TOKEN_CALIBRATION=0 关闭（不采样、因子恒 1.0）；
5. 预算应用：_effectiveWindowBudget 对 ruler 预算除以因子（尺子低估 →
   预算收缩），先除后钳 90% 硬顶（硬顶是真值单位）；
6. 工具调用响应不采样（账单含工具参数 JSON，会污染文本偏差信号）。
"""
import os
import sys
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from neurova.core import token_calibration as tc
from neurova.context.orchestrator import ContextOrchestrator


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.delenv("NEUROVA_TOKEN_CALIBRATION", raising=False)
    tc.resetForTests()
    yield
    tc.resetForTests()


def _seed(model: str, bias: float, samples: int = 5, base: int = 1000):
    for _ in range(samples):
        # 估算恒为 base，账单 = base×bias → 每个样本的偏差都是 bias
        tc.recordOutputSample(model, "字" * base, int(base * bias))


class TestObservationFace:
    def test_insufficient_samples_neutral(self):
        _seed("m-ins", 1.25, samples=2)
        assert tc.factorFor("m-ins") == 1.0, "样本不足（<5）不得改判据"

    def test_factor_after_min_samples(self):
        _seed("m-ok", 1.25, samples=5)
        assert tc.factorFor("m-ok") == pytest.approx(1.25), "5 样本后应输出实测偏差"

    def test_small_bias_stays_neutral(self):
        _seed("m-small", 1.05, samples=6)
        assert tc.factorFor("m-small") == 1.0, "偏差 ≤±15% 不改判据"

    def test_models_independent(self):
        _seed("m-a", 1.3, samples=5)
        _seed("m-b", 0.8, samples=5)
        assert tc.factorFor("m-a") == pytest.approx(1.3)
        assert tc.factorFor("m-b") == pytest.approx(0.8)

    def test_factor_clamped(self):
        _seed("m-extreme", 5.0, samples=5)
        assert tc.factorFor("m-extreme") == 2.0, "极端偏差钳到 2.0"
        _seed("m-tiny", 0.1, samples=5)
        assert tc.factorFor("m-tiny") == 0.5, "极端偏差钳到 0.5"

    def test_zero_billing_or_empty_text_skipped(self):
        tc.recordOutputSample("m-zero", "字" * 1000, 0)
        tc.recordOutputSample("m-zero", "", 500)
        assert tc.factorFor("m-zero") == 1.0
        assert tc.snapshot().get("m-zero", {}).get("samples", 0) == 0

    def test_tool_call_response_skipped(self):
        tc.recordOutputSample("m-tool", "字" * 1000, 500, has_tool_calls=True)
        assert tc.snapshot().get("m-tool", {}).get("samples", 0) == 0

    def test_kill_switch(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_TOKEN_CALIBRATION", "0")
        _seed("m-off", 1.3, samples=6)
        assert tc.factorFor("m-off") == 1.0
        assert tc.snapshot() == {}

    def test_snapshot_shape(self):
        _seed("m-snap", 1.2, samples=5)
        snap = tc.snapshot()
        assert snap["m-snap"]["samples"] == 5
        assert snap["m-snap"]["bias"] == pytest.approx(1.2)
        assert snap["m-snap"]["applied"] is True


class TestBudgetApplication:
    def _orch(self):
        return ContextOrchestrator(_mk_agent(), use_pool=False, auto_tag=False)

    def test_budget_shrinks_when_ruler_underestimates(self, monkeypatch):
        """尺子低估（因子 1.25）：ruler 预算除以因子——真值不超原意。"""
        monkeypatch.delenv("NEUROVA_TOKEN_CALIBRATION", raising=False)
        _seed("test-model", 1.25, samples=6)
        orch = self._orch()
        assert orch._effectiveWindowBudget(8000) == 6400, "8000/1.25=6400（先除因子后钳硬顶）"

    def test_budget_unchanged_when_neutral(self, monkeypatch):
        monkeypatch.delenv("NEUROVA_TOKEN_CALIBRATION", raising=False)
        orch = self._orch()  # 无采样 → 因子 1.0
        assert orch._effectiveWindowBudget(8000) == 8000

    def test_hard_limit_clamps_after_calibration(self, monkeypatch):
        """先除因子、后钳 90% 硬顶（硬顶是真值单位）。"""
        monkeypatch.delenv("NEUROVA_TOKEN_CALIBRATION", raising=False)
        _seed("test-model", 0.5, samples=6)  # 尺子高估：预算放大 ×2
        orch = self._orch()
        orch._window_hard_limit = 9000       # 真值单位硬顶
        assert orch._effectiveWindowBudget(8000) == 9000, "16000/2=8000… 放大后撞硬顶 9000"


def _mk_agent():
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
    agent.user_id = "u-a1"
    agent.agent_id = "a-a1"
    return agent
