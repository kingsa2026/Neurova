"""
Neurova 技能系统

功能:
1. 技能注册和管理
2. 技能池管理（公共池 + 专属池）
3. 技能推送机制
4. 技能隔离和权限控制
"""

import os
import logging
import importlib.util
import sys
from pathlib import Path
from typing import Optional, Any, Dict

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
        logger.warning(f"Failed to import module {module_name}: {e}")
        return None
    except Exception as e:
        logger.error(f"Error loading module {module_name}: {e}")
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
    else:
        raise AttributeError(f"module 'neurova.skill_system' has no attribute '{name}'")


# 导入核心类（向后兼容）
try:
    from neurova.skill_system.skill_pool_manager import (
        SkillPoolManager,
        SkillPoolType,
        SkillVisibility,
        SkillMetadata,
    )
except ImportError as e:
    logger.warning(f"Failed to import skill_pool_manager: {e}")


__all__ = [
    'SkillPoolManager',
    'SkillPoolType',
    'SkillVisibility',
    'SkillMetadata',
    'SkillStatus',
    '_get_skill_module',
]
