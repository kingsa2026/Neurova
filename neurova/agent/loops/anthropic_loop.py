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
        # 转换 messages 格式 (OpenAI → Anthropic)
        anthropic_messages = self._convert_messages_to_anthropic(messages)

        # 准备请求参数
        request_params = {
            "messages": anthropic_messages,
        }

        # 添加工具 (包括 computer 工具)
        if tools:
            # Anthropic 使用 tools 参数
            request_params["tools"] = self._convert_tools_to_anthropic(tools)

        # 添加 computer 工具 (如果提供了 computer_handler)
        if computer_handler:
            computer_tool = await self._build_computer_tool(computer_handler)
            if "tools" not in request_params:
                request_params["tools"] = []
            request_params["tools"].append(computer_tool)

        # 执行预测
        response = await self._predict_anthropic(request_params)

        # 处理 tool_calls (包括 computer 工具)
        if response.tool_calls:
            logger.info("LLM returned %s tool calls", len(response.tool_calls))

            # 执行工具
            tool_messages = await self.handle_tool_calls(response.tool_calls, messages)

            # 将工具结果添加到 messages
            messages.extend(tool_messages)

            # 递归调用，直到没有 tool_calls
            return await self.predict_step(messages, tools, computer_handler, **kwargs)

        return response

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

    async def _predict_anthropic(self, request_params: Dict) -> LLMResponse:
        """
        调用 Anthropic API 进行预测
        """
        # 使用 llm_client 调用 (假设它支持 Anthropic)
        response = await self.llm_client.chat(**request_params)
        return response

    async def handle_tool_calls(self, tool_calls: List, messages: List[Dict]) -> List[Dict]:
        """
        处理工具调用 (重写基类方法，添加 computer 工具支持)
        """
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
