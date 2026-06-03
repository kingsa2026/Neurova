"""
Agent Loops - 多模型适配循环

每个 Loop 实现特定的模型交互逻辑。
通过 register_loop 装饰器注册，Agent 自动选择合适的 Loop。
"""
from neurova.agent.loops.base import BaseAgentLoop
from neurova.agent.loops.registry import register_loop, find_agent_loop, LoopRegistry

# 导入所有 Loop 实现，确保装饰器被执行
from neurova.agent.loops import openai_loop  # noqa: F401
from neurova.agent.loops import anthropic_loop  # noqa: F401

__all__ = [
    "BaseAgentLoop",
    "register_loop",
    "find_agent_loop",
    "LoopRegistry",
]
