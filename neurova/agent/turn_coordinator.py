# -*- coding: utf-8 -*-
"""让位闸（GLANCE_YIELD 规则在回合入口的执行体）。

拍板口径：**最多重试 10 次、单次等待上限 20 秒（总预算 200s），超限不失败而是挂起等人工续跑。**

**为什么是这个形状**（三条都是实测出来的，不是偏好）：

1. Layer 1 的 `_check_model_pin` 自己会在首次见某 agent 时建 pin，并对"换了模型"直接判
   `MODEL_PIN_VIOLATION`。所以闸**不能**每次都 `register_agent`——那会把 pin 反复覆写掉，
   模型漂移这一格判据当场变哑（被摘链的那份装饰器与旧 coordinator 都犯了这一条）。
2. `MODEL_PIN_VIOLATION` 一类原因**等多久都不会自愈**（不是冷却，是身份不符）。等待只对
   可自愈的原因（并发、间距、限速冷却、碰撞）有意义，所以这里把它单列成不可重试：一次判定
   就挂起，而不是白等 200 秒再挂起。
3. 操作标识必须对"同一回合"稳定。旧的 coordinator 用 `turn_id + 毫秒时间戳`，等于每次重试
   都是一个新操作，`check_yield_rules` 的碰撞判据恒为假——那格规则白写。这里改成
   `sha256(session_id|user_input)`：同回合稳定、不同输入不同。

退役说明：同功能的第二份实现 `collaboration/coordination_decorators.glance_yield_check`
在协程里用 `time.sleep` 等待（一个 agent 让位会把整条事件循环睡掉），身份取
`kwargs.get("agent_id", "unknown")`（所有 agent 挤进同一个配额桶），且生产侧零消费者。
按教义第 7 条：先比后合——它的参数哈希长处并到本模块，其余随文件退役。
"""

from __future__ import annotations

import asyncio
import hashlib
import os
from dataclasses import dataclass
from typing import FrozenSet, Optional

from neurova.collaboration.glance_yield_rules import YieldReason, get_glance_yield_checker
from neurova.core.logger import get_logger

logger = get_logger(__name__)

DEFAULT_YIELD_MAX_ATTEMPTS = 10
DEFAULT_YIELD_CAP_SECONDS = 20.0
MIN_WAIT_SECONDS = 0.05

# 这些原因不会随时间自愈：等下去只是白占预算，第一次判定就挂起交人工
NON_RETRYABLE_YIELD_REASONS: FrozenSet[str] = frozenset(
    {YieldReason.MODEL_PIN_VIOLATION.value}
)

__all__ = [
    "YieldWaitPolicy",
    "yieldWaitPolicy",
    "turnOperationIdentity",
    "YieldGateOutcome",
    "requestYieldGate",
    "reportTurnOutcome",
]


@dataclass(frozen=True)
class YieldWaitPolicy:
    """让位等待预算：次数上限 + 单次上限（总预算由两者相乘自然成立）。"""

    maxAttempts: int
    capSeconds: float


def _readPositiveInt(envName: str, default: int) -> int:
    raw = (os.environ.get(envName) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(
            f"{envName}={raw!r} 不是整数；让位闸的策略值不做静默兜底（配了没生效比配错更难查）"
        ) from None
    if value < 0:
        raise ValueError(f"{envName}={value} 不能为负")
    return value


def _readPositiveFloat(envName: str, default: float) -> float:
    raw = (os.environ.get(envName) or "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        raise ValueError(
            f"{envName}={raw!r} 不是数值；让位闸的策略值不做静默兜底（配了没生效比配错更难查）"
        ) from None
    if value <= 0:
        raise ValueError(f"{envName}={value} 必须为正数")
    return value


def yieldWaitPolicy() -> YieldWaitPolicy:
    """每次调用现读 env。

    导入期绑定会让"改环境变量"变成"改了没生效"（本仓修过的同类病灶：日志目录、
    RSI 审计流落点都曾在导入期定死），策略旋钮也必须按调用解析。
    """
    return YieldWaitPolicy(
        maxAttempts=_readPositiveInt("NEUROVA_YIELD_MAX_ATTEMPTS", DEFAULT_YIELD_MAX_ATTEMPTS),
        capSeconds=_readPositiveFloat("NEUROVA_YIELD_WAIT_CAP_SECONDS", DEFAULT_YIELD_CAP_SECONDS),
    )


def turnOperationIdentity(*, sessionId: str, userInput: str) -> str:
    """本次回合的操作标识：对"会话 + 这条输入"取哈希。

    同回合重试必须落在这个标识上，否则碰撞判据（Layer 4 的 `record_operation_*` 一族）
    永远看到的是新操作，永远不会让位。
    """
    content = f"{sessionId or ''}|{userInput or ''}"
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:32]


