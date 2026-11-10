# -*- coding: utf-8 -*-
"""C5 纵报四格（survey §10.2）——接受率/新成功/回归/恢复成本进 checkpoint 台账。

红灯判据：触发一次回滚后，恢复成本（回滚耗时＋重测次数）入账可查；缺格
呈报点名（不冒充）。
"""

import pytest

from neurova.evolution.rsi.audit_schedule import AuditSchedule


def test_rollback_populates_recovery_cost(tmp_path, monkeypatch):
    """红灯判据本体：回滚发生后 checkpoint 快照带恢复成本（回滚耗时＋重测）。"""
    from unittest.mock import MagicMock

    from neurova.evolution.rsi.orchestrator import RSIOrchestrator

    monkeypatch.delenv("NEUROVA_RSI_IMPROVER_LEDGER", raising=False)
    monkeypatch.delenv("NEUROVA_RSI_AUDIT_SCHEDULE", raising=False)
    orch = RSIOrchestrator(
        sleep_system=MagicMock(), emotion_system=MagicMock(),
        experience_system=MagicMock(), tool_memory_system=MagicMock(),
    )
    # 注入一次回滚事件（直接压实例态，模拟回滚分支的产物）
    orch._last_recovery = {"rollback_ms": 12, "remeasure_evals": 1}
    columns = orch._checkpointColumns()
    assert columns["recovery_cost"]["rollback_ms"] == 12
    assert columns["missing"] == [] or "recovery_cost" not in columns["missing"]


def test_no_rollback_names_the_missing_column(tmp_path, monkeypatch):
    """缺格呈报点名：无回滚时 recovery_cost 缺席被点名，不冒充 0 成本。"""
    from unittest.mock import MagicMock

    from neurova.evolution.rsi.orchestrator import RSIOrchestrator

    monkeypatch.delenv("NEUROVA_RSI_IMPROVER_LEDGER", raising=False)
    orch = RSIOrchestrator(
        sleep_system=MagicMock(), emotion_system=MagicMock(),
        experience_system=MagicMock(), tool_memory_system=MagicMock(),
    )
    columns = orch._checkpointColumns()
    assert "recovery_cost" in columns["missing"], (
        f"缺格没点名：{columns}——缺席被读成零成本")
    assert columns["recovery_cost"] is None


def test_acceptance_rate_rolls_from_totals(tmp_path, monkeypatch):
    from unittest.mock import MagicMock

    from neurova.evolution.rsi.orchestrator import RSIOrchestrator

    monkeypatch.delenv("NEUROVA_RSI_IMPROVER_LEDGER", raising=False)
    orch = RSIOrchestrator(
        sleep_system=MagicMock(), emotion_system=MagicMock(),
        experience_system=MagicMock(), tool_memory_system=MagicMock(),
    )
    orch._attempts_total = 4
    orch._applied_total = 3
    assert orch._checkpointColumns()["acceptance_rate"] == pytest.approx(0.75)


def test_checkpoint_snapshot_carries_columns(tmp_path, monkeypatch):
    """D2 预定时刻快照携带四格（进台账可查）。"""
    schedule = AuditSchedule(tmp_path / "audit.json", stride=5)
    orch_snapshot = {"checkpoint_columns": {
        "acceptance_rate": 0.75, "new_successes": [], "regressions": [],
        "recovery_cost": {"rollback_ms": 8, "remeasure_evals": 1}, "missing": [],
    }}
    assert schedule.recordSnapshot(5, orch_snapshot)
    readout = schedule.readAuditSnapshot(5)
    assert readout["snapshot"]["checkpoint_columns"]["recovery_cost"][
        "rollback_ms"] == 8
