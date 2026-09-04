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


def _mount_pending_store():
    """进程级待确认记忆队列（P1-2）。独立函数便于测试注入失败。"""
    from neurova.memory.pending_memory import get_pending_memory_store

    return get_pending_memory_store()


def create_builtin_executor_skills(memory_manager=None) -> list:
    """构造内置 executor 对应的、可被 SkillRegistry 调用的 Skill 列表。

    名称与 create_default_skills 中原有 Skill 名称一致：
    memory / web_search / file_operation / kb_builder，
    保证调用方按名称查找时兼容。

    P1-2：memory executor 挂载待确认队列（用户 2026-09-04 决策启用）——
    聊天 memory_save 的单条写入默认先进待审、确认后入主库；挂载失败只
    降级为原直写语义（错误方向是"少一个待审项"，不是"聊天坏掉"）。
    """
    pending_store = None
    try:
        pending_store = _mount_pending_store()
    except Exception as exc:  # noqa: BLE001
        import logging

        logging.getLogger(__name__).warning("待确认记忆队列挂载失败，memory_save 保持直写: %s", exc)

    return [
        ExecutorBackedSkill(MemorySkillExecutor(memory_manager, pending_store=pending_store)),
        ExecutorBackedSkill(WebSearchSkillExecutor()),
        ExecutorBackedSkill(FileOperationSkillExecutor()),
        ExecutorBackedSkill(KbBuilderSkillExecutor()),
    ]
