# -*- coding: utf-8 -*-
"""Computer HTTP 面的属主隔离、公开 DTO 与静态路由顺序回归。"""

import hashlib
import re

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from neurova.api.endpoints import computer_api
from neurova.collaboration.computer_manager import ComputerManager
from neurova.models.computer import ComputerEngine, ComputerKind


ALICE = {"user_id": "alice", "username": "alice", "role": "user"}
BOB = {"user_id": "bob", "username": "bob", "role": "user"}
ADMIN = {"user_id": "admin", "username": "admin", "role": "admin"}
BASE = "/api/v1/computers"


@pytest.fixture()
def computerClient(tmp_path, monkeypatch):
    manager = ComputerManager(data_dir=str(tmp_path / "computers"))
    monkeypatch.setattr(computer_api, "get_computer_manager_singleton", lambda: manager)
    holder = {"user": dict(ALICE)}
    app = FastAPI()
    app.include_router(computer_api.router, prefix="/api/v1")
    app.dependency_overrides[computer_api.get_current_user] = lambda: holder["user"]
    with TestClient(app) as client:
        yield client, manager, holder


def _create(manager, owner=ALICE["user_id"], *, name="device", kind=ComputerKind.LOCAL):
    computer = manager.create_computer(
        name=name,
        owner_user_id=owner,
        kind=kind,
        engine=ComputerEngine.CLAUDE_CODE,
    )
    assert computer is not None
    return computer


def _issueTicket(client, computerId):
    response = client.post(f"{BASE}/{computerId}/pair-token")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert set(payload) == {"pair_token", "expires_in"}
    assert isinstance(payload["pair_token"], str)
    assert len(payload["pair_token"]) >= 32
    assert payload["expires_in"] > 0
    return payload["pair_token"]


def _pair(client, computerId, token):
    return client.post(
        f"{BASE}/{computerId}/pair",
        json={
            "pair_token": token,
            "host_name": "host.local",
            "available_engines": ["claude"],
            "daemon_version": "1.0.0",
            "supervised": False,
        },
    )


def _assertPublic(payload):
    assert "daemon_token" not in payload
    assert "credential_hash" not in payload


def _assertNoSecretText(response, secret):
    _assertPublic(response.json())
    assert secret not in response.text
    assert hashlib.sha256(secret.encode("utf-8")).hexdigest() not in response.text


@pytest.mark.parametrize("operation", ["deleteSoft", "deleteHard", "revoke", "pair"])
def test_nonOwnerMutationsAreRejectedWithoutStateChange(computerClient, operation):
    client, manager, holder = computerClient
    computer = _create(manager)
    ticket = "caller-selected-secret"
    holder["user"] = dict(BOB)

    if operation == "deleteSoft":
        response = client.delete(f"{BASE}/{computer.computer_id}")
    elif operation == "deleteHard":
        response = client.delete(f"{BASE}/{computer.computer_id}", params={"hard": "true"})
    elif operation == "revoke":
        response = client.post(f"{BASE}/{computer.computer_id}/revoke")
    else:
        response = _pair(client, computer.computer_id, ticket)

    assert response.status_code == 404, response.text
    stored = manager.get_computer(computer.computer_id, user_id=ALICE["user_id"])
    assert stored is computer
    assert computer.daemon_token is None
    assert computer.revoked_at is None
    assert computer.status.value == "offline"


def test_listAndDetailAreOwnerScoped(computerClient):
    client, manager, holder = computerClient
    aliceComputer = _create(manager, name="alice-device")
    bobComputer = _create(manager, owner=BOB["user_id"], name="bob-device")

    listed = client.get(BASE)
    assert listed.status_code == 200
    assert {row["computer_id"] for row in listed.json()} == {aliceComputer.computer_id}

    hidden = client.get(f"{BASE}/{bobComputer.computer_id}")
    assert hidden.status_code == 404
    own = client.get(f"{BASE}/{aliceComputer.computer_id}")
    assert own.status_code == 200
    assert own.json()["computer_id"] == aliceComputer.computer_id

    holder["user"] = dict(BOB)
    assert {row["computer_id"] for row in client.get(BASE).json()} == {bobComputer.computer_id}


def test_emptyIdentityFailsClosedOnOwnerSurfaces(computerClient):
    client, manager, holder = computerClient
    computer = _create(manager)
    holder["user"] = {"user_id": "", "username": "anonymous", "role": "user"}

    assert client.get(BASE).status_code == 401
    assert client.get(f"{BASE}/{computer.computer_id}").status_code == 401
    assert client.post(f"{BASE}/{computer.computer_id}/pair-token").status_code == 401
    assert client.delete(f"{BASE}/{computer.computer_id}").status_code == 401
    assert client.post(f"{BASE}/{computer.computer_id}/revoke").status_code == 401


def test_callerCannotChoosePairingTicket(computerClient):
    client, manager, _holder = computerClient
    computer = _create(manager)

    response = _pair(client, computer.computer_id, "caller-selected-secret")

    assert response.status_code == 401, response.text
    assert computer.daemon_token is None
    assert computer.paired_at is None


