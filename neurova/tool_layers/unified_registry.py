"""
Unified Tool Registry v1.0.0 — 统一工具注册表

职责:
- 在 ToolRouter 和 ToolEngine 之间建立双向同步
- ToolRouter 注册内置工具 → 自动同步到 ToolEngine
- ToolEngine 注册工具 → ToolRouter 可发现
- 关联 ToolCapabilityGraph 提供工具关系查询

隔离层级: 适配器层，位于 ToolRouter 和 ToolEngine 之间
"""

import datetime
from neurova.core.logger import get_logger
import time
import typing

logger = get_logger(__name__)


# 导入依赖模块（使用延迟导入避免循环依赖）
def _get_capability_graph():
    """延迟导入 capability_graph"""
    from neurova.tool_layers.capability_graph import ToolCapabilityGraph

    return ToolCapabilityGraph()


def _get_cli_executor():
    """延迟导入 cli_tool"""
    from neurova.tool_layers.cli_tool import CLIToolExecutor

    return CLIToolExecutor()


def _get_tool_logger():
    """延迟导入 tool_logger"""
    from neurova.tool_layers.tool_logger import ToolExecutionLogger

    return ToolExecutionLogger()


def _get_execution_result_class():
    """延迟导入 ToolExecutionResult"""
    from neurova.tool_layers.schemas import ToolExecutionResult

    return ToolExecutionResult


class UnifiedToolRegistry:
    """
    统一工具注册表

    在 ToolRouter 和 ToolEngine 之间建立双向同步，提供：
    - 工具注册和同步
    - 工具关系查询（通过 CapabilityGraph）
    - CLI 工具执行
    - 工具执行日志记录
    """

    def __init__(self):
        """初始化统一工具注册表"""
        self._builtin_tools: typing.Dict[str, typing.Any] = {}
        self._execution_engine: typing.Optional[typing.Any] = None
        self._capability_graph = None
        self._cli_executor = None
        self._tool_logger = None
        self._sync_to_engine: bool = True
        self._tool_metadata: typing.Dict[str, typing.Dict] = {}

    def register_builtin(self, name: str, tool: typing.Any) -> None:
        """
        注册内置工具

        Args:
            name: 工具名称
            tool: 工具实例
        """
        self._builtin_tools[name] = tool
        self._tool_metadata[name] = {
            "source": "builtin",
            "registered_at": datetime.datetime.now().isoformat(),
        }

        # 同步到执行引擎
        if self._sync_to_engine and self._execution_engine:
            self._register_to_engine(name, tool)

        logger.debug("Registered builtin tool: %s", name)

    def register_builtin_batch(self, tools: typing.Dict[str, typing.Any]) -> None:
        """
        批量注册内置工具

        Args:
            tools: 工具字典 {name: tool_instance}
        """
        for name, tool in tools.items():
            self.register_builtin(name, tool)

    def set_execution_engine(self, engine: typing.Any) -> None:
        """
        设置执行引擎

        Args:
            engine: 执行引擎实例
        """
        self._execution_engine = engine
        logger.debug("Execution engine set")

    def _register_to_engine(self, name: str, tool: typing.Any) -> None:
        """
        将工具注册到执行引擎

        Args:
            name: 工具名称
            tool: 工具实例
        """
        if self._execution_engine and hasattr(self._execution_engine, "register_tool"):
            try:
                self._execution_engine.register_tool(name, tool)
                logger.debug("Synced tool to engine: %s", name)
            except Exception as e:
                logger.warning("Failed to sync tool to engine: %s, error: %s", name, e)

    def register_to_engine(self, name: str, tool: typing.Any) -> None:
        """
        手动注册工具到执行引擎

        Args:
            name: 工具名称
            tool: 工具实例
        """
        self._register_to_engine(name, tool)

    def get_capability_graph(self) -> typing.Any:
        """
        获取能力图

        Returns:
            ToolCapabilityGraph 实例
        """
        if self._capability_graph is None:
            self._capability_graph = _get_capability_graph()
        return self._capability_graph

    def get_cli_executor(self) -> typing.Any:
        """
        获取 CLI 执行器

        Returns:
            CLIToolExecutor 实例
        """
        if self._cli_executor is None:
            self._cli_executor = _get_cli_executor()
        return self._cli_executor

    def get_tool_logger(self) -> typing.Any:
        """
        获取工具日志记录器

        Returns:
            ToolExecutionLogger 实例
        """
        if self._tool_logger is None:
            self._tool_logger = _get_tool_logger()
        return self._tool_logger

    async def execute_and_log(self, tool_name: str, params: typing.Dict[str, typing.Any]) -> typing.Any:
        """
        执行工具并记录日志

        Args:
            tool_name: 工具名称
            params: 工具参数

        Returns:
            ToolExecutionResult 实例
        """
        start_time = time.time()
        ToolExecutionResult = _get_execution_result_class()

        try:
            # 获取工具
            if tool_name not in self._builtin_tools:
                raise KeyError(f"Tool not found: {tool_name}")

            tool = self._builtin_tools[tool_name]

            # 执行工具
            if hasattr(tool, "execute") and callable(tool.execute):
                import asyncio

                if asyncio.iscoroutinefunction(tool.execute):
                    result = await tool.execute(params)
                else:
                    result = tool.execute(params)
            else:
                raise ValueError(f"Tool {tool_name} does not have an execute method")

            duration_ms = (time.time() - start_time) * 1000

            # 创建成功结果
            execution_result = ToolExecutionResult.success_result(
                tool_name=tool_name,
                output=result if isinstance(result, dict) else {"result": result},
                duration_ms=duration_ms,
            )

        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000

            # 创建错误结果
            execution_result = ToolExecutionResult.error_result(
                tool_name=tool_name,
                error=str(e),
                duration_ms=duration_ms,
            )

        # 记录日志
        logger_instance = self.get_tool_logger()
        if logger_instance:
            try:
                from neurova.tool_layers.tool_logger import ToolExecutionEntry

                entry = ToolExecutionEntry(
                    tool_name=tool_name,
                    params=params,
                    result=execution_result.to_dict(),
                    duration_ms=execution_result.duration_ms,
                    success=execution_result.success,
                    error=execution_result.error,
                )
                logger_instance.log(entry)
            except Exception as e:
                logger.warning("Failed to log tool execution: %s", e)

        return execution_result
