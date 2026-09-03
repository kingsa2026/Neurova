"""
远端 SKILL.md 指令型技能可执行测试（2026-08-31）

契约（市场安装的远端技能从"壳（可见不可调）"升级为"指令型可调"）:
1. SkillDocSkill.execute 返回 SKILL.md 指令体 + scripts 清单（Agent Skills
   标准语义），_get_parameters 提供通用 task 参数;
2. link_market_skill_to_agent 对安装目录含 SKILL.md 的技能注册指令型
   可执行（不再退化壳）;
3. restore_market_skills_from_service 冷启动同样恢复指令型;
4. 无映射且无 SKILL.md 时仍注册壳（既有语义保持）。
"""

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from neurova.skills.market_registry import (
    _build_executable_skill,
    link_market_skill_to_agent,
    restore_market_skills_from_service,
)
from neurova.skills.skill_service import SkillService
from neurova.skill_system import SkillRegistry

SKILL_MD = """---
name: demo-skill
description: 演示技能
---

# 演示技能

按以下步骤执行任务…
"""


@pytest.fixture
def fake_importer(monkeypatch, tmp_path):
    """get_market_importer 返回指向 tmp 安装目录的 fake"""
    skills_dir = tmp_path / "market-skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    fake = SimpleNamespace(_skills_dir=skills_dir)
    monkeypatch.setattr("neurova.skills.market_importer.get_market_importer", lambda: fake)
    return skills_dir


@pytest.fixture
def installed_remote_skill(fake_importer):
    """在 fake 安装目录放一个含 SKILL.md + scripts 的远端技能"""
    skill_dir = fake_importer / "aliyun--demo"
    (skill_dir / "scripts").mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(SKILL_MD, encoding="utf-8")
    (skill_dir / "scripts" / "run.py").write_text("print('hi')", encoding="utf-8")
    return skill_dir


@pytest.fixture
def service(tmp_path):
    return SkillService(agent_id="default", skills_dir=str(tmp_path / "agent-skills"))


class TestSkillDocSkill:
    def test_execute_returns_instructions(self, installed_remote_skill):
        from neurova.skills.market_registry import SkillDocSkill

        skill = SkillDocSkill("aliyun--demo", installed_remote_skill, description="演示")
        result = asyncio.run(skill.execute({"task": "帮我演示"}))
        assert result.success is True, getattr(result, "error", None)
        data = result.data
        assert "# 演示技能" in data["instructions"]
        assert "按以下步骤执行任务" in data["instructions"]
        assert data["scripts"] == ["run.py"]
        assert data["task"] == "帮我演示"
        assert data["skill_dir"] == str(installed_remote_skill)

    def test_get_parameters_has_task(self, installed_remote_skill):
        from neurova.skills.market_registry import SkillDocSkill

        skill = SkillDocSkill("aliyun--demo", installed_remote_skill)
        params = skill._get_parameters()
        assert "task" in params

    def test_execute_missing_skill_md_fails(self, tmp_path):
        from neurova.skills.market_registry import SkillDocSkill

        skill = SkillDocSkill("x", tmp_path / "nope")
        result = asyncio.run(skill.execute({}))
        assert result.success is False


class TestRegistryIntegration:
    def test_build_executable_prefers_doc_skill(self, installed_remote_skill, fake_importer):
        skill = _build_executable_skill("aliyun--demo", "演示描述")
        assert skill is not None
        assert skill.name == "aliyun--demo"
        assert skill.description == "演示描述"

    def test_link_registers_doc_skill(self, service, installed_remote_skill, fake_importer):
        registry = SkillRegistry()
        result = link_market_skill_to_agent(
            skill_id="aliyun--demo",
            name="Demo",
            description="演示技能",
            version="1.0.0",
            service=service,
            registry=registry,
        )
        assert result["registered"] is True
        skill = registry.get_skill("aliyun--demo")
        assert skill is not None
        r = asyncio.run(skill.execute({"task": "t"}))
        assert r.success is True
        assert "instructions" in r.data

    def test_restore_rebuilds_doc_skill(self, service, installed_remote_skill, fake_importer):
        registry = SkillRegistry()
        link_market_skill_to_agent(
            skill_id="aliyun--demo",
            name="Demo",
            description="演示技能",
            version="1.0.0",
            service=service,
            registry=registry,
        )
        # 模拟 Agent 重启后全新注册表
        fresh = SkillRegistry()
        restored = restore_market_skills_from_service(service, fresh, market_skills_dir=fake_importer)
        assert restored >= 1
        skill = fresh.get_skill("aliyun--demo")
        assert skill is not None
        r = asyncio.run(skill.execute({}))
        assert r.success is True and "instructions" in r.data

    def test_no_doc_falls_to_shell(self, service, fake_importer):
        """无映射且无 SKILL.md → 仍注册壳（既有语义）"""
        registry = SkillRegistry()
        result = link_market_skill_to_agent(
            skill_id="code-analysis",
            name="Code Analysis",
            description="desc",
            version="2.0.0",
            service=service,
            registry=registry,
        )
        assert result["registered"] is True
        assert registry.get_skill("code-analysis") is not None
        # 壳不是指令型（无 _get_parameters 的 task 契约）
        from neurova.skills.market_registry import SkillDocSkill

        assert not isinstance(registry.get_skill("code-analysis"), SkillDocSkill)
