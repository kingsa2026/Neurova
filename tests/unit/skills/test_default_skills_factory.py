"""
create_default_skills() 工厂和 get_skill_registry() 单例工厂测试

验证：
- create_default_skills() 返回含 4 个内置 skill 的 SkillRegistry
- get_skill_registry() 返回单例
"""
import asyncio
from pathlib import Path

import pytest

from neurova.skills.registry import SkillRegistry


@pytest.fixture(autouse=True)
def _clear_registry():
    """每个测试前清空单例 registry"""
    SkillRegistry().clear()
    yield
    SkillRegistry().clear()


# ================================================================
# create_default_skills
# ================================================================

class TestCreateDefaultSkills:
    def test_returns_registry_with_4_skills(self):
        from neurova.skills import create_default_skills

        registry = create_default_skills()
        assert isinstance(registry, SkillRegistry)
        assert len(registry.get_skill_names()) == 4

    def test_contains_memory_skill(self):
        from neurova.skills import create_default_skills

        registry = create_default_skills()
        assert registry.has_skill("memory")

    def test_contains_web_search_skill(self):
        from neurova.skills import create_default_skills

        registry = create_default_skills()
        assert registry.has_skill("web_search")

    def test_contains_file_operation_skill(self):
        from neurova.skills import create_default_skills

        registry = create_default_skills()
        assert registry.has_skill("file_operation")

    def test_skills_have_executors(self):
        """每个 skill 都注册了 executor，可以执行"""
        from neurova.skills import create_default_skills

        registry = create_default_skills()
        # 执行 memory skill 验证 executor 已注册（execute_skill 为异步方法）
        result = asyncio.run(
            registry.execute_skill("memory", params={"action": "search", "query": "test"})
        )
        assert result.success is True

    def test_with_memory_manager(self):
        """create_default_skills 接受 memory_manager 参数"""
        from neurova.skills import create_default_skills

        registry = create_default_skills(memory_manager=None)
        assert registry.has_skill("memory")


# ================================================================
# get_skill_registry
# ================================================================

class TestGetSkillRegistry:
    def test_returns_skill_registry_instance(self):
        from neurova.skills import get_skill_registry

        reg = get_skill_registry()
        assert isinstance(reg, SkillRegistry)

    def test_returns_singleton(self):
        from neurova.skills import get_skill_registry

        reg1 = get_skill_registry()
        reg2 = get_skill_registry()
        assert reg1 is reg2
