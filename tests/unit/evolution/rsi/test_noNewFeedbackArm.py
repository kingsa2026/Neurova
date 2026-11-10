# -*- coding: utf-8 -*-
"""F3 无新反馈对照臂（survey §10.2）——实验档切断外部参考，读数以臂为键。

红灯判据：该臂读数与主臂分列可查；混臂即红（读数以臂为键，单源登记）。
"""

import pytest

from neurova.evolution.rsi.orchestrator import RSIOrchestrator


def _orch(monkeypatch, arm):
    from unittest.mock import MagicMock

    monkeypatch.delenv("NEUROVA_RSI_IMPROVER_LEDGER", raising=False)
    monkeypatch.setenv("NEUROVA_RSI_F3_ARM", arm)
    return RSIOrchestrator(
        sleep_system=MagicMock(), emotion_system=MagicMock(),
        experience_system=MagicMock(), tool_memory_system=MagicMock(),
    )


def test_main_arm_collects_reference(monkeypatch):
    orch = _orch(monkeypatch, "main")
    orch._recordProxyReferencePair(0.5, 0.6)
    readout = orch._proxyReferenceReadout()
    assert readout["arm"] == "main"
    assert readout["channel"].startswith("e2e_alignment")


def test_experiment_arm_cuts_reference_collection(monkeypatch):
    """实验档：参考列切断（None 登记），臂键如实标注。"""
    orch = _orch(monkeypatch, "no_new_feedback")
    orch._recordProxyReferencePair(0.5, None)
    readout = orch._proxyReferenceReadout()
    assert readout["arm"] == "no_new_feedback"
    assert readout["channel"].startswith("no_new_feedback")


def test_mixed_arm_series_rejected(monkeypatch):
    """红灯判据本体：混臂读数当场红（主臂与实验臂数字不许混栏）。"""
    orch = _orch(monkeypatch, "main")
    orch._recordProxyReferencePair(0.5, 0.6)
    orch._proxyReferencePairs.append(
        {"proxy": 0.6, "reference": None, "arm": "no_new_feedback"})
    with pytest.raises(ValueError, match="混臂"):
        orch._proxyReferenceReadout()


def test_invalid_arm_name_rejected_at_construction(monkeypatch):
    """臂名单源：非 main/no_new_feedback 的构造被拒（实验档不开放任意臂名）。"""
    with pytest.raises(ValueError, match="臂名非法"):
        _orch(monkeypatch, "creative_arm")
