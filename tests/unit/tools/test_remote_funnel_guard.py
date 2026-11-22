# -*- coding: utf-8 -*-
"""W1c 守卫：computer_ssh_exec 的统一分派漏斗接线（W1b，注册制增量接入）。

锁定的契约：
- 已登记端点 → 必经 dispatchRemoteCall 漏斗（requiredCapability="exec"、
  U1 两类主机密钥异常进 transparentExceptions），结果按 U3 语义映射回
  既有载荷形状；
- 未登记端点 → 漏斗不得被调，走既有直连路径（存量行为零变化）；
- 首次直连成功 → 端点登记进统一注册表（connectionRef=ssh-bucket:<uid>:<host>、
  capabilities={"exec": True}），此后同端点自动走漏斗；
- capability 缺失 → 结构化拒绝载荷（TOOL_UNSUPPORTED 风格），不崩不吞、不执行；
- 漏斗失败信封 → REMOTE_NOT_EXECUTED 载荷（executed="unknown" 时 retryable=False）；
- 端点登记/查询 fail-soft：注册表故障只告警，工具照常返回。
"""
from __future__ import annotations

import pytest

from neurova.core import connection_pool as connection_pool_mod
from neurova.computer_use.ssh_runner import (
    HostKeyConfirmationNeeded,
    HostKeyMismatchError,
)
from neurova.remote_exec import registry as registry_mod
from neurova.remote_exec.dispatch import RemoteDispatchResult
from neurova.remote_exec.registry import KIND_SSH, getRemoteEndpointRegistry

HOST = "h1"
PORT = 22
ENDPOINT_NAME = f"ssh:{HOST}:{PORT}"


@pytest.fixture()
def isolatedDataRoot(tmp_path, monkeypatch):
    """临时数据根 + 注册表单例/连接池复位（登记与查询走真实注册表）。"""
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path))
    connection_pool_mod.close_all_pools()
    registry_mod._REGISTRY_SINGLETON = None
    yield tmp_path
    connection_pool_mod.close_all_pools()
    registry_mod._REGISTRY_SINGLETON = None


def _makeExecutor():
    from neurova.tool_executor import ToolExecutor

    inst = ToolExecutor.__new__(ToolExecutor)
    inst._agent = type("A", (), {"current_session_id": "s1", "_current_user_id": "u1"})()
    return inst


def _patchSshHappyPath(monkeypatch, stdout="direct-ok"):
    """免弹卡凭据 + 直连执行体命中记录器。"""
    ran = []

    def fake_run(host, command, **kwargs):
        ran.append((host, command, kwargs))
        return {"returncode": 0, "stdout": stdout, "stderr": ""}

    monkeypatch.setattr(
        "neurova.computer_use.ssh_runner.resolve_ssh_credentials",
        lambda u, h: {"user": "root", "port": PORT},
    )
    monkeypatch.setattr("neurova.computer_use.ssh_runner.run_ssh_command", fake_run)
    return ran


def _patchEmit(monkeypatch):
    emitted = []

    async def fake_emit(self, tool, params, result, screenshot_base64=None, terminal=None):
        emitted.append({"tool": tool, "result": result, "terminal": terminal})

    monkeypatch.setattr("neurova.tool_executor.ToolExecutor._emit_computer_event", fake_emit)
    return emitted


def _funnelSentinel(monkeypatch, result=None):
    """把漏斗入口换成哨兵：记录入参、返回受控结果。"""
    calls = []

    def sentinel(**kwargs):
        calls.append(kwargs)
        if result is not None:
            return result
        return RemoteDispatchResult(
            ok=True, executed=True, phase="exec", retryable=False,
            endpointId=kwargs["endpoint"].endpointId, kind=KIND_SSH,
            output={"returncode": 0, "stdout": "via-funnel", "stderr": ""},
        )

    monkeypatch.setattr("neurova.remote_exec.dispatch.dispatchRemoteCall", sentinel)
    return calls


def _registerHostEndpoint(capabilities=None):
    return getRemoteEndpointRegistry().registerEndpoint(
        registry_mod.RemoteEndpoint(
            endpointId="", kind=KIND_SSH, name=ENDPOINT_NAME,
            ownerId="agent-1", tenantId="default",
            capabilities={"exec": True} if capabilities is None else capabilities,
            connectionRef="cred:ssh-prod-1",
        )
    )


