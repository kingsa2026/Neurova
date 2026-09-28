"""
OpenAI Loop - OpenAI 兼容模型适配循环

支持: GPT-4, GPT-3.5-turbo, GPT-4V, 以及所有 OpenAI 兼容 API
"""

import asyncio
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from neurova.core.logger import get_logger

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

#: 流式单轮的"本轮已推进，请循环开下一轮"让出标记。
#:
#: 用 sentinel 而不是在单轮里 yield `done`：整条流恰好一个 done 是既有契约
#: （前端与管线都按"done 即收尾"消费），迭代化若让每个工具轮都 yield done，
#: 正文会被当成多轮回复拼接。
_STREAM_END = object()

#: 输出预算耗尽（length 空回复）重试仍空时的可见提示（杜绝空气泡）。
_LENGTH_EMPTY_NOTICE = (
    "⚠️ 未能生成回复：输出预算被思考过程占满（finish_reason=length），"
    "压缩上下文重试后仍未产出正文。建议切换非思考模型，"
    "或在模型设置中调大最大输出 token。"
)


@dataclass
class _TurnOutcome:
    """非流式单轮的推进结果。

    `done` 非空 = 整轮结束（收口 / 门控终止 / 轮次超限），循环把该响应交回调用方；
    `done` 为空 = 本轮已就地推进（工具轮完成或出口续跑提示已入历史），
    循环继续下一轮。迭代化把"下一步"从一次自递归变成一个返回值，
    栈深因此与轮数无关。
    """

    done: Optional[LLMResponse] = None

    @classmethod
    def finished(cls, response: LLMResponse) -> "_TurnOutcome":
        return cls(done=response)

    @classmethod
    def running(cls) -> "_TurnOutcome":
        return cls(done=None)


@dataclass
class _RoundEnd:
    """流式单轮的让出结果。

    `advanced=True` 表示本轮已就地推进（工具轮续写 / 出口续跑），下一轮由
    `_predict_stream` 的循环开，本轮**不**产出 done；为假则 `done` 是本轮的
    done 事件（整条流由它收尾）。
    """

    advanced: bool
    gotContent: bool
    done: Optional[Dict[str, Any]] = None


