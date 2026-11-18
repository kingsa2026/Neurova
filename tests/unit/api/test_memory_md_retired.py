# -*- coding: utf-8 -*-
"""MEMORY.md 人机共编层退役契约（2026-11-18 用户拍板）。

裁定依据：Neurova 已有宪法/人格（定义面常驻注入）+ memories 表温度生命周期
（机器写入过 admission、人写走 pending_memories 候选审阅）；蒸馏回写已裁定
进记忆温度体系而非 markdown 文件。MEMORY.md 成为无 UI、无自动写方的潜伏层，
按"无消费面模块必须接线或删除"退役。

本契约钉住退役后的形态：
1. 存取模块不复存在；
2. console 读写端点不复存在（404，而非 401/403——路由已删，鉴权无从谈起）；
3. build_context 不再消费 memoryMdContextLines（注入面清除）。
"""

import importlib.util
import inspect

import pytest
from fastapi.testclient import TestClient

from neurova.api.app import create_app
from neurova.api.auth import create_access_token

MD_BASE = "/api/v1/console/memory_md"


def _headers(role: str = "admin", name: str = "user-a") -> dict:
    token = create_access_token({"sub": name, "username": name, "role": role,
                                 "neuser_id": f"ne-{name}"})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path))
    app = create_app()
    yield TestClient(app)


def test_memory_md_module_removed():
    assert importlib.util.find_spec("neurova.memory.memory_md") is None, (
        "neurova.memory.memory_md 应已退役删除（用户 2026-11-18 拍板）"
    )


def test_memory_md_endpoints_removed(client):
    get_resp = client.get(MD_BASE, params={"agent_id": "default"}, headers=_headers())
    assert get_resp.status_code == 404, f"GET 应 404（路由已删），实际 {get_resp.status_code}"
    put_resp = client.put(MD_BASE, json={"agent_id": "default", "content": "x"},
                          headers=_headers())
    assert put_resp.status_code == 404, f"PUT 应 404（路由已删），实际 {put_resp.status_code}"


def test_build_context_no_longer_consumes_memory_md():
    from neurova.context import orchestrator

    source = inspect.getsource(orchestrator.ContextOrchestrator.build_context)
    assert "memoryMdContextLines" not in source, (
        "build_context 不应再消费 memoryMdContextLines（MEMORY.md 注入面已退役）"
    )
