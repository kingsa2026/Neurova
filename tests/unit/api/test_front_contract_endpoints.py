"""前端契约断链补齐的后端端点（Issue #68 收口）。

根因（把报错恢复原状就会复现）：`docs/09-dev-progress/api_inventory.md` 第四节把
28 处「前端调用 ↔ 后端注册」差异写成「由人去核」——只登记、不裁决。其中有活跃
消费者的一类（页面按钮点下去必失败）实测全是 404/405：

- `PUT /api/v1/memory/{id}`      —— MemoryPage 的「编辑内容」（此前 405）
- `GET /api/v1/files/{id}/content` —— FilePage/AgentFilePage 文本预览（此前 404）
- `POST /api/v1/settings/clear-cache` —— SettingPage 存储页「清缓存」（此前 405）
- `PUT` 之外：`/knowledge/annotations*` 迁入知识域（此前 404，见
  test_knowledge_annotations_contract.py）

本文件钉死这些端点的存在性 + 行为契约，与 `tests/unit/frontContractBaseline.txt`
的裁决台账同源咬合（守卫见 `test_route_mount_contract_guard.py::TestFrontContractBreaks*`）。
"""
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_front_contract_01")

from neurova.api.auth import get_current_user_or_default
from neurova.api.endpoints.memory import crud as memory_crud
from neurova.api.endpoints.memory.crud import router as memory_router
from neurova.cognitive_layers.memory_layer.models import Memory


def _client(router, prefix, **overrides):
    from neurova.api.auth import get_current_user as _auth_user
    from neurova.api.deps import get_current_user as _deps_user
    app = FastAPI()
    from neurova.api.error_handlers import register_error_handlers
    register_error_handlers(app)
    app.include_router(router, prefix=prefix)
    identity = {"user_id": "u1", "neuser_id": "u1", "agent_id": "a1"}
    for dep in (get_current_user_or_default, _auth_user, _deps_user):
        app.dependency_overrides[dep] = lambda: identity
    app.dependency_overrides.update(overrides)
    return TestClient(app, raise_server_exceptions=False)


# ── memory PUT ──────────────────────────────────────────────────────────


class TestMemoryUpdateEndpoint:
    def test_put_route_exists(self):
        routes = {(r.path, m) for r in memory_router.routes
                  for m in (getattr(r, "methods", None) or ())}
        assert ("/{memory_id}", "PUT") in routes, (
            "PUT /{memory_id} 未注册——MemoryPage 的编辑按钮必 405"
        )

    def test_put_updates_content_and_returns_entry(self, monkeypatch):
        mem = Memory(id="m1", agent_id="a1", content="old", metadata={})

        class _Storage:
            def get(self, mid):
                return mem.to_dict() if mid == "m1" else None

        class _Mgr:
            storage = _Storage()

            def update_memory(self, mid, **kw):
                if mid != "m1":
                    return False
                if "content" in kw:
                    mem.content = kw["content"]
                return True

        client = _client(memory_router, "/mem")
        monkeypatch.setattr(memory_crud, "get_memory_manager", lambda aid, u: _Mgr())
        r = client.put("/mem/m1", json={"content": "new"})
        assert r.status_code == 200, r.text
        assert r.json()["data"]["content"] == "new"

    def test_put_missing_returns_404(self, monkeypatch):
        class _Mgr:
            storage = Mock(get=Mock(return_value=None))

            def update_memory(self, mid, **kw):
                return False

        client = _client(memory_router, "/mem")
        monkeypatch.setattr(memory_crud, "get_memory_manager", lambda aid, u: _Mgr())
        r = client.put("/mem/ghost", json={"content": "x"})
        assert r.status_code == 404, r.text

    def test_put_empty_body_is_422(self, monkeypatch):
        class _Mgr:
            storage = Mock()

            def update_memory(self, mid, **kw):  # pragma: no cover - 不应到达
                raise AssertionError("空 body 不得触达 manager")

        client = _client(memory_router, "/mem")
        monkeypatch.setattr(memory_crud, "get_memory_manager", lambda aid, u: _Mgr())
        r = client.put("/mem/m1", json={})
        assert r.status_code == 422, r.text


# ── files content ────────────────────────────────────────────────────────


class TestFileContentEndpoint:
    def test_content_route_exists(self):
        from neurova.api.endpoints.files_api import router
        routes = {(r.path, m) for r in router.routes
                  for m in (getattr(r, "methods", None) or ())}
        assert ("/{file_id}/content", "GET") in routes, (
            "GET /{file_id}/content 未注册——FilePage 文本预览必 404"
        )

    def test_content_returns_utf8_text(self, tmp_path):
        from neurova.api.endpoints import files_api
        target = tmp_path / "note.txt"
        target.write_text("hello 世界", encoding="utf-8")
        files_api._files_store["f1"] = {
            "file_id": "f1", "filename": "note.txt", "path": str(target),
            "mime_type": "text/plain", "user_id": "u1",
        }
        client = _client(files_api.router, "/files")
        r = client.get("/files/f1/content")
        assert r.status_code == 200, r.text
        assert r.json()["content"] == "hello 世界"
        files_api._files_store.pop("f1", None)

    def test_content_on_binary_is_415_not_silent_empty(self, tmp_path):
        from neurova.api.endpoints import files_api
        target = tmp_path / "bin.dat"
        target.write_bytes(b"\xff\xfe\x00\x01")
        files_api._files_store["f2"] = {
            "file_id": "f2", "filename": "bin.dat", "path": str(target),
            "mime_type": "application/octet-stream", "user_id": "u1",
        }
        client = _client(files_api.router, "/files")
        r = client.get("/files/f2/content")
        assert r.status_code == 415, r.text
        files_api._files_store.pop("f2", None)


# ── settings clear-cache ─────────────────────────────────────────────────


class TestSettingsClearCacheEndpoint:
    def test_clear_cache_route_exists_before_key_route(self):
        from neurova.api.endpoints import settings as settings_mod
        paths = [r.path for r in settings_mod.router.routes]
        assert "/v1/settings/clear-cache" in paths, (
            "clear-cache 未注册——SettingPage 清缓存必 405"
        )
        assert paths.index("/v1/settings/clear-cache") < paths.index("/v1/settings/{key}"), (
            "/clear-cache 必须注册在 /{key} 之前，否则被路径参数吞掉"
        )

    def test_clear_cache_clears_registered_caches(self):
        from neurova.api.endpoints import settings as settings_mod
        from neurova.memory.core import cache as cache_mod
        cleared = []

        class _Cache:
            def clear(self):
                cleared.append(True)
                return 3

        cache_mod._cache_registry.clear()
        cache_mod._cache_registry["probe"] = _Cache()
        try:
            client = _client(settings_mod.router, "")
            r = client.post("/v1/settings/clear-cache")
            assert r.status_code == 200, r.text
            assert r.json()["data"]["total_cleared"] == 3
            assert cleared == [True]
        finally:
            cache_mod._cache_registry.clear()


# ── tool-layers execute (改指真实契约) ───────────────────────────────────


class TestToolExecuteContract:
    def test_execute_route_is_the_body_carried_one(self):
        from neurova.api.endpoints.tool_layers import router
        routes = {(r.path, m) for r in router.routes
                  for m in (getattr(r, "methods", None) or ())}
        assert ("/tools/execute", "POST") in routes
        assert ("/tools/{tool_id}/execute", "POST") not in routes, (
            "不得再注册按路径传 id 的 execute —— 唯一契约是 body 带 tool_name"
        )
