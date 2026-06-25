"""
内置模型适配器 — 常用 LLM 的支持

隔离层级: 全局（无状态路由）
"""

import json
from neurova.core.logger import get_logger
from typing import Any, AsyncIterator, Dict, List, Optional


from neurova.cognitive_layers.model_adapter.base import AdapterCapabilities, BaseModelAdapter, ToolCall, ToolCallType
from neurova.cognitive_layers.model_adapter.registry import (
    _generate_with_litellm,
    _stream_with_litellm,
    get_model_adapter_registry,
)

logger = get_logger(__name__)


class DeepSeekAdapter(BaseModelAdapter):
    """DeepSeek 模型适配器"""

    def __init__(self, model_name: str, config: Optional[Dict[str, Any]] = None):
        super().__init__(model_name, config)
        self.api_key = config.get("api_key", "") if config else ""
        self.api_base = config.get("api_base", "https://api.deepseek.com") if config else "https://api.deepseek.com"

    def _declare_capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            supports_streaming=True,
            supports_function_calling=True,
            supports_vision="vision" in self.model_name.lower() or "vl" in self.model_name.lower(),
            supports_json_mode=True,
            supports_parallel_function_calls=True,
            supports_tool_choice=True,
            max_context_length=128000,
            custom_capabilities={
                "supports_reasoning": "deepseek-reasoner" in self.model_name.lower(),
                "supports_coding": True,
            },
        )

    def format_prompt(
        self, messages: List[Dict[str, Any]], system_prompt: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """格式化提示词为 OpenAI 格式"""
        formatted = []
        if system_prompt:
            formatted.append({"role": "system", "content": system_prompt})

        for msg in messages:
            if isinstance(msg, dict):
                formatted.append(msg)
            else:
                formatted.append({"role": "user", "content": str(msg)})

        return formatted

    async def generate(self, prompt: Any, **kwargs) -> str:
        """生成文本"""
        try:
            return await _generate_with_litellm(
                model=self.model_name, messages=prompt, api_key=self.api_key, api_base=self.api_base, **kwargs
            )
        except Exception as e:
            self._last_error = str(e)
            self.logger.error("DeepSeek generate error: %s", e)
            raise

    async def generate_stream(self, prompt: Any, **kwargs) -> AsyncIterator[str]:
        """流式生成文本"""
        try:
            async for chunk in _stream_with_litellm(
                model=self.model_name, messages=prompt, api_key=self.api_key, api_base=self.api_base, **kwargs
            ):
                yield chunk
        except Exception as e:
            self._last_error = str(e)
            self.logger.error("DeepSeek stream error: %s", e)
            raise

    def parse_tool_call(self, response: Any) -> Optional[ToolCall]:
        """解析工具调用"""
        if not isinstance(response, dict):
            return None

        choices = response.get("choices", [])
        if not choices:
            return None

        message = choices[0].get("message", {})
        tool_calls = message.get("tool_calls", [])

        if not tool_calls:
            return None

        tc = tool_calls[0]
        function_data = tc.get("function", {})

        try:
            arguments = json.loads(function_data.get("arguments", "{}"))
        except json.JSONDecodeError:
            arguments = {}

        return ToolCall(
            id=tc.get("id", f"call_{id(tc)}"),
            type=ToolCallType.FUNCTION,
            function_name=function_data.get("name", ""),
            arguments=arguments,
            raw_data=tc,
        )

    def extract_content(self, response: Any) -> str:
        """提取响应内容"""
        if isinstance(response, str):
            return response

        if isinstance(response, dict):
            choices = response.get("choices", [])
            if choices:
                message = choices[0].get("message", {})
                return message.get("content", "")

        return ""

    def _create_client(self) -> Any:
        """创建 DeepSeek 客户端"""
        return None  # 使用 litellm 路由，不需要单独客户端


class ClaudeAdapter(BaseModelAdapter):
    """Claude 模型适配器"""

    def __init__(self, model_name: str, config: Optional[Dict[str, Any]] = None):
        super().__init__(model_name, config)
        self.api_key = config.get("api_key", "") if config else ""
        self.api_base = config.get("api_base", "https://api.anthropic.com") if config else "https://api.anthropic.com"

    def _declare_capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            supports_streaming=True,
            supports_function_calling=True,
            supports_vision="claude-3" in self.model_name.lower(),
            supports_json_mode=False,
            supports_parallel_function_calls=False,
            supports_tool_choice=True,
            max_context_length=200000,
            custom_capabilities={
                "supports_extended_thinking": "claude-3.5" in self.model_name.lower()
                or "claude-3-opus" in self.model_name.lower(),
                "supports_citations": True,
            },
        )

    def format_prompt(self, messages: List[Dict[str, Any]], system_prompt: Optional[str] = None) -> Dict[str, Any]:
        """格式化提示词为 Claude 格式"""
        formatted_messages = []

        for msg in messages:
            if isinstance(msg, dict):
                role = msg.get("role", "user")
                content = msg.get("content", "")

                # Claude 使用 user/assistant 角色
                if role == "system":
                    continue  # 系统提示单独处理

                formatted_messages.append({"role": role, "content": content})
            else:
                formatted_messages.append({"role": "user", "content": str(msg)})

        result = {"messages": formatted_messages}
        if system_prompt:
            result["system"] = system_prompt

        return result

    async def generate(self, prompt: Any, **kwargs) -> str:
        """生成文本"""
        try:
            # Claude 使用不同的消息格式
            messages = prompt.get("messages", [])
            system = prompt.get("system")

            formatted = []
            if system:
                formatted.append({"role": "system", "content": system})
            formatted.extend(messages)

            return await _generate_with_litellm(
                model=self.model_name, messages=formatted, api_key=self.api_key, **kwargs
            )
        except Exception as e:
            self._last_error = str(e)
            self.logger.error("Claude generate error: %s", e)
            raise

    async def generate_stream(self, prompt: Any, **kwargs) -> AsyncIterator[str]:
        """流式生成文本"""
        try:
            messages = prompt.get("messages", [])
            system = prompt.get("system")

            formatted = []
            if system:
                formatted.append({"role": "system", "content": system})
            formatted.extend(messages)

            async for chunk in _stream_with_litellm(
                model=self.model_name, messages=formatted, api_key=self.api_key, **kwargs
            ):
                yield chunk
        except Exception as e:
            self._last_error = str(e)
            self.logger.error("Claude stream error: %s", e)
            raise

    def parse_tool_call(self, response: Any) -> Optional[ToolCall]:
        """解析工具调用"""
        if not isinstance(response, dict):
            return None

        content = response.get("content", [])
        if not content:
            return None

        for block in content:
            if block.get("type") == "tool_use":
                return ToolCall(
                    id=block.get("id", f"call_{id(block)}"),
                    type=ToolCallType.TOOL,
                    function_name=block.get("name", ""),
                    arguments=block.get("input", {}),
                    raw_data=block,
                )

        return None

    def extract_content(self, response: Any) -> str:
        """提取响应内容"""
        if isinstance(response, str):
            return response

        if isinstance(response, dict):
            content = response.get("content", [])
            if content:
                # 提取文本内容
                text_parts = []
                for block in content:
                    if block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                return "".join(text_parts)

        return ""

    def _create_client(self) -> Any:
        """创建 Claude 客户端"""
        return None  # 使用 litellm 路由


