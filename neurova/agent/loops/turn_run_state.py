"""一次 chat 调用的轮次态（Issue #268 切片 A）。

轮次控制状态此前挂在 loop 实例上，而 loop 是 per-agent 单例
（`agent_core` 经 `loop_manager.get_loop()` 装配）。同一 agent 上两个会话交叠时，
后进入者在 `predict_step` 入口的清零会改写前一个会话正在累加的轮次预算与
停滞计数——实测同一 loop 实例上交叠驱动两次 `predict_step`，被交叠会话的
LLM 调用次数由 3 次变 4 次（预算被放大），`_stagnation_count` 同样被抹平。

本模块把这份状态抽成显式对象：生命周期 = 本次 `predict_step`，逐轮沿调用链传递，
不跨请求存活。门控执行器也随之一轮一份（`DoomLoopGate` 的滑动窗口本身就是
会话级态），构造点单源在 `OpenAILoop.buildGateRunner()`。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

#: 工具轮上限的兜底值（设置不可读时）。上限本身由 `OpenAILoop` 从
#: `security/agent_limits_settings` 的 `max_loop_rounds` 派生——不在此另立一份尺度。
ROUND_BUDGET_FALLBACK = 10


@dataclass
class TurnRunState:
    """轮次态。字段语义见使用点，不在此复述。"""

    toolRounds: int = 0
    maxToolRounds: int = ROUND_BUDGET_FALLBACK
    stagnationCount: int = 0
    roundUserKey: Optional[str] = None
    roundReplies: List[str] = field(default_factory=list)
    lastRoundCalls: List[Tuple[str, str]] = field(default_factory=list)
    toolsSupported: bool = True
    #: 已求过门控的轮次号。门控**每轮只求值一次**：`DoomLoopGate.check()` 会自行
    #: 把本轮签名记入窗口，同轮二次求值等于把自己的签名判成"重复"。取轮次号而非
    #: 签名：签名在"上一轮调用与本轮调用完全一致"的真死循环里也相同，用它去重会
    #: 让死循环门永远看不到第二次重复。
    gatedRound: int = -1
    #: 本轮门控执行器——**必填**，由入口构造时传入（`_buildGateRunner` 单点装配）。
    #: 同一轮内三条调用路径（非流式 / 流式 / 二者各自的续跑）共用这一份：
    #: `DoomLoopGate` 的滑动窗口与中断计数都挂在这份实例上，同一轮内多建一份
    #: 会让窗口不再累计、后续追加的门控只落在其中一份上。
    gateRunner: Any = None
    #: 创建者指纹（Issue #268 切片 C）：轮次归属已迁到本就是唯一事实源，
    #: 但"谁创建了它"此前从未被记录——把上一轮的 state 误递进新请求时，
    #: 新请求会继承旧轮次计数且**静默**（计数合法、上限不被违反）。
    #: 记录创建者后，交叉使用在开发期即由 `assertSameTurnAs` 点名报出。
    turnId: str = ""
    agentId: str = ""

    @classmethod
    def forTurn(cls, *, agentId: str, roundUserKey: Optional[str] = None, **kw: Any) -> "TurnRunState":
        """本轮轮次态的**唯一构造点**：签发 turnId 并记下创建者 agentId。

        直接 `TurnRunState(...)` 会得到空 turnId（无创建者记录），故生产侧一律
        走此处——两个构造点各不记指纹，正是"归属可自证"要消灭的形态。
        """
        return cls(
            roundUserKey=roundUserKey,
            agentId=str(agentId or ""),
            turnId=uuid.uuid4().hex,
            **kw,
        )

    def assertRoundInvariant(self) -> None:
        """轮入口自检：`toolRounds` 不得越过 `maxToolRounds`。

        上限判定本应在累加处咬合（越限即终止）。这条不变量在轮入口被违反，
        说明**上限判定被绕过**——今天唯一可复现的成因是跨会话污染（缺陷 A 的形态）：
        另一个会话把本方计数抹平，本方于是越过了自己的上限继续续轮。
        故它把缺陷 A 从"要靠并发活体才测得到"降级为"任何一轮入口都能自证"。
        """
        if self.toolRounds > self.maxToolRounds:
            raise RuntimeError(
                "轮次态不变量被违反：toolRounds="
                f"{self.toolRounds} > maxToolRounds={self.maxToolRounds}"
                f"（turnId={self.turnId or '<未签发>'}）"
                "——上限判定被绕过，通常是另一方会话污染了本轮的计数。"
            )

    def assertSameTurnAs(self, other: "TurnRunState") -> None:
        """交叉使用检查：两个 state 必须来自同一次 turn（否则点名两个 turnId）。"""
        if self.turnId != other.turnId:
            raise RuntimeError(
                "轮次态交叉使用："
                f"本 state turnId={self.turnId or '<未签发>'}，"
                f"传入 state turnId={other.turnId or '<未签发>'}"
                "——不同 turn 的轮次态不得互相传递（会把旧轮次计数带进新请求）。"
            )

    def roundSignature(self, toolSignatures: str = "") -> str:
        """死循环签名（本轮用户指纹 + 调用签名）——签名口径单源在此。"""
        return f"{self.roundUserKey}:{toolSignatures}"

    def exitSignature(self) -> str:
        """主出口（模型不再调工具）的轮次签名。

        出口求值点原先读 loop 实例上的 `_round_user_key`，而那个属性在切片 A
        之后**全仓零写入点**（只剩 `base.py` 一处 `getattr` 读），出口签名因此
        恒为 `":exit:N"` —— 交叠会话的两条出口判定签名完全相同。签发权归本轮
        state：指纹在这里，续跑序号走 `turn_context`（续跑计数是**轮级**量，
        不属本对象）。
        """
        from neurova.core.turn_context import get_turn_goal_continuations

        return f"{self.roundUserKey or ''}:exit:{get_turn_goal_continuations()}"

    def gateContext(self, toolSignatures: str = "", **extra: Any) -> Dict[str, Any]:
        """门控 ctx：轮次计数与签名从 state 取，不再从 loop 实例读。"""
        context: Dict[str, Any] = {
            "tool_rounds": self.toolRounds,
            "round_signature": self.roundSignature(toolSignatures),
        }
        context.update(extra)
        return context
