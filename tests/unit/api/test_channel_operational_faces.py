"""DEAD-13：渠道队列/出口台账读面与按 ID 重排端点判据。"""
from __future__ import annotations

import os
import sqlite3
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_dead_13_32_bytes_minimum")

from neurova.api.auth import get_current_user
from neurova.api.endpoints import channel_config as cc
from neurova.api.endpoints import set_app_state
from neurova.channels.base import ChannelMessage
from neurova.channels.channel_ingress_queue import ChannelIngressQueue
from neurova.channels.outbound_ledger import OutboundFailureLedger

ADMIN = {"user_id": "root", "username": "root", "role": "admin"}
OWNER = {"user_id": "u1", "username": "u1", "role": "user"}
STRANGER = {"user_id": "u2", "username": "u2", "role": "user"}
BASE = "/api/v1/channel-configs"


def _agent(owner):
    return SimpleNamespace(
        agent_id="kai", config=SimpleNamespace(owner_user_id=owner, agent_id="kai")
    )


def _deadLetter(queue, message_id: str, channel: str, agent: str) -> int:
    queue.enqueue(
        ChannelMessage(
            channel_type=channel, message_id=message_id, sender_id="u1",
            sender_name="User", content="hello", chat_id="chat-1",
        ),
        agent_id=agent,
    )
    event = queue.claim(worker="test")
    assert event is not None
    queue.nack(event.event_id, "boom")
    return event.event_id


