"""
Browser Backend Capability v1.0.0 — 浏览器后端能力描述

职责:
- 描述每个浏览器后端的能力、限制和最佳场景
- 生成 LLM 可读的后端能力上下文
- 支持根据任务类型推荐合适的后端

隔离层级: 与 ComputerUseManager 协作，注入到 LLM system prompt
"""

from neurova.core.logger import get_logger
import typing

logger = get_logger(__name__)


class BrowserBackendCapability:
    """
    浏览器后端能力描述

    功能：
    1. 描述后端能力
    2. 检查能力支持
    3. 生成 LLM 上下文
    4. 支持序列化和反序列化
    """

    def __init__(
        self,
        backend_name: str,
        capabilities: typing.List[str] = None,
        limitations: typing.List[str] = None,
        best_for: typing.List[str] = None,
        max_pages: int = 1,
        supports_mobile: bool = False,
        supports_geolocation: bool = False,
        metadata: typing.Dict[str, typing.Any] = None,
    ):
        """
        初始化能力描述

        参数:
            backend_name: 后端名称
            capabilities: 能力列表
            limitations: 限制列表
            best_for: 最佳使用场景
            max_pages: 最大页面数
            supports_mobile: 是否支持移动端
            supports_geolocation: 是否支持地理定位
            metadata: 额外元数据
        """
        self.backend_name = backend_name
        self.capabilities = capabilities or []
        self.limitations = limitations or []
        self.best_for = best_for or []
        self.max_pages = max_pages
        self.supports_mobile = supports_mobile
        self.supports_geolocation = supports_geolocation
        self.metadata = metadata or {}

    def has_capability(self, capability: str) -> bool:
        """
        检查是否具有指定能力

        参数:
            capability: 能力名称

        返回:
            是否具有该能力
        """
        return capability in self.capabilities

    def has_any_capability(self, capabilities: typing.List[str]) -> bool:
        """
        检查是否具有任意一个指定能力

        参数:
            capabilities: 能力列表

        返回:
            是否具有任意一个能力
        """
        return any(cap in self.capabilities for cap in capabilities)

    def has_all_capabilities(self, capabilities: typing.List[str]) -> bool:
        """
        检查是否具有所有指定能力

        参数:
            capabilities: 能力列表

        返回:
            是否具有所有能力
        """
        return all(cap in self.capabilities for cap in capabilities)

    def is_suitable_for(self, task: str) -> bool:
        """
        检查是否适合指定任务

        参数:
            task: 任务类型

        返回:
            是否适合
        """
        return task in self.best_for

    def get_limitations(self) -> typing.List[str]:
        """
        获取限制列表

        返回:
            限制列表
        """
        return self.limitations.copy()

    def to_dict(self) -> typing.Dict[str, typing.Any]:
        """
        转换为字典

        返回:
            字典表示
        """
        return {
            "backend_name": self.backend_name,
            "capabilities": self.capabilities,
            "limitations": self.limitations,
            "best_for": self.best_for,
            "max_pages": self.max_pages,
            "supports_mobile": self.supports_mobile,
            "supports_geolocation": self.supports_geolocation,
            "metadata": self.metadata,
        }

    def to_llm_context(self) -> str:
        """
        生成 LLM 可读的上下文

        返回:
            上下文文本
        """
        lines = [f"Browser Backend: {self.backend_name}"]

        if self.capabilities:
            lines.append(f"Capabilities: {', '.join(self.capabilities)}")

        if self.limitations:
            lines.append(f"Limitations: {', '.join(self.limitations)}")

        if self.best_for:
            lines.append(f"Best for: {', '.join(self.best_for)}")

        lines.append(f"Max pages: {self.max_pages}")
        lines.append(f"Supports mobile: {self.supports_mobile}")
        lines.append(f"Supports geolocation: {self.supports_geolocation}")

        if self.metadata:
            for key, value in self.metadata.items():
                lines.append(f"{key}: {value}")

        return "\n".join(lines)

    @classmethod
    def from_dict(cls, data: typing.Dict[str, typing.Any]) -> "BrowserBackendCapability":
        """
        从字典创建

        参数:
            data: 字典数据

        返回:
            BrowserBackendCapability 实例
        """
        return cls(
            backend_name=data["backend_name"],
            capabilities=data.get("capabilities", []),
            limitations=data.get("limitations", []),
            best_for=data.get("best_for", []),
            max_pages=data.get("max_pages", 1),
            supports_mobile=data.get("supports_mobile", False),
            supports_geolocation=data.get("supports_geolocation", False),
            metadata=data.get("metadata", {}),
        )

    def __repr__(self) -> str:
        """字符串表示"""
        return f"BrowserBackendCapability(backend_name='{self.backend_name}')"
