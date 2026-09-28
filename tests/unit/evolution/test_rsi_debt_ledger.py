"""RSI 回执负债口径与反向闸（Issue #289 · 003）。

票面（`docs/specs/2026-09-28-evidence-gate-and-context-economics/tickets/003`）
的七条红灯在此落地。它们的共同判据只有一句：

    现在的账只能证明"我做过有益的事"，不能证明"我没连续挥霍"。

单向账本会让棘轮**系统性偏向多动作者** —— 多动就多几条被记录的增益。

约定（与 002 同域，禁第二套口径）：

- 代价口径**引用** `context.compression_economics` 的 `profit` / `cost` 字段名，
  本模块与 `neurova/evolution/rsi/debt_ledger.py` 都不另立一份"代价"定义；
- 不动作原因与 002 共用同一命名体系（值域来自同一处声明）；
- 灰度复用 `deployment_controller` 的阶段语义，不新造开关。
"""

from __future__ import annotations

import json
from pathlib import Path

from neurova.evolution.rsi.integration_manager import RSIIntegrationManager
from tests.unit.evolution.conftest import ProbeSystem

PRODUCED_TOOL_MEMORY_PARAMS = {
    "success_bonus": 0.1,
    "failure_penalty": 0.05,
    "decay_rate": 0.01,
    "muscle_memory_threshold": 0.85,
}


def _manager(tmp_path: Path) -> RSIIntegrationManager:
    """真集成管理器 + 真落点参数（不用 MagicMock 冒充业务对象）。"""
    return RSIIntegrationManager(
        sleep_system=ProbeSystem("sleep"),
        emotion_system=ProbeSystem("emotion"),
        experience_system=ProbeSystem("experience"),
        tool_memory_system=ProbeSystem(
            "tool_memory",
            feedback={"total_usages": 50, "success_rate": 0.5},
            params=PRODUCED_TOOL_MEMORY_PARAMS,
        ),
    )


def _receipt_lines(path: Path) -> list:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


# ── 1. 回执行必须携带代价与偿还两字段 ─────────────────────────────
def testReceiptCarriesCostAndRepaymentFields(tmp_path, monkeypatch):
    """一笔动作落账时必须同时写下"欠了多少"与"还过多少"。

    现状红：行形态是 `{ts, parameter_path, old_value, new_value}` 四字段。
    """
    from neurova.evolution.rsi.debt_ledger import ledger_kind

    receipts = tmp_path / "rsi_receipts.jsonl"
    monkeypatch.setenv("NEUROVA_RSI_RECEIPTS", str(receipts))
    manager = _manager(tmp_path)
    assert manager.apply_optimization(
        "tool_memory.decay_rate", 0.05, debt_ledger=_make_ledger(tmp_path, monkeypatch)
    )
    lines = _receipt_lines(receipts)
    assert len(lines) == 1
    record = lines[0]
    assert "cost" in record, f"回执行缺代价字段：{sorted(record)}"
    assert "repayment" in record, f"回执行缺偿还字段：{sorted(record)}"
    assert ledger_kind(record) == "debt_carrying"


def _make_ledger(tmp_path: Path, monkeypatch):
    from neurova.evolution.rsi.debt_ledger import RsiDebtLedger

    receipts = tmp_path / "rsi_receipts.jsonl"
    monkeypatch.setenv("NEUROVA_RSI_RECEIPTS", str(receipts))
    return RsiDebtLedger(receipts)


