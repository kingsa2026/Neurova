"""006 · 技能停用与质量熔断要真的少掉一个工具（视图键域收口）。

根因（三闸恒开绿灯）：`skills/skill_visibility.py` 以 registry 键（= `skill.name`）
建条目且**硬编码 enabled=True**，而 manifest 条目按 `skill_id` 建键。schema 装配拿
**name** 去问视图 ⇒ 自动技能 `name ≠ skill_id` 时永远命中①条目：

1. `quality_for` 读①⇒无 usage⇒None ⇒ 质量熔断放行；
2. manifest 的 `enabled=False` 只挡②；
3. `SkillRegistry.set_skill_enabled` 只改 `skill.status`，schema 段无 `status` 判据。

验收判据是**发给 LLM 的工具清单少了那一项**，不是 manifest 字段变了。
"""

from __future__ import annotations

from typing import Any, Dict

import pytest

import pytest

from neurova.skills import library_service as lib
from neurova.skills.skill_injection import QualityInfo, quality_blocked
from neurova.skills.skill_visibility import SkillView, VisibleSkill, build_turn_view
from tests.unit.skills.creation_helpers import register_proven_skill


@pytest.fixture
def lib_base(tmp_path, monkeypatch):
    """三库根指向 tmp，并清空同进程单例（`library_service` 的既有测试姿势）。"""
    monkeypatch.setattr(lib, "_BASE_DIR", tmp_path / "skill-libraries")
    lib.reset_libraries_for_tests()
    yield tmp_path
    lib.reset_libraries_for_tests()


class _StubSkill:
    def __init__(self, name: str, description: str = ""):
        self.name = name
        self.description = description
        self.config = {}


def _stub_registry(name: str) -> Dict[str, Any]:
    return {name: _StubSkill(name, "自动技能")}


class TestIdentityReverseLookup:
    """① 条目必须按 identity 反查 manifest 的 enabled/usage，不硬编码 True。"""

    def test_disabled_auto_skill_is_not_invocable_by_name(self, lib_base):
        """自动技能 name≠skill_id：manifest 停用后，视图必须按 name 判不可见。"""
        agent_id = "agent-view-01"
        service = lib.get_library(lib.POOL_AGENT, agent_id)
        register_proven_skill(
            service, "synth_abc123", "general_tool", description="自动生成",
        )
        service.disable_skill("synth_abc123")
        view = build_turn_view(
            agent_id, None,
            registry_skills=_stub_registry("general_tool"),
        )
        assert not view.invocable("general_tool"), (
            "name≠skill_id 的自动技能停用后仍被视图判可见（①条目硬编码 enabled=True）"
        )

    def test_enabled_auto_skill_stays_invocable(self, lib_base):
        """反向锁：同一 name≠skill_id 技能**启用后**必须可见（不是一刀切拒掉）。"""
        agent_id = "agent-view-01"
        service = lib.get_library(lib.POOL_AGENT, agent_id)
        register_proven_skill(
            service, "synth_abc123", "general_tool", description="自动生成",
        )
        service.enable_skill("synth_abc123")
        try:
            from neurova.core.turn_context import set_turn_skills_off, reset_turn_skills_off
        except Exception:  # noqa: BLE001 - 无轮次上下文时跳过
            pass
        view = build_turn_view(agent_id, None, registry_skills=_stub_registry("general_tool"))
        assert view.invocable("general_tool")

    def test_quality_reads_manifest_usage_through_identity(self, lib_base):
        """质量读数必须沿同一反查口取到 manifest 的 usage（不再返回 None）。"""
        agent_id = "agent-view-01"
        service = lib.get_library(lib.POOL_AGENT, agent_id)
        register_proven_skill(
            service, "synth_abc123", "general_tool", description="自动生成",
        )
        service.enable_skill("synth_abc123")
        with service._lock:
            service._skills["synth_abc123"]["usage"] = {
                "applications": 3, "completions": 0, "fallbacks": 3,
            }
        view = build_turn_view(agent_id, None, registry_skills=_stub_registry("general_tool"))
        quality = view.quality_for("general_tool")
        assert quality is not None, "质量读数经 name 取不到 manifest 的 usage"
        assert quality.applications == 3
        assert quality_blocked(quality), "applications≥2 且零完成必须触发熔断"

    def test_tools_for_llm_loses_the_disabled_skill(self, lib_base):
        """验收判据：停用生效 = 发给 LLM 的工具清单真的少了那一项。"""
        agent_id = "agent-view-01"
        service = lib.get_library(lib.POOL_AGENT, agent_id)
        register_proven_skill(
            service, "synth_abc123", "general_tool", description="自动生成",
        )
        service.disable_skill("synth_abc123")
        view = build_turn_view(agent_id, None, registry_skills=_stub_registry("general_tool"))
        tools = [
            {"type": "function", "function": {"name": name}}
            for name in _stub_registry("general_tool")
            if view.invocable(name)
        ]
        assert [t["function"]["name"] for t in tools] == []


class TestViewLookupIsSinglePass:
    """invocable / quality_for / trust_for 三个取数口必须统一到同一次反查。"""

    def test_one_entry_carries_all_three_reads(self):
        view = SkillView(agent_id="a1")
        view.skills["general_tool"] = VisibleSkill(
            name="general_tool", skill_id="synth_abc123", pool=lib.POOL_AGENT,
            owner_key="a1",
            entry={
                "id": "synth_abc123", "enabled": True,
                "usage": {"applications": 2, "completions": 2, "fallbacks": 0},
                "identity": {"trust": {"state": "provisional"}},
            },
        )
        assert view.invocable("general_tool") is True
        assert view.quality_for("general_tool") is not None
        assert view.trust_for("general_tool") == "provisional"


class TestNameCollisionWarning:
    """同名覆盖要出声（计数可观测），但不硬拒存量库。"""

    @staticmethod
    def _skill(name: str, skill_id: str):
        from neurova.skill_system import Skill

        skill = Skill(name=name, description=f"{name}-{skill_id}")
        skill.skill_id = skill_id
        skill.config = {"skill_id": skill_id}
        return skill

    def test_same_name_different_identity_warns(self, caplog):
        import logging

        from neurova.skill_system import SkillRegistry

        registry = SkillRegistry()
        registry.register(self._skill("general_tool", "synth_a"))
        with caplog.at_level(logging.WARNING, logger="neurova.skill_system"):
            registry.register(self._skill("general_tool", "synth_b"))
        assert getattr(registry, "_name_collision_count", 0) == 1, "同名覆盖没有计数，静默丢技能不可见"
        assert any("同名覆盖" in r.message for r in caplog.records)

    def test_same_identity_does_not_warn(self):
        from neurova.skill_system import SkillRegistry

        registry = SkillRegistry()
        registry.register(self._skill("s1", "synth_c"))
        registry.register(self._skill("s1", "synth_c"))
        assert getattr(registry, "_name_collision_count", 0) == 0
