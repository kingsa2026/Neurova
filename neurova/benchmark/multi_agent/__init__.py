# -*- coding: utf-8 -*-
"""多 Agent 协作评测 harness（P0-1，依据 docs/04-plans/2026-11-17-multi-agent-collaboration-upgrade-plan.md）。

对外现役面：
- BenchmarkTask / TaskOutcome / registerTask / listTasks / getTask / clearTasks（任务注册表）
- BenchRunner（solo / swarm 双模式跑任务，swarm 走真 SwarmManager 链路含治理闸）
- metrics.aggregate / metrics.compare（成功率、均分、不可解题识别、开销对照）
- report.buildReport / renderMarkdown（JSON + Markdown 报告）

设计纪律（与 rag_eval 同族）：
- 判定器注入：任务自带 check(outcome) → (passed, score, details)，harness 不伪造分数；
- mock 优先：CI 用假 agent 验 harness 管道正确性；真模型跑是发布前手动门（NEUROVA_BENCH_LIVE）；
- 不绕治理闸：swarm 模式经 SwarmManager.spawn 正常入口，治理拒绝计为该任务失败。
"""
from neurova.benchmark.multi_agent.runner import BenchRunner
from neurova.benchmark.multi_agent.tasks import (
    BenchmarkTask,
    TaskOutcome,
    clearTasks,
    getTask,
    listTasks,
    registerTask,
)

__all__ = [
    "BenchRunner",
    "BenchmarkTask",
    "TaskOutcome",
    "registerTask",
    "listTasks",
    "getTask",
    "clearTasks",
]
