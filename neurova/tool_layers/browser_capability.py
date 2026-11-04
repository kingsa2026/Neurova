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


#: 真实后端的描述表（按 BrowserManager.availableBackendNames 的名字索引）。
#: 只声明本仓实装支持的能力；后端不在表里就不注入，避免给模型编造能力。
_BACKEND_DESCRIPTORS: typing.Dict[str, BrowserBackendCapability] = {
    "playwright": BrowserBackendCapability(
        backend_name="playwright",
        capabilities=["navigate", "click", "type", "screenshot", "dom_snapshot", "execute_js"],
        limitations=["单活动页面（max_pages=1）", "依赖本机 Playwright 浏览器内核"],
        best_for=["动态网页", "登录态操作", "表单交互"],
        max_pages=1,
        supports_geolocation=True,
    ),
    "scrapling": BrowserBackendCapability(
        backend_name="scrapling",
        capabilities=["static_fetch", "extract_text", "extract_links"],
        limitations=["不执行 JavaScript", "无页面交互"],
        best_for=["静态页面", "批量抓取"],
        max_pages=1,
    ),
    "camofox": BrowserBackendCapability(
        backend_name="camofox",
        capabilities=["navigate", "click", "type", "screenshot", "anti_detection"],
        limitations=["依赖外部 camofox 服务", "按用户池化，跨用户不共享"],
        best_for=["反检测站点", "高风控页面"],
        max_pages=1,
    ),
}


def buildBrowserCapabilityContext(
    backendNames: typing.Optional[typing.Iterable[str]] = None,
) -> str:
    """把当前真可用后端的描述渲染成 system prompt 段。

    消费方：context/orchestrator.get_tools_description（仅在工具面含浏览器/电脑
    工具时调用）。不传 backendNames 时经 BrowserManager.availableBackendNames()
    读运行时实装；取不到或没有已知后端返回空串（不注入编造的能力）。
    """
    if backendNames is None:
        try:
            from neurova.computer_use.browser_manager import get_browser_manager

            backendNames = get_browser_manager().availableBackendNames()
        except Exception as exc:  # noqa: BLE001 - 能力描述不可用不阻断 prompt
            logger.debug("浏览器后端能力读取失败（跳过注入）: %s", exc)
            return ""
    present = {str(name) for name in backendNames}
    capabilities = [
        capability for name, capability in _BACKEND_DESCRIPTORS.items() if name in present
    ]
    if not capabilities:
        return ""
    lines = [
        "## 浏览器后端能力",
        "工具会自动路由到可用后端；以下只说明各自的能力边界，供选择操作方式。",
    ]
    lines.extend(capability.to_llm_context() for capability in capabilities)
    return "\n\n".join(lines)
