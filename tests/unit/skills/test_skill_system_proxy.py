"""
A6 测试：验证 neurova.skill_system 包正确代理到 neurova.skills

TDD vertical slices:
1. test_get_skill_registry_proxied — from neurova.skill_system import get_skill_registry 成功
2. test_skill_proxied_to_skills_models — from neurova.skill_system import Skill 返回真实 Skill（非占位）
3. test_skill_event_proxied — from neurova.skill_system import SkillEvent 等于 neurova.skills.events.SkillEvent
4. test_create_default_skills_proxied_to_skills — neurova.skill_system.create_default_skills 返回套2 SkillRegistry
5. test_facadeIsStaticReexport — skill_system/__init__.py 无 __getattr__ 延迟代理
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

    # 2026-09-08 甄别：Skill 经 standalone 加载 —— 占位类只有 name/description，
    # 真类另有 execute/get_info。工单 017 F 项删掉 skill→registry 那条不发声的
    # 事件桥后，`add_event_handler` 不再是可区分的探针，探针换成 `get_info`。
    assert hasattr(Skill, "get_info"), (
        "neurova.skill_system.Skill 应具备 get_info（非占位类）"
    )
    assert not hasattr(Skill, "add_event_handler"), (
        "skill→registry 事件桥已退役，不得再长回来")
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


def test_facadeIsStaticReexport():
    """门面必须是纯 re-export：不定义任何符号，也不留 `__getattr__` 延迟代理。

    2026-09-08 该守卫锁的是相反方向（standalone 反射加载链必须存在），因为顶层
    同名文件被同名包遮蔽；影子文件搬进包内后遮蔽不再存在，反射加载与占位降级
    两类 workaround 同时失去理由。反射加载的防回流由 test_skillSymbolSingleCarrier
    负责，本条按 AST 判"门面不自带定义"，不受注释措辞影响。
    """
    import ast

    init_path = Path(__file__).resolve().parents[3] / "neurova" / "skill_system" / "__init__.py"
    tree = ast.parse(init_path.read_text(encoding="utf-8"))
    defined = sorted(
        node.name
        for node in tree.body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    )
    assert not defined, f"门面文件不得自带任何定义（只允许 re-export）：{defined}"


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
