"""参数表身份守卫 · 上下文经济性入表 · 参数活性读数（Issue #289 · 004）。

票面三条判据（M1–M3）落在此文件；M4（纪元失效）按票面硬约束
**在 D4 拍板前只交设计不交代码**，本文件只钉住它与 003 的接口语义
（`testEpochResetZeroesStatisticsButNotOutstandingDebt` 用的是 003 已落地的
负债面，不引入未拍板的失效触发点）。

## 为什么要先立 M1 守卫

`data/evolution/rsi_receipts.jsonl` 的 262 行真账里，每个 sleep 批次同时写下
两行互相矛盾的记录：

```
{"parameter_path":"sleep.similarity_threshold","old_value":0.7,"new_value":0.72}
{"parameter_path":"sleep.merge_threshold",     "old_value":0.7,"new_value":0.74}
```

同一真实参数两个名字，同批各写一值（14 对 14），永久留在账上。
别名后来收成 property，**但没有任何守卫防止它复发** —— 而本票正要往这张表里
加参数。这是实证理由，不是假想风险。
"""

from __future__ import annotations

import json

PRODUCED_TOOL_MEMORY_PARAMS = {
    "success_bonus": 0.1,
    "failure_penalty": 0.05,
    "decay_rate": 0.01,
    "muscle_memory_threshold": 0.85,
}


def _resolve_landing(host: type, name: str) -> str:
    """把 (宿主类, 属性名) 解析到**物理落点**标识：property 别名要穿透到真实属性。

    这是本文件唯一的落点解析入口 —— 判据本体在 `rsi/parameter_identity.py`，
    测试只用它，不另写一份口径。
    """
    from neurova.evolution.rsi.parameter_identity import resolve_physical_landing

    return resolve_physical_landing(host, name)


# ── 1. 参数表每项必须解析到唯一物理落点 ───────────────────────────
def testParameterTableResolvesToUniquePhysicalLanding():
    """守卫本体：`(宿主类, 物理落点)` 二元组在整张表内唯一。

    现状红：表里没有任何"物理落点"概念，按名字登记。
    """
    from neurova.evolution.rsi.parameter_identity import (
        duplicate_physical_landings,
        iter_parameter_landings,
    )

    landings = list(iter_parameter_landings())
    assert landings, "参数表为空 —— 守卫失去对象"
    duplicates = duplicate_physical_landings()
    assert not duplicates, f"以下参数与同表另一项落到同一个物理落点：{duplicates}"


# ── 2. 构造样本证明守卫不恒绿 ────────────────────────────────────
def testAliasPairIsDetectedAsSameLanding():
    """构造"两个名字 → 同一 property 落点"的表，守卫必须红。

    不给这条构造样本 = 守卫恒绿 = 假守卫。
    """
    from neurova.evolution.rsi.parameter_identity import (
        duplicate_physical_landings,
        iter_parameter_landings,
    )

    class SleepLikeHost:
        similarity_threshold = 0.7

        @property
        def merge_threshold(self) -> float:
            return self.similarity_threshold

        @merge_threshold.setter
        def merge_threshold(self, value: float) -> None:
            self.similarity_threshold = float(value)

    forged = {
        "sleep": [
            {"name": "similarity_threshold", "description": "真身"},
            {"name": "merge_threshold", "description": "别名幻影"},
        ],
    }
    hosts = {"sleep": SleepLikeHost}
    duplicates = duplicate_physical_landings(table=forged, hosts=hosts)
    assert duplicates, "构造的别名对未被判为同一落点 —— 守卫恒绿，是假守卫"
    landings = list(iter_parameter_landings(table=forged, hosts=hosts))
    assert len(landings) == 2
    assert {entry[2] for entry in landings} == {"similarity_threshold"}


# ── 3. 经济性参数入表的前置条件咬合 ──────────────────────────────
def testEconomicParameterEntersTableOnlyAfterDebtAccountingExists():
    """入表前置：该参数必须已有 003 的负债/代价记账，否则不入。

    无账本的参数进表，就是工单 018 `_is_placeholder` 修过的"棘轮奖励自己编辑
    空对象"的第二形态。本判据必须对"记账缺失"真的拒绝，不能恒放行。
    """
    from neurova.evolution.rsi.parameter_identity import (
        debt_accounting_present,
        admits_into_table,
    )

    assert debt_accounting_present() is True, (
        "003 的负债记账必须已落地（`rsi/debt_ledger.py` + 回执 cost/repayment 两列）"
    )
    assert admits_into_table(cost_field="cost", repayment_field="repayment") is True
    # 反向：记账缺失时必须拒绝（否则本判据是恒真装饰）
    assert admits_into_table(cost_field=None, repayment_field=None) is False
    assert admits_into_table(cost_field="cost", repayment_field=None) is False


# ── 4. 宿主缺席沿用 _is_placeholder 口径 ─────────────────────────
def testAbsentHostReturnsEmptyParameterList():
    """缺席宿主返回空参数列表 —— 沿用 `_is_placeholder` 同一口径。

    反证：不得在 apply 端补判空（教义第 1 条禁 consumer-only guard）。
    """
    from neurova.evolution.rsi.integration_manager import RSIIntegrationManager
    from tests.unit.evolution.conftest import ProbeSystem
    from neurova.agent_core import _NullSystem

    manager = RSIIntegrationManager(
        sleep_system=_NullSystem(), emotion_system=_NullSystem(),
        experience_system=_NullSystem(), tool_memory_system=_NullSystem(),
    )
    assert manager.get_placeholder_system_names(), "缺席宿主必须被识别"
    for system_name, params in manager.get_optimizable_parameters().items():
        assert params == [], f"{system_name} 缺席却仍供参数面"
    # 在线宿主照常供参数（正控：避免"全表恒空"被当成通过）
    live = RSIIntegrationManager(
        sleep_system=ProbeSystem("sleep"), emotion_system=ProbeSystem("emotion"),
        experience_system=ProbeSystem("experience"),
        tool_memory_system=ProbeSystem("tool_memory", params=PRODUCED_TOOL_MEMORY_PARAMS),
    )
    assert any(v for v in live.get_optimizable_parameters().values())


