"""pending 清单/裁决历史的 store 故障必须是标准信封

根因：`pending.py:64/87` 抛 `APIError(ErrorCodes.INTERNAL, ...)`，而枚举里只有
`INTERNAL_ERROR`（`api_standard.py:42`）。于是 store 真出故障时，except 块内二次抛
`AttributeError`——原始故障原因（比如 SQLite 打不开）既不进响应也不进日志的
错误信封，只剩一条 traceback。判据取行为：store 故障 → 500 + `code:5001` +
消息点名原始故障。

装配口径与 `test_memory_route_authorization.py` 一致：真 router、真鉴权依赖、
真错误处理器；身份经 `dependency_overrides` 注入真依赖的返回位；
store 故障经本模块自带的 `_get_store` 装配缝注入（`_get_store` 在调用处 import，
patch 源函数即命中生产读取路径）。
"""

import typing

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api import auth as auth_mod
from neurova.api.endpoints.memory import router as memoryRouter
from neurova.api.error_handlers import register_error_handlers

ADMIN = {"user_id": "root", "username": "root", "role": "admin", "neuser_id": "ne-root"}


@pytest.fixture
def client():
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(memoryRouter, prefix="/api/v1/memory")
    # 身份门按**路由图实际用到的**来打：记忆面 2026-10-26 点单甲之后整面挂
    # `requireIdentityForMemoryFace`（路由级），它不看处理器级的 override ⇒
    # 只钉 `get_current_user_or_default` 会整族 401，红落在"没鉴权"上而不是
    # 本档要测的"store 故障长什么样"。取法见 `tests/auth_headers.overrideIdentity`。
    from tests.auth_headers import overrideIdentity

    overrideIdentity(app, ADMIN)
    return TestClient(app)


def _failStore(monkeypatch, reason: str):
    def boom():
        raise RuntimeError(reason)

    monkeypatch.setattr("neurova.memory.pending_memory.get_pending_memory_store", boom)


@pytest.mark.parametrize(
    "path,reason",
    [
        ("/api/v1/memory/pending", "STORE-DOWN"),
        ("/api/v1/memory/pending/decisions", "DECISION-STORE-DOWN"),
    ],
)
def test_storeFailureReturnsStandardEnvelope(client, monkeypatch, path: str, reason: str):
    """两条 pending 读路由共用同一个错误码落点，逐条咬合"""
    _failStore(monkeypatch, reason)

    r = client.get(path)

    assert r.status_code == 500, r.text
    body: typing.Dict[str, object] = r.json()
    assert body.get("code") == 5001, f"应为标准 5001 信封，实得 {body}"
    assert reason in str(body.get("message", "")), f"原始故障原因必须点名进响应，实得 {body}"
