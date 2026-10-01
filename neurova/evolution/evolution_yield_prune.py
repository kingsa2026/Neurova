"""增益维度剪枝提案 — 三证合取的技能退役建议（只产计划，绝不执行）。

RRSI 对齐：组件"近 n 轮无正增益"就该连同其已接入机制一起被提请移除。
Neurova 的对应物是技能级剪枝——但**只产提案**，审批与执行走既有
ConsolidationPlanStore / skill_pool_api 审批面，不新造第二套通道。

三证合取（任一缺失即不产出，宁勿误杀）：
  1. 编辑历史台账（EvolutionLedger）：最近 streak_n 条候选全部被评测拒绝
     ——闸拒绝（constraints:/leak: 前缀）是提案质量问题，不算无增益证据；
  2. 使用归因读数（usage_fn）：有真实使用量（times_used 达标）且零正贡献；
  3. 未受保护（is_protected_fn）：pinned 等保护语义全绕开；判据故障视为
     受保护（fail-closed）。
"""

from __future__ import annotations

from typing import Callable, Optional

from neurova.core.logger import get_logger
from neurova.evolution.eval.history_ledger import GATE_REASON_PREFIXES

logger = get_logger(__name__)

PRUNE_REASON = "evolution_yield_exhausted"
PRUNE_BASIS = "evolution_yield"


def propose_evolution_prune_candidates(
    *,
    ledger,
    usage_fn: Callable[[str], dict],
    plan_store,
    is_protected_fn: Optional[Callable[[str], bool]] = None,
    streak_n: int = 5,
    min_times_used: int = 1,
) -> list[dict]:
    """扫描台账产出剪枝提案；返回本次新产的计划（同时 upsert 进待审仓）。"""
    plans: list[dict] = []
    for key in ledger.keys():
        if is_protected_fn is not None:
            try:
                if is_protected_fn(key):
                    continue
            except Exception as e:  # noqa: BLE001 - 保护判据故障 = 宁勿误杀
                logger.debug("剪枝保护判据失败 %s, 跳过: %s", key, e)
                continue

        records = ledger.tail(key, streak_n)
        if len(records) < streak_n:
            continue
        if any(r.get("accepted") for r in records):
            continue
        if any(str(r.get("reject_reason", "")).startswith(GATE_REASON_PREFIXES)
               for r in records):
            continue

        try:
            usage = dict(usage_fn(key) or {})
        except Exception as e:  # noqa: BLE001 - 归因读数故障 = 证据缺失，不剪
            logger.debug("剪枝归因读数失败 %s, 跳过: %s", key, e)
            continue
        times_used = int(usage.get("times_used", 0))
        positive = int(usage.get("positive", 0))
        if times_used < max(1, int(min_times_used)) or positive > 0:
            continue

        plan = {
            "umbrella": key,
            "absorbed": [],
            "reason": PRUNE_REASON,
            "basis": PRUNE_BASIS,
            "quality": {
                "reject_streak": streak_n,
                "streak_reasons": sorted({str(r.get("reject_reason") or "")
                                          for r in records if r.get("reject_reason")}),
                "usage": usage,
            },
        }
        plan_store.upsert([plan])
        plans.append(plan)
        logger.info("增益剪枝提案: %s（近 %d 轮改进全被拒且零正贡献，待审）",
                    key, streak_n)
    return plans