# ── 已登记端点：必经漏斗 ──


@pytest.mark.asyncio
async def test_registeredEndpointRoutesThroughFunnel(isolatedDataRoot, monkeypatch):
    _registerHostEndpoint()
    ran = _patchSshHappyPath(monkeypatch)
    _patchEmit(monkeypatch)
    calls = _funnelSentinel(monkeypatch)

    inst = _makeExecutor()
    out = await inst._execute_computer_ssh_exec({"host": HOST, "command": "echo hi"})

    assert len(calls) == 1, "已登记端点必须经漏斗（哨兵被调一次）"
    kwargs = calls[0]
    assert kwargs["toolName"] == "computer_ssh_exec"
    assert kwargs["endpoint"].name == ENDPOINT_NAME
    assert kwargs["endpoint"].kind == KIND_SSH
    assert kwargs["requiredCapability"] == "exec"
    assert set(kwargs["transparentExceptions"]) == {
        HostKeyConfirmationNeeded, HostKeyMismatchError,
    }, "U1 两类主机密钥异常必须透传给调用方自有处理"
    assert ran == [], "漏斗路径不得再走既有直连执行体"
    assert out["success"] is True and out["stdout"] == "via-funnel"
    assert out["host"] == HOST and out["command"] == "echo hi"


@pytest.mark.asyncio
async def test_unregisteredEndpointStaysDirect(isolatedDataRoot, monkeypatch):
    """未登记端点：漏斗哨兵不得被调（注册制增量接入契约）。"""
    ran = _patchSshHappyPath(monkeypatch)
    _patchEmit(monkeypatch)
    calls = _funnelSentinel(monkeypatch)

    inst = _makeExecutor()
    out = await inst._execute_computer_ssh_exec({"host": HOST, "command": "ls"})

    assert calls == [], "未登记端点必须走既有直连路径，漏斗不得被调"
    assert len(ran) == 1 and ran[0][0] == HOST
    assert out["success"] is True and out["stdout"] == "direct-ok"


@pytest.mark.asyncio
async def test_firstSuccessRegistersThenSubsequentCallsUseFunnel(isolatedDataRoot, monkeypatch):
    """W1a→W1b 链：首次直连成功即登记；此后同端点自动走漏斗。"""
    _patchSshHappyPath(monkeypatch)
    _patchEmit(monkeypatch)
    inst = _makeExecutor()

    first = await inst._execute_computer_ssh_exec({"host": HOST, "command": "ls"})
    assert first["success"] is True

    found = getRemoteEndpointRegistry().findEndpoints(
        tenantId="default", kind=KIND_SSH, name=ENDPOINT_NAME)
    assert len(found) == 1, "首次成功必须登记进统一注册表"
    ep = found[0]
    assert ep.capabilities.get("exec") is True
    assert ep.connectionRef == "ssh-bucket:u1:h1"
    assert ep.ownerId == ""

    calls = _funnelSentinel(monkeypatch)
    second = await inst._execute_computer_ssh_exec({"host": HOST, "command": "uptime"})
    assert second["success"] is True
    assert len(calls) == 1, "登记后的第二次调用必须走漏斗"


# ── 漏斗失败信封映射 ──


@pytest.mark.asyncio
async def test_funnelNotExecutedEnvelopeKeepsU3Shape(isolatedDataRoot, monkeypatch):
    """ok=False 且 executed=False（如 hold 耗尽）→ U3 结构化载荷，retryable 透传。"""
    _registerHostEndpoint()
    _patchSshHappyPath(monkeypatch)
    _patchEmit(monkeypatch)
    _funnelSentinel(monkeypatch, result=RemoteDispatchResult(
        ok=False, executed=False, phase="connect", retryable=True,
        endpointId="ep", kind=KIND_SSH,
        error="远程端点在 3000ms 离线等待窗口内未恢复（重试 2 次）：未执行、可安全重试。",
        holdAttempts=2, holdElapsedMs=3000,
    ))

    inst = _makeExecutor()
    out = await inst._execute_computer_ssh_exec({"host": HOST, "command": "ls"})

    assert out["success"] is False
    assert out["error_code"] == "REMOTE_NOT_EXECUTED"
    assert out["phase"] == "connect"
    assert out["executed"] is False
    assert out["retryable"] is True
    assert out["holdAttempts"] == 2 and out["holdElapsedMs"] == 3000
    assert "未执行、可安全重试" in out["error"]
    assert out["host"] == HOST and out["command"] == "ls"


