"""知识图谱 LLM 桥接回归测试（TDD 红绿）

根因链（2026-09-05 知识图谱页面恒空排查，日志实锤「未解析到可用 LLM，跳过图谱抽取」）:
  R1: knowledge._default_llm_call 读 request.app.state.agents —— 全仓没有任何
      生产代码向 FastAPI 原生 app.state 写入 agents（唯一事实源是
      neurova.api.endpoints.set_app_state 注入的模块级注册表，home.py 注释
      已明示此坑）→ 抽取在导入链路恒被跳过，图谱永远为空。
  R2: AgentLLMClient.chat 是 async —— 同步调用拿到 coroutine 后
      getattr(resp, "content", "") 恒为空串，即使解析到 agent 也抽取不出。
  R3: knowledge_graph_api._get_kg_manager 从不存在的 neurova.api.app_state
      模块导入 get_app_state → ImportError 被 except 吞掉 → agent 级
      knowledge_graph_manager 恒解析不到（静默死分支）。
  R4: 同根因消费方 semantic_search_api._get_runtime_memory_manager /
      enhanced_memory_search_api._get_all_recall_engines。
  R5: 抽取只挂在 /knowledge/import 时刻，无补跑入口 —— 存量条目（含 R1
      期间导入的）永久落后于图谱，需要 backfill 端点一次性补建。
"""

import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from neurova.api import endpoints as api_endpoints
from neurova.api import auth


@pytest.fixture
def registry():
    """注册表隔离：保存/恢复 endpoints 模块级 _app_state。"""
    old = api_endpoints.get_app_state()
    yield api_endpoints.set_app_state
    api_endpoints.set_app_state(old)


def _llm_agent(json_payload: str):
    """带 async chat 的 Agent 替身（模拟 AgentLLMClient 契约）。"""
    client = MagicMock()
    client.chat = AsyncMock(return_value=SimpleNamespace(content=json_payload))
    return SimpleNamespace(llm_client=client)


# ---------------------------------------------------------------
# R1+R2: _default_llm_call 从真实注册表解析 + async chat 同步桥接
# ---------------------------------------------------------------


def test_default_llm_call_resolves_agent_from_registry(registry):
    from neurova.api.endpoints import knowledge as kb

    registry({"agents": {"default": _llm_agent('{"entities": [], "relations": []}')}})
    llm_call = kb._default_llm_call(None)

    assert llm_call is not None, "注册表里有活跃 Agent 时必须解析出 LLM 调用器"
    assert llm_call("prompt") == '{"entities": [], "relations": []}'


def test_default_llm_call_empty_registry_returns_none(registry):
    from neurova.api.endpoints import knowledge as kb

    registry({"agents": {}})
    assert kb._default_llm_call(None) is None


def test_default_llm_call_empty_content_returns_empty_string(registry):
    from neurova.api.endpoints import knowledge as kb

    agent = SimpleNamespace(llm_client=MagicMock())
    agent.llm_client.chat = AsyncMock(return_value=SimpleNamespace(content=""))
    registry({"agents": {"default": agent}})

    assert kb._default_llm_call(None)("p") == ""


def test_default_llm_call_prefers_specified_agent(registry):
    """抽取应优先用知识所属 agent 的 LLM，而不是第一个碰巧有 client 的。"""
    from neurova.api.endpoints import knowledge as kb

    used = {"which": None}

    def _make_client(tag, payload):
        client = MagicMock()
        client.chat = AsyncMock(return_value=SimpleNamespace(content=payload))

        def _track(msgs, **kw):
            used["which"] = tag
            return client.chat.return_value

        client.chat.side_effect = _track
        return client

    registry(
        {
            "agents": {
                "default": SimpleNamespace(llm_client=_make_client("default", '{"from":"default"}')),
                "kai": SimpleNamespace(llm_client=_make_client("kai", '{"from":"kai"}')),
            }
        }
    )

    llm_call = kb._default_llm_call(None, prefer_agent_id="kai")
    assert llm_call("p") == '{"from":"kai"}'
    assert used["which"] == "kai"


