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


# ── F1 线乙：catalog 透出能力声明 + kind 取值收口单源 ─────────────────────


def test_catalogItemsDeclareCapabilities(client):
    from neurova.api.endpoints import external_agents_api
    from neurova.agent.neuacp.catalog import EXECUTOR_KINDS

    # kind 取值唯一事实源：管理面 VALID_KINDS 必须引用 catalog.EXECUTOR_KINDS
    assert external_agents_api.VALID_KINDS == EXECUTOR_KINDS
    resp = client.get(f"{BASE}/catalog", headers=adminHeaders())
    assert resp.status_code == 200, resp.text
    items = resp.json()
    assert items, "目录非空"
    for item in items:
        caps = item.get("capabilities")
        assert isinstance(caps, dict), f"{item['tool']} 的 catalog 响应缺 capabilities"
        assert {"transports", "permission_modes", "streaming", "resume", "session_reuse"} <= set(caps), item["tool"]
        assert isinstance(caps["transports"], list), "transports 出口须为 list（JSON 可序列化）"
        assert isinstance(caps["permission_modes"], list), "permission_modes 出口须为 list（JSON 可序列化）"


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
    # 真机 CLIs 的握手回包字段是 agentCapabilities（G2 录制实证）——
    # /test 必须把规范字段的能力透传出来，而非静默给空 dict。
    assert "tools" in data["serverCapabilities"], data


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


# ── F2 线戊：帧账本读面 GET /runs/{subagent_id}/frames（设计文档 §3.2，拍板 D-C） ──
#
# 数据根隔离按仓约定（tests/conftest.py 导入期把 NEUROVA_DATA_DIR 钉进会话临时目录）；
# 每条用例用独立 subagent_id，避免同会话内互相串账本。


def _framesUrl(sid: str) -> str:
    return f"{BASE}/runs/{sid}/frames"


def test_framesRouteIsRegistered(client):
    """路由清单与真路由表双向核对：frames 端点必须真的挂上 app。"""
    paths = client.app.openapi()["paths"]
    assert any("/external-agents/runs/{subagent_id}/frames" in p for p in paths), sorted(paths)


def test_framesRequiresAdmin(client):
    """与 catalog/test/status 同门：未认证 401，非 admin 403。"""
    assert client.get(_framesUrl("sw_frames_gate")).status_code == 401
    assert client.get(_framesUrl("sw_frames_gate"), headers=userHeaders()).status_code == 403


def test_framesAdminSameTenantReadsAscending(client):
    from neurova.agent.neuacp.frame_log import appendFrame

    sid = "sw_frames_read_asc"
    seq1 = appendFrame(sid, "in", {"jsonrpc": "2.0", "method": "session/prompt"})
    seq2 = appendFrame(sid, "out", {"jsonrpc": "2.0", "id": 1, "result": {}})
    seq3 = appendFrame(sid, "observed", {"type": "exited", "exit_code": 0})
    resp = client.get(_framesUrl(sid), headers=adminHeaders())
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["subagent_id"] == sid
    assert data["count"] == 3
    seqs = [f["seq"] for f in data["frames"]]
    assert seqs == [seq1, seq2, seq3], "frames 必须按 seq 升序全序回放"
    assert all("frame" in f and "direction" in f for f in data["frames"])


def test_framesAfterSeqCursorReturnsOnlyLaterFrames(client):
    from neurova.agent.neuacp.frame_log import appendFrame

    sid = "sw_frames_cursor"
    seqs = [appendFrame(sid, "in", {"n": i}) for i in range(5)]
    first = client.get(_framesUrl(sid), headers=adminHeaders(), params={"limit": 2}).json()
    assert [f["seq"] for f in first["frames"]] == seqs[:2]
    second = client.get(
        _framesUrl(sid), headers=adminHeaders(), params={"after_seq": seqs[1], "limit": 2}
    )
    assert second.status_code == 200, second.text
    second = second.json()
    assert [f["seq"] for f in second["frames"]] == seqs[2:4], "第二页只含比游标更大的 seq"
    assert second["count"] == 2


def test_framesCrossTenantRunNotFound(client):
    """run 租户线索（H-4 lineage）与请求者租户不同 → 404，不泄露存在性。"""
    from neurova.agent.swarm_event_log import appendRunEvent

    sid = "sw_frames_cross_tenant"
    appendRunEvent(sid, "spawned", {}, lineage={"tenant_id": "tenant-other"})
    resp = client.get(_framesUrl(sid), headers=adminHeaders())
    assert resp.status_code == 404, resp.text


