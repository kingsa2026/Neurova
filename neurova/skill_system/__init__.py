"""
Neurova 技能系统

功能:
1. 技能注册和管理
2. 技能池管理（公共池 + 专属池）
3. 技能推送机制
4. 技能隔离和权限控制
"""

import importlib.util
from neurova.core.logger import get_logger
import sys
from typing import Any, Optional

logger = get_logger(__name__)


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
    if name == "SkillResult":
        # 2026-09-08 断链修复：github_push/skill.py 等调用方经
        # `from neurova.skill_system import SkillResult` 取类，旧路径落到
        # 遮蔽文件里的独立定义（≠ skills.executor 规范类）→ 双类 split-brain。
        # 统一代理到规范 SkillResult。
        from neurova.skills.executor import SkillResult

        return SkillResult
    # SkillEvent 不在此代理：skills.events 门面反向 from neurova.skill_system
    # import SkillEvent——在此引 events 会循环导入（partially initialized）。
    # SkillEvent 走下方 standalone 加载分支，与 events 门面同源同对象。
    elif name == "SkillPoolManager":
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
    elif name == "get_skill_registry":
        # 候选: 从被遮蔽的 skill_system.py 加载单例工厂。
        # 生产代码（neurflow/node_registry.py、adapters.py）依赖
        # `from neurova.skill_system import get_skill_registry`，此前未在代理中
        # 暴露，导致导入失败；与 create_default_skills/SkillRegistry 复用同一
        # standalone 模块缓存。
        import importlib.util as _iu
        import os as _os
        import sys as _sys
        _cache_key = "neurova.skill_system_module_standalone"
        if _cache_key in _sys.modules:
            return _sys.modules[_cache_key].get_skill_registry
        _mod_path = _os.path.join(_os.path.dirname(__file__), _os.pardir, "skill_system.py")
        _spec = _iu.spec_from_file_location(_cache_key, _os.path.abspath(_mod_path))
        _mod = _iu.module_from_spec(_spec)
        _sys.modules[_cache_key] = _mod
        try:
            _spec.loader.exec_module(_mod)
        except Exception:
            _sys.modules.pop(_cache_key, None)
            raise
        return _mod.get_skill_registry
    elif name == "SkillRegistryProtocol":
        # 候选 1: 从被遮蔽的 skill_system.py 加载 Protocol(架构深化)
        import importlib.util as _iu
        import os as _os
        import sys as _sys
        _cache_key = "neurova.skill_system_module_standalone"
        if _cache_key in _sys.modules:
            return _sys.modules[_cache_key].SkillRegistryProtocol
        _mod_path = _os.path.join(_os.path.dirname(__file__), _os.pardir, "skill_system.py")
        _spec = _iu.spec_from_file_location(_cache_key, _os.path.abspath(_mod_path))
        _mod = _iu.module_from_spec(_spec)
        _sys.modules[_cache_key] = _mod
        try:
            _spec.loader.exec_module(_mod)
        except Exception:
            _sys.modules.pop(_cache_key, None)
            raise
        return _mod.SkillRegistryProtocol
    elif name == "SkillRegistry":
        # ADR 0011: 从被遮蔽的 skill_system.py 加载规范 SkillRegistry（class A）。
        # 复用与 SkillRegistryProtocol / create_default_skills 相同的 standalone
        # 模块缓存，避免重复 exec。class A 的 register(skill) 单参、skills 返回
        # Dict[str, Skill]、无 __len__，是唯一规范实现。
        import importlib.util as _iu
        import os as _os
        import sys as _sys
        _cache_key = "neurova.skill_system_module_standalone"
        if _cache_key in _sys.modules:
            return _sys.modules[_cache_key].SkillRegistry
        _mod_path = _os.path.join(_os.path.dirname(__file__), _os.pardir, "skill_system.py")
        _spec = _iu.spec_from_file_location(_cache_key, _os.path.abspath(_mod_path))
        _mod = _iu.module_from_spec(_spec)
        _sys.modules[_cache_key] = _mod
        try:
            _spec.loader.exec_module(_mod)
        except Exception:
            _sys.modules.pop(_cache_key, None)
            raise
        return _mod.SkillRegistry
    elif name == "SkillEvent":
        # 事件类型常量与注册回调所需的 SkillEvent，同样从被遮蔽的
        # skill_system.py 加载，复用同一 standalone 模块缓存。
        import importlib.util as _iu
        import os as _os
        import sys as _sys
        _cache_key = "neurova.skill_system_module_standalone"
        if _cache_key in _sys.modules:
            return _sys.modules[_cache_key].SkillEvent
        _mod_path = _os.path.join(_os.path.dirname(__file__), _os.pardir, "skill_system.py")
        _spec = _iu.spec_from_file_location(_cache_key, _os.path.abspath(_mod_path))
        _mod = _iu.module_from_spec(_spec)
        _sys.modules[_cache_key] = _mod
        try:
            _spec.loader.exec_module(_mod)
        except Exception:
            _sys.modules.pop(_cache_key, None)
            raise
        return _mod.SkillEvent
    elif name == "ToolSequenceSkill":
        # 技能执行体解释器：manifest.tool_sequence → 多步可执行技能
        import importlib.util as _iu
        import os as _os
        import sys as _sys
        _cache_key = "neurova.skill_system_module_standalone"
        if _cache_key in _sys.modules:
            return _sys.modules[_cache_key].ToolSequenceSkill
        _mod_path = _os.path.join(_os.path.dirname(__file__), _os.pardir, "skill_system.py")
        _spec = _iu.spec_from_file_location(_cache_key, _os.path.abspath(_mod_path))
        _mod = _iu.module_from_spec(_spec)
        _sys.modules[_cache_key] = _mod
        try:
            _spec.loader.exec_module(_mod)
        except Exception:
            _sys.modules.pop(_cache_key, None)
            raise
        return _mod.ToolSequenceSkill
    elif name == "Skill":
        # ADR 0011: 从被遮蔽的 skill_system.py 加载规范 Skill 基类，复用同一
        # standalone 模块缓存。此前 __getattr__ 缺少 "Skill" 分支，导致本文件底部
        # `from neurova.skill_system import Skill` 导入失败、回退为无方法的占位类，
        # 使 SkillRegistry.register() 里 skill.add_event_handler() 抛 AttributeError。
        import importlib.util as _iu
        import os as _os
        import sys as _sys
        _cache_key = "neurova.skill_system_module_standalone"
        if _cache_key in _sys.modules:
            return _sys.modules[_cache_key].Skill
        _mod_path = _os.path.join(_os.path.dirname(__file__), _os.pardir, "skill_system.py")
        _spec = _iu.spec_from_file_location(_cache_key, _os.path.abspath(_mod_path))
        _mod = _iu.module_from_spec(_spec)
        _sys.modules[_cache_key] = _mod
        try:
            _spec.loader.exec_module(_mod)
        except Exception:
            _sys.modules.pop(_cache_key, None)
            raise
        return _mod.Skill
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

# 导入 Skill 类（从被遮蔽的 skill_system.py 模块导入，避免占位降级）
try:
    from neurova.skill_system import Skill

    _ = Skill  # 复用 standalone 模块中的规范 Skill 类
except ImportError as e:
    logger.debug("Skill 从 skill_system 导入失败，使用占位: %s", e)

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


# 2026-09-08 断链修复：模块顶层直连定义的 SkillResult 与 __getattr__ 代理分支
# 并存时，顶层定义优先于延迟加载——调用方拿到的是本地类而非
# neurova.skills.executor 规范类（双类 split-brain，守卫测试实测不同一）。
# 删除顶层定义、顶层直接 re-export 规范类，保证两条路径同源。
from neurova.skills.executor import SkillResult as SkillResult  # noqa: E402,F811
from neurova.skill_system_module_standalone import Skill as Skill  # noqa: E402,F811


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
    "SkillRegistry",
    "SkillEvent",
    "_get_skill_module",
    "create_default_skills",
]
