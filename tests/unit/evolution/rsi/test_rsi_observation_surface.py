"""RSI 观测面收口（工单 012）：每块仪表要么真的接电，要么拆掉。

本文件锁四件事，全部是可grep/可运行的判据，不接受"看起来有实现"：

1. **规范指标必须有生产写入方**。`RSIMetrics` 声明 7 个规范常量，而
   `run_iteration` 写的是临时键（`iteration_count`/`applied_count`/…）——
   于是 `check_alerts()` 与"棘轮门通过率"吃的是从未被写过的键，恒 0。
   定义了没人写 = 缺陷；写了没人读 也是（工单 008 同口径）。
2. **不允许两套键并存**。临时键必须删净，否则同一件事有两个数，迟早漂移。
3. **候选统计与回滚史必须有真实来源**（剪枝器 `prune_history`、
   `rollback_manager.get_rollback_history()`），不是 `return []` 的显式 stub。
4. **状态端点必须存在且读对实例**：`deployment_phase` 与控制器逐值相等；
   RSI 没装配时不得用 200 + `available:false` 静默（工单 011 同一条证据）。

阶段一律经 `rsi_probe_factory` 由治理设置注入（conftest 禁令 1）。
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from neurova.evolution.rsi.metrics import RSIMetrics
from tests import ast_scan

REPO_ROOT = Path(__file__).resolve().parents[4]
PKG_ROOT = REPO_ROOT / "neurova"

# 规范指标常量名 → 它对应的键值（由 metrics.py 声明，本文件不复制字面量）
_CANONICAL_ATTRS = (
    "RSI_CYCLES_TOTAL",
    "RSI_IMPROVEMENT_RATE",
    "RSI_CONVERGENCE_ROI",
    "RSI_ROLLBACK_COUNT",
    "RSI_CANDIDATES_GENERATED",
    "RSI_CANDIDATES_PRUNED",
    "RSI_GATE_FAILURES",
    "EXPERIENCE_ROWS",
    "EXPERIENCE_UNEVIDENCED_RATIO",
    "EXPERIENCE_HIT_RATE",
    "EXPERIENCE_ADOPTION_SUCCESS_RATE",
    "EXPERIENCE_ADOPTION_DECISIONS",
)


def _production_metric_writes() -> set[str]:
    """收集生产代码里所有 `record_metric(RSIMetrics.X)` / `record_metric(self.X)` 的 X。

    排除 `metrics.py` 自身（它在 `__init__` 里把每个键初始化成 0，那是"仪表通电"
    不是"有读数"，算进去就等于让仪表自己给自己供值）。

    解析走 `tests/ast_scan.py`（Issue #148）：本判据只谈「`record_metric` 的写入点
    有哪些」，与文件总数无关，故按 `record_metric` 文本预筛——实测 `neurova/` 1014
    文件里含该字样的只有十几个，全仓 `ast.parse` 要 5s、与受保护子集其余 170 个
    文件共享机器时必撞 30s 默认墙钟（本次构建实测 timeout）。
    """
    written: set[str] = set()
    for path, node in ast_scan.callNodes(PKG_ROOT, "record_metric", hints=("record_metric",)):
        if path.name == "metrics.py":
            continue
        if not node.args:
            continue
        first = node.args[0]
        if isinstance(first, ast.Attribute) and first.attr in _CANONICAL_ATTRS:
            written.add(first.attr)
    return written


def test_every_declared_canonical_metric_has_a_production_writer():
    """声明了却没人写的指标 = 恒 0 的假仪表，必须接电或删除。"""
    declared = {name for name in _CANONICAL_ATTRS if hasattr(RSIMetrics, name)}
    written = _production_metric_writes()
    unwritten = sorted(declared - written)
    assert not unwritten, f"以下规范指标在生产侧零写入方：{unwritten}"
    # 反向锁：本清单里不得出现"已删除却还列着"的名字
    assert declared, "常量清单整体失效，需同步本用例"


def test_fresh_metrics_report_absence_not_zero():
    """新实例不得预写规范指标为 0（工单 017 C 项，与 012 同一条线）。

    `__init__` 曾把 12 颗指标预置成 0 —— 那等于在"还没测"的时刻给读侧一个
    "改进率 0%、ROI 0、回滚 0 次"的确定读数，而 012 立的就是这条禁止令。
    缺席必须由 `get_metric` 返回 None 表达，不能由 0 冒充。
    """
    fresh = RSIMetrics()

    assert not fresh._metrics, (
        f"未测即有值，读侧无法区分「没测到」与「真是 0」：{sorted(fresh._metrics)}")
    assert fresh.get_metric(RSIMetrics.RSI_IMPROVEMENT_RATE) is None
    assert fresh.get_metric(RSIMetrics.RSI_CONVERGENCE_ROI) is None
    # 告警面在空实例上不得凭空造出 CRITICAL（缺值按 0 处理，不是按"发散"处理）
    assert fresh.check_alerts() == []


def test_run_iteration_writes_canonical_names_and_no_temp_keys(rsi_probe_factory):
    """一轮迭代后：规范键在场，临时键一个都不许留。"""
    temp_keys = {
        "iteration_count", "feedback_signals_count",
        "optimizations_count", "applied_count", "eval_score",
    }
    probe = rsi_probe_factory(rsi_phase=2)
    probe.orchestrator.run_iteration()

    stored = set(probe.orchestrator.metrics._metrics)
    leftover = sorted(temp_keys & stored)
    assert not leftover, f"临时键未删净，与规范键并存必漂移：{leftover}"
    assert RSIMetrics.RSI_CYCLES_TOTAL in stored
    assert probe.orchestrator.metrics.get_metric(RSIMetrics.RSI_CYCLES_TOTAL) == 1, (
        "cycles_total 必须是真实迭代轮次（工单 008 的告警文案吃它）")


def test_candidate_statistics_come_from_real_prune_history(rsi_probe_factory):
    """候选生成/剪枝数来自剪枝器，不是常数 0（dashboard 恒 0 的病根）。"""
    probe = rsi_probe_factory(rsi_phase=2)
    result = probe.orchestrator.run_iteration()

    generated = probe.orchestrator.metrics.get_metric(RSIMetrics.RSI_CANDIDATES_GENERATED)
    pruned = probe.orchestrator.metrics.get_metric(RSIMetrics.RSI_CANDIDATES_PRUNED)
    assert generated and generated > 0, "本轮确有候选被剪枝（默认装配有真实梯度）"
    assert pruned is not None and pruned >= 0
    assert generated - pruned >= 1, "剪完至少要剩下东西，否则通过率恒 0 是假读数"


def test_improvement_rate_is_the_gain_history_ratio(rsi_probe_factory, measured_eval_harness):
    """改进率来自 `gain_history`，且必须等于"正增益轮次 / 已记录轮次"。

    判据取自分析器自己的历史，本用例锁的是"写进指标面的数与历史一致"，
    而不是再抄一份算式（工单 016 同口径：算式只能有一份）。
    """
    probe = rsi_probe_factory(rsi_phase=2)
    probe.orchestrator._eval_harness = measured_eval_harness([0.5, 0.9, 0.5, 0.4])

    for _ in range(2):
        probe.orchestrator.run_iteration()

    history = probe.orchestrator.convergence_analyzer.gain_history
    assert history, "前置：本轮确有增益被记录"
    expected = sum(1 for g in history if g > 0) / len(history)
    assert probe.orchestrator.metrics.get_metric(
        RSIMetrics.RSI_IMPROVEMENT_RATE) == pytest.approx(expected)


def test_gate_failures_count_consecutive_vetoes(rsi_probe_factory):
    """`check_alerts()` 的文案是"连续失败 N 次"，口径必须与之一致。"""
    probe = rsi_probe_factory(rsi_phase=1)  # 刚装配 → days 不足 → 每轮硬否决

    for _ in range(3):
        probe.orchestrator.run_iteration()
    failures = probe.orchestrator.metrics.get_metric(RSIMetrics.RSI_GATE_FAILURES)
    assert failures == 3, f"连续三次否决应计到 3，实际 {failures}"

    alerts = [a.metric for a in probe.orchestrator.metrics.check_alerts()]
    assert RSIMetrics.RSI_GATE_FAILURES in alerts, (
        "阈值 gate_failures_error=3 的告警必须真的可达（工单 008 同口径：不可达=缺陷）")


def test_rollback_count_mirrors_real_history_length(rsi_probe_factory):
    """回滚计数来自 `rollback_manager` 的真实历史（004 已使历史真实）。"""
    probe = rsi_probe_factory(rsi_phase=2)
    manager = probe.orchestrator.rollback_manager
    manager.execute_rollback(manager.create_snapshot({"x": {"system": "sleep", "value": 0.7}}))

    probe.orchestrator.run_iteration()

    assert probe.orchestrator.metrics.get_metric(
        RSIMetrics.RSI_ROLLBACK_COUNT) == len(manager.get_rollback_history()), (
        "回滚计数必须等于真实历史长度，不得恒 0")
    assert len(manager.get_rollback_history()) >= 1, "前置：确有回滚发生"


# ── get_status 收口：dashboard 的两个聚合并入，回滚史不再 return [] ──────────


def test_get_status_carries_candidate_aggregates_and_real_history(rsi_probe_factory):
    """`RSIDashboard` 被删后，它唯一有用的两个聚合必须在 `get_status()` 里可达。"""
    probe = rsi_probe_factory(rsi_phase=2)
    probe.orchestrator.run_iteration()

    status = probe.orchestrator.get_status()

    assert status["candidates"]["generated"] > 0
    assert 0.0 < status["candidates"]["pass_rate"] <= 1.0, (
        "通过率必须真的算得出来（dashboard 版恒 0 的那个缺陷不得复制过来）")
    assert isinstance(status["rollback_history"], list)
    assert status["phase_verdict"]["state"] in {"passed", "failed", "unevidenced"}
    assert "phase_persisted" in status, (
        "工单 005 的两态在此必须可读：推送面已随 012 删除，本端点是人的读点")
    assert "experience" in status["metrics"], (
        "工单 008 的经验族视图不得因删除 dashboard 而失去读点")


def test_dashboard_and_push_rsi_result_are_gone():
    """二选一选了"拆"：不留悬空仪表，也不留只被测试调用的推送口。"""
    assert not (PKG_ROOT / "evolution" / "rsi" / "dashboard.py").exists(), (
        "RSIDashboard 生产零实例化，应整删")
    import neurova.evolution.rsi as rsi_pkg

    assert not hasattr(rsi_pkg, "RSIDashboard")
    assert not hasattr(rsi_pkg, "create_rsi_dashboard")

    from neurova.notifications.negative_screen import NegativeScreenPusher

    assert not hasattr(NegativeScreenPusher, "push_rsi_result"), (
        "push_rsi_result 生产零调用方，与 dashboard 同病")
    assert not (REPO_ROOT / "tests" / "unit" / "evolution" / "test_rsi_dashboard.py").exists(), (
        "删除实现必须连单测一起删")


# ── 状态端点 ────────────────────────────────────────────────────────────────


def _governance_client(rsi_orchestrator):
    """沿用 `test_rsi_approval_endpoints.py` 的端点测试口径：只挂 governance 路由 + 管理员覆盖。

    `_get_rsi_orchestrator()` 的既有契约是"返回 RSI 编排器，没装配则返回 None"，
    本 helper 不把它换成 MagicMock —— 否则端点拿到的是替身，测不到真实读点。
    """
    from unittest.mock import patch

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from neurova.api.deps import get_current_user
    from neurova.api.endpoints.governance import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1/governance")
    app.dependency_overrides[get_current_user] = lambda: {"user_id": "admin1", "role": "admin"}

    patcher = patch(
        "neurova.api.endpoints.governance._get_rsi_orchestrator",
        return_value=rsi_orchestrator,
    )
    patcher.start()
    return TestClient(app), patcher


def test_status_endpoint_matches_controller_phase(rsi_probe_factory):
    """跑 3 轮后，端点报的 deployment_phase 必须与控制器逐值相等。"""
    probe = rsi_probe_factory(rsi_phase=2)
    for _ in range(3):
        probe.orchestrator.run_iteration()

    client, patcher = _governance_client(probe.orchestrator)
    try:
        resp = client.get("/api/v1/governance/rsi/status")
    finally:
        patcher.stop()

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["deployment_phase"] == \
        probe.orchestrator.deployment_controller.get_current_phase()
    assert data["iteration_count"] == 3
    assert data["candidates"]["generated"] > 0


def test_status_endpoint_refuses_to_silently_report_absent_rsi():
    """RSI 未装配必须是 503 + 原因，不得 200 + available:false 静默（工单 011 同证据）。"""
    client, patcher = _governance_client(None)
    try:
        resp = client.get("/api/v1/governance/rsi/status")
    finally:
        patcher.stop()

    assert resp.status_code == 503, (
        f"没装配的 RSI 被读成了一次正常状态：{resp.status_code} {resp.text[:200]}")
