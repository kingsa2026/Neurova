#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""性能回归门禁（Issue #55）。

为什么要这个门禁：本仓此前没有任何"性能"维度的 CI 检查——
.cnb.yml 无 perf 任务，tests/performance/ 只有一个压测，
于是"关键路径变慢 3 倍"这种回归只能等人肉发现（而尾延迟正是用户体验）。

门禁内容（都刻意与机器无关/宽松，只抓数量级回归）：

1. **import 冷启动预算**：``import neurova.post_chat_pipeline`` 的墙钟时长
   必须低于 IMPORT_BUDGET_MS。历史上该模块是每轮对话必经的 import 面，
   import 期偷偷做重活（网络/模型加载/大文件读）会直接进首轮延迟。
2. **关键路径微基准**：管线与共享线程池的最热操作必须有数量级裕量。
   - PostChatPipeline 步骤埋点开销（每步一次 counter+histogram）
   - 共享线程池 get_thread_pool() 复用（不得退化为每次新建）
   - MetricsCollector 假数据默认禁用（接线假数 = 仪表盘失真）

阈值策略：给足裕量（CI 机器比开发机慢、负载抖动）。门禁只回答
"是否发生数量级退化"，不追求精确 benchmark——追精确会让门禁变成
flaky 噪音源，最终被人绕过。

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


class Failures(list):
    def add(self, name: str, detail: str) -> None:
        self.append({"check": name, "detail": detail})


def _measure_import(module: str) -> float:
    """在子进程里冷 import 并返回毫秒（子进程隔离 sys.modules 缓存）。

    本函数是门禁里**唯一**该用墙钟的地方：它量的是"用户实际等了多久"
    （首轮对话延迟），等待 CPU 的时间对用户同样是延迟，必须计入。
    进程内的两处微基准与此相反，见模块 docstring。
    """
    code = (
        "import time; t=time.perf_counter(); "
        f"import {module}; "
        "print(round((time.perf_counter()-t)*1000, 2))"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
        timeout=180,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"import {module} 失败: {proc.stderr.strip()[-500:]}")
    return float(proc.stdout.strip().splitlines()[-1])


def check_import_budget(failures: Failures) -> dict:
    """检查 1：import 时长。"""
    results = {}
    total = 0.0
    for module in ("neurova.core.metrics", "neurova.post_chat_pipeline"):
        ms = _measure_import(module)
        results[module] = ms
        total += ms
        if ms > IMPORT_BUDGET_MS:
            failures.add(
                "import-budget",
                f"import {module} 耗时 {ms:.1f}ms > 预算 {IMPORT_BUDGET_MS:.0f}ms"
                "（import 期重型副作用会进首轮对话延迟）",
            )
    results["_total_ms"] = total
    if total > IMPORT_ALL_BUDGET_MS:
        failures.add(
            "import-budget",
            f"关键 import 面合计 {total:.1f}ms > 预算 {IMPORT_ALL_BUDGET_MS:.0f}ms",
        )
    return results


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
    # 量"这段代码要花多少 CPU"：取本线程 CPU 时间，等待不计入（见模块 docstring）
    start = time.thread_time()
    for i in range(iterations):
        metrics.record_pipeline_step(step_names[i % len(step_names)], "executed", 1.0)
    elapsed_ms = (time.thread_time() - start) * 1000.0
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
    # 同检查 2：取本线程 CPU 时间（池获取是纯 CPU 路径，等待不该算进判值）
    start = time.thread_time()
    acquired = [get_thread_pool(name="perf-probe", max_workers=2) for _ in range(iterations)]
    elapsed_ms = (time.thread_time() - start) * 1000.0
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
