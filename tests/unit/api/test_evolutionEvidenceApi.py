"""成功/失败执行证据的只读审计面。"""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.deps import get_current_user
from neurova.api.endpoints import text_evolution_api as api
from neurova.evolution.skill_evidence import recordExecutionEvidence

BASE = "/api/v1/evolution"
USER = {"user_id": "u1", "username": "alice", "role": "user", "neuser_id": "u1"}
ADMIN = {"user_id": "u1", "username": "admin", "role": "admin", "neuser_id": "u1"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path / "data"))
    written = recordExecutionEvidence(
        "a1",
        "sk",
        user_input="hello",
        params={},
        result=SimpleNamespace(
            success=True,
            data={"text": "answer"},
            error="",
            metadata={},
            execution_time=0.1,
        ),
    )
    record = SimpleNamespace(
        success=True,
        input_summary="hello",
        output_summary="answer",
        error_message="",
        metadata={"evidence_ref": written["evidence_ref"]},
    )

    import neurova.evolution.skill_improver as improver

    monkeypatch.setattr(
        improver,
        "get_skill_improver",
        lambda: SimpleNamespace(get_usage_history=lambda skill_id: [record]),
    )

    app = FastAPI()
    app.include_router(api.router, prefix=BASE)
    with TestClient(app) as c:
        c.app.dependency_overrides[get_current_user] = lambda: USER
        c.app.dependency_overrides[api._admin_dep] = lambda: ADMIN
        yield c


def test_success_evidence_reads_full_trajectory(client):
    r = client.get(f"{BASE}/skills/a1/evidence/sk", params={"kind": "success"})
    assert r.status_code == 200, r.text
    items = r.json()["data"]["items"]
    assert len(items) == 1
    assert items[0]["user_input"] == "hello"
    assert "answer" in items[0]["output"]
    assert items[0]["outcome"] == "success"


def test_kind_filters_success_and_failure(client):
    r = client.get(f"{BASE}/skills/a1/evidence/sk", params={"kind": "failure"})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["items"] == []


def test_invalid_kind_is_422(client):
    r = client.get(f"{BASE}/skills/a1/evidence/sk", params={"kind": "nope"})
    assert r.status_code == 422, r.text