class HunYuanAdapter(BaseModelAdapter):
    """混元模型适配器"""

    def __init__(self, model_name: str, config: Optional[Dict[str, Any]] = None):
        super().__init__(model_name, config)
        self.secret_id = config.get("secret_id", "") if config else ""
        self.secret_key = config.get("secret_key", "") if config else ""
        self.region = config.get("region", "ap-guangzhou") if config else "ap-guangzhou"

    def _declare_capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            supports_streaming=True,
            supports_function_calling=True,
            supports_vision="vision" in self.model_name.lower(),
            supports_json_mode=True,
            supports_parallel_function_calls=False,
            supports_tool_choice=False,
            max_context_length=32000,
            custom_capabilities={"supports_tencent_auth": True, "supports_regional_deployment": True},
        )

    def format_prompt(
        self, messages: List[Dict[str, Any]], system_prompt: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """格式化提示词"""
        formatted = []
        if system_prompt:
            formatted.append({"role": "system", "content": system_prompt})

        for msg in messages:
            if isinstance(msg, dict):
                formatted.append(msg)
            else:
                formatted.append({"role": "user", "content": str(msg)})

        return formatted

    async def generate(self, prompt: Any, **kwargs) -> str:
        """生成文本"""
        try:
            return await _generate_with_litellm(
                model=self.model_name,
                messages=prompt,
                secret_id=self.secret_id,
                secret_key=self.secret_key,
                region=self.region,
                **kwargs,
            )
        except Exception as e:
            self._last_error = str(e)
            self.logger.error("HunYuan generate error: %s", e)
            raise

    async def generate_stream(self, prompt: Any, **kwargs) -> AsyncIterator[str]:
        """流式生成文本"""
        try:
            async for chunk in _stream_with_litellm(
                model=self.model_name,
                messages=prompt,
                secret_id=self.secret_id,
                secret_key=self.secret_key,
                region=self.region,
                **kwargs,
            ):
                yield chunk
        except Exception as e:
            self._last_error = str(e)
            self.logger.error("HunYuan stream error: %s", e)
            raise

    def parse_tool_call(self, response: Any) -> Optional[ToolCall]:
        """解析工具调用"""
        if not isinstance(response, dict):
            return None

        choices = response.get("choices", [])
        if not choices:
            return None

        message = choices[0].get("message", {})
        tool_calls = message.get("tool_calls", [])

        if not tool_calls:
            return None

        tc = tool_calls[0]
        function_data = tc.get("function", {})

        try:
            arguments = json.loads(function_data.get("arguments", "{}"))
        except json.JSONDecodeError:
            arguments = {}

        return ToolCall(
            id=tc.get("id", f"call_{id(tc)}"),
            type=ToolCallType.FUNCTION,
            function_name=function_data.get("name", ""),
            arguments=arguments,
            raw_data=tc,
        )

    def extract_content(self, response: Any) -> str:
        """提取响应内容"""
        if isinstance(response, str):
            return response

        if isinstance(response, dict):
            choices = response.get("choices", [])
            if choices:
                message = choices[0].get("message", {})
                return message.get("content", "")

        return ""

    def _create_client(self) -> Any:
        """创建混元客户端"""
        return None


class GLMAdapter(BaseModelAdapter):
    """GLM 模型适配器"""

    def __init__(self, model_name: str, config: Optional[Dict[str, Any]] = None):
        super().__init__(model_name, config)
        self.api_key = config.get("api_key", "") if config else ""
        self.api_base = (
            config.get("api_base", "https://open.bigmodel.cn/api/paas/v4")
            if config
            else "https://open.bigmodel.cn/api/paas/v4"
        )

    def _declare_capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            supports_streaming=True,
            supports_function_calling=True,
            supports_vision="vision" in self.model_name.lower() or "v" in self.model_name.lower(),
            supports_json_mode=True,
            supports_parallel_function_calls=True,
            supports_tool_choice=True,
            max_context_length=128000,
            custom_capabilities={"supports_web_search": True, "supports_code_interpreter": True},
        )

    def format_prompt(
        self, messages: List[Dict[str, Any]], system_prompt: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """格式化提示词"""
        formatted = []
        if system_prompt:
            formatted.append({"role": "system", "content": system_prompt})

        for msg in messages:
            if isinstance(msg, dict):
                formatted.append(msg)
            else:
                formatted.append({"role": "user", "content": str(msg)})

        return formatted

    async def generate(self, prompt: Any, **kwargs) -> str:
        """生成文本"""
        try:
            return await _generate_with_litellm(
                model=self.model_name, messages=prompt, api_key=self.api_key, api_base=self.api_base, **kwargs
            )
        except Exception as e:
            self._last_error = str(e)
            self.logger.error("GLM generate error: %s", e)
            raise

    async def generate_stream(self, prompt: Any, **kwargs) -> AsyncIterator[str]:
        """流式生成文本"""
        try:
            async for chunk in _stream_with_litellm(
                model=self.model_name, messages=prompt, api_key=self.api_key, api_base=self.api_base, **kwargs
            ):
                yield chunk
        except Exception as e:
            self._last_error = str(e)
            self.logger.error("GLM stream error: %s", e)
            raise

    def parse_tool_call(self, response: Any) -> Optional[ToolCall]:
        """解析工具调用"""
        if not isinstance(response, dict):
            return None

        choices = response.get("choices", [])
        if not choices:
            return None

        message = choices[0].get("message", {})
        tool_calls = message.get("tool_calls", [])

        if not tool_calls:
            return None

        tc = tool_calls[0]
        function_data = tc.get("function", {})

        try:
            arguments = json.loads(function_data.get("arguments", "{}"))
        except json.JSONDecodeError:
            arguments = {}

        return ToolCall(
            id=tc.get("id", f"call_{id(tc)}"),
            type=ToolCallType.FUNCTION,
            function_name=function_data.get("name", ""),
            arguments=arguments,
            raw_data=tc,
        )

    def extract_content(self, response: Any) -> str:
        """提取响应内容"""
        if isinstance(response, str):
            return response

        if isinstance(response, dict):
            choices = response.get("choices", [])
            if choices:
                message = choices[0].get("message", {})
                return message.get("content", "")

        return ""

    def _create_client(self) -> Any:
        """创建 GLM 客户端"""
        return None


class KimiAdapter(BaseModelAdapter):
    """Kimi 模型适配器"""

    def __init__(self, model_name: str, config: Optional[Dict[str, Any]] = None):
        super().__init__(model_name, config)
        self.api_key = config.get("api_key", "") if config else ""
        self.api_base = config.get("api_base", "https://api.moonshot.cn/v1") if config else "https://api.moonshot.cn/v1"

    def _declare_capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            supports_streaming=True,
            supports_function_calling=True,
            supports_vision=False,  # Kimi 主要支持文本
            supports_json_mode=True,
            supports_parallel_function_calls=False,
            supports_tool_choice=True,
            max_context_length=128000,
            custom_capabilities={
                "supports_web_browsing": True,
                "supports_file_upload": True,
                "supports_long_context": True,
            },
        )

    def format_prompt(
        self, messages: List[Dict[str, Any]], system_prompt: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """格式化提示词"""
        formatted = []
        if system_prompt:
            formatted.append({"role": "system", "content": system_prompt})

        for msg in messages:
            if isinstance(msg, dict):
                formatted.append(msg)
            else:
                formatted.append({"role": "user", "content": str(msg)})

        return formatted

    async def generate(self, prompt: Any, **kwargs) -> str:
        """生成文本"""
        try:
            return await _generate_with_litellm(
                model=self.model_name, messages=prompt, api_key=self.api_key, api_base=self.api_base, **kwargs
            )
        except Exception as e:
            self._last_error = str(e)
            self.logger.error("Kimi generate error: %s", e)
            raise

    async def generate_stream(self, prompt: Any, **kwargs) -> AsyncIterator[str]:
        """流式生成文本"""
        try:
            async for chunk in _stream_with_litellm(
                model=self.model_name, messages=prompt, api_key=self.api_key, api_base=self.api_base, **kwargs
            ):
                yield chunk
        except Exception as e:
            self._last_error = str(e)
            self.logger.error("Kimi stream error: %s", e)
            raise

    def parse_tool_call(self, response: Any) -> Optional[ToolCall]:
        """解析工具调用"""
        if not isinstance(response, dict):
            return None

        choices = response.get("choices", [])
        if not choices:
            return None

        message = choices[0].get("message", {})
        tool_calls = message.get("tool_calls", [])

        if not tool_calls:
            return None

        tc = tool_calls[0]
        function_data = tc.get("function", {})

        try:
            arguments = json.loads(function_data.get("arguments", "{}"))
        except json.JSONDecodeError:
            arguments = {}

        return ToolCall(
            id=tc.get("id", f"call_{id(tc)}"),
            type=ToolCallType.FUNCTION,
            function_name=function_data.get("name", ""),
            arguments=arguments,
            raw_data=tc,
        )

    def extract_content(self, response: Any) -> str:
        """提取响应内容"""
        if isinstance(response, str):
            return response

        if isinstance(response, dict):
            choices = response.get("choices", [])
            if choices:
                message = choices[0].get("message", {})
                return message.get("content", "")

        return ""

    def _create_client(self) -> Any:
        """创建 Kimi 客户端"""
        return None


def register_builtin_adapters() -> None:
    """
    注册内置适配器

    在模块初始化时自动调用，将所有内置适配器注册到注册表。
    """
    registry = get_model_adapter_registry()

    # 定义适配器映射关系
    adapter_mappings = [
        # DeepSeek 模型
        (r"deepseek-.*", DeepSeekAdapter, 90),
        (r"deepseek/.*", DeepSeekAdapter, 90),
        # Claude 模型
        (r"claude-.*", ClaudeAdapter, 80),
        (r"anthropic/.*", ClaudeAdapter, 80),
        # 混元模型
        (r"hunyuan-.*", HunYuanAdapter, 70),
        (r"hunyuan/.*", HunYuanAdapter, 70),
        # GLM 模型
        (r"glm-.*", GLMAdapter, 60),
        (r"chatglm-.*", GLMAdapter, 60),
        (r"zhipu/.*", GLMAdapter, 60),
        # Kimi 模型
        (r"kimi-.*", KimiAdapter, 50),
        (r"moonshot-.*", KimiAdapter, 50),
        (r"moonshot/.*", KimiAdapter, 50),
    ]

    for pattern, adapter_class, priority in adapter_mappings:
        registry.register_adapter_pattern(pattern=pattern, adapter_class=adapter_class, priority=priority)
        logger.info("Registered adapter pattern: %s -> %s (priority: %s)", pattern, adapter_class.__name__, priority)


# 模块导入时自动注册内置适配器
register_builtin_adapters()
