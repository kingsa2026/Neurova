# -*- coding: utf-8 -*-
"""RSI 回执负债账本 —— 给只记功的增益史补上"欠了多少"。

本模块是 RSI 回执**负债语义**的唯一事实源（Issue #289 · 003）。

## 为什么需要它

`rsi_receipts.jsonl` 有 262 行真账，但行形态只有
`{ts, parameter_path, old_value, new_value}`：它只能证明"我做过有益的事"，
不能证明"我没连续挥霍"。单向账本会让棘轮**系统性偏向多动作者** ——
多动就多几条被记录的增益。

## 与 002 的关系（禁止第二套口径）

- **代价口径**引用 `context.compression_economics` 的 `cost` 字段语义，
  本模块不另立一份"代价"定义；
- **不动作原因**与 002 共用同一命名体系（值域必须在 `CompressionAction` 内，
  由 `tests/unit/evolution/test_rsi_debt_ledger.py::testDebtReasonSharesEnumWithCompressionGate`
  恒定咬合）。同域事实不得开第二套枚举（AGENTS.md 修复教义第 6 条）。

## 三态不可折叠

存量行**没有** `cost` 列，与"代价实测为 0"是两个不同的态：

- `debt_carrying`：本行带代价/偿还两列；
- `legacy_unpriced`：本行来自旧写入方，代价**未知** —— 不是 0，也不是欠账。

把两者折叠，正是本仓在 `success` 三态上已经修过的同一病灶。

## 丢行语义（票面前置）

写入方 `_write_optimization_receipt` 自陈"写失败仅告警不影响主流程"。
把闸建在允许丢行的账本上 = 闸可以靠"把账写丢"绕过。故本模块显式定义：
**债记不下时保守拒绝本次动作**（安全侧优先），且降级必须产生可归因读数。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

#: 回执/负债账本的落点开关（与 `_write_optimization_receipt` 同一枚 env，
#: 单一事实源：负债不另开第二个落点）。
RECEIPTS_ENV = "NEUROVA_RSI_RECEIPTS"

#: 负债回执行的**列名声明**（004 入表前置条件读它，不另写一份字面量）。
RECEIPT_FIELDS = frozenset({
    "ts", "parameter_path", "old_value", "new_value", "cost", "repayment",
})

# ── 行形态分类（互斥穷举）────────────────────────────────────────
LEDGER_KIND_DEBT_CARRYING = "debt_carrying"
LEDGER_KIND_LEGACY_UNPRICED = "legacy_unpriced"

# ── 负债侧不动作原因（值域必须落在 002 的 CompressionAction 内）──
# `debt_uncleared` 对应 002 的 `uneconomical`：一笔代价未清就再动，
# 与"省出的补不回本次代价"是同一类判定。这里只登记**原因名 → 002 值**的映射，
# 不新造词表 —— 同域事实不得开第二套枚举（教义第 6 条）。
DEBT_REASONS = frozenset({
    "debt_uncleared",
    "ledger_write_failed",
    "debt_clear",
})

#: 负债侧原因名 → 002 命名体系内的值（唯一一份映射，守卫逐条咬合）。
DEBT_REASON_TO_ACTION = {
    "debt_uncleared": "uneconomical",
    "ledger_write_failed": "insufficient_data",
    "debt_clear": "economical",
}

# ── 回滚处置（静默消失被显式禁止）────────────────────────────────
DISPOSITION_SETTLED = "settled"
DISPOSITION_CARRIED_FORWARD = "carried_forward"
ROLLBACK_DISPOSITIONS = frozenset({DISPOSITION_SETTLED, DISPOSITION_CARRIED_FORWARD})


def ledger_kind(record: Dict[str, Any]) -> str:
    """判定一行回执的形态：带代价两列，还是来自旧写入方的未定价行。

    **字段缺失与值为 0 必须分辨成两个态**：`"cost" in record` 而非 `record.get("cost")`。
    用后者会把 `{"cost": 0}` 与 `{}` 读成同一个值，正是本仓在 `success` 三态上
    修过的折叠病灶。
    """
    if "cost" in record and "repayment" in record:
        return LEDGER_KIND_DEBT_CARRYING
    return LEDGER_KIND_LEGACY_UNPRICED


def debt_fields_declared() -> tuple:
    """回执行声明的负债两列（供 004 的入表前置条件单源读取）。"""
    return ("cost" if "cost" in RECEIPT_FIELDS else None,
            "repayment" if "repayment" in RECEIPT_FIELDS else None)


@dataclass(frozen=True)
class DebtVerdict:
    """反向闸的结论：放不放行 + 原因 + 未清余额。"""

    allow: bool
    reason: str
    outstanding: int


@dataclass
class RsiDebtLedger:
    """挂在 `rsi_receipts.jsonl` 上的负债面（单一事实源，不新增第二份账本文件）。

    账仍是那一份 append-only JSONL；本类只做两件事：
    1. 写入时把 `cost` / `repayment` 两列带上；
    2. 读取时把"欠账是否已清"算出来，供反向闸判据使用。
    """

    path: Path
    _write_failure: bool = field(default=False, init=False, repr=False)
    _last_write_failure: Optional[str] = field(default=None, init=False, repr=False)

    def force_write_failure_for_test(self, enabled: bool) -> None:
        """测试注入口：让下一次写入必定失败，以实证丢行语义走安全侧。

        生产路径没有这个开关 —— 它只服务"丢行不得静默放行"这条判据的证伪。
        """
        self._write_failure = bool(enabled)

    def last_write_failure_reason(self) -> Optional[str]:
        """最近一次写入失败的原因值（`None` = 没失败过）。"""
        return self._last_write_failure

    # ── 写侧 ────────────────────────────────────────────────────
    def record(
        self,
        *,
        parameter_path: str,
        old_value: Any,
        new_value: Any,
        cost: int,
        repayment: int,
        ts: Optional[float] = None,
    ) -> bool:
        """追加一行带负债语义的回执。

        Returns:
            bool: 是否真落盘。`False` 时 `last_write_failure_reason()` 给出原因，
            且后续 `evaluate_next_step()` **必定不放行**（安全侧优先）。
        """
        import json as _json
        import time as _time

        if self._write_failure:
            self._last_write_failure = DEBT_WRITE_FAILED
            logger.warning("负债回执写入失败（注入）：放弃本行，债务按未清处置")
            return False

        payload = {
            "ts": _time.time() if ts is None else float(ts),
            "parameter_path": parameter_path,
            "old_value": old_value,
            "new_value": new_value,
            "cost": int(cost),
            "repayment": int(repayment),
        }
        try:
            target = Path(self.path)
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(target, "a", encoding="utf-8") as handle:
                handle.write(_json.dumps(payload, ensure_ascii=False) + chr(10))
            return True
        except Exception as exc:  # noqa: BLE001 - 落盘失败不抛，但必须留可归因读数
            self._last_write_failure = DEBT_WRITE_FAILED
            logger.warning("负债回执写入失败: %s", exc)
            return False

    # ── 读侧 ────────────────────────────────────────────────────
    def list_rows(self) -> List[Dict[str, Any]]:
        """读回全部回执行（损坏行跳过，不静默吞掉整份账）。"""
        import json as _json

        target = Path(self.path)
        if not target.exists():
            return []
        rows: List[Dict[str, Any]] = []
        for raw in target.read_text(encoding="utf-8").splitlines():
            if not raw.strip():
                continue
            try:
                parsed = _json.loads(raw)
            except ValueError:
                logger.warning("回执行不可解析，跳过一行（账本其余部分照读）")
                continue
            if isinstance(parsed, dict):
                rows.append(parsed)
        return rows

    def outstanding_lookup(self) -> Dict[str, Any]:
        """未清余额与两个行形态的计数（三态不折叠）。

        余额口径（单源，本模块内只此一处）：

            outstanding = Σ(各行 cost) − Σ(各行 repayment)

        即 `repayment` 记的是"**对账上既往欠账的偿还量**"，不是本行自身净额 ——
        否则一行 `cost=40, repayment=40` 会被算成"零欠账"，等于允许
        "一边欠一边说自己还了"。行级净额与账级余额是两件事，不合并。

        `legacy_unpriced` 行只计数不计额：它的代价**未知**，不是 0。
        """
        priced = 0
        unknown = 0
        gross_cost = 0
        repaid = 0
        settled = 0
        for row in self.list_rows():
            kind = ledger_kind(row)
            if kind == LEDGER_KIND_LEGACY_UNPRICED:
                unknown += 1
                continue
            priced += 1
            if row.get("debt_disposition") == DISPOSITION_CARRIED_FORWARD:
                # 显式转挂：该行的代价**原样留账**，不得因处置动作而消失。
                settled += 0
                gross_cost += max(0, int(row.get("cost") or 0))
                repaid += max(0, int(row.get("repayment") or 0))
                continue
            if row.get("debt_disposition") == DISPOSITION_SETTLED:
                # 已结清的清偿行（cost=0 / repayment=余额）：它**就是**清偿动作本身，
                # 计入 `settled_rows` 留痕；余额由它的 repayment 抵扣，不再重复计额。
                settled += 1
                repaid += max(0, int(row.get("repayment") or 0))
                continue
            gross_cost += max(0, int(row.get("cost") or 0))
            repaid += max(0, int(row.get("repayment") or 0))
        return {
            "outstanding": max(0, gross_cost - repaid),
            "priced_rows": priced,
            "unknown_rows": unknown,
            "settled_rows": settled,
        }

    def evaluate_next_step(self) -> DebtVerdict:
        """反向闸：上一次动作的代价未清 ⇒ 本次不动作并给出原因。

        判据次序（安全侧先于一切）：
            1. 最近一次写入失败 ⇒ 不放行（`ledger_write_failed`：账记不下就不敢动）；
            2. 未清余额 > 0 ⇒ 不放行（`debt_uncleared`）；
            3. 其余 ⇒ 放行（`debt_clear`）。
        """
        if self._last_write_failure is not None:
            return DebtVerdict(False, DEBT_WRITE_FAILED, -1)
        lookup = self.outstanding_lookup()
        if lookup["outstanding"] > 0:
            return DebtVerdict(False, DEBT_UNCLEARED, lookup["outstanding"])
        return DebtVerdict(True, DEBT_CLEAR, 0)

    # ── 回滚处置 ────────────────────────────────────────────────
    def settle_on_rollback(self, *, reason: str, ts: Optional[float] = None) -> str:
        """回滚发生时处置在途债务：结清，或显式转挂 —— 不许静默消失。

        处置以**一行带 `debt_disposition` 的回执**留痕：回滚让本次改动被撤销，
        该笔代价已由"撤销"本身付清，故取结清（`repayment` = 在途余额）。
        留不下这条处置，回滚就制造了一笔"无主欠账"（票面点名的失败形态）。

        账仍是同一份 append-only JSONL：`debt_disposition` 是**可选列**，
        只在这一行上出现，不改行形态分类（`ledger_kind` 只看 cost/repayment）。
        """
        lookup = self.outstanding_lookup()
        outstanding = lookup["outstanding"]
        disposition = DISPOSITION_SETTLED
        ok = self.record(
            parameter_path=ROLLBACK_SETTLE_PATH,
            old_value=outstanding,
            new_value=0,
            cost=0,
            repayment=outstanding,
            ts=ts,
        )
        if not ok:
            # 留痕失败 ⇒ 诚实报"转挂"，绝不报"已结清"（安全侧优先）。
            return DISPOSITION_CARRIED_FORWARD
        self.mark_last_disposition(disposition, reason=reason, ts=ts)
        return disposition

    def mark_last_disposition(self, disposition: str, *, reason: str, ts: Optional[float] = None) -> bool:
        """给刚追加的那一行打上处置标记（账本形态不变，不新增第二种行）。"""
        import json as _json

        if disposition not in ROLLBACK_DISPOSITIONS:
            raise ValueError(f"未知的债处置值：{disposition!r}")
        target = Path(self.path)
        rows = self.list_rows()
        if not rows:
            return False
        rows[-1]["debt_disposition"] = disposition
        rows[-1]["rollback_reason"] = reason
        try:
            target.write_text(
                "".join(_json.dumps(r, ensure_ascii=False) + chr(10) for r in rows),
                encoding="utf-8",
            )
            return True
        except Exception as exc:  # noqa: BLE001 - 留痕失败不抛，但读数可见
            logger.warning("债处置留痕失败: %s", exc)
            return False


# ── 模块级常量（供静态同源守卫读取）──────────────────────────────
DEBT_WRITE_FAILED = "ledger_write_failed"
DEBT_UNCLEARED = "debt_uncleared"
DEBT_CLEAR = "debt_clear"
ROLLBACK_SETTLE_PATH = "__rollback__"


def resolve_debt_ledger() -> Optional["RsiDebtLedger"]:
    """按 env 解析负债账本；未配置 `NEUROVA_RSI_RECEIPTS` 时返回 `None`。

    返回 `None` 表示**没有账**（未开账 / 单测零 IO 约定），与"账上欠着"
    是两个不同的态 —— 调用方不得把前者读成后者。

    账本与回执**同一条路径**：负债长在 `rsi_receipts.jsonl` 上，
    不新增第二份账本文件（票面禁区）。
    """
    import os as _os

    env_path = _os.environ.get(RECEIPTS_ENV)
    if not env_path:
        return None
    return RsiDebtLedger(Path(env_path))
