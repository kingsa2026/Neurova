# -*- coding: utf-8 -*-
"""C3 ab_library 净接线（survey §10.2，教义第 7 条：接线与新建之间选接线）。

冷热 A/B 原语（run_cold_warm_ab）与 A3 配对探针各自内联了"成对比较聚合"
（fixed/broken 与 improved/regressed 是同一判据的两种命名）——比后合：
聚合收口 `classifyPairwise` 单源，双消费方同读数；ab_library 消费者计数
0→≥1 的在册判据。
"""

import pytest

from neurova.evolution.eval.ab_library import classifyPairwise


def test_classify_pairwise_bool_and_float_same_rule():
    """布尔（A/B pass）与浮点（探针质量）同规则：candidate>baseline 记改善。"""
    assert classifyPairwise([False, True, True], [True, False, True],
                            ["a", "b", "c"]) == {
        "improved": ["a"], "regressed": ["b"], "unchanged": ["c"],
    }
    assert classifyPairwise([0.5, 0.5, 0.6], [0.6, 0.4, 0.6],
                            ["x", "y", "z"]) == {
        "improved": ["x"], "regressed": ["y"], "unchanged": ["z"],
    }


def test_cold_warm_ab_uses_the_shared_aggregation():
    """单源咬合：run_cold_warm_ab 的 fixed/broken 与共享聚合同读数。"""
    import asyncio

    from neurova.evolution.eval.ab_library import run_cold_warm_ab

    async def _executor(task_input, *, skills_enabled, seed=None):
        # cold 全败、warm 全过（构造 fixed 形态）
        return "expected-ok" if skills_enabled else "miss"

    cases = [{"task_input": f"t{i}", "expected": "expected-ok"} for i in range(3)]
    report = asyncio.run(run_cold_warm_ab(cases, _executor))
    assert report["fixed"] == ["t0", "t1", "t2"]
    assert report["broken"] == []
    shared = classifyPairwise([False] * 3, [True] * 3, ["t0", "t1", "t2"])
    assert report["fixed"] == shared["improved"], (
        "冷热 A/B 的聚合没走共享机器——双源并存")


def test_paired_probe_arms_carry_shared_classification():
    """探针的臂读数经共享聚合出 improved/regressed（与直算同读数）。"""
    from neurova.evolution.rsi.candidate_policy import CandidatePolicy
    from neurova.evolution.rsi.improver_paired_probe import ImproverPairedProbe

    def _mk(version):
        return CandidatePolicy(
            version=version, summary="s",
            setpoint_lookup=lambda s, n: 0.8,
            performance_extractor=lambda signals: 0.5,
            sealed_validator=None,
        )

    states = [{"system": "s", "param": f"p{i}", "current": 0.85, "setpoint": 0.8}
              for i in range(12)]

    def outcome(state, candidate):
        if candidate is None:
            return 0.5
        # 确定性结局流：按参数名分 improved/regressed/unchanged 三段
        idx = int(state["param"][1:])
        new_value = candidate.metadata["optimization"]["new_value"]
        return 0.3 if idx % 3 == 0 else (0.7 if idx % 3 == 1 else 0.5) + 0.0 * new_value

    probe = ImproverPairedProbe(
        policy_t=_mk("I_t"), policy_0=_mk("I_0"),
        starting_states=lambda: states,
        outcome_evaluator=outcome,
    )
    readout = probe.run()
    shared = classifyPairwise(
        [p["quality_0"] for p in readout["pairs"]],
        [p["quality_t"] for p in readout["pairs"]],
        [p["state"] for p in readout["pairs"]],
    )
    assert readout["arms"]["full"].get("improved") == shared["improved"], (
        "探针臂分类没走共享聚合——第二套判据机器")
    assert readout["arms"]["full"].get("regressed") == shared["regressed"]


def test_ab_library_consumer_count_is_registered():
    """在册判据：共享聚合的消费方 ≥2（A/B 原语＋配对探针）——0 消费者史终结。"""
    import subprocess

    result = subprocess.run(
        ["grep", "-rln", "classifyPairwise", "neurova/"],
        capture_output=True, text=True, cwd=".",
    )
    files = [line for line in result.stdout.splitlines() if line.strip()]
    assert len(files) >= 2, (
        f"classifyPairwise 消费方不足（{files}）——净接线未闭环")
