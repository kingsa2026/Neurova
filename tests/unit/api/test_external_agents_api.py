# -*- coding: utf-8 -*-
"""B4：外部编码代理管理面（/v1/external-agents）契约测试。

真 create_app（走 ENDPOINT_MODULES 注册表挂载）+ 真 JWT（bearerHeaders），
不打身份 override——连「注册表是否真的挂上本 router」一起验。/test 的
握手探测用测试内假 agent 子进程（真 stdio，非 mock 冒充，遵守教义第 3 条）。

设计文档 §4.7：catalog / test / status 三端点，admin 门（非 admin 403）。
"""
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient

from tests.auth_headers import bearerHeaders

_NEUACP_TEST_DIR = Path(__file__).resolve().parents[1] / "agent" / "neuacp"
FAKE_ACP_AGENT = str(_NEUACP_TEST_DIR / "fake_acp_agent.py")
FAKE_ZCODE_CLI = str(_NEUACP_TEST_DIR / "fake_zcode_cli.py")

BASE = "/api/v1/external-agents"


@pytest.fixture(scope="module")
def client():
    from neurova.api.app import create_app

    app = create_app(enable_memory=False, enable_channels=False)
    return TestClient(app)


def adminHeaders():
    return bearerHeaders("b4-admin", role="admin")


def userHeaders():
    return bearerHeaders("b4-user", role="user")


# ── 鉴权门：外部代理是本机进程派生面，必须 admin ──────────────────────────


def test_catalogRequiresAdmin(client):
    assert client.get(f"{BASE}/catalog").status_code == 401
    assert client.get(f"{BASE}/catalog", headers=userHeaders()).status_code == 403


def test_testRequiresAdmin(client):
    body = {"kind": "acp", "command": ["x"]}
    assert client.post(f"{BASE}/test", json=body).status_code == 401
    assert client.post(f"{BASE}/test", json=body, headers=userHeaders()).status_code == 403


def test_statusRequiresAdmin(client):
    assert client.get(f"{BASE}/status").status_code == 401
    assert client.get(f"{BASE}/status", headers=userHeaders()).status_code == 403


# ── catalog：内置预设 + 本机安装探测 ──────────────────────────────────────


def test_catalogListsPresetsWithInstallProbe(client):
    resp = client.get(f"{BASE}/catalog", headers=adminHeaders())
    assert resp.status_code == 200, resp.text
    items = resp.json()
    names = {item["tool"] for item in items}
    assert {"opencode", "qoder", "codebuddy", "zcode", "gemini-cli", "claude-code", "codex"} <= names
    for item in items:
        assert "installed" in item, "每项必须带本机安装探测结果"
        assert "install_hint" in item, "未装时前端靠 install_hint 展示安装指引"


# ── test：握手级连通测试 ─────────────────────────────────────────────────


def test_testAcpHandshakeWithFakeAgent(client):
    resp = client.post(
        f"{BASE}/test",
        headers=adminHeaders(),
        json={
            "kind": "acp",
            "tool": "opencode",
            "command": [sys.executable, FAKE_ACP_AGENT],
            "cwd": str(_NEUACP_TEST_DIR),
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["ok"] is True, data
    assert data["protocolVersion"] == "1"
    assert isinstance(data.get("serverCapabilities"), dict)


def test_testAcpNonAgentProcessFailsHonestly(client):
    resp = client.post(
        f"{BASE}/test",
        headers=adminHeaders(),
        json={
            "kind": "acp",
            "command": [sys.executable, "-c", "print('not a json-rpc agent')"],
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["ok"] is False
    assert data.get("error"), "连通失败必须带错误原文"


def test_testAcpEmptyCommandRejected(client):
    resp = client.post(f"{BASE}/test", headers=adminHeaders(), json={"kind": "acp", "command": []})
    assert resp.status_code == 400


def test_testUnknownKindRejected(client):
    resp = client.post(
        f"{BASE}/test",
        headers=adminHeaders(),
        json={"kind": "carrier-pigeon", "command": ["x"]},
    )
    assert resp.status_code == 400


def test_testPluginProbeWithFakeCli(client):
    resp = client.post(
        f"{BASE}/test",
        headers=adminHeaders(),
        json={
            "kind": "plugin",
            "tool": "zcode",
            "command": [sys.executable, FAKE_ZCODE_CLI],
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["ok"] is True, resp.json()


def test_testPluginUnreachableFailsHonestly(client):
    resp = client.post(
        f"{BASE}/test",
        headers=adminHeaders(),
        json={"kind": "plugin", "command": ["no-such-cli-b4-probe"]},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["ok"] is False
    assert data.get("error")


# ── status：进程池状态（B3 落地前占位） ───────────────────────────────────


def test_statusPoolPlaceholderUntilB3(client):
    resp = client.get(f"{BASE}/status", headers=adminHeaders())
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "processes" in data
    assert isinstance(data["processes"], list)
