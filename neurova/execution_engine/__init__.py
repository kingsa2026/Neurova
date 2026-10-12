"""
Neurova CogArch 1.0.0 - 执行引擎（手脚）

核心模块：
- tool_engine: 工具引擎 - 智能工具选择与执行
- workflow_engine: 工作流引擎
- agent_colab: 多Agent协作引擎
- execution_monitor: 执行监控器
- mcp_manager: MCP 协议管理器

（原列在此处的 `plan_orchestrator`（计划编排器/小脑）从未被本门面导入或再导出，且生产侧
零消费者——它自称的步骤状态机与真重试从未可达（执行表零注册方），那两格能力现已落在
服务路上的 `collaboration/neurflow/execution_engine.py`（层内并发上限 + 幂等声明门的
节点级重试）。台账 §6-157 比对、§6-166 退役。）
"""

try:
    from .tool_engine import (
        ToolCallingContext,
        ToolDefinition,
        ToolDiscoveryResult,
        ToolEngine,
        ToolInvocation,
        ToolParameter,
        ToolSelection,
        ToolStatus,
        ToolVersion,
    )
except ImportError:
    # 如果 tool_engine 模块不可用，提供占位类
    class ToolEngine:
        """工具引擎占位类"""


    class ToolStatus:
        """工具状态占位类"""

        AVAILABLE = "available"
        UNAVAILABLE = "unavailable"
        DEPRECATED = "deprecated"
        DISABLED = "disabled"

    class ToolParameter:
        """工具参数占位类"""


    class ToolDefinition:
        """工具定义占位类"""


    class ToolInvocation:
        """工具调用占位类"""


    class ToolSelection:
        """工具选择占位类"""


    class ToolCallingContext:
        """工具调用上下文占位类"""


    class ToolVersion:
        """工具版本占位类"""


    class ToolDiscoveryResult:
        """工具发现结果占位类"""

