"""Frozen pre-split contracts; all I/O below is local or mocked."""
import ast
import importlib
import inspect
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from neurova.api.endpoints import console as api

SNAPSHOT = Path(__file__).with_name("console_split_routes.json")
DOMAINS = {
    "files": ["post_console_upload", "list_console_uploads", "get_console_upload", "delete_console_upload"],
    "system": ["get_backend_debug_logs", "get_system_status", "post_debug_run_command"],
    "annotations": ["list_annotations", "create_annotation", "update_annotation", "delete_annotation", "export_training_set"],
}


def stable(value):
    if value is inspect.Signature.empty:
        return "<empty>"
    if hasattr(value, "model_json_schema"):
        return {"type": value.__module__ + "." + value.__qualname__, "schema": value.model_json_schema()}
    if hasattr(value, "dependency"):
        return {"dependency": dependency_call(value.dependency), "use_cache": value.use_cache}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [stable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): stable(v) for k, v in value.items()}
    if inspect.isclass(value):
        return value.__module__ + "." + value.__qualname__
    return str(value)


def dependency_call(call):
    if call is None:
        return None
    return {"name": getattr(call, "__module__", type(call).__module__) + "." + getattr(call, "__qualname__", type(call).__qualname__),
            "closure": [stable(c.cell_contents) for c in (getattr(call, "__closure__", None) or ())]}


def dependency_tree(dep, root=False):
    return {"call": None if root else dependency_call(dep.call), "name": dep.name,
            "use_cache": dep.use_cache,
            "children": [dependency_tree(child) for child in dep.dependencies]}


def route_snapshot():
    result = []
    for route in api.router.routes:
        sig = inspect.signature(route.endpoint)
        result.append({"kind": type(route).__name__, "path": route.path,
                       "methods": sorted(getattr(route, "methods", []) or []),
                       "name": route.name, "unique_id": getattr(route, "unique_id", None),
                       "operation_id": getattr(route, "operation_id", None),
                       "response_model": stable(getattr(route, "response_model", None)),
                       "status_code": getattr(route, "status_code", None),
                       "parameters": [{"name": p.name, "kind": p.kind.name,
                                       "annotation": stable(p.annotation), "default": stable(p.default)}
                                      for p in sig.parameters.values()],
                       "return": stable(sig.return_annotation),
                       "dependencies": dependency_tree(route.dependant, root=True)})
    return result


def test_full_router_snapshot():
    assert route_snapshot() == json.loads(SNAPSHOT.read_text(encoding="utf-8"))


@pytest.mark.parametrize("domain", DOMAINS)
def test_structure(domain):
    leaf = importlib.import_module("neurova.api.endpoints.console_" + domain)
    for name in DOMAINS[domain]:
        endpoint = getattr(api, name)
        assert endpoint.__module__ == leaf.__name__
        route = next(r for r in api.router.routes if r.name == name)
        assert route.endpoint is endpoint
        for param in inspect.signature(endpoint).parameters.values():
            if hasattr(param.default, "dependency"):
                assert next(d for d in route.dependant.dependencies if d.name == param.name).call is param.default.dependency
    calls = [n.func.id for n in ast.walk(ast.parse(inspect.getsource(leaf)))
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
    assert not {"exec", "globals"}.intersection(calls)


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(api, "_CONSOLE_UPLOAD_DIR", tmp_path)
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api.get_current_user] = lambda: {"user_id": "test", "role": "admin"}
    with TestClient(app) as client:
        yield client


def test_files_old_patch_seams(client, monkeypatch, tmp_path):
    safe = Mock(return_value="safe.txt")
    monkeypatch.setattr(api, "_safe_filename", safe)
    monkeypatch.setattr(api, "uuid", SimpleNamespace(uuid4=lambda: "12345678"))
    response = client.post("/upload", files={"file": ("input.txt", b"hello", "text/plain")})
    assert response.status_code == 200
    assert response.json()["data"]["file_id"] == "12345678"
    assert (tmp_path / "12345678_safe.txt").read_bytes() == b"hello"
    assert client.get("/uploads").json()["data"]["total"] == 1
    safe.return_value = "12345678_safe.txt"
    assert client.get("/uploads/input.txt").content == b"hello"
    response_factory = Mock(return_value={"patched": True})
    monkeypatch.setattr(api, "FileResponse", response_factory)
    assert client.get("/uploads/input.txt").json() == {"patched": True}
    response_factory.assert_called_once_with(str(tmp_path / "12345678_safe.txt"), filename="12345678_safe.txt")
    assert client.delete("/uploads/input.txt").status_code == 200
    assert not list(tmp_path.iterdir())
    assert client.get("/uploads/input.txt").status_code == 404
    assert client.delete("/uploads/input.txt").status_code == 404
    assert safe.call_count == 6


