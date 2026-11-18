"""QwenPaw 对照批 B2：人机共编长期记忆 MEMORY.md。

- 存取模块：读（缺文件=空串）/写（截断上界）/注入段格式；
- console 端点：GET/PUT /console/memory_md（requireAgentOwner 门）；
- 注入接线：orchestrator.build_context 的 system 段必须消费
  memoryMdContextLines（接线被删即源码断言红）。
"""

import pytest
from fastapi.testclient import TestClient
from types import SimpleNamespace

from neurova.api.app import create_app
from neurova.api.auth import create_access_token
from neurova.memory.memory_md import (
    memoryMdContextLines,
    memoryMdPath,
    readMemoryMd,
    writeMemoryMd,
)

MD_BASE = "/api/v1/console/memory_md"


def _headers(role: str = "admin", name: str = "user-a") -> dict:
    token = create_access_token({"sub": name, "username": name, "role": role,
                                 "neuser_id": f"ne-{name}"})
    return {"Authorization": f"Bearer {token}"}


class TestMemoryMdModule:

    def test_read_missing_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path))
        assert readMemoryMd("agent-x") == ""

    def test_write_then_read_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path))
        writeMemoryMd("agent-x", "用户偏好简洁回复")
        assert readMemoryMd("agent-x") == "用户偏好简洁回复"
        assert memoryMdPath("agent-x").name == "MEMORY.md"

    def test_context_lines_empty_when_absent(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path))
        assert memoryMdContextLines("agent-x") == []

    def test_context_lines_format_when_present(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path))
        writeMemoryMd("agent-x", "长期事实一条")
        lines = memoryMdContextLines("agent-x")
        assert len(lines) == 2 and "长期记忆" in lines[0] and lines[1] == "长期事实一条"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path))
    app = create_app()
    yield TestClient(app)


class TestEndpoint:

    def test_get_empty_then_put_roundtrip(self, client):
        r = client.get(MD_BASE, params={"agent_id": "default"}, headers=_headers())
        assert r.status_code == 200 and r.json()["data"]["content"] == ""

        r = client.put(MD_BASE, json={"agent_id": "default",
                                      "content": "用户偏好：先给结论"}, headers=_headers())
        assert r.status_code == 200

        r = client.get(MD_BASE, params={"agent_id": "default"}, headers=_headers())
        assert r.json()["data"]["content"] == "用户偏好：先给结论"

    def test_put_requires_admin(self, client):
        r = client.put(MD_BASE, json={"agent_id": "default", "content": "x"},
                       headers=_headers(role="user"))
        assert r.status_code == 403

    def test_get_requires_admin(self, client):
        r = client.get(MD_BASE, params={"agent_id": "default"},
                       headers=_headers(role="user"))
        assert r.status_code == 403


def test_injection_wiring_in_build_context():
    import inspect

    from neurova.context import orchestrator

    source = inspect.getsource(orchestrator.ContextOrchestrator.build_context)
    assert "memoryMdContextLines" in source, (
        "build_context 必须消费 memoryMdContextLines（人机共编记忆注入）——接线被删即红"
    )
