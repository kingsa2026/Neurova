# -*- coding: utf-8 -*-
"""性能回归门禁的常驻自检（Issue #55 P2）。

门禁脚本 scripts/ci/perf_gate.py 一旦自身失效（被删、被改成空壳、
或 CI 配置里被摘掉），性能回归就又回到"人肉发现"。本套件钉住：

1. 脚本存在、可执行、退出码语义正确（当前仓库应为 0=通过）；
2. 双侧 CI 都真的调用它（cnb + GitHub），语义都是阻断；
3. 门禁覆盖的四项能力仍在（import 预算 / 埋点开销 / 共享池复用 / 假数据门控）；
4. 假数据门控不会被"顺手"放宽（默认禁用的不变式由门禁自己验证）。
"""

import ast
import io
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
GATE = PROJECT_ROOT / "scripts" / "ci" / "perf_gate.py"

yaml = pytest.importorskip("yaml")


def _cnb_pipelines():
    data = yaml.safe_load(io.open(PROJECT_ROOT / ".cnb.yml", encoding="utf-8").read())
    return {p["name"]: p for p in data["main"]["push"]}


def _ghw_jobs():
    data = yaml.safe_load(
        io.open(PROJECT_ROOT / ".github" / "workflows" / "ci.yml", encoding="utf-8").read()
    )
    return data["jobs"]


class TestGateScriptExists:
    def test_script_present(self):
        assert GATE.exists(), "性能门禁脚本丢失——性能回归将无人拦"

    def test_script_runs_and_passes(self):
        proc = subprocess.run(
            [sys.executable, str(GATE), "--json"],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
            timeout=300,
        )
        assert proc.returncode == 0, (
            f"性能门禁当前不通过（CI 会红）：\n{proc.stdout[-2000:]}\n{proc.stderr[-1000:]}"
        )

    def test_budgets_defined(self):
        tree = ast.parse(io.open(GATE, encoding="utf-8").read())
        names = {t.id for n in ast.walk(tree) if isinstance(n, ast.Assign)
                 for t in n.targets if isinstance(t, ast.Name)}
        for budget in (
            "IMPORT_BUDGET_MS",
            "IMPORT_ALL_BUDGET_MS",
            "STEP_METRIC_BUDGET_MS",
            "POOL_GET_BUDGET_MS",
        ):
            assert budget in names, f"门禁缺预算常量 {budget}"

    def test_all_five_checks_registered(self):
        src = io.open(GATE, encoding="utf-8").read()
        for check in (
            "check_import_budget",
            "check_step_metric_overhead",
            "check_shared_pool_reuse",
            "check_no_mock_metrics_by_default",
            "check_hot_path_file_size",
        ):
            assert check in src, f"门禁缺检查 {check}"


class TestBothSidesWireTheGate:
    def test_cnb_runs_gate_blocking(self):
        pipe = _cnb_pipelines().get("perf-gate")
        assert pipe is not None, ".cnb.yml 缺 perf-gate 流水线"
        assert not pipe.get("allowFailure"), (
            "perf-gate 若设为 allowFailure，性能回归仅是通知——等于无门禁"
        )
        scripts = "\n".join(str(s.get("script", "")) for s in pipe.get("stages", []))
        assert "scripts/ci/perf_gate.py" in scripts

    def test_github_runs_gate_blocking(self):
        job = _ghw_jobs().get("perf-gate")
        assert job is not None, "ci.yml 缺 perf-gate job"
        assert not job.get("continue-on-error"), "perf-gate 不得为非阻塞"
        runs = "\n".join(str(s.get("run", "")) for s in job.get("steps", []))
        assert "scripts/ci/perf_gate.py" in runs
