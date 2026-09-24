# -*- coding: utf-8 -*-
"""性能回归门禁的常驻自检（Issue #55 P2）。

门禁脚本 scripts/ci/perf_gate.py 一旦自身失效（被删、被改成空壳、
或 CI 配置里被摘掉），性能回归就又回到"人肉发现"。本套件钉住：

1. 脚本存在、可执行、退出码语义正确（当前仓库应为 0=通过）；
2. 双侧 CI 都真的调用它（cnb + GitHub），语义都是阻断；
3. 门禁覆盖的四项能力仍在（import 预算 / 埋点开销 / 共享池复用 / 假数据门控）；
4. 假数据门控不会被"顺手"放宽（默认禁用的不变式由门禁自己验证）；
5. **判分量与机器负载无关**（下节）：门禁不得用墙钟判分。

第 5 条是 2026-09-24 那次「同一份代码 py3.11 红、py3.12 绿」的根修判据：
`POOL_GET_BUDGET_MS` / `STEP_METRIC_BUDGET_MS` 是**数量级契约**，判分却取自
`time.perf_counter()`。墙钟 = 本线程 CPU + **等 CPU / 等锁的时间**，于是读数随
同机负载漂移；误判方向还是「负载越高越红」，把「让 CI 变绿」的捷径变成放宽阈值
——那正是教义第 2 条禁止的降级断言换绿（判据同 `test_ci_wallclock_assertion_ledger`）。
"""

import ast
import importlib
import io
import subprocess
import sys
import time
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


