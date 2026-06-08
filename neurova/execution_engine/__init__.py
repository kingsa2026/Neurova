"""
Neurova CogArch 1.0.0 - 执行引擎（手脚）

核心模块：
- plan_orchestrator: 计划编排器（小脑）
- tool_engine: 工具引擎 - 智能工具选择与执行
- workflow_engine: 工作流引擎
- agent_colab: 多Agent协作引擎
- execution_monitor: 执行监控器
- mcp_manager: MCP 协议管理器
"""

try:
    from .tool_engine import (
        ToolEngine,
        ToolStatus,
        ToolParameter,
        ToolDefinition,
        ToolInvocation,
        ToolSelection,
        ToolCallingContext,
        ToolVersion,
        ToolDiscoveryResult,
    )
except ImportError:
    # 如果 tool_engine 模块不可用，提供占位类
    class ToolEngine:
        """工具引擎占位类"""
        pass
    
    class ToolStatus:
        """工具状态占位类"""
        AVAILABLE = "available"
        UNAVAILABLE = "unavailable"
        DEPRECATED = "deprecated"
        DISABLED = "disabled"
    
    class ToolParameter:
        """工具参数占位类"""
        pass
    
    class ToolDefinition:
        """工具定义占位类"""
        pass
    
    class ToolInvocation:
        """工具调用占位类"""
        pass
    
    class ToolSelection:
        """工具选择占位类"""
        pass
    
    class ToolCallingContext:
        """工具调用上下文占位类"""
        pass
    
    class ToolVersion:
        """工具版本占位类"""
        pass
    
    class ToolDiscoveryResult:
        """工具发现结果占位类"""
        pass