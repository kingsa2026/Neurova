"""N0 Build API：一句话需求 → 问答 → 批次批准。"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.deps import get_current_user
from neurova.api.endpoints import build_mode as build_ep
from neurova.build_mode import build_session as bs


def _assessment(ready: bool, questions=None):
    return json.dumps(
        {
            "ready": ready,
            "checklist": {
                "goal": ready,
                "target": ready,
                "nodes": ready,
                "params": ready,
                "env": ready,
                "permissions": ready,
                "budget": ready,
                "safe_version": True,
            },
            "build_plan": {"summary": "构建广告流程"},
            "questions": questions or [],
        },
        ensure_ascii=False,
    )


class _FakeLlm:
    def __init__(self):
        self.calls = 0
        self.responses = [
            _assessment(
                False,
                [
                    {
                        "id": "q1",
                        "question": "目标是什么？",
                        "kind": "text",
                        "why": "目标不明",
                        "impact": "决定节点",
                    }
                ],
            ),
            _assessment(True),
        ]

    async def chat(self, messages, model=None):
        value = self.responses[min(self.calls, len(self.responses) - 1)]
        self.calls += 1
        return SimpleNamespace(content=value)


@pytest.fixture
def client(tmp_path, monkeypatch):
    fake_agent = SimpleNamespace(
        config=SimpleNamespace(owner_user_id="u1", llm_model="fake"),
        llm_client=_FakeLlm(),
    )
    monkeypatch.setattr("neurova.api.endpoints.get_agent_instance", lambda agent_id: fake_agent)
    monkeypatch.setenv("NEUROVA_BUILD_SESSIONS", str(tmp_path / "build.json"))
    bs.reset_build_session_manager()

    app = FastAPI()
    app.include_router(build_ep.router, prefix="/api/v1/build")
    app.dependency_overrides[get_current_user] = lambda: {
        "user_id": "u1",
        "username": "user1",
        "role": "admin",
    }
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    bs.reset_build_session_manager()


def test_start_answer_approve(client):
    start = client.post(
        "/api/v1/build/sessions",
        json={"request": "帮我搭一条广告复盘流程", "agent_id": "default"},
    )
    assert start.status_code == 200, start.text
    session = start.json()["data"]["session"]
    assert session["status"] == "clarifying"
    assert session["rounds"][0]["questions"][0]["id"] == "q1"

    answer = client.post(
        f"/api/v1/build/sessions/{session['session_id']}/answers",
        json={
            "answers": [
                {"id": "q1", "selected": [], "custom": "按 ACOS 复盘并给预算建议"}
            ]
        },
    )
    assert answer.status_code == 200, answer.text
    updated = answer.json()["data"]["session"]
    assert updated["status"] == "ready"

    approved = client.post(f"/api/v1/build/sessions/{session['session_id']}/approve", json={})
    assert approved.status_code == 200, approved.text
    approved_session = approved.json()["data"]["session"]
    assert approved_session["status"] == "building"
    assert approved_session["batch_id"].startswith("build_batch_")


def test_unauthorized_is_rejected(client):
    client.app.dependency_overrides.pop(get_current_user, None)
    r = client.get("/api/v1/build/sessions/does-not-exist")
    assert r.status_code in (401, 403, 404)


def test_pausedAskUserBecomesBuildInteractionEvent():
    from neurova.api.endpoints.console import _extract_build_interaction

    payload = {
        "success": True,
        "status": "paused",
        "build_session_id": "build_1",
        "interaction_id": "int_1",
        "interaction": {
            "interaction_id": "int_1",
            "question": {
                "id": "q1",
                "question": "选哪个店铺？",
                "kind": "choice",
                "options": [{"label": "店铺 A"}],
                "multi": False,
                "allow_custom": True,
                "why": "需要 profileId",
                "impact": "影响数据源",
                "secret_key": "",
                "timeout_seconds": 600,
            },
        },
    }
    event = _extract_build_interaction(json.dumps(payload, ensure_ascii=False), {})
    assert event["build_session_id"] == "build_1"
    assert event["interaction_id"] == "int_1"
    assert event["question"] == "选哪个店铺？"
    assert event["kind"] == "choice"
