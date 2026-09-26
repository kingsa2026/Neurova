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


async def evaluateLoopExit(loop: "BaseAgentLoop", *, reply: str, roundUsage: Any, toolRound: int) -> LoopExitDecision:
    """主出口的门控求值（**唯一实现点**，两条路径共用）。

    为什么必须存在：工具轮的求值发生在 `if tool_calls:` 块内，而"模型不再调用
    工具"这一主出口在块外收口——假完成（停手且目标未达成）在那里一次都不会
    被看到。加调用方不改变这一点，缺的是求值点。

    ctx 带 `isLoopExit=True`，使 GoalGate 能区分"停在工具轮中途"与"自认为完成"：
    只有后者才是假完成，也只有后者才值得注入提示续跑。

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
        "round_signature": loop.turnRoundSignature(),
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
        """主出口的轮次签名。

        刻意**不带回复正文**，而是带续跑序号：出口上的"重复"与工具轮上的重复
        不是一回事——反复在出口停手是"假完成"，它的权威判据是目标门的续跑预算
        （有上限、理由可点名），不是死循环门。两处各管一件事，不设双重权威；
        反之若把正文当签名，模型两次给出同样措辞就会被死循环门提前掐断，
        预算耗尽的原因反而说不清。
        """
        from neurova.core.turn_context import get_turn_goal_continuations

        key = getattr(self, "_round_user_key", "") or ""
        return f"{key}:exit:{get_turn_goal_continuations()}"

    def gateRunnerForExit(self) -> Any:
        """主出口使用的门控执行器；子类未装配门控时返回 None（求值退化为正常收口）。"""
        return None

    @abstractmethod
    async def predict_step(self, messages: List[Dict], tools: Optional[List[Dict]] = None, **kwargs) -> Any:
        """
        执行一步预测 - 子类必须实现

        参数:
            messages: 对话历史
            tools: 可用工具列表 (OpenAI Schema 格式)
            **kwargs: 额外参数

        返回:
            LLMResponse 对象或原始响应
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

        outcomes: List = []
        for batch in planToolBatches(
            tool_calls, capabilities, maxParallel=resolveParallelBudget()
        ):
            if batch.parallel:
                batch_outcomes = await asyncio.gather(
                    *(self._execute_tool_call_worker(tc) for _, tc in batch.items)
                )
            else:
                batch_outcomes = [
                    await self._execute_tool_call_worker(tc) for _, tc in batch.items
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

