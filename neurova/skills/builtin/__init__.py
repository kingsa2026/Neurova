"""
内置 Skill Executor 模块

导出四个内置执行器，并提供 create_builtin_executor_skills() 工厂，
将同步 Executor 桥接为可被 SkillRegistry 调用的异步 Skill。
"""

from neurova.skills.executor import (
    BaseSkillExecutor,
    ExecutorBackedSkill,
    SkillResult,
)
from neurova.skills.builtin.memory_executor import MemorySkillExecutor
from neurova.skills.builtin.web_search_executor import WebSearchSkillExecutor
from neurova.skills.builtin.file_operation_executor import FileOperationSkillExecutor
from neurova.skills.builtin.kb_builder_executor import KbBuilderSkillExecutor

__all__ = [
    "BaseSkillExecutor",
    "ExecutorBackedSkill",
    "SkillResult",
    "MemorySkillExecutor",
    "WebSearchSkillExecutor",
    "FileOperationSkillExecutor",
    "KbBuilderSkillExecutor",
    "create_builtin_executor_skills",
]


def create_builtin_executor_skills(memory_manager=None) -> list:
    """构造内置 executor 对应的、可被 SkillRegistry 调用的 Skill 列表。

    名称与 create_default_skills 中原有 Skill 名称一致：
    memory / web_search / file_operation / kb_builder，
    保证调用方按名称查找时兼容。
    """
    return [
        ExecutorBackedSkill(MemorySkillExecutor(memory_manager)),
        ExecutorBackedSkill(WebSearchSkillExecutor()),
        ExecutorBackedSkill(FileOperationSkillExecutor()),
        ExecutorBackedSkill(KbBuilderSkillExecutor()),
    ]
