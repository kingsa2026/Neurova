"""
NeurFlow P1 Step 6+7 — 触发器 CRUD API 与投递记录测试

Step 6 契约（neurflow_api.py）：
- GET    /workflows/{wid}/triggers        列表
- POST   /workflows/{wid}/triggers        新建（webhook 自动生成 secret 返回明文一次）
- DELETE /triggers/{tid}                  删除
- POST   /triggers/{tid}/fire             手动触发

Step 7 契约（storage）：
- webhook_deliveries 表：save_delivery / list_deliveries
- 记录字段：trigger_id / signature_valid / execution_id / status_code / created_at

TDD：先红后绿。API 测试用独立 FastAPI app + tmp DB。
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.collaboration.neurflow.models import TriggerType


@pytest.fixture
def app(tmp_path):
    """独立 app + tmp DB 注入（monkeypatch _get_storage）。"""
    from neurova.api.endpoints import neurflow_api

    test_db = str(tmp_path / "nf_api.db")
    storage = neurflow_api.NeurflowStorage(db_path=test_db)
    orig = neurflow_api._get_storage
    neurflow_api._get_storage = lambda: storage
    # 提供 workflow 供 FK
    from neurova.collaboration.neurflow.models import (
        WorkflowDefinition, WorkflowNode, WorkflowEdge, WorkflowStatus,
    )
    storage.save_workflow(WorkflowDefinition(
        id="wf_api", name="api-wf", description="", version="1.0.0",
        nodes=[
            WorkflowNode(id="start", type="builtin:start", position={"x": 0, "y": 0}, config={}),
            WorkflowNode(id="end", type="builtin:end", position={"x": 10, "y": 0}, config={}),
        ],
        edges=[WorkflowEdge(id="e", source="start", target="end")],
        variables=[], tags=[], category="test", author="t",
        created_at=0, updated_at=0, status=WorkflowStatus.PUBLISHED,
    ))
    app = FastAPI()
    app.include_router(neurflow_api.router)
    # P0-7/N1：触发器端点现已挂严格鉴权——测试显式注入认证身份
    # （契约更新：未认证访问从 404 语义变为 401）
    from neurova.api.auth import get_current_user

    app.dependency_overrides[get_current_user] = lambda: {
        "user_id": "tuser", "username": "tuser", "role": "admin", "neuser_id": "tuser",
    }
    yield app
    neurflow_api._get_storage = orig


@pytest.fixture
def client(app):
    return TestClient(app)


class TestTriggerCRUDApi:
    def test_create_webhook_trigger_returns_secret_once(self, client):
        r = client.post(
            "/workflows/wf_api/triggers",
            json={"type": "webhook", "rate_limit_per_minute": 30},
        )
        assert r.status_code == 200
        body = r.json()
        data = body.get("data", body)
        assert data["trigger"]["type"] == "webhook"
        # 明文 secret 仅此一次返回
        assert data.get("secret")
        assert data["trigger"]["secret_encrypted"] is None  # 不回显密文

    def test_create_cron_trigger(self, client):
        r = client.post(
            "/workflows/wf_api/triggers",
            json={"type": "cron", "config": {"cron": "0 9 * * 1-5"}},
        )
        assert r.status_code == 200
        data = r.json().get("data", r.json())
        assert data["trigger"]["type"] == "cron"

    def test_create_cron_trigger_invalid_expr_rejected(self, client):
        r = client.post(
            "/workflows/wf_api/triggers",
            json={"type": "cron", "config": {"cron": "not-a-cron"}},
        )
        assert r.status_code in (400, 422)

    def test_list_triggers(self, client):
        client.post("/workflows/wf_api/triggers", json={"type": "webhook"})
        r = client.get("/workflows/wf_api/triggers")
        assert r.status_code == 200
        items = r.json().get("data", r.json())
        assert isinstance(items, list)
        assert len(items) >= 1

    def test_delete_trigger(self, client):
        created = client.post(
            "/workflows/wf_api/triggers", json={"type": "webhook"}
        ).json()
        tid = (created.get("data") or created)["trigger"]["id"]
        r = client.delete(f"/triggers/{tid}")
        assert r.status_code == 200
        # 二次删除 404
        r2 = client.delete(f"/triggers/{tid}")
        assert r2.status_code == 404

    def test_fire_unknown_trigger_404(self, client):
        r = client.post("/triggers/trg_none/fire", json={})
        assert r.status_code == 404


class TestDeliveryStorage:
    @pytest.fixture
    def storage(self, tmp_path):
        from neurova.collaboration.neurflow.storage import NeurflowStorage

        return NeurflowStorage(db_path=str(tmp_path / "dl.db"))

    def test_save_and_list_deliveries(self, storage):
        storage.save_delivery(
            trigger_id="trg_d1",
            signature_valid=True,
            execution_id="exec_1",
            status_code=202,
        )
        storage.save_delivery(
            trigger_id="trg_d1",
            signature_valid=False,
            execution_id=None,
            status_code=401,
        )
        items = storage.list_deliveries("trg_d1")
        assert len(items) == 2
        # 倒序：最新在前
        assert items[0]["signature_valid"] is False
        assert items[0]["status_code"] == 401
        assert items[1]["signature_valid"] is True

    def test_list_deliveries_empty(self, storage):
        assert storage.list_deliveries("trg_none") == []

    def test_list_deliveries_limit(self, storage):
        for i in range(5):
            storage.save_delivery(
                trigger_id="trg_l", signature_valid=True,
                execution_id=f"e{i}", status_code=202,
            )
        assert len(storage.list_deliveries("trg_l", limit=3)) == 3
