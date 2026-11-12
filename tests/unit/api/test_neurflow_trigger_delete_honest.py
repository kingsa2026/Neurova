# -*- coding: utf-8 -*-
"""P2-5 neurflow_triggers 删除吞 unregister 异常红测（全库断点审计 2026-11-12）。

缺陷：DELETE /triggers/{id} 先删存储再 unregister，unregister 失败被
`except Exception: pass` 吞掉仍报 deleted——已删触发器在重启前仍会触发。

修复口径（审计开方）：先 unregister 后删存储；unregister 失败＝删除失败，
保留触发器并如实报错。
"""
import os

os.environ.setdefault("NEUROVA_JWT_SECRET", "test_secret_for_trigger_delete_honest")
os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_for_trigger_delete_honest")

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.endpoints import neurflow_triggers


class FakeStorage:
    def __init__(self):
        self.triggers = {"t1": {"trigger_id": "t1", "name": "demo"}}
        self.deleted = []

    def get_trigger(self, tid):
        return self.triggers.get(tid)

    def delete_trigger(self, tid):
        self.deleted.append(tid)
        return self.triggers.pop(tid, None) is not None


@pytest.fixture
def app(monkeypatch):
    import neurova.api.endpoints.neurflow_api as api
    import neurova.collaboration.neurflow.triggers as trig_mod

    storage = FakeStorage()

    class FakeManager:
        def __init__(self):
            self.unregister_calls = []

        async def unregister(self, tid):
            self.unregister_calls.append(tid)
            raise RuntimeError("注销失败（模拟管理器故障）")

    manager = FakeManager()
    monkeypatch.setattr(api, "_get_storage", lambda: storage)
    monkeypatch.setattr(trig_mod, "get_trigger_manager", lambda: manager)

    application = FastAPI()
    application.include_router(neurflow_triggers.router, prefix="/v1/neurflow")
    application.dependency_overrides[neurflow_triggers.get_current_user] = lambda: {
        "user_id": "u1", "username": "u", "role": "admin", "neuser_id": "ne1",
    }
    return application, storage, manager


def test_unregister_failure_keeps_trigger_and_reports(app):
    application, storage, manager = app
    client = TestClient(application)
    resp = client.delete("/v1/neurflow/triggers/t1")
    assert resp.status_code >= 400, (
        f"unregister 失败必须如实报错，实得 {resp.status_code} {resp.json()}"
    )
    assert storage.deleted == [], "unregister 失败后存储被删——重启前该触发器仍会触发"
    assert manager.unregister_calls == ["t1"]


def test_unregister_success_still_deletes(app):
    """正常路径不回归：unregister 成功 → 存储删除 → 200。"""
    import neurova.collaboration.neurflow.triggers as trig_mod

    application, storage, manager = app

    # 放开故障注入：unregister 正常返回
    async def _ok(tid):
        manager.unregister_calls.append(tid)
        return True

    manager.unregister = _ok
    client = TestClient(application)
    resp = client.delete("/v1/neurflow/triggers/t1")
    assert resp.status_code == 200
    assert storage.deleted == ["t1"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
