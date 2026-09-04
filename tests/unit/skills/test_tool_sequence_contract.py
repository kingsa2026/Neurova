"""tool_sequence 契约统一 + 冷启动恢复白名单回归测试（经验结晶闭环审计 2026-09-04 修复 ①③）

断点①：pattern_miner / AutoSkillBuilder / genetic_engine 产出的 tool_sequence 是
List[str]，而 ToolSequenceSkill.execute 要求每步是 {"tool","params"} dict，否则
"第 0 步格式错误：必须是 dict"——自动进化技能注册成功但调用必败，闭环后段吃到的
全是假失败数据。修复：execute 入口把 str 步归一化为 {"tool": str}（契约缝单点修复，
覆盖全部三条生产线与冷启动恢复路径）。

断点③：genetic/skill_packer 持久化 manifest.source="auto"，但
market_registry.restore_market_skills_from_service 冷启动白名单只有
marketplace/synthesized/agent——重启后自动技能永不恢复进 registry。
修复：白名单纳入 "auto"。
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from neurova.skill_system import SkillRegistry, ToolSequenceSkill


class _FakeRouter:
    """记录调用的假工具路由器"""

    def __init__(self):
        self.calls = []

    def execute(self, tool_name, params, agent_id=None, user_id=None):
        self.calls.append((tool_name, dict(params or {})))
        return SimpleNamespace(success=True, result="ok")


class TestToolSequenceStringSteps:
    """断点①：List[str] 序列必须可执行"""

    @pytest.mark.asyncio
    async def test_string_sequence_executes(self):
        router = _FakeRouter()
        skill = ToolSequenceSkill(
            name="genetic_a_b",
            description="遗传进化工具组合",
            tool_sequence=["a", "b"],
            tool_router=router,
        )
        result = await skill.execute(
            params={}, context={"agent_id": "x", "user_id": "u"}
        )
        assert result.success is True, getattr(result, "error", "")
        assert router.calls == [("a", {}), ("b", {})]

    @pytest.mark.asyncio
    async def test_mixed_sequence_executes(self):
        """dict 步与 str 步混排（create_skill 产物 + 进化产物拼接）"""
        router = _FakeRouter()
        skill = ToolSequenceSkill(
            name="mixed",
            description="d",
            tool_sequence=[{"tool": "a", "params": {"p": 1}}, "b"],
            tool_router=router,
        )
        result = await skill.execute(params={}, context=None)
        assert result.success is True
        assert router.calls == [("a", {"p": 1}), ("b", {})]

    @pytest.mark.asyncio
    async def test_invalid_entry_type_still_fails(self):
        """非 str 非 dict 的步进仍然 fail-closed"""
        router = _FakeRouter()
        skill = ToolSequenceSkill(
            name="bad", description="d", tool_sequence=[123], tool_router=router
        )
        result = await skill.execute(params={}, context=None)
        assert result.success is False
        assert "格式错误" in (result.error or "")

    @pytest.mark.asyncio
    async def test_registry_registered_str_sequence_is_executable(self):
        """注册边界：register_skill 构造的 ToolSequenceSkill 也必须可执行"""
        router = _FakeRouter()
        registry = SkillRegistry()
        registry.set_tool_router(router)
        manifest = SimpleNamespace(
            id="genetic_a_b",
            name="genetic_a_b",
            description="遗传进化工具组合",
            config={"tool_sequence": ["a", "b"]},
        )
        assert registry.register_skill(manifest) is True
        skill = registry.get_skill("genetic_a_b")
        result = await skill.execute(params={}, context=None)
        assert result.success is True
        assert router.calls == [("a", {}), ("b", {})]


class TestRestoreAutoSource:
    """断点③：冷启动恢复白名单纳入 auto 源"""

    def _fake_service(self):
        service = MagicMock()
        service.list_skills.return_value = [
            {"id": "genetic_a_b", "name": "genetic_a_b", "description": "遗传进化"},
        ]
        service.get_skill_info.return_value = {
            "manifest": {"source": "auto", "config": {"tool_sequence": ["a", "b"]}},
        }
        return service

    def test_auto_source_restored_into_registry(self):
        from neurova.skills.market_registry import restore_market_skills_from_service

        registry = SkillRegistry()
        restored = restore_market_skills_from_service(self._fake_service(), registry)
        assert restored == 1
        assert registry.has_skill("genetic_a_b")

    def test_marketplace_source_still_restored(self):
        """存量白名单来源不回归"""
        from neurova.skills.market_registry import restore_market_skills_from_service

        service = self._fake_service()
        service.get_skill_info.return_value = {
            "manifest": {"source": "marketplace", "config": {"tool_sequence": ["a", "b"]}},
        }
        registry = SkillRegistry()
        restored = restore_market_skills_from_service(service, registry)
        assert restored == 1
        assert registry.has_skill("genetic_a_b")

    def test_unknown_source_skipped(self):
        from neurova.skills.market_registry import restore_market_skills_from_service

        service = self._fake_service()
        service.get_skill_info.return_value = {
            "manifest": {"source": "mystery", "config": {"tool_sequence": ["a", "b"]}},
        }
        registry = SkillRegistry()
        restored = restore_market_skills_from_service(service, registry)
        assert restored == 0
        assert not registry.has_skill("genetic_a_b")
