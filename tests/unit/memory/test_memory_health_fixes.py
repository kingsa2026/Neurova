"""记忆系统体检修复的回归测试（TDD）

1. GET /api/v1/context/inject/memories 曾调用不存在的
   MemoryManager.search()/get_recent() → 必然 AttributeError → HTTP 500。
   修复后应映射到真实方法：search_memories()/get_hot_memories()。
2. UnifiedVectorStore._select_backend('auto') 的探测体曾被剥空成
   `try: pass; return "faiss"` → 无条件选 faiss，本地 ONNX 模型即使存在
   也永远降级 TF-IDF。修复后应按 faiss→fastembed→onnx→tfidf 真实探测。
"""

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ----------------------------- /inject/memories -----------------------------


@pytest.fixture
def client():
    from neurova.api.endpoints import context as context_api

    agent = MagicMock()
    agent.memory_manager.search_memories = MagicMock(return_value=[{"id": "m1", "content": "命中"}])
    agent.memory_manager.get_hot_memories = MagicMock(return_value=[{"id": "m2", "content": "高温"}])
    # 防御: 旧坏代码调用的方法不应再出现
    del agent.memory_manager.search
    del agent.memory_manager.get_recent

    def _get_agent(agent_id="default"):
        return agent if agent_id == "default" else None

    app = FastAPI()
    app.include_router(context_api.router, prefix="/api/v1/context")
    client = TestClient(app)
    client._probe_agent = agent  # type: ignore[attr-defined]
    import neurova.api.endpoints.context as ctx_mod

    monkey_patch = pytest.MonkeyPatch()
    monkey_patch.setattr(ctx_mod, "_get_agent", _get_agent)
    yield client
    monkey_patch.undo()


def test_inject_memories_with_query_uses_search_memories(client):
    resp = client.get("/api/v1/context/inject/memories", params={"query": "测试", "limit": 5})
    assert resp.status_code == 200, f"应 200，实际 {resp.status_code}: {resp.text}"
    data = resp.json()["data"]
    assert data["count"] == 1
    client._probe_agent.memory_manager.search_memories.assert_called_once_with(query="测试", limit=5)


def test_inject_memories_without_query_uses_hot_memories(client):
    resp = client.get("/api/v1/context/inject/memories", params={"limit": 3})
    assert resp.status_code == 200, f"应 200，实际 {resp.status_code}: {resp.text}"
    data = resp.json()["data"]
    assert data["count"] == 1
    client._probe_agent.memory_manager.get_hot_memories.assert_called_once()


# ----------------------------- 向量后端探测 -----------------------------


class TestVectorBackendSelection:
    def test_auto_never_returns_faiss_without_import(self):
        """faiss 未安装时 auto 不得返回 'faiss'（探测体被剥空的回归）"""
        from neurova.cognitive_layers.memory_layer.unified_vector_store import UnifiedVectorStore

        try:
            import faiss  # noqa: F401

            pytest.skip("faiss 已安装，无法模拟缺失")
        except ImportError:
            pass

        backend = UnifiedVectorStore(backend="auto").backend
        assert backend != "faiss", "_select_backend 探测体为空，无条件返回 faiss"

    def test_explicit_backend_respected(self):
        from neurova.cognitive_layers.memory_layer.unified_vector_store import UnifiedVectorStore

        store = UnifiedVectorStore(backend="tfidf")
        assert store.backend == "tfidf"


# ----------------------------- Memory 序列化往返 -----------------------------


class TestMemorySharedRoundtrip:
    def test_shared_flag_survives_to_dict_from_dict(self):
        """共享标记必须穿越 to_dict/from_dict（from_dict 重建上下文时曾丢失 shared）"""
        from neurova.cognitive_layers.memory_layer.isolation import IsolationContext
        from neurova.cognitive_layers.memory_layer.models import Memory, MemoryType

        ctx = IsolationContext(agent_id="agent_1", shared=True)
        memory = Memory(content="共享记忆", memory_type=MemoryType.SEMANTIC, isolation_context=ctx)

        assert memory.shared is True
        data = memory.to_dict()
        restored = Memory.from_dict(data)
        assert restored.shared is True, "from_dict 重建 IsolationContext 时不得丢失 shared"
        assert restored.agent_id == "agent_1"

    def test_share_group_ids_survive_roundtrip(self):
        from neurova.cognitive_layers.memory_layer.isolation import IsolationContext
        from neurova.cognitive_layers.memory_layer.models import Memory, MemoryType

        ctx = IsolationContext(
            agent_id="agent_1", shared=True, share_group_ids=("grp_a", "grp_b")
        )
        memory = Memory(content="群组共享", memory_type=MemoryType.SEMANTIC, isolation_context=ctx)

        data = memory.to_dict()
        restored = Memory.from_dict(data)
        assert set(restored.share_group_ids) >= {"grp_a", "grp_b"}
