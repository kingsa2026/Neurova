# -*- coding: utf-8 -*-
"""性能回归门禁的常驻自检（Issue #55 P2）。

门禁脚本 scripts/ci/perf_gate.py 一旦自身失效（被删、被改成空壳、
或 CI 配置里被摘掉），性能回归就又回到"人肉发现"。本套件钉住：

1. 脚本存在、可执行、退出码语义正确（当前仓库应为 0=通过）；
2. 双侧 CI 都真的调用它（cnb + GitHub），语义都是阻断；
3. 门禁覆盖的四项能力仍在（import 预算 / 埋点开销 / 共享池复用 / 假数据门控）；
4. 假数据门控不会被"顺手"放宽（默认禁用的不变式由门禁自己验证）；
5. **判分量与机器负载无关**：进程内两处微基准不得用墙钟判分（下节）；
6. **池复用判据必须能被证伪**（再下一节）：真退化成"每次新建池"时要报红。

本套件自身不得自带负载：它每个用例的预算（pytest-timeout 30s）由 CI job 的
全部用例共享，自带 32 个 CPU 自旋线程的判据会把测量拖到 ~19s，机器一忙即撞
超时（2026-09-24 构建 cnb-i3l-1k3a5ht8f-004 实测）。负载一律走**注入**：
在被测环节的生产装配点上注入等待，是确定性的、与机器无关的。

第 5 条是 2026-09-24 那次「同一份代码 py3.11 红、py3.12 绿」的根修判据：
`POOL_GET_BUDGET_MS` / `STEP_METRIC_BUDGET_MS` 是**数量级契约**，判分却取自
`time.perf_counter()`。墙钟 = 本线程 CPU + **等 CPU / 等锁的时间**，于是读数随
同机负载漂移；误判方向还是「负载越高越红」，把「让 CI 变绿」的捷径变成放宽阈值
——那正是教义第 2 条禁止的降级断言换绿（判据同 `test_ci_wallclock_assertion_ledger`）。
**例外**：冷 import 检查量与机器无关的"用户实际等了多久"，属可留墙钟的命中点；
该例外由 `TestImportBudgetKeepsWallClock` 单独钉住，不在这条禁令内。
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

#: 有界注入：注入的等待**墙钟总量**不变，而系统调用数降 `INJECT_EVERY` 倍。
#: 逐次小睡会把 N 次 `sleep` 铺进被测链路，而 `time.thread_time()` 读
#: `CLOCK_THREAD_CPUTIME_ID`（**含内核态时间**），调度拥挤时每次 `sleep` 的
#: 内核开销随同机负载一起涨 ⇒ "等待"经系统调用换算成 CPU 读数，
#: 判据自身变成负载相关。实测（2000 次注入）：逐次 9.2~10.3ms，粗粒度 0.2ms。
INJECT_EVERY = 100
#: 逐次注入的等价单次等待（ms）；粗睡时长 = 本值 × `INJECT_EVERY`。
PER_CALL_WAIT_MS = 0.3
PER_CALL_POOL_WAIT_MS = 0.1

#: 本套件要跑门禁本体与三个生产装配点，故依赖 `prometheus_client` / `psutil`
#: （门禁 import 面 → `neurova.core.metrics`；占用者观测面 → `port_guard`）。
#: 这两者由 CI 与运行时的依赖清单声明（`requirements-ci.lock` / `requirements.txt`），
#: 缺席只可能是精简环境手工跑——但**收集期**缺席会让整个文件收集失败，把"一条都不该
#: 少跑"的常驻守卫变成"静默作废"：夹具不咬合时那份绿比红危险（本容器缺
#: `prometheus_client` 实测：`pytest tests/performance/ -q` ⇒ `1 error`）。
#: 故按本文件既有 `yaml = pytest.importorskip(...)` 的同一形态，在**模块级**声明依赖：
#: pytest 对收集期 `Skipped` 只按文件级 skip 处理，不判红。
yaml = pytest.importorskip("yaml")
pytest.importorskip("prometheus_client", reason="门禁 import 面依赖 neurova.core.metrics")
pytest.importorskip("psutil", reason="端口占用者观测面依赖 psutil.net_connections")


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

    例外且必须留墙钟的是冷 import 检查：它量"用户为首轮对话实际等了多久"，
    见本类末节 `TestImportBudgetKeepsWallClock`。
    """

    def test_gate_exposes_a_load_independent_scoring_primitive(self):
        gate = importlib.import_module("scripts.ci.perf_gate")
        assert hasattr(gate, "measureThreadCpu"), (
            "门禁没有「按本线程 CPU 计分」的取数口——各检查会退回各写一套墙钟"
        )
        charged = gate.measureThreadCpu(lambda: time.sleep(0.3))
        assert charged < 50.0, (
            f"注入 300ms 纯等待被计了 {charged:.1f}ms——等待不得进入判分"
        )

    def test_no_injection_hook_sleeps_on_every_call(self):
        """注入钩子一律不得"每次调用都小睡"——系统调用数必须与迭代数解耦。

        根因（2026-09-25 py3.12 CI 实测红，`unit-tests-py312` 收尾残留 1 failed）：
        `time.thread_time()` 读 `CLOCK_THREAD_CPUTIME_ID`，**含内核态时间**。
        逐次注入一次小睡（2000 × 0.2ms）会把 2000 次 `sleep` 系统调用铺进被测链路，
        每次调用的内核开销随同机调度拥挤一起涨 —— "等待"就这么经系统调用换算成
        CPU 读数。失败原文：

            2000 次 record_pipeline_step 耗时 68.8ms > 预算 50ms

        这处此前**只修了一个命中点**，同一根因的其余形态留下来了：`cb92f2d1`
        把 `TestJudgingIgnoresMachineLoad` 两处改成粗粒度后，
        `TestJudgedValueIsLoadIndependent` 那条（经 `_injectLoad` 注入，
        同样是 2000 × 0.2ms 逐次小睡）接着红。

        判据按**结构**扫全文件（教义第 5 条：同一根因全命中点扫荡）：
        `monkeypatch` 用的注入钩子是**嵌套函数**（`slowed` / `injectedStep` /
        `injectedPool`），其中每个 `time.sleep` 都必须落在 `if` 保护内。
        非嵌套的一次性注入（如 `measureThreadCpu(lambda: time.sleep(0.3))`）
        不与迭代数同阶，不在此列。
        """
        source = io.open(__file__, encoding="utf-8").read()
        tree = ast.parse(source)
        parents = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parents[child] = node

        offenders = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            # 注入钩子=嵌套函数：外层还有函数定义（顶层测试方法不算）
            ancestor = parents.get(node)
            is_hook = False
            while ancestor is not None:
                if isinstance(ancestor, ast.FunctionDef):
                    is_hook = True
                    break
                ancestor = parents.get(ancestor)
            if not is_hook:
                continue
            for inner in ast.walk(node):
                if not isinstance(inner, ast.Call):
                    continue
                func = inner.func
                if not (
                    isinstance(func, ast.Attribute)
                    and func.attr == "sleep"
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "time"
                ):
                    continue
                # 守卫必须是"按调用计数取模"的有界注入，而不是常量开关：
                # `if sleep_ms:` 这种开关对被测链路而言恒真，等于无条件逐次小睡
                # ——`_injectLoad` 正是这样漏网的第三个命中点。
                guarded = False
                chain = parents.get(inner)
                while chain is not None and chain is not node:
                    if isinstance(chain, ast.If) and any(
                        isinstance(sub, ast.BinOp) and isinstance(sub.op, ast.Mod)
                        for sub in ast.walk(chain.test)
                    ):
                        guarded = True
                        break
                    chain = parents.get(chain)
                if not guarded:
                    offenders.append((node.name, inner.lineno))

        assert not offenders, (
            "以下注入钩子对每次调用都执行 time.sleep（函数, 行号）："
            f"{offenders}。迭代 N 次即 N 次系统调用，其内核开销经 thread_time "
            "计入判分，判据自身变成负载相关（同机负载越高越红）。"
            "改法：按调用计数每 N 次粗睡一次、时长 ×N，注入墙钟总量不变而系统调用数降 N 倍。"
        )

    def test_injected_waiting_is_not_charged_by_step_metric_check(self, monkeypatch):
        """真正的红：在门禁**真实取数链路**上注入等待，判据必须仍判绿。"""
        gate = importlib.import_module("scripts.ci.perf_gate")
        # 生产装配点取类：不抄私有类名，避免与真实实现漂移
        from neurova.core.metrics import get_metrics

        collector = type(get_metrics())
        original = collector.record_pipeline_step
        calls = {"n": 0}

        def slowed(self, step_name, status, duration_ms):
            # 有界注入：每 N 次粗睡一次、时长 ×N。注入的墙钟总量与逐次小睡等价，
            # 而系统调用数降 N 倍 —— 逐次小睡的内核开销会经 thread_time 计入判分。
            calls["n"] += 1
            if calls["n"] % INJECT_EVERY == 0:
                time.sleep(PER_CALL_WAIT_MS * INJECT_EVERY / 1000.0)
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
        calls = {"n": 0}

        def slowed(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] % INJECT_EVERY == 0:
                time.sleep(PER_CALL_POOL_WAIT_MS * INJECT_EVERY / 1000.0)
            return original(*args, **kwargs)

        monkeypatch.setattr(pool_mod, "get_thread_pool", slowed)
        failures = gate.Failures()
        gate.check_shared_pool_reuse(failures)
        assert [f["check"] for f in failures] == [], (
            f"同机负载（等待）被算成池获取退化——判据绑了墙钟：{list(failures)}"
        )

