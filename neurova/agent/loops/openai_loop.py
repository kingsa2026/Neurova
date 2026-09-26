"""
OpenAI Loop - OpenAI 兼容模型适配循环

支持: GPT-4, GPT-3.5-turbo, GPT-4V, 以及所有 OpenAI 兼容 API
"""

import asyncio
import re

from neurova.core.logger import get_logger
from typing import TYPE_CHECKING, Any, Dict, List, Optional

# Agent 仅用于类型注解；运行时导入会与 agent_core 形成循环依赖
if TYPE_CHECKING:
    from neurova.agent_core import Agent

from neurova.agent.gates import StopDecision as _StopDecision

from neurova.agent.loops.base import BaseAgentLoop
from neurova.agent.loops.registry import register_loop
from neurova.agent.loops.turn_run_state import ROUND_BUDGET_FALLBACK, TurnRunState
from neurova.core import turn_context
from neurova.llm_client import LLMResponse

logger = get_logger(__name__)

#: 本轮门控已求值时的占位决策（BYPASS）——避免同轮二次求值污染 DoomLoopGate 窗口。
_BYPASS_DECISION = _StopDecision.bypass()


# ══════════════════════════════════════════════════════════════
# 工具降级判定（模块级，供测试与类方法共用）TOOLROBUST-B
# ══════════════════════════════════════════════════════════════
_AUTH_KEYS = re.compile(
    r"(invalid api key|authentication|unauthorized|forbidden|access denied|401|403|permission|credential)",
    re.IGNORECASE,
)
_HTTP_4XX_KEYS = re.compile(r"\b(400|422|409)\b")
_TOOL_KEYS = re.compile(r"(tool|function call|tool_choice|schema|parameter|argument)", re.IGNORECASE)
_SCHEMA_ERR_KEYS = re.compile(
    r"(missing|invalid).*(parameter|schema|argument|type)|parameters\.type", re.IGNORECASE
)


def _looks_like_unsupported_tools_error(err_str: str) -> bool:
    """判断错误文本是否属于"function calling 不被 API 支持"，避免误伤认证等非工具错误。

    返回 True 当且仅当：
    1. 错误文本不包含认证/权限关键词（401/403/"Invalid API key"等）；
    2. 命中 tools/function/schema/parameter 语义；
    3. 且同时命中 HTTP 4xx 状态码 或 明确 schema/参数缺失语义（如 "Missing required parameter"），
       以排除 "4000"/"400ms" 等无关数字误伤。
    """
    if not err_str:
        return False
    if _AUTH_KEYS.search(err_str):
        return False
    if not _TOOL_KEYS.search(err_str):
        return False
    return bool(_HTTP_4XX_KEYS.search(err_str) or _SCHEMA_ERR_KEYS.search(err_str))


def _raised_output_budget(cur: Any) -> int:
    """length 空回复重试时的输出预算放宽（病根在输出侧：思考吃满 max_tokens）。

    规则：翻倍、至少 +4096、绝对下限 8192、上限 65536；无效/缺失值取 8192。
    """
    try:
        cur_int = int(cur)
    except (TypeError, ValueError):
        return 8192
    if cur_int <= 0:
        return 8192
    return min(65536, max(cur_int * 2, cur_int + 4096, 8192))


