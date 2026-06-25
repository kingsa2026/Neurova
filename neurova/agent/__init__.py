"""
Agent 包 — 统一入口

提供 Agent 核心类及其深度模块的统一导入路径。

使用方式:
    # 推荐方式（新路径）
    from neurova.agent import Agent, AgentConfig, MemCore

    # 或者导入子模块
    from neurova.agent.context_orchestrator import ContextOrchestrator
    from neurova.agent.tool_executor import ToolExecutor

    # 向后兼容（旧路径仍然可用）
    from neurova.agent_core import Agent, AgentConfig

模块结构:
    neurova.agent
    ├── Agent          # Agent 主类
    ├── AgentConfig    # Agent 配置
    ├── AgentLLMClient # Agent LLM 客户端
    ├── MemCore        # 记忆核心模块
    ├── ToolExecutor   # 工具执行模块
    ├── ChatPipeline   # 对话流程管线 (P5)
    └── loops/         # Agent Loop 系统

    ContextOrchestrator → neurova.context 包（统一路径）
"""

from neurova.agent.chat_pipeline import ChatContext, ChatPipeline
from neurova.agent.initialization_manager import (
    InitializationManager,
    create_initialization_manager,
    get_initialization_manager,
    reset_initialization_manager,
)
from neurova.agent.loop_manager import LoopEvent, LoopManager, LoopState

# 从 loops 子包导入
from neurova.agent.loops.registry import find_agent_loop, register_loop
from neurova.agent.tool_execution_manager import (
    ExecutionEvent,
    ExecutionStatus,
    TimeoutStrategy,
    ToolExecutionContext,
    ToolExecutionManager,
)

# ContextOrchestrator 已统一到 neurova.context 包
# from neurova.agent.context_orchestrator import ContextOrchestrator  # 已删除，使用 neurova.context
# ToolExecutor 已统一到 neurova.tool_executor
from neurova.tool_executor import ToolExecutor

# 从 mem_core 导入记忆核心模块
from neurova.mem_core import MemCore


# 延迟导入 Agent 核心类（避免循环导入）
def __getattr__(name: str):
    if name in ("Agent", "AgentConfig", "AgentLLMClient"):
        from neurova.agent_core import Agent, AgentConfig, AgentLLMClient

        return {"Agent": Agent, "AgentConfig": AgentConfig, "AgentLLMClient": AgentLLMClient}[name]
    raise AttributeError(f"module 'neurova.agent' has no attribute {name!r}")


__all__ = [
    # 核心类（延迟导入）
    "Agent",
    "AgentConfig",
    "AgentLLMClient",
    # 深度模块
    "MemCore",
    # ContextOrchestrator 已统一到 neurova.context 包
    "ToolExecutor",
    "ChatPipeline",
    "ChatContext",
    "LoopManager",
    "LoopState",
    "LoopEvent",
    "ToolExecutionManager",
    "ToolExecutionContext",
    "TimeoutStrategy",
    "ExecutionStatus",
    "ExecutionEvent",
    # 初始化管理
    "InitializationManager",
    "create_initialization_manager",
    "get_initialization_manager",
    "reset_initialization_manager",
    # Loop 系统
    "register_loop",
    "find_agent_loop",
]

# 版本信息
__version__ = "2.1.0"  # MemCore 统一版本
