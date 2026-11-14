"""V2 保留分支一等对象 —— 分支引导进化的池管理（2026-11-14）。

对照档：docs/08-research/videoevolve_vs_neurova_harness_evolution_comparison_2026-11-14.md §3-V2。
论文（arXiv 2610.01766）Branch-Guided Harness Evolution：champion 之外，有希望的
非冠军分支**保留为后续精炼的父代**，晋升（promoted）或重试额度耗尽（exhausted）
后重置——「别急着砍第二名」。

本模块只做**簿记与生命周期**，不做任何评测/判定：谁被保留、谁晋升、谁退役。
池容量由调用方（evolveRecursive 的 pool_size）把关，本池不设上限闸。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


#: 分支状态词值单源（审计面/报告面都取这里，不各写字面量）。
BRANCH_ACTIVE = "active"
BRANCH_PROMOTED = "promoted"
BRANCH_EXHAUSTED = "exhausted"


@dataclass
class EvolutionBranch:
    """一条保留分支：递归池里的一个候选谱系。

    branch_id   — 池内唯一身份（`br1`、`br2`…，确定性递增）；
    text        — 该谱系当前正文（下一轮变异的父代）；
    score       — 入池时的评测分（holdout 或 tune，调用方口径）；
    parent_id   — 母分支 id（种子分支为空串）；
    epoch_created — 入池的轮次（种子 = 0）；
    retries_left  — 剩余重试额度：颗粒无收一轮扣一次，扣穿即退役；
    status      — active / promoted / exhausted；
    promoted_epoch — 后代成为新 champion 的轮次（未晋升为 None）。
    """

    branch_id: str
    text: str
    score: float = 0.0
    parent_id: str = ""
    epoch_created: int = 0
    retries_left: int = 0
    status: str = BRANCH_ACTIVE
    promoted_epoch: Optional[int] = None

    def to_dict(self) -> dict:
        return {
            "branch_id": self.branch_id,
            "parent_id": self.parent_id,
            "epoch_created": self.epoch_created,
            "status": self.status,
            "retries_left": self.retries_left,
            "score": round(float(self.score), 6),
            "promoted_epoch": self.promoted_epoch,
            "text_head": self.text[:60],
        }


class BranchPool:
    """保留分支池：只管身份与生命周期，不评测、不判定。

    retry_budget — 每条分支的**额外**重试轮数（0 = 颗粒无收一轮即退役，
    与既有递归行为逐字一致；>0 = 保留到额度耗尽）。
    """

    def __init__(self, *, retry_budget: int = 0):
        self._retryBudget = max(0, int(retry_budget))
        self._branches: dict[str, EvolutionBranch] = {}
        self._order: list[str] = []
        self._counter = 0

    def _nextId(self) -> str:
        self._counter += 1
        return f"br{self._counter}"

    def seed(self, text: str, score: float = 0.0) -> EvolutionBranch:
        """种子分支（递归起点的正文）。"""
        branch = EvolutionBranch(
            branch_id=self._nextId(), text=text, score=float(score),
            parent_id="", epoch_created=0, retries_left=self._retryBudget,
            status=BRANCH_ACTIVE)
        self._branches[branch.branch_id] = branch
        self._order.append(branch.branch_id)
        return branch

    def retain(self, *, text: str, score: float, parent_id: str,
               epoch: int) -> EvolutionBranch:
        """新分支入池（母分支的幸存后代），重试额度重置。"""
        if parent_id not in self._branches:
            raise KeyError(f"母分支不存在: {parent_id}")
        branch = EvolutionBranch(
            branch_id=self._nextId(), text=text, score=float(score),
            parent_id=parent_id, epoch_created=max(0, int(epoch)),
            retries_left=self._retryBudget, status=BRANCH_ACTIVE)
        self._branches[branch.branch_id] = branch
        self._order.append(branch.branch_id)
        return branch

    def get(self, branch_id: str) -> Optional[EvolutionBranch]:
        return self._branches.get(branch_id)

    def active(self) -> list[EvolutionBranch]:
        """当前应被精炼的分支（按入池序，确定性）。"""
        return [self._branches[i] for i in self._order
                if self._branches[i].status == BRANCH_ACTIVE]

    def hasActive(self) -> bool:
        return any(b.status == BRANCH_ACTIVE for b in self._branches.values())

    def exhaust(self, branch_id: str) -> None:
        """强制退役（池容量让位等场景）：无论剩余额度，即刻出局——审计面上
        与「额度自然耗尽」同词值，退役原因由调用方的轨迹记录承担。"""
        branch = self._branches.get(branch_id)
        if branch is None:
            raise KeyError(f"分支不存在: {branch_id}")
        branch.status = BRANCH_EXHAUSTED

    def markPromoted(self, branch_id: str, epoch: int) -> None:
        """晋升：该分支的后代成为新 champion——分支光荣退役（重置语义）。"""
        branch = self._branches.get(branch_id)
        if branch is None:
            raise KeyError(f"分支不存在: {branch_id}")
        branch.status = BRANCH_PROMOTED
        branch.promoted_epoch = max(0, int(epoch))

    def markFailed(self, branch_id: str) -> None:
        """颗粒无收：扣一次重试额度，扣穿即退役。"""
        branch = self._branches.get(branch_id)
        if branch is None:
            raise KeyError(f"分支不存在: {branch_id}")
        branch.retries_left -= 1
        if branch.retries_left < 0:
            branch.status = BRANCH_EXHAUSTED

    def all(self) -> list[EvolutionBranch]:
        """全部分支（按入池序）——审计面用。"""
        return [self._branches[i] for i in self._order]

    def to_dict(self) -> list[dict]:
        return [b.to_dict() for b in self.all()]
