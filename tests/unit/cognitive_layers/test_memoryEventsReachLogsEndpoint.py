# -*- coding: utf-8 -*-
"""A3b（§6-12 收口）：记忆写入必须能在**现役 HTTP 读面**上看到，而不是只"发出去了"。

A3a 把两份总线合成一份后，`manager.py` 的 MEMORY_* 第一次抵达共享总线；而共享总线的
事件日志正是 `api/endpoints/logs.py:72` 读的那份，前端在
`NeurUI/src/api/modules/system-logs.ts:29` + `config/navigation.ts:73` 有真实入口。
所以"写了没人读"这一格是被**这条回路**关掉的，不是靠新造一个订阅者。

为什么不接"记忆变更→清上下文缓存"（本批一度想做的形态）：实测
`UnifiedContextInjector.cache_entry`(:1103) 与 `get_cached_entry`(:1115) **全仓零调用方**
（`neurova/` 与 `tests/` 都无人调），即那张 LRU `_cache`(:135) 既不写也不读。把事件接到
"清一张恒空的表"上，绿灯会亮、闭环并不存在——属教义第 2 条禁止的表面抹除，已撤回，
该格另登记为产品裁决项（见台账 §6-51）。

判据两条：① 真 `remember()` 之后，`GET /api/v1/logs` 的返回里必须出现 `memory_created`
（写入→总线→日志→HTTP 读面全链，缺任一环即红）；② 同一条事件带 `source="memory_manager"`
与 `memory_id`，否则读面上无法归因是哪个域发的。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from neurova.core.event_bus import get_event_bus, reset_event_bus


@pytest.fixture
def app_and_client(tmp_path, monkeypatch):
    """真装配 + 真 JWT + 隔离数据根（不 monkeypatch 身份门）。"""
    reset_event_bus()
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path / "nvdata"))

    from neurova.api.app import create_app
    from neurova.api.auth import create_access_token

    client = TestClient(create_app())
    token = create_access_token(data={"sub": "memory-loop-probe-user"})
    yield client, {"Authorization": f"Bearer {token}"}
    reset_event_bus()


@pytest.fixture
def manager(tmp_path):
    from neurova.cognitive_layers.memory_layer.manager import MemoryManager

    return MemoryManager(db_path=str(tmp_path / "mem.db"), agent_id="agent_a")


def testMemoryWriteIsVisibleOnLogsEndpoint(app_and_client, manager):
    """① 写入 → 共享总线 → 事件日志 → `GET /api/v1/logs`，端到端必须闭合。"""
    client, headers = app_and_client

    manager.remember("总线上这一发要能被 HTTP 读面看到", category="fact", importance=0.7)

    resp = client.get("/api/v1/logs?limit=200", headers=headers)
    assert resp.status_code == 200, f"读面本身不通：{resp.status_code} {resp.text[:120]}"

    body = resp.json()
    names = [str(item) for item in (body if isinstance(body, list) else [body])]
    hits = [n for n in names if "memory_created" in n]
    assert hits, (
        f"`GET /api/v1/logs` 里看不到 memory_created（共 {len(names)} 条）——"
        "记忆事件又回到了「发了没人读」：要么 manager 仍在往私有总线发，"
        "要么日志读面接的不是同一条总线"
    )


def testMemoryEventCarriesAttribution(app_and_client, manager):
    """② 事件必须带来源与记忆 id，否则读面上只是一条无名记录，无法归因。"""
    client, headers = app_and_client
    bus = get_event_bus()

    seen = []
    bus.subscribe("memory_created", lambda event: seen.append(event))
    manager.remember("带归属的一发", category="fact", importance=0.6)

    assert seen, "共享总线上没收到这条事件"
    event = seen[-1]
    assert event.source == "memory_manager", f"来源缺失：{event.source!r}"
    assert event.data.get("memory_id"), "载荷没有 memory_id，读面上认不出是哪条记忆"
    assert event.data.get("content") == "带归属的一发"