# ── 5. 参数活性读数三态不折叠 ────────────────────────────────────
def testParamActivityReadoutSeparatesNoDataSparseAndNeverProposed(tmp_path):
    """`no_data` / `sparse` / `never_proposed` 必须是三个不同的值。

    沿用 `scripts/diagnostics/tool_parallelism_readout.py` 已钉过的
    `no_data ≠ sparse` 纪律，不另立口径。
    """
    from neurova.evolution.rsi.parameter_activity import readParameterActivity

    receipts = tmp_path / "rsi_receipts.jsonl"
    # 一份账里三种形态都要出现：moving（动过 ≥2 次）/ sparse（只动过 1 次）/
    # never_proposed（在表但一次没出现）。
    receipts.write_text(
        "\n".join(json.dumps(row) for row in [
            {"ts": 1.0, "parameter_path": "tool_memory.decay_rate",
             "old_value": 0.01, "new_value": 0.05, "cost": 3, "repayment": 0},
            {"ts": 2.0, "parameter_path": "tool_memory.decay_rate",
             "old_value": 0.05, "new_value": 0.04, "cost": 1, "repayment": 3},
            {"ts": 3.0, "parameter_path": "tool_memory.muscle_memory_threshold",
             "old_value": 0.85, "new_value": 0.83, "cost": 1, "repayment": 0},
        ]) + "\n",
        encoding="utf-8",
    )
    readout = readParameterActivity(receipts)
    states = readout["states"]
    assert states["tool_memory.decay_rate"] == "moving"
    assert states["tool_memory.muscle_memory_threshold"] == "sparse"
    assert states["sleep.base_decay_rate"] == "never_proposed"
    assert "no_data" in readout["vocabulary"]
    assert "sparse" in readout["vocabulary"]
    assert "never_proposed" in readout["vocabulary"]
    # 三个"没结论"的值必须互不相同（折叠就是本仓 success 三态的老病灶）
    assert len({"no_data", "sparse", "never_proposed"}) == 3

    # 账本缺席 ⇒ no_data（不是"全都 never_proposed"：那是拿失明当结论）
    missing = readParameterActivity(tmp_path / "absent.jsonl")
    assert missing["overall"] == "no_data"
    assert missing["states"] == {}


# ── 6. M4 与 003 的接口：纪元归零不清债 ──────────────────────────
def testEpochResetZeroesStatisticsButNotOutstandingDebt(tmp_path, monkeypatch):
    """本票最关键一条：纪元归零**不得**连带清掉 003 的欠账。

    否则"换个任务就免债"会把 M4 变成 003 的反向闸绕过通道。

    票面硬约束：M4 的**失效触发点**在 D4 拍板前不动代码；但"归零不清债"
    这条接口语义由 003 已落地的负债面直接可证，不需引入未拍板的触发点。
    """
    from neurova.evolution.rsi.debt_ledger import RsiDebtLedger

    receipts = tmp_path / "rsi_receipts.jsonl"
    monkeypatch.setenv("NEUROVA_RSI_RECEIPTS", str(receipts))
    ledger = RsiDebtLedger(receipts)
    ledger.record(parameter_path="tool_memory.decay_rate", old_value=0.01,
                  new_value=0.05, cost=40, repayment=0, ts=100.0)
    assert ledger.outstanding_lookup()["outstanding"] == 40

    from neurova.evolution.rsi.parameter_activity import beginNewEpoch

    report = beginNewEpoch(tmp_path)
    # 统计面归零
    assert report["new_epoch"] != report["previous_epoch"]
    # 债跨纪元活下来
    assert ledger.outstanding_lookup()["outstanding"] == 40, "纪元归零把债清了"
    assert ledger.evaluate_next_step().allow is False


# ── 7. 入表必可见 ────────────────────────────────────────────────
def testGovernanceSurfacesShowNewParameters(tmp_path, monkeypatch):
    """入表参数必须在治理面可读 —— 只写入表的参数是断点。"""
    monkeypatch.setenv("NEUROVA_RSI_RECEIPTS", str(tmp_path / "rsi_receipts.jsonl"))
    monkeypatch.setenv("NEUROVA_EVOLUTION_ROLLBACK", str(tmp_path / "rb.json"))
    monkeypatch.setenv("NEUROVA_GOVERNANCE_SETTINGS", str(tmp_path / "gov.json"))
    (tmp_path / "gov.json").write_text(json.dumps({"rsi_phase": 0}), encoding="utf-8")

    from neurova.evolution.rsi.orchestrator import RSIOrchestrator
    from tests.unit.evolution.conftest import _default_systems

    systems = _default_systems(PRODUCED_TOOL_MEMORY_PARAMS)
    orchestrator = RSIOrchestrator(
        sleep_system=systems["sleep"], emotion_system=systems["emotion"],
        experience_system=systems["experience"], tool_memory_system=systems["tool_memory"],
    )
    status = orchestrator.get_status()
    assert "parameter_activity" in status, f"治理状态面缺参数活性读数：{sorted(status)}"
    vocabulary = status["parameter_activity"]["vocabulary"]
    assert "never_proposed" in vocabulary
