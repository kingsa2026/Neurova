"""质量事件/指标 API。"""
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api import auth as knowledge_auth
from neurova.api.endpoints import quality as quality_module
from neurova.quality.outcome_store import ConversationQualityStore

ALICE = {"user_id": "1", "username": "alice", "role": "user", "neuser_id": "1"}
ADMIN = {"user_id": "9", "username": "admin", "role": "admin", "neuser_id": "9"}
PREFIX = "/v1/quality"


@pytest.fixture()
def api(tmp_path, monkeypatch):
    store = ConversationQualityStore(str(tmp_path / "quality.db"))
    monkeypatch.setattr(quality_module, "get_quality_store", lambda: store)
    app = FastAPI()
    app.include_router(quality_module.router, prefix=PREFIX)
    holder = {"user": dict(ADMIN)}
    app.dependency_overrides[knowledge_auth.get_current_user_or_service] = lambda: holder["user"]
    yield TestClient(app), holder, store
    store.close()


def test_takeover_event_and_metrics(api):
    client, _holder, store = api
    resp = client.post(PREFIX + "/outcomes", json={
        "event_type": "human_takeover_started", "session_id": "s1",
        "source": "console_mark", "source_event_id": "op-1",
    })
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["duplicate"] is False

    store.recordTurnOutcome("t1", "s1", outcome="answered")
    metrics = client.get(PREFIX + "/metrics").json()["data"]
    assert metrics["turns"] == 1
    assert metrics["human_takeover_rate"] == 1.0
    assert metrics["takeover_sources"] == {"console_mark": 1}


def test_explicit_turn_outcome_endpoint(api):
    client, _holder, store = api

    resp = client.post(PREFIX + "/turn-outcomes", json={
        "turn_id": "t-explicit", "session_id": "s1",
        "outcome": "tool_failure", "channel": "console",
    })

    assert resp.status_code == 200, resp.text
    metrics = store.metrics()
    assert metrics["outcomes"]["tool_failure"] == 1
    assert metrics["tool_failure_rate"] == 1.0


def test_explicit_outcome_overrides_pipeline_classification(api):
    client, _holder, store = api
    store.recordTurnOutcome("t-override", "s1", outcome="answered")

    resp = client.post(PREFIX + "/turn-outcomes", json={
        "turn_id": "t-override", "session_id": "s1",
        "outcome": "tool_failure",
    })

    assert resp.status_code == 200, resp.text
    metrics = client.get(PREFIX + "/metrics").json()["data"]
    assert metrics["turns"] == 1
    assert metrics["turn_outcome_events"] == 2
    assert metrics["outcomes"] == {"tool_failure": 1}


def test_metrics_report_channel_takeover_capability(api, monkeypatch):
    client, _holder, _store = api
    manager = MagicMock()
    manager.list_adapters.return_value = {
        "feishu": {"human_takeover_events": False},
        "native-helpdesk": {"human_takeover_events": True},
    }
    monkeypatch.setattr(
        "neurova.channels.manager.get_channel_manager", lambda: manager
    )

    data = client.get(PREFIX + "/metrics").json()["data"]

    assert data["takeover_channel_capability"] == {
        "supported": ["native-helpdesk"],
        "unsupported": ["feishu"],
    }


def test_takeover_state_round_trip(api):
    """开始→true，结束→false；无事件时 observed=False，不冒充「未接管」。"""
    client, _holder, _store = api
    path = PREFIX + "/sessions/s-state/takeover"

    empty = client.get(path).json()["data"]
    assert empty["observed"] is False and empty["active"] is False

    client.post(PREFIX + "/outcomes", json={
        "event_type": "human_takeover_started", "session_id": "s-state",
        "source": "console_mark",
    })
    started = client.get(path).json()["data"]
    assert started["observed"] is True and started["active"] is True

    client.post(PREFIX + "/outcomes", json={
        "event_type": "human_takeover_ended", "session_id": "s-state",
        "source": "console_mark",
    })
    ended = client.get(path).json()["data"]
    assert ended["observed"] is True and ended["active"] is False


def test_non_admin_gets_403(api):
    client, holder, _store = api
    holder["user"] = dict(ALICE)
    assert client.get(PREFIX + "/metrics").status_code == 403
    assert client.post(PREFIX + "/outcomes", json={
        "event_type": "human_takeover_started", "session_id": "s1",
    }).status_code == 403
    assert client.get(PREFIX + "/sessions/s1/takeover").status_code == 403