def test_debug_old_patch_seams(client, monkeypatch):
    monkeypatch.setattr(api, "config", SimpleNamespace(get=Mock(return_value="fake.log")))
    monkeypatch.setattr(api, "os", SimpleNamespace(path=SimpleNamespace(exists=Mock(return_value=True))))
    tail = Mock(return_value="mock log")
    monkeypatch.setattr(api, "_tail_text_file", tail)
    assert client.get("/debug/logs?lines=7").json()["data"]["content"] == "mock log"
    tail.assert_called_once_with("fake.log", 7)
    import psutil
    monkeypatch.setattr(psutil, "cpu_percent", Mock(return_value=12))
    monkeypatch.setattr(psutil, "virtual_memory", Mock(return_value=SimpleNamespace(percent=10, used=1048576, total=2097152)))
    monkeypatch.setattr(psutil, "disk_usage", Mock(return_value=SimpleNamespace(percent=20)))
    monkeypatch.setattr(psutil, "boot_time", Mock(return_value=90))
    monkeypatch.setattr(api, "time", SimpleNamespace(time=lambda: 100))
    assert client.get("/debug/status").json()["data"] == {"cpu_percent": 12, "memory_percent": 10, "memory_used_mb": 1, "memory_total_mb": 2, "disk_percent": 20, "uptime_seconds": 10}
    proc = SimpleNamespace(communicate=AsyncMock(return_value=(b"mock", b"")), returncode=0)
    spawn = AsyncMock(return_value=proc)
    monkeypatch.setattr(api.asyncio, "create_subprocess_exec", spawn)
    assert client.post("/debug/command", json={"command": "pwd"}).json()["data"]["stdout"] == "mock"
    spawn.assert_awaited_once_with("pwd", stdout=api.asyncio.subprocess.PIPE, stderr=api.asyncio.subprocess.PIPE)
    assert client.post("/debug/command", json={"command": "not-allowed"}).status_code == 403
    assert spawn.await_count == 1


@pytest.mark.parametrize("role, expected", [(None, 401), ("user", 403)])
@pytest.mark.parametrize("method, path, body", [("get", "/debug/logs", None), ("get", "/debug/status", None), ("post", "/debug/command", {"command": "pwd"}), ("post", "/push/message", {"content": "test"})])
def test_admin_http_rejection(client, monkeypatch, role, expected, method, path, body):
    def user():
        if role is None:
            raise HTTPException(401, "Not authenticated")
        return {"user_id": "test", "role": role}
    client.app.dependency_overrides[api.get_current_user] = user
    spawn = AsyncMock(side_effect=AssertionError("must not execute"))
    monkeypatch.setattr(api.asyncio, "create_subprocess_exec", spawn)
    assert client.request(method, path, json=body).status_code == expected
    spawn.assert_not_awaited()


def test_annotations_mock_store(client, monkeypatch):
    from neurova.core import annotation_store
    store = Mock()
    item = {"id": "a", "question": "Question", "answer": "Answer"}
    store.list_annotations.return_value = [item]
    store.count.return_value = 1
    store.add.return_value = "a"
    store.get.return_value = item
    store.delete.return_value = True
    store.export_training_set.return_value = ["one", "two"]
    monkeypatch.setattr(annotation_store, "get_annotation_store", lambda: store)
    assert client.get("/annotations?q=question").json()["data"] == {"items": [item], "total": 1}
    assert client.get("/annotations?q=missing").json()["data"]["items"] == []
    assert client.get("/annotations?limit=0").status_code == 422
    assert client.post("/annotations", json={"question": " q ", "answer": " a "}).json()["data"]["id"] == "a"
    store.add.assert_called_once_with("q", "a", source="manual")
    assert client.post("/annotations", json={"question": " ", "answer": "a"}).status_code == 400
    assert client.put("/annotations/a", json={"answer": "new", "enabled": False}).status_code == 200
    store.update_answer.assert_called_once_with("a", "new")
    store.set_enabled.assert_called_once_with("a", False)
    assert client.get("/annotations/export").json()["data"] == {"jsonl": "one\ntwo", "count": 2}
    assert client.delete("/annotations/a").status_code == 200
    store.get.return_value = None
    assert client.put("/annotations/a", json={"answer": "new"}).status_code == 404
    store.delete.return_value = False
    assert client.delete("/annotations/a").status_code == 404


def test_model_identity():
    for name, model in [("post_debug_run_command", api.CommandRequest), ("create_annotation", api.AnnotationCreateRequest), ("update_annotation", api.AnnotationUpdateRequest)]:
        assert inspect.signature(getattr(api, name)).parameters["body"].annotation is model
        assert model.__module__ == api.__name__
