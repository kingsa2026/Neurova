# -*- coding: utf-8 -*-
"""本轮目标声明（LoopGoal）——目标验收链的**单一输入契约**。

职责边界
========
只做一件事：把"调用方怎么给目标"归一成一个不可变对象。

- 目标不是本模块产生的，本模块也不存目标：**唯一事实源是轮次槽**
  （`neurova.core.turn_context` 的 `set_turn_goal` / `get_turn_goal`）。
  写入方只有轮次装配处（会话 metadata / 工具编排入口），读侧只有 Loop 出口求值。
- 非法输入返回 `None`，**不猜、不兜默认目标**：验收链的 fail-closed 边界是
  "没有可信目标就不做验收"（无目标一律不判定，不产生额外 LLM 支出）。

命名刻意避开心跳任务的 `set_goal`（`memory_layer` 的 SelfManagerModule，
语义无关），也不沿用历史上零写入点的 `agent._goal` 裸属性。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple
import time


@dataclass(frozen=True)
class LoopGoal:
    """一次会话内的目标声明。

    frozen：目标变更走整体替换而不是就地改，使门控读到的快照与判定输入
    在同一时间点一致；否则"边判定边改目标"会让 verdict 归属到新目标上。
    """

    id: str
    statement: str
    successCriteria: Tuple[str, ...] = ()
    sourceTurnId: Optional[str] = None
    createdAt: float = field(default_factory=time.time)

    def asDict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "statement": self.statement,
            "successCriteria": list(self.successCriteria),
            "sourceTurnId": self.sourceTurnId,
        }


def _criteriaOf(raw: Any) -> Tuple[str, ...]:
    if isinstance(raw, str):
        text = raw.strip()
        return (text,) if text else ()
    if isinstance(raw, (list, tuple)):
        return tuple(str(item).strip() for item in raw if str(item or "").strip())
    return ()


def normalizeGoal(raw: Any) -> Optional[LoopGoal]:
    """把 dict / LoopGoal / 纯字符串 / None 归一为 Optional[LoopGoal]。

    空声明（无 statement 且无条目）返回 None——"声明了但没有内容"与"没声明"
    在验收链上是同一件事：都不该付一次判定调用。
    """
    if raw is None:
        return None
    if isinstance(raw, LoopGoal):
        return raw
    if isinstance(raw, str):
        text = raw.strip()
        return LoopGoal(id=_stableGoalId(text), statement=text) if text else None
    if isinstance(raw, dict):
        statement = str(raw.get("statement") or raw.get("description") or "").strip()
        criteria = _criteriaOf(raw.get("successCriteria") or raw.get("success_criteria"))
        if not statement and criteria:
            statement = "；".join(criteria)
        if not statement:
            return None
        goalId = str(raw.get("id") or "").strip() or _stableGoalId(statement)
        return LoopGoal(
            id=goalId,
            statement=statement,
            successCriteria=criteria,
            sourceTurnId=(
                str(raw.get("sourceTurnId") or raw.get("source_turn_id") or "") or None
            ),
        )
    return None


def _stableGoalId(statement: str) -> str:
    """同一目标的标识稳定可复现（跨轮比对不依赖随机值）。"""
    import hashlib

    return "goal_" + hashlib.md5(statement.encode("utf-8")).hexdigest()[:12]
