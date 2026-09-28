# -*- coding: utf-8 -*-
"""处置批的**存量读数**必须由台账现算，不许手填（Issue #310）。

## 为什么要这一条（根因，不是形状）

`待处置` 轴上一片补了**归属**（每个待处置条目必须能回答「归哪一批」），于是
「登记 ×N 而不产生红」这个形态被拦住了。但归属只解决「谁认领」，不解决
「推到哪了」：

    18 条待处置、分属 6 个批次之后，「T-09 还剩几条」只能靠 grep 依据列数出来。
    而这个数正是「批推进一步」这件事的全部验收线 —— 它一靠人手复述，
    下一轮接手的人就只能信上一轮的话。

手填的状态位就是第二份自述（与 `登记 ×N 而不产生红` 同一条根因：机器不看，
所以填错不红）。故本片补的是**读数**，不是状态位：

- `batchProgress()` 从台账现算每批的存量（判据是「该批次名下一条待处置都不剩」）；
- `batchProgressLine()` 是同一读数的一行机器可读形态，进 `main()` 的正常输出 ——
  即「跑一次器械就能看见进度」，不再需要任何人复述。

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


def _pendingEntries() -> dict:
    return {
        symbol: entry
        for symbol, entry in ledger.readLedger().items()
        if entry["disposal"] == ledger.DISPOSAL_PENDING
    }


class TestBatchProgressIsComputedNotDeclared:
    """批次进度必须是**现算的事实**：台账改一条，读数立刻跟着动。"""

    def test_everyBatchInTheEnumHasAProgressReading(self):
        """值域里的每个批次都必须在读数里出现——缺一个就是一条读不到的存量。"""
        missing = set(ledger.PENDING_BATCHES) - set(ledger.batchProgress())
        assert not missing, (
            f"以下批次的存量读不出来（读数里没有这一项）：{sorted(missing)}——"
            "推进一步之前先得能看见还剩多少条"
        )

    def test_progressMatchesTheLedgerRowByRow(self):
        """读数与台账逐行同源：归属标记解析出的条目集合必须完全一致。

        这条是**反向控制**：若读数改成自己攒一份计数（而不是从依据列现算），
        它与台账就会各说各话，而两边都不会红。
        """
        progress = ledger.batchProgress()
        expected: dict = {}
        for symbol, entry in _pendingEntries().items():
            batch = ledger.pendingBatchOf(entry)
            expected.setdefault(batch, []).append(symbol)
        for batch, bucket in progress.items():
            assert bucket["pending"] == sorted(expected.get(batch, [])), (
                f"{batch}: 读数 {bucket['pending']} 与台账现算 "
                f"{sorted(expected.get(batch, []))} 不一致"
            )
            assert bucket["total"] == len(expected.get(batch, [])), (
                f"{batch}: 计数 {bucket['total']} 与台账条目数不符"
            )

    def test_closedIsNotVacuous(self):
        """「已清」必须由「一条待处置都不剩」推出，不许是恒真。

        合成输入自证：喂一个仍有待处置的批次，`closed` 必须是 False；
        喂一个已无待处置的批次，`closed` 才是 True。
        """
        progress = ledger.batchProgress()
        for batch, bucket in progress.items():
            assert bucket["closed"] == (bucket["total"] == 0), (
                f"{batch}: closed={bucket['closed']} 而存量 {bucket['total']} 条——"
                "「已清」不是由存量推出的，读数失去判别力"
            )

    def test_everyBatchHasAHumanReadableLabel(self):
        """每个批次必须有人类可读名字：裸代号（`T-09=9 条待处置`）读不出它在干什么。"""
        for batch in ledger.PENDING_BATCHES:
            label = ledger.BATCH_LABELS.get(batch)
            assert label, f"批次 {batch} 没有可读标签——标签与值域是同一单源，必须两处同批"
        assert set(ledger.BATCH_LABELS) == set(ledger.PENDING_BATCHES), (
            "批次标签与批次值域不是同一集合——两边各写一份就必然漂移"
        )

    def test_progressLineIsMachineReadable(self):
        """一行读数必须含每个批次的名与态，供 `main()` 输出与人工核对。"""
        line = ledger.batchProgressLine()
        for batch in ledger.PENDING_BATCHES:
            assert batch in line, f"一行读数里没有批次 {batch}：{line!r}"
        assert "待处置" in line, f"一行读数读不出存量形态：{line!r}"
