"""
循环门控系统

StopAction 三态：
- BYPASS: 继续（无干预）
- INTERRUPT_AND_CONTINUE: 注入提示后继续（软干预，把 gate 意见告知 LLM）
- TERMINATE: 终止循环（硬停止，循环立即结束）

StopGate ABC：check(ctx) → StopDecision。GateRunner 按优先级执行全部门控，
故障隔离（gate 异常 = BYPASS + warning），TERMINATE 优先于一切。

接入点（openai_loop）：
- 每轮工具调用后（含 skill/router 结果）：GateRunner.on_round_end(...)
- **主出口**（模型不再调用工具）：同一 GateRunner，ctx 带 `isLoopExit=True` ——
  假完成（停手且目标未达成）正是在这里才可被识别，工具轮内求值永远看不到它
- 上下文 ctx 携带轮次计数/累计 token/本轮回复签名/目标与判定结果
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
    """轮次上限门控。"""

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
    """累计 token 预算门控。"""

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
    """死循环门控。"""

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
    """目标达成门控：工具轮预算（既有）+ **主出口的假完成拦截**（G2）。

    两种 ctx 语义，同一个类：

    - **工具轮**（既有）：`ctx["goal"]` + 可选 `completion_check` 回调（同步、
      低成本判据），未达成时保持现状（继续跑工具轮，不额外发声）。
    - **主出口**（`ctx["isLoopExit"]` 为真）：模型已自认完成。此时"未达成"
      就是假完成，必须发声——判据来自 `ctx["goal_verdict"]`（由 Loop 在出口处
      完成异步判定后放入，故本门控保持纯同步、无 I/O）。续跑次数由
      `ctx["goal_continuations"]` 计数，上限是 `maxContinuations`（**唯一的
      配置绑定阈值**，配置键 `goal_max_continuations`）。

    判据不可用（`parse_ok` 为假）时一律 BYPASS：绝不因判据坏掉而阻断正常回复；
    该情形由出口处的观测面以诚实形态暴露。
    """

    def __init__(
        self,
        goal: Optional[Dict[str, Any]] = None,
        completion_check: Optional[Callable[[Dict[str, Any], Dict[str, Any]], tuple]] = None,
        max_rounds: int = 15,
        maxContinuations: int = 2,
    ):
        self.name = "goal"
        self.priority = 15
        self.goal = dict(goal or {})
        self._completion_check = completion_check
        self.max_rounds = max_rounds
        # 续跑预算独立于工具轮预算：一次续跑消耗一格 goal_max_continuations，
        # 不消耗工具轮预算。两者绑定**不同的配置键**，故阈值可达性为 single_source
        # （不得与 max_loop_rounds 共享尺度来源——那是 IterationGate 被机器算成
        # scaled_sparse 的成因，本门控不得再现该形态）。
        self.maxContinuations = maxContinuations

    def check(self, ctx: Dict[str, Any]) -> StopDecision:
        """两种 ctx 语义并在一个判定体内（阈值比较也在此，便于机器复算可达性）。"""
        rounds = int(ctx.get("tool_rounds") or 0)
        spent = int(ctx.get("goal_continuations") or 0)
        goal_id = (self.goal.get("id") or "goal")[:24]
        goal = dict(ctx.get("goal") or self.goal or {})

        if ctx.get("isLoopExit"):
            # 主出口求值：只对"未达成"发声，达成与判据不可用都放行。
            verdict = ctx.get("goal_verdict") or {}
            if not verdict.get("parse_ok"):
                # 判据不可用（解析失败/通道故障）→ 不拦截；观测面已在出口处记过。
                return StopDecision.bypass()
            if verdict.get("achieved"):
                return StopDecision(
                    action=StopAction.TERMINATE,
                    reason=f"目标达成: {verdict.get('explanation') or ''}".strip(),
                    gate_name=self.name,
                )
            if spent >= self.maxContinuations:
                return StopDecision(
                    action=StopAction.TERMINATE,
                    reason=(
                        f"目标未达成且续跑预算耗尽（{self.maxContinuations}）: "
                        + self._missingSummary(verdict)
                    ),
                    gate_name=self.name,
                )
            return StopDecision(
                action=StopAction.INTERRUPT_AND_CONTINUE,
                reason=f"模型自认完成但目标未达成: {self._missingSummary(verdict)}",
                gate_name=self.name,
                continuation_prompt=self._buildReopenPrompt(goal, verdict),
            )

        if self._completion_check is not None:
            try:
                achieved, summary = self._completion_check(goal or self.goal, ctx)
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

    @staticmethod
    def _missingSummary(verdict: Dict[str, Any]) -> str:
        missing = [str(item) for item in (verdict.get("missing") or []) if str(item or "").strip()]
        return "；".join(missing) if missing else "（判定未给出缺失条目）"

    def _buildReopenPrompt(self, goal: Dict[str, Any], verdict: Dict[str, Any]) -> str:
        """续跑提示：点名目标、缺失条目与要求，使模型知道差在哪。"""
        statement = str(goal.get("statement") or "")
        lines = ["【目标未完成，请继续】"]
        if statement:
            lines.append(f"目标：{statement}")
        lines.append(f"尚未完成：{self._missingSummary(verdict)}")
        explanation = str(verdict.get("explanation") or "").strip()
        if explanation:
            lines.append(f"判定说明：{explanation}")
        lines.append("请补齐上述缺口后再给出最终答复；不要重复已经完成的步骤。")
        return "\n".join(lines)

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

    def reset_session(self) -> None:
        """重置所有门控的会话级状态（2026-09-07：轮次状态必须 per-request，
        跨请求残留会让 DoomLoopGate 把新一轮的正常调用误判为死循环）。"""
        for gate in self._gates:
            if hasattr(gate, "reset_session"):
                gate.reset_session()
