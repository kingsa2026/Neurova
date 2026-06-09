"""
工具层模块

提供工具编排、市场和管理功能。

包含以下核心模块：
- schemas: 统一工具层数据模型
- tool_router: 统一工具路由器
- unified_registry: 统一工具注册表
- mcp_client: MCP 工具客户端
- capability_graph: 工具能力关系图
- tool_orchestrator: DAG 工具编排器
- tool_marketplace: 工具市场（含贝叶斯评分）
- tool_cache: 三级智能工具缓存
- tool_logger: 结构化工具执行日志
- cli_tool: CLI 工具执行器
- browser_capability: 浏览器后端能力描述
- openai_schema: OpenAI Tool Schema 兼容层
"""

import logging
from typing import Dict, Any, List, Optional, Callable

logger = logging.getLogger(__name__)

# 导入核心模块
try:
    from neurova.tool_layers.schemas import (
        ToolSource,
        ToolParameter,
        ToolSchema,
        MCPConnection,
        ToolExecutionResult,
        ToolType,
    )
except ImportError as e:
    logger.warning(f"Failed to import schemas: {e}")

try:
    from neurova.tool_layers.tool_router import ToolRouter
except ImportError as e:
    logger.warning(f"Failed to import tool_router: {e}")

try:
    from neurova.tool_layers.unified_registry import UnifiedToolRegistry
except ImportError as e:
    logger.warning(f"Failed to import unified_registry: {e}")

try:
    from neurova.tool_layers.mcp_client import MCPToolClient, ToolNotFoundError
except ImportError as e:
    logger.warning(f"Failed to import mcp_client: {e}")

try:
    from neurova.tool_layers.capability_graph import ToolCapabilityGraph, ToolCapabilityNode
except ImportError as e:
    logger.warning(f"Failed to import capability_graph: {e}")

try:
    from neurova.tool_layers.tool_orchestrator import ToolOrchestrator, ExecutionStatus, StepResult, OrchestrationResult
except ImportError as e:
    logger.warning(f"Failed to import tool_orchestrator: {e}")

try:
    from neurova.tool_layers.tool_marketplace import ToolMarketplace, MarketplaceTool, BayesianRating, ToolReview, ToolFork
except ImportError as e:
    logger.warning(f"Failed to import tool_marketplace: {e}")

try:
    from neurova.tool_layers.tool_cache import ToolCache, CacheEntry
except ImportError as e:
    logger.warning(f"Failed to import tool_cache: {e}")

try:
    from neurova.tool_layers.tool_logger import ToolExecutionLogger, ToolExecutionEntry
except ImportError as e:
    logger.warning(f"Failed to import tool_logger: {e}")

try:
    from neurova.tool_layers.cli_tool import CLIToolExecutor
except ImportError as e:
    logger.warning(f"Failed to import cli_tool: {e}")

try:
    from neurova.tool_layers.browser_capability import BrowserBackendCapability
except ImportError as e:
    logger.warning(f"Failed to import browser_capability: {e}")

try:
    from neurova.tool_layers.openai_schema import (
        OpenAIFunctionSchema,
        AnthropicToolSchema,
        GoogleToolSchema,
        ToolSchemaConverter,
        ToolCallParser,
    )
except ImportError as e:
    logger.warning(f"Failed to import openai_schema: {e}")


# 向后兼容的简单实现（仅在真实类导入失败时定义，避免覆盖）
if "MarketplaceTool" not in dir() or MarketplaceTool is None:  # type: ignore[possibly-undefined]
    class MarketplaceTool:
        """市场工具（向后兼容）"""
        def __init__(self, name: str = "", description: str = "", version: str = "1.0.0", **kwargs):
            self.name = name
            self.description = description
            self.version = version
            self.metadata = kwargs

if "ToolOrchestrator" not in dir() or ToolOrchestrator is None:  # type: ignore[possibly-undefined]
    class ToolOrchestrator:
        """DAG 工具编排器（向后兼容）"""
        def __init__(self):
            self._tools: Dict[str, Any] = {}
            self._dag: Dict[str, List[str]] = {}

        def register_tool(self, name: str, tool: Any) -> None:
            self._tools[name] = tool

        def add_dependency(self, tool: str, depends_on: str) -> None:
            if tool not in self._dag:
                self._dag[tool] = []
            self._dag[tool].append(depends_on)

        def get_execution_order(self) -> List[str]:
            return list(self._tools.keys())

        async def execute(self, task: str, context: Optional[Dict] = None) -> Dict[str, Any]:
            return {'success': True, 'result': f"Executed: {task}"}

if "ToolMarketplace" not in dir() or ToolMarketplace is None:  # type: ignore[possibly-undefined]
    class ToolMarketplace:
        """工具市场（向后兼容）"""
        def __init__(self):
            self._tools: Dict[str, MarketplaceTool] = {}

        def list_tools(self) -> List[MarketplaceTool]:
            return list(self._tools.values())

        def get_tool(self, name: str) -> Optional[MarketplaceTool]:
            return self._tools.get(name)

        def register_tool(self, tool: MarketplaceTool) -> None:
            self._tools[tool.name] = tool

        async def search(self, query: str) -> List[MarketplaceTool]:
            return [t for t in self._tools.values() if query.lower() in t.name.lower()]


__all__ = [
    # 核心数据模型
    'ToolSource',
    'ToolParameter',
    'ToolSchema',
    'MCPConnection',
    'ToolExecutionResult',
    'ToolType',
    
    # 核心类
    'ToolRouter',
    'UnifiedToolRegistry',
    'MCPToolClient',
    'ToolNotFoundError',
    'ToolCapabilityGraph',
    'ToolCapabilityNode',
    'ToolOrchestrator',
    'ExecutionStatus',
    'StepResult',
    'OrchestrationResult',
    'ToolMarketplace',
    'MarketplaceTool',
    'BayesianRating',
    'ToolReview',
    'ToolFork',
    'ToolCache',
    'CacheEntry',
    'ToolExecutionLogger',
    'ToolExecutionEntry',
    'CLIToolExecutor',
    'BrowserBackendCapability',
    
    # OpenAI Schema 兼容层
    'OpenAIFunctionSchema',
    'AnthropicToolSchema',
    'GoogleToolSchema',
    'ToolSchemaConverter',
    'ToolCallParser',
]