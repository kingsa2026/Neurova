"""
BaseModelAdapter — 模型适配器基类

所有模型适配器的统一抽象接口。
"""

import logging
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, AsyncIterator, Dict, List, Optional

from pydantic import BaseModel, Field


class ToolCallType(str, Enum):
    """工具调用类型"""

    FUNCTION = "function"
    TOOL = "tool"
    UNKNOWN = "unknown"


class ToolCall(BaseModel):
    """工具调用数据结构"""

    id: str = Field(default_factory=lambda: f"call_{id(self)}")
    type: ToolCallType = ToolCallType.FUNCTION
    function_name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)
    raw_data: Optional[Dict[str, Any]] = None

    class Config:
        use_enum_values = True


class AdapterCapabilities(BaseModel):
    """适配器能力描述"""

    supports_streaming: bool = True
    supports_function_calling: bool = False
    supports_vision: bool = False
    supports_audio: bool = False
    supports_video: bool = False
    supports_image_generation: bool = False
    max_context_length: int = 4096
    supports_json_mode: bool = False
    supports_parallel_function_calls: bool = False
    supports_tool_choice: bool = False
    custom_capabilities: Dict[str, Any] = Field(default_factory=dict)

    def has_capability(self, capability_name: str) -> bool:
        """检查是否具有指定能力"""
        standard_caps = {
            "streaming": self.supports_streaming,
            "function_calling": self.supports_function_calling,
            "vision": self.supports_vision,
            "audio": self.supports_audio,
            "video": self.supports_video,
            "image_generation": self.supports_image_generation,
            "json_mode": self.supports_json_mode,
            "parallel_function_calls": self.supports_parallel_function_calls,
            "tool_choice": self.supports_tool_choice,
        }
        if capability_name in standard_caps:
            return standard_caps[capability_name]
        return self.custom_capabilities.get(capability_name, False)


class BaseModelAdapter(ABC):
    """
    模型适配器抽象基类

    所有模型适配器必须实现此基类定义的接口。
    适配器负责将不同 LLM 提供商的 API 差异统一化。
    """

    def __init__(self, model_name: str, config: Optional[Dict[str, Any]] = None):
        """
        初始化适配器

        Args:
            model_name: 模型名称
            config: 配置字典，包含 API 密钥、端点等
        """
        self.model_name = model_name
        self.config = config or {}
        self.logger = logging.getLogger(f"{self.__class__.__name__}[{model_name}]")
        self._capabilities = self._declare_capabilities()
        self._client = None
        self._last_error = None

    @abstractmethod
    def _declare_capabilities(self) -> AdapterCapabilities:
        """
        声明适配器支持的能力

        Returns:
            AdapterCapabilities: 能力描述对象
        """

    @abstractmethod
    def format_prompt(self, messages: List[Dict[str, Any]], system_prompt: Optional[str] = None) -> Any:
        """
        格式化提示词

        Args:
            messages: 消息列表
            system_prompt: 系统提示词

        Returns:
            格式化后的提示词
        """

    @abstractmethod
    async def generate(self, prompt: Any, **kwargs) -> str:
        """
        生成文本

        Args:
            prompt: 格式化后的提示词
            **kwargs: 其他参数

        Returns:
            生成的文本
        """

    @abstractmethod
    async def generate_stream(self, prompt: Any, **kwargs) -> AsyncIterator[str]:
        """
        流式生成文本

        Args:
            prompt: 格式化后的提示词
            **kwargs: 其他参数

        Yields:
            生成的文本片段
        """

    @abstractmethod
    def parse_tool_call(self, response: Any) -> Optional[ToolCall]:
        """
        解析工具调用

        Args:
            response: 模型响应

        Returns:
            工具调用对象，如果没有工具调用则返回 None
        """

    @abstractmethod
    def extract_content(self, response: Any) -> str:
        """
        提取模型响应内容

        Args:
            response: 模型响应

        Returns:
            提取的内容
        """

    def get_llm_client(self) -> Any:
        """
        获取 LLM 客户端实例

        Returns:
            LLM 客户端实例
        """
        if self._client is None:
            self._client = self._create_client()
        return self._client

    @abstractmethod
    def _create_client(self) -> Any:
        """
        创建 LLM 客户端

        Returns:
            LLM 客户端实例
        """

    @property
    def capabilities(self) -> AdapterCapabilities:
        """获取适配器能力"""
        return self._capabilities

    def supports_function_calling(self) -> bool:
        """检查是否支持函数调用"""
        return self._capabilities.supports_function_calling

    def supports_streaming(self) -> bool:
        """检查是否支持流式生成"""
        return self._capabilities.supports_streaming

    def get_max_context_length(self) -> int:
        """获取最大上下文长度"""
        return self._capabilities.max_context_length

    def get_config(self, key: str, default: Any = None) -> Any:
        """获取配置值"""
        return self.config.get(key, default)

    def update_config(self, updates: Dict[str, Any]) -> None:
        """更新配置"""
        self.config.update(updates)

    def get_last_error(self) -> Optional[str]:
        """获取最后一次错误信息"""
        return self._last_error

    def clear_error(self) -> None:
        """清除错误信息"""
        self._last_error = None

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(model={self.model_name})"

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "class_name": self.__class__.__name__,
            "model_name": self.model_name,
            "config": self.config,
            "capabilities": self._capabilities.dict(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BaseModelAdapter":
        """从字典创建适配器"""
        return cls(model_name=data["model_name"], config=data.get("config", {}))


# 便捷函数
def create_adapter(adapter_class: type, model_name: str, config: Optional[Dict[str, Any]] = None) -> BaseModelAdapter:
    """
    创建适配器实例

    Args:
        adapter_class: 适配器类
        model_name: 模型名称
        config: 配置字典

    Returns:
        适配器实例
    """
    return adapter_class(model_name=model_name, config=config)


def get_adapter_info(adapter: BaseModelAdapter) -> Dict[str, Any]:
    """
    获取适配器信息

    Args:
        adapter: 适配器实例

    Returns:
        适配器信息字典
    """
    return {
        "model_name": adapter.model_name,
        "class_name": adapter.__class__.__name__,
        "capabilities": adapter.capabilities.dict(),
        "supports_function_calling": adapter.supports_function_calling(),
        "supports_streaming": adapter.supports_streaming(),
        "max_context_length": adapter.get_max_context_length(),
    }
