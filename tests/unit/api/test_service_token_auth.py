"""
服务令牌身份（遗留修复 ④）：无 JWT 调用方（渠道后端/n8n/运维脚本）访问知识条目 API

契约（get_current_user_or_service）：
- JWT 优先：有效 Bearer → 正常用户身份（原行为）
- 无 JWT 时：X-Service-Token 头与环境变量 NEUROVA_SERVICE_TOKEN
  常量时间比较（hmac.compare_digest）；匹配 → role=admin 的机器身份
  {user_id: "system", auth_source: "service_token"}
- env 未配置/未带头/错值 → 401（服务令牌功能关闭时不留后门）
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api import auth as knowledge_auth
from neurova.api.endpoints import knowledge as knowledge_module

PREFIX = "/v1/knowledge"
ALICE_JWT_OVERRIDE = {"user_id": "1", "username": "alice", "role": "user", "neuser_id": "1"}


@pytest.fixture()
def app(tmp_path, monkeypatch):
    from neurova.knowledge.repository import KnowledgeRepository

    r = KnowledgeRepository(str(tmp_path / "kb"))
    monkeypatch.setattr("neurova.knowledge.repository.get_knowledge_repository", lambda: r)

    application = FastAPI()
    application.include_router(knowledge_module.router, prefix=PREFIX)
    return application


def test_service_token_grants_machine_identity(app, monkeypatch):
    monkeypatch.setenv("NEUROVA_SERVICE_TOKEN", "svc-secret-1")
    client = TestClient(app)
    resp = client.get(PREFIX, headers={"X-Service-Token": "svc-secret-1"})
    assert resp.status_code == 200
    # 机器身份可创建私有条目（归属 system）
    resp = client.post(
        PREFIX,
        json={"title": "ops-doc", "content": "c"},
        headers={"X-Service-Token": "svc-secret-1"},
    )
    assert resp.status_code == 200
    assert resp.json()["owner_user_id"] == "system"


def test_service_token_wrong_or_missing_rejected(app, monkeypatch):
    monkeypatch.setenv("NEUROVA_SERVICE_TOKEN", "svc-secret-1")
    client = TestClient(app)
    assert client.get(PREFIX).status_code == 401
    assert client.get(PREFIX, headers={"X-Service-Token": "wrong"}).status_code == 401


def test_service_token_disabled_when_env_unset(app, monkeypatch):
    monkeypatch.delenv("NEUROVA_SERVICE_TOKEN", raising=False)
    client = TestClient(app)
    resp = client.get(PREFIX, headers={"X-Service-Token": "svc-secret-1"})
    assert resp.status_code == 401


def test_jwt_path_unaffected_by_service_token(app, monkeypatch):
    """有效 JWT 走原用户路径（身份不是 system 机器身份）"""
    from neurova.api.auth import create_access_token

    monkeypatch.setenv("NEUROVA_SERVICE_TOKEN", "svc-secret-1")
    client = TestClient(app)
    token = create_access_token(
        {"sub": "1", "username": "alice", "role": "user", "neuser_id": "1"}
    )
    resp = client.get(PREFIX, headers={"Authorization": "Bearer " + token})
    assert resp.status_code == 200

    resp = client.post(
        PREFIX + "/search", json={"query": "x"}, headers={"Authorization": "Bearer " + token}
    )
    assert resp.status_code == 200
