"""P2-20：技能启停与执行必须读真实注册表状态。"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from neurova.api.endpoints import skill as skill_api
from neurova.skill_system import Skill, SkillRegistry, SkillResult, SkillStatus


class _ProbeSkill(Skill):
    def __init__(self, name: str = "probe"):
        super().__init__(name=name, description="probe")
        self.calls = 0

    async def execute(self, params, context=None):
        self.calls += 1
        return SkillResult(success=True, data={"params": params})


def _request():
    return SimpleNamespace(state=SimpleNamespace(request_id="p2-20"))


def _registry_with(skill):
    registry = SkillRegistry()
    registry.register(skill)
    return registry


def test_disable_is_read_back_and_inactive_execution_is_rejected(monkeypatch):
    probe = _ProbeSkill()
    registry = _registry_with(probe)
    monkeypatch.setattr("neurova.skills.get_skill_registry", lambda: registry)

    response = asyncio.run(skill_api.disable_skill(_request(), "probe"))

    assert response["data"]["enabled"] is False
    assert registry.get_skill("probe").status == SkillStatus.INACTIVE
    listed = skill_api._get_skills_from_registry()
    assert listed[0]["enabled"] is False, "列表仍把 INACTIVE 报成 enabled"

    with pytest.raises(HTTPException) as raised:
        asyncio.run(skill_api.execute_skill(
            _request(), "probe", skill_api.SkillExecuteRequest(parameters={"x": 1})
        ))
    assert raised.value.status_code == 409
    assert probe.calls == 0, "INACTIVE 技能仍进入执行体"


def test_registry_execution_root_rejects_inactive_skill():
    probe = _ProbeSkill()
    registry = _registry_with(probe)
    registry.set_skill_enabled("probe", False)

    result = asyncio.run(registry.execute_skill("probe", {"x": 1}))

    assert result.success is False
    assert "inactive" in result.error.lower()
    assert probe.calls == 0


def test_false_set_enabled_is_not_reported_as_success(monkeypatch):
    class _RefusingRegistry(SkillRegistry):
        def set_skill_enabled(self, skill_name, enabled):
            return False

    registry = _RefusingRegistry()
    registry.register(_ProbeSkill())
    monkeypatch.setattr("neurova.skills.get_skill_registry", lambda: registry)

    with pytest.raises(HTTPException) as raised:
        asyncio.run(skill_api.disable_skill(_request(), "probe"))
    assert raised.value.status_code == 409


def test_registry_failure_does_not_fall_back_to_builtin_table(monkeypatch):
    class _BrokenRegistry(SkillRegistry):
        def list_skills(self):
            raise RuntimeError("registry unavailable")

    monkeypatch.setattr("neurova.skills.get_skill_registry", lambda: _BrokenRegistry())

    with pytest.raises(HTTPException) as raised:
        skill_api._get_skills_from_registry()
    assert raised.value.status_code == 503
    assert "registry unavailable" in raised.value.detail
