"""First-wave split guards: frozen pre-split route order and patch seams."""
import ast
import inspect
import json
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

ROOT = Path(__file__).resolve().parents[3]
ENDPOINTS = ROOT / "neurova/api/endpoints"
SNAPSHOT = json.loads(Path(__file__).with_name("route_contract_snapshot.json").read_text(encoding="utf-8"))


def test_ordered_route_contract():
    from neurova.api.endpoints import neurflow_api as api
    assert len(api.router.routes) == 65
    for route, expected in zip(api.router.routes, SNAPSHOT):
        assert sorted(route.methods) == [expected["method"]]
        assert route.path == expected["path"]
        assert route.name == expected["name"]
        assert route.operation_id is None
        path_format = expected["path"].replace(":path}", "}")
        assert route.unique_id == re.sub(r"\W", "_", expected["name"] + path_format) + "_" + expected["method"].lower()
        function = ast.parse(inspect.getsource(route.endpoint)).body[0]
        assert ast.unparse(function.args) == expected["signature"]
        assert ast.get_docstring(function) == expected["doc"]
        decorator = expected["decorator"].replace("router.", "deliveries_router.", 1) if expected["path"].startswith("/trigger/deliveries") else expected["decorator"]
        assert ast.unparse(function.decorator_list[0]) == decorator


@pytest.mark.parametrize("domain", ["stores", "triggers"])
def test_leaf_domains_own_routes_and_reexport(domain):
    from neurova.api.endpoints import neurflow_api as api
    path = ENDPOINTS / f"neurflow_{domain}.py"
    assert path.is_file(), f"missing leaf domain: {domain}"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    functions = {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    routes = [r for r in api.router.routes if r.endpoint.__module__.endswith(f"neurflow_{domain}")]
    assert len(routes) == 9
    sibling = "neurflow_triggers" if domain == "stores" else "neurflow_stores"
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            assert sibling not in ast.unparse(node)
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            assert "neurflow_api" not in ast.unparse(node), "aggregator imports must be call-time only"
    for route in routes:
        assert route.name in functions
        assert getattr(api, route.name) is route.endpoint
    assert not any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "exec" for n in ast.walk(tree))


