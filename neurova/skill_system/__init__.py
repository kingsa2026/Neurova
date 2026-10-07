"""
Neurova 技能系统 —— 单一事实源门面

实现载体在 `neurova/skill_system/core.py`（ADR 0011 的规范 SkillRegistry，
原为顶层 `neurova/skill_system.py`，2026-10-07 搬入包内以消解"同名包遮蔽同名
文件"这一根病灶：只要两者并存，`import neurova.skill_system` 永不到达该文件，
所有取用都只能靠 importlib 按路径反射回来，同一批符号就会长出多条取用路径）。

本文件只做静态 re-export，不再有任何 `__getattr__` 延迟代理、反射加载或占位降级类。

（原"技能池管理/推送/隔离"由 skill_pool_manager 孤岛承担，2026-09-15 退役——
零生产调用方；三层库设计吸收其词汇。）
"""

from neurova.skill_system.core import (
    Skill,
    SkillEvent,
    SkillRegistry,
    SkillRegistryProtocol,
    SkillResult,
    SkillStatus,
    ToolSequenceSkill,
    create_default_skills,
    get_skill_registry,
    registered_collision_count,
)

__all__ = [
    "Skill",
    "SkillEvent",
    "SkillRegistry",
    "SkillRegistryProtocol",
    "SkillResult",
    "SkillStatus",
    "ToolSequenceSkill",
    "create_default_skills",
    "get_skill_registry",
    "registered_collision_count",
]
