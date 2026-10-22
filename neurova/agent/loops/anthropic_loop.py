"""
Anthropic Loop - Anthropic 模型适配循环

支持: Claude-3 系列 (opus, sonnet, haiku)
特殊能力: computer_use_preview (通过 tools 参数)
"""

import json
from neurova.core.logger import get_logger
from typing import TYPE_CHECKING, Any, Dict, List, Optional

# Agent 仅用于类型注解；运行时导入会与 agent_core 形成循环依赖
if TYPE_CHECKING:
    from neurova.agent_core import Agent

from neurova.agent.loops.base import BaseAgentLoop
from neurova.agent.loops.reasoning_degeneracy import ReasoningStreamGuard, stripDegeneracy
from neurova.agent.loops.turn_run_state import TurnRunState, resolveToolRoundBudget
from neurova.llm_client import LLMResponse

logger = get_logger(__name__)


class AnthropicLoop(BaseAgentLoop):
    """
    Anthropic 模型 Loop

    处理 Claude 系列模型的交互，
    支持 computer_use_preview 工具。
    """

    def __init__(self, agent: "Agent"):
        super().__init__(agent)
        logger.info("AnthropicLoop initialized for agent: %s", agent.config.name)

    async def predict_step(
        self, messages: List[Dict], tools: Optional[List[Dict]] = None, computer_handler: Optional[Any] = None, **kwargs
    ) -> Any:
        """一次 chat 调用的驱动入口（Anthropic 格式）。

        `stream=True` 时**必须返回异步生成器**——消费点
        `chat_pipeline._call_loop_stream` 拿到它就 `async for`。改前这里把 `**kwargs`
        整个吞掉、只返回 `LLMResponse`，于是 claude 系每次流式都在消费点抛
        `TypeError: 'LLMResponse' object is not async iterable`，被
        `chat_pipeline.py:2377-2389` 判成"Loop 实现错误"而回退 legacy；legacy 又不传
        tools——原生 function-calling、门控、主出口判定、邮箱排空、工具事件对 claude
        一并失效，只剩文本正则那条通道（A 批根修）。

        参数:
            messages: 对话历史 (OpenAI 格式，逐轮转成 Anthropic 形态)
            tools: 可用工具列表
            computer_handler: Computer Use 处理器 (可选)
            **kwargs: `stream` 等

        返回:
            流式：异步生成器（事件形状与 `OpenAILoop` 同一契约）；非流式：LLMResponse
        """
        # 轮次态与门控执行器都按本轮构造、逐轮传递（Issue #268：loop 是 per-agent
        # 单例，实例态会让交叠会话互踩）；装配单点在基类，两条环共用同一份门清单。
        runner = self._buildGateRunner()
        self._gate_runner = runner
        state = TurnRunState.forTurn(
            agentId=self._agentFingerprint(),
            roundUserKey=self._fingerprintUserMessage(messages),
            gateRunner=runner,
            maxToolRounds=resolveToolRoundBudget(),
        )
        # `_round_usage` 与目标续跑计数都是"本轮"语义：不重置就跨请求累计，
        # TokenBudgetGate 第二轮即掐死回复（OpenAI 环 2026-09-07 的同一回归教训）。
        self.agent._round_usage = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }
        from neurova.core import turn_context

        turn_context.reset_turn_goal_continuations()

        drive = {"tools": tools, "computer_handler": computer_handler}
        if kwargs.get("stream"):
            return self._predict_stream(messages, drive, state)
        return await self._predict_normal(messages, drive, state)

    async def _predict_normal(self, messages: List[Dict], drive: Dict, state: TurnRunState) -> LLMResponse:
        """非流式工具环：一次往返 → 执行 → **回放** → 再判定要不要开下一轮。

        与 `OpenAILoop._advanceNormalRound` 同一条规则（B 批）：轮次上限与门控只裁定
        「要不要再问一次模型」，不裁定「模型这一轮声明的调用要不要有下文」。改前这里
        的上限判定摆在执行**之前**，被终止那一轮的调用既没跑也没回环；而主出口
        （模型不再调工具）从未求值过门控——`gateRunnerForExit` 在基类恒回 None，
        GoalGate 的目标验收对 claude 一律缺席。
        """
        from neurova.agent.gates import StopAction as _SA
        from neurova.agent.loops.base import LOOP_CONTINUE, evaluateLoopExit

        while True:
            state.assertRoundInvariant()
            response = await self._predict_anthropic(
                await self._build_request(drive["tools"], drive["computer_handler"], messages)
            )
            self._accumulateRoundUsage(getattr(response, "usage", None) or {})

            if not response.tool_calls:
                decision = await evaluateLoopExit(
                    self,
                    reply=getattr(response, "content", "") or "",
                    roundUsage=getattr(self.agent, "_round_usage", None) or {},
                    toolRound=state.toolRounds,
                    roundSignature=state.exitSignature(),
                )
                if decision.action == LOOP_CONTINUE:
                    # 出口续跑仍属本轮：state 继续传递，就地开下一轮（不递归重建）
                    messages.append({"role": "user", "content": decision.continuation_prompt})
                    continue
                if decision.action != "done":
                    logger.warning(
                        "Anthropic 主出口门控 %s 终止: %s", decision.gate_name, decision.reason
                    )
                return response

            state.toolRounds += 1
            logger.info(
                "LLM returned %s tool calls (round %s)", len(response.tool_calls), state.toolRounds
            )

            tool_messages = await self.handle_tool_calls(response.tool_calls, messages)

            # 执行即回放——连同声明这些调用的 assistant 消息：
            # provider 层要按 assistant.tool_calls 产 tool_use 块，缺声明时
            # tool_result 没有前置配对，协议判非法（与 OpenAI 侧同一根因）
            # 非流式整块思考同样剥退化段（与流式同一份判据，不另拼正则）
            _round_reasoning = stripDegeneracy(getattr(response, "reasoning_content", None) or "")[0]
            messages.extend(
                self.buildToolRoundMessages(
                    response.tool_calls,
                    tool_messages,
                    assistantText=getattr(response, "content", "") or "",
                    reasoningText=(
                        _round_reasoning if self._shouldReplayReasoning(_round_reasoning) else None
                    ),
                )
            )

            if state.gatedRound != state.toolRounds:
                state.gatedRound = state.toolRounds
                _gd = state.gateRunner.on_round_end(state.gateContext(
                    self._toolSignatures(response.tool_calls),
                    round_reply=getattr(response, "content", "") or "",
                    round_usage=getattr(self.agent, "_round_usage", None) or {},
                    goal=self.resolveTurnGoal() or {},
                ))
                if _gd is not None and _gd.action == _SA.TERMINATE:
                    logger.warning(
                        "门控 %s 终止 Anthropic 非流式循环: %s", _gd.gate_name, _gd.reason
                    )
                    return response
                if _gd is not None and _gd.action == _SA.INTERRUPT_AND_CONTINUE:
                    messages.append({"role": "user", "content": _gd.continuation_prompt})
                    logger.info(
                        "门控 %s 软干预（Anthropic 非流式）: %s", _gd.gate_name, _gd.reason
                    )

    async def _predict_stream(self, messages: List[Dict], drive: Dict, state: TurnRunState):
        """流式工具环（异步生成器）：逐 token 让出 + 分片合并 tool_calls + 判定后置。

        事件契约与 `OpenAILoop._predict_stream` 一致：`content`/`reasoning`/
        `tool_call`/`tool_result`/`gate_terminate`/`done`，且整条流**恰好一个 done**
        （多个会让消费方重复收尾）。工具轮结束让出哨兵后由本层 `while` 开下一轮，
        不递归自调用——叠帧会把"参数是否传全"的机会再留一遍（Issue #268 切片 B 的理由）。
        """
        from neurova.agent.gates import StopAction as _SA
        from neurova.agent.loops.base import LOOP_CONTINUE, LOOP_DONE, evaluateLoopExit

        while True:
            state.assertRoundInvariant()
            reply_parts: List[str] = []
            reasoningGuard = ReasoningStreamGuard()
            pending_tool_calls: List[Dict] = []
            finish_reason = None
            # 同一次流式调用可能回多个 usage chunk（同一累计值）；只取最后一个，
            # 流结束后累加一次。逐 chunk 累加会把 TokenBudgetGate 抬到真实值的一倍。
            pending_usage = None

            request_params = await self._build_request(
                drive["tools"], drive["computer_handler"], messages
            )
            async for chunk in self.llm_client.chat_stream(
                **self._attachPerceptionImage(request_params)
            ):
                if isinstance(chunk, dict):
                    # 错误 dict 必须分类上抛：认不出的错误会被 chat_pipeline 当成
                    # "Loop 实现错误"回退 legacy，再撞同一个坏模型（时有时无的形态）
                    if chunk.get("error"):
                        raise self._raise_for_error_dict(chunk)
                    continue
                text = getattr(chunk, "content", "") or ""
                if text:
                    reply_parts.append(text)
                    yield {"type": "content", "data": text}
                rtext = getattr(chunk, "reasoning_content", None)
                if rtext:
                    for out_text in reasoningGuard.consume(rtext):
                        yield {"type": "reasoning", "data": out_text}
                    if reasoningGuard.aborted:
                        # 判定退化即终止这一次调用（与 OpenAI 环同一份判据与节拍）
                        break
                usage = getattr(chunk, "usage", None)
                if usage:
                    pending_usage = usage
                for tc_delta in getattr(chunk, "tool_calls", None) or []:
                    self._merge_tool_call_delta(pending_tool_calls, tc_delta)
                if getattr(chunk, "finish_reason", None):
                    finish_reason = chunk.finish_reason

            if reasoningGuard.aborted:
                found = reasoningGuard.found
                logger.warning(
                    "[REASONING_DEGENERACY] 思考流退化截断：「%s」连发 %s 次（尾部 %s 字符），"
                    "本轮按输出预算耗尽交出成因",
                    found.unit,
                    found.repeats,
                    found.chars,
                )
                # 截断点之后的 tool_calls 分片是半截 JSON，不执行一个没声明完的调用
                pending_tool_calls.clear()
                finish_reason = finish_reason or "length"

            if pending_usage is not None:
                self._accumulateRoundUsage(pending_usage)

            round_reply = "".join(reply_parts)

            if not pending_tool_calls:
                decision = await evaluateLoopExit(
                    self,
                    reply=round_reply,
                    roundUsage=getattr(self.agent, "_round_usage", None) or {},
                    toolRound=state.toolRounds,
                    roundSignature=state.exitSignature(),
                )
                if decision.action == LOOP_CONTINUE:
                    messages.append({"role": "user", "content": decision.continuation_prompt})
                    yield {"type": "reasoning", "data": decision.continuation_prompt}
                    continue
                if decision.action != LOOP_DONE:
                    # 不静默：reasoning 是前端会显示的既有通道，正文照常随 done 交出
                    yield {
                        "type": "gate_terminate",
                        "reason": decision.reason,
                        "gate": decision.gate_name,
                    }
                    yield {"type": "reasoning", "data": f"已停止继续尝试：{decision.reason}"}
                yield {
                    "type": "done",
                    "reply": round_reply,
                    "finish_reason": finish_reason,
                    "usage": getattr(self.agent, "_round_usage", None) or {},
                }
                return

            state.toolRounds += 1
            logger.info(
                "LLM returned %s tool calls (stream round %s)",
                len(pending_tool_calls), state.toolRounds,
            )
            for tc in pending_tool_calls:
                yield {"type": "tool_call", "data": tc}

            tool_messages = await self.handle_tool_calls(pending_tool_calls, messages)
            for tm in tool_messages:
                yield {"type": "tool_result", "data": tm}

            # 执行即回放：其后的判定只决定要不要开下一轮（与 OpenAI 环同一规则）
            _round_reasoning = reasoningGuard.cleanText
            messages.extend(
                self.buildToolRoundMessages(
                    pending_tool_calls,
                    tool_messages,
                    assistantText=round_reply,
                    reasoningText=(
                        _round_reasoning if self._shouldReplayReasoning(_round_reasoning) else None
                    ),
                )
            )

            current_calls = [
                ((tc.get("function") or {}).get("name", ""),
                 (tc.get("function") or {}).get("arguments", ""))
                for tc in pending_tool_calls
            ]
            stagnant = self._assess_stagnation(state, round_reply, current_calls)
            state.roundReplies.append(round_reply)
            state.lastRoundCalls = current_calls

            if state.gatedRound != state.toolRounds:
                state.gatedRound = state.toolRounds
                _gd = state.gateRunner.on_round_end(state.gateContext(
                    self._toolSignatures(pending_tool_calls),
                    round_reply=round_reply,
                    round_usage=getattr(self.agent, "_round_usage", None) or {},
                    goal=self.resolveTurnGoal() or {},
                ))
                if _gd is not None and _gd.action == _SA.TERMINATE:
                    logger.warning("门控 %s 终止 Anthropic 流式循环: %s", _gd.gate_name, _gd.reason)
                    yield {"type": "gate_terminate", "reason": _gd.reason, "gate": _gd.gate_name}
                    return
                if _gd is not None and _gd.action == _SA.INTERRUPT_AND_CONTINUE:
                    messages.append({"role": "user", "content": _gd.continuation_prompt})
                    yield {"type": "reasoning", "data": _gd.continuation_prompt}

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
                messages.append({
                    "role": "user",
                    "content": "检测到重复的响应内容。请更换策略，避免重复已经尝试过的无效路径。",
                })
            else:
                state.stagnationCount = 0

    async def _build_request(self, tools, computer_handler, messages) -> Dict:
        """构造一次请求参数——**交的是 OpenAI 形态**，线形状只在 provider 层转一次。

        §6-76 修法 A：这里此前自带 `_convert_messages_to_anthropic` /
        `_convert_tools_to_anthropic`，与路由层 `build_anthropic_body` 是同一件事的两处
        实现。后果两条都实测过：走 OpenAI 兼容网关（OpenRouter 的 `anthropic/*` 路由）
        时预转的 tools 被校验判 400 `invalid_literal tools[0].type expected "function"`；
        走真 anthropic-kind 时预转好的内容块又被路由层 `str(content)` 拍平成 Python
        repr 字面量。收口后本环不再认识任何线协议形状。
        """
        request_params: Dict[str, Any] = {"messages": list(messages)}
        if tools:
            request_params["tools"] = list(tools)
        if computer_handler:
            computer_tool = await self._buildComputerToolDescriptor(computer_handler)
            request_params.setdefault("tools", []).append(computer_tool)
        return request_params

    async def _buildComputerToolDescriptor(self, computer_handler) -> Dict:
        """computer 能力只交**协议中立描述符**（分辨率这类能力参数）。

        `computer_<版本串>` 是 Anthropic 的线协议细节，由 `tool_transport` 那一处拼；
        写在本环里就等于把"哪版协议"的知识复制进 Agent 层。
        """
        try:
            width, height = await computer_handler.get_dimensions()
        except Exception:
            width, height = 1024, 768

        try:
            await computer_handler.get_environment()
        except Exception:
            pass

        return {
            "type": "computer",
            "name": "computer",
            "display_width_px": width,
            "display_height_px": height,
            "display_number": 1,
        }

    def _attachPerceptionImage(self, request_params: Dict) -> Dict:
        """把本轮暂存的截图挂到**这一次请求**的副本上（T-09 · 🔒Q-3 拍"与 OpenAI 环同形"）。

        两环现在交同一个形状：OpenAI 的 `image_url` 切片，由 `_imageUrlPart` 单源产出，
        Anthropic 的 `image` 源块归 provider 层。改前两环各产一种形状，而本环那份
        （`{"type":"image","source":…}`）还要再经一次路由层拍平——"同一条能力两份形状"
        正是 §6-76 收口的对象。

        闸门与归一化由 `perception_gate` 单源持有，本处只管挂载位置；副本同理——
        `request_params["messages"]` 跨轮活，图挂上去就是进历史。
        """
        from neurova.agent.loops import perception_gate

        offer = perception_gate.claimTurnPerception()
        if offer is None:
            return request_params

        messages = [dict(m) for m in request_params.get("messages") or []]
        target = next((m for m in reversed(messages)
                       if isinstance(m, dict) and m.get("role") == "user"), None)
        if target is None:
            return request_params
        existing = target.get("content")
        blocks = ([dict(b) for b in existing if isinstance(b, dict)]
                  if isinstance(existing, list) else
                  ([{"type": "text", "text": existing}] if existing else []))
        blocks.append({"type": "text", "text": perception_gate.PERCEPTION_INSTRUCTION_TEXT})
        blocks.append(self._imageUrlPart(offer))
        target["content"] = blocks
        sent = {**request_params, "messages": messages}
        perception_gate.commitTurnPerception(self.agent, offer)
        return sent

    async def _predict_anthropic(self, request_params: Dict) -> LLMResponse:
        """
        调用 Anthropic API 进行预测
        """
        # 使用 llm_client 调用 (假设它支持 Anthropic)
        response = await self.llm_client.chat(**self._attachPerceptionImage(request_params))
        return response

    async def handle_tool_calls(self, tool_calls: List, messages: List[Dict]) -> List[Dict]:
        """
        处理工具调用 (重写基类方法，添加 computer 工具支持)

        **无 `computer` 调用时整批交给基类**：基类的批次分组按整批算，逐条转发
        `super().handle_tool_calls([单条])` 会让这条路径上永远只有一项 ⇒ 任何能力
        声明都拿不到成组执行（`claude-*` 走的就是本 Loop），而这一点在形态读数上
        表现为"全是 single_call"，不解读者会以为 M3 在这侧没有收益。

        `computer` 调用仍逐条处理：它是共享外设（并行轴上必须串行），且回装形状
        与基类不同（`tool_result` 块）。取"批里有它才走逐条"，而不是默认逐条——
        逐条是特例，整批才是常态。
        """
        if tool_calls and all(
            ((tc or {}).get("function") or {}).get("name") != "computer"
            for tc in tool_calls
        ):
            return await super().handle_tool_calls(tool_calls, messages)

        new_messages = []

        for tool_call in tool_calls:
            function_name = tool_call["function"]["name"]

            # 特殊处理 computer 工具
            if function_name == "computer":
                result = await self._execute_computer_tool(tool_call)
            else:
                # 普通工具，使用基类方法
                result = await super().handle_tool_calls([tool_call], messages)
                new_messages.extend(result)
                continue

            # 构建 tool_result message
            new_messages.append(
                {
                    "role": "user",
                    "content": [{"type": "tool_result", "tool_use_id": tool_call["id"], "content": result}],
                }
            )

        return new_messages

    async def _execute_computer_tool(self, tool_call: Dict) -> Dict:
        """
        执行 computer 工具

        解析 tool_call 参数，执行相应的 computer 操作
        """
        args = json.loads(tool_call["function"]["arguments"])
        action = args["action"]

        # 获取 computer_handler (假设从 agent 获取)
        computer_handler = getattr(self.agent, "computer_handler", None)

        if not computer_handler:
            return {"type": "text", "text": "Computer handler not available"}

        try:
            if action == "screenshot":
                screenshot = await computer_handler.screenshot()
                return {
                    "type": "image",
                    "source": {"type": "base64", "media_type": "image/png", "data": screenshot["image_base64"]},
                }

            elif action == "click":
                x, y = args["x"], args["y"]
                await computer_handler.click(x, y)
                return {"type": "text", "text": f"Clicked at ({x}, {y})"}

            elif action == "type":
                text = args["text"]
                await computer_handler.type_text(text)
                return {"type": "text", "text": f"Typed: {text}"}

            elif action == "scroll":
                dx, dy = args.get("dx", 0), args.get("dy", 0)
                await computer_handler.scroll(dx, dy)
                return {"type": "text", "text": f"Scrolled: ({dx}, {dy})"}

            else:
                return {"type": "text", "text": f"Unknown action: {action}"}

        except Exception as e:
            logger.error("Computer tool execution failed: %s", e)
            return {"type": "text", "text": f"Error: {str(e)}"}


# 注册到全局注册表
try:
    from neurova.agent.loops.registry import register_loop

    @register_loop(r"claude-.*|anthropic/.*", priority=20)
    class RegisteredAnthropicLoop(AnthropicLoop):
        """注册到全局注册表的 Anthropic Loop"""


    logger.info("AnthropicLoop registered to global registry")
except ImportError:
    logger.warning("Could not register AnthropicLoop (registry not available)")
