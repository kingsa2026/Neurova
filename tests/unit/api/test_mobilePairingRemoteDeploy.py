"""代部署（档三）API 咬合守卫：admin 门、任务轮询、诚实失败、凭据不外泄。"""
import json
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api import deps as apiDeps
from neurova.tunnel import connection_config as CC
from neurova.tunnel import remote_deploy as RD

PREFIX = "/api/v1/mobile"

ADMIN = {"user_id": "1", "username": "root-admin", "role": "admin",
         "neuser_id": "1", "tenant_id": "default"}
PLAIN_USER = {"user_id": "10006", "username": "chatverify", "role": "user",
              "neuser_id": "10006", "tenant_id": "default"}


class _FakeChannel:
    def __init__(self, rc):
        self._rc = rc

    def recv_exit_status(self):
        return self._rc


class _FakeStdout:
    def __init__(self, text, rc):
        self._text = text.encode("utf-8")
        self._rc = rc
        self.channel = _FakeChannel(rc)

    def read(self):
        return self._text


class _FakeStderr:
    def read(self):
        return b""


class _FakeStdin:
    def close(self):
        return


class FakeSshClient:
    def __init__(self, script):
        self.script = script
        self.executed = []

    def connect(self, **kwargs):
        self.connected = True

    def exec_command(self, command, timeout=None):
        self.executed.append(command)
        for key, rc, out in self.script:
            if key in command:
                return _FakeStdin(), _FakeStdout(out, rc), _FakeStderr()
        return _FakeStdin(), _FakeStdout("", 0), _FakeStderr()

    def close(self):
        pass


@pytest.fixture()
def api(monkeypatch, tmp_path):
    from neurova.api.endpoints import mobile_pairing as MP

    MP._pairing_codes.clear()
    MP.resetDeviceRegistry()
    path = CC.configFilePath()
    if path.exists():
        path.unlink()

    from neurova.web_reach import credentials as cred_mod

    store = cred_mod.UserCredentialStore(base_dir=str(tmp_path / "creds"))
    monkeypatch.setattr(cred_mod, "get_credential_store", lambda base_dir="": store)

    app = FastAPI()
    app.include_router(MP.router, prefix=PREFIX)
    current = {"identity": ADMIN}
    app.dependency_overrides[apiDeps.strictIdentityGate] = lambda: current["identity"]
    app.dependency_overrides[MP._get_current_user_id] = lambda: current["identity"]["user_id"]
    client = TestClient(app)

    yield {"client": client, "current": current}
    app.dependency_overrides.clear()
    MP._pairing_codes.clear()
    MP.resetDeviceRegistry()
    if path.exists():
        path.unlink()


def _waitSuccess(c, taskId, timeout=10.0):
    deadline = time.time() + timeout
    view = {}
    while time.time() < deadline:
        res = c.get(f"{PREFIX}/pairing/connection-config/remote-deploy/{taskId}")
        view = res.json()
        if view.get("state") != "running":
            return view
        time.sleep(0.02)
    return view


def test_non_admin_forbidden(api):
    api["current"]["identity"] = PLAIN_USER
    c = api["client"]
    body = {"host": "192.0.2.10", "username": "root", "password": "x"}
    assert c.post(f"{PREFIX}/pairing/connection-config/remote-deploy",
                  json=body).status_code == 403
    assert c.get(f"{PREFIX}/pairing/connection-config/remote-deploy/deploy-x").status_code == 403
    assert c.post(f"{PREFIX}/pairing/connection-config/remote-undeploy",
                  json=body).status_code == 403


def test_deploy_task_lifecycle_applies_config(api):
    script = [
        ("id -u", 0, "0"),
        ("cat /etc/neurova-relay/enrollment_token", 0, ""),
        ("curl", 0, "200"),
    ]
    RD.setSshClientFactory(lambda: FakeSshClient(script))
    c = api["client"]
    res = c.post(f"{PREFIX}/pairing/connection-config/remote-deploy", json={
        "host": "192.0.2.10", "username": "root", "password": "pw-1",
        "relay_port": 8443, "domain": "pair.example.com",
    })
    assert res.status_code == 200, res.text
    taskId = res.json()["task_id"]
    view = _waitSuccess(c, taskId)
    assert view["state"] == "success", view
    assert view["relay_url"] == "http://pair.example.com:8443"
    assert "pw-1" not in json.dumps(view), "凭据不得出现在任务视图"
    cfg = CC.getConnectionConfig()
    assert cfg["mode"] == "relay"
    assert cfg["relay_url"] == "http://pair.example.com:8443"
    assert cfg["has_relay_enrollment_token"] is True


def test_deploy_missing_credentials_422(api):
    RD.setSshClientFactory(lambda: FakeSshClient([]))
    c = api["client"]
    res = c.post(f"{PREFIX}/pairing/connection-config/remote-deploy",
                 json={"host": "192.0.2.10", "username": "root"})
    assert res.status_code == 422, res.text


def test_deploy_unknown_task_404(api):
    c = api["client"]
    assert c.get(f"{PREFIX}/pairing/connection-config/remote-deploy/deploy-nope").status_code == 404


def test_undeploy_resets_mode(api):
    script = [("systemctl", 0, "")]
    RD.setSshClientFactory(lambda: FakeSshClient(script))
    c = api["client"]
    CC.setConnectionConfig(mode="relay", relayUrl="http://pair.example.com:8443",
                           relayEnrollmentToken="tok-1")
    res = c.post(f"{PREFIX}/pairing/connection-config/remote-undeploy",
                 json={"host": "192.0.2.10", "username": "root", "password": "pw-1"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["state"] == "success", body
    assert CC.getConnectionConfig()["mode"] == "auto"
