"""提案生命周期契约（§6-2 阶段①，2026-10-07）——两套提案仓的单一事实源。

背景（对比研究 §6-2 / B.4）：文本进化与 RSI 各有一套"待审提案"生命周期，
转移守卫与审批语义各自内联——同一函数两份实现。本模块收口：

- 状态机（教义第 7 条：先比后合）：两臂的批准都是**原子决定**（批准即生效，
  不存在瞬态"已批准未应用"态）。RSI 侧的 ``ProposalStatus.APPROVED`` 从未
  被任何转移产出（self_improvement_proposer 自注"不经过瞬态 APPROVED"），
  属死状态，随本契约退役。
- 转移合法性：仅 PENDING 可被决定（approve→APPLIED / reject→REJECTED）；
  仅 APPLIED 可回滚（→ROLLED_BACK）；REJECTED/ROLLED_BACK 终态。
- 审批语义：批准必须记录非空审批人（人类评审主 gate）。文本臂此前缺这一层
  ——API 拿到认证身份却没传进 decide，决策不可归因，本契约补齐。

已知分叉（阶段②/③ 收口，登记不隐瞒）：
- 持久化格式与 API 面两套（proposals.json vs proposals/<id>.json）；
- 文本臂历史行以 "approved" 记"批准即生效"，本契约的规范值是 "applied"——
  读路径经 :data:`LEGACY_TEXT_STATUS_ALIASES` 归一，写路径（下一次 decide）
  落规范值；前端按 "pending" 过滤操作列表，不受影响。
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from neurova.core.logger import get_logger

logger = get_logger(__name__)


class ProposalStatus(str, Enum):
    """提案状态（规范值，两臂共用）。

    状态机：PENDING → APPLIED →（可选）ROLLED_BACK；PENDING → REJECTED。
    不存在"已批准未应用"瞬态——两臂的批准都是原子决定。
    """

    PENDING = "pending"
    REJECTED = "rejected"
    APPLIED = "applied"
    ROLLED_BACK = "rolled_back"


DECIDABLE = frozenset({ProposalStatus.PENDING})
ROLLBACKABLE = frozenset({ProposalStatus.APPLIED})
TERMINAL = frozenset({ProposalStatus.REJECTED, ProposalStatus.ROLLED_BACK})

# 文本臂历史行的"批准即生效"字面量 → 规范值（只读兼容，阶段②落盘归一）
LEGACY_TEXT_STATUS_ALIASES = {"approved": ProposalStatus.APPLIED.value}


class ProposalTransitionError(ValueError):
    """非法提案状态转移或非法状态值。"""


def _as_status(current: Any) -> ProposalStatus:
    try:
        return ProposalStatus(current)
    except ValueError:
        raise ProposalTransitionError(f"非法提案状态: {current!r}") from None


def assert_can_decide(current: Any) -> None:
    """仅 PENDING 可被决定（approve→APPLIED / reject→REJECTED）。"""
    if _as_status(current) not in DECIDABLE:
        raise ProposalTransitionError(
            f"非法状态转移：当前状态 {current}，仅 pending 可被决定")


def assert_can_rollback(current: Any) -> None:
    """仅 APPLIED 可被回滚（→ROLLED_BACK）。"""
    if _as_status(current) not in ROLLBACKABLE:
        raise ProposalTransitionError(
            f"非法状态转移：当前状态 {current}，仅 applied 可被回滚")


def require_approver(approver: Any, *, action: str) -> str:
    """人类评审主 gate：决定必须可归因到非空审批人。"""
    cleaned = str(approver or "").strip()
    if not cleaned:
        raise ValueError(f"{action} 必须记录非空审批人（人类评审主 gate）")
    return cleaned


def normalize_legacy_status(status: Any) -> str:
    """历史行状态字面量归一（文本臂 "approved" → 规范 "applied"）。"""
    raw = str(status or "")
    return LEGACY_TEXT_STATUS_ALIASES.get(raw, raw)
