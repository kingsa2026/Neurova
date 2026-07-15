"""
Skill Registry - 中央注册表

提供Skill的集中注册与管理功能。
实现Singleton模式，确保全局唯一的注册表实例。

主要功能:
- Skill的注册与取消注册
- 启动/关闭Hook管理
- 控制命令注册
- 线程安全的操作

ADR 0011: SkillRegistry 统一为 skill_system.py 的 class A（规范实现）。
本模块仅 re-export 规范 SkillRegistry，不再定义 class B（tuple 返回、
__len__ falsy、register(manifest, path) 双参等不兼容 API 已废弃）。
保留 HookRegistration / ControlCommandRegistration 等独有数据类。
"""

import asyncio
import inspect
from neurova.core.logger import get_logger
import threading
import time
import typing
from dataclasses import dataclass
from pathlib import Path

# skills imports
from neurova.skills.executor import SkillExecutor, SkillResult
from neurova.skills.models import Skill

# ADR 0011: re-export 规范 SkillRegistry（class A），消除双实现 split-brain。
# class B 原 register(manifest, path) 双参 / skills 返回 Tuple / __len__ falsy 等
# 不兼容 API 一并废弃；运行时实例本就来自 skill_system.create_default_skills()。
from neurova.skill_system import SkillRegistry


@dataclass
class HookRegistration:
    """Hook注册记录"""

    skill_id: str
    hook_name: str
    callback: typing.Callable
    priority: int = 100


@dataclass
class ControlCommandRegistration:
    """控制命令注册记录"""

    skill_id: str
    handler: typing.Callable
    priority_level: int = 10
