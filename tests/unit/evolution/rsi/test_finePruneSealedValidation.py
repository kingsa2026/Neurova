# -*- coding: utf-8 -*-
"""G1 剪枝细筛补实装（survey §10.2，拍板：补实装路线）。

细筛 docstring 声称"完整测试套件/安全审计"等校验步，实装却只是方向公式
（survey §3.2③ 教义第 2 条诚实形态问题）。本批补实装：校验步接 D1 密封档——
候选步进值代入活值快照副本实跑密封用例（复用既有机器不新建），例级对照
当前态出 regressions；真实系统不得被校验过程改动。
"""

import pytest

from neurova.evolution.rsi.recursive_ratchet_pruner import Candidate


@pytest.fixture
def probe(rsi_probe_factory):
    """phase 2 自动执行档 + tool_memory 真实梯度（0.5 vs setpoint 0.8）。"""
    return rsi_probe_factory(
        rsi_phase=2,
        tool_memory_params={"muscle_memory_threshold": 0.5},
    )


def _cand(cid, new_value, *, heuristic, quick):
    return Candidate(
        id=cid,
        name=cid,
        parameters={"adjustment_ratio": 0.1},
        complexity=1.0,
        heuristic_score=heuristic,
        quick_evaluation_score=quick,
        metadata={"optimization": {
            "system": "tool_memory",
            "parameter": "tool_memory.muscle_memory_threshold",
            "current_value": 0.5,
            "new_value": new_value,
            "setpoint": 0.8,
            "performance": 0.5,
        }},
    )


def test_sealed_validation_runs_the_claimed_step(probe):
    """探针走到声称的校验步：候选值代入密封档实跑，例级对照出 regressions。

    非数值步进值能漏过方向校验（isinstance 门跳过 toward 检查）——密封档实跑
    是它在应用前的最后一道网（A5 元优化候选的安全前置）。
    """
    orch = probe.orchestrator
    bad_opt = {
        "system": "tool_memory",
        "parameter": "tool_memory.muscle_memory_threshold",
        "current_value": 0.5,
        "new_value": "0.9-with-garbage",  # 非数值：方向校验放行，密封档必须抓住
        "setpoint": 0.8,
    }

    readout = orch._sealedCandidateValidation(bad_opt)

    assert readout["state"] == "measured", f"密封档实跑没跑起来：{readout}"
    assert "tm_threshold_band" in readout["regressions"], (
        f"打崩密封用例的候选值没被例级对照抓住：{readout}")
    assert readout["score"] is not None and readout["score"] < readout["baseline"], (
        f"密封分未因塌方例低于当前态基线：{readout}")


def test_sealed_validation_does_not_touch_real_systems(probe):
    """校验是代入快照的推演：真实系统参数在前后逐值不变。"""
    orch = probe.orchestrator
    before = dict(probe.systems["tool_memory"].get_parameters()
                  if hasattr(probe.systems["tool_memory"], "get_parameters")
                  else {})
    if not before:
        # ProbeSystem 的参数面：直接从编排器读同一份活值快照
        before = {p.name: p.current_value
                  for p in orch.integration_manager.get_optimizable_parameters()
                  .get("tool_memory", [])}

    orch._sealedCandidateValidation({
        "system": "tool_memory",
        "parameter": "tool_memory.muscle_memory_threshold",
        "current_value": 0.5,
        "new_value": "garbage",
        "setpoint": 0.8,
    })

    after = {p.name: p.current_value
             for p in orch.integration_manager.get_optimizable_parameters()
             .get("tool_memory", [])}
    assert after == before, f"校验过程改动了真实系统：{before} → {after}"


def test_pruner_demotes_sealed_breaking_candidate(probe):
    """端到端：密封档塌方的候选即便启发式/快评分最高，也必须在细筛被撤下。

    改前该候选凭方向公式满分通过（docstring 声称的校验步未实装），
    会被应用进真实参数——坏值进生产靠回滚兜底；补实装后应用前即拦。
    """
    orch = probe.orchestrator
    safe = _cand("safe-step", 0.55, heuristic=0.4, quick=0.2)      # 朝 setpoint 的正常步进
    breaking = _cand("garbage-step", "0.9-with-garbage", heuristic=0.9, quick=0.8)

    best = orch._prune_candidates([safe, breaking], signals={})

    assert best is not None
    assert best.id == "safe-step", (
        f"密封档塌方候选胜出：{best.id}——细筛校验步没咬合")
