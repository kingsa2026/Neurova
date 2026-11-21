# -*- coding: utf-8 -*-
"""G1 卡：ACP registry 零代码接入（official registry → catalog 合并 → admin 刷新面）。

- 解析归一：官方 registry.json 真实形状（version/agents[]/extensions[]，条目
  distribution ∈ npx|binary|uvx）→ 目录条目（command argv / transport=stdio /
  install_hint / 保守能力缺省 / protocol_version / source="registry"）。
- 合并优先级：预设（CATALOG）> registry，同名预设胜出；本地直配层是运行时
  事实源（名册 executor.command），位于目录之上，不在本目录合并面内。
- 安全边界：默认关（不刷新零网络请求）；网络失败 stale 降级保留上次快照；
  体积上限 5MiB 拒收；admin 门（非 admin 403）。
- 协议版本：条目声明 protocolVersion → 目录透出 → 执行体 client.start 按声明
  版本协商（缺省 "1" 行为不变；v2 仅按声明协商，语义面待 spec 另评）。

测试纪律：解析/合并/降级用注入 fetch（不联网）；握手与 /test 面用真 stdio
假 agent 子进程（非 mock 冒充，教义第 3 条）。
"""
import asyncio
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from neurova.agent.neuacp.acp_executor import NeuacpStdioExecutor
from neurova.agent.neuacp.catalog import (
    CATALOG,
    capabilitiesFor,
    defaultCommand,
    listCatalog,
    mergedCatalog,
    protocolVersionFor,
    refuseExecutorSpec,
)
from neurova.agent.neuacp.executor import NeuacpSessionContext
from neurova.agent.neuacp.registry import (
    FETCH_TIMEOUT_S,
    MAX_PAYLOAD_BYTES,
    REGISTRY_URL,
    AcpRegistry,
    RegistryFetchError,
    RegistryParseError,
    fetchRegistry,
    getAcpRegistry,
    parseRegistry,
    resetAcpRegistry,
)
from tests.auth_headers import bearerHeaders

_SAMPLE_PATH = Path(__file__).resolve().parent / "registry_sample.json"
_NEUACP_TEST_DIR = Path(__file__).resolve().parent
_FAKE_ACP_AGENT = str(_NEUACP_TEST_DIR / "fake_acp_agent.py")
_STRICT_AGENT = str(_NEUACP_TEST_DIR / "strict_initialize_agent.py")

_BASE = "/api/v1/external-agents"

_BOOLEAN_DIMS = (
    "streaming", "resume", "session_reuse", "handoff_inject",
    "model_switch_in_session", "conversation_rollback", "steer", "fork",
)


def _loadSample() -> dict:
    return json.loads(_SAMPLE_PATH.read_text(encoding="utf-8"))


def _boom(url, timeout):
    raise OSError("network unreachable")


@pytest.fixture(autouse=True)
def _freshRegistrySingleton():
    """每个用例前后复位单例，避免快照跨用例串扰。"""
    resetAcpRegistry()
    yield
    resetAcpRegistry()


# ── 解析归一：脱敏样本（真实形状裁剪） ─────────────────────────────────────


def test_sampleParsesToNormalizedEntries():
    entries = parseRegistry(_loadSample())
    byTool = {entry["tool"]: entry for entry in entries}
    assert set(byTool) == {"cline", "opencode", "fast-agent", "sample-v2-agent"}

    cline = byTool["cline"]
    assert cline["kind"] == "acp"
    assert cline["transport"] == "stdio"
    assert cline["command"] == ["npx", "cline@3.0.74", "--acp"], "npx 形态 → npx + package + args"
    assert cline["requires_node"] is True
    assert cline["source"] == "registry"
    assert cline["protocol_version"] == "1", "未声明 protocolVersion 按 ACP v1 缺省（v1 全量保持）"
    assert cline["install_hint"] == "npx cline@3.0.74"
    caps = cline["capabilities"]
    assert caps["transports"] == ("stdio",), "能力保守缺省：只放行 stdio"
    assert caps["permission_modes"] == ("chain",), "能力保守缺省：只放行 chain"
    for dim in _BOOLEAN_DIMS:
        assert not caps.get(dim), f"布尔维度 {dim} 缺省必须 False（fail-closed）"

    opencode = byTool["opencode"]
    assert opencode["command"][0] in ("./opencode.exe", "./opencode"), "binary 形态取当前平台档 cmd"
    assert opencode["command"][1:] == ["acp"]
    assert opencode["install_hint"].startswith("https://"), "binary 形态 install_hint 指向归档下载"

    fastAgent = byTool["fast-agent"]
    assert fastAgent["command"] == ["uvx", "fast-agent-acp==0.10.63", "-x"], "uvx 形态 → uvx + package + args"
    assert fastAgent["requires_node"] is False

    assert byTool["sample-v2-agent"]["protocol_version"] == "2", "条目声明 v2 → 目录透出 2"


