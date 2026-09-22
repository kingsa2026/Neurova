# -*- coding: utf-8 -*-
"""`POST /v1/memory/reload`：让运行中的后端看见别的进程写下的记忆（F-05）。

红灯依据（Issue #81 / F-05 后半，用户拍板"开 HTTP 端点 / 加 reload_memories 入口"）：

记忆快照只在进程构造时读一次盘，于是 CLI 在另一个进程导入的记忆，对运行中的
服务一条都看不见——CLI 此前只能靠一句"需后端重启后才可见"诚实暴露，用户没有
不重启就看见的路。本端点就是那条路：它调 `MemoryManager.reload_memories()`
增量并入缺失行，并**只**报真实并入的条数。

锁定的判据：

1. 端点存在且挂在 `/api/v1/memory` 下（与 `/v1/memory` 同一装配点、同一鉴权口径）；
2. 外来行并入后，紧接着的 `GET /v1/memory` 就能读到（写→读→反馈闭环）；
3. 幂等：再调一次报 0，不重复装载；
4. 路由顺序：`/reload` 是字面路由，不能被 `/{memory_id}` 吞掉（吞掉就变成
   "获取 memory_id=reload 的记忆" → 404，这正是此前 `/hot`、`/stats` 栽过的同一个坑）。
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.auth import get_current_user_or_default
from neurova.api.endpoints import memory as memory_pkg


@pytest.fixture()
def manager(tmp_path):
    from neurova.cognitive_layers.memory_layer.manager import MemoryManager

    return MemoryManager(
        db_path=str(tmp_path / "mem" / "memory.db"),
        agent_id="reload-agent",
        enable_buffer=False,
    )


@pytest.fixture()
def client(manager, monkeypatch):
    """挂真 router + 真 manager：走生产装配点 `get_app_state()`，不绕开取值路径。"""
    class _FakeAgent:
        memory_manager = manager

    class _FakeState:
        agents = {"reload-agent": _FakeAgent()}

        def get_agent(self, agent_id=None):
            return self.agents.get(agent_id or "reload-agent")

    # `get_memory_manager` 内部是函数级 import，故打在它的源模块上
    import neurova.api.app as app_module

    monkeypatch.setattr(app_module, "get_app_state", lambda: _FakeState())

    app = FastAPI()
    app.include_router(memory_pkg.router, prefix="/v1/memory")
    app.dependency_overrides[get_current_user_or_default] = lambda: {
        "username": "tester", "role": "admin",
        "neuser_id": "default", "user_id": "default",
    }
    yield TestClient(app)
    app.dependency_overrides.clear()


def _foreign_write(manager, content: str):
    """另一个进程往同一份库写一条（CLI 导入的真实形态）；返回该写者供撤销使用。"""
    from neurova.cognitive_layers.memory_layer.manager import MemoryManager
    from neurova.memory_ingest.bundle.records import MemoryRecord

    writer = MemoryManager(db_path=manager._persist_db_path, agent_id="reload-agent",
                           enable_buffer=False)
    writer.import_memories(
        [MemoryRecord(identity_key="ik-http-1", content=content, memory_type="semantic",
                      category="general", origin="owner", importance=60.0,
                      ts="2026-05-01T10:00:00+00:00")],
        ingest_run_id="nvimp-http-1")
    return writer


def test_reload_route_is_not_swallowed_by_the_memory_id_route(client):
    """`/reload` 必须是字面路由：被 `/{memory_id}` 吞掉就只剩 404。"""
    resp = client.post("/v1/memory/reload")
    assert resp.status_code == 200, (
        f"POST /v1/memory/reload 返回 {resp.status_code}（预期 200）——"
        "多半是字面路由注册晚于 crud 的 /{memory_id}，被当成 memory_id='reload' 了"
    )


def test_reload_makes_a_foreign_row_visible_to_the_next_read(client, manager):
    _foreign_write(manager, "另一个进程导入的记忆锚点")

    before = client.get("/v1/memory", params={"limit": 100}).json()
    assert "另一个进程导入的记忆锚点" not in str(before), (
        "不 reload 就看见了外来行——判据失效"
    )

    reloaded = client.post("/v1/memory/reload")
    assert reloaded.status_code == 200, reloaded.text
    assert reloaded.json()["data"]["reloaded"] == 1, reloaded.json()

    after = client.get("/v1/memory", params={"limit": 100}).json()
    assert "另一个进程导入的记忆锚点" in str(after), (
        "reload 之后紧跟的 GET /v1/memory 仍读不到——闭环没接上"
    )


def test_reload_reaps_a_row_that_another_process_undid(client, manager):
    """断点①的端点面：另一进程撤销后 reload 要回收，列表里那条不能再"还在"。"""
    from neurova.cognitive_layers.memory_layer.manager import MemoryManager

    writer = _foreign_write(manager, "待撤销的锚点")
    assert client.post("/v1/memory/reload").json()["data"]["reloaded"] == 1

    writer.delete_ingested_memories("nvimp-http-1")   # 另一进程撤销：盘上行已删
    writer.close()

    reaped = client.post("/v1/memory/reload").json()["data"]

    assert reaped["reaped"] == 1, reaped
    assert "待撤销的锚点" not in str(client.get("/v1/memory", params={"limit": 100}).json())


def test_reload_is_idempotent(client, manager):
    _foreign_write(manager, "幂等锚点")

    first = client.post("/v1/memory/reload").json()["data"]["reloaded"]
    second = client.post("/v1/memory/reload").json()["data"]["reloaded"]

    assert (first, second) == (1, 0)
