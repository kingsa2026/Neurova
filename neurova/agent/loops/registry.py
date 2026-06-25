"""
Agent Loop 注册机制

通过 @register_loop 装饰器注册 Loop，
Agent 根据模型名称自动选择合适的 Loop。
"""

from neurova.core.logger import get_logger
import re
from typing import Dict, List, Optional, Type

from neurova.agent.loops.base import BaseAgentLoop

logger = get_logger(__name__)

# 全局 Loop 注册表
LOOP_REGISTRY: List[Dict] = []


def register_loop(models: str, priority: int = 0):
    """
    Loop 注册装饰器

    参数:
        models: 正则表达式，匹配支持的模型名称
        priority: 优先级 (数字越大越优先)

    示例:
        @register_loop(r"gpt-.*", priority=10)
        class OpenAILoop(BaseAgentLoop):
            pass

        @register_loop(r"claude-.*", priority=20)
        class AnthropicLoop(BaseAgentLoop):
            pass
    """

    def decorator(cls: Type[BaseAgentLoop]):
        # 检查是否继承自 BaseAgentLoop
        if not issubclass(cls, BaseAgentLoop):
            raise TypeError(f"{cls.__name__} must inherit from BaseAgentLoop")

        LOOP_REGISTRY.append(
            {"pattern": re.compile(models, re.IGNORECASE), "priority": priority, "class": cls, "name": cls.__name__}
        )

        # 按优先级排序 (高优先级在前)
        LOOP_REGISTRY.sort(key=lambda x: x["priority"], reverse=True)

        logger.info("Registered Loop: %s (models=%s, priority=%s)", cls.__name__, models, priority)
        return cls

    return decorator


def find_agent_loop(model: str) -> Optional[Type[BaseAgentLoop]]:
    """
    根据模型名称查找合适的 Loop 类

    参数:
        model: 模型名称 (e.g., "gpt-4", "claude-3-opus", "zai-org/GLM-5.1-FP8")

    返回:
        匹配的 Loop 类，如果未找到则返回 OpenAILoop
    """
    # 首先尝试正则匹配（不区分大小写）
    for entry in LOOP_REGISTRY:
        if entry["pattern"].search(model):
            logger.debug("Found Loop %s for model %s", entry['name'], model)
            return entry["class"]

    # 未找到匹配的 Loop，优先返回 OpenAILoop（通用兼容性最好）
    for entry in LOOP_REGISTRY:
        if "OpenAI" in entry["name"]:
            logger.warning("No Loop found for model %s, using OpenAILoop (通用兼容)", model)
            return entry["class"]

    # 兜底：返回第一个注册的 Loop
    if LOOP_REGISTRY:
        default_loop = LOOP_REGISTRY[0]["class"]
        logger.warning("No Loop found for model %s, using default: %s", model, default_loop.__name__)
        return default_loop

    logger.error("No Loops registered!")
    return None


def list_registered_loops() -> List[Dict]:
    """
    列出所有已注册的 Loops

    返回:
        包含 Loop 信息的字典列表
    """
    return [
        {"name": entry["name"], "pattern": entry["pattern"].pattern, "priority": entry["priority"]}
        for entry in LOOP_REGISTRY
    ]


class LoopRegistry:
    """
    Loop 注册表管理器 (面向对象的接口)
    """

    @staticmethod
    def register(models: str, priority: int = 0):
        """注册 Loop (装饰器)"""
        return register_loop(models, priority)

    @staticmethod
    def find(model: str) -> Optional[Type[BaseAgentLoop]]:
        """查找合适的 Loop"""
        return find_agent_loop(model)

    @staticmethod
    def list_all() -> List[Dict]:
        """列出所有已注册的 Loops"""
        return list_registered_loops()

    @staticmethod
    def clear():
        """清空注册表 (主要用于测试)"""
        LOOP_REGISTRY.clear()