def test_pairSuccessReturnsDaemonCredentialExactlyOnce(computerClient):
    client, manager, _holder = computerClient
    computer = _create(manager)
    ticket = _issueTicket(client, computer.computer_id)

    paired = _pair(client, computer.computer_id, ticket)
    assert paired.status_code == 200, paired.text
    payload = paired.json()
    assert set(payload) == {"computer", "daemon_token"}
    _assertPublic(payload["computer"])
    secret = payload["daemon_token"]
    assert secret != ticket
    assert len(secret) >= 32
    assert computer.daemon_token == hashlib.sha256(secret.encode("utf-8")).hexdigest()

    replay = _pair(client, computer.computer_id, ticket)
    assert replay.status_code == 401
    assert secret not in replay.text

    detail = client.get(f"{BASE}/{computer.computer_id}")
    listed = client.get(BASE)
    _assertNoSecretText(detail, secret)
    _assertNoSecretText(listed, secret)

    heartbeat = client.post(
        f"{BASE}/{computer.computer_id}/heartbeat",
        headers={"Authorization": f"Bearer {secret}"},
    )
    assert heartbeat.status_code == 200
    digestHeartbeat = client.post(
        f"{BASE}/{computer.computer_id}/heartbeat",
        params={"token": hashlib.sha256(secret.encode("utf-8")).hexdigest()},
    )
    assert digestHeartbeat.status_code == 200
    ticketHeartbeat = client.post(
        f"{BASE}/{computer.computer_id}/heartbeat",
        params={"token": ticket},
    )
    assert ticketHeartbeat.status_code == 401


def test_revokeInvalidatesDaemonCredential(computerClient):
    client, manager, _holder = computerClient
    computer = _create(manager)
    ticket = _issueTicket(client, computer.computer_id)
    secret = _pair(client, computer.computer_id, ticket).json()["daemon_token"]

    revoked = client.post(f"{BASE}/{computer.computer_id}/revoke")
    assert revoked.status_code == 200, revoked.text
    _assertNoSecretText(revoked, secret)
    heartbeat = client.post(
        f"{BASE}/{computer.computer_id}/heartbeat",
        headers={"Authorization": f"Bearer {secret}"},
    )
    assert heartbeat.status_code == 401


def test_regularResponsesNeverExposeCredentialFields(computerClient):
    client, manager, holder = computerClient
    computer = _create(manager)
    legacySecret = "legacy-daemon-secret"
    computer.daemon_token = hashlib.sha256(legacySecret.encode("utf-8")).hexdigest()
    manager._save_computer(computer)

    responses = [
        client.get(BASE),
        client.get(f"{BASE}/{computer.computer_id}"),
        client.post(BASE, params={"name": "created", "kind": "local"}),
    ]
    holder["user"] = dict(ADMIN)
    adminResponse = client.get(f"{BASE}/admin/all")
    assert adminResponse.status_code == 200, adminResponse.text
    responses.append(adminResponse)

    for response in responses:
        assert response.status_code == 200, response.text
        _assertNoSecretText(response, legacySecret)
        if isinstance(response.json(), list):
            for row in response.json():
                _assertPublic(row)
        else:
            _assertPublic(response.json())


def test_cloudAndAdminStaticRoutesPrecedeDynamicDetail(computerClient):
    client, manager, holder = computerClient
    cloud = _create(manager, name="cloud-device", kind=ComputerKind.CLOUD)
    local = _create(manager, name="local-device")

    specs = [(route.path, frozenset(route.methods or ())) for route in computer_api.router.routes if isinstance(route, APIRoute)]
    dynamicIndex = specs.index(("/computers/{computer_id}", frozenset({"GET"})))
    for staticPath in ("/computers/cloud", "/computers/admin/all"):
        staticIndex = specs.index((staticPath, frozenset({"GET"})))
        assert staticIndex < dynamicIndex, f"{staticPath} 仍注册在动态详情之后"

    cloudResponse = client.get(f"{BASE}/cloud")
    assert cloudResponse.status_code == 200, cloudResponse.text
    assert cloudResponse.json()["computer_id"] == cloud.computer_id

    holder["user"] = dict(ADMIN)
    adminResponse = client.get(f"{BASE}/admin/all")
    assert adminResponse.status_code == 200, adminResponse.text
    assert {row["computer_id"] for row in adminResponse.json()} == {cloud.computer_id, local.computer_id}

    holder["user"] = dict(ALICE)
    detailResponse = client.get(f"{BASE}/{local.computer_id}")
    assert detailResponse.status_code == 200
    assert detailResponse.json()["computer_id"] == local.computer_id


def test_routeOrderGuardDetectsSyntheticRegression():
    def specsFor(router):
        return [(route.path, frozenset(route.methods or ())) for route in router.routes if isinstance(route, APIRoute)]

    def firstMatch(specs, method, path):
        for routePath, methods in specs:
            if method not in methods:
                continue
            regex = re.sub(r"{[^}]+}", "[^/]+", routePath)
            if re.fullmatch(regex, path):
                return routePath
        return None

    bad = FastAPI()
    bad.get("/{computer_id}")(lambda computer_id: None)
    bad.get("/cloud")(lambda: None)
    assert firstMatch(specsFor(bad.router), "GET", "/cloud") == "/{computer_id}"


def test_publicDtoSchemaExcludesCredentials():
    app = FastAPI()
    app.include_router(computer_api.router, prefix="/api/v1")
    schemas = app.openapi()["components"]["schemas"]
    computerSchema = schemas["ComputerPublic"]["properties"]
    assert "daemon_token" not in computerSchema
    assert "credential_hash" not in computerSchema

    pairSchema = schemas["ComputerPairResponse"]["properties"]
    assert set(pairSchema) == {"computer", "daemon_token"}
