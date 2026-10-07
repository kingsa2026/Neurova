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
    def test_returns_registry_with_5_skills(self):
        """工厂产出 5 技能（4 executor 桥接 + github_push 注册断链修复后接入）"""
        from neurova.skills import create_default_skills

        registry = create_default_skills()
        assert isinstance(registry, SkillRegistry)
        assert len(registry.get_skill_names()) == 5
        assert "github_push" in registry.get_skill_names()

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
        """executor 确实接线并可执行——但"能执行"不等于"没装配也算成功"。

        改判说明（审计 §6-17 的现场）：原断言是 `create_default_skills()`（不带
        memory_manager）执行 search 后 `success is True`。那条契约钉的是**假成功**——
        记忆管理器缺席时 executor 什么都没查，回执却与"真查了、没命中"完全不可区分。
        因此这里拆成两条各自能证伪的判据：缺席必须点名失败；装上管理器才要求真调用。
        """
        from neurova.skills import create_default_skills

        registry = create_default_skills()
        result = asyncio.run(
            registry.execute_skill("memory", params={"action": "search", "query": "test"})
        )
        assert result.success is False, (
            "未装配记忆管理器时 executor 不得回执成功：%r" % (result.output,))
        assert result.error and "记忆管理器" in result.error, result.error

    def test_skills_execute_reach_the_manager(self):
        """正向半：真挂上管理器时，桥接后的 executor 必须调到它（不是自证 success 字段）。"""
        calls = []

        class _RecordingManager:
            def recall(self, *args, **kwargs):
                calls.append((args, kwargs))
                return []

            def remember(self, **kwargs):
                calls.append(("remember", kwargs))
                return {"id": "m-1"}

        from neurova.skills import create_default_skills

        registry = create_default_skills(memory_manager=_RecordingManager())
        result = asyncio.run(
            registry.execute_skill("memory", params={"action": "search", "query": "要点"})
        )
        assert result.success is True, "%s / %s" % (result.success, result.error)
        assert calls, "回执成功但管理器一次都没被调用——那还是假成功"
        # store 走的是待审队列（默认挂载），不会直连管理器——那是设计而非假成功，
        # 故正向半用 search 证桥接；直写路径由 test_builtin_executors 覆盖。

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
