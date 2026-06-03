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
    ├── ContextOrchestrator # 上下文构建模块
    ├── ToolExecutor   # 工具执行模块
    └── loops/         # Agent Loop 系统
"""

# 从 agent_core 导入核心类（保持单一实现源）
from neurova.agent_core import Agent, AgentConfig, AgentLLMClient

# 从 mem_core 导入记忆核心模块
from neurova.mem_core import MemCore

# 从子模块导入深度模块
from neurova.agent.context_orchestrator import ContextOrchestrator
from neurova.agent.tool_executor import ToolExecutor

# 从 loops 子包导入
from neurova.agent.loops.registry import register_loop, find_agent_loop

__all__ = [
    # 核心类
    "Agent",
    "AgentConfig",
    "AgentLLMClient",

    # 深度模块
    "MemCore",
    "ContextOrchestrator",
    "ToolExecutor",

    # Loop 系统
    "register_loop",
    "find_agent_loop",
]

# 版本信息
__version__ = "2.1.0"  # MemCore 统一版本
