"""SkillRegistry 单元测试（对齐 ADR 0011 规范实现）。

前置：neurova/skill_system/__init__.py 的 __getattr__ 已补上 "Skill" 分支，
使 `from neurova.skill_system import Skill` 不再回退为无方法的占位类。

真实 API（neurova/skill_system.py 的 class A，经包 __getattr__ 以 standalone 模块加载）：
    SkillRegistry(runtime_manager=None)
    register(skill)                     # 按 skill.name 存储，skill.add_event_handler
    skills -> Dict[str, Skill]
    register_skill(manifest, path=None) -> bool
    unregister / get_skill / has_skill / list_skills / get_skill_names / clear
    execute_skill(name, params, context) -> SkillResult   # async，触发事件
    add_event_handler / register_event_callback(event_type, handler)

SkillResult 字段：success / data / error / metadata / execution_time。
"""

import pytest

from neurova.skill_system import Skill, SkillEvent, SkillRegistry, SkillResult


class _EchoSkill(Skill):
    async def execute(self, params, context=None):
        return SkillResult(success=True, data={"echo": params})


class _BoomSkill(Skill):
    async def execute(self, params, context=None):
        raise RuntimeError("boom")


@pytest.fixture
def registry():
    return SkillRegistry()


class TestRegistration:
    def test_new_registry_is_empty(self, registry):
        assert registry.skills == {}
        assert registry.get_skill_names() == []

    def test_register_stores_by_name(self, registry):
        registry.register(_EchoSkill("demo", "demo skill"))
        assert "demo" in registry.skills
        assert isinstance(registry.skills["demo"], Skill)

    def test_get_skill_and_has_skill(self, registry):
        registry.register(_EchoSkill("demo"))
        assert registry.has_skill("demo") is True
        assert registry.get_skill("demo").name == "demo"
        assert registry.has_skill("missing") is False
        assert registry.get_skill("missing") is None

    def test_unregister_removes_skill(self, registry):
        registry.register(_EchoSkill("demo"))
        registry.unregister("demo")
        assert registry.has_skill("demo") is False

    def test_unregister_missing_is_noop(self, registry):
        registry.unregister("nope")
        assert registry.skills == {}

    def test_clear_empties_registry(self, registry):
        registry.register(_EchoSkill("a"))
        registry.register(_EchoSkill("b"))
        registry.clear()
        assert registry.skills == {}


class TestListing:
    def test_get_skill_names(self, registry):
        registry.register(_EchoSkill("a"))
        registry.register(_EchoSkill("b"))
        assert sorted(registry.get_skill_names()) == ["a", "b"]

    def test_list_skills_returns_skill_info(self, registry):
        registry.register(_EchoSkill("a", "desc-a"))
        infos = registry.list_skills()
        assert len(infos) == 1
        assert infos[0].name == "a"
        assert infos[0].description == "desc-a"


class TestRegisterSkillCompat:
    def test_accepts_skill_instance(self, registry):
        skill = _EchoSkill("direct")
        assert registry.register_skill(skill) is True
        assert registry.has_skill("direct")

    def test_accepts_manifest_with_name(self, registry):
        class Manifest:
            name = "from-manifest"
            description = "built from manifest"
            config = {}

        assert registry.register_skill(Manifest()) is True
        assert registry.has_skill("from-manifest")

    def test_manifest_with_tool_sequence_builds_executable_skill(self, registry):
        from neurova.skill_system import ToolSequenceSkill

        class Manifest:
            name = "seq-skill"
            description = ""
            config = {"tool_sequence": [{"tool": "echo", "params": {}}]}

        assert registry.register_skill(Manifest()) is True
        assert isinstance(registry.get_skill("seq-skill"), ToolSequenceSkill)


class TestExecuteSkill:
    @pytest.mark.asyncio
    async def test_execute_existing_skill(self, registry):
        registry.register(_EchoSkill("demo"))
        result = await registry.execute_skill("demo", {"x": 1})
        assert result.success is True
        assert result.data == {"echo": {"x": 1}}

    @pytest.mark.asyncio
    async def test_execute_missing_skill_fails(self, registry):
        result = await registry.execute_skill("missing", {})
        assert result.success is False
        assert "不存在" in result.error

    @pytest.mark.asyncio
    async def test_execute_swallows_exception_into_result(self, registry):
        registry.register(_BoomSkill("boom"))
        result = await registry.execute_skill("boom", {})
        assert result.success is False
        assert "boom" in result.error


class TestEvents:
    @pytest.mark.asyncio
    async def test_execute_emits_before_and_after_events(self, registry):
        seen = []
        registry.add_event_handler(lambda event: seen.append(event.event_type))
        registry.register(_EchoSkill("demo"))
        await registry.execute_skill("demo", {})
        assert SkillEvent.PRE_EXECUTE in seen
        assert SkillEvent.POST_EXECUTE in seen

    @pytest.mark.asyncio
    async def test_execute_emits_error_event_on_failure(self, registry):
        seen = []
        registry.add_event_handler(lambda event: seen.append(event.event_type))
        registry.register(_BoomSkill("boom"))
        await registry.execute_skill("boom", {})
        assert SkillEvent.ERROR in seen

    @pytest.mark.asyncio
    async def test_register_event_callback_by_type(self, registry):
        calls = []
        registry.register_event_callback(
            SkillEvent.POST_EXECUTE,
            lambda skill, data: calls.append(skill.name),
        )
        registry.register(_EchoSkill("demo"))
        await registry.execute_skill("demo", {})
        assert calls == ["demo"]