@pytest.mark.asyncio
async def test_funnelUnknownExecutedMapsRetryableFalse(isolatedDataRoot, monkeypatch):
    """executed="unknown"（已获部分输出后中断）→ retryable 恒 False，不可盲目重试。"""
    _registerHostEndpoint()
    _patchSshHappyPath(monkeypatch)
    _patchEmit(monkeypatch)
    _funnelSentinel(monkeypatch, result=RemoteDispatchResult(
        ok=False, executed="unknown", phase="exec", retryable=False,
        endpointId="ep", kind=KIND_SSH, error="已获部分输出后中断",
    ))

    inst = _makeExecutor()
    out = await inst._execute_computer_ssh_exec({"host": HOST, "command": "ls"})

    assert out["success"] is False
    assert out["error_code"] == "REMOTE_NOT_EXECUTED"
    assert out["executed"] == "unknown"
    assert out["retryable"] is False


# ── capability 缺失：结构化拒绝 ──


@pytest.mark.asyncio
async def test_capabilityMissingRejectedStructured(isolatedDataRoot, monkeypatch):
    """端点未声明 exec 能力 → TOOL_UNSUPPORTED 风格结构化拒绝，且不产生执行副作用。

    用真实漏斗（不换哨兵）：准入拒绝发生在任何执行副作用之前。
    """
    _registerHostEndpoint(capabilities={"files": True})
    ran = _patchSshHappyPath(monkeypatch)
    _patchEmit(monkeypatch)

    inst = _makeExecutor()
    out = await inst._execute_computer_ssh_exec({"host": HOST, "command": "ls"})

    assert ran == [], "capability 缺失必须发生在任何执行副作用之前"
    assert out["success"] is False
    assert out["error_code"] == "TOOL_UNSUPPORTED"
    assert "exec" in out["reason"]
    assert out["error"]


# ── 登记/查询 fail-soft ──


class _RegisterBoomRegistry:
    def findEndpoints(self, **kwargs):
        return []

    def registerEndpoint(self, endpoint):
        raise RuntimeError("registry db down")


class _LookupBoomRegistry:
    def findEndpoints(self, **kwargs):
        raise RuntimeError("registry db down")

    def registerEndpoint(self, endpoint):
        raise RuntimeError("registry db down")


@pytest.mark.asyncio
async def test_registerFailureFailSoft(isolatedDataRoot, monkeypatch):
    """登记失败只告警：直连成功照常返回，不被注册表故障阻断。"""
    ran = _patchSshHappyPath(monkeypatch)
    _patchEmit(monkeypatch)
    monkeypatch.setattr(
        "neurova.remote_exec.registry.getRemoteEndpointRegistry",
        lambda: _RegisterBoomRegistry(),
    )

    inst = _makeExecutor()
    out = await inst._execute_computer_ssh_exec({"host": HOST, "command": "ls"})

    assert len(ran) == 1
    assert out["success"] is True and out["stdout"] == "direct-ok"


@pytest.mark.asyncio
async def test_lookupFailureFailSoft(isolatedDataRoot, monkeypatch):
    """查询失败按未登记处理：走直连路径，工具照常返回。"""
    ran = _patchSshHappyPath(monkeypatch)
    _patchEmit(monkeypatch)
    monkeypatch.setattr(
        "neurova.remote_exec.registry.getRemoteEndpointRegistry",
        lambda: _LookupBoomRegistry(),
    )

    inst = _makeExecutor()
    out = await inst._execute_computer_ssh_exec({"host": HOST, "command": "ls"})

    assert len(ran) == 1
    assert out["success"] is True and out["stdout"] == "direct-ok"