@dataclass(frozen=True)
class YieldGateOutcome:
    """闸的结论。`proceeded=False` 时 `parkReason` 必须非空——不许出现"既没放行也没原因"。"""

    proceeded: bool
    attempts: int
    waitedSeconds: float
    operation: str
    parkReason: str = ""
    agentId: str = ""
    sessionId: str = ""

    @property
    def shouldPark(self) -> bool:
        return not self.proceeded


async def requestYieldGate(
    *,
    agentId: str,
    modelName: str,
    sessionId: str = "",
    userInput: str = "",
    policy: Optional[YieldWaitPolicy] = None,
) -> YieldGateOutcome:
    """回合开跑前的让位闸。

    只做三件事：问裁决器 → 可自愈的原因就等（单次 ≤ capSeconds，最多 maxAttempts 次）→
    要么放行并登记操作开始，要么带着原因回来说"该挂起了"。

    不在这里落库、不在这里发事件：挂起态属于 run 台账（`core/agent_run_store`），
    由调用方按结论去写——闸只管判，别既当裁判又记账。

    Raises:
        任何来自裁决器的异常都原样向上抛（闸不吞异常；降级与否由调用方决定并留痕）。
    """
    checker = await get_glance_yield_checker()
    resolved = policy or yieldWaitPolicy()
    operation = turnOperationIdentity(sessionId=sessionId, userInput=userInput)

    attempts = 0
    waited = 0.0

    while True:
        attempts += 1
        decision = checker.check_yield_rules(
            agent_id=agentId,
            model_name=modelName,
            proposed_operations=[operation],
            conversation_id=sessionId or None,
        )

        if not decision.should_yield:
            checker.record_operation_start(agentId, operation)
            return YieldGateOutcome(
                proceeded=True,
                attempts=attempts,
                waitedSeconds=waited,
                operation=operation,
                agentId=agentId,
                sessionId=sessionId,
            )

        reason = str(decision.reason.value) if decision.reason else "unspecified"

        if reason in NON_RETRYABLE_YIELD_REASONS:
            logger.warning(
                "让位闸挂起（等也不会自愈）：agent=%s 原因=%s", agentId, reason
            )
            return YieldGateOutcome(
                proceeded=False,
                attempts=attempts,
                waitedSeconds=waited,
                operation=operation,
                parkReason=reason,
                agentId=agentId,
                sessionId=sessionId,
            )

        if attempts > resolved.maxAttempts:
            logger.warning(
                "让位闸超限挂起：agent=%s 判 %d 次、累计等 %.1fs、原因=%s",
                agentId, attempts, waited, reason,
            )
            return YieldGateOutcome(
                proceeded=False,
                attempts=attempts,
                waitedSeconds=waited,
                operation=operation,
                parkReason=reason,
                agentId=agentId,
                sessionId=sessionId,
            )

        waitSeconds = min(
            max(float(decision.wait_time_seconds or 0.0), MIN_WAIT_SECONDS),
            resolved.capSeconds,
        )
        await asyncio.sleep(waitSeconds)
        waited += waitSeconds


async def reportTurnOutcome(*, outcome: YieldGateOutcome, success: bool) -> None:
    """回合结束时由调用方 await 回填 pacing 统计（间距/自适应节律的判据来源）。

    放行才回填——没跑的操作记成完成，Layer 3 的节律统计就说假话。
    这里刻意**不**自起后台任务：仓里已登记过"句柄丢弃 → 关停无法收敛"的病灶
    （§6-21/R8），要异步由调用方决定并持有句柄。
    """
    if not outcome.proceeded or not outcome.operation:
        return
    checker = await get_glance_yield_checker()
    checker.record_operation_complete(outcome.agentId, outcome.operation, success=success)
