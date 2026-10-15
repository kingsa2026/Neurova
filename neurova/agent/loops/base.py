"""
Agent Loop 基类 - 定义标准接口

每个 Loop 实现特定的模型交互逻辑。
"""

import asyncio
import json
from neurova.core.logger import get_logger
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, Dict, List, Optional

# Agent 仅用于类型注解；运行时导入会与 agent_core 形成循环依赖
if TYPE_CHECKING:
    from neurova.agent_core import Agent


logger = get_logger(__name__)


def _safe_json_dumps(obj: Any) -> str:
    """JSON 序列化兜底（LLM 工具结果必须可序列化）。

    SkillResult 等自定义对象（实测：幻觉工具名经 ToolRouter 返回）无法
    json.dumps 时，降级为 repr 截断——执行链不因序列化崩溃，LLM 仍能
    看到错误形态并自我纠正。
    """
    try:
        return json.dumps(obj)
    except (TypeError, ValueError):
        return json.dumps({"non_serializable": repr(obj)[:500]})


#: 主出口求值的三态动词（与 `gates.StopAction` 不重合：那边是门控意见，
#: 这边是"循环该怎么办"的落地决定；`done` 不新增门控语义、不做第二套干预通路）。
LOOP_DONE = "done"
LOOP_CONTINUE = "continue"
LOOP_STOP = "stop"


@dataclass(frozen=True)
class LoopExitDecision:
    """主出口（模型不再调用工具）的求值结果。

    三态：正常收口 / 注入提示后续跑 / 有理由地终止。
    载荷 `continuation_prompt` 直译自 `StopDecision.continuation_prompt`，
    不新增 StopAction 枚举值——门控的动词集只有一套表达。
    """

    action: str = LOOP_DONE
    continuation_prompt: str = ""
    reason: str = ""
    gate_name: str = ""

    @classmethod
    def done(cls) -> "LoopExitDecision":
        return cls(action=LOOP_DONE)

    @classmethod
    def stop(cls, reason: str, gate_name: str = "") -> "LoopExitDecision":
        return cls(action=LOOP_STOP, reason=reason, gate_name=gate_name)

    @classmethod
    def resume(cls, prompt: str, gate_name: str = "") -> "LoopExitDecision":
        return cls(action=LOOP_CONTINUE, continuation_prompt=prompt, gate_name=gate_name)


async def evaluateLoopExit(
    loop: "BaseAgentLoop",
    *,
    reply: str,
    roundUsage: Any,
    toolRound: int,
    roundSignature: Optional[str] = None,
) -> LoopExitDecision:
    """主出口的门控求值（**唯一实现点**，两条路径共用）。

    为什么必须存在：工具轮的求值发生在 `if tool_calls:` 块内，而"模型不再调用
    工具"这一主出口在块外收口——假完成（停手且目标未达成）在那里一次都不会
    被看到。加调用方不改变这一点，缺的是求值点。

    ctx 带 `isLoopExit=True`，使 GoalGate 能区分"停在工具轮中途"与"自认为完成"：
    只有后者才是假完成，也只有后者才值得注入提示续跑。

    `roundSignature` 由调用方从**本轮 `TurnRunState`** 取（`state.exitSignature()`）：
    这里原先读 loop 实例的 `turnRoundSignature()`，而它依赖的 `_round_user_key`
    在轮次态迁出实例后已成零写入点的死属性——出口签名恒为 `":exit:N"`，
    交叠会话的两条出口判定因此同签名。缺省仍退回实例读法，兼容未传的调用方。

    判定输入由 `ctx["goal_verdict"]` 承载（异步判定在进入门控前完成），
    故门控本身保持纯同步、无 I/O。
    """
    from neurova.core import turn_context as turnContext

    goal = loop.resolveTurnGoal()
    if not goal or not goalVerificationEnabled():
        # **无目标就不求值**（D-4），这是本求值点的成本边界，也是语义边界：
        # 出口求值要抓的是"假完成"——一个伪命题在没有目标时并不存在。
        # 若在此照跑门控集合，死循环门会拿出口签名去判重，普通对话会因此
        # 收到一次没有意义的"换策略"续跑（实测：length 恢复重试被多打一轮）。
        return LoopExitDecision.done()

    runner = loop.gateRunnerForExit()
    if runner is None:
        return LoopExitDecision.done()

    from neurova.agent.gates import StopAction
    from neurova.agent.goal_verifier import verifyGoalCompletion
    from neurova.agent.loop_goal import normalizeGoal

    verdict = await verifyGoalCompletion(
        loop.llm_client.chat, normalizeGoal(goal), loop.buildExitEvidence(reply)
    )
    turnContext.set_turn_goal_verdict(verdict)
    recordGoalVerification(verdict)

    decision = runner.on_round_end({
        "tool_rounds": toolRound,
        "round_reply": reply,
        "round_usage": roundUsage or {},
        "round_signature": roundSignature or loop.turnRoundSignature(),
        "goal": goal or {},
        "isLoopExit": True,
        "goal_verdict": verdict,
        "goal_continuations": turnContext.get_turn_goal_continuations(),
    })
    if decision.action == StopAction.TERMINATE:
        if verdict and verdict.get("achieved"):
            return LoopExitDecision.done()
        return LoopExitDecision.stop(decision.reason, decision.gate_name)
    if decision.action == StopAction.INTERRUPT_AND_CONTINUE:
        # 出口续跑是 goal 门控的能力，**预算归它所有**：任何门控在出口请求续跑
        # 都受同一个上限约束，否则一个恒发声的门控就能让出口无限递归。
        budget = _exitContinuationBudget(runner)
        spent = turnContext.get_turn_goal_continuations()
        if budget <= 0 or spent >= budget:
            return LoopExitDecision.stop(
                f"目标未达成且续跑预算耗尽（{budget}）: {decision.reason}",
                decision.gate_name,
            )
        turnContext.mark_turn_goal_continuation()
        logger.info("主出口门控 %s 软干预（提示将注入消息序列）: %s", decision.gate_name, decision.reason)
        return LoopExitDecision.resume(decision.continuation_prompt, decision.gate_name)
    return LoopExitDecision.done()


