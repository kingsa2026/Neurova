"""`GET /memory-settings/settings/export` 不得被 `/settings/{section}` 吞掉

根因：FastAPI 按注册顺序匹配，而字面路由 `/settings/export` 声明在参数化路由
`/settings/{section}` 之后，于是导出请求被当成 `section="export"`，再由未知 section
判定抛 404——端点定义存在却永远打不到（同 `crud.py` 里 `/{memory_id}` 必须最后注册
的纪律，只是方向相反：字面量在前）。

判据双向：导出必须 200；未知 section 仍须 404（防止"让位"改成放宽校验）。
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api import deps as deps_mod
from neurova.api.endpoints.memory_settings_api import router as settingsRouter
from neurova.api.error_handlers import register_error_handlers

ALICE = {"user_id": "alice", "username": "alice", "role": "user", "neuser_id": "ne-alice"}


@pytest.fixture
def client():
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(settingsRouter, prefix="/api/v1/memory-settings")
    testClient = TestClient(app)
    testClient.app.dependency_overrides[deps_mod.get_current_user] = lambda: ALICE
    return testClient


def test_exportRespondsWithPayload(client):
    r = client.get("/api/v1/memory-settings/settings/export")

    assert r.status_code == 200, (
        "导出路由应 200，实得 "
        f"{r.status_code}: {r.text}（404=被 /settings/{{section}} 抢先匹配）"
    )
    assert r.json().get("data"), f"导出应带回参数读数，实得 {r.text}"


def test_unknownSectionStillRejects(client):
    r = client.get("/api/v1/memory-settings/settings/no-such-section")

    assert r.status_code == 404, r.text
