# -*- coding: utf-8 -*-
"""P1-1（审计 2026-11-04）：model.py 非只读端点匿名可写。

缺陷：DELETE/PUT/POST 全挂 get_optional_user（未认证返回 None 不拒请求），
`NEUROVA_GLOBAL_AUTH` 默认 off 无兜底——容器部署（compose/helm 均绑
0.0.0.0）下匿名可删改模型配置、触发模型下载，/check-connection 还构成
匿名 SSRF 探测原语（可任意 base_url 出网探测）。

契约（绿灯态）：
- 非 GET 端点一律 get_current_user——无凭证 401，拒绝发生在进 handler 之前；
- GET 保持匿名可读（列表/能力/进度面契约不变）；
- 持有效凭证的写面行为不变（本文件带 token 用例 + 既有用例改造为带 token）。
"""
import os

import pytest

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_model_gate_0123456789abcdef")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from neurova.api.auth import create_access_token  # noqa: E402
from neurova.api.endpoints import model as model_ep  # noqa: E402
from neurova.llm.provider_manager import LLMProviderManager, reset_provider_manager  # noqa: E402


@pytest.fixture()
def mgr(tmp_path):
    reset_provider_manager()
    m = LLMProviderManager(config={"config_path": str(tmp_path / "providers.json")})
    m.add_provider(
        name="TestProv", provider="openai",
        base_url="https://example.test/v1", api_key="sk-test-1234567890",
        models=["m1"],
    )
    yield m
    reset_provider_manager()


@pytest.fixture()
def client(mgr):
    """最小 FastAPI 只挂 model router（沿 test_model_capability_endpoints 既有形态），
    provider manager 注入 fixture 实例——鉴权依赖走真实 get_current_user 不打桩。"""
    app = FastAPI()
    app.include_router(model_ep.router, prefix="/api/v1/models")
    original = model_ep._get_provider_manager
    model_ep._get_provider_manager = lambda current_user=None: mgr
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    model_ep._get_provider_manager = original


def _authHeaders():
    return {"Authorization": "Bearer " + create_access_token({
        "sub": "tester", "username": "tester", "role": "admin", "tenant_id": "default",
    })}


# 匿名必拒面：method, path, json body
ANON_WRITES = [
    ("delete", "/api/v1/models/m1", None),
    ("put", "/api/v1/models/m1", {"name": "renamed"}),
    ("post", "/api/v1/models/switch", {"model_id": "m1"}),
    ("post", "/api/v1/models/detect-capabilities", {}),
    ("post", "/api/v1/models/probe-multimodal", {"model_id": "m1"}),
    ("post", "/api/v1/models/probe-output-limit", {"provider_id": "p", "model_id": "m1"}),
    ("post", "/api/v1/models/download-source", {"model": "m1", "choice": "skip"}),
    ("post", "/api/v1/models/download", {"model": "m1"}),
]


class TestAnonymousWritesRejected:
    """审计命中的每一条匿名写/探测链路，逐端点钉 401。"""

    @pytest.mark.parametrize("method,path,body", ANON_WRITES)
    def test_anonymous_write_is_401(self, client, method, path, body):
        resp = getattr(client, method)(path, **({"json": body} if body is not None else {}))
        assert resp.status_code == 401, (
            f"{method.upper()} {path} 匿名可进（{resp.status_code}）——"
            "写面必须落在 get_current_user 之后"
        )

    def test_anonymous_check_connection_is_401(self, client):
        resp = client.post("/api/v1/models/check-connection", params={"model_id": "m1"})
        assert resp.status_code == 401


class TestReadFaceUnchanged:
    def test_anonymous_list_still_200(self, client):
        assert client.get("/api/v1/models").status_code == 200


class TestAuthedWriteStillWorks:
    def test_delete_with_token_200(self, client):
        resp = client.delete("/api/v1/models/m1", headers=_authHeaders())
        assert resp.status_code == 200, resp.text
