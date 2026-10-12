# -*- coding: utf-8 -*-
"""检索地板判据（批次 K3 / 断点 N3）。

缺陷：台架建了 `evaluation_cases/runs/findings` 三表、有 `freezeBaseline`、REST 读面
（`knowledge_core.py:214-221`）也备好了，但 `seedFromRepository` 与 `freezeBaseline`
**生产零调用点**，且 `data/knowledge/` 里连 `knowledge_evaluation.db` 这个文件都不存在
——台架从未对任何数据跑过。于是改一路检索权重、改 hop 上限、开 `NEUROVA_KB_FACT_SURFACE`
都不会有任何东西变红：检索质量**没有地板**。

本批两片（用户 2026-10-09 拍板「真库跑一次取读数 + 合成夹具做闸」）：
① `tests/manual/retrievalBaselineLive.py` 对真库跑一次并冻基线，台账只记聚合读数
   （真库 36 条全是 private，导出查询串等于把用户私有语料交出去）；
② 本文件——把地板做成**别人 clone 下来也会红**的形态。只跑真库不闭这一格：
   基线若只活在某人机器的一个运行时文件里，评测集在别人那儿为空、CI 永绿。

跑法只有一处定义（`tests/fixtures/knowledge_retrieval/harness.py`），"算不算退步"
也只有一处（`RetrievalBenchmark.compareAgainstBaseline`）——本文件不另拼一份 hybrid 调用、
也不自己写裁决，否则门拦的是两套装配之差。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from neurova.knowledge.evaluation.retrieval_benchmark import RetrievalBenchmark
from neurova.knowledge.foundation.storage_fence import PRODUCTION_STORAGE_DIR
from tests.fixtures.knowledge_retrieval.harness import (
    BASELINE_PATH,
    openGate,
    runGateBenchmark,
    runOnce,
)

_KEYS = ("recall_at_k", "mrr", "unhit_rate")


@pytest.fixture(scope="module")
def floor() -> dict:
    """入库基线（尺子）。故意 module 级：它是**被对照物**，每用例重解析一次会掩盖漂移。"""
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


class TestFloorIsReproducible:
    def test_currentRunMatchesTheCommittedFloor(self, tmp_path, floor):
        report = runGateBenchmark(tmp_path)

        for key in _KEYS:
            assert report[key] == pytest.approx(floor["readings"][key], abs=0.0), (
                "%s 与入库基线不一致：先判是语料动的还是管路动的，再决定改基线还是修检索" % key)
        assert report["case_count"] == floor["case_count"]
        assert report["labeling_breakdown"] == floor["labeling_breakdown"]

    def test_threeLabelingMethodsAllProduceCases(self, tmp_path):
        """真库那次跑出 29/1/0（标签为空），那种形状下"管路通"会被当成"检索准"。

        地板若只钉住标题直取这一条路，tag/category 两路整段哑掉也照绿——所以这一格
        钉的是**评测集形状**，不是检索读数。
        """
        breakdown = runGateBenchmark(tmp_path)["labeling_breakdown"]

        for method in ("title_literal", "tag", "category"):
            assert breakdown.get(method, 0) > 0, "%s 口径零产例，地板少一条腿" % method

    def test_runningTheGateNeverTouchesTheRealKnowledgeDirectory(self, tmp_path):
        """门必须跑在合成语料上：碰真库的判据在别人那儿要么空转要么假红。"""
        before = sorted(p.name for p in Path(PRODUCTION_STORAGE_DIR).iterdir()) \
            if Path(PRODUCTION_STORAGE_DIR).exists() else []

        gate = openGate(tmp_path)
        try:
            runOnce(gate)
        finally:
            gate["bench"].close()

        after = sorted(p.name for p in Path(PRODUCTION_STORAGE_DIR).iterdir()) \
            if Path(PRODUCTION_STORAGE_DIR).exists() else []
        assert after == before, "跑门在生产知识库目录里落了新东西：%s" % (set(after) - set(before))


class TestFloorActuallyBites:
    """反证三格：地板不咬人等于没有地板。"""

    def test_gateWouldCatchSearchGoingDark(self, tmp_path, floor):
        gate = openGate(tmp_path)
        try:
            baselineRun = runOnce(gate)
            gate["bench"].freezeBaseline(baselineRun, note="反证用临时基线")

            dark = runOnce(gate, searchOverride=lambda _query: [])
            verdict = gate["bench"].compareAgainstBaseline(dark)

            assert verdict["verdict"] == "regress", verdict
            assert verdict["newly_unhit_cases"], "整条检索路哑掉，逐案却无一例判丢——裁决写虚了"
            for key in _KEYS:
                assert verdict["deltas"], "聚合差值没算出来"
        finally:
            gate["bench"].close()

    def test_comparatorRefusesToCompareTheBaselineWithItself(self, tmp_path):
        gate = openGate(tmp_path)
        try:
            only = runOnce(gate)
            gate["bench"].freezeBaseline(only, note="同 run 自比")

            verdict = gate["bench"].compareAgainstBaseline(only)

            assert verdict["verdict"] == "self_reference", verdict
            assert verdict.get("newly_unhit_cases") is None or not verdict["newly_unhit_cases"]
        finally:
            gate["bench"].close()

    def test_missingFloorIsUnevidencedNotPass(self, tmp_path):
        """没冻基线时绝不回 `pass`——没测过的事报成没退化，是门禁最坏的失效方向。"""
        bench = RetrievalBenchmark(str(Path(tmp_path) / "knowledge_evaluation.db"))
        try:
            verdict = bench.compareAgainstBaseline({"run_id": "evr_none"})
            assert verdict["verdict"] == "unevidenced", verdict
            assert "基线" in verdict["missing_reason"]
        finally:
            bench.close()
