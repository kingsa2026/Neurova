"""
agent 自主分装（合成）技能联邦注册测试（2026-08-31）

根因: NL 合成/create_skill 只注册进内存 SkillRegistry(agent._skill_registry):
- /agent/{id}/skills 页面读 SkillService manifest —— 看不到;
- 冷启动后 registry 重建 —— 合成技能丢失;
- register_skill 构造 ToolSequenceSkill 时 registry.tool_router 恒为 None
  (agent_core 从未反向绑定) —— "能看见不能调"，执行报"需要 Agent 工具路由器"。

契约:
1. persist_synthesized_skill 后 SkillService.list_skills 可见(source=synthesized);
2. restore(market_registry) 后新 registry 含该技能, 且为可执行
   (SkillRegistry.set_tool_router 注入后 ToolSequenceSkill 逐步骤执行);
3. 执行时 tool_sequence 步骤经 tool_router 透传(工具路由 mock)。
"""

import asyncio

import pytest

from neurova.skills.market_registry import (
    persist_synthesized_skill,
    restore_market_skills_from_service,
)
from neurova.skills.skill_service import SkillService
from neurova.skill_system import SkillRegistry


@pytest.fixture
def service(tmp_path):
    return SkillService(agent_id="default", skills_dir=str(tmp_path / "skills"))


class _FakeToolResult:
    success = True
    error = None
    result = {"ok": True}


class _FakeToolRouter:
    def __init__(self):
        self.calls = []

    def execute(self, tool_name, params, agent_id=None, user_id=None):
        self.calls.append((tool_name, params))
        return _FakeToolResult()


def test_synthesized_skill_visible_in_agent_skills(service):
    ok = persist_synthesized_skill(
        skill_id="summarize_notes",
        name="summarize_notes",
        description="汇总笔记",
        version="1.0.0",
        tool_sequence=[{"tool": "memory_search", "params": {"query": "笔记"}}],
        service=service,
    )
    assert ok is True
    skills = service.list_skills()
    assert any(s.get("id") == "summarize_notes" for s in skills)
    info = service.get_skill_info("summarize_notes")
    assert (info.get("manifest") or {}).get("source") == "synthesized"
    # 技能页契约字段
    entry = next(s for s in skills if s.get("id") == "summarize_notes")
    assert entry["name"] == "summarize_notes"
    assert entry["enabled"] is True


def test_synthesized_restored_executable_after_restart(service):
    """冷启动: 新 registry 恢复 tool_sequence 技能, 且经 tool_router 可执行"""
    persist_synthesized_skill(
        skill_id="summarize_notes",
        name="summarize_notes",
        description="汇总笔记",
        version="1.0.0",
        tool_sequence=[{"tool": "memory_search", "params": {"query": "笔记"}}],
        service=service,
    )
    fresh = SkillRegistry()
    router = _FakeToolRouter()
    fresh.set_tool_router(router)
    restored = restore_market_skills_from_service(service, fresh)
    assert restored >= 1
    skill = fresh.get_skill("summarize_notes")
    assert skill is not None
    assert hasattr(skill, "execute")

    result = asyncio.run(skill.execute({}, context={"agent_id": "default", "user_id": "u1"}))
    assert result.success is True, getattr(result, "error", None)
    assert router.calls and router.calls[0][0] == "memory_search"
    assert router.calls[0][1].get("query") == "笔记"


def test_synthesized_without_router_restores_as_shell(service):
    """未绑定 tool_router 时恢复为壳(可见), 执行报需要路由器 —— 注册表绑定顺序守卫"""
    persist_synthesized_skill(
        skill_id="summarize_notes", name="summarize_notes", description="desc",
        version="1.0.0", tool_sequence=[{"tool": "memory_search", "params": {}}],
        service=service,
    )
    fresh = SkillRegistry()  # 不 set_tool_router
    restore_market_skills_from_service(service, fresh)
    skill = fresh.get_skill("summarize_notes")
    assert skill is not None
    result = asyncio.run(skill.execute({}, context={"agent_id": "default"}))
    assert result.success is False