def test_exports_and_assembly_stay_explicit():
    from neurova.api.endpoints import neurflow_api as api, neurflow_stores, neurflow_triggers
    from neurova.agent import workflow_agent
    from neurova.collaboration.neurflow import webhook_ingress
    assert webhook_ingress._DEPS_PROVIDER is api._webhook_ingress_deps
    assert workflow_agent._deps_provider is api.get_workflow_agent_deps
    for name in ("_get_storage", "get_workflow_executor", "get_dag_validator", "get_node_registry", "get_agent_instance"):
        assert callable(getattr(api, name))
    assert isinstance(api._DEBUG_SESSIONS, dict)
    for module in (neurflow_stores, neurflow_triggers):
        for name, value in vars(module).items():
            if callable(value) and getattr(value, "__module__", None) == module.__name__:
                assert getattr(api, name) is value
    tree = ast.parse((ENDPOINTS / "neurflow_api.py").read_text(encoding="utf-8"))
    includes = [ast.unparse(n.value) for n in tree.body if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call) and isinstance(n.value.func, ast.Attribute) and n.value.func.attr == "include_router"]
    assert includes == ["router.include_router(_stores_router)", "router.include_router(_triggers_router)", "router.include_router(_deliveries_router)"]
    retained = {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert {"_get_storage", "get_workflow_agent_deps", "execute_workflow", "step_run_node", "retry_from_checkpoint"} <= retained
    assert not {"list_stores", "oauth_callback", "fire_trigger", "retry_delivery"} & retained


@pytest.mark.asyncio
async def test_store_leaf_reads_aggregator_patch_after_import(monkeypatch):
    from neurova.api.endpoints import neurflow_api as api, neurflow_stores as leaf
    for expected in ("first", "second"):
        manager = Mock()
        manager.list_stores.return_value = [expected]
        manager.mask.side_effect = lambda value: {"name": value}
        monkeypatch.setattr(api, "_get_store_manager", lambda: manager)
        assert await leaf.list_stores(platform="jd", current_user={"user_id": "owner"}) == {"stores": [{"name": expected}], "total": 1}
        manager.list_stores.assert_called_once_with("jd", user_id="owner")


@pytest.mark.asyncio
async def test_oauth_leaf_consumes_patched_exchange_and_writes_state(monkeypatch):
    from starlette.requests import Request
    from neurova.api.endpoints import neurflow_api as api, neurflow_stores as leaf
    manager = Mock()
    manager.create_store.return_value = SimpleNamespace(store_id="store")
    manager.resolve_credentials.return_value = SimpleNamespace(app_key="fake-key", app_secret="fake-secret")
    monkeypatch.setattr(api, "_get_store_manager", lambda: manager)
    monkeypatch.setattr(api, "_oauth_callback_uri", lambda request: "https://example.invalid/callback")
    authorize = Mock(return_value="https://example.invalid/authorize")
    exchange = AsyncMock(return_value={"access_token": "fake-token", "refresh_token": "fake-refresh", "expires_in": 60})
    monkeypatch.setattr(api, "_oauth_authorize_url", authorize)
    monkeypatch.setattr(api, "_oauth_exchange_token", exchange)
    request = Request({"type": "http", "headers": []})
    response = await leaf.oauth_authorize(request, "jd", "fake-key", "fake-secret", "shop", {"user_id": "owner"})
    assert response.status_code == 302
    state, meta = manager.oauth_state_set.call_args.args
    assert meta["user_id"] == "owner" and meta["store_id"] == "store"
    manager.create_store.assert_called_once_with("jd", "shop", credentials={"app_key": "fake-key", "app_secret": "fake-secret"}, user_id="owner", status="pending")
    authorize.assert_called_once_with("jd", "fake-key", "https://example.invalid/callback", state)
    manager.oauth_state_pop.return_value = meta
    response = await leaf.oauth_callback(request, "fake-code", state)
    exchange.assert_awaited_once_with("jd", "fake-key", "fake-secret", "fake-code", "https://example.invalid/callback")
    manager.oauth_state_pop.assert_called_once_with(state)
    update = manager.update_store.call_args.kwargs
    assert update["credentials"] == {"access_token": "fake-token", "refresh_token": "fake-refresh", "status": "active", "last_error": ""}
    assert update["user_id"] == "owner" and update["token_expires_at"] > meta["created_at"]
    assert response.headers["location"].endswith("store_oauth=ok")


@pytest.mark.asyncio
async def test_trigger_closures_read_storage_executor_and_cache_patches(monkeypatch):
    from neurova.api.endpoints import neurflow_api as api, neurflow_triggers as leaf
    from neurova.collaboration.neurflow.models import WorkflowStatus
    deps = leaf._webhook_ingress_deps()
    for identity in ("first", "second"):
        workflow = SimpleNamespace(user_id=identity, status=WorkflowStatus.PUBLISHED)
        storage = Mock()
        storage.get_trigger.return_value = identity
        storage.get_workflow.return_value = workflow
        executor = SimpleNamespace(execute=AsyncMock(return_value=identity))
        monkeypatch.setattr(api, "_get_storage", lambda: storage)
        monkeypatch.setattr(api, "get_workflow_executor", lambda: executor)
        assert deps["load_trigger"]("trigger") == identity
        assert deps["load_published_workflow"]("workflow") is workflow
        assert await deps["run_workflow"](workflow, {}) == identity
        executor.execute.assert_awaited_once_with(workflow=workflow, inputs={}, user_id=identity)
        workflow.status = WorkflowStatus.DRAFT
        assert deps["load_published_workflow"]("workflow") is None
    bucket = object()
    monkeypatch.setattr(api, "_WEBHOOK_RATE_LIMITERS", {"trigger": bucket})
    assert deps["rate_limiter_for"](SimpleNamespace(id="trigger")) is bucket


@pytest.mark.asyncio
async def test_retry_leaf_uses_all_aggregator_patch_seams(monkeypatch):
    from neurova.api.endpoints import neurflow_api as api, neurflow_triggers as leaf
    replay = AsyncMock(return_value={"success": True, "execution_id": "execution"})
    monkeypatch.setattr(api, "handle_webhook_ingress_simple", replay)
    monkeypatch.setattr(api, "_webhook_ingress_deps", lambda: {"load_trigger": lambda tid: object()})
    async def retry(delivery_id, redeliver):
        assert delivery_id == 7
        return await redeliver("trigger", 1)
    service = SimpleNamespace(retry_delivery=retry, list_failed=Mock(return_value=["failed"]))
    monkeypatch.setattr(api, "_get_retry_service", lambda: service)
    assert (await leaf.list_failed_deliveries(3, {}))["data"]["items"] == ["failed"]
    service.list_failed.assert_called_once_with(limit=3)
    assert (await leaf.retry_delivery(7, {}))["data"] == {"ok": True, "execution_id": "execution"}
    replay.assert_awaited_once_with("trigger", {})
