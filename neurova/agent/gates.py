"""
循环门控系统（P2-5，对标 QP loop/gates 三态语义）

StopAction 三态：
- BYPASS: 继续（无干预）
- INTERRUPT_AND_CONTINUE: 注入提示后继续（软干预，把 gate 意见告知 LLM）
- TERMINATE: 终止循环（硬停止，循环立即结束）

StopGate ABC：check(ctx) → StopDecision。GateRunner 按优先级执行全部门控，
故障隔离（gate 异常 = BYPASS + warning），TERMINATE 优先于一切。

接入点（openai_loop）：
- 每轮工具调用后（含 skill/router 结果）：GateRunner.on_round_end(...)
- 上下文 ctx 携带轮次计数/累计 token/本轮回复签名
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class StopAction(Enum):
    BYPASS = "bypass"
    INTERRUPT_AND_CONTINUE = "interrupt_and_continue"
    TERMINATE = "terminate"


@dataclass
class StopDecision:
    action: StopAction
    reason: str = ""
    gate_name: str = ""
    # INTERRUPT_AND_CONTINUE 时注入给 LLM 的提示文本
    continuation_prompt: str = ""

    @classmethod
    def bypass(cls) -> "StopDecision":
        return cls(action=StopAction.BYPASS)


class StopGate(ABC):
    """循环停止门控基类。"""

    name: str = "gate"
    priority: int = 100  # 数字小先执行

    @abstractmethod
    def check(self, ctx: Dict[str, Any]) -> StopDecision:
        """判定当前循环状态。ctx 键：tool_rounds / round_reply / round_usage /
        last_tool_calls / goal（可选，goal 模式注入）。"""


class IterationGate(StopGate):
    """轮次上限门控（对标 QP IterationGate）。"""

    def __init__(self, max_rounds: int = 20):
        self.name = "iteration"
        self.priority = 10
        self.max_rounds = max_rounds

    def check(self, ctx: Dict[str, Any]) -> StopDecision:
        rounds = int(ctx.get("tool_rounds") or 0)
        if rounds >= self.max_rounds:
            return StopDecision(
                action=StopAction.TERMINATE,
                reason=f"工具调用轮次达到上限 {self.max_rounds}",
                gate_name=self.name,
            )
        return StopDecision.bypass()


class TokenBudgetGate(StopGate):
    """累计 token 预算门控（对标 QP TokenBudgetGate）。"""

    def __init__(self, max_tokens: int = 100000):
        self.name = "token_budget"
        self.priority = 20
        self.max_tokens = max_tokens

    def check(self, ctx: Dict[str, Any]) -> StopDecision:
        usage = ctx.get("round_usage") or {}
        total = int((usage or {}).get("total_tokens") or 0)
        if total >= self.max_tokens:
            return StopDecision(
                action=StopAction.TERMINATE,
                reason=f"累计 token 达到预算上限 {self.max_tokens}",
                gate_name=self.name,
            )
        return StopDecision.bypass()


class DoomLoopGate(StopGate):
    """死循环门控（对标 QP DoomLoopGate 滑动窗口相似度）。"""

    def __init__(
        self,
        window_size: int = 4,
        similarity_threshold: float = 0.95,
        max_interrupts: int = 2,
    ):
        self.name = "doom_loop"
        self.priority = 5
        self.window_size = window_size
        self.similarity_threshold = similarity_threshold
        self.max_interrupts = max_interrupts
        self._window: List[str] = []
        self._interrupt_count = 0

    def check(self, ctx: Dict[str, Any]) -> StopDecision:
        signature = str(ctx.get("round_signature") or "")
        if not signature:
            return StopDecision.bypass()

        if signature in self._window:
            self._interrupt_count += 1
            if self._interrupt_count >= self.max_interrupts:
                observed = self._interrupt_count  # reset 前捕获（reset 会清零）
                self.reset_session()
                return StopDecision(
                    action=StopAction.TERMINATE,
                    reason=f"检测到死循环（重复签名出现 {observed} 次）",
                    gate_name=self.name,
                )
            return StopDecision(
                action=StopAction.INTERRUPT_AND_CONTINUE,
                continuation_prompt=(
                    "检测到重复的工具调用模式。请更换策略，避免重复已失败的路径。"
                ),
                gate_name=self.name,
            )

        self._window.append(signature)
        if len(self._window) > self.window_size:
            self._window.pop(0)
        self._interrupt_count = 0
        return StopDecision.bypass()

    def reset_session(self) -> None:
        self._window.clear()
        self._interrupt_count = 0


class GoalGate(StopGate):
    """goal 模式门控：目标达成判定 + 轮次预算（对标 QP GoalSession 三 gate 合一）。

    completion_check(goal, ctx) 由调用方注入（LLM rubric 或显式条件），
    返回 (achieved: bool, summary: str)。
    """

    def __init__(
        self,
        goal: Dict[str, Any],
        completion_check: Optional[Callable[[Dict[str, Any], Dict[str, Any]], tuple]] = None,
        max_rounds: int = 15,
    ):
        self.name = "goal"
        self.priority = 15
        self.goal = dict(goal or {})
        self._completion_check = completion_check
        self.max_rounds = max_rounds

    def check(self, ctx: Dict[str, Any]) -> StopDecision:
        rounds = int(ctx.get("tool_rounds") or 0)
        goal_id = (self.goal.get("id") or "goal")[:24]

        if self._completion_check is not None:
            try:
                achieved, summary = self._completion_check(self.goal, ctx)
            except Exception as e:
                logger.warning("goal completion check 异常（忽略）: %s", e)
                achieved, summary = False, ""
            if achieved:
                return StopDecision(
                    action=StopAction.TERMINATE,
                    reason=f"目标达成: {summary or goal_id}",
                    gate_name=self.name,
                )

        if rounds >= self.max_rounds:
            return StopDecision(
                action=StopAction.TERMINATE,
                reason=f"goal 模式轮次预算耗尽（{self.max_rounds}）",
                gate_name=self.name,
            )
        return StopDecision.bypass()


class GateRunner:
    """门控执行器：按优先级执行全部门控，故障隔离。"""

    def __init__(self, gates: Optional[List[StopGate]] = None):
        self._gates: List[StopGate] = list(gates or [])

    def add_gate(self, gate: StopGate) -> None:
        self._gates.append(gate)
        self._gates.sort(key=lambda g: g.priority)

    @property
    def gates(self) -> List[StopGate]:
        return list(self._gates)

    def on_round_end(self, ctx: Dict[str, Any]) -> StopDecision:
        """按优先级执行全部门控；TERMINATE 立即返回，INTERRUPT 记录最后一条，
        其余 BYPASS 继续。gate 异常故障隔离为 BYPASS。全 BYPASS 时返回
        显式 bypass 决策（调用方无须判 None）。"""
        final: Optional[StopDecision] = StopDecision.bypass()
        for gate in sorted(self._gates, key=lambda g: g.priority):
            try:
                decision = gate.check(ctx)
            except Exception as e:
                logger.warning("门控 %s 异常（故障隔离为 BYPASS）: %s", gate.name, e)
                continue
            if decision.action == StopAction.TERMINATE:
                return decision  # TERMINATE 优先于一切
            if decision.action == StopAction.INTERRUPT_AND_CONTINUE:
                final = decision
        return final
