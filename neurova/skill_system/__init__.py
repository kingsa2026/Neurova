"""
Neurova 技能系统

功能:
1. 技能注册和管理
2. 技能池管理（公共池 + 专属池）
3. 技能推送机制
4. 技能隔离和权限控制
"""

import importlib.util
import logging
import sys
from typing import Any, Optional

logger = logging.getLogger(__name__)


def _get_skill_module(module_name: str) -> Optional[Any]:
    """
    动态加载 neurova.skill_system 模块

    Args:
        module_name: 模块名称

    Returns:
        模块对象或 None
    """
    try:
        # 尝试直接导入
        if module_name in sys.modules:
            return sys.modules[module_name]

        # 动态导入
        module = importlib.import_module(module_name)
        return module

    except ImportError as e:
        logger.warning("Failed to import module %s: %s", module_name, e)
        return None
    except Exception as e:
        logger.error("Error loading module %s: %s", module_name, e)
        return None


def __getattr__(name: str) -> Any:
    """
    模块级别的 __getattr__，用于延迟加载

    Args:
        name: 属性名称

    Returns:
        属性值

    Raises:
        AttributeError: 属性不存在
    """
    # 导入核心类
    if name == "SkillPoolManager":
        from neurova.skill_system.skill_pool_manager import SkillPoolManager

        return SkillPoolManager
    elif name == "SkillPoolType":
        from neurova.skill_system.skill_pool_manager import SkillPoolType

        return SkillPoolType
    elif name == "SkillVisibility":
        from neurova.skill_system.skill_pool_manager import SkillVisibility

        return SkillVisibility
    elif name == "SkillMetadata":
        from neurova.skill_system.skill_pool_manager import SkillMetadata

        return SkillMetadata
    elif name == "SkillStatus":
        # SkillStatus 枚举
        from enum import Enum

        class SkillStatus(str, Enum):
            """技能状态枚举"""

            ACTIVE = "active"
            INACTIVE = "inactive"
            DEPRECATED = "deprecated"
            BETA = "beta"
            EXPERIMENTAL = "experimental"

        return SkillStatus
    elif name == "create_default_skills":
        # 使用 importlib 从被遮蔽的模块加载，避免递归
        import importlib.util as _iu
        import os as _os
        import sys as _sys
        _cache_key = "neurova.skill_system_module_standalone"
        if _cache_key in _sys.modules:
            return _sys.modules[_cache_key].create_default_skills
        _mod_path = _os.path.join(_os.path.dirname(__file__), _os.pardir, "skill_system.py")
        _spec = _iu.spec_from_file_location(_cache_key, _os.path.abspath(_mod_path))
        _mod = _iu.module_from_spec(_spec)
        _sys.modules[_cache_key] = _mod
        try:
            _spec.loader.exec_module(_mod)
        except Exception:
            _sys.modules.pop(_cache_key, None)
            raise
        return _mod.create_default_skills
    else:
        raise AttributeError(f"module 'neurova.skill_system' has no attribute '{name}'")


# 导入 create_default_skills（向后兼容）
try:
    from neurova.skill_system import create_default_skills
except ImportError as e:
    logger.warning("Failed to import create_default_skills: %s", e)

# 导入核心类（向后兼容）
try:
    from neurova.skill_system.skill_pool_manager import (
        SkillMetadata,
        SkillPoolManager,
        SkillPoolType,
        SkillVisibility,
    )
except ImportError as e:
    logger.warning("Failed to import skill_pool_manager: %s", e)

# 导入 Skill 类（从模块导入）
try:
    from neurova.skill_system.skill_pool_manager import Skill as _PoolSkill

    Skill = _PoolSkill
except ImportError as e:
    logger.debug("Skill 从 skill_pool_manager 导入失败，使用占位: %s", e)

    class Skill:  # type: ignore[no-redef]
        def __init__(self, name, description=""):
            self.name = name
            self.description = description


class SkillResult:
    def __init__(self, success=True, data=None, error=None, execution_time=0.0):
        self.success = success
        self.data = data
        self.error = error
        self.execution_time = execution_time


class SkillInfo:
    def __init__(self, name, description="", status=None):
        self.name = name
        self.description = description
        self.status = status


__all__ = [
    "SkillPoolManager",
    "SkillPoolType",
    "SkillVisibility",
    "SkillMetadata",
    "SkillStatus",
    "Skill",
    "SkillResult",
    "SkillInfo",
    "_get_skill_module",
    "create_default_skills",
]
