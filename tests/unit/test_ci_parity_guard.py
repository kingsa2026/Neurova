# -*- coding: utf-8 -*-
"""CI 双远端门禁对齐守卫（.cnb.yml vs .github/workflows/ci.yml）。

背景：cnb 侧 CI 曾长期是样例空壳（只 echo），前端门禁只在 GitHub 生效；
2026-09-17 补齐 .cnb.yml 后，两份配置存在"各自演进、静默漂移"的风险——
一侧加门禁另一侧不知道，放行标准悄然分叉。

本守卫锁定四件事：

1. **覆盖集**：GitHub 每个 job 必须在 cnb 有对应流水线（unit-tests 的
   matrix 两格对应 py311/py312 两条流水线）；反向不得有多余流水线；
2. **命令同源**：每对 job/pipeline 的核心门禁命令逐字一致（语义漂移
   最常见形态就是命令被"顺手改一下"）；
3. **放行标准**：非阻塞语义对齐（GitHub continue-on-error ↔ cnb allowFailure）；
4. **防再生**：cnb 不得退回样例空壳（echo 流水线 = 无门禁）。

合法的映射变更流程：同时改两份配置 + 同步更新本文件的 EXPECTED 映射表，
提交说明写明差异原因。
"""
import io
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CNB = PROJECT_ROOT / ".cnb.yml"
GHW = PROJECT_ROOT / ".github" / "workflows" / "ci.yml"

# job 名（GitHub）→ 流水线名列表（cnb）；unit-tests matrix 两格拆两条
EXPECTED_MAP = {
    "static-gate": ["static-gate"],
    "lint": ["lint"],
    "import-and-regression": ["import-and-regression"],
    "unit-tests": ["unit-tests-py311", "unit-tests-py312"],
    "e2e": ["e2e-backend-boot"],
    "frontend": ["frontend"],
    "dependency-audit": ["dependency-audit"],
}

# 非阻塞（允许失败）的 job：两侧行为必须一致
EXPECTED_NON_BLOCKING = {"dependency-audit"}

# 每对 job/pipeline 的核心门禁命令（"存在于该侧全部脚本中"断言）。
# 命令改动若属两例试图不同步，这里会红。
EXPECTED_CORE_COMMANDS = {
    "static-gate": ["python scripts/ci_static_gate.py --skip-import"],
    "lint": ["python -m ruff check neurova tests --no-cache"],
    "import-and-regression": [
        "python scripts/ci_static_gate.py",
        "python -m pytest tests/unit/test_audit_regressions.py -q",
    ],
    "unit-tests": [
        "scripts/ci/protected_tests.txt",
        "--cov-fail-under=60",
        "requirements-ci.lock",
    ],
    "e2e": ["python -m pytest tests/e2e/test_backend_boot.py -q --timeout 240"],
    "frontend": ["npx vue-tsc --noEmit", "npx vitest run"],
    "dependency-audit": ["python -m pip_audit -r requirements-ci.lock"],
}


@pytest.fixture(scope="module")
def cnb_pipelines():
    assert CNB.exists(), ".cnb.yml 丢失——cnb 门禁退化为无"
    data = yaml.safe_load(io.open(CNB, encoding="utf-8").read())
    main = data.get("main") or {}
    push = main.get("push")
    assert isinstance(push, list), ".cnb.yml main.push 不是流水线数组（可能退回样例空壳）"
    by_name = {}
    for p in push:
        if isinstance(p, dict) and p.get("name"):
            by_name[p["name"]] = p
    # 防再生：echo 空壳必须被抓住
    assert by_name, ".cnb.yml 无具名流水线——cnb 门禁退化为样例空壳"
    return by_name


@pytest.fixture(scope="module")
def ghw_jobs():
    assert GHW.exists(), ".github/workflows/ci.yml 丢失——GitHub 门禁退化为无"
    data = yaml.safe_load(io.open(GHW, encoding="utf-8").read())
    jobs = (data.get("jobs") or {})
    assert jobs, "ci.yml 无 job 定义"
    return jobs


def _pipeline_scripts(pipe: dict) -> str:
    out = []
    for stage in pipe.get("stages") or []:
        if isinstance(stage, dict) and stage.get("script"):
            out.append(str(stage["script"]))
    return "\n".join(out)


def _job_scripts(job: dict) -> str:
    out = []
    for step in job.get("steps") or []:
        if isinstance(step, dict) and step.get("run"):
            out.append(str(step["run"]))
    return "\n".join(out)