@pytest.fixture()
def env(tmp_path, monkeypatch):
    queue = ChannelIngressQueue(tmp_path / "ingress.db", max_attempts=1)
    ledger = OutboundFailureLedger(tmp_path / "outbound.db")
    manager = SimpleNamespace(
        ingress_queue=queue, outbound_ledger=ledger,
        _get_ingress_queue=lambda: queue, _get_outbound_ledger=lambda: ledger,
    )
    monkeypatch.setattr(cc, "get_channel_manager", lambda: manager)
    set_app_state({"agents": {"default": _agent(None), "kai": _agent("u1")}})

    app = FastAPI()
    app.include_router(cc.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: dict(OWNER)

    auditLogger = SimpleNamespace(entries=[])
    auditLogger.log = auditLogger.entries.append
    monkeypatch.setattr(
        "neurova.security.audit_logger.get_audit_logger", lambda: auditLogger
    )
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client, app, queue, ledger, auditLogger
    finally:
        queue.close()
        ledger.close()
        app.dependency_overrides.clear()
        set_app_state(None)


def _as(app, identity):
    app.dependency_overrides[get_current_user] = lambda: dict(identity)


def test_operationalReadsRequireExplicitAgent(env):
    client, _, _, _, _ = env
    assert client.get(f"{BASE}/ingress/dead-letters").status_code == 422
    assert client.get(f"{BASE}/outbound/failures").status_code == 422
    assert client.post(f"{BASE}/ingress/dead-letters/requeue", json={"event_ids": [1]}).status_code == 422


def test_ownerReadsOnlyOwnDeadLettersWithOptionalChannel(env):
    client, app, queue, _, _ = env
    _deadLetter(queue, "kai-feishu", "feishu", "kai")
    _deadLetter(queue, "kai-telegram", "telegram", "kai")
    _deadLetter(queue, "other-feishu", "feishu", "other")

    response = client.get(f"{BASE}/ingress/dead-letters", params={"agent_id": "kai"})
    assert response.status_code == 200, response.text
    assert {row["message_id"] for row in response.json()["dead_letters"]} == {
        "kai-feishu", "kai-telegram"
    }

    filtered = client.get(
        f"{BASE}/ingress/dead-letters",
        params={"agent_id": "kai", "channel_type": "feishu"},
    )
    assert filtered.status_code == 200, filtered.text
    assert [row["message_id"] for row in filtered.json()["dead_letters"]] == ["kai-feishu"]

    _as(app, STRANGER)
    denied = client.get(f"{BASE}/ingress/dead-letters", params={"agent_id": "kai"})
    assert denied.status_code == 403, denied.text


def test_requeueUsesOnlySelectedIdsAndWritesAudit(env):
    client, app, queue, _, auditLogger = env
    selected = _deadLetter(queue, "selected", "feishu", "kai")
    _deadLetter(queue, "not-selected", "feishu", "kai")
    _deadLetter(queue, "other-agent", "feishu", "other")

    response = client.post(
        f"{BASE}/ingress/dead-letters/requeue",
        params={"agent_id": "kai", "channel_type": "feishu"},
        json={"event_ids": [selected]},
    )
    assert response.status_code == 200, response.text
    assert response.json()["requeued"] == 1
    assert [row["message_id"] for row in queue.list_dead_letters(agent_id="kai")] == [
        "not-selected"
    ]
    assert [row["message_id"] for row in queue.list_dead_letters(agent_id="other")] == [
        "other-agent"
    ]
    assert len(auditLogger.entries) == 1
    entry = auditLogger.entries[0]
    assert entry.user_id == OWNER["user_id"]
    assert entry.action == "channel_ingress_dead_letter_requeue"
    assert entry.details["agent_id"] == "kai"
    assert entry.details["event_ids"] == [selected]
    assert entry.details["requeued"] == 1

    _as(app, STRANGER)
    denied = client.post(
        f"{BASE}/ingress/dead-letters/requeue",
        params={"agent_id": "kai"}, json={"event_ids": [selected]},
    )
    assert denied.status_code == 403, denied.text
    assert len(auditLogger.entries) == 1


def test_requeueRejectsEmptyIdsAndMissingQueueIs503(env, monkeypatch):
    client, _, _, _, auditLogger = env
    empty = client.post(
        f"{BASE}/ingress/dead-letters/requeue",
        params={"agent_id": "kai"}, json={"event_ids": []},
    )
    assert empty.status_code == 422, empty.text

    monkeypatch.setattr(
        cc, "get_channel_manager",
        lambda: SimpleNamespace(_get_ingress_queue=lambda: None),
    )
    unavailable = client.post(
        f"{BASE}/ingress/dead-letters/requeue",
        params={"agent_id": "kai"}, json={"event_ids": [1]},
    )
    assert unavailable.status_code == 503, unavailable.text
    assert auditLogger.entries == []


def test_readFailuresAreHonest5xx(env, monkeypatch):
    client, _, queue, ledger, _ = env

    def failRead(**kwargs):
        raise sqlite3.OperationalError("read database unavailable")

    monkeypatch.setattr(queue, "list_dead_letters", failRead)
    response = client.get(f"{BASE}/ingress/dead-letters", params={"agent_id": "kai"})
    assert response.status_code == 500, response.text
    assert "read database unavailable" in response.json()["detail"]

    monkeypatch.setattr(ledger, "queryFailures", failRead)
    response = client.get(f"{BASE}/outbound/failures", params={"agent_id": "kai"})
    assert response.status_code == 500, response.text
    assert "read database unavailable" in response.json()["detail"]


def test_outboundFailuresAreAgentScopedAndKeepChannelChatFilters(env):
    client, app, _, ledger, _ = env
    for agent, channel, chat in (
        ("kai", "feishu", "chat-a"),
        ("kai", "feishu", "chat-b"),
        ("other", "feishu", "chat-a"),
    ):
        ledger.recordFailure(
            channel_type=channel, chat_id=chat, agent_id=agent,
            part_index=1, total_parts=1, attempts=2, error="boom", content="secret-head",
        )

    response = client.get(
        f"{BASE}/outbound/failures",
        params={"agent_id": "kai", "channel_type": "feishu", "chat_id": "chat-a"},
    )
    assert response.status_code == 200, response.text
    assert len(response.json()["failures"]) == 1
    assert response.json()["failures"][0]["agent_id"] == "kai"
    assert response.json()["failures"][0]["chat_id"] == "chat-a"

    _as(app, STRANGER)
    assert client.get(f"{BASE}/outbound/failures", params={"agent_id": "kai"}).status_code == 403


def test_operationalRoutesRequireLogin(env):
    client, app, _, _, _ = env
    app.dependency_overrides.pop(get_current_user)
    assert client.get(f"{BASE}/ingress/dead-letters", params={"agent_id": "kai"}).status_code == 401
    assert client.get(f"{BASE}/outbound/failures", params={"agent_id": "kai"}).status_code == 401