class _StreamRounds:
    """流式循环的轮间标志（均为"本轮"语义，一轮结束即重置）。

    `advanced` 是"本轮是否已被接续"：为真（工具轮续写 / 出口续跑）时下一轮由循环开；
    为假时本轮的 done 就是整条流的收尾。
    """

    def __init__(self) -> None:
        self.exhausted = False           # 轮次超限（无 done 可交，直接收尾）
        self.lengthEmpty = False         # 本轮 length 且正文为空 → 值得重试
        self.lengthEmptyRetried = False   # 已发生一次 length 重试（防循环）
        self.retriedStillEmpty = False    # 重试后仍空 → 收尾时补可见提示
        self.advanced = False             # 本轮被接续（工具轮续写/出口续跑）

    def beginNextRound(self) -> None:
        """进入下一轮：清掉只属于"上一轮"的标志。"""
        self.lengthEmpty = False
        self.advanced = False
        self.retriedStillEmpty = False


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
        # 轮次预算一律走 `_goalRoundBudget()`（配置单源 `goal_round_budget`）：
        # **默认装配路径也必须传它**，否则 GoalGate 回落到 gates.py 的类字面量，
        # 上限再次不受任何配置键管辖——这正是本片要消灭的形态。
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
            max_rounds=self._goalRoundBudget(),
        )

    def _goalRoundBudget(self, limits: Optional[dict] = None) -> int:
        """GoalGate 的轮次预算——单源取 `goal_round_budget`（跟随 max_loop_rounds）。

        `set_goal_gate(max_rounds=...)` 是**显式覆盖**，优先级高于配置：它是调用方
        对该次会话目标的直接裁定，不是第二份默认值。缺省（`None`）时一律回配置单源
        —— 此前缺省是字面量 15，装配路径不传它，于是上限不受任何配置键管辖。
        """
        spec = getattr(self, "_goal_gate_spec", None) or {}
        override = spec.get("max_rounds")
        if override is not None:
            return int(override)
        values = limits if limits is not None else self._load_agent_limits()
        return int(values["goal_round_budget"])

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

    def set_goal_gate(
        self, goal: Dict[str, Any], completion_check=None, max_rounds: Optional[int] = None
    ) -> None:
        """goal 模式：登记 GoalGate 规格（目标达成判定 + 轮次预算）。

        只登记规格，不再持有第二份装配路径（修复教义第 6 条）。
        `max_rounds=None`（缺省）= 不覆盖，取配置单源 `goal_round_budget`
        ——此前缺省是字面量 15，与 `_buildGoalGate` 的缺省构成同一份数字的两处落点。
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
        """入口构造本轮轮次态（`predict_step` 与 `_predict_*` 直接驱动的兜底同源）。

        门控执行器就地取规格装配（单点 `_buildGateRunner`），并写回实例引用：
        读取面与判定面必须是**同一份**，否则经 `_gate_runner` 追加的门控与
        `DoomLoopGate` 的窗口都只落在其中一份上。

        构造一律走 `TurnRunState.forTurn`（唯一签发点）：切片 C 之后轮次态要能
        自证归属，而"谁创建的"只有签发时知道——直接 `TurnRunState(...)` 会得到
        空 turnId，正是"构造点各写一份、指纹无人记"的形态。
        """
        _runner = self._buildGateRunner()
        self._gate_runner = _runner
        state = TurnRunState.forTurn(
            agentId=self._agentFingerprint(),
            roundUserKey=self._fingerprintUserMessage(messages),
            gateRunner=_runner,
        )
        state.maxToolRounds = getattr(self, "_max_tool_rounds", None) or ROUND_BUDGET_FALLBACK
        return state

    def _agentFingerprint(self) -> str:
        """创建者指纹（切片 C）：优先 agent_id，退到 name——两者皆无则空串。"""
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
        state = TurnRunState.forTurn(
            agentId=self._agentFingerprint(),
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

        # 执行预测（tools 被拒的降级在**单轮内**完成，见 `_chatNormalWithDegrade`
        # 与流式的降级分支；此处不再重入整条循环——重入会让"这一轮"多一层栈帧）
        if stream:
            return self._predict_stream(request_params, state)
        return await self.predict_normal(request_params, state)

    def _dropToolsForDegrade(self, request_params: Dict, state: TurnRunState, error: str) -> None:
        """工具被拒后的降级准备：摘掉 tools 并注入文本调用教学。"""
        logger.warning(
            "[TOOLROBUST-B] function calling 疑似不被 API 支持，本轮降级为无 tools 重试并注入文本教学。错误: %s",
            error,
        )
        state.toolsSupported = False
        # 标记降级事件，供可观测（agent.ui / 监控可读）
        try:
            self.agent.append_tool_event({"type": "tools_degraded", "reason": error[:200]})
        except Exception:
            pass
        request_params.pop("tools", None)
        request_params.pop("tool_choice", None)
        # 降级后注入文本调用教学，避免模型在无 tools 状态下完全不会调工具
        request_params["messages"] = self._append_tool_hint(request_params["messages"])

    async def predict_normal(self, request_params: Dict, state: TurnRunState = None) -> LLMResponse:
        """非流式循环（**单层迭代**，Issue #268 切片 B）。

        一次调用推进到"模型不再调工具"为止：工具轮、门控终止、出口续跑三类推进
        都在这一个 `while` 里就地完成，不靠"再调一次本方法"叠帧。
        切片 A 之后轮次态已随 `state` 传递，只剩控制流还是递归；递归不炸栈
        （方案 §1 实测可嵌套 493 轮，合法上限 100），代价是每多一层就多一次
        "参数是否传全"的机会——栈深随轮数增长正是这件事的读数（红灯实测每轮 +1 帧）。

        [TOOLROBUST-B] 自动降级：带 tools 的请求若被 API 拒绝（工具型 400），
        去掉 tools 并注入文本调用教学后重试一次，避免整轮崩溃且弱 provider 仍有工具通道。

        `state` 缺省时按本次请求现建一份（直接驱动本方法时每调用即一整轮）。
        """
        if state is None:
            state = self._startTurnState(request_params.get("messages") or [])
        while True:
            # 轮入口不变量（切片 C）：越限即点名——把"上限判定被绕过"
            # （跨会话污染的形态）从要靠并发活体才测得到，降级为每轮可自证。
            state.assertRoundInvariant()
            outcome = await self._runOneNormalRound(request_params, state)
            if outcome.done is not None:
                return outcome.done
            # 出口续跑：提示已入历史，就地开下一轮

    async def _runOneNormalRound(
        self, request_params: Dict, state: TurnRunState
    ) -> "_TurnOutcome":
        """非流式**单轮**：一次模型往返 + 工具执行 + 门控求值 + 出口裁决。

        返回值三态：`done` 为最终响应（收口/终止/超限），`done is None` 表示
        "本轮已注入续跑提示，请继续下一轮"。
        """
        response = await self._chatNormalWithDegrade(request_params, state)

        # 记录思考过程（用于前端展示）
        reasoning_content = getattr(response, "reasoning_content", None)
        if reasoning_content:
            # 将思考过程存储到 agent 上，供 chat() 方法读取
            self.agent.set_current_reasoning(reasoning_content)
            logger.info("🧠 捕获思考过程: %s 字符", len(reasoning_content))

        # 处理 tool_calls（部分 provider 响应无 tool_calls 字段，需容错）
        tool_calls = getattr(response, "tool_calls", None)
        if not tool_calls:
            return await self._settleMainExit(request_params, response, state)

        return await self._advanceNormalRound(request_params, state, response, tool_calls, reasoning_content)

    async def _chatNormalWithDegrade(self, request_params: Dict, state: TurnRunState) -> LLMResponse:
        """模型往返 + 工具型 400 的无工具降级重试（单轮内，不叠帧）。"""
        try:
            return await self.llm_client.chat(**request_params)
        except Exception as e:
            if not (request_params.get("tools") and self._is_tools_rejected_error(str(e))):
                raise
            self._dropToolsForDegrade(request_params, state, str(e))
            return await self.llm_client.chat(**request_params)

    async def _advanceNormalRound(
        self,
        request_params: Dict,
        state: TurnRunState,
        response: LLMResponse,
        tool_calls: List,
        reasoning_content: Optional[str],
    ) -> "_TurnOutcome":
        """非流式工具轮：超限判定 → 门控 → 执行 → 回放 → 入历史。

        `done is None` 表示本轮结束、循环继续（迭代形态里"继续"就是返回上一层
        的 `while`，不再是一次自调用）。
        """
        state.toolRounds += 1
        if state.toolRounds > state.maxToolRounds:
            # 2026-09-07 根因修复（audit P2-8）：原实现只打日志继续递归，
            # 实际上限是 IterationGate 的 20；现在超限真正终止
            logger.warning("工具调用轮次超过上限 (%s)，终止", state.toolRounds)
            return _TurnOutcome.finished(response)
        # P2-5：非流式路径同样过门控（TERMINATE 即终止）
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
                return _TurnOutcome.finished(response)
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

        # 本轮结束、循环继续（迭代形态：返回上一层 while，不再递归自身）
        return _TurnOutcome.running()

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
            roundSignature=state.exitSignature(),
        )
        if decision.action == LOOP_CONTINUE:
            request_params["messages"].append(
                {"role": "user", "content": decision.continuation_prompt}
            )
            # 续跑就地开下一轮（不再递归自身）：state 继续传递，交叠会话下
            # 不会捡到"最后进入本 loop 的会话"留下的门控执行器。
            return _TurnOutcome.running()
        if decision.action != "done":
            logger.warning("主出口门控 %s 终止: %s", decision.gate_name, decision.reason)
        return _TurnOutcome.finished(response)

    async def _predict_stream(self, request_params: Dict, state: TurnRunState = None) -> Any:
        """流式循环（**单层迭代**，Issue #268 切片 B）。

        两条恢复机制都并入这一层 `while`，不再靠递归自身叠帧：

        - 请求打开即上下文溢出（`TokenLimitExceeded`，且尚无内容产出）→ 折叠消息后
          单次重试；重试仍溢出原样抛出（防循环）；流中途溢出（已有内容）原样抛
          （重试会造成内容重复）。
        - 输出预算耗尽（`finish_reason=length` 且正文为空：思考模型把 max_tokens
          吃满，HTTP 200 无异常）→ 放宽输出预算 + 思考降级 + 压缩消息后单次重试；
          重试仍空则补一条可见提示，`done.reply` 同步改写（杜绝空气泡）。

        迭代化后这两条从"再进一次 `_predict_stream`"变成"改 `request_params` 就地
        开下一轮"，已产出的正文事件**不重复 yield**（重放会变成两次 done 事件，
        前端正文翻倍）。

        返回：恰好一个 `done` 事件收尾的异步生成器。
        """
        from neurova.context.recovery import (
            compact_messages_for_overflow,
            is_context_overflow_error,
        )

        if state is None:
            state = self._startTurnState(request_params.get("messages") or [])

        self._rounds = _StreamRounds()  # 本轮流式循环的轮间标志（见 `_resumeAfterLengthEmpty`）
        while True:
            # 轮入口不变量（切片 C）：与非流式同判据，两条路径共用同一份自证。
            state.assertRoundInvariant()
            produced = None
            gotContent = False
            try:
                async for item in self._streamOneRound(request_params, state):
                    if isinstance(item, _RoundEnd):
                        produced, gotContent = item.done, item.gotContent
                        self._rounds.advanced = item.advanced
                        break
                    if isinstance(item, dict) and item.get("type") == "content" and item.get("data"):
                        gotContent = True
                    yield item
            except BaseException as e:  # noqa: BLE001 - 统一捕获后按类型分流
                resumed = self._resumeAfterOverflow(
                    e, request_params, gotContent, compact_messages_for_overflow, is_context_overflow_error
                )
                if resumed is None:
                    raise
                request_params = resumed
                continue

            if self._rounds.exhausted:
                # 轮次超限：本轮没有 done 可交，静默收尾（与非流式「终止」同判据）
                return

            if self._rounds.lengthEmpty:
                # 输出预算耗尽（本轮 length 且正文为空）→ 放宽预算后就地重试。
                # 本轮的空 done 不让出（无正文可看），只让出提示；重试仍空由
                # `retriedStillEmpty` 分支补可见提示并改写 done.reply（杜绝空气泡）。
                resumed, notice = self._resumeAfterLengthEmpty(
                    request_params, compact_messages_for_overflow
                )
                if resumed is None:
                    # 无可动旋钮 / 无可折叠 → 原样交出该 done（不二次重试，防循环）
                    if produced is not None:
                        yield produced
                    return
                if notice is not None:
                    yield notice
                request_params = resumed
                continue

            if produced is not None:
                # 首轮(或重试轮)的 done：重试仍空 → 补可见提示并改写 done.reply，
                # 使 ctx.reply 非空、落盘与前端气泡均有内容（杜绝空气泡，闭环）
                if not (produced.get("reply") or "").strip() and (
                    self._rounds.retriedStillEmpty or self._rounds.lengthEmptyRetried
                ):
                    # `lengthEmptyRetried` 为真 = 重试轮仍空（本轮就是那次重试）
                    yield {"type": "content", "data": _LENGTH_EMPTY_NOTICE}
                    produced = {**produced, "reply": _LENGTH_EMPTY_NOTICE}
                yield produced
                return

            if self._rounds.advanced:
                # 本轮被接续（工具轮续写 / 出口续跑）：下一轮由循环开
                continue
            return

    def _resumeAfterOverflow(
        self,
        error: BaseException,
        request_params: Dict,
        gotContent: bool,
        compactMessages,
        isOverflow,
    ) -> Optional[Dict]:
        """溢出恢复：返回"下一轮要用的 request_params"，或 `None` 表示原样抛出。

        单次语义由调用方经 `request_params` 上的 `_overflowRetried` 标记保证：
        已重试过的轮不再重试（原实现靠"重试走另一条分支、不再进同一判断"实现，
        迭代后同一段代码会被再次进入，故标记必须显式）。
        """
        if gotContent or not isOverflow(error) or request_params.get("_overflowRetried"):
            return None
        messages = request_params.get("messages") or []
        compact, info = compactMessages(messages)
        if info.get("folded_count", 0) <= 0:
            return None  # 无可折叠内容，恢复无意义
        logger.warning(
            "[CTX_RECOVERY] 上下文溢出，折叠 %d 条消息后单次重试（%d → %d）",
            info["folded_count"], info["original_count"], info["compact_count"],
        )
        self._rollupFoldedDigest(info)
        return {**request_params, "messages": compact, "_overflowRetried": True}

    def _resumeAfterLengthEmpty(self, request_params: Dict, compactMessages):
        """输出预算耗尽恢复：返回（下一轮的 request_params, 首轮提示事件）。

        `request_params is None` 表示无旋钮可动、不重试。病根在输出侧
        （思考吃满 max_tokens），重试必须同步放宽输出预算 + 思考降级；
        只压缩输入会原样撞同一堵墙。
        """
        if request_params.get("_length_empty_retried"):
            return None, None
        compact, info = compactMessages(request_params.get("messages") or [])
        budgetKnobs = "max_tokens" in request_params or any(
            k in request_params
            for k in ("thinking_enabled", "thinking_effort", "reasoning_effort", "thinking_budget")
        )
        if info.get("folded_count", 0) <= 0 and not budgetKnobs:
            return None, None
        logger.warning(
            "[CTX_RECOVERY] 输出预算耗尽(length)且正文为空，放宽输出预算+思考降级后单次重试（折叠 %d 条）",
            info.get("folded_count", 0),
        )
        self._rollupFoldedDigest(info)
        retryParams = {
            **request_params,
            "messages": compact,
            "_length_empty_retried": True,
            # 输出侧放宽：思考关停（预算让位给正文）；仅当原请求显式带预算/档位键
            # 时才覆写对应键，不凭空注入预算。
            "thinking_enabled": False,
        }
        if "max_tokens" in request_params:
            retryParams["max_tokens"] = _raised_output_budget(request_params.get("max_tokens"))
        if "thinking_effort" in request_params:
            retryParams["thinking_effort"] = "light"
        if "reasoning_effort" in request_params:
            retryParams["reasoning_effort"] = "low"
        retryParams.pop("thinking_budget", None)
        self._rounds.lengthEmptyRetried = True
        # 紧接着的这一轮若仍空即"重试仍空"：由收尾路径补可见提示（不再重试，防循环）
        self._rounds.retriedStillEmpty = True
        return retryParams, {
            "type": "reasoning",
            "data": "检测到回复为空（输出预算被思考过程耗尽），正在放宽输出预算并压缩上下文后重试…",
        }

    def _rollupFoldedDigest(self, info: Dict) -> None:
        """被折叠消息生成摘要回写池（fire-and-forget，不阻塞重试；无池 no-op）。"""
        try:
            pool = getattr(getattr(self.agent, "context_orchestrator", None), "context_pool", None)
            if pool is not None:
                asyncio.ensure_future(pool.rollup_overflow_digest(info.get("folded_messages") or []))
        except Exception:
            logger.debug("折叠摘要回写跳过", exc_info=True)

    async def _streamOneRound(self, request_params: Dict, state: TurnRunState) -> Any:
        """流式**单轮**：拉一轮 chunk（让出正文事件），再就地推进工具轮/出口。

        循环推进的语义（三类）都在这里落地成 `rounds` 上的标志，由
        `_predict_stream` 决定是继续下一轮还是收尾——单轮本身不递归、不循环。
        """
        self._rounds.beginNextRound()
        gotContent = False
        advanced = False
        doneEvent: Optional[Dict[str, Any]] = None
        async for event in self._predict_stream_once(request_params, state):
            if event is _STREAM_END:
                # 本轮已就地推进（工具轮续写 / 出口续跑）：done 不由本单轮交出
                advanced = True
                continue
            if isinstance(event, dict) and event.get("type") == "content" and event.get("data"):
                gotContent = True
            if isinstance(event, dict) and event.get("type") == "done":
                # done 由迭代层让出（不在此就地 yield）：恢复路径要先看读数的
                # 决定发不发它（length 空回复重试时那一轮的空 done 不该让用户看见）
                doneEvent = event
                continue
            yield event

        self._rounds.advanced = advanced
        if not advanced and not gotContent and doneEvent is not None:
            # 输出预算耗尽防线（前置于 done 事件的判定，见 `_predict_stream` 分支）
            self._rounds.lengthEmpty = (
                not request_params.get("_length_empty_retried")
                and not (doneEvent.get("reply") or "").strip()
                and str(doneEvent.get("finish_reason") or "").lower() in ("length", "max_tokens")
            )

        yield _RoundEnd(advanced, gotContent, doneEvent)

    async def _predict_stream_once(self, request_params: Dict, state: TurnRunState = None) -> Any:
        """流式预测 — 实时 yield 结构化事件（content / reasoning / tool_call / tool_result / done）。

        底层 chat_stream 逐 chunk 产出 LLMResponse 对象（见 llm_client.chat_stream_async），
        失败时被 multi_model_client.chat_stream 包装为 {"error": ...} 字典。本方法负责：
        1. 把 chunk 实时转成 typed 事件（reasoning/content 逐片段转发，思考过程不再整块滞后）；
        2. 流式 tool_calls 分片按 index 合并为完整调用（OpenAI 兼容流中首片带 id/name，
           后续片段仅携带 arguments 碎片），流结束后执行并产出 tool_result 事件；
        3. 工具执行后就地推进（让出 `_STREAM_END` 给 `_predict_stream` 的循环，
           由它开下一轮），本方法**不递归、不循环**；
        4. 单轮结束时 yield 一个 done 事件（携带本轮正文快照）——整条流恰好一个
           done 由 `_predict_stream` 保证；
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
            if k not in ("messages", "stream", "_length_empty_retried", "_overflowRetried")
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

            # A-19：与非流式 predict_normal 同一可配置来源（state.maxToolRounds，
            # predict_step 入口从 get_effective_limits() 读取）——消除硬编码 10 漂移
            if state.toolRounds <= state.maxToolRounds:
                # 工具结果入历史后就地推进（迭代形态：由 `_predict_stream` 的循环
                # 开下一轮），保持后续轮次同样逐 token 转发
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
                # 单轮结束：本轮正文/工具事件已让出，下一轮由循环开
                yield _STREAM_END
                return
            logger.warning("工具调用轮次超过上限 (%s)，停止", state.toolRounds)

        from neurova.agent.loops.base import LOOP_CONTINUE, LOOP_DONE, evaluateLoopExit

        _exitDecision = await evaluateLoopExit(
            self,
            reply="".join(reply_parts),
            roundUsage=getattr(self.agent, "_round_usage", None) or {},
            toolRound=state.toolRounds,
            roundSignature=state.exitSignature(),
        )
        if _exitDecision.action == LOOP_CONTINUE:
            request_params["messages"].append(
                {"role": "user", "content": _exitDecision.continuation_prompt}
            )
            yield {"type": "reasoning", "data": _exitDecision.continuation_prompt}
            # 同 `_settleMainExit`：续跑是本轮的续跑，state 继续传递（门控执行器
            # 随 state 走，不会捡到最后一个进入本 loop 的会话留下的那份）；
            # 下一轮由 `_predict_stream` 的循环开——本轮不 yield done，
            # 整条流仍恰好一个 done。
            yield _STREAM_END
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

        # 单轮收口（整条流到此结束，`_predict_stream` 不再开下一轮）
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

    #: `_predict_normal` 是本方法的既有私有名（既有测试与调试脚本按它驱动单轮/多轮）。
    #: 迭代化只改控制流，入口名保持不变——改名会把调用面一并拖进来，
    #: 与"切片 B 不动公有面"的边界不符。
    _predict_normal = predict_normal

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