########################################################################
# 冷 import：门禁里唯一该留墙钟的命中点
########################################################################


########################################################################
# 依赖缺席的形态：跳过，而不是整文件收集失败
########################################################################


#: 子进程里用来"假装重依赖不在"的 sitecustomize：装一个 meta_path 拒绝者。
#: 刻意不用"往 PYTHONPATH 里放同名模块抛 ImportError"——那会绕过 `importorskip`
#: 的捕获范围（它只捕 ImportError 来源的"模块找不到"），实测落在收集期 ERROR。
#: 这里让 `find_spec` 抛 `ModuleNotFoundError`（`ImportError` 的子类），
#: 与"真的没装"同形，正是本判据要覆盖的场景。
_DEP_BLOCKER_SOURCE = """\
import sys
import importlib.abc


class _Rejector(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "prometheus_client":
            raise ModuleNotFoundError("No module named 'prometheus_client'")
        return None


sys.meta_path.insert(0, _Rejector())
"""


class TestHeavyDepsAreDeclaredAtCollectionTime:
    """重依赖缺席时，本套件必须是**文件级 skip**，不得整文件 ERROR。

    为什么这条值得常驻：整个测试根 `tests/` 在 `.gitignore` 里整根豁免，
    单纯把重依赖写进依赖清单**不够**：`tests/performance/` 不在 CI 的受保护子集里
    （没人跑它），故本判据常驻在这里，钉住"缺依赖时的形态"。

    判据形态刻意选**行为**而非源码扫描：真正要钉的是"缺依赖时 pytest 判 skip
    而不是 error"。子进程里放的是**本文件自己**（一次跑完 26 条判据，本容器 16s），
    但不带 `::用例` 选择器——模块级 skip 只在收集期成立，带选择器会让 pytest
    因"选择器指着一条被跳过的用例"退 4，那是选择器语义，不是本判据要钉的形态。

    **不许用"往 PYTHONPATH 里放同名模块抛 ImportError"来伪造缺席**：实测那会绕过
    `importorskip` 的捕获范围（它只把"模块找不到"这类异常转成 skip）、直接落在
    收集期 ERROR——那正是本判据要区分的两种形态被混成一种。故用 meta_path 拒绝者
    抛 `ModuleNotFoundError`（与"真的没装"同形）。
    """

    def test_missingHeavyDepYieldsFileLevelSkipNotError(self, tmp_path):
        import os
        import subprocess

        (tmp_path / "sitecustomize.py").write_text(_DEP_BLOCKER_SOURCE, encoding="utf-8")
        env = dict(os.environ)
        env["PYTHONPATH"] = str(tmp_path)
        proc = subprocess.run(
            # 刻意整文件跑（不带 `::用例` 选择器）：模块级 skip 只在收集期成立，
            # 带选择器时 pytest 会因"选择器指着一条被跳过的用例"退 4（非 0），
            # 那是选择器语义、不是本判据要钉的形态。
            [sys.executable, "-m", "pytest", str(Path(__file__)), "-q", "--no-header", "-p", "no:cacheprovider"],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
            env=env,
            timeout=120,
        )
        output = proc.stdout + proc.stderr
        # 退出码语义：0 = 有用例跑完（正常），5 = 一条都没收集到但**没有错误**
        # （文件级 skip 就是这种形态）。两者都说明"缺依赖没有把文件判成失败"。
        assert proc.returncode in (0, 5), (
            "重依赖缺席时整文件收集失败（本文件 20+ 条判据被一次性作废）：\n"
            + output[-1200:]
        )
        assert " 1 skipped" in output, (
            "缺依赖既没报红也没报「整文件跳过」——形态不明，"
            f"读者无从判断这次跑是不是什么都没验：\n{output[-1200:]}"
        )

    def test_theGuardItselfBitesWhenTheDeclarationsAreRemoved(self, tmp_path):
        """反向控制：把模块级依赖声明摘掉后，同一场景必须真的红（判据不空转）。

        同样整文件跑（不带选择器）：摘掉声明后**收集期**就会失败，
        pytest 不会收集到任何用例，故不会重演"21 条判据各跑一遍"的开销。
        """
        import os
        import subprocess

        scratch = Path(tmp_path) / "stripped_perf_gate_contract.py"
        stripped = io.open(Path(__file__), encoding="utf-8").read()
        #: 逐条摘掉模块级依赖声明（行锚定到本文件自己的声明文本）
        for module in ("prometheus_client", "psutil"):
            stripped = stripped.replace(
                f'pytest.importorskip("{module}", reason=', f'pytest.{module}_declared('
            )
        scratch.write_text(stripped, encoding="utf-8")
        (Path(tmp_path) / "sitecustomize.py").write_text(_DEP_BLOCKER_SOURCE, encoding="utf-8")
        env = dict(os.environ)
        env["PYTHONPATH"] = str(tmp_path)
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", str(scratch), "-q", "--no-header", "-p", "no:cacheprovider"],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
            env=env,
            timeout=120,
        )
        output = proc.stdout + proc.stderr
        assert proc.returncode != 0, (
            "摘掉依赖声明后同一场景仍判绿——本判据对'守卫失效'无反应（恒真断言）：\n"
            + output[-1200:]
        )
        assert "ERROR collecting" in output, (
            f"摘掉声明后的红灯不是收集期失败，判据测的不是同一件事：\n{output[-1200:]}"
        )


