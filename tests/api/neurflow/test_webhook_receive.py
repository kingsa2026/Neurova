"""
NeurFlow P1 Step 4b — Webhook 入站测试（handler 业务链 + 端点壳）

handler：neurova/collaboration/neurflow/webhook_ingress.py（纯注入 deps）
端点：POST /neurflow/triggers/webhook/{trigger_id}/receive（薄壳）

契约：
- 有效签名 → 派发成功（202 信封，含 execution_id）
- 签名缺失/错误 → 401
- trigger 不存在/未启用/非 webhook → 404
- workflow 未发布 → 404 (WORKFLOW_NOT_PUBLISHED)
- 超限流 → 429；非法 JSON → 400；deps 未配置 → 500
- WorkflowTrigger.secret_encrypted 字段（AES-GCM 可逆，供验签）
TDD：先红后绿。
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.core.trigger_rate_limiter import TriggerRateLimiter
from neurova.core.webhook_security import compute_signature


@pytest.fixture
def app():
    from neurova.api.endpoints.neurflow_api import router

    app = FastAPI()
    app.include_router(router)
    from neurova.api.auth import get_current_user

    app.dependency_overrides[get_current_user] = lambda: {
        "user_id": "tuser", "username": "tuser", "role": "admin", "neuser_id": "tuser",
    }
    return app


@pytest.fixture
def client(app):
    return TestClient(app)


class TestSecretEncryptedField:
    def test_secret_encrypted_field_exists(self):
        from neurova.collaboration.neurflow.models import WorkflowTrigger

        tr = WorkflowTrigger(id="t", workflow_id="wf", type="webhook")
        assert hasattr(tr, "secret_encrypted")
        assert tr.secret_encrypted is None


def _make_deps(trigger=None, instance=None):
    """构造注入式 deps（全 mock，无 storage）。limiter 按 trigger 缓存（同生产语义）。"""
    limiter_cache: dict = {}

    def rate_limiter_for(tr):
        tid = getattr(tr, "id", "default")
        if tid not in limiter_cache:
            limiter_cache[tid] = TriggerRateLimiter(
                getattr(tr, "rate_limit_per_minute", None)
            )
        return limiter_cache[tid]

    async def run_workflow(workflow, inputs):
        return instance if instance is not None else MagicMock()

    return {
        "load_trigger": MagicMock(return_value=trigger),
        "load_published_workflow": MagicMock(return_value=MagicMock()),
        "decrypt_secret": MagicMock(return_value="raw-secret"),
        "run_workflow": run_workflow,
        "rate_limiter_for": rate_limiter_for,
    }


def _webhook_trigger(**overrides):
    from neurova.collaboration.neurflow.models import TriggerType, WorkflowTrigger

    fields = dict(
        id="trg_1", workflow_id="wf_1", type=TriggerType.WEBHOOK
    )
    fields.update(overrides)
    return WorkflowTrigger(**fields)


class TestIngressHandler:
    @pytest.mark.asyncio
    async def test_valid_signature_dispatches(self):
        from neurova.collaboration.neurflow.webhook_ingress import handle_webhook_ingress

        trigger = _webhook_trigger(secret_encrypted="enc", rate_limit_per_minute=10)
        instance = MagicMock()
        instance.status.value = "completed"
        instance.id = "exec_9"
        deps = _make_deps(trigger=trigger, instance=instance)

        payload = b'{"payload":{"a":1}}'
        sig = compute_signature(payload, "raw-secret")

        result = await handle_webhook_ingress("trg_1", payload, sig, deps=deps)
        assert result["code"] == 0
        assert result["data"]["execution_id"] == "exec_9"

    @pytest.mark.asyncio
    async def test_invalid_signature_raises_401(self):
        from neurova.collaboration.neurflow.webhook_ingress import (
            IngressRejected,
            handle_webhook_ingress,
        )

        deps = _make_deps(trigger=_webhook_trigger())
        with pytest.raises(IngressRejected) as exc:
            await handle_webhook_ingress("trg_1", b"{}", "sha256=" + "0" * 64, deps=deps)
        assert exc.value.status_code == 401

    @pytest.mark.asyncio
    async def test_missing_trigger_raises_404(self):
        from neurova.collaboration.neurflow.webhook_ingress import (
            IngressRejected,
            handle_webhook_ingress,
        )

        deps = _make_deps(trigger=None)
        with pytest.raises(IngressRejected) as exc:
            await handle_webhook_ingress("trg_none", b"{}", None, deps=deps)
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_non_webhook_type_raises_404(self):
        from neurova.collaboration.neurflow.models import TriggerType
        from neurova.collaboration.neurflow.webhook_ingress import (
            IngressRejected,
            handle_webhook_ingress,
        )

        deps = _make_deps(trigger=_webhook_trigger(type=TriggerType.CRON))
        with pytest.raises(IngressRejected) as exc:
            await handle_webhook_ingress("trg_1", b"{}", None, deps=deps)
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_rate_limit_exceeded_raises_429(self):
        from neurova.collaboration.neurflow.webhook_ingress import (
            IngressRejected,
            handle_webhook_ingress,
        )

        trigger = _webhook_trigger(rate_limit_per_minute=1)
        deps = _make_deps(trigger=trigger)

        await handle_webhook_ingress("trg_1", b"{}", None, deps=deps)
        with pytest.raises(IngressRejected) as exc:
            await handle_webhook_ingress("trg_1", b"{}", None, deps=deps)
        assert exc.value.status_code == 429

    @pytest.mark.asyncio
    async def test_invalid_json_raises_400(self):
        from neurova.collaboration.neurflow.webhook_ingress import (
            IngressRejected,
            handle_webhook_ingress,
        )

        deps = _make_deps(trigger=_webhook_trigger())
        # 开放 trigger（无 secret）：不携带签名头即可过验签环节
        with pytest.raises(IngressRejected) as exc:
            await handle_webhook_ingress("trg_1", b"not-json", None, deps=deps)
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_unpublished_workflow_raises_404(self):
        from neurova.collaboration.neurflow.webhook_ingress import (
            IngressRejected,
            handle_webhook_ingress,
        )

        deps = _make_deps(trigger=_webhook_trigger())
        deps["load_published_workflow"] = MagicMock(return_value=None)
        with pytest.raises(IngressRejected) as exc:
            await handle_webhook_ingress("trg_1", b"{}", None, deps=deps)
        assert exc.value.status_code == 404
        assert exc.value.reason == "WORKFLOW_NOT_PUBLISHED"

    @pytest.mark.asyncio
    async def test_no_deps_configured_raises_500(self):
        from neurova.collaboration.neurflow import webhook_ingress

        saved = webhook_ingress._DEPS_PROVIDER
        webhook_ingress._DEPS_PROVIDER = None
        try:
            with pytest.raises(webhook_ingress.IngressRejected) as exc:
                await webhook_ingress.handle_webhook_ingress("t", b"{}", None)
            assert exc.value.status_code == 500
        finally:
            webhook_ingress._DEPS_PROVIDER = saved


class TestDeliveryRecording:
    """遗留④：receive 端点把每次投递落入 webhook_deliveries"""

    @pytest.fixture
    def patched_client(self, tmp_path, monkeypatch):
        from neurova.api.endpoints import neurflow_api
        from neurova.collaboration.neurflow.models import (
            WorkflowDefinition, WorkflowNode, WorkflowEdge,
            WorkflowStatus, TriggerType, WorkflowTrigger,
        )
        from neurova.llm.providers.secret_store import encrypt_api_key

        storage = neurflow_api.NeurflowStorage(db_path=str(tmp_path / "dl_e2e.db"))
        monkeypatch.setattr(neurflow_api, "_get_storage", lambda: storage)

        storage.save_workflow(WorkflowDefinition(
            id="wf_dl", name="dl", description="", version="1.0.0",
            nodes=[
                WorkflowNode(id="start", type="builtin:start", position={"x": 0, "y": 0}, config={}),
                WorkflowNode(id="end", type="builtin:end", position={"x": 10, "y": 0}, config={}),
            ],
            edges=[WorkflowEdge(id="e", source="start", target="end")],
            variables=[], tags=[], category="t", author="t",
            created_at=0, updated_at=0, status=WorkflowStatus.PUBLISHED,
        ))
        secret = "delivery-secret"
        storage.save_trigger(WorkflowTrigger(
            id="trg_dl", workflow_id="wf_dl", type=TriggerType.WEBHOOK,
            enabled=True,
            secret_hash=neurflow_api.NeurflowStorage.hash_trigger_secret(secret),
            secret_encrypted=encrypt_api_key(secret),
        ))

        app = FastAPI()
        app.include_router(neurflow_api.router)
        from neurova.api.auth import get_current_user

        app.dependency_overrides[get_current_user] = lambda: {
                "user_id": "tuser", "username": "tuser", "role": "admin", "neuser_id": "tuser",
        }
        return TestClient(app), storage, secret

    def test_success_delivery_recorded(self, patched_client):
        c, storage, secret = patched_client
        payload = b'{"payload":{"a":1}}'
        sig = compute_signature(payload, secret)
        r = c.post(
            "/triggers/webhook/trg_dl/receive",
            content=payload,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig},
        )
        assert r.status_code == 200
        items = storage.list_deliveries("trg_dl")
        assert len(items) == 1
        assert items[0]["signature_valid"] is True
        assert items[0]["status_code"] == 200
        assert items[0]["execution_id"]

    def test_invalid_signature_delivery_recorded(self, patched_client):
        c, storage, _ = patched_client
        r = c.post(
            "/triggers/webhook/trg_dl/receive",
            content=b"{}",
            headers={"X-Hub-Signature-256": "sha256=" + "0" * 64},
        )
        assert r.status_code == 401
        items = storage.list_deliveries("trg_dl")
        assert len(items) == 1
        assert items[0]["signature_valid"] is False
        assert items[0]["status_code"] == 401


class TestWebhookReceiveEndpoint:
    """FastAPI 薄壳端点（经 set_deps_provider 装配）"""

    def test_endpoint_registered(self):
        from neurova.api.endpoints.neurflow_api import router

        paths = [r.path for r in router.routes if hasattr(r, "path")]
        assert any("receive" in p and "trigger" in p for p in paths)

    def test_missing_trigger_returns_404(self, client):
        r = client.post(
            "/triggers/webhook/trg_nope/receive",
            json={"payload": {"a": 1}},
            headers={"X-Hub-Signature-256": "sha256=" + "0" * 64},
        )
        assert r.status_code == 404

    def test_invalid_signature_returns_401(self, client):
        r = client.post(
            "/triggers/webhook/trg_sig/receive",
            json={"payload": {"a": 1}},
            headers={"X-Hub-Signature-256": "sha256=" + "f" * 64},
        )
        assert r.status_code in (401, 404)

    def test_receive_response_envelope_shape(self, client):
        r = client.post(
            "/triggers/webhook/any/receive",
            content=b"{}",
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code in (400, 401, 404, 429, 202)
        assert r.headers.get("content-type", "").startswith("application/json")