# -*- coding: utf-8 -*-
"""折叠零丢失校验：折叠集合逐条对归档对账（Issue #90 · B6-10 批次 B）。

## 为什么单独一个模块

审计 §5 把 `_last_archived_window_hashes` 记为「只写不读」，并点名它是
"折叠前必须已归档"这条**零丢失判据的唯一物证**却**留下没人校验**。留下而
无人读的字段就是断点：它既不产生读数，也不拦住错误。

本模块是该判据的**唯一消费面**——取数与判定都只在这里，编排器只负责在折叠
发生的那一刻调用它。校验两条互不替代的事实：

1. `not_archived_before_fold`：折叠时刻晚于归档（**时序**）。判据源是编排器的
   归档指纹集；指纹不在其中即说明本轮的折叠发生在归档之前，而池是内容的唯一
   副本——视图里已无原文，丢失不可挽回。
2. `missing`：指纹在池中确实存在（**落地**）。归档集合是"调用过归档"的记账，
   池内是否有该条是另一件事（去重命中、写入咽喉异常等都会让两者分叉）。

改前这两条都不可能校验成立：折叠侧按 `CONVERSATION` 域取指纹，而工具结果
归档在 `TOOL_CALL` 域，必然报假缺失——所以它一直没被读。指纹域收口
（`ContextOrchestrator._windowChunkIdentity` 为唯一派生处）后本模块才有意义。

## 为什么不判红而是上报

池缺席（非 pool 分支）时判据没有落点，如实标记 `PoolAbsent` 而不是静默通过；
编排器把它并进 `get_context_health()["fold_integrity"]`，与 B6-8 的降级读数同
一个面。消费方无需解析日志即可读到 `checked / missing /
not_archived_before_fold / last_error`。
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

#: 违规形态的点名（读数与日志共用同一串，避免两处各写一份措辞）。
REASON_FOLD_BEFORE_ARCHIVE = "FoldBeforeArchive"
REASON_FOLD_LOST = "FoldLost"
REASON_POOL_ABSENT = "PoolAbsent"

#: 空报告的默认形状（单源：编排器的 `_context_health` 初始化与回退都用它）。
EMPTY_REPORT: dict = {
    "checked": 0,
    "missing": 0,
    "not_archived_before_fold": 0,
    "last_error": None,
}


def verifyFoldIntegrity(
    folded_hashes: Optional[Iterable[str]],
    archived_before_fold: Optional[Iterable[str]],
    pool,
) -> dict:
    """校验折叠集合与归档对账，返回读数（不抛异常、不静默）。

    Args:
        folded_hashes: 本轮被折叠消息的归档指纹集合。
        archived_before_fold: 归档侧登记的指纹集合（时序判据的唯一物证）。
        pool: 池实例；None 表示无池（判据无落点，如实标记）。
    """
    folded = tuple(h for h in (folded_hashes or ()) if h)
    report: dict = dict(EMPTY_REPORT)
    report["checked"] = len(folded)

    late = [h for h in folded if h not in set(archived_before_fold or ())]
    report["not_archived_before_fold"] = len(late)

    if late:
        report["last_error"] = (
            f"{REASON_FOLD_BEFORE_ARCHIVE}: {len(late)} 条被折叠内容不在归档集合中"
            f"——折叠发生在归档之前，视图里已无原文（不可挽回）"
        )
    elif pool is None:
        report["last_error"] = f"{REASON_POOL_ABSENT}: 无池，折叠零丢失判据未校验"
    else:
        present = set(getattr(pool, "_by_hash", {}) or {})
        missing = [h for h in folded if h not in present]
        report["missing"] = len(missing)
        if missing:
            report["last_error"] = (
                f"{REASON_FOLD_LOST}: {len(missing)} 条被折叠内容在池中无归档"
                f"（池是唯一副本，折叠后视图中已无原文）"
            )

    if report["last_error"]:
        logger.warning("折叠零丢失校验告警: %s", report["last_error"])
    return report


def verifyOrchestratorFoldIntegrity(orchestrator) -> dict:
    """对编排器的本轮折叠状态取数并校验（判据取数只此一处）。

    判据源——折叠集合与归档指纹集——都从编排器**直接**读，**不在调用点各传一份**：
    两次取值之间的窗口会让校验对象与实际状态错位。两属性在编排器上有类级空默认
    （`frozenset()`），故 `__new__` 直构路径同样取得到。
    """
    return verifyFoldIntegrity(
        orchestrator._last_folded_hashes,
        orchestrator._last_archived_window_hashes,
        getattr(orchestrator, "context_pool", None),
    )
