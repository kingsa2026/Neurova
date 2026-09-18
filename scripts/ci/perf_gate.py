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
    """在子进程里冷 import 并返回毫秒（子进程隔离 sys.modules 缓存）。"""
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
    start = time.perf_counter()
    for i in range(iterations):
        metrics.record_pipeline_step(step_names[i % len(step_names)], "executed", 1.0)
    elapsed_ms = (time.perf_counter() - start) * 1000.0
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
    """检查 3：共享线程池确为复用（不得退化为每次新建池）。"""
    from neurova.core.thread_pool import get_thread_pool

    iterations = 1000
    start = time.perf_counter()
    pools = {id(get_thread_pool(name="perf-probe", max_workers=2)) for _ in range(iterations)}
    elapsed_ms = (time.perf_counter() - start) * 1000.0
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
