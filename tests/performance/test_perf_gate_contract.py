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
import threading
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


class TestJudgedValueIsLoadIndependent:
    """判值只在"干活的时间"上成立，不在"排队等 CPU 的时间"上成立。

    根因（构建 cnb-6t7-1k3964vd2 实测，2026-09-24）：门禁把三处**数量级契约**
    （池必须复用而非每次新建、埋点必须是轻活）编码成了**墙钟上界**，判分量取自
    ``time.perf_counter()``。墙钟 = 本线程 CPU 时间 + **等 CPU 的时间**，于是判据
    随同机负载漂移：同一提交 ``-004``（unit-tests-py311）红、``-005``（py312）绿，
    失败原文 ``1000 次池获取耗时 21.9ms > 预算 20ms``；该 sha 之后两次主线构建
    11/11 全绿，其间无任何 perf / thread_pool 改动。

    这与 ``tests/unit/test_ci_wallclock_assertion_ledger.py`` 已定稿的纪律同形：
    结构契约不得编码成墙钟上界——判据与机器强相关则同一份代码两片一红一绿，
    且误判方向是"负载越高越红"，于是捷径变成放宽阈值，反而把真回归一并放行。
    """

    #: 争抢线程数：4×CPU 的超订量足以让墙钟口径必然出现被拉长的读数。
    CONTEND_WORKERS = 32

    def test_judged_value_does_not_inflate_under_cpu_contention(self):
        """受控 CPU 争抢下判值不得放大——墙钟口径实测放大 10–100 倍。"""
        idle = _peakJudgedValue(self.CONTEND_WORKERS, loaded=False)
        loaded = _peakJudgedValue(self.CONTEND_WORKERS, loaded=True)
        for name, (base, hot) in (("埋点开销", (idle[0], loaded[0])), ("池获取", (idle[1], loaded[1]))):
            assert hot <= base * 3 + 2.0, (
                f"{name}判值被同机 CPU 争抢放大：空载 {base:.3f}ms → 争抢 {hot:.3f}ms。"
                "判分口径把'等待 CPU'算进去了；应量本线程 CPU 时间（time.thread_time）"
            )

    def test_judged_checks_take_their_clock_from_thread_cpu_time(self):
        """判分用时源必须是本线程 CPU 时间——改回墙钟即判红（唯一事实源在门禁里）。"""
        source = io.open(GATE, encoding="utf-8").read()
        for check in ("check_step_metric_overhead", "check_shared_pool_reuse"):
            segment = _functionSource(source, check)
            assert "thread_time" in segment, (
                f"{check} 的判分用时源不是本线程 CPU 时间——墙钟会把同机负载算进判值"
            )
            assert "perf_counter" not in segment, (
                f"{check} 仍用墙钟（perf_counter）判分——本仓墙钟台账纪律禁止（负载越高越红）"
            )

    def test_import_budget_keeps_wallclock_and_says_why(self):
        """冷 import 是**子进程**墙钟，量的是"用户实际等了多久"——属可留墙钟的命中点。"""
        source = io.open(GATE, encoding="utf-8").read()
        segment = _functionSource(source, "_measure_import")
        assert "perf_counter" in segment, (
            "冷 import 若改量本进程 CPU 时间，就不再量'首轮对话延迟'了；"
            "该命中点属可留墙钟，不得顺手改"
        )


def _functionSource(source: str, name: str) -> str:
    """取某个顶层函数定义的源码段（到下一个顶层 def/class/常量区为止）。"""
    marker = f"def {name}("
    start = source.index(marker)
    tail = source[start:]
    for stop in ("\n\ndef ", "\n\nCHECKS", "\n\nclass "):
        index = tail.find(stop, 1)
        if index != -1:
            tail = tail[:index]
    return tail


def _peakJudgedValue(workers: int, loaded: bool):
    """(埋点判值, 池判值) 在该负载窗口内的**峰值**读数。

    取峰值而非均值：判据若含"等待"，负载下必然出现被拉长的读数，峰值就是它的上界读数；
    而改用本线程 CPU 时间后，峰值同样不受争抢影响（实测 1.3 倍以内）。
    线程为守护线程且退出即回收，不留常驻进程。
    """
    stop = threading.Event()
    threads = []
    if loaded:
        def spin():
            counter = 0
            while not stop.is_set():
                counter += 1

        threads = [
            threading.Thread(target=spin, daemon=True, name=f"contend-{i}") for i in range(workers)
        ]
        for thread in threads:
            thread.start()
        time.sleep(0.6)
    try:
        gate = _loadGate()
        step = max(_judgeValue(gate, gate.check_step_metric_overhead) for _ in range(3))
        pool = max(_judgeValue(gate, gate.check_shared_pool_reuse) for _ in range(3))
    finally:
        stop.set()
        for thread in threads:
            thread.join(timeout=5)
    return step, pool


def _judgeValue(gate, check) -> float:
    failures = gate.Failures()
    return float(check(failures)["elapsed_ms"])


def _loadGate():
    import importlib.util

    spec = importlib.util.spec_from_file_location("perf_gate_under_contract_test", GATE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestReuseJudgeIsFalsifiable:
    """池复用判据必须**能被证伪**：真退化成"每次新建池"时它会红。

    根因（与上一类同族，同一检查内的第二处断链，2026-09-24 实测发现）：
    原写法 ``{id(get_thread_pool(...)) for _ in range(1000)}`` 在集合推导里
    **即时丢弃引用**，于是每个新建出来的池立刻可回收，CPython 复用同一块内存
    ⇒ ``id()`` 全部相同 ⇒ ``len(pools) == 1``。实测把生产实现改成"每次新建池"
    后判据仍报绿（distinct=1），即这条"不得退化为每次新建池"的判据**从未能**
    咬合过——它只报绿，不报红。保留引用再比 id 才量得准（同一变异实测
    distinct=1000）。

    这是教义第 2 条点名禁止的"恒真断言"形态：判据看起来在守一条契约，
    实际上对违反者一律放行。
    """

    def test_judge_reds_when_pool_is_recreated_every_call(self, monkeypatch):
        """把生产实现换成"每次新建池"，判据必须报红（反向自证）。"""
        from concurrent.futures import ThreadPoolExecutor

        import neurova.core.thread_pool as thread_pool_module

        def recreatedPerCall(*_args, **_kwargs):
            return ThreadPoolExecutor(max_workers=2, thread_name_prefix="mutant")

        monkeypatch.setattr(thread_pool_module, "get_thread_pool", recreatedPerCall)
        gate = _loadGate()
        failures = gate.Failures()
        result = gate.check_shared_pool_reuse(failures)
        assert failures, (
            "池被改成每次新建后判据仍报绿：distinct_pools="
            f"{result['distinct_pools']} —— 该判据无法咬合（id() 在对象回收后被复用）"
        )

    def test_judge_uses_live_references_not_recycled_ids(self):
        """判据必须持有实例引用——只比 id 会被内存复用骗过。"""
        source = io.open(GATE, encoding="utf-8").read()
        segment = _functionSource(source, "check_shared_pool_reuse")
        assert "id(" in segment, "池判据不再比实例身份，判据结构变了"
        assert "id(get_thread_pool(" not in segment, (
            "判据把 id() 直接打在临时值上（即时丢弃引用），回收后的内存会被复用，"
            "于是一律 distinct=1；必须先收集实例再比对身份"
            "（实测变异体在原写法下 distinct=1，保留引用后为 1000）"
        )
