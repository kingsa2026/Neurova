"""记忆 API 路由阴影回归测试

背景 Bug（2026-08-29，前端记忆管理 Hot 分页报 500）：

1. crud.py 中 GET/DELETE ``/{memory_id}`` 先于字面路由 GET ``/hot``、
   GET ``/crystallized`` 注册；memory 包 ``__init__`` 中 crud 又先于
   profile/working_memory 导入 —— 导致 ``/hot``、``/crystallized``、
   ``/self-model``、``/wm``、``/emotion/summary`` 等字面路由全部被
   路径参数路由吞掉（FastAPI 按注册顺序匹配）。
2. ``get_memory`` 等 15 处以 3 个位置参数调用
   ``get_memory_manager(agent_id, neuser_id, user_id)``，而其签名为
   ``(agent_id, user)`` → TypeError。
3. ``APIError`` 是普通 Exception，应用未注册 exception handler →
   Starlette 兜底返回纯文本 500，本应 404 的"记忆不存在"也变成 500。
"""
import pytest
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.endpoints.memory import router as memory_router
from neurova.cognitive_layers.memory_layer.models import Memory
from neurova.interfaces.api_standard import ErrorCodes


# ============================================================
# 测试用 App 构造
# ============================================================


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(memory_router, prefix="/api/v1/memory")
    # 与 create_app 保持一致：注册 APIError 全局处理器
    # （容错导入：handler 模块缺失时仅影响 404 语义测试，不阻塞路由测试）
    try:
        from neurova.api.error_handlers import register_error_handlers

        register_error_handlers(app)
    except ImportError:
        pass
    return app


# ============================================================
# Fake 记忆管理器 / 应用状态
# ============================================================


class _FakeStorage:
    def __init__(self, store):
        self._store = store

    def get(self, memory_id):
        return self._store.get(memory_id)


class _FakeMemoryManager:
    """覆盖被测端点用到的最小接口"""

    def __init__(self):
        self.neuser_id = "default"
        self.user_id = "default"
        self.cleared = False
        self._store = {}
        for i in range(1, 4):
            m = Memory(
                id=f"mem-{i}",
                content=f"hot memory {i}",
                agent_id="agent-1",
                temperature=90.0,
            )
            self._store[f"mem-{i}"] = m.to_dict()

    @property
    def storage(self):
        return _FakeStorage(self._store)

    def get_hot_memories(self, limit=10):
        # 与真实 MemoryManager.recall() 契约一致：返回 Memory.to_dict() 字典列表
        return [self._store[k] for k in list(self._store)[:limit]]

    def get_crystallized(self, limit=20):
        return []

    def get_stats(self):
        return {"total_memories": len(self._store)}

    def get_self_model(self):
        return {"persona": "tester"}

    def wm_clear(self):
        self.cleared = True
        return True

    def forget(self, memory_id):
        if memory_id in self._store:
            self._store.pop(memory_id)
            return True
        return False


class _FakeState:
    def __init__(self, agent):
        self.agents = {"agent-1": agent}

    def get_agent(self):
        return self.agents["agent-1"]


@pytest.fixture
def env(monkeypatch):
    agent = SimpleNamespace(memory_manager=_FakeMemoryManager())
    monkeypatch.setattr("neurova.api.app.get_app_state", lambda: _FakeState(agent))
    return TestClient(_make_app()), agent


# ============================================================
# 结构性测试：字面路由不得被路径参数路由吞掉
# ============================================================


def _first_matching_route(app, path, method):
    """模拟 FastAPI 的路由匹配：按注册顺序返回第一条命中的路由"""
    for route in app.routes:
        if not hasattr(route, "path_regex"):
            continue
        methods = getattr(route, "methods", None) or set()
        if method not in methods:
            continue
        if route.path_regex.fullmatch(path):
            return route
    return None


def test_literal_routes_win_over_param_routes():
    """memory 包内所有字面路由在其已注册的方法上必须被自身路由命中，
    而非被 /{memory_id}、/emotion/{emotion_type} 等参数路由截获"""
    app = _make_app()
    literal_routes = [
        r
        for r in app.routes
        if getattr(r, "path", "").startswith("/api/v1/memory")
        and "{" not in getattr(r, "path", "")
        and getattr(r, "methods", None)
    ]
    assert literal_routes, "memory 路由未注册"

    shadowed = []
    for route in literal_routes:
        for method in route.methods:
            matched = _first_matching_route(app, route.path, method)
            if matched is not None and matched.path != route.path:
                shadowed.append(f"{method} {route.path} -> {matched.path}")
    assert not shadowed, f"字面路由被路径参数路由吞掉: {shadowed}"