def test_missingFieldsHandledConservatively():
    entries = parseRegistry({"agents": [
        {"id": "", "name": "missing-id"},
        {"id": "missing-name", "name": ""},
        "not-a-dict",
        42,
        None,
        {"id": "no-dist", "name": "No Dist"},
        {"id": "empty-dist", "name": "Empty Dist", "distribution": {}},
        {"id": "bad-npx", "name": "Bad Npx", "distribution": {"npx": {"package": ""}}},
        {"id": "bad-version", "name": "Bad Version",
         "distribution": {"npx": {"package": "x@1"}}, "protocolVersion": "2.0-beta"},
        {"id": "ok", "name": "Ok", "website": "https://example.com/ok",
         "distribution": {"npx": {"package": "ok@1"}}, "protocolVersion": 2},
    ]})
    byTool = {entry["tool"]: entry for entry in entries}
    assert set(byTool) == {"no-dist", "empty-dist", "bad-npx", "bad-version", "ok"}, "缺关键字段的条目保守丢弃"
    assert byTool["no-dist"]["command"] == [], "无可推导命令 → 空 argv（只登记不安装）"
    assert byTool["no-dist"]["install_hint"] == ""
    assert byTool["empty-dist"]["command"] == []
    assert byTool["bad-npx"]["command"] == [], "npx 缺 package 不可用 → 空 argv"
    assert byTool["bad-npx"]["install_hint"] == ""
    assert byTool["bad-version"]["protocol_version"] == "1", "非整数声明保守回落 v1"
    assert byTool["ok"]["protocol_version"] == "2"
    assert byTool["ok"]["install_hint"] == "npx ok@1"


def test_malformedPayloadsRejected():
    with pytest.raises(RegistryParseError):
        parseRegistry(None)
    with pytest.raises(RegistryParseError):
        parseRegistry("not-a-dict")
    with pytest.raises(RegistryParseError):
        parseRegistry({"unexpected": []})
    with pytest.raises(RegistryParseError):
        parseRegistry({"agents": "not-a-list"})
    assert parseRegistry({"agents": []}) == []


def test_duplicateRegistryIdsKeepFirst():
    entries = parseRegistry({"agents": [
        {"id": "dup", "name": "First"},
        {"id": "dup", "name": "Second"},
    ]})
    assert [entry["name"] for entry in entries] == ["First"], "同 id 首个胜出（保守）"


# ── fetch：体积上限 / 超时边界 ─────────────────────────────────────────────


class _FakeStream:
    def __init__(self, chunks):
        self._chunks = list(chunks)

    def read(self, size=-1):
        return self._chunks.pop(0) if self._chunks else b""

    def close(self):
        pass


