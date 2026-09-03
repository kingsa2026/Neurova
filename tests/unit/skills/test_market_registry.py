"""
市场技能安装 → Agent 联邦注册 测试（2026-08-31）

根因链（三链断）：
1. MarketImporter.import_skill 只写模拟 skill.json 到市场目录 + 内存 _installed；
2. Agent 技能页（GET /skill-pool/agent/{id}/skills）读 SkillService 的
   data/agents/{id}/skills/manifest.json —— 市场安装从未写入 → 页面看不到；
3. agent 工具集来自 SkillRegistry（LLM 每轮把 registry skills 混入 tools）——
   市场安装从未 register_skill → agent 感知不到、无法调用。

契约（link_market_skill_to_agent）：
1. 安装后 SkillService(list_skills) 可见该技能（技能页）；
2. 安装后 SkillRegistry.get_skill 非 None，且 execute 参数直通可调用
   （web-search → WebSearchSkill 真实执行体）；
3. unlink_market_skill_from_agent 后两处均移除（卸载一致性）。

测试注入隔离：tmp 目录 SkillService + 手工 SkillRegistry（不触碰单例）。
"""

import pytest

from neurova.skills.market_registry import (
    link_market_skill_to_agent,
    unlink_market_skill_from_agent,
)
from neurova.skills.skill_service import SkillService
from neurova.skill_system import SkillRegistry


@pytest.fixture
def service(tmp_path):
    return SkillService(agent_id="default", skills_dir=str(tmp_path / "skills"))


@pytest.fixture
def registry():
    return SkillRegistry()


def test_install_web_search_visible_in_agent_skills(service, registry):
    result = link_market_skill_to_agent(
        skill_id="web-search",
        name="Web Search",
        description="搜索互联网获取实时信息",
        version="1.2.0",
        service=service,
        registry=registry,
    )
    assert result["registered"] is True
    skills = service.list_skills()
    assert any(s.get("id") == "web-search" for s in skills)
    # 技能页契约字段
    entry = next(s for s in skills if s.get("id") == "web-search")
    assert entry["name"] == "Web Search"
    assert entry["enabled"] is True


def test_web_search_registered_executable(service, registry, monkeypatch):
    link_market_skill_to_agent(
        skill_id="web-search",
        name="Web Search",
        description="搜索互联网获取实时信息",
        version="1.2.0",
        service=service,
        registry=registry,
    )
    skill = registry.get_skill("web-search")
    assert skill is not None
    assert hasattr(skill, "execute") and hasattr(skill, "name")

    # 参数直通验证: web-search 执行体把 params.query 透传给搜索后端
    import asyncio

    sent = {}
    import neurova.skills.builtin.web_search_executor as wse

    def fake_web_search(query, max_results=5, timeout=10.0, backend="bing"):
        sent["query"] = query
        sent["max_results"] = max_results
        return [{"query": query, "snippet": "stub"}]

    monkeypatch.setattr(wse, "web_search", fake_web_search)
    result = asyncio.run(skill.execute({"query": "Neurova 音乐", "max_results": 3}))
    assert result.success is True, getattr(result, "error", None)
    assert sent["query"] == "Neurova 音乐"
    assert sent["max_results"] == 3


def test_uninstall_removes_from_both(service, registry):
    link_market_skill_to_agent("web-search", "Web Search", "desc", "1.0.0", service=service, registry=registry)
    result = unlink_market_skill_from_agent("web-search", service=service, registry=registry)
    assert result["unregistered"] is True
    assert registry.get_skill("web-search") is None
    assert not any(s.get("id") == "web-search" for s in service.list_skills())


def test_unknown_skill_degrades_to_shell(service, registry):
    """无真实执行体的市场技能: 注册可见但明确标注不可调用 hint"""
    result = link_market_skill_to_agent(
        skill_id="code-analysis", name="Code Analysis", description="desc", version="2.0.0", service=service, registry=registry
    )
    assert result["registered"] is True
    assert registry.get_skill("code-analysis") is not None
    # 壳: 仅可感知(技能页/工具列表), 无真实执行体
    assert result["registry_count"] == 1


def test_link_injects_running_agent_registries(service, registry):
    """运行中 Agent 的独立注册表同样被注入（安装即感知）"""
    running_registry = SkillRegistry()
    result = link_market_skill_to_agent(
        skill_id="web-search", name="Web Search", description="desc", version="1.0.0",
        service=service, registry=registry, extra_registries=[running_registry],
    )
    assert result["registry_count"] == 2
    assert registry.get_skill("web-search") is not None
    assert running_registry.get_skill("web-search") is not None


def test_market_skill_exposes_param_schema(service, registry):
    """参数 schema 断点守卫: 注册名 web-search(连字符) 必须在
    skills/builtin/schemas 表中有别名, 否则模型看不到 query 参数不调用"""
    link_market_skill_to_agent(
        skill_id="web-search", name="Web Search", description="搜索", version="1.0.0",
        service=service, registry=registry,
    )
    skill = registry.get_skill("web-search")
    assert skill is not None
    params = skill._get_parameters()
    assert "query" in params, "web-search 缺少参数 schema: 模型将不知道如何传参"
    assert params["query"].get("required") is True


def test_restore_after_agent_restart(service):
    """冷启动恢复：新 registry 从 SkillService manifest 恢复市场技能"""
    from neurova.skills.market_registry import (
        link_market_skill_to_agent,
        restore_market_skills_from_service,
    )

    link_market_skill_to_agent(
        skill_id="web-search", name="Web Search", description="desc", version="1.0.0",
        service=service, registry=SkillRegistry(),
    )
    # 模拟 Agent 重启后全新注册表
    fresh = SkillRegistry()
    restored = restore_market_skills_from_service(service, fresh)
    assert restored >= 1
    assert fresh.get_skill("web-search") is not None
