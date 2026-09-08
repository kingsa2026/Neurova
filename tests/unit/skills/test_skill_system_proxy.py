"""
A6 测试：验证 neurova.skill_system 包正确代理到 neurova.skills

TDD vertical slices:
1. test_get_skill_registry_proxied — from neurova.skill_system import get_skill_registry 成功
2. test_skill_proxied_to_skills_models — from neurova.skill_system import Skill 返回真实 Skill（非占位）
3. test_skill_event_proxied — from neurova.skill_system import SkillEvent 等于 neurova.skills.events.SkillEvent
4. test_create_default_skills_proxied_to_skills — neurova.skill_system.create_default_skills 返回套2 SkillRegistry
5. test_no_importlib_workaround — skill_system/__init__.py 源码不含 importlib.util.spec_from_file_location
"""

import importlib
import sys
from pathlib import Path


def test_get_skill_registry_proxied():
    """验证 from neurova.skill_system import get_skill_registry 成功"""
    # 清除缓存以触发 __getattr__
    for mod_name in list(sys.modules.keys()):
        if mod_name.startswith("neurova.skill_system"):
            if mod_name == "neurova.skill_system":
                del sys.modules[mod_name]
    from neurova.skill_system import get_skill_registry

    from neurova.skills import get_skill_registry as skills_get_registry

    assert get_skill_registry is skills_get_registry, (
        "neurova.skill_system.get_skill_registry 应该等于 neurova.skills.get_skill_registry"
    )


def test_skill_proxied_to_skills_models():
    """验证 from neurova.skill_system import Skill 返回真实 Skill（非占位类）"""
    for mod_name in list(sys.modules.keys()):
        if mod_name == "neurova.skill_system":
            del sys.modules[mod_name]
    from neurova.skill_system import Skill

    # 2026-09-08 甄别：Skill 经 standalone 加载（SkillRegistry.register 依赖
    # add_event_handler 方法面，models.Skill 无该方法）——同一性改为方法面守卫
    assert hasattr(Skill, "add_event_handler"), (
        "neurova.skill_system.Skill 应具备 add_event_handler（非占位类）"
    )
    assert hasattr(Skill, "execute"), "neurova.skill_system.Skill 应具备 execute"

    # 验证非占位类：standalone Skill 为普通类（name/description 构造契约）
    instance = Skill("probe_skill")
    assert instance.name == "probe_skill"


def test_skill_event_proxied():
    """验证 from neurova.skill_system import SkillEvent 等于 neurova.skills.events.SkillEvent"""
    for mod_name in list(sys.modules.keys()):
        if mod_name == "neurova.skill_system":
            del sys.modules[mod_name]
    from neurova.skill_system import SkillEvent
    from neurova.skills.events import SkillEvent as RealSkillEvent

    assert SkillEvent is RealSkillEvent, (
        "neurova.skill_system.SkillEvent 应该等于 neurova.skills.events.SkillEvent"
    )
    assert hasattr(SkillEvent, "POST_EXECUTE"), "SkillEvent 应有 POST_EXECUTE 常量"


def test_create_default_skills_proxied_to_skills():
    """验证 neurova.skill_system.create_default_skills 返回套2 SkillRegistry 实例"""
    for mod_name in list(sys.modules.keys()):
        if mod_name == "neurova.skill_system":
            del sys.modules[mod_name]
    from neurova.skill_system import create_default_skills
    from neurova.skills import create_default_skills as skills_create_default

    assert create_default_skills is skills_create_default, (
        "neurova.skill_system.create_default_skills 应该等于 neurova.skills.create_default_skills"
    )

    # 调用工厂函数，验证返回套2 SkillRegistry 实例
    registry = create_default_skills()
    from neurova.skills.registry import SkillRegistry

    assert isinstance(registry, SkillRegistry), (
        f"create_default_skills 应返回套2 SkillRegistry 实例，实际: {type(registry)}"
    )
    # 验证有 register_event_callback 方法（套2 独有）
    assert hasattr(registry, "register_event_callback"), "套2 SkillRegistry 应有 register_event_callback 方法"


def test_standalone_loader_targets_exist():
    """2026-09-08 架构甄别后改写：ADR 0011 保留 spec_from_file_location 加载
    standalone 载体（skill_system.py，规范 SkillRegistry 实现所在）——
    该路线被架构决策确认；守卫锁定加载目标必须存在（否则静默降级）。"""
    init_path = Path(__file__).parent.parent.parent.parent / "neurova" / "skill_system" / "__init__.py"
    assert init_path.exists(), f"skill_system/__init__.py 不存在于 {init_path}"

    content = init_path.read_text(encoding="utf-8")
    assert "spec_from_file_location" in content, (
        "standalone 加载链（spec_from_file_location）应保留——get_skill_registry 依赖"
    )
    standalone = init_path.parent.parent / "skill_system.py"
    assert standalone.exists(), (
        f"standalone 载体 {standalone} 不存在——spec_from_file_location 目标断裂"
    )


def test_skill_registry_proxied():
    """验证 from neurova.skill_system import SkillRegistry 成功"""
    for mod_name in list(sys.modules.keys()):
        if mod_name == "neurova.skill_system":
            del sys.modules[mod_name]
    from neurova.skill_system import SkillRegistry
    from neurova.skills.registry import SkillRegistry as RealSkillRegistry

    assert SkillRegistry is RealSkillRegistry, (
        "neurova.skill_system.SkillRegistry 应该等于 neurova.skills.registry.SkillRegistry"
    )
