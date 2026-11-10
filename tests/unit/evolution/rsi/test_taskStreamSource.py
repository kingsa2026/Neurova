# -*- coding: utf-8 -*-
"""B2 Goal B 固定任务流（survey §10.2，甲案：合成形态种子）。

三纪律三格：不相交（重叠守卫）、固定（确定性加载）、来源登记（provenance
随 fixture 走）；挂 eval/dataset source 体系（source=task_stream）。
"""

import json

import pytest

from neurova.evolution.eval.dataset import evaluation_split
from neurova.evolution.rsi.task_stream import (
    TASK_STREAM_FORMS,
    TASK_STREAM_SOURCE,
    loadTaskStream,
    taskStreamDataset,
    taskStreamOverlapGuard,
    taskStreamProvenance,
)


def test_fixture_loads_three_forms_deterministically():
    """固定加载：三问形态齐备、source=task_stream、同文件同读数。"""
    first = loadTaskStream()
    second = loadTaskStream()
    assert first == second, "任务流加载不确定——评测标尺在漂"
    assert first, "任务流为空——B2 的外部参考没有任务"
    assert all(e.source == TASK_STREAM_SOURCE for e in first)
    forms = set()
    for fixture in json.loads(
            (taskStreamProvenance() and _fixturesPath()).read_text(encoding="utf-8"))["tasks"]:
        forms.add(fixture["form"])
    assert forms == set(TASK_STREAM_FORMS), f"三问形态缺：{forms}"


def _fixturesPath():
    from neurova.evolution.rsi import task_stream as ts
    return ts._FIXTURES_PATH


def test_provenance_registered_with_seed_policy():
    """来源登记：种子策略与回填状态随 fixture 走（甲案＝待回填、seed 空集）。"""
    provenance = taskStreamProvenance()
    assert provenance.get("kind") == "goal_b_task_stream"
    assert provenance.get("seed_session_ids") == [], (
        "甲案种子必须为空集（真语料回填是运维动作，不入 repo）")


def test_overlap_guard_raises_on_intersection():
    """红灯判据本体：同一 session 出现在挖掘与任务流两侧 → 红。"""
    with pytest.raises(ValueError, match="重叠"):
        taskStreamOverlapGuard(["sess-1", "sess-2"], fixture_session_ids=["sess-2"])
    taskStreamOverlapGuard(["sess-1"], fixture_session_ids=["sess-2"])  # 不重叠不抛
    # 甲案现态：fixture 侧空集，任何 mined 集都不相交
    taskStreamOverlapGuard(["sess-anything"])


def test_dataset_mounts_into_source_system():
    """挂 source 体系：数据集入判据集、sourceMix 读数按 task_stream 分组。"""
    ds = taskStreamDataset()
    assert len(evaluation_split(ds)) == len(ds.holdout)
    from neurova.evolution.eval.service import sourceMixOfEvidence

    mix = sourceMixOfEvidence(ds)
    assert mix == {TASK_STREAM_SOURCE: len(ds.holdout)}, (
        f"task_stream 未挂进 source 体系：{mix}")


def test_mined_side_guard_wiring_ready(tmp_path, monkeypatch):
    """挖掘侧出处接线就绪：守卫接受挖掘侧真值集合（回填后即生效）。"""
    # 挖掘侧集合来自调用方——守卫不自己猜（与"读数缺省不参与"同纪律）
    taskStreamOverlapGuard([], fixture_session_ids=[])
    with pytest.raises(ValueError):
        taskStreamOverlapGuard(["s"], fixture_session_ids=["s", "t"])
