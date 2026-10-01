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
        """
        执行一步预测 (Anthropic 格式)

        参数:
            messages: 对话历史 (OpenAI 格式，需要转换为 Anthropic 格式)
            tools: 可用工具列表
            computer_handler: Computer Use 处理器 (可选)
            **kwargs: 额外参数

        返回:
            LLMResponse 对象
        """
        # 轮次态随本次调用构造、逐轮传递：原先挂在实例上，同一 agent 上两个会话
        # 交叠时后进入者会改写前者的轮次计数（与 OpenAILoop 同一根因，Issue #268）。
        # 构造走 `forTurn`（切片 C 唯一签发点）：记录创建者指纹，交叉使用可自证。
        _config = getattr(self.agent, "config", None)
        state = TurnRunState.forTurn(
            agentId=str(
                getattr(_config, "agent_id", None) or getattr(_config, "name", None) or ""
            ),
            maxToolRounds=resolveToolRoundBudget(),
        )
        while True:
            state.assertRoundInvariant()
            response = await self._predict_anthropic(
                await self._build_request(tools, computer_handler, messages)
            )
            if not response.tool_calls:
                return response

            state.toolRounds += 1
            if state.toolRounds > state.maxToolRounds:
                logger.warning(
                    "Anthropic 工具调用轮次超过上限 (%s)，终止工具循环", state.toolRounds
                )
                return response
            logger.info("LLM returned %s tool calls (round %s)", len(response.tool_calls), state.toolRounds)

            tool_messages = await self.handle_tool_calls(response.tool_calls, messages)

            # 将工具结果添加到 messages——连同声明这些调用的 assistant 消息：
            # _convert_messages_to_anthropic 靠它产出 tool_use 块，缺块时
            # tool_result 没有前置声明，协议判为非法（与 OpenAI 侧同一根因）
            messages.extend(
                self.buildToolRoundMessages(
                    response.tool_calls,
                    tool_messages,
                    assistantText=getattr(response, "content", "") or "",
                )
            )

    async def _build_request(self, tools, computer_handler, messages) -> Dict:
        """构造一次 Anthropic 请求参数（含 tools 与 computer 工具）。"""
        request_params: Dict[str, Any] = {
            "messages": self._convert_messages_to_anthropic(messages),
        }
        if tools:
            request_params["tools"] = self._convert_tools_to_anthropic(tools)
        if computer_handler:
            computer_tool = await self._build_computer_tool(computer_handler)
            request_params.setdefault("tools", []).append(computer_tool)
        return request_params

    def _convert_messages_to_anthropic(self, messages: List[Dict]) -> List[Dict]:
        """
        将 OpenAI 格式 messages 转换为 Anthropic 格式

        OpenAI: [{"role": "user", "content": "Hello"}]
        Anthropic: [{"role": "user", "content": [{"type": "text", "text": "Hello"}]}]

        Bug A-3 修复 [HIGH]: 原代码不处理 "tool" role 和 assistant 的 tool_calls，
        导致 Anthropic API 拒绝请求或行为未定义。

        修复:
        1. "tool" role → "user" role + tool_result content block
           （Anthropic 要求 tool result 作为 user message 的 content block）
        2. assistant 的 tool_calls → tool_use content block
           （Anthropic 要求 tool use 作为 assistant message 的 content block）
        3. 连续的 tool result 合并到同一个 user message
           （Anthropic 要求 tool result 必须紧跟在 assistant tool_use 之后，
            多个 tool result 应合并为一个 user message 的多个 content block）
        """
        import json as _json

        anthropic_messages = []

        for msg in messages:
            role = msg["role"]
            content = msg.get("content")

            # Bug A-3 修复 1: "tool" role → "user" role + tool_result block
            if role == "tool":
                tool_call_id = msg.get("tool_call_id", "")
                tool_content = content if isinstance(content, str) else _json.dumps(content)
                tool_result_block = {
                    "type": "tool_result",
                    "tool_use_id": tool_call_id,
                    "content": tool_content,
                }
                # 合并到前一个 user message（如果它是 tool_result 容器）
                if (
                    anthropic_messages
                    and anthropic_messages[-1]["role"] == "user"
                    and isinstance(anthropic_messages[-1]["content"], list)
                    and any(
                        isinstance(c, dict) and c.get("type") == "tool_result"
                        for c in anthropic_messages[-1]["content"]
                    )
                ):
                    anthropic_messages[-1]["content"].append(tool_result_block)
                else:
                    anthropic_messages.append(
                        {"role": "user", "content": [tool_result_block]}
                    )
                continue

            # 转换 role
            if role == "assistant":
                ant_role = "assistant"
            elif role == "user":
                ant_role = "user"
            elif role == "system":
                # Anthropic 使用 "system" 参数，而不是 messages
                continue
            else:
                ant_role = role

            # Bug A-3 修复 2: assistant 的 tool_calls → tool_use block
            ant_content = []
            if isinstance(content, str):
                if content:
                    ant_content.append({"type": "text", "text": content})
            elif isinstance(content, list):
                ant_content = content  # 已经是正确格式
            elif content is None:
                pass  # assistant 只有 tool_calls 时 content 为 None

            # 转换 tool_calls → tool_use block
            tool_calls = msg.get("tool_calls")
            if tool_calls and ant_role == "assistant":
                for tc in tool_calls:
                    func = tc.get("function", {})
                    args_str = func.get("arguments", "{}")
                    try:
                        args_dict = _json.loads(args_str) if isinstance(args_str, str) else args_str
                    except (_json.JSONDecodeError, TypeError):
                        args_dict = {"raw": args_str}
                    ant_content.append(
                        {
                            "type": "tool_use",
                            "id": tc.get("id", ""),
                            "name": func.get("name", ""),
                            "input": args_dict,
                        }
                    )

            # 确保 content 不为空（Anthropic 要求 content 非空）
            if not ant_content:
                ant_content = [{"type": "text", "text": ""}]

            anthropic_messages.append({"role": ant_role, "content": ant_content})

        return anthropic_messages

    def _convert_tools_to_anthropic(self, tools: List[Dict]) -> List[Dict]:
        """
        将 OpenAI Tool Schema 转换为 Anthropic 格式

        OpenAI: {"type": "function", "function": {"name": ..., "parameters": ...}}
        Anthropic: {"name": ..., "description": ..., "input_schema": ...}
        """
        ant_tools = []

        for tool in tools:
            if tool.get("type") == "function":
                func = tool["function"]
                ant_tools.append(
                    {
                        "name": func["name"],
                        "description": func.get("description", ""),
                        "input_schema": func.get("parameters", {"type": "object", "properties": {}}),
                    }
                )

        return ant_tools

    async def _build_computer_tool(self, computer_handler) -> Dict:
        """
        构建 Anthropic computer 工具

        返回 Anthropic 格式的 computer 工具定义
        """
        # 获取屏幕分辨率
        try:
            width, height = await computer_handler.get_dimensions()
        except Exception:
            width, height = 1024, 768

        # 获取环境
        try:
            await computer_handler.get_environment()
        except Exception:
            pass

        return {
            "type": "computer_20241022",
            "name": "computer",
            "display_width_px": width,
            "display_height_px": height,
            "display_number": 1,
        }

    def _attachPerceptionImage(self, request_params: Dict) -> Dict:
        """把本轮暂存的截图挂到**这一次请求**的副本上（T-09 · 🔒Q-3 拍"与 OpenAI 环同形"）。

        改前这条环只服务它自己的原生 computer 工具内容块（`_execute_computer_tool` 里那个
        `{"type":"image",…}`），不经轮级槽——于是走 Anthropic 服务商时槽被生产者填、
        装配侧无人消费，能力"尚未生效"却只记在散文里。

        闸门与归一化由 `perception_gate` 单源持有，本处只做 Anthropic 的内容块形状：
        两环各留一份三闸，迟早漂移成"某条环给图、另一条不给"的分裂读数。
        副本同理——`request_params["messages"]` 跨轮活，图挂上去就是进历史。
        """
        import base64

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
        blocks.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": offer["mime"],
                "data": base64.b64encode(offer["bytes"]).decode("ascii"),
            },
        })
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
