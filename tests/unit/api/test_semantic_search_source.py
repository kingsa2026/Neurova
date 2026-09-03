"""semantic_search_api 数据源分裂回归测试（TDD）

修复前：所有端点经模块级单例 get_memory_manager() 检索——与运行时 Agent
的 MemoryManager（per-agent persist.db + 内存索引）不是同一对象，
导致 API 永远查不到聊天产生的记忆（断点 S1）。
修复后：优先解析 request.app.state.agents 中活跃 Agent 的 memory_manager，
无活跃 Agent 时才降级到单例。
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def clients(tmp_path):
    from neurova.api import auth as semantic_auth
    from neurova.api.endpoints import semantic_search_api
    from neurova.cognitive_layers.memory_layer.manager import MemoryManager

    manager = MemoryManager(str(tmp_path / "mem.db"), agent_id="a1", neuser_id="n1", user_id="u1")
    manager.remember("用户正在计划九月份去青海湖旅行", memory_type="episodic", category="conversation")

    agent = MagicMockLike = type("AgentStub", (), {"memory_manager": manager})()

    def _make(app_agents: dict):
        app = FastAPI()
        app.state.agents = app_agents
        # 批次 2：检索端点接入 JWT 鉴权——测试注入固定身份
        app.dependency_overrides[semantic_auth.get_current_user_or_service] = lambda: {
            "user_id": "u1",
            "username": "u1",
            "role": "user",
            "neuser_id": "n1",
        }
        app.include_router(semantic_search_api.router, prefix="/api/v1/semantic-search")
        return TestClient(app)

    return _make({}), _make({"a1": agent})


def test_hybrid_search_finds_runtime_agent_memories(clients):
    """运行时 Agent 的记忆必须可被语义混合检索命中"""
    empty_client, runtime_client = clients
    body = {"query": "青海湖", "top_k": 5}

    # 单例降级路径：查不到（不报错即可）
    r0 = empty_client.post("/api/v1/semantic-search/hybrid", json=body)
    assert r0.status_code == 200

    # 运行时路径：必须命中
    r1 = runtime_client.post("/api/v1/semantic-search/hybrid", json=body)
    assert r1.status_code == 200, r1.text
    contents = [x["content"] for x in r1.json()["data"]["results"]]
    assert any("青海湖" in c for c in contents), f"应命中聊天记忆，实际: {contents}"


def test_bm25_search_uses_runtime_agent_manager(clients):
    _, runtime_client = clients
    r = runtime_client.post(
        "/api/v1/semantic-search/bm25", json={"query": "旅行 计划", "top_k": 5}
    )
    assert r.status_code == 200
    contents = [x["content"] for x in r.json()["data"]["results"]]
    assert any("青海湖" in c for c in contents)