class TestJudgingIgnoresMachineLoad:
    """门禁的判分量必须与机器负载无关（墙钟会把排队算成退化）。

    红灯形态（修复前实测）：给被测环节注入**等待**，墙钟判分立刻放大——
    `record_pipeline_step` 每次多等 0.3ms × 2000 次 ≈ 600ms > 预算 50ms；
    `get_thread_pool` 每次多等 0.1ms × 1000 次 ≈ 100ms > 预算 20ms。
    同一份代码在负载下就这么被判红，与是否有真实退化无关。
    """

    def test_gate_never_scores_with_a_wall_clock(self):
        """判分不得取自墙钟：`perf_counter` 一族出现在门禁源码里即负载相关。

        实测依据（2026-09-24，构建 cnb-6t7-1k3964vd2-004）：同一提交的
        unit-tests-py311 报 `1000 次池获取耗时 21.9ms > 预算 20ms`，
        unit-tests-py312 同机同 cpus 却 success；其后两次主线构建 11/11 全绿。
        """
        tree = ast.parse(io.open(GATE, encoding="utf-8").read())
        wall = sorted(
            ast.unparse(node)
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and node.attr in {"perf_counter", "monotonic", "time", "time_ns", "process_time"}
        )
        assert wall == [], (
            "性能门禁用墙钟判分——读数随同机负载漂移，同一份代码会在共享 runner 上偶发红："
            f"{wall}\n修复：判分一律走本线程 CPU 时间 `time.thread_time()`。"
        )

    def test_gate_exposes_a_load_independent_scoring_primitive(self):
        gate = importlib.import_module("scripts.ci.perf_gate")
        assert hasattr(gate, "measureThreadCpu"), (
            "门禁没有「按本线程 CPU 计分」的取数口——各检查会退回各写一套墙钟"
        )
        charged = gate.measureThreadCpu(lambda: time.sleep(0.3))
        assert charged < 50.0, (
            f"注入 300ms 纯等待被计了 {charged:.1f}ms——等待不得进入判分"
        )

    def test_injected_waiting_is_not_charged_by_step_metric_check(self, monkeypatch):
        """真正的红：在门禁**真实取数链路**上注入等待，判据必须仍判绿。"""
        gate = importlib.import_module("scripts.ci.perf_gate")
        # 生产装配点取类：不抄私有类名，避免与真实实现漂移
        from neurova.core.metrics import get_metrics

        collector = type(get_metrics())
        original = collector.record_pipeline_step

        def slowed(self, step_name, status, duration_ms):
            time.sleep(0.0003)
            return original(self, step_name, status, duration_ms)

        monkeypatch.setattr(collector, "record_pipeline_step", slowed)
        failures = gate.Failures()
        gate.check_step_metric_overhead(failures)
        assert [f["check"] for f in failures] == [], (
            "同机负载（等待）被算成了埋点退化——判据绑了墙钟："
            f"{list(failures)}"
        )

    def test_real_cpu_regression_in_step_metric_is_still_caught(self, monkeypatch):
        """反向控制：真退化（CPU 变重）必须仍被判红，本判据不得空转。"""
        gate = importlib.import_module("scripts.ci.perf_gate")
        # 生产装配点取类：不抄私有类名，避免与真实实现漂移
        from neurova.core.metrics import get_metrics

        collector = type(get_metrics())
        original = collector.record_pipeline_step

        def heavy(self, step_name, status, duration_ms):
            deadline = time.thread_time() + 0.0001
            while time.thread_time() < deadline:
                pass
            return original(self, step_name, status, duration_ms)

        monkeypatch.setattr(collector, "record_pipeline_step", heavy)
        failures = gate.Failures()
        gate.check_step_metric_overhead(failures)
        assert any(f["check"] == "pipeline-step-metric" for f in failures), (
            "埋点真变重 200ms 却仍判绿——本判据已被改空"
        )

    def test_injected_waiting_is_not_charged_by_pool_check(self, monkeypatch):
        import importlib as _importlib

        gate = importlib.import_module("scripts.ci.perf_gate")
        pool_mod = _importlib.import_module("neurova.core.thread_pool")
        original = pool_mod.get_thread_pool

        def slowed(*args, **kwargs):
            time.sleep(0.0001)
            return original(*args, **kwargs)

        monkeypatch.setattr(pool_mod, "get_thread_pool", slowed)
        failures = gate.Failures()
        gate.check_shared_pool_reuse(failures)
        assert [f["check"] for f in failures] == [], (
            f"同机负载（等待）被算成池获取退化——判据绑了墙钟：{list(failures)}"
        )

    def test_import_probe_ignores_waiting_and_flags_side_effects(self, tmp_path):
        """import 判据同样不得计等待；而「import 期做重活」要以结构形态暴露。"""
        import importlib as _importlib

        gate = _importlib.import_module("scripts.ci.perf_gate")
        (tmp_path / "sleepy_module.py").write_text(
            "import time\ntime.sleep(0.4)\n", encoding="utf-8"
        )
        (tmp_path / "networky_module.py").write_text(
            "import socket\nsocket.getaddrinfo('localhost', 80)\n", encoding="utf-8"
        )
        sleepy = gate.measureImportProbe("sleepy_module", searchPath=str(tmp_path))
        assert sleepy["cpu_ms"] < 100.0, (
            f"import 期 400ms 纯等待被计了 {sleepy['cpu_ms']}ms——等待不得进入判分"
        )
        assert sleepy["sideEffects"] == [], f"干净模块被误判副作用: {sleepy['sideEffects']}"
        networky = gate.measureImportProbe("networky_module", searchPath=str(tmp_path))
        assert networky["sideEffects"], (
            "import 期发起网络调用未被点名——CPU 时钟看不到这类重活，"
            "必须由结构判据兜住，否则本次改动等于降级断言"
        )

    def test_import_reading_a_data_file_is_named(self, tmp_path):
        """import 期读**非代码**数据文件同样要点名（CPU 时钟看不见 IO 等待）。

        这是换时钟必须补上的另一半：否则「把大文件/模型/语料挪到 import 期」
        会从本判据下溜过（CPU 只耗一点点，首轮延迟却全付在这里）。
        """
        import importlib as _importlib

        gate = _importlib.import_module("scripts.ci.perf_gate")
        (tmp_path / "corpus.json").write_text("[]", encoding="utf-8")
        (tmp_path / "reader_module.py").write_text(
            f"open({str(tmp_path / 'corpus.json')!r}).read()\n", encoding="utf-8"
        )
        reader = gate.measureImportProbe("reader_module", searchPath=str(tmp_path))
        assert any("corpus.json" in e for e in reader["sideEffects"]), (
            f"import 期读数据文件未被点名: {reader['sideEffects']}——"
            "该路径会让首轮对话替 import 付 IO 等待"
        )

    def test_real_cpu_regression_in_import_is_still_caught(self, tmp_path):
        """反向控制：import 期真做 CPU 重活必须仍被判红。"""
        import importlib as _importlib

        gate = _importlib.import_module("scripts.ci.perf_gate")
        (tmp_path / "busy_module.py").write_text(
            "import time\n"
            "deadline = time.thread_time() + 0.25\n"
            "while time.thread_time() < deadline:\n"
            "    pass\n",
            encoding="utf-8",
        )
        busy = gate.measureImportProbe("busy_module", searchPath=str(tmp_path))
        assert busy["cpu_ms"] >= 100.0, (
            f"import 期 250ms CPU 重活只读到 {busy['cpu_ms']}ms——判据已被改空"
        )
