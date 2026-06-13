"""
Skill模块兼容性层

提供 neurova.skill 命名空间，实际实现在 neurova.skills 和 neurova.skill_system 中。
这是为了兼容现有测试代码中的导入语句。
"""

import importlib
import logging

logger = logging.getLogger(__name__)

# ---- 安全的懒导入（避免硬依赖导致整个命名空间崩溃） ----


def __getattr__(name: str):
    """模块级 __getattr__：按需延迟导入，避免循环依赖和启动崩溃"""
    _LAZY_MAP = {
        # skills.models
        "ExperienceRecord": "neurova.skills.models.ExperienceRecord",
        "Skill": "neurova.skills.models.Skill",
    }
    if name in _LAZY_MAP:
        try:
            module_path, attr = _LAZY_MAP[name].rsplit(".", 1)
            mod = importlib.import_module(module_path)
            return getattr(mod, attr)
        except (ImportError, AttributeError) as e:
            logger.debug("Lazy import %s failed: %s", name, e)
            raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from e
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# 向后兼容别名（仅在已被导入时使用）
try:
    from neurova.skills.models import ExperienceRecord, Skill
except ImportError:
    pass

__all__ = ["ExperienceRecord", "Skill"]
