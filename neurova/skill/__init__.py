"""
Skill模块兼容性层

提供 neurova.skill 命名空间，实际实现在 neurova.skills 和 neurova.skill_system 中。
这是为了兼容现有测试代码中的导入语句。

P2（Issue #46）：本包原先还挂着一个 `skill_packer` 子模块（旧的
SkillPacker 打包器）——生产零调用（agent_core 的 `skill_packer` 属性实为
`evolution.AutoSkillBuilder`），且其产物不经过证据闸，与新链路安全基线
冲突。已连同其专用测试（`tests/skill/*`）一并删除；本包只保留
`ExperienceRecord` / `Skill` 两个向后兼容别名。
"""

import importlib
from neurova.core.logger import get_logger
logger = get_logger(__name__)

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