# ── 2. 字段缺失 ≠ 值为 0 ─────────────────────────────────────────
def testMissingFieldIsDistinguishedFromZero(tmp_path, monkeypatch):
    """存量行没有 `cost` 列，与"代价实测为 0"必须是两个不同的态。

    把两者折叠，就是本仓在 `success` 三态上已经修过的同一病灶。
    """
    from neurova.evolution.rsi.debt_ledger import RsiDebtLedger, ledger_kind

    receipts = tmp_path / "rsi_receipts.jsonl"
    receipts.write_text(
        json.dumps({"ts": 1.0, "parameter_path": "sleep.base_decay_rate",
                    "old_value": 0.7, "new_value": 0.72}) + "\n"
        + json.dumps({"ts": 2.0, "parameter_path": "sleep.base_decay_rate",
                      "old_value": 0.72, "new_value": 0.74,
                      "cost": 0, "repayment": 0}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("NEUROVA_RSI_RECEIPTS", str(receipts))
    ledger = RsiDebtLedger(receipts)
    rows = ledger.list_rows()
    assert len(rows) == 2
    assert ledger_kind(rows[0]) == "legacy_unpriced"
    assert ledger_kind(rows[1]) == "debt_carrying"
    # 未定价的行不得被读成"债为 0"：它的负债额是"未知"，不是 0。
    assert ledger.outstanding_lookup()["unknown_rows"] == 1
    assert ledger.outstanding_lookup()["priced_rows"] == 1


# ── 3. 欠账未清则拒绝下一次寻优动作 ───────────────────────────────
def testUnclearedDebtBlocksNextOptimizationStep(tmp_path, monkeypatch):
    """反向闸本体：上一笔代价未清 ⇒ 本次不动作且给出原因。

    现状红：全仓无任何一处因"上次代价未清"而拒绝本次动作。
    """
    from neurova.evolution.rsi.debt_ledger import RsiDebtLedger

    receipts = tmp_path / "rsi_receipts.jsonl"
    monkeypatch.setenv("NEUROVA_RSI_RECEIPTS", str(receipts))
    ledger = RsiDebtLedger(receipts)
    ledger.record(parameter_path="tool_memory.decay_rate", old_value=0.01,
                  new_value=0.05, cost=40, repayment=0, ts=100.0)
    verdict = ledger.evaluate_next_step()
    assert verdict.allow is False
    assert verdict.reason == "debt_uncleared"
    assert verdict.outstanding == 40
    # 还清之后放行：二次动作把上次欠的 40 全数偿还（repayment 不参与本行自身净额，
    # 故本行不能再叠新代价 —— 这正是"先还债才准再做"的语义）。
    ledger.record(parameter_path="tool_memory.decay_rate", old_value=0.05,
                  new_value=0.04, cost=0, repayment=40, ts=200.0)
    cleared = ledger.evaluate_next_step()
    assert cleared.allow is True, cleared
    assert cleared.outstanding == 0


# ── 4. 账本写失败走安全侧 ────────────────────────────────────────
def testLedgerWriteFailureTakesSafeSideAndEmitsReason(tmp_path, monkeypatch):
    """丢行不得静默放行：债记不下时保守拒绝本次动作，并留下可归因读数。

    票面前置：`_write_optimization_receipt` 自陈"写失败仅告警不影响主流程"。
    把闸建在允许丢行的账本上 = 闸可以靠"把账写丢"绕过。
    """
    from neurova.evolution.rsi.debt_ledger import RsiDebtLedger

    receipts = tmp_path / "rsi_receipts.jsonl"
    monkeypatch.setenv("NEUROVA_RSI_RECEIPTS", str(receipts))
    ledger = RsiDebtLedger(receipts)
    ledger.force_write_failure_for_test(True)
    ok = ledger.record(parameter_path="tool_memory.decay_rate", old_value=0.01,
                       new_value=0.05, cost=40, repayment=0, ts=100.0)
    assert ok is False
    assert ledger.last_write_failure_reason() == "ledger_write_failed"
    verdict = ledger.evaluate_next_step()
    assert verdict.allow is False
    assert verdict.reason == "ledger_write_failed"


# ── 5. 回滚不得制造无主欠账 ──────────────────────────────────────
def testRollbackSettlesOrCarriesDebt(tmp_path, monkeypatch):
    """回滚时该笔债务必须结清或显式转挂，不许静默消失。"""
    from neurova.evolution.rsi.debt_ledger import RsiDebtLedger

    receipts = tmp_path / "rsi_receipts.jsonl"
    monkeypatch.setenv("NEUROVA_RSI_RECEIPTS", str(receipts))
    ledger = RsiDebtLedger(receipts)
    ledger.record(parameter_path="tool_memory.decay_rate", old_value=0.01,
                  new_value=0.05, cost=40, repayment=0, ts=100.0)
    assert ledger.outstanding_lookup()["outstanding"] == 40
    disposition = ledger.settle_on_rollback(reason="rollback_restored_snapshot", ts=150.0)
    assert disposition in {"settled", "carried_forward"}
    lookup = ledger.outstanding_lookup()
    # 静默消失被显式禁止：两种合法处置都必须留下可读的账。
    if disposition == "settled":
        assert lookup["outstanding"] == 0
    else:
        assert lookup["outstanding"] == 40
    assert ledger.list_rows()[-1]["debt_disposition"] == disposition


# ── 6. 原因枚举与 002 同源 ───────────────────────────────────────
def testDebtReasonSharesEnumWithCompressionGate():
    """静态守卫：负债侧的原因值必须落在 002 建立的同一命名体系里。

    两处各开一套枚举 = 教义第 6 条双源。
    """
    from neurova.context.compression_economics import INACTION_VALUES, CompressionAction
    from neurova.evolution.rsi import debt_ledger

    shared = {value.value for value in CompressionAction}
    # 负债侧原因名 → 002 命名体系的映射值必须逐条落在 002 的枚举值内。
    mapped = set(debt_ledger.DEBT_REASON_TO_ACTION.values())
    unknown = {v for v in mapped if v not in shared}
    assert not unknown, f"负债侧映射值不在 002 的命名体系内：{sorted(unknown)}"
    # 每个原因名都必须有映射 —— 漏一个就是"同一事实两处定义"的开端。
    assert debt_ledger.DEBT_REASONS == set(debt_ledger.DEBT_REASON_TO_ACTION), (
        "负债侧原因名与映射表不同步"
    )
    # 映射表必须真的引用 002 的枚举值而不是抄一份字面量：改空 002 时本守卫要红。
    assert INACTION_VALUES == frozenset(
        {CompressionAction.PROFIT_NOT_POSITIVE, CompressionAction.UNECONOMICAL,
         CompressionAction.INSUFFICIENT_DATA, CompressionAction.INFEASIBLE,
         CompressionAction.RULER_UNCALIBRATED, CompressionAction.ENVELOPE_DISCARDED}
    )
    assert debt_ledger.DEBT_REASON_TO_ACTION["debt_uncleared"] == (
        CompressionAction.UNECONOMICAL.value
    )


# ── 7. 治理面必须能看到新账 ──────────────────────────────────────
def testGovernanceSurfaceExposesDebt(tmp_path, monkeypatch):
    """新列必须在治理面可读 —— 只写不读的字段是 AGENTS.md §2 点名的断点。"""
    receipts = tmp_path / "rsi_receipts.jsonl"
    monkeypatch.setenv("NEUROVA_RSI_RECEIPTS", str(receipts))
    monkeypatch.setenv("NEUROVA_EVOLUTION_ROLLBACK", str(tmp_path / "rb.json"))
    monkeypatch.setenv("NEUROVA_GOVERNANCE_SETTINGS", str(tmp_path / "gov.json"))
    (tmp_path / "gov.json").write_text(json.dumps({"rsi_phase": 0}), encoding="utf-8")

    from neurova.evolution.rsi.debt_ledger import RsiDebtLedger
    from tests.unit.evolution.conftest import _default_systems

    ledger = RsiDebtLedger(receipts)
    ledger.record(parameter_path="tool_memory.decay_rate", old_value=0.01,
                  new_value=0.05, cost=40, repayment=0, ts=100.0)

    from neurova.evolution.rsi.orchestrator import RSIOrchestrator

    systems = _default_systems(PRODUCED_TOOL_MEMORY_PARAMS)
    orchestrator = RSIOrchestrator(
        sleep_system=systems["sleep"], emotion_system=systems["emotion"],
        experience_system=systems["experience"], tool_memory_system=systems["tool_memory"],
    )
    status = orchestrator.get_status()
    assert "debt" in status, f"治理状态面缺负债读数：{sorted(status)}"
    assert status["debt"]["outstanding"] == 40
    assert status["debt"]["next_step"]["allow"] is False
    assert status["debt"]["next_step"]["reason"] == "debt_uncleared"


# ── 8. 反向闸必须在编排器生产路径上真的生效 ─────────────────────
def testOrchestratorGateBlocksOptimizationsWhenDebtUncleared(tmp_path, monkeypatch):
    """接线层判据：闸不能只是账本里的一个方法，必须真接在寻优路径上。

    与 002 的"AST 守卫"同一意图：判据本体存在 ≠ 生产链路过闸。
    这里走编排器真装配点（不私赋 phase，经治理设置文件进入）。
    """
    import json as _json

    receipts = tmp_path / "rsi_receipts.jsonl"
    monkeypatch.setenv("NEUROVA_RSI_RECEIPTS", str(receipts))
    monkeypatch.setenv("NEUROVA_EVOLUTION_ROLLBACK", str(tmp_path / "rb.json"))
    monkeypatch.setenv("NEUROVA_GOVERNANCE_SETTINGS", str(tmp_path / "gov.json"))
    # phase 2 = 低风险自动执行已放开（K3：灰度复用既有阶段语义，不新造开关）
    (tmp_path / "gov.json").write_text(_json.dumps({"rsi_phase": 2}), encoding="utf-8")

    from neurova.evolution.rsi.debt_ledger import RsiDebtLedger
    from neurova.evolution.rsi.orchestrator import RSIOrchestrator
    from tests.unit.evolution.conftest import _default_systems

    RsiDebtLedger(receipts).record(
        parameter_path="tool_memory.decay_rate", old_value=0.01,
        new_value=0.05, cost=40, repayment=0, ts=100.0,
    )

    systems = _default_systems(PRODUCED_TOOL_MEMORY_PARAMS)
    orchestrator = RSIOrchestrator(
        sleep_system=systems["sleep"], emotion_system=systems["emotion"],
        experience_system=systems["experience"], tool_memory_system=systems["tool_memory"],
    )
    verdict = orchestrator._debt_gate_verdict()
    assert verdict.allow is False
    assert verdict.reason == "debt_uncleared"

    # 真跑一轮：本轮不得产生任何 applied（闸把 optimizations 清空）。
    result = orchestrator.run_iteration()
    assert result["applied_count"] == 0, result
    assert orchestrator.get_status()["debt"]["next_step"]["allow"] is False


# ── 9. 拦下必须可归因（不得表现为"本轮刚好没候选"）──────────────
def testGateBlockIsAttributableInTheIterationResult(tmp_path, monkeypatch):
    """被闸拦下与"本轮没有候选"在观测上是相反的事，必须分得开。"""
    import json as _json

    receipts = tmp_path / "rsi_receipts.jsonl"
    monkeypatch.setenv("NEUROVA_RSI_RECEIPTS", str(receipts))
    monkeypatch.setenv("NEUROVA_EVOLUTION_ROLLBACK", str(tmp_path / "rb.json"))
    monkeypatch.setenv("NEUROVA_GOVERNANCE_SETTINGS", str(tmp_path / "gov.json"))
    (tmp_path / "gov.json").write_text(_json.dumps({"rsi_phase": 2}), encoding="utf-8")

    from neurova.evolution.rsi.debt_ledger import RsiDebtLedger
    from neurova.evolution.rsi.orchestrator import RSIOrchestrator
    from tests.unit.evolution.conftest import _default_systems

    RsiDebtLedger(receipts).record(
        parameter_path="tool_memory.decay_rate", old_value=0.01,
        new_value=0.05, cost=40, repayment=0, ts=100.0,
    )
    systems = _default_systems(PRODUCED_TOOL_MEMORY_PARAMS)
    orchestrator = RSIOrchestrator(
        sleep_system=systems["sleep"], emotion_system=systems["emotion"],
        experience_system=systems["experience"], tool_memory_system=systems["tool_memory"],
    )
    result = orchestrator.run_iteration()
    assert result["debt_gate"]["blocked"] is True, result["debt_gate"]
    assert result["debt_gate"]["reason"] == "debt_uncleared"
    assert result["debt_gate"]["outstanding"] == 40


# ── 10. 真装配路径下的回执必须带 cost（生产链路口径一致）────────
def testReceiptsThroughOrchestratorCarryCost(tmp_path, monkeypatch):
    """走 `apply_optimizations` 真路径的回执也要带 `cost` 两列。

    `apply_optimization(debt_ledger=...)` 单测绿 ≠ 生产链路带账本 ——
    这一条防的是"判据本体存在、接线漏了"那类假收口。
    """
    import json as _json

    receipts = tmp_path / "rsi_receipts.jsonl"
    monkeypatch.setenv("NEUROVA_RSI_RECEIPTS", str(receipts))
    monkeypatch.setenv("NEUROVA_EVOLUTION_ROLLBACK", str(tmp_path / "rb.json"))
    monkeypatch.setenv("NEUROVA_GOVERNANCE_SETTINGS", str(tmp_path / "gov.json"))
    (tmp_path / "gov.json").write_text(_json.dumps({"rsi_phase": 2}), encoding="utf-8")

    from neurova.evolution.rsi.debt_ledger import ledger_kind
    from neurova.evolution.rsi.orchestrator import RSIOrchestrator
    from tests.unit.evolution.conftest import _default_systems

    systems = _default_systems(PRODUCED_TOOL_MEMORY_PARAMS)
    orchestrator = RSIOrchestrator(
        sleep_system=systems["sleep"], emotion_system=systems["emotion"],
        experience_system=systems["experience"], tool_memory_system=systems["tool_memory"],
    )
    results = orchestrator.apply_optimizations(
        [{"parameter": "tool_memory.decay_rate", "new_value": 0.05}]
    )
    assert results and results[0]["applied"] is True, results
    rows = _receipt_lines(receipts)
    assert rows, "真装配路径没有写下任何回执"
    assert ledger_kind(rows[0]) == "debt_carrying", (
        f"生产链路回执未携带负债两列：{sorted(rows[0])}"
    )
    assert rows[0]["cost"] > 0
