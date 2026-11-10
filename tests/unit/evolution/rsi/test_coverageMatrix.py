# -*- coding: utf-8 -*-
"""H1 覆盖读数（survey §10.2）——任务族×覆盖矩阵，未覆盖族逐名告警。

分母口径先定死（期望族单源＝harness 决策档∪任务流形态，从注册表取
不手抄）；合成缺族序列 → 告警点名族名；分母变更走单源守卫。
"""

import pytest

from neurova.evolution.rsi.coverage import coverageReadout, expectedFamilies


def test_missing_family_is_named():
    """红灯判据本体：合成缺族序列 → 告警点名族名。"""
    families = expectedFamilies()
    readout = coverageReadout(families[:-1])  # 缺最后一个族
    assert readout["alert"] is True
    assert readout["uncovered"] == [families[-1]], (
        f"缺族没点名：{readout['uncovered']}")


def test_full_coverage_no_alert():
    readout = coverageReadout(expectedFamilies())
    assert readout["alert"] is False
    assert readout["uncovered"] == []


def test_denominator_is_single_sourced_from_registries():
    """分母单源守卫：期望族从两张注册表读出（决策档四族∪任务流三形态）。"""
    from neurova.evolution.rsi.eval_harness import splitSealedCases
    from neurova.evolution.rsi.task_stream import TASK_STREAM_FORMS

    decision, _ = splitSealedCases()
    harness_families = {family for _c, family, _fn in decision}
    expected = set(expectedFamilies())
    assert harness_families <= expected, (
        f"harness 族缺出分母：{harness_families - expected}")
    assert set(TASK_STREAM_FORMS) <= expected, (
        f"任务流形态缺出分母：{set(TASK_STREAM_FORMS) - expected}")
    # 手抄防线：分母不含注册表之外的族
    extra = expected - harness_families - set(TASK_STREAM_FORMS)
    assert not extra, f"分母出现注册表之外的族（手抄态）：{extra}"


def test_orchestrator_surfaces_coverage(tmp_path, monkeypatch):
    from unittest.mock import MagicMock

    from neurova.evolution.rsi.orchestrator import RSIOrchestrator

    monkeypatch.delenv("NEUROVA_RSI_IMPROVER_LEDGER", raising=False)
    orch = RSIOrchestrator(
        sleep_system=MagicMock(), emotion_system=MagicMock(),
        experience_system=MagicMock(), tool_memory_system=MagicMock(),
    )
    readout = orch.get_status().get("coverage")
    assert isinstance(readout, dict)
    assert "uncovered" in readout and "alert" in readout
