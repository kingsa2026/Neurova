# -*- coding: utf-8 -*-
"""M-B：联合轮的**族级归因读数**（ModularRSI 对照 §4 M-B；台账记有本格）。

## 缺陷形态

`rsi/orchestrator.py:409-434` 的一轮动作是：对**每个**参数各产 1 个最优候选
（`generate_optimizations()`，:853-868「每个参数最多 1 个最优候选」）→ `apply_optimizations()`
全量应用 → **一次** `perf_after - perf_before` → 一次 `rollback_manager.should_rollback`
对整体快照回滚。提名按参数、判定与回滚按整轮，于是「这轮涨了」永远回答不了
「是哪一族动的」——观测面上只留着 `optimizations` 与 `applied_results` 两个平铺列表。

对照给出的论据是「联合演化在消融里掉分」；但本仓**不能直接拆轮**：
`rsi/parameter_activity.py:5-9` 实测 262 行真账里 11 个参数只有 7 个出现过，4 个
`never_proposed`，把一轮拆成五轮多数轮次会在无数据上空转且每轮都要付一次评测成本。
本批因此**只加归因读数，不动动作粒度**（用户裁定的档位）。

## 判据钉四件事

- **A 随行**：`run_iteration()` 的返回体带 `family_attribution`，且参数表里**每一族都在**
  （缺族就是把"这族本轮没动"和"这族不存在"折叠成同一件事——`parameter_activity` 的
  `never_proposed ≠ sparse ≠ no_data` 三态纪律，不许折叠）。
- **B 实质**：被应用过的那一族必须给出逐参数的 `from`/`to`，光有计数证不了改了什么。
- **C 跨文件闭环**：同一份读数必须经 `summarize_rsi_result()` 投影出去、并经
  `get_latest_rsi_summary()` 被读回来。**只写不读的观测面就是本仓自己明令的断点。**
- **D 诚实边界**：读数里不得出现按族拆开的 gain（本仓一轮只有一次 gain）——
  写成 `gain_scope == "round"`，防止后来人把这格读成"各族贡献已分离"。

替身只在系统边界（探针的四系统来自 `tests/unit/evolution/conftest.py`，与既有 RSI 批次同形）。
"""
from __future__ import annotations

from typing import Any, Dict, List

import pytest

ALLOWED_STATUSES = {"acted", "proposed_not_applied", "no_candidate", "placeholder_host"}


def _attributionOf(optimizations: List[Dict[str, Any]], applied: List[Dict[str, Any]],
                   *, tableFamilies, placeholderSystems=()):
    from neurova.evolution.rsi.orchestrator import familyAttribution

    return familyAttribution(optimizations, applied,
                             tableFamilies=tableFamilies,
                             placeholderSystems=list(placeholderSystems))


class TestFamilyAttributionIsPureReading:
    """归因函数本身的四态判定（不需要起编排器，也不碰判据语义之外的东西）。"""

    def test_A_everyTableFamilyIsPresentNeverSilentlyDropped(self):
        attribution = _attributionOf(
            [{"system": "tool_memory", "parameter": "tool_memory.success_bonus",
              "current_value": 0.15, "new_value": 0.18}],
            [{"parameter": "tool_memory.success_bonus", "new_value": 0.18, "applied": True}],
            tableFamilies=["sleep", "tool_memory"],
        )
        rows = attribution["by_family"]
        assert set(rows) == {"sleep", "tool_memory"}, (
            f"族集合必须等于参数表全集，实得 {sorted(rows)}"
        )
        assert rows["sleep"]["status"] == "no_candidate", (
            f"没提名的族应判 no_candidate，实得 {rows['sleep']}"
        )

    def test_B_appliedFamilyCarriesPerParameterFromTo(self):
        attribution = _attributionOf(
            [{"system": "tool_memory", "parameter": "tool_memory.success_bonus",
              "current_value": 0.15, "new_value": 0.18}],
            [{"parameter": "tool_memory.success_bonus", "new_value": 0.18, "applied": True}],
            tableFamilies=["tool_memory"],
        )
        row = attribution["by_family"]["tool_memory"]
        assert row["status"] == "acted"
        assert row["applied"] == 1 and row["proposed"] == 1
        detail = row["params"][0]
        assert (detail["parameter"], detail["from"], detail["to"], detail["applied"]) == (
            "tool_memory.success_bonus", 0.15, 0.18, True
        ), f"逐参数改前改后必须随行，实得 {detail}"

    def test_C_blockedProposalIsNotFoldedIntoNoCandidate(self):
        """有提名但一件没应用成 ⇒ proposed_not_applied，不是 no_candidate。"""
        attribution = _attributionOf(
            [{"system": "sleep", "parameter": "sleep.similarity_threshold",
              "current_value": 0.3, "new_value": 0.33}],
            [{"parameter": "sleep.similarity_threshold", "new_value": 0.33, "applied": False}],
            tableFamilies=["sleep"],
        )
        row = attribution["by_family"]["sleep"]
        assert row["status"] == "proposed_not_applied", (
            f"折叠了『闸拦下了』与『本来就没候选』：{row}"
        )

    def test_D_placeholderHostIsItsOwnState(self):
        """缺席/替身系统是第三种状态，既不是没候选也不是被闸拦。"""
        attribution = _attributionOf([], [], tableFamilies=["context"],
                                     placeholderSystems=["context"])
        row = attribution["by_family"]["context"]
        assert row["status"] == "placeholder_host", (
            f"替身族被判成 {row['status']}——观测面上与『跑过了但没空间』不可分"
        )

    def test_E_noPerFamilyGainIsInvented(self):
        attribution = _attributionOf(
            [{"system": "sleep", "parameter": "sleep.base_decay_rate",
              "current_value": 0.2, "new_value": 0.22}],
            [{"parameter": "sleep.base_decay_rate", "new_value": 0.22, "applied": True}],
            tableFamilies=["sleep"],
        )
        assert attribution["gain_scope"] == "round", (
            "本仓一轮只有一次 gain；出现按族拆的 gain 字段就是造假归因"
        )
        for family, row in attribution["by_family"].items():
            assert "gain" not in row, f"{family} 族行里出现了 gain：{row}"

    def test_F_statusVocabularyIsClosed(self):
        attribution = _attributionOf([], [], tableFamilies=["a", "b"], placeholderSystems=["b"])
        bad = {f: r["status"] for f, r in attribution["by_family"].items()
               if r["status"] not in ALLOWED_STATUSES}
        assert not bad, f"越界状态：{bad}（允许 {sorted(ALLOWED_STATUSES)}）"


