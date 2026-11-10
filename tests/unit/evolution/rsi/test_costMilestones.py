# -*- coding: utf-8 -*-
"""E4 质量@成本里程碑＋E5 部署摊销读数（survey §10.2）。"""

import pytest

from neurova.core.usage_accounting import (
    get_usage_accounting,
    reset_usage_accounting,
)
from neurova.evolution.rsi.candidate_policy import CandidatePolicy
from neurova.evolution.rsi.deployment_amortization import deploymentAmortization
from neurova.evolution.rsi.improver_paired_probe import ImproverPairedProbe


class TestQualityAtMilestones:
    def _probe(self):
        def _mk(version):
            return CandidatePolicy(
                version=version, summary="s",
                setpoint_lookup=lambda s, n: 0.8,
                performance_extractor=lambda signals: 0.5,
                sealed_validator=None,
            )

        states = [{"system": "s", "param": f"p{i}", "current": 0.85, "setpoint": 0.8}
                  for i in range(12)]
        return ImproverPairedProbe(
            policy_t=_mk("I_t"), policy_0=_mk("I_0"),
            starting_states=lambda: states,
            outcome_evaluator=lambda s, c: (
                0.5 if c is None else
                1.0 - abs(c.metadata["optimization"]["new_value"] - 0.8)),
        )

    def test_milestones_reported_per_arm(self):
        readout = self._probe().run()
        milestones = readout["quality_at_milestones"]
        assert milestones["axis"] == [5, 10]
        for arm in ("full", "frozen_I_0", "no_update"):
            for point in ("5", "10"):
                entry = milestones[arm][point]
                assert entry["state"] == "measured", f"{arm}@{point} 空线：{entry}"
                assert entry["quality_mean"] is not None

    def test_missing_milestone_names_the_arm(self):
        """红灯判据：里程碑超出容量 → 点名缺哪个臂（不空线冒充）。"""
        probe = self._probe()
        probe.MILESTONES = (5, 10, 50)  # 50 超出 12 态容量
        readout = probe.run()
        milestones = readout["quality_at_milestones"]
        entry = milestones["full"]["50"]
        assert entry["state"] == "unevidenced"
        assert "full" in entry["reason"], f"缺臂没点名：{entry}"


class TestDeploymentAmortization:
    def test_c_bar_traces_to_real_serving_samples(self, clean_usage):
        """红灯判据：c̄_task 可回溯到真实 serving 事件样本（种子后读数现形）。"""
        get_usage_accounting().record(model="m", provider="p",
                                      prompt_tokens=300, completion_tokens=100,
                                      estimated=False)
        get_usage_accounting().record(model="m", provider="p",
                                      prompt_tokens=200, completion_tokens=100,
                                      estimated=False)
        snapshot = get_usage_accounting().snapshot()
        readout = deploymentAmortization(dev_tokens=500, horizon=100,
                                         usage_snapshot=snapshot)
        assert readout["serving_samples"] == 2
        assert readout["c_bar_task"] == pytest.approx(350.0)
        assert readout["c_total_n"] == pytest.approx(500 + 350.0 * 100)
        assert readout["missing"] == []

    def test_no_samples_report_unevidenced(self, clean_usage):
        """无样本 → N·c̄ 报 unevidenced（C_dev 段照实），不拿 0 冒充。"""
        readout = deploymentAmortization(dev_tokens=500, horizon=100,
                                         usage_snapshot={"total": {"calls": 0,
                                                                   "total_tokens": 0}})
        assert readout["state"] == "insufficient_data"
        assert "c_bar_task" in readout["missing"]
        assert readout["c_total_n"] is None
        assert readout["dev_tokens"] == 500


@pytest.fixture
def clean_usage():
    reset_usage_accounting()
    yield get_usage_accounting()
    reset_usage_accounting()
