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
    gateRunner: Any = None

    def roundSignature(self, toolSignatures: str = "") -> str:
        """死循环签名（本轮用户指纹 + 调用签名）——签名口径单源在此。"""
        return f"{self.roundUserKey}:{toolSignatures}"

    def gateContext(self, toolSignatures: str = "", **extra: Any) -> Dict[str, Any]:
        """门控 ctx：轮次计数与签名从 state 取，不再从 loop 实例读。"""
        context: Dict[str, Any] = {
            "tool_rounds": self.toolRounds,
            "round_signature": self.roundSignature(toolSignatures),
        }
        context.update(extra)
        return context