def _exitContinuationBudget(runner: Any) -> int:
    """出口续跑预算：取自装配面里 goal 门控的**同一个** `maxContinuations`。

    不新造第二份预算定义——阈值只在 `GoalGate` 上有一处，本函数只是读取它。
    """
    for gate in runner.gates:
        if getattr(gate, "name", "") == "goal":
            return int(getattr(gate, "maxContinuations", 0) or 0)
    return 0


def _recordBatchShape(batches: List, loop: Any) -> None:
    """落一轮的批次形态读数（M3 收益判据的输入，唯一落点）。

    三态按**执行形态**分，不按工具类别分：

    - `single_call`：本轮只有一个调用——M3 在这上面本来就没有收益可言，
      混进分母会把"多工具批次占比"稀释成两个不同问题的平均数；
    - `multi_parallel`：至少有一个**成组**批（`planToolBatches` 只在 ≥2 项时
      给 `parallel=True`）——这是 M3 唯一能兑现收益的形态；
    - `multi_serial`：多调用但零成组批——M3 的**目标客户**，`w ≥ 1` 的
      一票否决形态与"全未声明"都落这里，两者对 M3 的意义相同（都拿不到并行）。

    `path` 取调度实现类名，因为**两条路径的批形态不同**：`AnthropicLoop`
    只在批里含 `computer` 时才逐条转发 `super().handle_tool_calls([单条])`
    （其余整批交基类），故它的残留盲区是"含 `computer` 的批恒 `single_call`"，
    而不是整条路径——分开计，是因为把它并进总数会把这条盲区读成
    "M3 没有收益"。依据的活行为由 `anthropic_loop.handle_tool_calls` 的分支
    给出，不在此抄一份（抄了就会像它上一版那样静默过期）。
    读数失败不影响调度（观测面故障不得改变执行语义）。
    """
    try:
        from neurova.core.metrics import record_tool_batch_shape
        from neurova.core.tool_capability import classifyBatchShape

        shape = classifyBatchShape(
            sum(len(batch.items) for batch in batches),
            any(batch.parallel for batch in batches),
        )
        record_tool_batch_shape(type(loop).__name__, shape.value)
    except Exception:  # noqa: BLE001 - 观测失败不改变执行语义
        logger.debug("批次形态读数跳过", exc_info=True)


def resolveParallelBudget() -> int:
    """单批并行上限（单源 `agent_limits_settings` 的 `max_parallel_tools`）。

    不在此处再写一份默认值或夹紧边界：合法域在配置单源里夹好，本函数只读取。
    读不到设置时回落到**安全的一侧**——上限取下界，即"最多 1 个并发"退回串行，
    而不是放开。上限的意义是护栏（缺陷 E：`asyncio.gather` 此前无上限，一轮
    20 个 MCP 调用就是 20 并发），故取不到时宁可保守。
    """
    try:
        from neurova.security.agent_limits_settings import get_effective_limits

        return int(get_effective_limits().get("max_parallel_tools", 1) or 1)
    except Exception:  # noqa: BLE001 - 读不到设置不改变既有保守语义（按串行）
        return 1


def goalVerificationEnabled() -> bool:
    """目标验收链总开关（单源 `agent_limits_settings`）。

    默认开：本片修的正是"假完成无人拦"，默认关等于接了线不通电。成本边界由
    **目标是否存在**守住（无目标零判定调用），开关只作运营侧的成本闸。
    """
    try:
        from neurova.security.agent_limits_settings import get_effective_limits

        return bool(get_effective_limits().get("goal_verification_enabled", True))
    except Exception:  # noqa: BLE001 - 读不到设置不改变既有行为（按开）
        return True


def recordGoalVerification(verdict: Dict[str, Any]) -> None:
    """判定结果入观测面（唯一埋点入口；不常驻 agent）。"""
    if not verdict.get("parse_ok"):
        outcome = "parse_failed"
    else:
        outcome = "achieved" if verdict.get("achieved") else "unmet"
    try:
        from neurova.core.metrics import record_goal_verification

        record_goal_verification(outcome)
    except Exception:  # noqa: BLE001 - 观测失败不影响对话主链
        logger.debug("目标判定埋点失败（忽略）", exc_info=True)


def resolveCallId(tool_call: Dict) -> str:
    """工具调用 id 的唯一解析点——assistant 声明侧与 tool 结果侧必须同源于此。

    两侧若各算各的，assistant.tool_calls 的 id 与 tool 消息的 tool_call_id 就
    对不上，配对判据（context/recovery.repair_tool_turns）会把整轮判为孤儿。
    provider 首片不给 id 时（兼容网关实测）就地合成：None 两侧一致也只是
    "同样非法"，协议仍要求每条调用带有效 id。
    """
    callId = tool_call.get("id")
    return str(callId) if callId else f"call_{id(tool_call)}"


