"""
A5 + E2 测试：验证 agent_core.py 从 neurova.skills 导入 create_default_skills 和 SkillEvent

TDD vertical slices:
1. RED: test_create_default_skills_importable_from_skills — 验证 neurova.skills 提供create_default_skills
2. RED: test_skill_event_importable_from_skills_events — 验证 neurova.skills.events 提供 SkillEvent
3. RED: test_agent_core_module_imports_without_error — 验证 agent_core 模块可导入（不抛 NameError）
"""

import importlib
import sys
from pathlib import Path


def test_create_default_skills_importable_from_skills():
    """验证 create_default_skills 可从 neurova.skills 导入（套2 工厂）"""
    from neurova.skills import create_default_skills
    assert callable(create_default_skills), "create_default_skills 应该是可调用的"


def test_skill_event_importable_from_skills_events():
    """验证 SkillEvent 可从 neurova.skills.events 导入（含 POST_EXECUTE 常量）"""
    from neurova.skills.events import SkillEvent
    assert hasattr(SkillEvent, "POST_EXECUTE"), "SkillEvent 应有 POST_EXECUTE 常量"
    assert isinstance(SkillEvent.POST_EXECUTE, str), "POST_EXECUTE 应该是字符串常量"


def test_agent_core_module_imports_without_error():
    """验证 agent_core 模块可导入（不抛 NameError/ImportError）

    Bug #2: agent_core.py:1252 使用 SkillEvent 但未导入 → NameError
    Bug #3: agent_core.py:1251 调用 register_event_callback（套2 有此方法）
    """
    # 强制重新导入以检测导入时错误
    if "neurova.agent_core" in sys.modules:
        del sys.modules["neurova.agent_core"]
    try:
        importlib.import_module("neurova.agent_core")
    except NameError as e:
        assert False, f"agent_core 导入失败（NameError）: {e}"
    except ImportError as e:
        assert False, f"agent_core 导入失败（ImportError）: {e}"


def test_agent_core_source_uses_skills_module_not_skill_system():
    """验证 agent_core.py 源码从 neurova.skills 导入 create_default_skills（而非 neurova.skill_system）

    A5: L632/L974 应改为 from neurova.skills import create_default_skills
    """
    agent_core_path = Path(__file__).parent.parent.parent.parent / "neurova" / "agent_core.py"
    if not agent_core_path.exists():
        assert False, f"agent_core.py 不存在于 {agent_core_path}"

    content = agent_core_path.read_text(encoding="utf-8")

    # 不应从 neurova.skill_system 导入 create_default_skills
    bad_import = "from neurova.skill_system import create_default_skills"
    assert bad_import not in content, (
        f"agent_core.py 仍包含 '{bad_import}'，应改为 'from neurova.skills import create_default_skills'"
    )

    # 应从 neurova.skills 导入 create_default_skills
    good_import = "from neurova.skills import create_default_skills"
    assert good_import in content, (
        f"agent_core.py 应包含 '{good_import}'"
    )


def test_agent_core_imports_skill_event():
    """验证 agent_core.py 导入 SkillEvent（修复 Bug #2）"""
    agent_core_path = Path(__file__).parent.parent.parent.parent / "neurova" / "agent_core.py"
    content = agent_core_path.read_text(encoding="utf-8")

    # 应导入 SkillEvent
    assert "from neurova.skills.events import SkillEvent" in content, (
        "agent_core.py 应包含 'from neurova.skills.events import SkillEvent' 导入"
    )