def test_framesSameTenantLineagePasses(client):
    """run 租户线索与请求者租户一致 → 200（admin 同租户读自己的 run）。"""
    from neurova.agent.neuacp.frame_log import appendFrame
    from neurova.agent.swarm_event_log import appendRunEvent

    sid = "sw_frames_same_tenant"
    appendRunEvent(sid, "spawned", {}, lineage={"tenant_id": "default"})
    appendFrame(sid, "in", {"a": 1})
    resp = client.get(_framesUrl(sid), headers=adminHeaders())
    assert resp.status_code == 200, resp.text
    assert resp.json()["count"] == 1


def test_framesInMemoryRunTenantChecked(client, monkeypatch):
    """租户解析①：swarm 管理器内存 run 的 tenant_id 优先参与同租户校验。"""
    from types import SimpleNamespace

    from neurova.agent.swarm import get_swarm_manager

    sid = "sw_frames_mem_tenant"
    manager = get_swarm_manager()
    monkeypatch.setitem(manager._runs, sid, SimpleNamespace(tenant_id="tenant-other"))
    resp = client.get(_framesUrl(sid), headers=adminHeaders())
    assert resp.status_code == 404, resp.text


def test_framesUnknownRunNotFound(client):
    """无帧记录且无任何租户线索 → 404（run 不存在或无帧记录）。"""
    resp = client.get(_framesUrl("sw_frames_never_existed"), headers=adminHeaders())
    assert resp.status_code == 404, resp.text


def test_framesLimitClampedToThousand(client):
    """limit=5000 超上限 → 生效值 1000（返回 count 上限体现夹取）。"""
    from neurova.agent.neuacp.frame_log import appendFrame

    sid = "sw_frames_limit_clamp"
    for i in range(1001):
        appendFrame(sid, "in", {"n": i})
    resp = client.get(_framesUrl(sid), headers=adminHeaders(), params={"limit": 5000})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["count"] == 1000, "limit 夹取到 [1,1000] 上限"
    assert len(data["frames"]) == 1000


def test_framesLimitFloorClampedToOne(client):
    """limit=0 低于下限 → 生效值 1。"""
    from neurova.agent.neuacp.frame_log import appendFrame

    sid = "sw_frames_limit_floor"
    appendFrame(sid, "in", {"n": 1})
    appendFrame(sid, "in", {"n": 2})
    resp = client.get(_framesUrl(sid), headers=adminHeaders(), params={"limit": 0})
    assert resp.status_code == 200, resp.text
    assert resp.json()["count"] == 1


def test_framesNegativeAfterSeqTreatedAsZero(client):
    """after_seq 负数按 0 处理，不全空。"""
    from neurova.agent.neuacp.frame_log import appendFrame

    sid = "sw_frames_neg_cursor"
    appendFrame(sid, "in", {"n": 1})
    resp = client.get(_framesUrl(sid), headers=adminHeaders(), params={"after_seq": -5})
    assert resp.status_code == 200, resp.text
    assert resp.json()["count"] == 1


# ── M6：/status 必须读池真实水位（原 getattr 落空恒占位） ──────────────────


class _FakePoolProc:
    def __init__(self):
        self.terminated = False
    def is_alive(self):
        return not self.terminated
    def terminate(self):
        self.terminated = True
    def close(self):
        self.terminated = True


def test_statusReportsRealPoolSnapshot(client, monkeypatch):
    from neurova.agent.neuacp import process_pool as pp

    pool = pp.NeuacpProcessPool(maxProcs=4, idleSeconds=600)
    monkeypatch.setattr(pp, "_poolInstance", pool)
    key = pp.poolKey("tenant_a", "opencode", ["opencode"], "/tmp/wk", "stdio", "")
    entry = pool.acquire(key, lambda: _FakePoolProc())
    pool.release(key, entry)  # 归还成 idle → 快照应见真实条目

    resp = client.get(f"{BASE}/status", headers=adminHeaders())
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data.get("live") == 1, f"池快照应报真实存活数: {data}"
    assert data.get("idle") == 1
    assert data.get("busy") == 0
    assert data.get("max_procs") == 4
    assert isinstance(data.get("processes"), list) and len(data["processes"]) == 1
    assert data["processes"][0]["tool"] == "opencode"
    assert data["processes"][0]["tenant"] == "tenant_a"
