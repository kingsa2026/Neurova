#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""性能回归门禁（Issue #55）。

为什么要这个门禁：本仓此前没有任何"性能"维度的 CI 检查——
.cnb.yml 无 perf 任务，tests/performance/ 只有一个压测，
于是"关键路径变慢 3 倍"这种回归只能等人肉发现（而尾延迟正是用户体验）。

## 判分时钟：本线程 CPU 时间，不用墙钟

判据是**数量级契约**，判分量就必须与机器负载无关。`time.perf_counter()`
量的是「本线程 CPU 时间 + **等 CPU / 等锁的时间**」，于是读数随同机负载漂移，
误判方向还是「负载越高越红」——"让 CI 变绿"的捷径因此变成放宽阈值，
而那恰好把真正的尾延迟回归一并放行（`AGENTS.md` 教义第 2 条禁止的降级断言换绿；
同一纪律已由 tests/unit/test_ci_wallclock_assertion_ledger.py 常驻锁定）。

实测（2026-09-24，构建 cnb-6t7-1k3964vd2）：同一提交的 unit-tests-py311
报 `1000 次池获取耗时 21.9ms > 预算 20ms`，而同机同 cpus 的 unit-tests-py312
success；该 sha 之后两次主线构建 11/11 全绿，其间无 perf 相关改动。
受控复现（本容器 8 cpus，给被测环节注入纯等待）：
  `get_thread_pool` 1000 次注入 0.1ms 等待 → 墙钟读 154.1ms > 预算 20ms（判红）
                                         → 本线程 CPU 读 0.22ms（判绿）
  `record_pipeline_step` 2000 次注入 0.3ms 等待 → 墙钟读 715.1ms > 预算 50ms
                                               → 本线程 CPU 读 5.4ms
故判分一律走 `time.thread_time()`（等待不计入）。**预算一个都没有放宽**。

换时钟不能变成"看不见重活"：CPU 时钟看不到 import 期的**阻塞型**副作用
（网络、子进程、动态库、读仓内数据文件），故 import 检查同时挂 `sys.addaudithook`
把这些事件按**结构形态**点名（`measureImportProbe` 的 `sideEffects`），
而不是靠一个会被负载左右秒数。

门禁内容（都刻意与机器无关/宽松，只抓数量级回归）：

1. **import 冷启动预算**：``import neurova.post_chat_pipeline`` 的**本线程
   CPU 时长**必须低于 IMPORT_BUDGET_MS，且 import 期不得出现阻塞型副作用。
   历史上该模块是每轮对话必经的 import 面，import 期偷偷做重活
   （网络/模型加载/大文件读）会直接进首轮延迟。
2. **关键路径微基准**：管线与共享线程池的最热操作必须有数量级裕量。
   - PostChatPipeline 步骤埋点开销（每步一次 counter+histogram）
   - 共享线程池 get_thread_pool() 复用（不得退化为每次新建）
   - MetricsCollector 假数据默认禁用（接线假数 = 仪表盘失真）

阈值策略：给足裕量（CI 机器比开发机慢、负载抖动），且同一判据连量
`SCORING_ROUNDS` 轮取最优。门禁只回答"是否发生数量级退化"，不追求精确
benchmark——追精确会让门禁变成 flaky 噪音源，最终被人绕过。
取优抵的是调度抖动，不是放宽：真退化在每一轮都成立，取优抹不平它。

**判分用时源（Issue #176 未闭环项，构建 cnb-6t7-1k3964vd2 实测）**：
进程内的两处微基准量的是"这段代码要花多少 CPU"，故取**本线程 CPU 时间**
（``time.thread_time``），不取墙钟。墙钟 = 本线程 CPU 时间 + **等 CPU 的时间**，
于是判值随同机负载漂移：同一提交 ``-004``（unit-tests-py311）报
``1000 次池获取耗时 21.9ms > 预算 20ms`` 而 ``-005``（py312）绿，
其后两次主线构建 11/11 全绿且其间无任何 perf / thread_pool 改动。
更坏的是误判方向——负载越高越红，于是"让 CI 变绿"的捷径变成放宽阈值，
而那恰恰把真正的尾延迟回归一并放行（``AGENTS.md`` 修复教义第 2 条）。
受控取证（8 cpus / 64 自旋线程）：同一份工作墙钟读数 7.5ms → 528–1561ms，
本线程 CPU 时间稳定在 7.4–8.5ms。

冷 import 检查是**例外**且必须留墙钟：它在子进程里量"用户实际等了多久"
（首轮对话延迟），不是"这段代码要花多少 CPU"。该例外由
``tests/performance/test_perf_gate_contract.py`` 的两条用例分别钉住。