# ============================================================
# 行为测试：被阴影的端点恢复正常语义
# ============================================================


def test_get_hot_memories_returns_200(env):
    client, _ = env
    resp = client.get("/api/v1/memory/hot", params={"agent_id": "agent-1", "limit": 2})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["code"] == 0
    assert body["data"]["count"] == 2
    first = body["data"]["memories"][0]
    assert first["id"] == "mem-1"
    # recall() 返回 dict，memory_to_dict 必须能取到内容而非空串
    assert first["content"] == "hot memory 1"
    assert first["temperature"] == 90.0


def test_memory_to_dict_accepts_recall_dict():
    """manager.recall() 返回 Memory.to_dict() 字典；序列化不得产出全空记录"""
    from neurova.api.endpoints.memory.base import memory_to_dict

    m = Memory(
        id="mem-9",
        content="hello world",
        agent_id="agent-1",
        temperature=88.0,
        importance=90.0,
    )
    out = memory_to_dict(m.to_dict())
    assert out["id"] == "mem-9"
    assert out["content"] == "hello world"
    assert out["agent_id"] == "agent-1"
    assert out["temperature"] == 88.0
    assert out["is_important"] is True
    assert out["created_at"]  # 非空
    assert out["last_accessed_at"] == ""  # None → 空串而非 "None"


def test_get_crystallized_memories_returns_200(env):
    client, _ = env
    resp = client.get("/api/v1/memory/crystallized", params={"agent_id": "agent-1"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["code"] == 0
    assert body["data"]["count"] == 0


def test_get_self_model_returns_200(env):
    client, _ = env
    resp = client.get("/api/v1/memory/self-model", params={"agent_id": "agent-1"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["code"] == 0
    assert body["data"] == {"persona": "tester"}


def test_delete_wm_returns_200(env):
    client, agent = env
    resp = client.delete("/api/v1/memory/wm", params={"agent_id": "agent-1"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["code"] == 0
    assert agent.memory_manager.cleared is True


def test_get_memory_stats_returns_200(env):
    client, _ = env
    resp = client.get("/api/v1/memory/stats", params={"agent_id": "agent-1"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["total_memories"] == 3


def test_get_emotion_types_returns_200():
    """/emotion/types 不得因导入不存在的 EMOTION_WEIGHTS 而 500"""
    client = TestClient(_make_app())
    resp = client.get("/api/v1/memory/emotion/types")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    types = body["data"]["emotion_types"]
    assert body["data"]["count"] == len(types) > 0
    assert {"type", "layer", "category"} <= set(types[0].keys())


def test_get_memory_detail_returns_200(env):
    client, _ = env
    resp = client.get("/api/v1/memory/mem-1", params={"agent_id": "agent-1"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["data"]["id"] == "mem-1"
    assert body["data"]["content"] == "hot memory 1"


def test_delete_memory_detail_returns_200(env):
    client, agent = env
    resp = client.delete("/api/v1/memory/mem-2", params={"agent_id": "agent-1"})
    assert resp.status_code == 200, resp.text
    assert "mem-2" not in agent.memory_manager._store


# ============================================================
# APIError 全局处理：业务错误不再变成纯文本 500
# ============================================================


def test_get_unknown_memory_returns_structured_404(env):
    client, _ = env
    resp = client.get("/api/v1/memory/does-not-exist", params={"agent_id": "agent-1"})
    assert resp.status_code == 404, resp.text
    body = resp.json()
    assert body["code"] == ErrorCodes.NOT_FOUND
    assert "does-not-exist" in body["message"]


def test_delete_unknown_memory_returns_structured_404(env):
    client, _ = env
    resp = client.delete("/api/v1/memory/does-not-exist", params={"agent_id": "agent-1"})
    assert resp.status_code == 404, resp.text
    assert resp.json()["code"] == ErrorCodes.NOT_FOUND