class TestFamilyAttributionIsWiredAndRead:
    """随行、投影、读回三段必须真接通——只写不读就是本仓自己的断点。"""

    def test_01_runIterationCarriesItForEveryTableFamily(self, rsi_probe_factory):
        probe = rsi_probe_factory(rsi_phase=0)
        result = probe.orchestrator.run_iteration()
        attribution = result.get("family_attribution")
        assert isinstance(attribution, dict), (
            "run_iteration 返回体没有 family_attribution——联合轮的归因读数还没随行"
        )
        tableFamilies = list(probe.orchestrator.integration_manager
                             .get_optimizable_parameters().keys())
        assert set(attribution["by_family"]) == set(tableFamilies), (
            f"随行读数缺族：表里 {tableFamilies}，读数 {sorted(attribution['by_family'])}"
        )
        assert attribution["gain_scope"] == "round"

    def test_02_summaryProjectsItAndReadoutCarriesItBack(self, rsi_probe_factory):
        from neurova.evolution.rsi import result_summary

        probe = rsi_probe_factory(rsi_phase=0)
        result = probe.orchestrator.run_iteration()
        summary = result_summary.summarize_rsi_result(result)
        assert summary is not None
        assert "family_attribution" in summary, (
            "摘要投影把这格丢了——落库的 jsonl 与响应面都看不见归因，写了等于没写"
        )
        recorded = result_summary.record_rsi_summary("attr-agent", "attr-session", result, turn=3)
        assert recorded is not None
        readBack = result_summary.get_latest_rsi_summary("attr-agent", "attr-session")
        assert readBack is not None
        assert readBack.get("family_attribution") == summary["family_attribution"], (
            "读侧拿不到或值不一致——这一格就成了只写不读的观测面"
        )

    def test_03_countsAreConsistentWithTheFlatListsTheySummarize(self, rsi_probe_factory):
        probe = rsi_probe_factory(rsi_phase=0)
        result = probe.orchestrator.run_iteration()
        attribution = result["family_attribution"]["by_family"]
        proposedTotal = sum(row["proposed"] for row in attribution.values())
        appliedTotal = sum(row["applied"] for row in attribution.values())
        assert proposedTotal == len(result.get("optimizations") or []), (
            f"族级提名合计 {proposedTotal} 与平铺 optimizations "
            f"{len(result.get('optimizations') or [])} 不等——两份口径在漂"
        )
        assert appliedTotal == int(result.get("applied_count") or 0), (
            f"族级应用合计 {appliedTotal} 与 applied_count "
            f"{result.get('applied_count')} 不等"
        )

    def test_04_familiesWithoutTableEntryAreNotInvented(self, rsi_probe_factory):
        probe = rsi_probe_factory(rsi_phase=0)
        result = probe.orchestrator.run_iteration()
        table = set(probe.orchestrator.integration_manager.get_optimizable_parameters().keys())
        extra = set(result["family_attribution"]["by_family"]) - table
        assert not extra, f"读数里冒出参数表之外的族 {extra}——第二份族清单"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
