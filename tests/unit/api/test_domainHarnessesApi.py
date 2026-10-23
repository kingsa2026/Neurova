"""N8 跨域 harness 检索端点。"""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_p0_fixes_0123456789")

from neurova.api.endpoints import skill_pool_api

MOCK_USER = {"user_id": "test_user", "username": "testuser", "role": "admin"}


@pytest.fixture()
def client(monkeypatch):
    class _Service:
        def searchDomainHarnesses(self, query, *, domain="", limit=5):
            return [
                {
                    "skill_id": "peer",
                    "version": "1.2.0",
                    "domain": domain or "legal",
                    "adopted": True,
                    "context_template": "PEER",
                    "score": 1.0 if query else None,
                }
            ][:limit]

    monkeypatch.setattr(skill_pool_api, "_pool_service", lambda agent_id: _Service())
    from neurova.api.deps import get_current_user

    app = FastAPI()
    app.include_router(skill_pool_api.router, prefix="/v1/skill-pool")
    app.dependency_overrides[get_current_user] = lambda: MOCK_USER
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_domain_harness_search(client):
    resp = client.get(
        "/v1/skill-pool/agent/agent/domain-harnesses",
        params={"query": "合同", "domain": "legal", "limit": 3},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data[0]["skill_id"] == "peer"
    assert data[0]["adopted"] is True


@pytest.fixture()
def adoptClient(monkeypatch, tmp_path):
    """采纳端点：把技能库与进化服务都换成临时目录里的真服务。

    这条端点是前端「采纳」按钮唯一的落点（`evolutionApi.adoptDomainHarness`），
    此前零测试——连带它返回的是裸 `{code, data}` 而前端按 `evolutionApi` 命名空间调用
    这件事，也没人咬住。这里只钉两条：能出提案、提案进 pending 且不自动应用。
    """
    from neurova.api.deps import get_current_user as _get_current_user
    from neurova.api.deps import strictIdentityGate

    library = {
        "peer": {"manifest": {"config": {"context_template": "PEER BODY"}}},
        "target": {"manifest": {"config": {"context_template": "TARGET BODY"}}},
    }

    class _Library:
        def get_skill_info(self, skill_id):
            return library.get(skill_id)

    monkeypatch.setattr(
        "neurova.api.endpoints.text_evolution_api.agentLibrary", lambda agent_id: _Library()
    )
    # 进化目录由 `SkillEvolutionService` **局部** import（§3 的懒加载纪律），
    # 所以补丁打在源头模块上，不打在使用点模块上。
    monkeypatch.setattr(
        "neurova.core.agent_workspaces.get_agent_evolution_dir",
        lambda agent_id: tmp_path / agent_id,
    )

    from neurova.api.endpoints import text_evolution_api

    app = FastAPI()
    app.include_router(text_evolution_api.router, prefix="/v1/evolution")
    app.dependency_overrides[_get_current_user] = lambda: MOCK_USER
    # 管理员闸走 `require_role("admin")` → `strictIdentityGate`，覆盖的是**内层**那一个：
    # 覆盖 `require_admin()` 的返回值等于另造一个新依赖，端点里那个原样不动，照样 401。
    app.dependency_overrides[strictIdentityGate] = lambda: MOCK_USER
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_adopt_domain_harness_creates_pending_proposal(adoptClient):
    resp = adoptClient.post(
        "/v1/evolution/skills/agent/domain-harnesses/peer/adopt",
        json={"target_skill_id": "target"},
    )
    assert resp.status_code == 200, resp.text
    proposal = resp.json()["data"]
    assert proposal["status"] == "pending", "采纳只出提案，绝不自动应用"
    assert proposal["skill_id"] == "target"
    assert proposal["baseline_text"] == "TARGET BODY"
    assert proposal["improved_text"] == "PEER BODY"


def test_adopt_domain_harness_rejects_unknown_peer(adoptClient):
    resp = adoptClient.post(
        "/v1/evolution/skills/agent/domain-harnesses/nope/adopt",
        json={"target_skill_id": "target"},
    )
    assert resp.status_code == 404
