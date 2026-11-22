# -*- coding: utf-8 -*-
"""生成域租户隔离（多模态追平遗留审计）：任务台账带 tenant 列并在归属校验中生效。

场景：同一 user_id 跨租户复用（历史/迁移）时，跨租户访问必须被拒——
仅靠 owner_user_id 相等不足以证明「同租户」，需记录级 tenant 列参与校验。
红：TaskRecord 无 tenant 列、_get_owned_task_record 不校验租户——
    owner=uid 且 tenant=t2 的记录对 tenant=t1 的同名用户 200 可达；
    创建点也不从 JWT 落 tenant_id（记录 tenant_id 为空）。
绿：创建点从 JWT 落 tenant_id（缺省 default）；归属校验租户不符即 403；
    无 tenant 的存量记录按既有 owner/管理员规则放行（向后兼容）。
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.deps import get_current_user as _gcu_deps
from neurova.api.endpoints import generation as generation_ep
from neurova.llm.generators import task_ledger as ledger_mod
from neurova.llm.generators import protocols as proto_mod
from neurova.llm.generators import runtime as gen_runtime
from neurova.llm.generators.task_ledger import GenerationTaskLedger, TaskRecord
from neurova.llm.generators.protocols import ProtocolCredentials


@pytest.fixture()
def tmp_ledger(tmp_path, monkeypatch):
    led = GenerationTaskLedger(path=str(tmp_path / "tasks.json"))
    monkeypatch.setattr(ledger_mod, "_ledger", led)
    yield led


@pytest.fixture()
def client_t1(tmp_ledger, monkeypatch):
    """tenant=t1 的普通用户（非 admin，排除管理员越权干扰）。"""
    app = FastAPI()
    app.include_router(generation_ep.router, prefix="/api/v1/generation")
    app.dependency_overrides[_gcu_deps] = lambda: {
        "user_id": "u1", "username": "u1", "role": "user", "tenant_id": "t1",
    }
    with TestClient(app) as c:
        yield c


def _seed(led: GenerationTaskLedger, task_id: str, tenant: str) -> None:
    led.add(TaskRecord(
        task_id=task_id, kind="music", protocol="fal", model="fal-ai/musicgen",
        base_url="https://queue.fal.run", status="submitted", remote_task_id="req-1",
        prompt="p", owner_user_id="u1", tenant_id=tenant,
    ))


class TestGenerationTenantIsolation:
    def test_cross_tenant_user_reuse_is_denied(self, client_t1, tmp_ledger):
        """同 user_id 跨租户复用：t2 租户的同名用户不得读 t1 用户的任务。"""
        _seed(tmp_ledger, "task-x", "t2")
        resp = client_t1.get("/api/v1/generation/music/status/task-x")
        assert resp.status_code == 403

    def test_same_tenant_owner_still_allowed(self, client_t1, tmp_ledger, monkeypatch):
        _seed(tmp_ledger, "task-ok", "t1")

        async def fake_poll(creds, task_id, poll_url="", result_url="", timeout=30.0):
            return {"status": "running"}

        monkeypatch.setattr(proto_mod, "poll_music", fake_poll)
        resp = client_t1.get("/api/v1/generation/music/status/task-ok")
        assert resp.status_code == 200

    def test_legacy_record_without_tenant_still_by_owner(self, client_t1, tmp_ledger,
                                                         monkeypatch):
        """无 tenant 的存量记录（升级前）按既有 owner/管理员规则放行。"""
        _seed(tmp_ledger, "task-legacy", "")

        async def fake_poll(creds, task_id, poll_url="", result_url="", timeout=30.0):
            return {"status": "running"}

        monkeypatch.setattr(proto_mod, "poll_music", fake_poll)
        resp = client_t1.get("/api/v1/generation/music/status/task-legacy")
        assert resp.status_code == 200

    def test_create_stamps_tenant_from_jwt(self, client_t1, tmp_ledger, monkeypatch):
        """创建点从 JWT 落 tenant_id（缺省 default），不依赖前端传参。"""

        def fake_resolve(protocol_hint, model, provider_id, api_key, base_url,
                         default_base):
            return ProtocolCredentials(api_key="k", base_url="https://queue.fal.run",
                                       model="fal-ai/musicgen", protocol=protocol_hint)

        async def fake_submit(creds, prompt, duration=30, timeout=60.0):
            return {"task_id": "req-9",
                    "poll_url": "https://queue.fal.run/fal-ai/musicgen/requests/req-9/status",
                    "result_url": "https://queue.fal.run/fal-ai/musicgen/requests/req-9",
                    "raw": {"request_id": "req-9"}}

        monkeypatch.setattr(gen_runtime, "resolve_generation_creds", fake_resolve)
        monkeypatch.setattr(proto_mod, "submit_music", fake_submit)
        resp = client_t1.post("/api/v1/generation/music", json={"prompt": "p"})
        assert resp.status_code == 200, resp.text
        ledger_task_id = resp.json()["data"]["task_id"]
        rec = tmp_ledger.get(ledger_task_id)
        assert rec is not None
        assert rec.owner_user_id == "u1"
        assert rec.tenant_id == "t1"
