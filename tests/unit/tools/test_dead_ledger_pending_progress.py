# -*- coding: utf-8 -*-
"""T-11：死线台账「待处置」轴的**进度判据**（Issue #310 收口）。

## 为什么需要这道守卫（根因，不是形状）

`test_tool_loop_deadline_disposal.py` 钉住了处置轴的**一致性**：`已接线` / `已删除`
的条目必须逐条在处置批里点名论证；`待处置` 的条目**只要求「仍在原状」**。

这条纪律对**已处置**的条目足够，对**待处置**的条目留了一个缺口：它不要求任何进展。
于是在本仓实际发生过这件事——

    `GoalGate` 的 15 轮硬顶被**四次独立登记**（切片 B 的 live-verify、切片 D、
    切片 C 各自的「登记待办」节），每次都能复现、每次判断都对、每次都写
    「改的是预算语义，属 T-04，不在本片顺手改」。四次都正确，**四次都不红**。
    它最终被收口，是因为用户碰巧点了「下一步」，而不是因为有任何东西拦住了
    下一个人。

**登记 ×N 而不产生红，是「静默遗留」的另一种长相**：台账里有、Issue 里有，
却没有一处判据会在下一个人路过时拦他一下。这不是台账坏了，是台账的
「待处置」这一轴**缺一个进度判据**。

## 判据设计（为什么不是「换个地方写劝告」）

「进展」不能靠人去填（那又是自述）。故本片不引入人工进度字段，只做两件事：

1. **待处置条目必须能回答「归哪一批处置」**（`pendingBatchOf`）：归属写在依据列的
   **结构化标记**里（`〔待处置批：X〕`），值域是一个**有限枚举**（`PENDING_BATCHES`）。
   无归属的 `待处置` = **没人认领的遗留**；归属点名一个不存在的批次 = 与
   `disposal` 轴同一条纪律（人填的值由机器判定）。
2. **同域「已处置批次」不得留下无人认领的待处置**：某一批若已在本域处置过条目
   （该批的处置条目在台账里为 `已接线` / `已删除`），同一域里**不得**再有
   「无批次归属」的待处置条目——那一批摸过这个域，却把它原样留在 `待处置`，
   正是「登记 ×N 无人认领」的机器可读形态。

判据的输入全部来自**已在仓里的事实**：台账的处置列与依据列、处置批论证。
新增的人工字段只有一个（依据列里的批次标记），它一旦填错机器报红。

## 判据口径不在这里复制

一律取 `scripts/ci/tool_loop_deadline_ledger.py`（单一事实源）。
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.ci import tool_loop_deadline_ledger as ledger  # noqa: E402

#: 同域的**已处置批次**（该批已有条目在台账里 `已接线` / `已删除`）。
#: 这些批次「摸过这个域」，故同域不得再有无人认领的待处置条目。
#: 逐条点名是刻意的：批次名是本守卫的输入事实，不是从依据里猜出来的。
WAVES_THAT_TOUCHED_THIS_DOMAIN = {
    "G2": "GoalGate / set_turn_goal / get_turn_goal / goal_max_continuations 已接线",
    "G4": "kill_all 已接线（会话进程随应用关停回收）",
    "切片 D": "max_subagent_depth 已接线（子代理深度成为单源契约）",
    "T-09": "MAX_TOOL_CALL_ROUNDS 已删除（只写不读的护栏残骸）",
}


def _pendingEntries() -> dict:
    return {
        symbol: entry
        for symbol, entry in ledger.readLedger().items()
        if entry["disposal"] == ledger.DISPOSAL_PENDING
    }


def _ownedBatches() -> set:
    """本域待处置条目已经认领的批次（从依据列的标记机器解析）。"""
    return {
        batch
        for entry in _pendingEntries().values()
        if (batch := ledger.pendingBatchOf(entry))
    }


class TestPendingEntriesHaveAnOwner:
    """每个 `待处置` 条目必须能回答「它归哪一批处置」。"""

    def test_pendingBatchEnumIsDefinedInTheLedgerModule(self):
        """批次归属的值域必须由台账模块单源给出，守卫不自己另立一份。"""
        assert hasattr(ledger, "PENDING_BATCHES"), (
            "台账模块未给出「待处置批次」的有限枚举——归属值域无单源，"
            "人填的批次名无从机器判定（这正是本片要补的第一处）"
        )
        assert ledger.PENDING_BATCHES, "批次枚举为空：判据会退化成恒真"
        assert ledger.PENDING_BATCH_ISSUE_SCOPE in ledger.PENDING_BATCHES, (
            "枚举缺少「未分期」哨兵：单条待处置项无从表达「尚未并入任何批」"
        )

    def test_pendingBatchResolutionIsHonest(self):
        """归属解析必须对「无标记」如实返回空——**不兜底猜**，否则判据恒真。

        反向控制：喂一个依据里没有批次标记的条目，必须解析为空。
        """
        synthetic = {"disposal": ledger.DISPOSAL_PENDING, "basis": "某条无批次标记的依据"}
        assert ledger.pendingBatchOf(synthetic) == "", (
            "归属解析对「无批次标记」的条目兜底猜了一个批次——判据会因此恒真"
        )
        marked = {"disposal": ledger.DISPOSAL_PENDING, "basis": "…〔待处置批：T-09〕…"}
        assert ledger.pendingBatchOf(marked) == "T-09", (
            "归属解析认不出结构化标记——判据的另一半（认得对的）缺失"
        )

    def test_everyPendingEntryCarriesAPendingBatch(self):
        """无批次归属的 `待处置` = 没人认领的遗留，必须报红。"""
        offenders = []
        for symbol, entry in _pendingEntries().items():
            batch = ledger.pendingBatchOf(entry)
            if not batch:
                offenders.append(f"{symbol}: 待处置但无批次归属")
            elif batch not in ledger.PENDING_BATCHES:
                offenders.append(
                    f"{symbol}: 批次归属 {batch} 不在有限枚举里（值域 {ledger.PENDING_BATCHES}）"
                )
        assert not offenders, (
            "待处置条目缺少可判定的批次归属（它归哪一批处置？）：\n  "
            + "\n  ".join(offenders)
            + "\n无归属的待处置条目没有任何东西会在下一个人路过时拦他一下——"
            "这正是本片要消灭的「登记 ×N 而不产生红」形态。"
        )


class TestProgressIsNotVacuous:
    """进度判据必须有判别力：同一批摸过这个域，就不该有无人认领的遗留。"""

    def test_ownedBatchesAreSubsetOfRegisteredWaves(self):
        """守卫点名的「已处置批次」必须与台账里的归属值域同词汇——不许自造批次名。"""
        unknown = set(WAVES_THAT_TOUCHED_THIS_DOMAIN) - set(ledger.PENDING_BATCHES)
        assert not unknown, (
            f"本守卫点名了台账枚举里不存在的批次 {sorted(unknown)}——"
            "批次名是单一事实源，守卫不得自造第二份词汇"
        )

    def test_wavesThatTouchedTheDomainOwnTheirPendingRemainder(self):
        """某一批已在同域处置过条目时，同域残留的待处置必须归属到某一批。

        这是本片的核心判据：它把「登记 ×N 无人认领」变成可机器检验的形态——
        一个批次摸过这个域（已有条目接线/退役），同域却有悬空待处置条目，
        说明那一批摸过它却没认领它。
        """
        owned = _ownedBatches()
        touched = set(WAVES_THAT_TOUCHED_THIS_DOMAIN)
        unowned = [
            symbol for symbol, entry in _pendingEntries().items()
            if not ledger.pendingBatchOf(entry)
        ]
        assert not unowned, (
            f"以下批次已在本域处置过条目 {sorted(touched)}，"
            f"但同域仍有无人认领的待处置条目 {unowned}——"
            "它们被反复登记却始终没有批次归属，正是 Issue #310 点名的静默遗留形态"
        )
        assert owned, (
            "本域一个待处置条目都没有归属——若取数坏了（`_pendingEntries` 返回空），"
            "上一条断言会空转通过；这条钉住「确实有归属被解析出来」"
        )

    def test_unownedPendingSymbolsIsTheOneSourceOfTruth(self):
        """守卫不自己遍历台账：无人认领的判定必须走模块单源函数。"""
        assert hasattr(ledger, "unownedPendingSymbols"), (
            "台账模块未提供「无人认领的待处置」判定——守卫若自己遍历，"
            "两处口径必然漂移（教义第 6 条）"
        )
        assert sorted(ledger.unownedPendingSymbols()) == sorted(
            symbol for symbol, entry in _pendingEntries().items()
            if not ledger.pendingBatchOf(entry)
        ), "模块单源函数与守卫的就地判定不一致"

class TestProgressAxisHasTeeth:
    """本轴必须在**合成输入**上真的咬合，否则是「看一眼就判」的第二份自述。"""

    def test_reconcileAxisFiresOnSyntheticUnowned(self):
        """喂一个无归属的待处置条目，纯函数必须报出——证明判据不是恒真。"""
        conflicts = ledger.pendingOwnerConflicts(
            {"幽灵符号": {"disposal": ledger.DISPOSAL_PENDING, "basis": "无批次标记的依据"}}
        )
        assert any(c["symbol"] == "幽灵符号" and c["kind"] == "unowned" for c in conflicts), (
            "合成样本（无归属待处置）未被判为冲突——进度轴失去了判别力，"
            "本片要拦的「登记 ×N 无人认领」形态会照样溜过"
        )

    def test_reconcileAxisFiresOnSyntheticUnknownBatch(self):
        """喂一个点名不存在批次的条目，必须报出——归属值域不可自造。"""
        conflicts = ledger.pendingOwnerConflicts(
            {"幽灵符号": {
                "disposal": ledger.DISPOSAL_PENDING,
                "basis": "依据里点名〔待处置批：T-99〕这个不存在的批次",
            }}
        )
        assert any(
            c["symbol"] == "幽灵符号" and c["kind"] == "unknown_batch"
            and c.get("batch") == "T-99"
            for c in conflicts
        ), "点名不存在批次未被判冲突——人填的归属没有机器判定，与 disposal 轴纪律不符"

    def test_reconcileAxisIsSilentOnTheRealLedger(self):
        """反向：真台账上必须静默——否则守卫会靠「恒红」冒充咬合。"""
        assert ledger.pendingOwnerConflicts() == [], (
            "真台账上进度轴报出冲突：" + repr(ledger.pendingOwnerConflicts())
        )
        problems = ledger.reconcile()
        assert not problems["pending_owner"], (
            f"reconcile() 报出无归属待处置：{problems['pending_owner']}"
        )
        assert not problems["unknown_pending_batch"], (
            f"reconcile() 报出未知批次归属：{problems['unknown_pending_batch']}"
        )