用法：
    python scripts/ci/perf_gate.py            # 全部检查
    python scripts/ci/perf_gate.py --json     # 机器可读
"""

from __future__ import annotations

import argparse
import importlib
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Union

PROJECT_ROOT = Path(__file__).resolve().parents[2]
# 门禁脚本由 CI 以 `python scripts/ci/perf_gate.py` 直接跑（不一定 pip install -e .），
# 显式把仓库根放进 sys.path，否则 import neurova 会 ModuleNotFoundError。
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ── 预算（含充裕裕量，只抓数量级回归）─────────────────────────────────
IMPORT_BUDGET_MS = 3000.0        # 单模块冷 import
IMPORT_ALL_BUDGET_MS = 8000.0    # 关键 import 面合计
STEP_METRIC_BUDGET_MS = 50.0     # 1000 次步骤埋点
POOL_GET_BUDGET_MS = 20.0        # 1000 次共享池获取


#: 同一判据连量几轮，取**最小值**（最优读数）后判分。
#: 取优抵的是调度抖动与偶发 GC，**不是放宽阈值**——阈值一个都没动，
#: 而真退化在每一轮都成立，取优抹不平它。受控复现：本容器 8 cpus、
#: 注入 64 个自旋进程时，`record_pipeline_step` 的墙钟读数在
#: 528ms / 1307ms / 1561ms 之间跳（同一份工作），而本线程 CPU 稳定在 8ms 级。
SCORING_ROUNDS = 5

#: import 期**阻塞型**副作用的事件名（本线程 CPU 时钟看不到它们，
#: 故必须由结构判据点名，不能靠秒数）。刻意不含 `ctypes.dlopen`：
#: 它是 CPython 装载扩展模块的正常行为，纳进来会把假阳性变成常态化噪音。
BLOCKING_IMPORT_EVENTS = (
    "socket.connect",
    "socket.getaddrinfo",
    "socket.gethostbyname",
    "subprocess.Popen",
    "os.system",
    "os.exec",
    "os.spawn",
)

#: 不算重活的扩展名（import 期读 `.py`/`.pyc` 是解释器本职，`.so` 是扩展模块装载）。
_CODE_EXTENSIONS = (
    ".py", ".pyc", ".pyi", ".pth", ".egg-link", ".dist-info", ".egg-info",
    ".so", ".pyd", ".dylib", ".dll",
)

#: 子进程里的 import 探针：隔离 sys.modules 缓存，按**本线程 CPU 时间**计时，
#: 并用 `sys.addaudithook` 记录 import 期的阻塞型副作用与仓内数据文件读取。
#: 载荷经 argv 以 JSON 传入（免去转义与拼接）。
_IMPORT_PROBE_SOURCE = r"""
import json, sys, sysconfig, time

_payload = json.loads(sys.argv[1])
_target = _payload["module"]
_code_ext = tuple(_payload["codeExt"])

# 解释器自身的地盘（标准库 / site-packages / 前缀 / 虚拟设备）不算重活：
# import 期在那里读 `.py` 之外的东西（如 dist-info）是解释器本职。
_own_trees = set()
for _key in ("stdlib", "platstdlib", "purelib", "platlib"):
    _path = sysconfig.get_paths().get(_key)
    if _path:
        _own_trees.add(_path)
_own_trees.update({sys.prefix, sys.base_prefix, getattr(sys, "exec_prefix", sys.prefix)})
_own_trees.update({"/proc", "/sys", "/dev"})

def _isOwnTree(path):
    return any(path == tree or path.startswith(tree.rstrip("/") + "/") for tree in _own_trees)

_events = []

def _looksLikeCode(path):
    # .py 一族；并覆盖 CPython 写字节码缓存与它落盘的临时名：
    #   .../__pycache__/foo.cpython-311.pyc
    #   .../__pycache__/foo.cpython-311.pyc.140283084811248
    # 这两类都是解释器本职（写 .pyc 是 import 的正常副产物），算成重活即假阳性。
    lowered = path.lower()
    if lowered.endswith(_code_ext):
        return True
    if "__pycache__" in lowered:
        return True
    head, _, tail = lowered.rpartition(".pyc.")
    return bool(head) and tail.isdigit()

def _hook(event, args):
    if event in _payload["blocking"]:
        _events.append(event)
        return
    if event != "open":
        return
    raw = args[0]
    # `open` 的路径既可能是 str/bytes，也可能是个**文件描述符整数**（fdopen 一族）；
    # 后者不是"读了哪个文件"的事实，`str()` 出来只会是 `open:3` 这种噪音。
    if isinstance(raw, bytes):
        path = raw.decode("utf-8", "replace")
    elif isinstance(raw, str):
        path = raw
    else:
        return
    if _looksLikeCode(path) or _isOwnTree(path):
        return
    _events.append("open:" + path)

