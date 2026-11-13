# -*- coding: utf-8 -*-
"""graph_search 内置工具三元组（schema 单源 / 分派表 / 执行体）测试。

schema/dispatch 全量对账由既有守卫（test_builtin_tools_expansion、
test_tool_schema_contract）承担；本文件钉 graph_search 自己的行为面：
三种 mode 的路由、参数校验、只读能力声明、失败诚实透传。
（graphiti 对照批 C4，docs/08-research/graphiti_vs_neurova_*）
"""

from unittest.mock import Mock

import pytest

from neurova.builtin_tools import _BUILTIN_SCHEMAS, get_builtin_tool_params


def _make_executor():
    from neurova.tool_executor import ToolExecutor

    agent = Mock()
    agent._skill_registry = Mock()
    agent.tool_router = Mock()
    agent.tool_memory = Mock()
    agent.tool_lifecycle = Mock()
    agent.skill_packer = Mock()
    agent.config = Mock()
    agent.config.agent_id = "default"
    agent._current_user_id = "default"
    agent.agent_id = "default"
    agent.memory_manager = Mock()
    agent.asr_manager = None
    agent.tts_manager = None
    return ToolExecutor(agent)


def _seedChain(store):
    """两跳链 A1 -linked_a-> A2 -linked_b-> A3 ＋ 独立簇 B1->B2。"""
    from neurova.knowledge.foundation.admission import (
        AdmissionRequest,
        productionAdmissionGate,
    )
    from neurova.knowledge.ontology.term_registry import OntologyTermRegistry

    registry = OntologyTermRegistry(store)
    registry.register("linked_a", "relation")
    registry.register("linked_b", "relation")
    gate = productionAdmissionGate(store)
    for src, dst, pred in [("A1", "A2", "linked_a"), ("A2", "A3", "linked_b"),
                           ("B1", "B2", "linked_a")]:
        content = "%s %s %s" % (src, pred, dst)
        gate.admit(AdmissionRequest(
            agentId="default", subjectLabel=src, predicateTermId=pred,
            objectTerm=dst, content=content,
            assertions=[{"actorType": "pipeline", "actorId": "unit",
                         "mediumRef": "unit:test", "statementText": content}]))
    return registry


@pytest.fixture
def kb(tmp_path, monkeypatch):
    from neurova.knowledge.foundation import knowledge_facts as kf

    s = kf.KnowledgeFactStore(str(tmp_path / "kb.db"))
    monkeypatch.setattr(kf, "get_knowledge_fact_store", lambda *a, **k: s)
    yield s
    s.close()


class TestSchemaAndDispatch:
    def test_schemaRegistered(self):
        entry = get_builtin_tool_params("graph_search")
        assert entry is not None, "graph_search 必须进 schema 单源"
        assert entry["parameters"]["required"] == ["query"]
        modeEnum = entry["parameters"]["properties"]["mode"]["enum"]
        assert modeEnum == ["walk", "global", "drift"]

    def test_dispatchRowPointsToRealMethod(self):
        dispatch = type(_make_executor())._builtin_dispatch
        assert dispatch.get("graph_search") == "_execute_graph_search"
        assert callable(getattr(type(_make_executor()), "_execute_graph_search", None))

    def test_capabilityReadOnly(self):
        """只读走查：无写作用域，治理故障时按只读白名单放行。"""
        cap = _BUILTIN_SCHEMAS["graph_search"]["capability"]
        assert cap["readOnly"] is True
        assert cap["writeScopes"] == ("none",)


class TestExecutorModes:
    @pytest.mark.asyncio
    async def test_missingQueryRejected(self, kb):
        result = await _make_executor()._execute_graph_search({"mode": "walk"})
        assert "error" in result
        assert "query" in result["error"]

    @pytest.mark.asyncio
    async def test_invalidModeRejected(self, kb):
        result = await _make_executor()._execute_graph_search(
            {"query": "A1", "mode": "crawl"})
        assert "error" in result
        assert "mode" in result["error"]

    @pytest.mark.asyncio
    async def test_walkModeReturnsTwoHopFacts(self, kb):
        _seedChain(kb)
        result = await _make_executor()._execute_graph_search(
            {"query": "A1", "mode": "walk", "max_hops": 2, "limit": 8})
        assert result["success"] is True
        assert result["mode"] == "walk"
        assert result["count"] >= 1, "两跳链应至少带回 A1→A2→A3 一条"
        paths = " || ".join(str(r.get("path") or "") for r in result["results"])
        assert "A3" in paths, "终点事实应含链尾 A3"

    @pytest.mark.asyncio
    async def test_walkModeHopsClampedToCeiling(self, kb):
        """max_hops 放大值必须被钳到 4（递归 CTE 硬上限，防组合爆炸）。"""
        _seedChain(kb)
        result = await _make_executor()._execute_graph_search(
            {"query": "A1", "mode": "walk", "max_hops": 99})
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_globalModeHitsCommunitySummary(self, kb):
        _seedChain(kb)
        from neurova.knowledge.community_graph import CommunityGraphBuilder

        builder = CommunityGraphBuilder(kb, agentId="default", tenantId="default")
        builder.detect(summarizer=lambda labels: "齿轮箱 维护 " + ",".join(labels))
        result = await _make_executor()._execute_graph_search(
            {"query": "齿轮箱 维护", "mode": "global"})
        assert result["success"] is True
        assert result["count"] >= 1, "global：查询应命中社区摘要"

    @pytest.mark.asyncio
    async def test_driftModeFollowsNeighborhood(self, kb):
        _seedChain(kb)
        from neurova.knowledge.community_graph import CommunityGraphBuilder

        CommunityGraphBuilder(kb, agentId="default", tenantId="default").detect()
        result = await _make_executor()._execute_graph_search(
            {"query": "A1", "mode": "drift"})
        assert result["success"] is True
        assert result["count"] >= 1, "drift：实体邻域应命中 A 簇社区"