def test_default_llm_call_falls_back_when_preferred_errors(registry):
    """首选 agent 的模型坏（AgentLLMClient 错误契约：返回 [LLM Error] 文本不抛）→
    必须回退下一个活跃 agent，而不是整个抽取链静默死亡。"""
    from neurova.api.endpoints import knowledge as kb

    bad = MagicMock()
    bad.chat = AsyncMock(return_value=SimpleNamespace(content="[LLM Error] Model id: x has no provider"))
    good = MagicMock()
    good.chat = AsyncMock(return_value=SimpleNamespace(content='{"entities": []}'))
    registry(
        {
            "agents": {
                "default": SimpleNamespace(llm_client=bad),
                "216fb777": SimpleNamespace(llm_client=good),
            }
        }
    )

    llm_call = kb._default_llm_call(None, prefer_agent_id="default")
    assert llm_call("p") == '{"entities": []}'
    good.chat.assert_awaited()


# ---------------------------------------------------------------
# R3: agent 级 knowledge_graph_manager 解析
# ---------------------------------------------------------------


def test_get_kg_manager_prefers_agent_scoped_manager(registry, monkeypatch):
    from neurova.api.endpoints import knowledge_graph_api as kg

    fake_graph = object()
    registry(
        {"agents": {"a1": SimpleNamespace(knowledge_graph_manager=fake_graph)}}
    )
    sentinel = object()
    monkeypatch.setattr(
        "neurova.cognitive_layers.knowledge_graph.manager.get_knowledge_graph_manager",
        lambda *a, **k: sentinel,
    )

    assert kg._get_kg_manager("a1") is fake_graph


def test_get_kg_manager_falls_back_to_agent_scoped_registry(monkeypatch):
    """fallback 语义更新（2026-09-05 隔离）：不再落全局单例，改 per-agent 注册表。"""
    from fastapi import HTTPException

    from neurova.api.endpoints import knowledge_graph_api as kg

    sentinel = object()
    monkeypatch.setattr(
        "neurova.cognitive_layers.knowledge_graph.manager.get_knowledge_graph_manager",
        lambda *a, **k: sentinel,
    )
    monkeypatch.setattr(
        "neurova.cognitive_layers.knowledge_graph.manager._agent_graph_root",
        lambda: "/tmp/kg-isolation-test-root",
    )

    mgr = kg._get_kg_manager("a1")
    assert mgr is not sentinel, "fallback 必须走 per-agent 注册表而非全局单例"
    assert mgr._storage_dir.name == "knowledge_graph"

    with pytest.raises(HTTPException) as ei:
        kg._get_kg_manager("../evil")
    assert ei.value.status_code == 400


# ---------------------------------------------------------------
# R5: backfill 补抽端点
# ---------------------------------------------------------------