sys.addaudithook(_hook)
sys.path[:0] = [p for p in _payload["searchPath"] if p]

# 两个读数各回答一件事：墙钟 elapsed_ms = "用户为首轮对话实际等了多久"
# （判分用它）；cpu_ms = 这段 import 花了多少 CPU（诊断用，不参与判分，
# 因为阻塞型重活不耗 CPU）。sideEffects 补上 CPU 时钟看不见的那一半。
_wall_start = time.perf_counter()
_cpu_start = time.thread_time()
__import__(_target)
_cpu_ms = (time.thread_time() - _cpu_start) * 1000.0
_elapsed_ms = (time.perf_counter() - _wall_start) * 1000.0
print("##import-probe##" + json.dumps({
    "elapsed_ms": round(_elapsed_ms, 3),
    "cpu_ms": round(_cpu_ms, 3),
    "sideEffects": sorted(set(_events)),
}))
"""

_PROBE_MARKER = "##import-probe##"


class Failures(list):
    def add(self, name: str, detail: str) -> None:
        self.append({"check": name, "detail": detail})


def measureThreadCpu(job: Callable[[], None]) -> float:
    """按**本线程 CPU 时间**给一段工作计分（毫秒）。

    为什么不是 `time.perf_counter()`：墙钟 = 本线程 CPU 时间 **+ 等 CPU /
    等锁的时间**。等待不是被测对象的成本，把它算进判分只会让读数随同机负载
    漂移，且误判方向是「负载越高越红」。实测：同一份 1000 次池获取，注入
    0.1ms/次纯等待后墙钟读 154.1ms（越过 20ms 预算判红），本线程 CPU 读 0.22ms。
    """
    start = time.thread_time()
    job()
    return (time.thread_time() - start) * 1000.0


def bestOfRounds(job: Callable[[], None], rounds: int = SCORING_ROUNDS) -> float:
    """同一判据连量 `rounds` 轮取最小读数（抵抖动，不动阈值）。

    取**最小值**（最优读数）：真退化在每一轮都成立，取优抹不平它；
    被抹掉的是调度抖动与偶发 GC。这与墙钟/CPU 时钟之争是两件事——
    时钟口径决定"等 CPU 算不算成本"，取优只决定"抖动用哪一轮读数"。
    """
    return min(measureThreadCpu(job) for _ in range(rounds))


def measureImportProbe(
    module: str, searchPath: Optional[Union[str, List[str]]] = None
) -> Dict[str, object]:
    """在子进程里冷 import `module`，回报 `elapsed_ms`（墙钟）与 import 期副作用。

    子进程隔离 `sys.modules` 缓存（同进程二次 import 只会读到缓存，量不到冷启动）。
    本函数是门禁里**唯一**该用墙钟（``time.perf_counter``）的地方：它量的是
    "用户实际等了多久"（首轮对话延迟），等待对用户同样是延迟，必须计入。
    `sideEffects` 则回答另一半：import 期是否做了**阻塞型**重活（网络/子进程/
    读仓内数据文件）——这类活首轮延迟要全付，但阻塞不耗 CPU，
    本线程 CPU 时钟看不见它，必须以结构形态点名。

    `searchPath` 收单个路径或路径列表（单个字符串被 `for` 迭代会逐字符裂开，
    静默变成"模块找不到"——那是调用方无从察觉的陷阱）。
    """
    if searchPath is None:
        extraPath: List[str] = []
    elif isinstance(searchPath, str):
        extraPath = [searchPath]
    else:
        extraPath = [str(p) for p in searchPath]
    payload = json.dumps(
        {
            "module": module,
            "blocking": list(BLOCKING_IMPORT_EVENTS),
            "codeExt": list(_CODE_EXTENSIONS),
            "searchPath": [str(PROJECT_ROOT)] + extraPath,
        }
    )
    proc = subprocess.run(
        [sys.executable, "-c", _IMPORT_PROBE_SOURCE, payload],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
        timeout=180,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"import {module} 失败: {proc.stderr.strip()[-500:]}")
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith(_PROBE_MARKER)]
    if not lines:
        raise RuntimeError(f"import {module} 探针无读数（stdout 末行: {proc.stdout.strip()[-200:]}）")
    return json.loads(lines[-1][len(_PROBE_MARKER):])


def check_import_budget(failures: Failures) -> dict:
    """检查 1：import 冷启动（**墙钟**判分 + 阻塞型副作用结构点名）。

    本检查是门禁里**唯一**该用墙钟的命中点：它量的是"用户为首轮对话实际等了
    多久"，等待对用户同样是延迟，必须计入。与进程内两处微基准相反，
    那两处量的是"这段代码要花多少 CPU"，故取本线程 CPU 时间。
    """
    results = {}
    total = 0.0
    for module in ("neurova.core.metrics", "neurova.post_chat_pipeline"):
        probe = measureImportProbe(module)
        ms = float(probe["elapsed_ms"])  # 探针墙钟读数（perf_counter），首轮延迟口径
        results[module] = ms
        results[f"{module}::cpu_ms"] = probe["cpu_ms"]
        results[f"{module}::sideEffects"] = probe["sideEffects"]
        total += ms
        if ms > IMPORT_BUDGET_MS:
            failures.add(
                "import-budget",
                f"import {module} 冷启动 {ms:.1f}ms > 预算 {IMPORT_BUDGET_MS:.0f}ms"
                "（import 期重型副作用会进首轮对话延迟）",
            )
        # 阻塞型重活不耗 CPU，CPU 时钟量不到它 —— 以结构形态点名，
        # 否则本次换时钟会把「import 期偷偷起网络/子进程」一并放行。
        if probe["sideEffects"]:
            failures.add(
                "import-budget",
                f"import {module} 在 import 期做了阻塞型/IO 重活: {probe['sideEffects']}"
                "（首轮对话要为它付等待；应惰性化到真正使用时）",
            )
    results["_total_ms"] = total
    if total > IMPORT_ALL_BUDGET_MS:
        failures.add(
            "import-budget",
            f"关键 import 面合计 {total:.1f}ms > 预算 {IMPORT_ALL_BUDGET_MS:.0f}ms",
        )
    return results


def _trackPipelineSteps(metrics, stepNames, iterations: int) -> None:
    for i in range(iterations):
        metrics.record_pipeline_step(stepNames[i % len(stepNames)], "executed", 1.0)


def _getPoolRepeatedly(iterations: int) -> None:
    from neurova.core.thread_pool import get_thread_pool

    for _ in range(iterations):
        get_thread_pool(name="perf-probe", max_workers=2)


def check_step_metric_overhead(failures: Failures) -> dict:
    """检查 2：每条步骤埋点开销（每轮管线 15+ 次，不能是重活）。

    用真实管线的步骤名集合（标签基数有界），避免门禁自身造出上千
    timeseries 而把测出来的数字算成"埋点开销"。
    """
    from neurova.core.metrics import get_metrics

    metrics = get_metrics()
    step_names = (
        "save_session", "save_memory", "generate_tts", "cognitive_analysis",
        "proactive_question", "update_memory_temperature", "reflection",
        "record_experience", "skill_funnel_flush", "evocate_generation",
        "conflict_detection", "version_snapshot", "extract_conversation_rules",
        "motivation_observations", "rsi_iteration",
    )
    iterations = 2000
    # 取本线程 CPU 时间（time.thread_time）：等待不计入判分；并连量数轮取最优。
    elapsed_ms = bestOfRounds(lambda: _trackPipelineSteps(metrics, step_names, iterations))
    per_step_us = elapsed_ms * 1000.0 / iterations
    if elapsed_ms > STEP_METRIC_BUDGET_MS:
        failures.add(
            "pipeline-step-metric",
            f"{iterations} 次 record_pipeline_step 耗时 {elapsed_ms:.1f}ms > "
            f"预算 {STEP_METRIC_BUDGET_MS:.0f}ms（每步 {per_step_us:.1f}us，"
            "埋点不能成为新的尾延迟）",
        )
    return {
        "iterations": iterations,
        "elapsed_ms": round(elapsed_ms, 3),
        "per_step_us": round(per_step_us, 2),
    }


def check_shared_pool_reuse(failures: Failures) -> dict:
    """检查 3：共享线程池确为复用（不得退化为每次新建池）。

    身份判据必须**持有实例引用**：原写法在集合推导里即时丢弃引用，新建出来的池
    立刻可回收，CPython 复用同一块内存 ⇒ ``id()`` 全部相同 ⇒ ``len(pools) == 1``。
    实测把实现换成"每次新建池"后该判据仍报绿，即这条判据从未能咬合过
    （保留引用再比 id 则同一变异给出 1000 个不同实例）。
    这是教义第 2 条点名禁止的"恒真断言"：看着守一条契约，对违反者一律放行。
    """
    from neurova.core.thread_pool import get_thread_pool

    iterations = 1000
    # 同检查 2：取本线程 CPU 时间（time.thread_time，池获取是纯 CPU 路径，等待不
    # 该算进判值），连量数轮取最优。
    elapsed_ms = bestOfRounds(lambda: _getPoolRepeatedly(iterations))
    # 身份判据则**先收集实例再比对**：集合推导里即时丢弃引用会让回收内存被复用，
    # 于是一律 distinct=1；保留引用后同一变异给出 1000 个不同实例。
    acquired = [get_thread_pool(name="perf-probe", max_workers=2) for _ in range(iterations)]
    pools = {id(pool) for pool in acquired}
    if len(pools) != 1:
        failures.add(
            "shared-thread-pool",
            f"{iterations} 次 get_thread_pool 拿到 {len(pools)} 个不同池实例"
            "（每次新建池 = 每轮对话创建/销毁线程）",
        )
    if elapsed_ms > POOL_GET_BUDGET_MS:
        failures.add(
            "shared-thread-pool",
            f"{iterations} 次池获取耗时 {elapsed_ms:.1f}ms > 预算 {POOL_GET_BUDGET_MS:.0f}ms",
        )
    return {"iterations": iterations, "distinct_pools": len(pools), "elapsed_ms": elapsed_ms}


def check_no_mock_metrics_by_default(failures: Failures) -> dict:
    """检查 4：假指标默认禁用（接线假数 = 仪表盘失真，比空更坏）。"""
    import os

    from neurova.analytics.collector import ALLOW_MOCK_METRICS_ENV

    os.environ.pop(ALLOW_MOCK_METRICS_ENV, None)
    module = importlib.import_module("neurova.analytics.collector")
    if module.mock_metrics_enabled():
        failures.add(
            "mock-metrics-gate",
            "假指标在未设开关时被视为开启——仪表盘会显示编造的数字",
        )
    try:
        module.MetricsCollector()._generate_mock_agent_metrics("a", "A")
    except module.MockMetricsDisabledError:
        return {"gated": True}
    failures.add(
        "mock-metrics-gate",
        "_generate_mock_agent_metrics 在默认配置下仍产出假数（应抛 "
        "MockMetricsDisabledError）",
    )
    return {"gated": False}


def check_hot_path_file_size(failures: Failures) -> dict:
    """检查 5：轮次热路径文件不得无节制膨胀（读得动、改得动）。"""
    limits = {
        "neurova/post_chat_pipeline.py": 260_000,
        "neurova/agent/chat_pipeline.py": 160_000,
        "neurova/tool_executor.py": 400_000,
    }
    sizes = {}
    for rel, limit in limits.items():
        path = PROJECT_ROOT / rel
        if not path.exists():
            continue
        nbytes = path.stat().st_size
        sizes[rel] = nbytes
        if nbytes > limit:
            failures.add(
                "hot-path-file-size",
                f"{rel} 已达 {nbytes}B > {limit}B——"
                "每轮对话必经的文件继续膨胀会拖慢 review 与重构，"
                "新逻辑应抽到独立模块后再接线",
            )
    return sizes


CHECKS = (
    ("import-budget", check_import_budget),
    ("pipeline-step-metric", check_step_metric_overhead),
    ("shared-thread-pool", check_shared_pool_reuse),
    ("mock-metrics-gate", check_no_mock_metrics_by_default),
    ("hot-path-file-size", check_hot_path_file_size),
)


def main() -> int:
    parser = argparse.ArgumentParser(description="性能回归门禁")
    parser.add_argument("--json", action="store_true", help="机器可读输出")
    args = parser.parse_args()

    failures = Failures()
    results = {}
    for name, fn in CHECKS:
        try:
            results[name] = fn(failures)
        except Exception as exc:  # noqa: BLE001 - 门禁自身故障也要报出来
            failures.add(name, f"检查执行失败: {type(exc).__name__}: {exc}")

    if args.json:
        print(json.dumps({"results": results, "failures": list(failures)}, ensure_ascii=False, indent=2))
        return 1 if failures else 0

    print("=" * 72)
    print("性能回归门禁")
    print("=" * 72)
    for name, _fn in CHECKS:
        print(f"\n[{name}]")
        print(f"  {json.dumps(results.get(name, {}), ensure_ascii=False)}")

    if failures:
        print("\n" + "=" * 72)
        print(f"❌ 发现 {len(failures)} 项性能回归：")
        for item in failures:
            print(f"  - {item['check']}: {item['detail']}")
        return 1
    print("\n✅ 性能门禁通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