class TestImportBudgetKeepsWallClock:
    """冷 import 判分取**子进程墙钟**，并保留 CPU 读数作诊断。

    为什么是例外：它量的是"用户为首轮对话实际等了多久"——等待 CPU 的时间对用户
    同样是延迟，必须计入；而进程内两处微基准正相反（"这段代码要花多少 CPU"）。
    把 import 判分顺手改成 CPU 时间，就不再量首轮延迟了（教义第 5 条：同一根因
    全命中点扫荡，但例外命中点不得顺手改）。

    另一半：CPU 时钟看不到 import 期的**阻塞型**重活（网络/子进程/读数据文件），
    故由 `sys.addaudithook` 按结构形态点名（`sideEffects`），否则本次换时钟
    等于把"import 期偷偷做重活"一并放行（教义第 2 条禁止的降级换绿）。
    """

    def test_import_probe_reports_wallclock_and_ignores_load(self, tmp_path):
        """判分读数是墙钟；而与负载无关的阻塞被点名，纯等待仍照实计入（这就是它要量的）。"""
        import importlib as _importlib

        gate = _importlib.import_module("scripts.ci.perf_gate")
        (tmp_path / "sleepy_module.py").write_text(
            "import time\ntime.sleep(0.4)\n", encoding="utf-8"
        )
        sleepy = gate.measureImportProbe("sleepy_module", searchPath=str(tmp_path))
        assert sleepy["elapsed_ms"] >= 300.0, (
            f"import 期 400ms 等待只被读到 {sleepy['elapsed_ms']}ms——"
            "冷 import 量的是用户实际等待，必须计入"
        )
        assert sleepy["cpu_ms"] < 100.0, (
            f"纯等待被计成 CPU {sleepy['cpu_ms']}ms——CPU 读数只作诊断，不得把等待算进去"
        )
        assert sleepy["sideEffects"] == [], f"干净模块被误判副作用: {sleepy['sideEffects']}"

    def test_import_side_effects_are_named_by_structure(self, tmp_path):
        """import 期的阻塞型重活不耗 CPU，必须由结构判据点名。"""
        import importlib as _importlib

        gate = _importlib.import_module("scripts.ci.perf_gate")
        (tmp_path / "networky_module.py").write_text(
            "import socket\nsocket.getaddrinfo('localhost', 80)\n", encoding="utf-8"
        )
        networky = gate.measureImportProbe("networky_module", searchPath=str(tmp_path))
        assert networky["sideEffects"], (
            "import 期发起网络调用未被点名——CPU 时钟看不到这类重活，"
            "必须由结构判据兜住，否则本次改动等于降级断言"
        )

    def test_import_reading_a_data_file_is_named(self, tmp_path):
        """import 期读**非代码**数据文件同样要点名（CPU 时钟看不见 IO 等待）。

        这是冷 import 判据必须留墙钟/挂审计钩的另一半：否则「把大文件/模型/语料
        挪到 import 期」会从本判据下溜过（CPU 只耗一点点，首轮延迟却全付在这里）。
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
        assert busy["elapsed_ms"] >= 100.0, (
            f"import 期 250ms CPU 重活在墙钟口径下只读到 {busy['elapsed_ms']}ms——判据已被改空"
        )

    def test_import_judging_uses_wallclock_only_for_the_probe(self, monkeypatch):
        """预算判分读的是墙钟读数：把探针读数调大，检查必须报红。"""
        gate = importlib.import_module("scripts.ci.perf_gate")

        def inflated(module, searchPath=None):
            return {"elapsed_ms": gate.IMPORT_BUDGET_MS + 1000.0, "cpu_ms": 1.0, "sideEffects": []}

        monkeypatch.setattr(gate, "measureImportProbe", inflated)
        failures = gate.Failures()
        gate.check_import_budget(failures)
        assert any(f["check"] == "import-budget" for f in failures), (
            "冷 import 超预算却未判红——import 判分被改空"
        )


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

    def test_judged_value_does_not_inflate_under_injected_waiting(self, monkeypatch):
        """被测环节被注入**等待**时，判值不得放大（两个检查都不得把等待算成退化）。

        注入的等待是该环节花掉的真实墙钟时间，判值若把它算进去就与"排队等 CPU"
        同形：同一份代码在共享 runner 上会因同机负载被误判成退化。门禁改量本线程
        CPU 时间后，注入 2000×0.3ms + 1000×0.1ms = 700ms 等待，判值不动。
        """
        gate = importlib.import_module("scripts.ci.perf_gate")
        injected, failures, judged = _measuringWithInjectedWaiting(gate, monkeypatch)
        assert not failures, (
            f"同机负载（等待）被算成退化：{list(failures)}\n注入等待 {injected:.1f}ms，"
            f"判值 {judged}"
        )

    def test_real_cpu_regression_is_still_caught_under_the_same_harness(self, monkeypatch):
        """同一判据必须仍咬得住真退化：CPU 真变重 10 倍即判红（反向控制）。

        与上一条共用同一个"注入"入口，只把等待换成 CPU 自旋：判据若被改成
        "对任何注入一律报绿"，这条立刻红。
        """
        gate = importlib.import_module("scripts.ci.perf_gate")
        _, failures, judged = _measuringWithInjectedWaiting(gate, monkeypatch, cpu_ms=0.1)
        for name in ("pipeline-step-metric", "shared-thread-pool"):
            assert any(f["check"] == name for f in failures), (
                f"{name} 真退化（每次多烧 0.1ms CPU）却判绿——判据已被改空；判值 {judged}"
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

    def test_judged_checks_take_their_reading_from_the_single_scoring_primitive(self):
        """两处判值必须取自门禁**唯一**的取数口，且经 `bestOfRounds` 连量取优。

        取数口收在一处（`measureThreadCpu` / `bestOfRounds`），是"改回墙钟即判红"这条
        判据能成立的前提：各检查各写一套取数，就总有一处能悄悄退回 `perf_counter`。
        取数与取优本身的行为面由 `TestCheckSourceIsSingleAndRepeated` 两条钉住。
        """
        source = io.open(GATE, encoding="utf-8").read()
        for check in ("check_step_metric_overhead", "check_shared_pool_reuse"):
            segment = _functionSource(source, check)
            assert "bestOfRounds(" in segment, (
                f"{check} 的判值不经过 bestOfRounds——单轮读数会把一次性成本与超订算进判值"
            )

    def test_import_budget_keeps_wallclock_and_says_why(self):
        """冷 import 是**子进程**墙钟，量的是"用户实际等了多久"——属可留墙钟的命中点。

        判分口径的单一事实源在门禁侧的 `measureImportProbe`：它出的 `elapsed_ms`
        取自子进程 `time.perf_counter`，`check_import_budget` 也只读这个字段。
        """
        source = io.open(GATE, encoding="utf-8").read()
        segment = _functionSource(source, "measureImportProbe")
        assert "perf_counter" in segment, (
            "冷 import 探针不再取墙钟读数，就不再量'首轮对话延迟'了；"
            "该命中点属可留墙钟，不得顺手改"
        )
        check = _functionSource(source, "check_import_budget")
        assert "elapsed_ms" in check, (
            "import 预算判分不再读墙钟读数（elapsed_ms）——首轮延迟口径被改掉"
        )


def _injectLoad(monkeypatch, sleep_ms: float, cpu_ms: float):
    """在被测环节的**生产装配点**上注入成本：等待与 CPU 二选一。

    注入点在门禁真正取数的那两个函数上（`MetricsCollector.record_pipeline_step`
    与 `neurova.core.thread_pool.get_thread_pool`），不碰门禁的计时口径——
    故判据是否"把等待算成退化"由门禁自己回答。

    注入的两种成本强度都按**量级**取：等待是 1e-4 s 级、CPU 是 1e-4 s 级，
    与门禁的预算（20/50ms）隔着数量级，注入量本身不构成 flaky。
    """
    from neurova.core.metrics import get_metrics

    collector = type(get_metrics())
    original_step = collector.record_pipeline_step

    step_calls = {"n": 0}

    def injectedStep(self, step_name, status, duration_ms):
        if cpu_ms:
            deadline = time.thread_time() + cpu_ms / 1000.0
            while time.thread_time() < deadline:
                pass
        if sleep_ms:
            # 有界注入：每 `INJECT_EVERY` 次粗睡一次、时长 ×`INJECT_EVERY`。
            # 逐次小睡会把 N 次 `sleep` 系统调用铺进被测链路，其内核开销
            # 经 `thread_time`（CLOCK_THREAD_CPUTIME_ID，含内核态）计入判分，
            # 判据自身因此变成负载相关。
            step_calls["n"] += 1
            if step_calls["n"] % INJECT_EVERY == 0:
                time.sleep(sleep_ms * INJECT_EVERY / 1000.0)
        return original_step(self, step_name, status, duration_ms)

    monkeypatch.setattr(collector, "record_pipeline_step", injectedStep)

    pool_module = importlib.import_module("neurova.core.thread_pool")
    original_pool = pool_module.get_thread_pool

    pool_calls = {"n": 0}

    def injectedPool(*args, **kwargs):
        if cpu_ms:
            deadline = time.thread_time() + cpu_ms / 1000.0
            while time.thread_time() < deadline:
                pass
        if sleep_ms:
            pool_calls["n"] += 1
            if pool_calls["n"] % INJECT_EVERY == 0:
                time.sleep(sleep_ms * INJECT_EVERY / 1000.0)
        return original_pool(*args, **kwargs)

    monkeypatch.setattr(pool_module, "get_thread_pool", injectedPool)
    return (sleep_ms / 1000.0) * (2000 + 1000)


def _measuringWithInjectedWaiting(gate, monkeypatch, cpu_ms: float = 0.0):
    """注入等待（默认）或 CPU，回报 (注入总等待 ms, 门禁失败项, 两个判值)。"""
    sleep_ms = 0.0 if cpu_ms else 0.2
    injected = _injectLoad(monkeypatch, sleep_ms, cpu_ms)
    failures = gate.Failures()
    step = gate.check_step_metric_overhead(failures)
    pool = gate.check_shared_pool_reuse(failures)
    judged = {"step_metric_ms": step["elapsed_ms"], "pool_get_ms": pool["elapsed_ms"]}
    return injected, failures, judged


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


class TestCheckSourceIsSingleAndRepeated:
    """判值取数口是**一处**，且**连量取优**——两半都是"判据不随机器漂移"的前提。

    第一半（取数口唯一）在 AST 侧钉住：两处检查的判值构建式必须出现 `bestOfRounds(`。
    各检查各写一套取数，就总有一处能悄悄退回 `perf_counter`，那条"改回墙钟即判红"
    的判据也就不再成立。

    第二半（连量取优）是门禁预算能对**稳态**成立的那一半：`check_step_metric_overhead`
    的单轮读数在空闲机上也会出现首轮档位（首次把 prometheus 的 histogram / label 路径
    编译完，之后各轮才落到稳态——本容器实测首轮 10.5ms / 稳态 5.2ms），且单位 cpu
    时间的读数在超订机上会被抬高（同机 8 个满载进程下最佳轮 7.8ms）。门禁要回答的是
    "稳态下有没有数量级退化"，故取各轮最小值；这不是放宽阈值——真退化在每一轮都成立，
    取优抹不平它。两半都由行为侧用例钉住（取最小值 + 首轮一次性成本被抹掉）。
    """

    def test_best_of_rounds_takes_the_minimum_and_repeats(self):
        gate = importlib.import_module("scripts.ci.perf_gate")
        rounds = []

        def job():
            start = time.thread_time()
            deadline = start + 0.01
            while time.thread_time() < deadline:
                pass
            rounds.append((time.thread_time() - start) * 1000.0)

        best = gate.bestOfRounds(job)
        assert len(rounds) == gate.SCORING_ROUNDS, (
            f"取数口只量了 {len(rounds)} 轮，判据的取优面消失"
        )
        assert best <= min(rounds) + 0.5, (
            f"bestOfRounds 取的不是最小值（{best:.3f}ms vs 各轮最小值 {min(rounds):.3f}ms）"
            "——判值会随机器抖动"
        )

    def test_single_round_reading_is_not_a_usable_judge_on_a_loaded_machine(self):
        """反向控制：**同一段工作**的单轮读数确实会随机器状态漂开——取优不是装饰。

        判据每轮跑同一段工作，其中**第一轮**含一次性成本（与稳态差一个数量级，
        复刻首次把 prometheus 的 histogram / label 路径编译完那个档位）。取各轮
        最小值时读数落在稳态档；只判单轮（尤其判第一轮或取最大值）就会把一次性
        成本算进判值，判值于是看机器状态——这条用例把那个改动钉红。
        """
        gate = importlib.import_module("scripts.ci.perf_gate")
        state = {"round": 0}

        def firstCallThenSteady():
            state["round"] += 1
            if state["round"] == 1:
                # 首轮的一次性成本：与稳态差一个数量级（复刻 prometheus 首次编译）
                deadline = time.thread_time() + 0.02
                while time.thread_time() < deadline:
                    pass

        best = gate.bestOfRounds(firstCallThenSteady)
        assert best < 10.0, (
            f"取优把首轮一次性成本算了进去（{best:.3f}ms）——判值对机器状态敏感"
        )
