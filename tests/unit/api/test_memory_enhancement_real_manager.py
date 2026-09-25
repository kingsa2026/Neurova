# -*- coding: utf-8 -*-
"""记忆增强端点必须写/读真 MemoryManager，不得落进程内影子字典。

红灯依据（Issue #128 / 构建 cnb-3k8-1k33gorhr 未完成的 F-17 议题）：

`neurova/api/endpoints/memory_enhancement.py` 维护了一份模块级
`_memories_store: Dict[str, Dict[str, Any]] = {}`，六条端点（forget /
strengthen / categories / batch / export / import）全部以它为事实源。
该字典进程内创建、从不被任何生产写入路径填充，也不会被读取侧看到 ——
于是「导入成功」「遗忘成功」都是假成功：返回 200 + 计数，真记忆库纹丝不动。

本测试锁定三条判据：
1. 导入一条记忆后，真 MemoryManager 里必须能查到（写入闭环）；
2. 导出必须回读真 MemoryManager（读取闭环，不得只吐影子字典）；
3. 对不存在于真库的 memory_id 调 forget，必须诚实 404，
   不得因为影子字典里「找不到」就换个语义蒙混，也不得凭空造一条。
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.auth import get_current_user


@pytest.fixture()
def manager(tmp_path):
    from neurova.cognitive_layers.memory_layer.manager import MemoryManager

    return MemoryManager(
        db_path=str(tmp_path / "mem.db"),
        agent_id="agent-under-test",
        neuser_id="neuser-under-test",
        user_id="user-under-test",
        enable_buffer=False,
    )


@pytest.fixture()
def client(manager, monkeypatch):
    """把真 MemoryManager 挂进 AppState，命中原装配点 get_app_state()。"""
    from neurova.api.endpoints import memory_enhancement

    class _FakeAgent:
        memory_manager = manager

    class _FakeState:
        agents = {"agent-under-test": _FakeAgent()}

        def get_agent(self, agent_id=None):
            return self.agents.get(agent_id or "agent-under-test")

    # 命中原装配点：get_memory_manager 内部是函数级 import，
    # 故必须打在 its 源模块 neurova.api.app 上，打在本模块无用。
    import neurova.api.app as app_module

    monkeypatch.setattr(app_module, "get_app_state", lambda: _FakeState())

    app = FastAPI()

    @app.middleware("http")
    async def _inject_user(request, call_next):
        request.state.user = {
            "neuser_id": "neuser-under-test",
            "user_id": "user-under-test",
        }
        return await call_next(request)

    app.include_router(memory_enhancement.router, prefix="/v1/memory-enhancement")
    app.dependency_overrides[get_current_user] = lambda: {
        "username": "tester",
        "role": "admin",
        "neuser_id": "neuser-under-test",
        "user_id": "user-under-test",
    }
    yield TestClient(app)
    app.dependency_overrides.clear()


def _seed(manager, content: str):
    """经真 manager 的写入路径落一条记忆，返回其 id。"""
    manager.set_request_scope(neuser_id="neuser-under-test", user_id="user-under-test")
    return manager.remember(content=content, origin="owner")


def test_import_lands_in_real_manager(client, manager):
    """导入必须真落到 MemoryManager，而不是只回一个 imported 计数。"""
    resp = client.post(
        "/v1/memory-enhancement/import",
        json={"memories": [{"content": "导入进来的记忆锚点", "type": "episodic"}]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["data"]["imported"] == 1, body

    manager.set_request_scope(neuser_id="neuser-under-test", user_id="user-under-test")
    contents = [m["content"] for m in manager.get_memories(agent_wide=True, limit=100)]
    assert "导入进来的记忆锚点" in contents, (
        "导入返回成功但真 MemoryManager 里查不到该记忆 —— 写入了影子字典"
    )


def test_export_reads_real_manager(client, manager):
    """导出必须回读真 MemoryManager；真库非空时导出不得为空。"""
    _seed(manager, "真库里已有的记忆")

    resp = client.get("/v1/memory-enhancement/export")
    assert resp.status_code == 200, resp.text
    payload = resp.json()["data"]
    rendered = str(payload)
    assert "真库里已有的记忆" in rendered, (
        "导出数据里没有真库的内容 —— 读的是影子字典，读路径断链"
    )


def test_forget_missing_memory_is_honest_404(client):
    """不存在的记忆必须 404，不得凭空造一条影子记录再报成功。"""
    resp = client.post(
        "/v1/memory-enhancement/definitely-absent/forget", json={"reason": "test"}
    )
    assert resp.status_code == 404, (
        f"对真库中不存在的记忆 forget 返回 {resp.status_code}，应为 404；"
        "影子字典在替真库「兜底」"
    )


def test_strengthen_missing_memory_is_honest_404(client):
    resp = client.post(
        "/v1/memory-enhancement/definitely-absent/strengthen",
        json={"importance_boost": 0.2},
    )
    assert resp.status_code == 404, f"应为 404，实得 {resp.status_code}"


def test_strengthen_raises_importance_in_real_manager(client, manager):
    mid = _seed(manager, "待强化的记忆")
    manager.set_request_scope(neuser_id="neuser-under-test", user_id="user-under-test")
    before = manager.get_memory(mid, agent_wide=True)["importance"]

    resp = client.post(
        f"/v1/memory-enhancement/{mid}/strengthen",
        json={"importance_boost": 0.2},
    )
    assert resp.status_code == 200, resp.text

    manager.set_request_scope(neuser_id="neuser-under-test", user_id="user-under-test")
    after = manager.get_memory(mid, agent_wide=True)["importance"]
    assert after > before, f"强化后 importance 未变化: {before} → {after}"


def test_forget_marks_forgotten_in_real_manager(client, manager):
    mid = _seed(manager, "待遗忘的记忆")

    resp = client.post(f"/v1/memory-enhancement/{mid}/forget", json={"reason": "test"})
    assert resp.status_code == 200, resp.text

    manager.set_request_scope(neuser_id="neuser-under-test", user_id="user-under-test")
    got = manager.get_memory(mid, agent_wide=True)
    assert got is not None, "真库中该记忆不见了（被硬删）"
    assert got["lifecycle_stage"] == "forgotten", (
        f"forget 未落到真库 lifecycle_stage，实得 {got['lifecycle_stage']}"
    )


def test_no_phantom_store_writes_on_import(client):
    """证据判据：导入后影子字典必须仍为空 —— 说明根本没用它。"""
    from neurova.api.endpoints import memory_enhancement as mod

    client.post(
        "/v1/memory-enhancement/import",
        json={"memories": [{"content": "锚点 B", "type": "episodic"}]},
    )
    assert not getattr(mod, "_memories_store", {}), (
        "导入写进了进程内影子字典 _memories_store —— 第二事实源仍在"
    )