def test_backfill_extracts_only_pending_entries(registry, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from neurova.api.endpoints import knowledge_graph_api as kg

    entry_pending = {
        "knowledge_id": "k1",
        "title": "T1",
        "content": "C1 body",
        "graph_node_ids": [],
    }
    entry_done = {
        "knowledge_id": "k2",
        "title": "T2",
        "content": "C2 body",
        "graph_node_ids": ["n9"],
    }

    class FakeRepo:
        def __init__(self):
            self.updated = None

        def list_knowledge(self, agent_id, category=None, limit=20, offset=0):
            assert agent_id == "default"
            return [dict(entry_pending), dict(entry_done)]

        def find_item(self, knowledge_id):
            if knowledge_id == "k1":
                return ("default", entry_pending)
            return None

        def update_knowledge(self, agent_id, knowledge_id, updates):
            assert updates.get("graph_node_ids") == ["n1", "n2"]
            self.updated = (agent_id, knowledge_id)

    fake_repo = FakeRepo()

    fake_graph = MagicMock()
    fake_graph.search_nodes.return_value = []
    fake_graph.add_node.side_effect = [
        SimpleNamespace(node_id="n1"),
        SimpleNamespace(node_id="n2"),
    ]

    registry(
        {
            "agents": {
                "default": SimpleNamespace(
                    llm_client=_llm_agent(
                        '{"entities": [{"label": "Neurova", "type": "concept"},'
                        ' {"label": "记忆", "type": "entity"}],'
                        ' "relations": [{"source": "Neurova", "target": "记忆", "type": "contains"}]}'
                    ).llm_client,
                    knowledge_graph_manager=fake_graph,
                )
            }
        }
    )
    monkeypatch.setattr(
        "neurova.knowledge.repository.get_knowledge_repository", lambda: fake_repo
    )

    app = FastAPI()
    app.include_router(kg.router, prefix="/api/v1/knowledge-graph")
    app.dependency_overrides[auth.get_current_user_or_service] = lambda: {
        "user_id": "1",
        "role": "user",
    }
    client = TestClient(app)

    resp = client.post("/api/v1/knowledge-graph/default/knowledge-graph/backfill")
    assert resp.status_code == 200, resp.text

    data = resp.json()["data"]
    assert data["entries"] == 1, "只补抽 graph_node_ids 为空的条目"
    assert data["extracted_nodes"] == 2
    assert data["failed"] == 0
    assert fake_repo.updated == ("default", "k1"), "抽取结果必须回写条目"
    assert fake_graph.add_edge.called


def test_backfill_without_llm_reports_reason(registry, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from neurova.api.endpoints import knowledge_graph_api as kg

    registry({"agents": {}})

    app = FastAPI()
    app.include_router(kg.router, prefix="/api/v1/knowledge-graph")
    app.dependency_overrides[auth.get_current_user_or_service] = lambda: {
        "user_id": "1",
        "role": "user",
    }
    client = TestClient(app)

    resp = client.post("/api/v1/knowledge-graph/default/knowledge-graph/backfill")
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["reason"]


# ---------------------------------------------------------------
# R4: 同根因兄弟消费方
# ---------------------------------------------------------------


def test_semantic_search_resolves_runtime_memory_manager_from_registry(
    registry, tmp_path
):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from neurova.api.endpoints import semantic_search_api
    from neurova.cognitive_layers.memory_layer.manager import MemoryManager

    manager = MemoryManager(
        str(tmp_path / "mem.db"), agent_id="a1", neuser_id="n1", user_id="u1"
    )
    manager.remember("用户正在计划九月份去青海湖旅行", memory_type="episodic", category="conversation")
    registry({"agents": {"a1": SimpleNamespace(memory_manager=manager)}})

    app = FastAPI()
    app.include_router(semantic_search_api.router, prefix="/api/v1/semantic-search")
    app.dependency_overrides[auth.get_current_user_or_service] = lambda: {
        "user_id": "u1",
        "username": "u1",
        "role": "user",
        "neuser_id": "n1",
    }
    client = TestClient(app)

    resp = client.post("/api/v1/semantic-search/hybrid", json={"query": "青海湖", "top_k": 5})
    assert resp.status_code == 200, resp.text
    contents = [x["content"] for x in resp.json()["data"]["results"]]
    assert any("青海湖" in c for c in contents), f"应命中运行时 Agent 记忆，实际: {contents}"


def test_enhanced_search_engines_resolved_from_registry(registry):
    from neurova.api.endpoints import enhanced_memory_search_api as ems

    engine = object()
    registry(
        {
            "agents": {
                "a1": SimpleNamespace(memory_agent=SimpleNamespace(recall_engine=engine))
            }
        }
    )
    req = MagicMock()
    req.app.state.agents = {}  # 旧路径恒空，必须改走注册表

    assert ems._get_all_recall_engines(req) == [engine]