class TestCoverage:
    def test_every_github_job_has_cnb_counterpart(self, cnb_pipelines, ghw_jobs):
        missing = []
        for job_name in ghw_jobs:
            expected = EXPECTED_MAP.get(job_name)
            if expected is None:
                continue  # 新 job 未登记映射 → 由 test_mapping_registry_is_complete 红
            for pipe_name in expected:
                if pipe_name not in cnb_pipelines:
                    missing.append(f"ci.yml job '{job_name}' 缺 cnb 流水线 '{pipe_name}'")
        assert not missing, (
            "GitHub 门禁在 cnb 侧缺失（放行标准分叉）:\n  " + "\n  ".join(missing) +
            "\n合法流程：补齐 .cnb.yml 并同步 EXPECTED_MAP。"
        )

    def test_no_extra_cnb_pipelines(self, cnb_pipelines, ghw_jobs):
        """cnb 侧不得有映射表之外的流水线（防一侧私自加门禁/残留死流水线）。"""
        known = {name for names in EXPECTED_MAP.values() for name in names}
        extra = sorted(set(cnb_pipelines) - known)
        assert not extra, (
            f"cnb 存在未登记映射的流水线: {extra}。\n"
            "同步 EXPECTED_MAP 并确认 GitHub 侧有等价 job（单一放行标准）。"
        )

    def test_mapping_registry_is_complete(self, ghw_jobs):
        """GitHub 新增 job 必须登记映射（否则上一条测不到它）。"""
        unregistered = sorted(set(ghw_jobs) - set(EXPECTED_MAP))
        assert not unregistered, (
            f"ci.yml 新增 job 未登记 EXPECTED_MAP: {unregistered}——"
            "补登记并补 cnb 流水线，否则对齐守卫对它失效。"
        )


class TestCommandParity:
    @pytest.mark.parametrize("job_name", sorted(EXPECTED_MAP))
    def test_core_commands_on_both_sides(self, cnb_pipelines, ghw_jobs, job_name):
        pipe_names = EXPECTED_MAP[job_name]
        ghw_scripts = _job_scripts(ghw_jobs[job_name])
        cnb_scripts = "\n".join(
            _pipeline_scripts(cnb_pipelines[n]) for n in pipe_names if n in cnb_pipelines
        )
        for cmd in EXPECTED_CORE_COMMANDS[job_name]:
            assert cmd in ghw_scripts, f"ci.yml job '{job_name}' 缺核心命令: {cmd}"
            assert cmd in cnb_scripts, (
                f".cnb.yml 流水线 {pipe_names} 缺核心命令: {cmd}\n"
                f"ci.yml 对应 job 有而 cnb 无——命令被单侧改动，放行标准漂移。"
            )


class TestNonBlockingParity:
    @pytest.mark.parametrize("job_name", sorted(EXPECTED_NON_BLOCKING))
    def test_allow_failure_aligned(self, cnb_pipelines, ghw_jobs, job_name):
        pipe_names = EXPECTED_MAP[job_name]
        ghw_job = ghw_jobs[job_name]
        ghw_ok = bool(ghw_job.get("continue-on-error"))
        for n in pipe_names:
            pipe = cnb_pipelines.get(n)
            assert pipe is not None, f"cnb 流水线 {n} 缺失"
            cnb_ok = bool(pipe.get("allowFailure"))
            assert cnb_ok == ghw_ok, (
                f"非阻塞语义不一致: ci.yml '{job_name}' continue-on-error={ghw_ok}, "
                f"cnb '{n}' allowFailure={cnb_ok}"
            )

    @pytest.mark.parametrize("job_name", sorted(set(EXPECTED_MAP) - EXPECTED_NON_BLOCKING))
    def test_blocking_jobs_stay_blocking(self, cnb_pipelines, ghw_jobs, job_name):
        """阻塞门禁不得被单侧悄悄放宽为非阻塞（最危险的漂移形态）。"""
        for n in EXPECTED_MAP[job_name]:
            pipe = cnb_pipelines.get(n) or {}
            assert not pipe.get("allowFailure"), (
                f"cnb 流水线 '{n}'（对应阻塞门禁 '{job_name}'）被设为 allowFailure——"
                "放行标准被单侧放宽"
            )
            assert not ghw_jobs[job_name].get("continue-on-error"), (
                f"ci.yml job '{job_name}' 被设为 continue-on-error——"
                "GitHub 侧放行标准被放宽"
            )


class TestAntiRegression:
    def test_cnb_not_echo_shell(self, cnb_pipelines):
        """防再生：任何流水线的 script 都不得只是 echo/占位（历史空壳形态）。"""
        shells = [
            name for name, pipe in cnb_pipelines.items()
            if _pipeline_scripts(pipe).strip() == ""
            or all(
                line.strip().startswith("echo")
                for line in _pipeline_scripts(pipe).splitlines()
                if line.strip()
            )
        ]
        assert not shells, f"cnb 流水线退化为样例空壳: {shells}"

    def test_push_and_pr_share_same_pipeline_definition(self, cnb_pipelines):
        """push 与 pull_request 必须共用同一份流水线（锚点别名，单一事实来源）。"""
        data = yaml.safe_load(io.open(CNB, encoding="utf-8").read())
        main = data["main"]
        assert main["push"] == main.get("pull_request"), (
            "main.push 与 main.pull_request 定义不一致——PR 门禁与 push 门禁分叉"
        )

    def test_referenced_files_exist(self):
        """两份配置引用的门禁构件必须真实存在（缺一个 = 该门禁上线即红）。"""
        for f in (
            "requirements-ci.txt", "requirements-ci.lock",
            "scripts/ci_static_gate.py", "scripts/ci/protected_tests.txt",
            "tests/e2e/test_backend_boot.py", "tests/unit/test_audit_regressions.py",
            "NeurUI/package-lock.json",
        ):
            assert (PROJECT_ROOT / f).exists(), f"CI 配置引用的门禁构件缺失: {f}"
