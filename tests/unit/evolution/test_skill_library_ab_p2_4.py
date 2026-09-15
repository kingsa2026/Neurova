"""P2-4 技能库 cold/warm A/B 评测（OpenSpace benchmark 方法论移植 + 避坑）

OpenSpace 的 65.2%→78.7% warm 数字把**同任务 verifier 输出/reward/验收目标**
打包成技能注入（带答案重放），不能当技能库泛化收益引用（对比报告 §2.11）。
本 harness 的可信度纪律：

1. verifier 只在**评分面**出现，永不进 executor 参数（执行面只见任务）；
2. warm 种子只许白名单字段（任务输入/成功工具序列/无答案摘要）——
   含 verifier/reward/expected/acceptance 等答案形态键即拒绝；
3. 报告如实呈现退化（degraded/broken），不做只报喜聚合。
"""

import pytest

from neurova.evolution.eval.ab_library import (
    SeedLeakError,
    build_seed_from_successful_run,
    run_cold_warm_ab,
    sanitize_warm_seed,
)


def _cases():
    return [
        {"task_input": "t1", "expected": "ok1"},
        {"task_input": "t2", "expected": "ok2"},
        {"task_input": "t3", "expected": "ok3"},
    ]


@pytest.mark.asyncio
async def test_warm_beats_cold_reported():
    """warm（开技能库）通过率高于 cold → 数字如实进报告。"""

    async def executor(task_input, *, skills_enabled, seed=None):
        # 假象：开库后 t1/t2 会做对，t3 都不会
        return "ok1" if (skills_enabled and task_input == "t1") else (
            "ok2" if (skills_enabled and task_input == "t2") else "fail"
        )

    report = await run_cold_warm_ab(_cases(), executor)
    assert report["cold_pass_rate"] == 0.0
    assert report["warm_pass_rate"] == pytest.approx(2 / 3)
    assert report["delta"] == report["warm_pass_rate"] - report["cold_pass_rate"]
    assert sorted(report["fixed"]) == ["t1", "t2"]
    assert report["broken"] == []


@pytest.mark.asyncio
async def test_degradation_reported_honestly():
    async def executor(task_input, *, skills_enabled, seed=None):
        return "ok" if not skills_enabled else "bad"

    cases = [{"task_input": f"t{i}", "expected": "ok"} for i in range(3)]
    report = await run_cold_warm_ab(cases, executor)
    assert report["warm_pass_rate"] == 0.0
    assert len(report["broken"]) == 3, "warm 退化必须如实记账，不报喜不报忧"


@pytest.mark.asyncio
async def test_verifier_never_reaches_executor():
    """执行面只见任务，评分面才见预期——OpenSpace warm 分支泄漏的根治。"""
    seen_kwargs = []

    async def executor(task_input, *, skills_enabled, seed=None):
        seen_kwargs.append({"task_input": task_input, "seed": seed})
        return "ok"

    cases = [{"task_input": "t1", "expected": "super-secret-answer"}]
    await run_cold_warm_ab(cases, executor)
    flat = repr(seen_kwargs)
    assert "super-secret-answer" not in flat


@pytest.mark.asyncio
async def test_warm_runs_in_seed_mode_not_verifier_mode():
    seeds_passed = []

    async def executor(task_input, *, skills_enabled, seed=None):
        if skills_enabled:
            seeds_passed.append(seed)
        return "ok"

    run_record = {
        "task_input": "t1",
        "tool_sequence": ["web_search", "file_write"],
        "success": True,
        "verifier_output": "SHOULD NOT LEAK",
    }
    seed = build_seed_from_successful_run(run_record)
    cases = [{"task_input": "t1", "expected": "ok", "warm_seed": seed}]
    await run_cold_warm_ab(cases, executor)
    assert seeds_passed and "SHOULD NOT LEAK" not in repr(seeds_passed)
    assert seeds_passed[0]["tool_sequence"] == ["web_search", "file_write"]


def test_sanitize_warm_seed_whitelist():
    seed = sanitize_warm_seed(
        {"task_input": "t", "tool_sequence": ["a"], "summary": "用了两把工具", "junk": "x"}
    )
    assert seed == {"task_input": "t", "tool_sequence": ["a"], "summary": "用了两把工具"}


@pytest.mark.parametrize("bad_key", ["verifier_output", "reward", "expected_answer", "acceptance_targets", "test_stdout"])
def test_sanitize_warm_seed_rejects_answer_bearing_keys(bad_key):
    with pytest.raises(SeedLeakError):
        sanitize_warm_seed({"task_input": "t", bad_key: "42"})


def test_build_seed_strips_verifier():
    seed = build_seed_from_successful_run(
        {"task_input": "t", "tool_sequence": ["a"], "success": True, "reward": 1.0}
    )
    assert "reward" not in seed
    assert seed["tool_sequence"] == ["a"]


def test_build_seed_rejects_failed_run():
    with pytest.raises(ValueError):
        build_seed_from_successful_run({"task_input": "t", "success": False})
