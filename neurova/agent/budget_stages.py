"""分段预算提醒（HN4/HC4，2026-11-13）。

来历：HarnessPro 对照（docs/08-research/harnesspro_vs_neurova_cost_aware_
harness_rsi_comparison_2026-11-13.md）断点 HN4——本仓门控预算是全局单一
配置（token_budget/max_loop_rounds 对所有任务一视同仁），只有「到点 TERMINATE」
的硬悬崖，没有「分段劝、最后拦」的梯度。

本模块提供**纯文本分段提醒**（借鉴 HarnessPro 的 economy/strict/finalize
三段形态，文案与阈值独立实现）：

- economy：到收敛段——批量合并独立检查、停止复述；
- strict：停止面状探索——只处理与当前失败/交付直接相关的证据；
- finalize：预算将尽——完成实现、聚焦校验、收尾，不扩大范围。

纪律：
- **只注入文本，不终止**——硬停止仍由既有 IterationGate/TokenBudgetGate/
  DoomLoopGate/GoalGate 单点执法，本模块不造第二把 TERMINATE（教义第 6 条）；
- 阈值随执行档位（agent_limits_settings.EXEC_PROFILES）派生，同源不手抄；
- 提醒作为 user 消息追加在工具结果之后（不改写历史消息——保 provider 的
  prompt cache 前缀命中）；
- kill-switch：NEUROVA_BUDGET_STAGES=off（默认开——纯文本引导，风险低）。
"""

from __future__ import annotations

import os
from typing import Dict, Tuple

#: 各档位的分段比例（economy/strict/finalize 占 max_rounds 的比例）与复提醒周期。
#: lite 收得早（探索段短），heavy 放得开（探索段长）——与 EXEC_PROFILES 的
#: 预算方向一致，由测试钉住「heavy.economy > lite.economy」。
_STAGE_RATIOS: Dict[str, Tuple[float, float, float, int]] = {
    "lite": (0.30, 0.50, 0.70, 3),
    "standard": (0.40, 0.60, 0.80, 4),
    "heavy": (0.50, 0.70, 0.85, 6),
}

_ECONOMY_TEXT = (
    "【预算提示】已进入收敛段：请批量合并独立的读取/校验，停止复述过程，"
    "不要重复已经完成的检查。"
)
_STRICT_TEXT = (
    "【预算提示】请停止面状探索：只处理与当前失败或交付直接相关的证据，"
    "为最终校验保留预算。"
)
_FINALIZE_TEXT = (
    "【预算提示】工具预算即将耗尽：请完成当前实现、做一次聚焦校验并收尾，"
    "不要继续扩大范围。"
)


def stagesEnabled() -> bool:
    """分段提醒总开关：NEUROVA_BUDGET_STAGES=off 关闭，默认开。"""
    return (os.environ.get("NEUROVA_BUDGET_STAGES") or "on").strip().lower() != "off"


def activeProfile() -> str:
    """当前执行档位——任务级（turn ContextVar，R3/R6）优先，回落部署级。

    两条都故障时回 standard（fail-open）。
    """
    try:
        from neurova.agent.turn_profile import getTurnProfile

        turn_profile = getTurnProfile()
        if turn_profile:
            return turn_profile
    except Exception:  # noqa: BLE001
        pass
    try:
        from neurova.security.agent_limits_settings import active_exec_profile

        return active_exec_profile()
    except Exception:  # noqa: BLE001 - 配置面故障回退标准档（fail-open）
        return "standard"


def stageThresholds(max_rounds: int, profile: str = "") -> Dict[str, int]:
    """从轮次预算派生三段阈值（向上取整、严格递增、不越过 max_rounds）。

    max_rounds 过小（如 1）时三段全部夹到安全值——提醒退化为不发声，
    终止仍由既有门控负责。
    """
    name = profile or activeProfile()
    ratios = _STAGE_RATIOS.get(name, _STAGE_RATIOS["standard"])
    budget = max(0, int(max_rounds or 0))
    economy = max(1, int(budget * ratios[0])) if budget else 1
    strict = max(economy + 1, int(budget * ratios[1])) if budget else 1
    finalize = max(strict + 1, int(budget * ratios[2])) if budget else 1
    if budget:
        economy = min(economy, budget)
        strict = min(max(strict, economy + 1), max(budget - 1, economy + 1))
        finalize = min(max(finalize, strict + 1), max(budget, strict + 1))
    return {
        "economy": economy,
        "strict": strict,
        "finalize": finalize,
        "reminder": int(ratios[3]),
    }


def budgetStageGuidance(tool_rounds: int, max_rounds: int, profile: str = "") -> str:
    """按当前轮次返回分段提醒文本（不发声返回空串）。

    触发规则：economy 段在到达那一轮提醒一次；strict/finalize 段在到达时
    与之后每 reminder 轮复提醒（与 HarnessPro 的「到达＋周期复提醒」同形态，
    参数与文案独立）。
    """
    if not stagesEnabled():
        return ""
    rounds = int(tool_rounds or 0)
    if rounds <= 0:
        return ""
    t = stageThresholds(max_rounds, profile)
    if rounds == t["economy"]:
        return _ECONOMY_TEXT
    if rounds == t["finalize"] or (
            rounds > t["finalize"] and (rounds - t["finalize"]) % t["reminder"] == 0):
        return _FINALIZE_TEXT
    if rounds == t["strict"] or (
            rounds > t["strict"] and (rounds - t["strict"]) % t["reminder"] == 0):
        return _STRICT_TEXT
    return ""


__all__ = [
    "stagesEnabled",
    "stageThresholds",
    "budgetStageGuidance",
    "activeProfile",
]