def test_fetchRejectsOversizedPayload():
    chunk = b"x" * 65536
    oversized = _FakeStream([chunk] * (MAX_PAYLOAD_BYTES // len(chunk) + 1))
    with pytest.raises(RegistryFetchError):
        fetchRegistry(opener=lambda url, timeout: oversized)


def test_fetchUsesBoundedTimeoutAndReturnsPayload():
    seen = {}

    def opener(url, timeout):
        seen["url"] = url
        seen["timeout"] = timeout
        return _FakeStream([json.dumps(_loadSample()).encode("utf-8")])

    payload = fetchRegistry(opener=opener)
    assert seen["url"] == REGISTRY_URL
    assert seen["timeout"] <= 15, "timeout ≤ 15s"
    assert FETCH_TIMEOUT_S <= 15
    assert payload["version"] == "1.0.0"


def test_defaultOpenSendsProjectUserAgent(monkeypatch):
    """缺省打开器必须自报 User-Agent：官方 CDN 对缺省 Python-urllib UA 回 403。"""
    import urllib.request

    from neurova.agent.neuacp import registry as registryModule

    captured = {}

    def fakeUrlopen(request, timeout=None):
        captured["request"] = request
        return _FakeStream([b"{}"])

    monkeypatch.setattr(urllib.request, "urlopen", fakeUrlopen)
    registryModule._defaultOpen(REGISTRY_URL, 5.0)
    request = captured["request"]
    assert request.full_url == REGISTRY_URL
    assert request.get_header("User-agent") == registryModule.FETCH_USER_AGENT, \
        "拉取须带项目 User-Agent（官方 CDN 拒收无身份的缺省 urllib UA）"


# ── 合并优先级：预设 > registry（同名预设胜出） ────────────────────────────


def test_presetWinsOverSameNameRegistryEntry():
    reg = getAcpRegistry()
    status = reg.refresh(fetch_fn=lambda url, timeout: _loadSample())
    assert status["stale"] is False and status["entry_count"] == 4

    merged = mergedCatalog()
    assert merged["opencode"]["source"] == "preset", "同名冲突预设胜出"
    assert merged["opencode"]["command"] == list(CATALOG["opencode"]["command"])
    assert merged["cline"]["source"] == "registry", "registry 独有条目照常并入"
    assert merged["sample-v2-agent"]["protocol_version"] == "2"

    names = [item["tool"] for item in listCatalog()]
    assert names.count("opencode") == 1, "同名只暴露胜出方一份"
    assert "cline" in names and "sample-v2-agent" in names


def test_mergedViewFeedsCapabilitiesRefusalAndVersion():
    getAcpRegistry().refresh(fetch_fn=lambda url, timeout: _loadSample())
    assert capabilitiesFor("cline")["transports"] == ["stdio"], "registry 条目走保守能力档"
    assert capabilitiesFor("cline")["permission_modes"] == ["chain"]
    assert capabilitiesFor("opencode")["permission_modes"] == ["chain", "auto"], "预设档不被 registry 覆盖"
    assert defaultCommand("cline") == ["npx", "cline@3.0.74", "--acp"]
    assert defaultCommand("not-a-tool") is None

    assert refuseExecutorSpec({"kind": "acp", "tool": "cline", "transport": "stdio",
                               "permission_mode": "chain"}) == [], "registry 条目 stdio+chain 放行"
    reasons = refuseExecutorSpec({"kind": "acp", "tool": "cline", "transport": "stdio",
                                  "permission_mode": "auto"})
    assert reasons and "permission_mode" in "; ".join(reasons), "保守档 auto 拒（fail-closed）"

    assert protocolVersionFor("cline") == "1"
    assert protocolVersionFor("sample-v2-agent") == "2"
    assert protocolVersionFor("opencode") == "1", "预设缺省 v1"
    assert protocolVersionFor("not-a-tool") == "1"


# ── 快照语义：成功 / stale 降级 / fail-closed ──────────────────────────────


def test_refreshSuccessRecordsSnapshotStatus():
    reg = AcpRegistry()
    status = reg.refresh(fetch_fn=lambda url, timeout: _loadSample())
    assert status["stale"] is False
    assert status["error"] is None
    assert status["fetched_at"]
    assert status["entry_count"] == 4
    assert status["source_url"] == REGISTRY_URL
    assert len(reg.entries()) == 4
    assert reg.snapshotStatus()["entry_count"] == 4


def test_refreshFailureKeepsStaleSnapshot():
    reg = AcpRegistry()
    reg.refresh(fetch_fn=lambda url, timeout: _loadSample())
    before = reg.entries()
    failed = reg.refresh(fetch_fn=_boom)
    assert failed["stale"] is True
    assert failed["error"], "失败原因诚实回填"
    assert reg.entries() == before, "网络失败保留上次快照，不用空表"
    assert reg.snapshotStatus()["entry_count"] == len(before)
    assert reg.snapshotStatus()["fetched_at"], "fetched_at 仍指向上次成功刷新"


def test_firstFetchFailureFailsClosedWithoutFabrication():
    reg = AcpRegistry()
    status = reg.refresh(fetch_fn=_boom)
    assert status["stale"] is True
    assert status["error"]
    assert status["entry_count"] == 0
    assert reg.entries() == [], "无快照可保留时空表 + 诚实标注，不臆造条目"


# ── 默认关：不刷新零网络请求 ───────────────────────────────────────────────


def test_defaultOffNoNetworkOnCatalogPaths(monkeypatch):
    def _noNetwork(*args, **kwargs):
        raise AssertionError("默认关：目录/条目路径不得发起网络请求")

    monkeypatch.setattr("urllib.request.urlopen", _noNetwork)
    assert getAcpRegistry().entries() == []
    assert getAcpRegistry().snapshotStatus()["fetched_at"] is None
    assert mergedCatalog()["opencode"]["source"] == "preset"
    assert [item["tool"] for item in listCatalog()]
    assert protocolVersionFor("cline") == "1"


# ── 成员执行体：按条目声明版本协商（真 stdio，缺省 "1" 行为不变） ───────────


def _startExecutor(protocolVersion=None):
    kwargs = {"request_timeout": 30.0, "cwd": str(_NEUACP_TEST_DIR)}
    if protocolVersion is not None:
        kwargs["protocol_version"] = protocolVersion
    executor = NeuacpStdioExecutor([sys.executable, _STRICT_AGENT], **kwargs)
    ctx = NeuacpSessionContext(member_session_id="g1-version", task_text="ping",
                                cwd=str(_NEUACP_TEST_DIR))

    async def _run():
        await executor.start(ctx)

    asyncio.run(_run())
    return executor


def test_executorPassesDeclaredProtocolVersionToClientStart():
    executor = _startExecutor("2")
    try:
        handshake = executor._client._handshake
        assert handshake["protocolVersion"] == 2, "条目声明 v2 → client.start 按 v2 协商"
    finally:
        asyncio.run(executor.close())


def test_executorDefaultsToV1BehaviorUnchanged():
    executor = _startExecutor()
    try:
        handshake = executor._client._handshake
        assert handshake["protocolVersion"] == 1, '缺省 "1" 行为不变（v1 全量保持）'
    finally:
        asyncio.run(executor.close())


# ── 管理面：admin 刷新端点 + catalog 透出 + /test 面可发现（真 create_app） ──


@pytest.fixture(scope="module")
def client():
    from neurova.api.app import create_app

    app = create_app(enable_memory=False, enable_channels=False)
    return TestClient(app)


def _adminHeaders():
    return bearerHeaders("g1-admin", role="admin")


def _userHeaders():
    return bearerHeaders("g1-user", role="user")


def _e2ePayload() -> dict:
    """样本 + 可真跑的 e2e 条目（binary cmd=本解释器 + 真 stdio 假 agent）。"""
    payload = _loadSample()
    payload["agents"].append({
        "id": "sample-e2e-agent",
        "name": "Sample E2E Agent",
        "distribution": {"binary": {"windows-x86_64": {
            "cmd": sys.executable, "args": [_FAKE_ACP_AGENT],
        }}},
    })
    return payload


def test_registryRefreshRequiresAdmin(client, monkeypatch):
    reg = getAcpRegistry()
    monkeypatch.setattr(reg, "_fetch_fn", lambda url, timeout: _loadSample())
    assert client.post(f"{_BASE}/registry/refresh").status_code == 401, "未认证 401"
    assert client.post(f"{_BASE}/registry/refresh", headers=_userHeaders()).status_code == 403, "非 admin 403"


def test_registryRefreshLoadsEntriesAndCatalogExposesThem(client, monkeypatch):
    reg = getAcpRegistry()
    monkeypatch.setattr(reg, "_fetch_fn", lambda url, timeout: _e2ePayload())
    resp = client.post(f"{_BASE}/registry/refresh", headers=_adminHeaders())
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["stale"] is False
    assert data["error"] is None
    assert data["fetched_at"]
    tools = {entry["tool"] for entry in data["entries"]}
    assert {"cline", "opencode", "fast-agent", "sample-v2-agent", "sample-e2e-agent"} <= tools

    items = client.get(f"{_BASE}/catalog", headers=_adminHeaders()).json()
    byTool = {item["tool"]: item for item in items}
    assert byTool["cline"]["source"] == "registry"
    assert byTool["cline"]["protocol_version"] == "1"
    assert byTool["sample-v2-agent"]["protocol_version"] == "2"
    assert byTool["opencode"]["source"] == "preset", "catalog 响应透出 source/protocol_version"

    # /test 面可发现：registry 条目的 argv 可直接做握手探测（真 stdio 假 agent）
    command = byTool["sample-e2e-agent"]["command"]
    assert command == [sys.executable, _FAKE_ACP_AGENT]
    probe = client.post(f"{_BASE}/test", headers=_adminHeaders(),
                        json={"kind": "acp", "tool": "sample-e2e-agent", "command": command})
    assert probe.status_code == 200, probe.text
    assert probe.json()["ok"] is True, probe.json()
    assert probe.json()["protocolVersion"] == "1"


def test_registryRefreshNetworkFailureReturnsStaleHonestly(client, monkeypatch):
    reg = getAcpRegistry()
    monkeypatch.setattr(reg, "_fetch_fn", _boom)
    resp = client.post(f"{_BASE}/registry/refresh", headers=_adminHeaders())
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["stale"] is True
    assert data["error"], "网络失败以诚实形态暴露（stale + error），不静默吞掉"
    assert data["entries"] == []
