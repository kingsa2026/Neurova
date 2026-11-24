# -*- coding: utf-8 -*-
"""D7 自动调参工具判据：报告形状 / 择优 / 回写设置 / 报告落盘。"""
from __future__ import annotations

import pytest

from neurova.benchmark.recall_auto_tune import load_last_report, run_recall_auto_tune
from neurova.cognitive_layers.memory_layer.settings_config import (
    MemorySettingsConfig,
    get_memory_settings,
)


@pytest.fixture
def settings(tmp_path):
    MemorySettingsConfig.reset_instance()
    cfg = get_memory_settings(str(tmp_path))
    yield cfg
    MemorySettingsConfig.reset_instance()


def test_report_shape_and_no_apply(settings, tmp_path):
    report = run_recall_auto_tune(
        floors=[0.4, 0.9], apply=False, work_dir=str(tmp_path / "w1")
    )
    assert report["applied"] is False
    assert [c["floor"] for c in report["candidates"]] == [0.4, 0.9]
    assert all("mrr" in c and "hit5" in c for c in report["candidates"])
    assert report["best"]["floor"] in (0.4, 0.9)
    assert report["baseline_without_temp"] is not None
    # apply=False：设置不被改动
    assert get_memory_settings().get("recall.temp_channel_relevance_floor") == 0.6


def test_apply_writes_best_floor_and_persists_report(settings, tmp_path):
    report = run_recall_auto_tune(
        floors=[0.4, 0.9], apply=True, work_dir=str(tmp_path / "w2")
    )
    assert report["applied"] is True
    assert get_memory_settings().get(
        "recall.temp_channel_relevance_floor"
    ) == report["best"]["floor"]
    last = load_last_report()
    assert last is not None and last["best"]["floor"] == report["best"]["floor"]


def test_floor_candidates_clamped(settings, tmp_path):
    report = run_recall_auto_tune(
        floors=[-1.0, 2.0], apply=False, work_dir=str(tmp_path / "w3")
    )
    assert [c["floor"] for c in report["candidates"]] == [0.0, 1.0]