class BaseAgentLoop(ABC):
    """
    Agent Loop 基类

    每个 Loop 实现特定的模型交互逻辑。
    子类必须实现 predict_step() 方法。

    """

    def __init__(self, agent: "Agent"):
        """
        初始化 Loop

        参数:
            agent: Agent 实例，提供对记忆、技能等系统的访问
        """
        self.agent = agent
        self.llm_client = agent.llm_client
        # 门控装配的三份轮级态：goal 规格、追加门控规格、本轮执行器。
        # 全部 loop 共用这一处初始化——此前它们只活在 OpenAILoop.__init__ 里，
        # 于是 AnthropicLoop 连门控执行器都没有（`gateRunnerForExit` 恒回 None）。
        self._goal_gate_spec = None
        self._extra_gate_specs: List[Any] = []
        self._gate_runner = self._buildGateRunner()

    # ── 目标验收链（G2 出口求值）的共享接入点 ──────────────────────────

    def resolveTurnGoal(self) -> Optional[Dict[str, Any]]:
        """本轮目标（归一后的 dict 形态；未声明返回 None）。

        **全环唯一解析点**：写入方经 `turn_context.set_turn_goal` 单点归一，
        读取方一律走这里——两条路径各自 `getattr(agent, ...)` 就是第二份读法。
        """
        from neurova.core.turn_context import get_turn_goal

        return get_turn_goal()

    def buildExitEvidence(self, reply: str) -> str:
        """判定证据：本轮最终回复 + 已执行工具的动作摘要。

        只取本轮（不是全量历史），避免判定调用二次 token 膨胀。
        """
        from neurova.core.turn_context import get_turn_tool_messages_snapshot

        parts = [f"最终回复：{str(reply or '')}"]
        lines: List[str] = []
        for record in (get_turn_tool_messages_snapshot() or [])[-12:]:
            if not isinstance(record, dict):
                continue
            kind = record.get("type")
            if kind == "tool_call":
                lines.append(f"- 调用 {record.get('tool_name')}")
            elif kind == "tool_result":
                lines.append(
                    f"- 结果 {record.get('tool_name')}: success={record.get('success')}"
                )
        if lines:
            parts.append("本轮工具动作：\n" + "\n".join(lines))
        return "\n".join(parts)[:4000]

    def turnRoundSignature(self) -> str:
        """主出口轮次签名的**兜底**读法（无 state 可用时）。

        正式取数点是 `TurnRunState.exitSignature()`——签名的主体是"本轮用户
        指纹"，而轮次态归属已迁到那次调用自己的 state 上（Issue #268）。
        本方法保留给"直接驱动 `evaluateLoopExit` 而无 state"的调用方，
        指纹位因此只能为空：不做第二份事实源（`_round_user_key` 已随切片 A
        成为零写入点的死属性，不再从实例读它）。
        """
        from neurova.core.turn_context import get_turn_goal_continuations

        return f":exit:{get_turn_goal_continuations()}"

    # ── 门控装配（两条环的唯一实现点）──────────────────────────────────
    #
    # 上移自 `OpenAILoop`：门清单与预算属于"环怎么停"这件事，不属于某一家供应商。
    # 留在 OpenAI 侧时，Anthropic 环既没有 IterationGate 也没有 DoomLoopGate/
    # TokenBudgetGate，基类 `gateRunnerForExit` 恒回 None，`evaluateLoopExit` 于是
    # 对 claude 退化成"正常收口"——同一份配置键读出两套停止行为，且没有任何东西报红。

    @staticmethod
    def _load_agent_limits() -> dict:
        """读取 Agent 运行限制设置（token_budget/max_loop_rounds）。

        失败时回退内置默认（100000/20），不阻断 Loop 构造。
        """
        try:
            from neurova.security.agent_limits_settings import get_effective_limits

            return get_effective_limits()
        except Exception as e:  # noqa: BLE001
            logger.warning("读取 agent limits 失败，使用默认: %s", e)
            return {
                "token_budget": 100000,
                "max_loop_rounds": 20,
                "goal_max_continuations": 2,
            }

    def _buildGateRunner(self):
        """门控装配的唯一实现点（`__init__` 与懒初始化路径同调它）。

        GoalGate 绑定 `goal_max_continuations`——**独立配置键**，与工具轮预算
        不共享尺度来源（同键两尺度正是 IterationGate 被判 scaled_sparse 的成因）。
        """
        from neurova.agent.gates import (
            DoomLoopGate,
            GateRunner,
            GoalGate,
            IterationGate,
            TokenBudgetGate,
        )
        from neurova.agent.loops.turn_run_state import resolveToolRoundBudget

        limits = self._load_agent_limits()
        # G2：GoalGate 默认进装配；`set_goal_gate` 只登记**规格**，不再持有第二份
        # 装配路径——规格与默认装配同在这一个构造点成型。
        # 轮次预算一律走 `_goalRoundBudget()`（配置单源 `goal_round_budget`）：
        # 默认装配路径也必须传它，否则 GoalGate 回落到 gates.py 的类字面量，
        # 上限再次不受任何配置键管辖。
        spec = getattr(self, "_goal_gate_spec", None)
        goal_gate = (
            self._buildGoalGate()
            if spec
            else GoalGate(
                maxContinuations=limits["goal_max_continuations"],
                max_rounds=self._goalRoundBudget(limits),
            )
        )
        return GateRunner([
            # 死循环门的两个在用阈值同样从配置单源取数——此前这里是 `DoomLoopGate()`
            # 无参构造，门限只活在 gates.py 的字面量上（同下面那条 GoalGate 注释
            # 点名的形态：上限不受任何配置键管辖）。
            DoomLoopGate(
                window_size=limits["doom_loop_window_size"],
                max_interrupts=limits["doom_loop_max_interrupts"],
            ),
            # T-04：门控阈值与轮内守卫同取一处派生，不再各读一遍配置键的不同尺度。
            IterationGate(max_rounds=resolveToolRoundBudget()),
            TokenBudgetGate(max_tokens=limits["token_budget"]),
            goal_gate,
            *list(getattr(self, "_extra_gate_specs", None) or []),
        ])

    def buildGateRunner(self):
        """本轮门控执行器——由 `_buildGateRunner`（装配单点）构造，转调它。

        每轮一份而不是实例一份：`DoomLoopGate` 的滑动窗口与中断计数是**会话级**
        状态，挂在单例 loop 上会让两个会话互相把对方的正常调用判成重复（Issue #268）。
        """
        return self._buildGateRunner()

    def _buildGoalGate(self):
        from neurova.agent.gates import GoalGate

        spec = getattr(self, "_goal_gate_spec", None) or {}
        return GoalGate(
            goal=spec.get("goal") or {},
            completion_check=spec.get("completion_check"),
            max_rounds=self._goalRoundBudget(),
        )

    def _goalRoundBudget(self, limits: Optional[dict] = None) -> int:
        """GoalGate 的轮次预算——单源取 `goal_round_budget`（跟随 max_loop_rounds）。

        `set_goal_gate(max_rounds=...)` 是**显式覆盖**，优先级高于配置；缺省（None）
        时一律回配置单源，不再留一份字面量默认值与之构成两处落点。
        """
        spec = getattr(self, "_goal_gate_spec", None) or {}
        override = spec.get("max_rounds")
        if override is not None:
            return int(override)
        values = limits if limits is not None else self._load_agent_limits()
        return int(values["goal_round_budget"])

    def registerGate(self, gate: Any) -> None:
        """登记**追加门控规格**（替换为门控实例，由装配单点每轮成型）。

        门控执行器每轮一份，故"给本轮追加一个门控"只能登记规格：直接往持久引用
        `_gate_runner` 上 `add_gate` 会被下一轮重建抹掉，是"只写不读"的断点形态。
        """
        if not hasattr(self, "_extra_gate_specs") or self._extra_gate_specs is None:
            self._extra_gate_specs: List[Any] = []
        self._extra_gate_specs.append(gate)

    def set_goal_gate(
        self, goal: Dict[str, Any], completion_check=None, max_rounds: Optional[int] = None
    ) -> None:
        """goal 模式：登记 GoalGate 规格（目标达成判定 + 轮次预算）。

        只登记规格，不在两条环里各持一份装配路径（教义第 6 条）。
        """
        self._goal_gate_spec = {
            "goal": goal,
            "completion_check": completion_check,
            "max_rounds": max_rounds,
        }

    def _ensure_gate_runner(self) -> None:
        """懒初始化门控执行器（__new__ 绕过 __init__ 的测试构造兼容）。"""
        if getattr(self, "_gate_runner", None) is None:
            self._gate_runner = self._buildGateRunner()

    def gateRunnerForExit(self) -> Any:
        """主出口使用的门控执行器（与工具轮同一个实例、同一份门控集合）。"""
        self._ensure_gate_runner()
        return getattr(self, "_gate_runner", None)

    # ── 轮级指纹（死循环签名的主体）────────────────────────────────────

    def _agentFingerprint(self) -> str:
        """创建者指纹（Issue #268 切片 C）：优先 agent_id，退到 name——两者皆无则空串。"""
        config = getattr(self.agent, "config", None)
        return str(
            getattr(config, "agent_id", None)
            or getattr(config, "name", None)
            or ""
        )

    @staticmethod
    def _fingerprintUserMessage(messages: List[Dict]) -> str:
        """本轮用户消息指纹：死循环签名绑定真实用户请求。

        新的用户消息 → 新指纹 → 跨轮的同名工具调用永不误判死循环；
        同一轮内重复相同调用（真死循环）仍然触发。
        """
        import hashlib as _hashlib

        last_user = next((m for m in reversed(messages) if m.get("role") == "user"), {})
        return _hashlib.md5(
            str(last_user.get("content") or "").encode("utf-8")
        ).hexdigest()[:12]

    @staticmethod
    def _imageUrlPart(offer: Dict) -> Dict:
        """闸门归一化好的字节 → OpenAI `image_url` 切片（降采样已在闸门里挡过 413）。

        两条环共用这一份：轮历史只有一种形状（OpenAI 形态），线协议形状归 provider 层。
        此前它在 `OpenAILoop` 上、`AnthropicLoop` 自产 Anthropic 内容块，同一能力两份
        形状就是 §6-76 收口的对象。
        """
        import base64

        return {"type": "image_url",
                "image_url": {"url": f"data:{offer['mime']};base64,"
                               f"{base64.b64encode(offer['bytes']).decode('ascii')}"}}

    @staticmethod
    def _merge_tool_call_delta(pending: List[Dict], delta: Dict) -> None:
        """按 index 合并流式 tool_calls 分片（两家 provider 同一形态）。

        兼容流式响应中一次工具调用被拆到多个 chunk：首片携带 id/name，
        后续片段 id/name 为 None、仅递增 arguments 文本。chat_stream 透传 delta
        的 index 字段，据此定位合并位置；无 index 时退化为追加新条目。
        """
        fn = delta.get("function") or {}
        index = delta.get("index")
        if index is None or index >= len(pending):
            pending.append(
                {
                    "id": delta.get("id"),
                    "type": delta.get("type") or "function",
                    "function": {
                        "name": fn.get("name") or "",
                        "arguments": fn.get("arguments") or "",
                    },
                }
            )
            return
        entry = pending[index]
        if delta.get("id"):
            entry["id"] = delta["id"]
        if fn.get("name"):
            entry["function"]["name"] = (entry["function"].get("name") or "") + fn["name"]
        if fn.get("arguments"):
            entry["function"]["arguments"] = (entry["function"].get("arguments") or "") + fn["arguments"]


    @staticmethod
    def _raise_for_error_dict(chunk: Dict) -> Exception:
        """把流式错误 dict 转成分类异常（error_type 优先，缺省按消息内容兜底分类）。

        实测缺陷：商汤 404 "model route not found" 曾以裸 RuntimeError 抛出，
        chat_pipeline 的供应商错误守卫认不出它 → 错误地 fallback 到 legacy
        再撞同一个坏模型（429/200 抽签，用户表现为"回复时有时无"）。
        """
        from neurova.llm_client import (
            LLMConnectionError,
            LLMAuthError,
            LLMBadRequestError,
            LLMRateLimitError,
            LLMServiceUnavailableError,
            TokenLimitExceeded,
        )

        raw = str(chunk.get("error") or "")
        message = f"LLM 流式调用失败: {chunk.get('error')}"
        error_type = str(chunk.get("error_type") or "")
        # 键为五类标准错误（error_mapping ErrorCategory.value，multi_model_client
        # 流内错误编码铁律 P0-1 的生产端）；旧四键保留兼容历史 dict。
        mapping = {
            "rate_limited": LLMRateLimitError,
            "rate_limit": LLMRateLimitError,
            "service_unavailable": LLMServiceUnavailableError,
            "connection_failed": LLMConnectionError,
            "connection": LLMConnectionError,
            "auth_failed": LLMAuthError,
            "auth": LLMAuthError,
            "bad_request": LLMBadRequestError,
            "token_limit": TokenLimitExceeded,
        }
        cls = mapping.get(error_type)
        if cls is None:
            # error_type 缺失时按 HTTP 语义兜底分类（供应商 404 模型不存在
            # 属请求构造错误，重试/换 fallback 路径无意义）
            low = raw.lower()
            if "404" in low or "not found" in low or "not_found" in low:
                cls = LLMBadRequestError
            elif "429" in low or "rate limit" in low or "too many requests" in low:
                cls = LLMRateLimitError
            elif "401" in low or "403" in low or "unauthorized" in low or "forbidden" in low:
                cls = LLMAuthError
        if cls is not None:
            return cls(message)
        return RuntimeError(message)

    @staticmethod
    def _toolSignatures(tool_calls: List[Dict]) -> str:
        """本轮调用签名（死循环门的比对主体）——单源一处拼法。

        `LLMResponse.tool_calls` 契约是 List[Dict]：llm_client 已把 SDK 对象转成 dict，
        执行链也按 dict 访问。属性式访问（`tc.name`）会在 dict 上抛 AttributeError 并
        让整轮回退 legacy、工具环丢失（2026-09-14 飞书事故），故这里只做 dict 取值。
        参数截 64 字符是既有口径（长参数不影响"同一调用重复了没有"的判定）。
        """
        return "|".join(
            f"{(tc.get('function') or {}).get('name', '')}:"
            f"{str((tc.get('function') or {}).get('arguments', ''))[:64]}"
            for tc in tool_calls
        )

    def _shouldReplayReasoning(self, reasoning: str) -> bool:
        """思考链是否随工具轮回放——默认关（`NEUROVA_REASONING_REPLAY=1` 开）+ 能力门。

        上移单源的理由：这条判定原来在 `OpenAILoop` 的流式与非流式两处各内联一遍，
        Anthropic 环要用就只能再抄第三遍；而"哪些 provider 禁止回传 reasoning_content"
        是一件事实在，两处漂移时不会有任何东西报红（教义第 6 条）。
        """
        if not reasoning:
            return False
        try:
            from neurova.agent.loops.reasoning_replay import should_replay_reasoning

            return should_replay_reasoning(
                str(getattr(self.agent.config, "llm_model", "") or "")
            )
        except Exception:  # noqa: BLE001 - 回放失败不影响工具轮
            logger.debug("reasoning 回放判定失败(忽略)", exc_info=True)
            return False

    def _accumulateRoundUsage(self, usage: Any) -> None:
        """把一次往返的 usage 累进**本轮**预算口 `agent._round_usage`。

        TokenBudgetGate 只读这一个数；不累计的那条环等于该闸永不触发（写了不读的反面：
        读了不写）。键集合与 `OpenAILoop` 一致，不新造第三份形状。

        进料有**两种形状**且都由生产路径给出：`LLMResponse.usage` 声明是 dict，而流式
        有一批 chunk 是原样透传的 SDK 对象（`llm_client.py:554` 的注释承认这一点）。
        归一只在这里做一次——此前 `OpenAILoop` 自带一份 `getattr` 归一、基类这份只认
        `.get()`，于是 Anthropic 环遇真网关的 SDK usage 直接抛 `AttributeError`
        （§6-77，H1 的 OpenRouter 活体实测）。
        """
        if not usage:
            return
        read = usage.get if isinstance(usage, dict) else lambda key, default=0: getattr(usage, key, default)
        try:
            prev = getattr(self.agent, "_round_usage", None) or {}
            self.agent._round_usage = {
                "prompt_tokens": int(prev.get("prompt_tokens", 0)) + int(read("prompt_tokens", 0) or 0),
                "completion_tokens": int(prev.get("completion_tokens", 0)) + int(read("completion_tokens", 0) or 0),
                "total_tokens": int(prev.get("total_tokens", 0)) + int(read("total_tokens", 0) or 0),
            }
        except (TypeError, ValueError):  # noqa: BLE001 - usage 形状异常不阻断回复
            logger.debug("usage 累计跳过（形状异常）: %r", usage)

    def _assess_stagnation(
        self, state: Any, round_reply: str, current_calls: List[tuple]
    ) -> bool:
        """判定本轮是否停滞：内容与上一轮高度相似，或工具调用签名完全重复。

        历史回复与上一轮签名从 `state` 取——它们属于本次调用，不属于 loop 实例
        （挂实例时交叠会话会互相污染，Issue #268）。

        空回复（纯工具轮）不参与内容停滞判定，避免误伤只调工具不说话的正常轮次。
        """
        from neurova.agent_loop_detection import calculate_similarity

        previous_calls = state.lastRoundCalls
        previous_replies = [r for r in state.roundReplies if r]
        if round_reply and previous_replies:
            if calculate_similarity is not None:
                for prev in previous_replies[-2:]:
                    if calculate_similarity(round_reply, prev) >= 0.8:
                        return True
            elif round_reply in previous_replies:
                return True
        if current_calls and current_calls == previous_calls:
            return True
        return False

    @abstractmethod
    async def predict_step(self, messages: List[Dict], tools: Optional[List[Dict]] = None, **kwargs) -> Any:
        """
        执行一步预测 - 子类必须实现

        参数:
            messages: 对话历史
            tools: 可用工具列表 (OpenAI Schema 格式)
            **kwargs: 额外参数；**`stream=True` 时必须返回异步生成器**，逐事件产出
            `{"type": "content"|"reasoning"|"tool_call"|"tool_result"|"done", ...}`。
            这条契约的消费点是 `chat_pipeline._call_loop_stream`（`async for`），
            返回 `LLMResponse` 会在那里 TypeError 并整轮回退 legacy——判据见
            `tests/unit/agent/test_anthropicLoopStreamContract.py`。

        返回:
            流式：异步生成器；非流式：LLMResponse 对象
        """
        # A-11：abstractmethod 只在实例化时拦截；动态构造/热加载等绕过 ABC
        # 检查的路径会落到这里——必须显式抛错，不得静默返回 None（空回复）
        raise NotImplementedError("子类必须实现 predict_step()")

    def buildToolRoundMessages(
        self,
        tool_calls: List[Dict],
        tool_messages: List[Dict],
        assistantText: str = "",
        reasoningText: Optional[str] = None,
    ) -> List[Dict]:
        """工具轮回放的协议合法块：assistant 声明 tool_calls + 逐条 tool 结果。

        OpenAI 协议要求每条 role="tool" 必须紧跟在声明它的 assistant.tool_calls
        之后。缺这条声明时，严格校验的网关会把整次续写判为
        `400 inference request is invalid`（商汤 400001 实测），宽容网关则照常
        返回——同一畸形序列在不同服务商下的两种表象，故协议正确性不能做成开关。

        reasoningText 仅在调用方过完 REASONING 能力门后传入：思考链回传被部分
        provider 显式禁止，声明 tool_calls 与被禁止的 reasoning_content 必须分档。
        """
        declaredCalls = [
            {
                "id": resolveCallId(tc),
                "type": (tc.get("type") or "function"),
                "function": {
                    "name": (tc.get("function") or {}).get("name", "") or "",
                    "arguments": (tc.get("function") or {}).get("arguments") or "{}",
                },
            }
            for tc in tool_calls
        ]
        assistantMessage: Dict[str, Any] = {
            "role": "assistant",
            "content": str(assistantText or ""),
            "tool_calls": declaredCalls,
        }
        if reasoningText:
            assistantMessage["reasoning_content"] = str(reasoningText)
        return [assistantMessage, *tool_messages]

    async def handle_tool_calls(self, tool_calls: List, messages: List[Dict]) -> List[Dict]:
        """
        处理工具调用 - 默认实现

        遍历 tool_calls，执行对应的 Skill，
        并将结果作为 tool 消息添加到 messages。

        参数:
            tool_calls: LLM 返回的工具调用列表
            messages: 当前对话历史

        返回:
            新的消息列表 (tool 消息)
        """
        new_messages = []

        # 声明制分组并行：按**每个工具自己的能力声明**分组，连续的资格项合成
        # 一批 gather（受单源上限截断），其余项各自成池串行。改前是 all-or-nothing
        # ——任一调用未声明 ⇒ 整轮全串行，于是"读三个文件 + 一次搜索 + 写一个文件"
        # 这种最常见的混合批一点并行都拿不到。
        #
        # 保序不变：分组只改**执行时序**，回装仍按原 tool_call 顺序（见下方回装段），
        # 前端 call/result 相邻配对契约不受影响。
        from neurova.agent.tool_coordinator import resolveBatchCapabilities
        from neurova.core.tool_capability import planToolBatches

        capabilities = resolveBatchCapabilities(tool_calls)

        batches = planToolBatches(
            tool_calls, capabilities, maxParallel=resolveParallelBudget()
        )
        _recordBatchShape(batches, self)

        outcomes: List = []
        for batch in batches:
            if batch.parallel:
                batch_outcomes = await asyncio.gather(
                    *(self._executeToolCallUnit(tc) for _, tc in batch.items)
                )
            else:
                batch_outcomes = [
                    await self._executeToolCallUnit(tc) for _, tc in batch.items
                ]
            outcomes.extend(batch_outcomes)

        # 回装（原序）：tool 消息 + call/result 展示记录（保持相邻配对契约）
        for msg, records in outcomes:
            new_messages.append(msg)
            self.agent.append_tool_messages(records)

        # P1-9：工具轮间隙排空插话邮箱——turn 进行中
        # 用户补充的消息以 user 角色并入消息序列，下一次采样即可见
        try:
            from neurova.core.steer_queue import get_steer_queue

            _sid = getattr(self.agent, "current_session_id", "") or ""
            for _steer_text in get_steer_queue().drain(str(_sid)):
                new_messages.append(
                    {"role": "user", "content": f"[用户插话] {_steer_text}"}
                )
        except Exception:  # noqa: BLE001 - 插话排空失败不影响工具结果回装
            logger.debug("steer 排空失败(忽略)", exc_info=True)

        # P2-5：排空子代理回传邮箱——后台子代理的完成
        # 结果逐轮可见；嵌套模式的完成摘要同样显式回灌
        try:
            from neurova.agent.mailbox import get_agent_mailbox

            _sid = getattr(self.agent, "current_session_id", "") or ""
            for _mail_text in get_agent_mailbox().drain(str(_sid)):
                new_messages.append(
                    {"role": "user", "content": _mail_text}
                )
        except Exception:  # noqa: BLE001
            logger.debug("子代理邮箱排空失败(忽略)", exc_info=True)

        return new_messages

    async def _executeToolCallUnit(self, tool_call: Dict) -> tuple:
        """单条调用的**配对结果单元**：无论如何都要换回一条 tool 结果。

        工具本身的失败已由执行咽喉转成失败正文回环（`native_tool_dispatch`）；这里
        管的是执行链自己炸掉的那一类（溢出分层、能力解析、记账）——那种调用若不
        补一条下文，`asyncio.gather` 会把同批其它已就绪的结果一起掀掉并整批上抛，
        本轮工具白跑，最后由上游回退 legacy 兜住（教义第 1 条点名的 consumer-side
        兜底形态）。不吞异常：如实回传失败正文并 warning 带栈。

        只捕 `Exception`：取消是 `BaseException`，用户停止必须原样上抛，本层不截。
        """
        try:
            return await self._execute_tool_call_worker(tool_call)
        except Exception as exc:  # noqa: BLE001 - 转成协议要求的配对结果，不是消失
            toolName = (tool_call.get("function") or {}).get("name", "unknown_tool")
            logger.warning(
                "工具 %s 的执行链异常（已回环为失败结果，同批其余调用不受牵连）: %s",
                toolName, exc, exc_info=True,
            )
            return self._failedToolOutcome(tool_call, exc)

    def _failedToolOutcome(self, tool_call: Dict, exc: BaseException) -> tuple:
        """为一条没有下文的生产调用合成诚实的失败结果（协议仍配对）。"""
        from neurova.agent import native_tool_dispatch as _native_dispatch

        toolName = (tool_call.get("function") or {}).get("name", "unknown_tool")
        callId = resolveCallId(tool_call)
        errorText = f"工具 {toolName} 执行链异常: {exc}"
        content = _safe_json_dumps(
            _native_dispatch.buildFailureToolBody(errorText, None)
        )
        toolMsg = {
            "role": "tool",
            "tool_call_id": callId,
            "name": toolName,
            "content": content,
        }
        records = [
            {
                "type": "tool_result",
                "tool_name": toolName,
                "tool_call_id": callId,
                "result": errorText,
                "success": False,
                "timestamp": datetime.now().isoformat(),
            }
        ]
        return toolMsg, records

    async def _execute_tool_call_worker(self, tool_call: Dict) -> tuple:
        """单条工具调用执行（P1-2 抽取，顺序无关的纯执行单元）。

        Returns:
            (tool_message, records)：tool_message 为回传 LLM 的 tool 消息；
            records 为 _tool_messages_list 的追加记录（tool_call + tool_result，
            由调用方按原序落位，保持前端配对展示契约）。
        """
        records: List[Dict] = []

        # 每次迭代使用独立的变量名，防止跨迭代器状态污染
        _tc_function_name = tool_call.get("function", {}).get("name", "unknown_tool")
        _tc_id = resolveCallId(tool_call)

        # G5-A：把"正在执行哪一次调用"绑进当前任务的上下文，供深层的执行咽喉
        # （治理判 ASK 时要给审批记录写上回投地址）读取。写入点放在这里而不是
        # 逐层加形参：这条链要穿 native_tool_dispatch → execute_tool → execute →
        # _execute_single_tool → _governance_precheck 五层，而只有最里层用得着它；
        # 且并行批次下每个 worker 跑在自己的 gather 子任务里，上下文副本天然隔离。
        from neurova.core.turn_context import set_turn_tool_call_id

        set_turn_tool_call_id(_tc_id)

        # [TOOLROBUST-A] 参数 JSON 解析单独 try：
        # 原实现在 try 外 json.loads，一遇到某条工具参数是非法 JSON，
        # handle_tool_calls 整体抛异常 → 被 loop 当作"工具调用失败"降级/回退到
        # 无工具路径，本轮全部工具静默丢失。
        # 现在解析失败只把错误作为该工具的结果回传给 LLM，让它自行纠正参数格式。
        # T-10a（工单 §11.2）：协议原文形态的 arguments。展示记录要把它逐字节带走——
        # 落盘只会写展示记录，重建 assistant.tool_calls 时须与 provider 回传形态对齐，
        # 从 `params` 反序列化重排出来的串会与 provider 的原文对不上。
        # `_has_arguments` 是"provider 到底给过没有"的**唯一**判据：下层必须显式
        # 按它判，不得反过来把"取值里那份默认 `{}`"当成"给过"（那判据恒真）。
        _raw_arguments = tool_call.get("function", {}).get("arguments", "{}")
        _has_arguments = "arguments" in (tool_call.get("function") or {})
        # 模型原始载荷在此冻成快照（`arguments` 记录的就是它）：执行面随后会剥离
        # taskName*，dict 形态若与 `_tc_arguments` 共用同一对象，剥离会就地改写
        # 原始载荷 —— "模型原样传入"与"剥离后的执行参数"必须各自成立。
        _tc_arguments_text = (
            _raw_arguments if isinstance(_raw_arguments, str)
            else _safe_json_dumps(_raw_arguments)
        )

        _tc_arguments = {}
        try:
            if isinstance(_raw_arguments, str):
                _tc_arguments = json.loads(_raw_arguments) if _raw_arguments.strip() else {}
            elif isinstance(_raw_arguments, dict):
                _tc_arguments = dict(_raw_arguments)
        except (json.JSONDecodeError, TypeError, ValueError) as _parse_err:
            _parse_error = f"工具 {_tc_function_name} 参数 JSON 解析失败: {_parse_err}"
            logger.warning(_parse_error)
            parse_msg = {
                "role": "tool",
                "tool_call_id": _tc_id,
                "name": _tc_function_name,
                "content": json.dumps({"error": _parse_error}),
            }
            records.append(
                {
                    "type": "tool_result",
                    "tool_name": _tc_function_name,
                    "tool_call_id": _tc_id,
                    "result": _parse_error,
                    "success": False,
                    "timestamp": datetime.now().isoformat(),
                }
            )
            return parse_msg, records

        # B3：剥离执行摘要参数——taskName* 是给时间轴 UI 的展示元数据，
        # 不属于工具真实参数；先提取再从 _tc_arguments 移除，SkillRegistry/
        # ToolRouter 两条执行通道都收不到
        _task_name_active = ""
        _task_name_complete = ""
        try:
            _task_name_active = str(_tc_arguments.pop("taskNameActive", "") or "")
            _task_name_complete = str(_tc_arguments.pop("taskNameComplete", "") or "")
        except AttributeError:
            pass

        # 记录工具调用消息（用于前端展示）
        _call_record = {
            "type": "tool_call",
            "tool_name": _tc_function_name,
            # T-10a：硬地址在调用侧也落一份。此前只有结果侧带 `tool_call_id`，
            # 配对信息随落盘丢失，读侧无从重建（工单 §11.2 点名的硬缺口）。
            "tool_call_id": _tc_id,
            "params": _tc_arguments,
            "timestamp": datetime.now().isoformat(),
        }
        # 协议原文形态（JSON 串），与 provider 回传逐字节同源；
        # provider 未给过该键时**不写** —— 补默认值等于替它声称"给过"。
        if _has_arguments:
            _call_record["arguments"] = _tc_arguments_text
        if _task_name_active:
            _call_record["task_name"] = _task_name_active
        records.append(_call_record)

        # 执行工具：一律经执行咽喉（ToolExecutor._execute_single_tool_inner）。
        # 原生链此前各自调用 SkillRegistry / ToolRouter，既拿不到客观票据与
        # on_tool_executed，又与文本链对同一失败工具给出不同的 success 值
        # （见 neurova/agent/native_tool_dispatch.py 的模块说明）。
        from neurova.agent.native_tool_dispatch import execute_native_tool

        outcome = await execute_native_tool(self.agent, _tc_function_name, dict(_tc_arguments))
        exec_result = SimpleNamespace(
            success=outcome["success"],
            data=outcome["result"],
            error=outcome["error"],
            metadata={},
        )

        # 构建 tool_result message
        if exec_result.success:
            content = _safe_json_dumps(exec_result.data) if exec_result.data is not None else "Success"
        else:
            # 失败正文不得只剩一句兜底串：`run_code` 这类"跑了但非零退出"的工具
            # 由执行面给出 `{success: False, error: None, stderr, exit_code}`，
            # 原实现只序列化 `error`（None），stderr/exit_code 在回环处蒸发。
            # 诊断键名单与正文构造**单源**在 `native_tool_dispatch`。
            from neurova.agent import native_tool_dispatch as _native_dispatch

            content = _safe_json_dumps(
                _native_dispatch.buildFailureToolBody(exec_result.error, exec_result.data)
            )

        # P1-#6（§5.6）：溢出分层——可重现大结果全文落工作区文件、
        # 消息体换预览+指针；不可重现（含 MCP/自创未声明）豁免原文直进。
        from neurova.core.tool_offload import apply_offload_policy, resolve_tool_reproducible

        _reproducible = resolve_tool_reproducible(self.agent, _tc_function_name)
        _offload = apply_offload_policy(
            tool_name=_tc_function_name,
            call_id=_tc_id,
            content=content,
            reproducible=_reproducible,
            workspace_root=getattr(self.agent, "workspace_path", None) or None,
        )
        content = _offload.content

        tool_msg = {
            "role": "tool",
            "tool_call_id": _tc_id,
            "name": _tc_function_name,
            "content": content,
        }

        # 记录工具执行结果（用于前端展示）
        # 完整保留 content（不预截断）：SSE 去重 key 基于完整内容 hash，
        # 截断会让"前缀相同正文不同"的结果（如同计划 create/mark_step）
        # 被误判为重复；展示层截断由 console._build_tool_events 的 [:500] 处理
        # P1-#6 条目增强：call_id 硬地址 + reproducible 落盘证据（防工具
        # 改标/删除后历史语义漂移）+ offload_path（溢出时全文真相指针）
        _result_record = {
            "type": "tool_result",
            "tool_name": _tc_function_name,
            "tool_call_id": _tc_id,
            "result": content if content else "执行完成",
            "success": exec_result.success,
            "timestamp": datetime.now().isoformat(),
            "reproducible": _reproducible,
            "offload_path": _offload.offload_path,
        }
        if _task_name_complete:
            _result_record["task_name"] = _task_name_complete
        records.append(_result_record)

        logger.info("Tool executed: %s, success=%s", _tc_function_name, exec_result.success)
        return tool_msg, records

