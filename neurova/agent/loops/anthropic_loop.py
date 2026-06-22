"""
Anthropic Loop - Anthropic 模型适配循环

支持: Claude-3 系列 (opus, sonnet, haiku)
特殊能力: computer_use_preview (通过 tools 参数)
"""

import json
import logging
from typing import Any, Dict, List, Optional

from neurova.agent.loops.base import BaseAgentLoop
from neurova.llm_client import LLMResponse

logger = logging.getLogger(__name__)


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
        """
        anthropic_messages = []

        for msg in messages:
            role = msg["role"]
            content = msg["content"]

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

            # 转换 content
            if isinstance(content, str):
                ant_content = [{"type": "text", "text": content}]
            else:
                ant_content = content  # 已经是正确格式

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