class OpenAILoop(BaseAgentLoop):
    """
    OpenAI 模型 Loop

    处理 OpenAI 兼容 API 的调用流程，
    支持工具调用 (tool_calls) 和流式输出。
    """

    def __init__(self, agent: "Agent"):
        super().__init__(agent)
        # 轮次态不挂实例：它是"一次 chat 调用的状态"，而 loop 是 per-agent 单例
        # （agent_core 经 loop_manager.get_loop() 装配）——同一 agent 上两个会话
        # 交叠时，后进入者在 predict_step 入口的清零会改写前者的轮次预算与
        # 停滞计数（实测：被交叠会话的调用次数由 3 变 4）。故入口构造
        # TurnRunState 并逐轮传递，见 turn_run_state.py。
        # goal 模式门控由调用方经 set_goal_gate 登记规格，装配仍在 _buildGateRunner 单点。
        self._goal_gate_spec = None
        # 追加门控规格（`registerGate` 登记，装配单点每轮成型）
        self._extra_gate_specs: List[Any] = []
        # 门控执行器：实例上的引用**就是本轮判定面**（predict_step 入口重建、
        # 交给 `TurnRunState` 持有），装配单点在 `_buildGateRunner`。
        self._gate_runner = self._buildGateRunner()
        _limits = self._load_agent_limits()
        logger.info(
            "OpenAILoop initialized for agent: %s (max_rounds=%s, token_budget=%s, goal_continuations=%s)",
            agent.config.name, _limits["max_loop_rounds"], _limits["token_budget"],
            _limits.get("goal_max_continuations"),
        )

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
        `max_rounds` 不在此绑定：工具轮预算的单源是 IterationGate 与
        `_max_tool_rounds`，GoalGate 保留该参数只为门控自身契约。
        """
        from neurova.agent.gates import (
            DoomLoopGate,
            GateRunner,
            GoalGate,
            IterationGate,
            TokenBudgetGate,
        )

        limits = self._load_agent_limits()
        # G2：GoalGate 默认进装配（目标续跑预算绑定独立配置键 `goal_max_continuations`）；
        # `set_goal_gate` 只登记**规格**（显式 goal / completion_check / max_rounds），
        # 不再持有第二份装配路径——规格与默认装配同在这一个构造点成型。
        spec = getattr(self, "_goal_gate_spec", None)
        goal_gate = (
            self._buildGoalGate()
            if spec
            else GoalGate(maxContinuations=limits["goal_max_continuations"])
        )
        return GateRunner([
            DoomLoopGate(),
            IterationGate(max_rounds=limits["max_loop_rounds"]),
            TokenBudgetGate(max_tokens=limits["token_budget"]),
            goal_gate,
            *list(getattr(self, "_extra_gate_specs", None) or []),
        ])

    def buildGateRunner(self):
        """本轮门控执行器——由 `_buildGateRunner`（装配单点）构造，转调它。

        每轮一份而不是实例一份：`DoomLoopGate` 的滑动窗口与中断计数是**会话级**
        状态，挂在单例 loop 上会让两个会话互相把对方的正常调用判成重复；
        这里另建一份是为了让新增门控（规格经 `set_goal_gate` 登记）落到规格上，
        而判定面永远取自本轮 state。
        """
        return self._buildGateRunner()

    def _buildGoalGate(self):
        from neurova.agent.gates import GoalGate

        spec = self._goal_gate_spec or {}
        return GoalGate(
            goal=spec.get("goal") or {},
            completion_check=spec.get("completion_check"),
            max_rounds=spec.get("max_rounds", 15),
        )

    def registerGate(self, gate: Any) -> None:
        """登记**追加门控规格**（替换为门控实例，由装配单点每轮成型）。

        门控执行器每轮一份（Issue #268 轮次态归属：会话级态不得挂在单例 loop 上），
        故"给本轮装配追加一个门控"只能登记规格，不能持有实例——直接往持久引用
        `_gate_runner` 上 `add_gate` 会被下一轮重建抹掉，是"只写不读"的断点形态。
        门控实例由调用方提供（同一门控在每轮装配中各出现一次，互不共享会话态）。
        """
        if not hasattr(self, "_extra_gate_specs") or self._extra_gate_specs is None:
            self._extra_gate_specs: List[Any] = []
        self._extra_gate_specs.append(gate)

    def set_goal_gate(self, goal: Dict[str, Any], completion_check=None, max_rounds: int = 15) -> None:
        """goal 模式：登记 GoalGate 规格（目标达成判定 + 轮次预算）。

        只登记规格，不再持有第二份装配路径（修复教义第 6 条）。
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

    def _assess_stagnation(
        self, state: TurnRunState, round_reply: str, current_calls: List[tuple]
    ) -> bool:
        """判定本轮是否停滞：内容与上一轮高度相似，或工具调用签名完全重复。

        历史回复与上一轮签名从 `state` 取——它们属于本次调用，不属于 loop 实例
        （挂实例时交叠会话会互相污染，Issue #268）。

        空回复（纯工具轮）不参与内容停滞判定，避免误伤只调工具不说话的正常轮次。
        """
        try:
            from neurova.agent_loop_detection import calculate_similarity
        except ImportError:  # pragma: no cover - 模块缺失时退化为仅签名判定
            calculate_similarity = None

        previous_calls = state.lastRoundCalls
        # 2026-09-07 根因修复（audit P2-10）：原 [:-1] 把紧邻上一轮切掉，
        # 逐轮重复检测永远失效；append 在本方法调用之后执行，无需再切
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

    # ══════════════════════════════════════════════════════════════
    # 工具降级健壮性（TOOLROBUST-B）
    # ══════════════════════════════════════════════════════════════
    def _is_tools_rejected_error(self, err_str: str) -> bool:
        """精确判断是否为"function calling 不被 API 支持"的错误，避免误伤认证等非工具错误。

        委托给模块级 _looks_like_unsupported_tools_error 以复用同一判定逻辑。
        返回 True 当且仅当：非认证/权限错误，且命中工具语义 + HTTP 4xx 或 schema 参数缺失语义。
        """
        return _looks_like_unsupported_tools_error(err_str)

    def _append_tool_hint(self, messages: List[Dict]) -> List[Dict]:
        """降级后把文本调用教学合并进 system 提示（不新增消息体，保持 system 靠前）。

        复用 context.orchestrator.get_tool_call_format_hint()；任何异常都静默跳过，
        避免降级路径再次因导入/内容问题抛异常。
        """
        try:
            from neurova.context.orchestrator import get_tool_call_format_hint

            hint = get_tool_call_format_hint()
        except Exception:
            hint = ""
        if not hint:
            return messages
        msgs = list(messages)
        for i, m in enumerate(msgs):
            if isinstance(m, dict) and m.get("role") == "system":
                msgs[i] = {**m, "content": (m.get("content") or "") + hint}
                return msgs
        msgs.insert(0, {"role": "system", "content": hint})
        return msgs

    def _startTurnState(self, messages: List[Dict]) -> TurnRunState:
        """入口构造本轮轮次态（`_predict_*` 被直接驱动时的兜底同源）。

        门控执行器就地取规格装配（单点 `_buildGateRunner`），并写回实例引用：
        读取面与判定面必须是**同一份**，否则经 `_gate_runner` 追加的门控与
        `DoomLoopGate` 的窗口都只落在其中一份上。
        """
        _runner = self._buildGateRunner()
        self._gate_runner = _runner
        state = TurnRunState(
            roundUserKey=self._fingerprintUserMessage(messages),
            gateRunner=_runner,
        )
        state.maxToolRounds = getattr(self, "_max_tool_rounds", None) or ROUND_BUDGET_FALLBACK
        return state

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

    async def predict_step(
        self, messages: List[Dict], tools: Optional[List[Dict]] = None, stream: bool = False, **kwargs
    ) -> Any:
        """
        执行一步预测

        参数:
            messages: 对话历史
            tools: 可用工具列表 (OpenAI Schema 格式)
            stream: 是否流式输出
            **kwargs: 额外参数

        返回:
            LLMResponse 对象 (非流式) 或 AsyncGenerator (流式)
        """
        # 本轮轮次态：入口构造、逐轮传递、随轮释放。
        # 不得写回 self——loop 是 per-agent 单例，实例态会让交叠会话互相清零
        # 彼此的轮次预算（Issue #268，缺陷 A）。
        # 工具轮上限读取设置（与 IterationGate 同源；尺度收口属 T-04，本片不动口径）
        try:
            from neurova.security.agent_limits_settings import get_effective_limits

            self._max_tool_rounds = get_effective_limits()["max_loop_rounds"] // 2
        except Exception:  # noqa: BLE001 - 设置不可读不阻断对话
            self._max_tool_rounds = ROUND_BUDGET_FALLBACK
        # 门控执行器每轮一份：**读取面就是判定面**（同一份实例）。
        # `DoomLoopGate` 的窗口与中断计数是会话级态，挂在单例 loop 上会让两个会话
        # 互相把对方的正常调用判成重复（Issue #268 缺陷 A）；但同一轮内两条路径
        # 各建一份，会让窗口在同一轮内不再累计、经实例追加的门控只落在其中一份上。
        # 故入口重建一次、实例引用即本轮判定面，`TurnRunState.gateRunner` 直接持有它。
        _round_gate_runner = self._buildGateRunner()
        self._gate_runner = _round_gate_runner
        state = TurnRunState(
            roundUserKey=self._fingerprintUserMessage(messages),
            gateRunner=_round_gate_runner,
        )
        state.maxToolRounds = getattr(self, "_max_tool_rounds", None) or ROUND_BUDGET_FALLBACK
        # 2026-09-07 回归修复：_round_usage 是"本轮 token 预算"语义，必须
        # 每次用户请求重置——原修复只加了写入方，忘了重置，跨请求无限累计
        # 导致第二轮 LLM 调用被 TokenBudgetGate 掐死（回复空白回归）
        self.agent._round_usage = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }
        # 同理由：目标续跑次数是"本轮"语义，跨请求残留会让下一轮一开局就
        # 撞上已耗尽的续跑预算（目标门在出口直接 TERMINATE，回复被掐断）。
        turn_context.reset_turn_goal_continuations()
        request_params = {
            "messages": messages,
            "stream": stream,
        }

        # 添加工具（如果 API 不支持则跳过）
        if tools and state.toolsSupported:
            # 过滤格式不正确的工具（缺少 function 字段会触发 400 错误）
            valid_tools = [t for t in tools if isinstance(t, dict) and "function" in t]
            if valid_tools:
                request_params["tools"] = valid_tools
                request_params["tool_choice"] = kwargs.get("tool_choice", "auto")
            else:
                logger.warning("所有工具格式不正确，跳过 tools 注入")
        elif tools and not state.toolsSupported:
            logger.info(f"跳过 tools 注入：API 不支持 function calling")

        # 添加其他参数
        for key in ["temperature", "max_tokens", "top_p", "frequency_penalty"]:
            if hasattr(self.agent.llm_client.config, key):
                value = getattr(self.agent.llm_client.config, key)
                if value is not None:
                    request_params[key] = value

        # 思考档位透传（2026-09-08 AMD 推理透传）：前端深度选择器
        # thinking_effort（light/standard/deep）经管线 metadata → 此处
        # request_params → LLMClient._build_request_params 按 provider
        # compat 声明映射为 reasoning_effort（未声明网关不注入，防 400）。
        # B1-3：思考开关两级旋钮同通道透传（enable_thinking/thinking_budget
        # 经 compat.supports_thinking_toggle 门控注入）。
        for key in ["thinking_effort", "reasoning_effort", "thinking_enabled", "thinking_budget"]:
            if key in kwargs and kwargs[key] is not None:
                request_params[key] = kwargs[key]

        # 执行预测（如果 tools 导致 API 400，回退到无 tools 模式）
        try:
            if stream:
                return self._predict_stream(request_params, state)
            else:
                return await self._predict_normal(request_params, state)
        except Exception as e:
            err_str = str(e)
            # [TOOLROBUST-B] 精确判定 400：
            # 原实现用宽泛子串 "400"/"Invalid"/"Missing" 判断，会把 "Invalid API key"
            # 等认证错误误判为"工具不被支持"而静默降级，掩盖真实错误、另本轮无工具可用。
            # 现在：先排除认证/权限类错误，再要求同时命中 HTTP 4xx 状态码 + tools 语义才算降级。
            if tools and self._is_tools_rejected_error(err_str):
                logger.warning(
                    "[TOOLROBUST-B] function calling 疑似不被 API 支持，本轮降级为无 tools 重试并注入文本教学。错误: %s",
                    e,
                )
                state.toolsSupported = False
                # 标记降级事件，供可观测（agent.ui / 监控可读）
                try:
                    self.agent.append_tool_event({"type": "tools_degraded", "reason": err_str[:200]})
                except Exception:
                    pass
                request_params.pop("tools", None)
                request_params.pop("tool_choice", None)
                # 降级后注入文本调用教学，避免模型在无 tools 状态下完全不会调工具
                request_params["messages"] = self._append_tool_hint(request_params["messages"])
                if stream:
                    return self._predict_stream(request_params, state)
                else:
                    return await self._predict_normal(request_params, state)
            raise

    async def _predict_normal(self, request_params: Dict, state: TurnRunState = None) -> LLMResponse:
        """普通预测 (非流式)。

        [TOOLROBUST-B] 自动降级：带 tools 的请求若被 API 拒绝（工具型 400），
        去掉 tools 并注入文本调用教学后重试一次，避免整轮崩溃且弱 provider 仍有工具通道。

        `state` 缺省时按本次请求现建一份（直接驱动本方法时每调用即一整轮）。
        """
        if state is None:
            state = self._startTurnState(request_params.get("messages") or [])
        try:
            response = await self.llm_client.chat(**request_params)
        except Exception as e:
            err_str = str(e)
            if request_params.get("tools") and self._is_tools_rejected_error(err_str):
                logger.warning(
                    "[TOOLROBUST-B] function calling 疑似不被 API 支持，本轮降级为无 tools 重试并注入文本教学。错误: %s",
                    e,
                )
                state.toolsSupported = False
                try:
                    self.agent.append_tool_event({"type": "tools_degraded", "reason": err_str[:200]})
                except Exception:
                    pass
                request_params.pop("tools", None)
                request_params.pop("tool_choice", None)
                # 降级后注入文本调用教学，避免模型在无 tools 状态下完全不会调工具
                request_params["messages"] = self._append_tool_hint(request_params["messages"])
                response = await self.llm_client.chat(**request_params)
            else:
                raise

        # 记录思考过程（用于前端展示）
        reasoning_content = getattr(response, "reasoning_content", None)
        if reasoning_content:
            # 将思考过程存储到 agent 上，供 chat() 方法读取
            self.agent.set_current_reasoning(reasoning_content)
            logger.info("🧠 捕获思考过程: %s 字符", len(reasoning_content))

        # 处理 tool_calls（部分 provider 响应无 tool_calls 字段，需容错）
        tool_calls = getattr(response, "tool_calls", None)
        if tool_calls:
            state.toolRounds += 1
            _max_rounds = getattr(self, "_max_tool_rounds", None) or ROUND_BUDGET_FALLBACK
            if state.toolRounds > _max_rounds:
                # 2026-09-07 根因修复（audit P2-8）：原实现只打日志继续递归，
                # 实际上限是 IterationGate 的 20；现在超限真正终止
                logger.warning("工具调用轮次超过上限 (%s)，终止递归", state.toolRounds)
                return response
            # P2-5：非流式路径同样过门控（TERMINATE 即终止递归）
            from neurova.agent.gates import StopAction as _SA

            # LLMResponse.tool_calls 契约是 List[Dict]（llm_client 已把 SDK 对象转
            # dict，base.py 执行链同样按 dict 访问）；原属性访问 tc.name 在 dict 上
            # AttributeError → 整轮回退 legacy、工具环丢失（2026-09-14 飞书事故）
            _tool_sigs = "|".join(
                f"{(tc.get('function') or {}).get('name', '')}:"
                f"{str((tc.get('function') or {}).get('arguments', ''))[:64]}"
                for tc in tool_calls
            )
            # 门控 ctx 走本轮 state（轮次计数/签名不读实例——Issue #268）；
            # 键集合与流式路径对齐（RC-3）：缺键会让 TokenBudgetGate / GoalGate
            # 在非流式路径恒不可触发。
            # **每轮只求值一次**：`DoomLoopGate.check()` 会自行把本轮签名记入窗口，
            # 同轮重复求值等于把自己的签名判成"重复"（实测：同轮二次求值 → 第二轮
            # 即被误判死循环终止）。出口续跑经 `_settleMainExit` 重入本方法时轮次号
            # 未变，故按轮次号去重。
            _interrupt_prompt = ""
            if state.gatedRound != state.toolRounds:
                state.gatedRound = state.toolRounds
                _gd = state.gateRunner.on_round_end(state.gateContext(
                    _tool_sigs,
                    round_reply=getattr(response, "content", "") or "",
                    round_usage=getattr(self.agent, "_round_usage", None) or {},
                    goal=self.resolveTurnGoal() or {},
                ))
                if _gd is not None and _gd.action == _SA.TERMINATE:
                    logger.warning("门控 %s 终止非流式循环: %s", _gd.gate_name, _gd.reason)
                    return response
                if _gd is not None and _gd.action == _SA.INTERRUPT_AND_CONTINUE:
                    _interrupt_prompt = _gd.continuation_prompt

            logger.info("LLM returned %s tool calls (round %s)", len(tool_calls), state.toolRounds)

            # 执行工具
            tool_messages = await self.handle_tool_calls(tool_calls, request_params["messages"])

            # P2-6：工具轮间回放推理链——reasoning_content 默认关
            # （NEUROVA_REASONING_REPLAY=1 开）+ REASONING 能力门，部分 provider
            # 显式禁止回传；而 assistant.tool_calls 声明是无条件的协议要求，
            # 缺它会被严格网关判 400（与流式路径同一 buildToolRoundMessages）
            _round_reasoning = reasoning_content or ""
            _replayReasoning = False
            if _round_reasoning:
                try:
                    from neurova.agent.loops.reasoning_replay import should_replay_reasoning

                    _replayReasoning = should_replay_reasoning(
                        str(getattr(self.agent.config, "llm_model", "") or "")
                    )
                except Exception:  # noqa: BLE001 - 回放失败不影响工具轮
                    logger.debug("reasoning 回放判定失败(忽略)", exc_info=True)

            # 将工具结果添加到消息（连同协议要求的 assistant 声明）
            request_params["messages"].extend(
                self.buildToolRoundMessages(
                    tool_calls,
                    tool_messages,
                    assistantText=getattr(response, "content", "") or "",
                    reasoningText=_round_reasoning if _replayReasoning else None,
                )
            )

            # RC-3：软干预与流式路径同一行为（原实现直接丢弃 INTERRUPT，
            # 同一条门控意见一条路执行、一条路扔掉）；注入点与流式一致——工具
            # 结果入历史之后、续跑之前。
            if _interrupt_prompt:
                request_params["messages"].append(
                    {"role": "user", "content": _interrupt_prompt}
                )
                logger.info("门控 %s 软干预（非流式，提示已注入消息序列）: %s", _gd.gate_name, _gd.reason)

            # 递归调用，直到没有 tool_calls
            return await self._predict_normal(request_params, state)

        return await self._settleMainExit(request_params, response, state)

    async def _settleMainExit(
        self, request_params: Dict, response: LLMResponse, state: TurnRunState
    ) -> Any:
        """非流式路径的主出口收口（RC-1：出口也过门）。

        "模型不再调用工具"是循环的主出口，也是假完成的唯一可识别位置——
        工具轮内求值永远看不到它。判定与门控经基类 `evaluateLoopExit`
        （单一实现点，流式路径同调它）。

        `state` 必须随调用链**继续传递**（Issue #268）：出口续跑是本轮的续跑，
        不传 state 会让续跑段重建一份轮次态，其门控执行器取自实例引用
        `self._gate_runner`——那是**最后进入本 loop 的会话**留下的，交叠会话下
        等于把别人的门控窗口接过来（实测：续跑轮的调用签名落到另一会话窗口，
        被死循环门误判终止）。
        """
        from neurova.agent.loops.base import LOOP_CONTINUE, evaluateLoopExit

        decision = await evaluateLoopExit(
            self,
            reply=getattr(response, "content", "") or "",
            roundUsage=getattr(self.agent, "_round_usage", None) or {},
            toolRound=state.toolRounds,
        )
        if decision.action == LOOP_CONTINUE:
            request_params["messages"].append(
                {"role": "user", "content": decision.continuation_prompt}
            )
            return await self._predict_normal(request_params, state)
        if decision.action != "done":
            logger.warning("主出口门控 %s 终止: %s", decision.gate_name, decision.reason)
        return response

    async def _predict_stream(self, request_params: Dict, state: TurnRunState = None) -> Any:
        """流式预测入口（P1-1① 溢出恢复包装）。

        请求打开即上下文溢出（TokenLimitExceeded，且尚无内容产出）→ 折叠
 消息后单次重试；重试仍溢出原样抛出，
        不做第二次重试（防循环）。流中途溢出（已有内容）原样抛——重试会
        造成内容重复。
        """
        from neurova.context.recovery import (
            compact_messages_for_overflow,
            is_context_overflow_error,
        )

        if state is None:
            state = self._startTurnState(request_params.get("messages") or [])
        first_error: Optional[BaseException] = None
        got_content = False
        try:
            async for event in self._predict_stream_once(request_params, state):
                if isinstance(event, dict) and event.get("type") == "content" and event.get("data"):
                    got_content = True
                # 修3（2026-09-09）：输出预算耗尽防线——finish_reason=length
                # 且正文为空（思考模型把 max_tokens 吃满，HTTP 200 无异常，
                # TokenLimitExceeded 溢出恢复永远不触发）。放宽输出预算+
                # 思考降级+压缩消息后单次重试；重试仍空则原样转发该 done
                # （不二次重试，防循环）。
                if (
                    isinstance(event, dict)
                    and event.get("type") == "done"
                    and not got_content
                    and not request_params.get("_length_empty_retried")
                    and not (event.get("reply") or "").strip()
                    and str(event.get("finish_reason") or "").lower() in ("length", "max_tokens")
                ):
                    compact, info = compact_messages_for_overflow(request_params.get("messages") or [])
                    # 可动旋钮判定：输出预算（max_tokens）或思考档位任一存在即值得
                    # 重试；两者皆无且输入无可折叠 → 不重试（防空转循环）。
                    # 病根在输出侧（思考吃满 max_tokens），重试必须同步放宽输出
                    # 预算+思考降级，只压缩输入会原样撞同一堵墙。
                    _budget_knobs = "max_tokens" in request_params or any(
                        k in request_params
                        for k in ("thinking_enabled", "thinking_effort", "reasoning_effort", "thinking_budget")
                    )
                    if info.get("folded_count", 0) > 0 or _budget_knobs:
                        logger.warning(
                            "[CTX_RECOVERY] 输出预算耗尽(length)且正文为空，放宽输出预算+思考降级后单次重试（折叠 %d 条）",
                            info.get("folded_count", 0),
                        )
                        yield {
                            "type": "reasoning",
                            "data": "检测到回复为空（输出预算被思考过程耗尽），正在放宽输出预算并压缩上下文后重试…",
                        }
                        # 被折叠消息摘要回写池（fire-and-forget，与溢出恢复同构）
                        try:
                            pool = getattr(
                                getattr(self.agent, "context_orchestrator", None), "context_pool", None
                            )
                            if pool is not None:
                                asyncio.ensure_future(
                                    pool.rollup_overflow_digest(info.get("folded_messages") or [])
                                )
                        except Exception:
                            logger.debug("length 恢复摘要回写跳过", exc_info=True)
                        retry_params = {
                            **request_params,
                            "messages": compact,
                            "_length_empty_retried": True,
                            # 输出侧放宽：思考关停（预算让位给正文）；仅当原请求
                            # 显式带预算/档位键时才覆写对应键，不凭空注入预算。
                            "thinking_enabled": False,
                        }
                        if "max_tokens" in request_params:
                            retry_params["max_tokens"] = _raised_output_budget(
                                request_params.get("max_tokens")
                            )
                        if "thinking_effort" in request_params:
                            retry_params["thinking_effort"] = "light"
                        if "reasoning_effort" in request_params:
                            retry_params["reasoning_effort"] = "low"
                        retry_params.pop("thinking_budget", None)
                        async for ev in self._predict_stream(retry_params, state):
                            # 重试仍空 → 补可见提示（杜绝空气泡），done.reply 同步改写
                            # 使 ctx.reply 非空、落盘与前端气泡均有内容（闭环）
                            if (
                                isinstance(ev, dict)
                                and ev.get("type") == "done"
                                and not (ev.get("reply") or "").strip()
                            ):
                                notice = (
                                    "⚠️ 未能生成回复：输出预算被思考过程占满（finish_reason=length），"
                                    "压缩上下文重试后仍未产出正文。建议切换非思考模型，"
                                    "或在模型设置中调大最大输出 token。"
                                )
                                yield {"type": "content", "data": notice}
                                ev = {**ev, "reply": notice}
                            yield ev
                        return
                yield event
            return
        except BaseException as e:  # noqa: BLE001 - 统一捕获后按类型分流
            first_error = e

        # 流中途已产出内容 → 重试会造成内容重复，原样抛
        if got_content or not is_context_overflow_error(first_error):
            raise first_error

        messages = request_params.get("messages") or []
        compact, info = compact_messages_for_overflow(messages)
        if info.get("folded_count", 0) <= 0:
            raise first_error  # 无可折叠内容，恢复无意义
        logger.warning(
            "[CTX_RECOVERY] 上下文溢出，折叠 %d 条消息后单次重试（%d → %d）",
            info["folded_count"], info["original_count"], info["compact_count"],
        )
        # 增强①：被折叠消息生成摘要回写池（fire-and-forget，不阻塞重试；
        # 无池/无摘要器 no-op——rollup 内部自兜底）
        try:
            pool = getattr(
                getattr(self.agent, "context_orchestrator", None), "context_pool", None
            )
            if pool is not None:
                asyncio.ensure_future(
                    pool.rollup_overflow_digest(info.get("folded_messages") or [])
                )
        except Exception:
            logger.debug("溢出摘要回写跳过", exc_info=True)
        retry_params = {**request_params, "messages": compact}
        async for event in self._predict_stream_once(retry_params, state):
            yield event

    async def _predict_stream_once(self, request_params: Dict, state: TurnRunState = None) -> Any:
        """流式预测 — 实时 yield 结构化事件（content / reasoning / tool_call / tool_result / done）。

        底层 chat_stream 逐 chunk 产出 LLMResponse 对象（见 llm_client.chat_stream_async），
        失败时被 multi_model_client.chat_stream 包装为 {"error": ...} 字典。本方法负责：
        1. 把 chunk 实时转成 typed 事件（reasoning/content 逐片段转发，思考过程不再整块滞后）；
        2. 流式 tool_calls 分片按 index 合并为完整调用（OpenAI 兼容流中首片带 id/name，
           后续片段仅携带 arguments 碎片），流结束后执行并产出 tool_result 事件；
        3. 工具执行后以流式续写（递归本方法），直到模型不再调用工具；
        4. 整个生成器恰好 yield 一个 done 事件（携带最终轮正文快照）；
        5. error 字典抛 RuntimeError 交由管线降级，而不是静默返回空回复。
        """
        if state is None:
            state = self._startTurnState(request_params.get("messages") or [])
        reply_parts: List[str] = []
        reasoning_parts: List[str] = []
        pending_tool_calls: List[Dict] = []
        finish_reason = ""
        # P2-4d：流式 usage 聚合（OpenAI 流式 usage 在最后一 chunk 携带全量）
        round_usage = None

        # 内部控制标志不透传 LLM 链路（_build_request_params 虽忽略未知键，
        # 但泄漏进 provider 兼容层属于未定义行为）
        stream_kwargs = {
            k: v for k, v in request_params.items()
            if k not in ("messages", "stream", "_length_empty_retried")
        }
        async for chunk in self.llm_client.chat_stream(request_params["messages"], **stream_kwargs):
            if isinstance(chunk, dict):
                if chunk.get("retry_status"):
                    # 429 重试/切换过程事件：转成 typed
                    # 事件供管线/前端倒计时；reset=半截回复作废，本轮已累积的
                    # content/reasoning/未执行 tool_calls 全部清空后重来
                    payload = chunk["retry_status"]
                    if payload.get("reset"):
                        reply_parts.clear()
                        reasoning_parts.clear()
                        pending_tool_calls.clear()
                    yield {"type": "retry_status", "data": payload}
                    continue
                if chunk.get("error"):
                    raise self._raise_for_error_dict(chunk)
                continue
            content = getattr(chunk, "content", "") or ""
            if content:
                reply_parts.append(content)
                yield {"type": "content", "data": content}
            if getattr(chunk, "usage", None):
                u = chunk.usage
                round_usage = {
                    "prompt_tokens": getattr(u, "prompt_tokens", 0) or 0,
                    "completion_tokens": getattr(u, "completion_tokens", 0) or 0,
                    "total_tokens": getattr(u, "total_tokens", 0) or 0,
                }
                # 2026-09-07 根因修复（audit P2-8）：agent._round_usage 全仓无
                # 写入方 → TokenBudgetGate 恒死门；从流式 usage 聚合写入
                prev = getattr(self.agent, "_round_usage", None) or {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
                self.agent._round_usage = {
                    "prompt_tokens": prev.get("prompt_tokens", 0) + round_usage["prompt_tokens"],
                    "completion_tokens": prev.get("completion_tokens", 0) + round_usage["completion_tokens"],
                    "total_tokens": prev.get("total_tokens", 0) + round_usage["total_tokens"],
                }
            rtext = getattr(chunk, "reasoning_content", None)
            if rtext:
                reasoning_parts.append(rtext)
                yield {"type": "reasoning", "data": rtext}
            for tc_delta in getattr(chunk, "tool_calls", None) or []:
                self._merge_tool_call_delta(pending_tool_calls, tc_delta)
            if getattr(chunk, "finish_reason", None):
                finish_reason = chunk.finish_reason

        # 保存思考过程到 agent（供 post-chat 持久化/前端展示）
        if reasoning_parts:
            reasoning_text = "".join(reasoning_parts)
            self.agent.set_current_reasoning(reasoning_text)
            logger.info("🧠 捕获流式思考过程: %s 字符", len(reasoning_text))

        if pending_tool_calls:
            state.toolRounds += 1
            logger.info(
                "LLM returned %s tool calls (stream round %s)",
                len(pending_tool_calls), state.toolRounds,
            )
            for tc in pending_tool_calls:
                yield {"type": "tool_call", "data": tc}

            tool_messages = await self.handle_tool_calls(pending_tool_calls, request_params["messages"])
            for tm in tool_messages:
                yield {"type": "tool_result", "data": tm}

            # 停滞检测：记录本轮回复与调用签名，重复时注入提示，连续停滞终止
            round_reply = "".join(reply_parts).strip()
            current_calls = [
                ((tc.get("function") or {}).get("name", ""), (tc.get("function") or {}).get("arguments", ""))
                for tc in pending_tool_calls
            ]
            stagnant = self._assess_stagnation(state, round_reply, current_calls)
            state.roundReplies.append(round_reply)
            state.lastRoundCalls = current_calls

            # P2-5：门控检查（TERMINATE → gate_terminate 事件由 chat_pipeline 终止循环；
            # INTERRUPT → 注入提示后继续）。门控执行器与本轮 state 同生共死，
            # 且**每轮只求值一次**——DoomLoopGate 的 `check()` 会自行把本轮签名
            # 记入窗口，对同一轮重复求值等于把自己的签名判成"重复"
            # （实测：同一轮被求值两次 → 第二轮即被误判死循环终止）。
            _tool_sigs = "|".join(f"{n}:{a[:64]}" for n, a in current_calls)
            # 每轮只求值一次（理由同非流式路径）
            if state.gatedRound == state.toolRounds:
                gate_decision = _BYPASS_DECISION
            else:
                state.gatedRound = state.toolRounds
                gate_decision = state.gateRunner.on_round_end(state.gateContext(
                    _tool_sigs,
                    round_reply=round_reply,
                    round_usage=getattr(self.agent, "_round_usage", None) or {},
                    goal=self.resolveTurnGoal() or {},
                ))
            if gate_decision.action.value == "terminate":
                logger.warning("门控 %s 终止循环: %s", gate_decision.gate_name, gate_decision.reason)
                yield {
                    "type": "gate_terminate",
                    "reason": gate_decision.reason,
                    "gate": gate_decision.gate_name,
                }
                return
            if gate_decision.action.value == "interrupt_and_continue":
                # 注入提示进消息序列后继续
                # （round_reply/签名仅 yield reasoning 供前端展示，LLM 看到的是消息）
                request_params["messages"].append(
                    {"role": "user", "content": gate_decision.continuation_prompt}
                )
                logger.info("门控 %s 软干预（提示已注入消息序列）: %s", gate_decision.gate_name, gate_decision.reason)
                yield {"type": "reasoning", "data": gate_decision.continuation_prompt}

            if stagnant:
                state.stagnationCount += 1
                if state.stagnationCount >= 2:
                    logger.warning(
                        "连续 %s 轮停滞（重复响应/调用），终止工具循环", state.stagnationCount
                    )
                    yield {
                        "type": "reasoning",
                        "data": "检测到连续重复的响应，已停止工具循环，避免无效重试。",
                    }
                    return
            else:
                state.stagnationCount = 0

            # A-19：与非流式 _predict_normal 同一可配置来源（_max_tool_rounds，
            # predict_step 入口从 get_effective_limits() 读取）——消除硬编码 10 漂移
            if state.toolRounds <= (getattr(self, "_max_tool_rounds", None) or ROUND_BUDGET_FALLBACK):
                # 工具结果入历史后流式续写（递归），保持后续轮次同样逐 token 转发
                # P2-6：流式路径同批回放推理链——但 reasoning_content 与被禁止它的
                # provider 分档，assistant.tool_calls 声明本身是无条件协议要求
                # （缺声明 → 严格网关把续写判 400，见 base.buildToolRoundMessages）
                _round_reasoning = "".join(reasoning_parts)
                _replayReasoning = False
                if _round_reasoning:
                    try:
                        from neurova.agent.loops.reasoning_replay import should_replay_reasoning

                        _replayReasoning = should_replay_reasoning(
                            str(getattr(self.agent.config, "llm_model", "") or "")
                        )
                    except Exception:  # noqa: BLE001 - 回放失败不影响工具轮
                        logger.debug("reasoning 回放判定失败(忽略)", exc_info=True)
                request_params["messages"].extend(
                    self.buildToolRoundMessages(
                        pending_tool_calls,
                        tool_messages,
                        assistantText=round_reply,
                        reasoningText=_round_reasoning if _replayReasoning else None,
                    )
                )
                if stagnant:
                    stagnation_prompt = (
                        "检测到重复的响应内容。请更换策略，避免重复已经尝试过的无效路径。"
                    )
                    request_params["messages"].append({"role": "user", "content": stagnation_prompt})
                async for event in self._predict_stream(request_params, state):
                    yield event
                return
            logger.warning("工具调用轮次超过上限 (%s)，停止递归", state.toolRounds)

        from neurova.agent.loops.base import LOOP_CONTINUE, LOOP_DONE, evaluateLoopExit

        _exitDecision = await evaluateLoopExit(
            self,
            reply="".join(reply_parts),
            roundUsage=getattr(self.agent, "_round_usage", None) or {},
            toolRound=state.toolRounds,
        )
        if _exitDecision.action == LOOP_CONTINUE:
            request_params["messages"].append(
                {"role": "user", "content": _exitDecision.continuation_prompt}
            )
            yield {"type": "reasoning", "data": _exitDecision.continuation_prompt}
            # 同 `_settleMainExit`：续跑是本轮的续跑，state 必须继续传递，
            # 否则续跑段会捡起最后进入本 loop 的会话留下的门控执行器。
            async for event in self._predict_stream(request_params, state):
                yield event
            return
        if _exitDecision.action != LOOP_DONE:
            # 有理由地终止，且**不得静默**：reasoning 是前端会显示的既有通道
            # （与停滞终止同一范式），gate_terminate 供管道侧消费；
            # 正文照常随 done 交出——只发理由不发正文 = 用户看到空气泡。
            yield {
                "type": "gate_terminate",
                "reason": _exitDecision.reason,
                "gate": _exitDecision.gate_name,
            }
            yield {
                "type": "reasoning",
                "data": f"已停止继续尝试：{_exitDecision.reason}",
            }

        yield {
            "type": "done",
            "reply": "".join(reply_parts),
            "finish_reason": finish_reason,
            "usage": round_usage,
        }

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
    def _merge_tool_call_delta(pending: List[Dict], delta: Dict) -> None:
        """按 index 合并流式 tool_calls 分片。

        OpenAI 兼容流式响应中，一次工具调用被拆到多个 chunk：首片携带 id/name，
        后续片段 id/name 为 None、仅递增 arguments 文本。chat_stream_async 透传
        delta 的 index 字段，据此定位合并位置；无 index 时退化为追加新条目。
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

    async def handle_tool_calls(self, tool_calls: List, messages: List[Dict]) -> List[Dict]:
        """
        处理工具调用 (重写基类方法，添加更多日志)
        """
        logger.info("Handling %s tool calls", len(tool_calls))
        return await super().handle_tool_calls(tool_calls, messages)


# 注册到全局注册表
try:
    from neurova.agent.loops.registry import register_loop

    @register_loop(
        r"gpt-.*|openai/.*|/v1/.*|glm-.*|kimi-.*|qwen.*|deepseek-.*|doubao-.*|"
        r"zhipu/.*|zai-org/.*|moonshot/.*|yi-.*|internlm-.*|baichuan-.*|"
        r"mistral-.*|llama-.*|mixtral-.*|gemini-.*|text-.*|chatglm-.*|"
        r"minimax-.*|Meta-.*|THUDM/.*|Qwen/.*|Pro/.*|SiliconFlow.*",
        priority=10,
    )
    class RegisteredOpenAILoop(OpenAILoop):
        """注册到全局注册表的 OpenAI Loop (通用兼容)"""


    logger.info("OpenAILoop registered to global registry")
except ImportError:
    logger.warning("Could not register OpenAILoop (registry not available)")
