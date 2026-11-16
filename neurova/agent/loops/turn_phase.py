"""Turn 相位状态机（P1）。

此前轮次相位散在 loop 实例字段与两条环的控制流里，相位
合法性靠约定——不可测、不可审计。

本模块把"一轮对话走到哪一步"显式化：

- 相位取值与迁移表**静态声明**，非法迁移抛 `TurnPhaseError`（带当前/目标相位）；
- `TurnPhaseMachine` 挂在 `TurnRunState` 上（一轮一份，随轮释放——不落单例，
  与 Issue #268 的轮次态纪律一致）；
- `history` 记录每次迁移（相位→相位），供测试与诊断读数；
- 推进失败**不吞**：调用方传错相位是接线 bug，必须当场炸出来（教义第 2 条）。

相位语义（与 Neurova 两条环的实际控制流对齐）：

- IDLE：轮次态已建，尚未开始
- PROCESSING_INPUT：入口准备（工具面/参数装配）
- AWAITING_MODEL_RESPONSE：即将发起一次模型请求
- STREAMING：模型响应已开始到达（流式 chunk / 非流式整块）
- SCHEDULING_TOOLS：模型声明了工具调用，正在编排批次
- EXECUTING_TOOLS：工具批次执行中
- AGGREGATING_RESULTS：工具结果已回环、续跑提示/门控求值中
- COMPLETING：本轮收口（正常完成 / 门控终止 / 上限终止）
- ERROR：本轮以异常收场
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from neurova.core.logger import get_logger

_logger = get_logger(__name__)


class TurnPhaseError(RuntimeError):
    """非法相位迁移。调用方传错相位是接线 bug，必须当场点名。"""


class TurnPhase:
    """轮次相位常量（字符串词值，便于日志/台账直接落）。"""

    IDLE = "idle"
    PROCESSING_INPUT = "processing_input"
    AWAITING_MODEL_RESPONSE = "awaiting_model_response"
    STREAMING = "streaming"
    SCHEDULING_TOOLS = "scheduling_tools"
    EXECUTING_TOOLS = "executing_tools"
    AGGREGATING_RESULTS = "aggregating_results"
    COMPLETING = "completing"
    ERROR = "error"


#: 合法迁移表（静态声明；不在表内的一律拒绝）。
_VALID_TRANSITIONS: Dict[str, Tuple[str, ...]] = {
    TurnPhase.IDLE: (
        TurnPhase.PROCESSING_INPUT,
        # 直接驱动环入口（单轮/流式生成器）的合法起点：测试与旧调用路径
        # 不经 predict_step 的入口准备、直接从轮循环进入。
        TurnPhase.AWAITING_MODEL_RESPONSE,
        TurnPhase.STREAMING,
        TurnPhase.ERROR,
    ),
    TurnPhase.PROCESSING_INPUT: (TurnPhase.AWAITING_MODEL_RESPONSE, TurnPhase.COMPLETING, TurnPhase.ERROR),
    TurnPhase.AWAITING_MODEL_RESPONSE: (
        TurnPhase.STREAMING,
        # 纯工具调用响应（无正文/思考 chunk）从本相位直接进入工具编排。
        TurnPhase.SCHEDULING_TOOLS,
        # 空内容轮的出口求值（门控续跑/终止）直接从本相位聚合——
        # 非流式整块响应也可能一个内容 chunk 都没有。
        TurnPhase.AGGREGATING_RESULTS,
        TurnPhase.COMPLETING,
        TurnPhase.ERROR,
    ),
    TurnPhase.STREAMING: (
        TurnPhase.SCHEDULING_TOOLS,
        TurnPhase.AGGREGATING_RESULTS,
        # 恢复路径就地重发同一次请求（溢出/输出预算重试）：从流中退回
        # "等待模型响应"再开下一轮——重试不是新轮次，是同一轮的续。
        TurnPhase.AWAITING_MODEL_RESPONSE,
        TurnPhase.COMPLETING,
        TurnPhase.ERROR,
    ),
    TurnPhase.SCHEDULING_TOOLS: (TurnPhase.EXECUTING_TOOLS, TurnPhase.AWAITING_MODEL_RESPONSE, TurnPhase.ERROR),
    TurnPhase.EXECUTING_TOOLS: (TurnPhase.AGGREGATING_RESULTS, TurnPhase.ERROR),
    TurnPhase.AGGREGATING_RESULTS: (
        TurnPhase.AWAITING_MODEL_RESPONSE,
        TurnPhase.SCHEDULING_TOOLS,
        TurnPhase.COMPLETING,
        TurnPhase.ERROR,
    ),
    TurnPhase.COMPLETING: (),
    TurnPhase.ERROR: (),
}

_TERMINAL = (TurnPhase.COMPLETING, TurnPhase.ERROR)


def canTransitionTo(current: str, target: str) -> bool:
    """静态判据：当前相位是否允许迁到目标相位。"""
    return target in _VALID_TRANSITIONS.get(current, ())


def isTerminalPhase(phase: str) -> bool:
    return phase in _TERMINAL


class TurnPhaseMachine:
    """一轮对话的相位机：唯一写入点是 `transition()`，非法迁移当场抛错。"""

    def __init__(self) -> None:
        self.phase: str = TurnPhase.IDLE
        self.history: List[Tuple[str, str]] = []

    def transition(self, target: str) -> str:
        """迁到目标相位；非法迁移抛 `TurnPhaseError`（带两个相位与迁移史尾）。"""
        if not canTransitionTo(self.phase, target):
            raise TurnPhaseError(
                f"非法轮次相位迁移: {self.phase} → {target}"
                f"（合法目标: {_VALID_TRANSITIONS.get(self.phase, ())}；"
                f"迁移史尾: {self.history[-3:]}）"
            )
        self.history.append((self.phase, target))
        self.phase = target
        return self.phase

    def transitionIfChanged(self, target: str) -> str:
        """同相位幂等推进：目标与当前相同则原地返回（流式逐 chunk 推进用），
        跨相位跳变仍走 `transition()` 的严格校验。"""
        if self.phase == target:
            return self.phase
        return self.transition(target)

    def isComplete(self) -> bool:
        return isTerminalPhase(self.phase)

    def snapshot(self) -> Dict[str, Any]:
        """读数投影（诊断/台账用）：当前相位＋迁移步数。"""
        return {"phase": self.phase, "transitions": len(self.history)}


def phaseAdvance(state: Any, target: str) -> None:
    """推进轮次相位（严格校验）。无相位机的 state（手工构造）跳过——
    生产侧 `TurnRunState.forTurn` 必带；缺它只可能是测试桩。"""
    machine = getattr(state, "phaseMachine", None)
    if machine is None:
        return
    machine.transition(target)


def phaseAdvanceIfChanged(state: Any, target: str) -> None:
    """同相位幂等版（流式逐 chunk 推进用）。"""
    machine = getattr(state, "phaseMachine", None)
    if machine is None:
        return
    machine.transitionIfChanged(target)


def phaseMarkError(state: Any) -> None:
    """错误路径的相位收口：尽力迁到 ERROR。

    与主路径的严格校验不同——这里若迁移被拒（说明错误发生在终端相位之后，
    本身就是接线异常），**不能顶掉正在上抛的真因**：留警告日志后返回，
    原异常照常传播。这是"不掩盖真因"与"相位可观测"两个要求的交点。
    """
    machine = getattr(state, "phaseMachine", None)
    if machine is None or machine.isComplete():
        return
    try:
        machine.transition(TurnPhase.ERROR)
    except TurnPhaseError as exc:
        _logger.warning("错误路径相位收口被拒（原异常不受影响）: %s", exc)
