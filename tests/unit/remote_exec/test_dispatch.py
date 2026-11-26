# -*- coding: utf-8 -*-
"""W1b 统一分派漏斗 + 离线 hold——行为测试。

- 成功透传（output 原样返回、endpoint 转 online、事件 start/result）；
- connect 相位在 hold 窗口内指数退避重试后成功（sleepFn 注入假时钟，不真睡）；
- 窗口耗尽 → 「未执行、可安全重试」结果（executed=False、retryable=True、
  holdAttempts/holdElapsedMs 实测、退避 ×2 且单次上限 5s）；
- auth 相位不重试；executed="unknown" 不重试（已产输出不可盲目重试）；
- capability_missing / unknown_kind 结构化准入拒绝；
- 其他异常 → dispatch 相位失败；
- registry 故障不阻断分派结果；生命周期事件不携带明文凭据。
"""
from __future__ import annotations

import json

import pytest

from neurova.core import connection_pool as connection_pool_mod
from neurova.computer_use.ssh_runner import RemoteNotExecutedError
from neurova.remote_exec import dispatch as dispatch_mod
from neurova.remote_exec import registry as registry_mod
from neurova.remote_exec.dispatch import (
    DEFAULT_HOLD_TIMEOUT_MS,
    HOLD_TIMEOUT_ENV,
    RemoteDispatchError,
    dispatchRemoteCall,
)
from neurova.remote_exec.registry import (
    KIND_SSH,
    RemoteEndpoint,
    getRemoteEndpointRegistry,
)


@pytest.fixture()
def isolatedDataRoot(tmp_path, monkeypatch):
    """临时数据根 + 单例/连接池复位（health 落库走真实注册表）。"""
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path))
    connection_pool_mod.close_all_pools()
    registry_mod._REGISTRY_SINGLETON = None
    yield tmp_path
    connection_pool_mod.close_all_pools()
    registry_mod._REGISTRY_SINGLETON = None


def _endpoint(**overrides) -> RemoteEndpoint:
    fields = dict(
        endpointId="",
        kind=KIND_SSH,
        name="ssh:10.0.0.5:22",
        ownerId="agent-1",
        tenantId="default",
        capabilities={"exec": True},
        connectionRef="cred:ssh-prod-1",
    )
    fields.update(overrides)
    return RemoteEndpoint(**fields)


def _registeredEndpoint(**overrides) -> RemoteEndpoint:
    """先注册进真实注册表，再参与分派——health 写入可断言。"""
    return getRemoteEndpointRegistry().registerEndpoint(_endpoint(**overrides))


def _eventRecorder():
    """onEvent(name, payload) → [(name, payload)] 记录器。"""
    events = []

    def record(name, payload):
        events.append((name, payload))

    return events, record


def _connectFailure(attempt: int) -> RemoteNotExecutedError:
    return RemoteNotExecutedError(
        f"SSH 连接失败（第 {attempt} 次）: connection refused",
        phase="connect",
        retryable=True,
        executed=False,
    )


# ── 成功路径 ──


def test_successPassesExecutorOutputThrough(isolatedDataRoot):
    endpoint = _registeredEndpoint()
    seenParams = []

    def executor(params):
        seenParams.append(params)
        return {"stdout": "up 3 days", "exitCode": 0}

    events, recordEvent = _eventRecorder()
    result = dispatchRemoteCall(
        toolName="computer_ssh_exec",
        params={"command": "uptime"},
        endpoint=endpoint,
        executor=executor,
        onEvent=recordEvent,
    )

    assert seenParams == [{"command": "uptime"}]
    assert result.ok is True
    assert result.executed is True
    assert result.phase == "exec"
    assert result.retryable is False
    assert result.output == {"stdout": "up 3 days", "exitCode": 0}
    assert result.error is None
    assert result.holdAttempts == 0
    assert result.holdElapsedMs == 0
    assert result.endpointId == endpoint.endpointId
    assert result.kind == KIND_SSH

    # 成功 → 端点转 online 且 lastSeenAt 落库
    stored = getRemoteEndpointRegistry().getEndpoint(endpoint.endpointId)
    assert stored is not None
    assert stored.health == "online"
    assert stored.lastSeenAt is not None

    assert [name for name, _ in events] == ["remote_dispatch_start", "remote_dispatch_result"]
    resultEvent = events[-1][1]
    assert resultEvent["phase"] == "exec"
    assert resultEvent["ok"] is True
    assert isinstance(resultEvent["elapsedMs"], int)


# ── 离线 hold：窗口内重试后成功 ──


def test_connectPhaseRetriesWithinWindowThenSucceeds(isolatedDataRoot):
    endpoint = _registeredEndpoint()
    attempts = []

    def executor(params):
        attempts.append(1)
        if len(attempts) < 3:
            raise _connectFailure(len(attempts))
        return "done"

    sleeps = []
    events, recordEvent = _eventRecorder()
    result = dispatchRemoteCall(
        toolName="computer_ssh_exec",
        params={"command": "uptime"},
        endpoint=endpoint,
        executor=executor,
        holdTimeoutMs=10000,
        sleepFn=sleeps.append,
        onEvent=recordEvent,
    )

    assert result.ok is True
    assert result.executed is True
    assert result.phase == "exec"
    assert result.output == "done"
    assert len(attempts) == 3
    assert result.holdAttempts == 2
    assert result.holdElapsedMs == 1500  # 0.5s + 1.0s
    assert sleeps == [0.5, 1.0]

    assert [name for name, _ in events] == [
        "remote_dispatch_start",
        "remote_dispatch_retry",
        "remote_dispatch_retry",
        "remote_dispatch_result",
    ]
    assert events[1][1]["attempt"] == 1
    assert events[1][1]["delayMs"] == 500
    assert events[2][1]["attempt"] == 2
    assert events[2][1]["delayMs"] == 1000

    # hold 期间标 offline，最终成功转回 online
    stored = getRemoteEndpointRegistry().getEndpoint(endpoint.endpointId)
    assert stored is not None
    assert stored.health == "online"


# ── 离线 hold：窗口耗尽 ──


def test_windowExhaustedReturnsNotExecutedRetryable(isolatedDataRoot):
    endpoint = _registeredEndpoint()
    attempts = []

    def executor(params):
        attempts.append(1)
        raise _connectFailure(len(attempts))

    sleeps = []
    result = dispatchRemoteCall(
        toolName="computer_ssh_exec",
        params={"command": "uptime"},
        endpoint=endpoint,
        executor=executor,
        holdTimeoutMs=100,
        sleepFn=sleeps.append,
    )

    assert result.ok is False
    assert result.executed is False
    assert result.phase == "connect"
    assert result.retryable is True
    assert result.output is None
    assert "未执行、可安全重试" in result.error
    assert result.holdAttempts >= 1
    assert result.holdElapsedMs == 100  # 窗口封顶，不越界
    assert sum(sleeps) * 1000 <= 100
    assert len(attempts) == result.holdAttempts + 1  # 首次 + 重试次数

    stored = getRemoteEndpointRegistry().getEndpoint(endpoint.endpointId)
    assert stored is not None
    assert stored.health == "offline"


def test_backoffDoublesAndCapsAtFiveSeconds(isolatedDataRoot):
    def executor(params):
        raise _connectFailure(1)

    sleeps = []
    result = dispatchRemoteCall(
        toolName="computer_ssh_exec",
        params={},
        endpoint=_endpoint(),
        executor=executor,
        holdTimeoutMs=20000,
        sleepFn=sleeps.append,
    )

    # 首延 0.5s、×2、单次上限 5s；末次按剩余窗口收口
    assert sleeps == [0.5, 1.0, 2.0, 4.0, 5.0, 5.0, 2.5]
    assert result.holdAttempts == 7
    assert result.holdElapsedMs == 20000
    assert result.ok is False


def test_holdTimeoutDefaultsFromEnvWhenNotPassed(isolatedDataRoot, monkeypatch):
    monkeypatch.setenv(HOLD_TIMEOUT_ENV, "50")
    assert DEFAULT_HOLD_TIMEOUT_MS == 45000

    def executor(params):
        raise _connectFailure(1)

    sleeps = []
    result = dispatchRemoteCall(
        toolName="computer_ssh_exec",
        params={},
        endpoint=_endpoint(),
        executor=executor,
        sleepFn=sleeps.append,
    )

    assert result.ok is False
    assert result.holdElapsedMs == 50
    assert result.retryable is True


# ── 不重试路径 ──


def test_authPhaseDoesNotRetry(isolatedDataRoot):
    def executor(params):
        raise RemoteNotExecutedError("SSH 认证失败: bad password", phase="auth", retryable=True)

    sleeps = []
    result = dispatchRemoteCall(
        toolName="computer_ssh_exec",
        params={},
        endpoint=_endpoint(),
        executor=executor,
        holdTimeoutMs=10000,
        sleepFn=sleeps.append,
    )

    assert result.ok is False
    assert result.executed is False
    assert result.phase == "auth"
    assert result.retryable is True
    assert result.holdAttempts == 0
    assert result.holdElapsedMs == 0
    assert sleeps == []
    assert "认证失败" in result.error


def test_execTimeoutUnknownDoesNotRetry(isolatedDataRoot):
    attempts = []

    def executor(params):
        attempts.append(1)
        raise RemoteNotExecutedError(
            "SSH 命令执行超时（零输出，执行状态未知）",
            phase="timeout",
            retryable=False,
            executed="unknown",
        )

    sleeps = []
    result = dispatchRemoteCall(
        toolName="computer_ssh_exec",
        params={"command": "reboot"},
        endpoint=_endpoint(),
        executor=executor,
        holdTimeoutMs=10000,
        sleepFn=sleeps.append,
    )

    assert result.ok is False
    assert result.executed == "unknown"
    assert result.phase == "timeout"
    assert result.retryable is False
    assert result.holdAttempts == 0
    assert result.holdElapsedMs == 0
    assert attempts == [1]
    assert sleeps == []


def test_execUnknownPhaseDoesNotRetry(isolatedDataRoot):
    def executor(params):
        raise RemoteNotExecutedError(
            "已获部分输出后中断", phase="exec", retryable=False, executed="unknown"
        )

    sleeps = []
    result = dispatchRemoteCall(
        toolName="computer_ssh_exec",
        params={},
        endpoint=_endpoint(),
        executor=executor,
        holdTimeoutMs=10000,
        sleepFn=sleeps.append,
    )

    assert result.ok is False
    assert result.executed == "unknown"
    assert result.phase == "exec"
    assert result.retryable is False
    assert result.holdAttempts == 0
    assert result.holdElapsedMs == 0
    assert sleeps == []


def test_otherExceptionMapsToDispatchFailure(isolatedDataRoot):
    def executor(params):
        raise ValueError("boom")

    result = dispatchRemoteCall(
        toolName="computer_ssh_exec",
        params={},
        endpoint=_endpoint(),
        executor=executor,
    )

    assert result.ok is False
    assert result.executed is False
    assert result.phase == "dispatch"
    assert result.retryable is False
    assert "boom" in result.error


# ── 准入拒绝 ──


def test_capabilityMissingRejected(isolatedDataRoot):
    executorCalls = []

    def executor(params):
        executorCalls.append(1)
        return "should-not-run"

    with pytest.raises(RemoteDispatchError) as excinfo:
        dispatchRemoteCall(
            toolName="computer_ssh_exec",
            params={"command": "uptime"},
            endpoint=_endpoint(capabilities={"files": True}),
            executor=executor,
            requiredCapability="exec",
        )

    assert excinfo.value.reason == "capability_missing"
    assert excinfo.value.details == {"requiredCapability": "exec"}
    assert executorCalls == []


def test_unknownKindRejected(isolatedDataRoot):
    executorCalls = []

    def executor(params):
        executorCalls.append(1)
        return "should-not-run"

    with pytest.raises(RemoteDispatchError) as excinfo:
        dispatchRemoteCall(
            toolName="computer_ssh_exec",
            params={"command": "uptime"},
            endpoint=_endpoint(kind="telnet"),
            executor=executor,
        )

    assert excinfo.value.reason == "unknown_kind"
    assert excinfo.value.retryable is False
    assert executorCalls == []


# ── 事件 hygiene ──


def test_eventPayloadsNeverCarryConnectionRef(isolatedDataRoot):
    endpoint = _registeredEndpoint()
    attempts = []

    def executor(params):
        attempts.append(1)
        if len(attempts) < 2:
            raise _connectFailure(len(attempts))
        return "done"

    events, recordEvent = _eventRecorder()
    dispatchRemoteCall(
        toolName="computer_ssh_exec",
        params={"command": "uptime"},
        endpoint=endpoint,
        executor=executor,
        holdTimeoutMs=10000,
        sleepFn=lambda seconds: None,
        onEvent=recordEvent,
    )

    assert events, "至少应有 start/result 事件"
    for name, payload in events:
        serialized = json.dumps(payload, ensure_ascii=False)
        assert "cred:ssh-prod-1" not in serialized
        assert "connectionRef" not in serialized
    startPayload = events[0][1]
    assert startPayload["toolName"] == "computer_ssh_exec"
    assert startPayload["endpointId"] == endpoint.endpointId
    assert startPayload["kind"] == KIND_SSH


# ── registry 容错 ──


class _BrokenRegistry:
    def markEndpointSeen(self, *args, **kwargs):
        raise RuntimeError("registry db down")


def test_registryFailureDoesNotBlockSuccess(isolatedDataRoot, monkeypatch):
    monkeypatch.setattr(dispatch_mod, "getRemoteEndpointRegistry", lambda: _BrokenRegistry())

    result = dispatchRemoteCall(
        toolName="computer_ssh_exec",
        params={},
        endpoint=_endpoint(),
        executor=lambda params: {"ok": 1},
    )

    assert result.ok is True
    assert result.executed is True
    assert result.output == {"ok": 1}


def test_registryFailureDoesNotBlockOfflineHold(isolatedDataRoot, monkeypatch):
    monkeypatch.setattr(dispatch_mod, "getRemoteEndpointRegistry", lambda: _BrokenRegistry())

    def executor(params):
        raise _connectFailure(1)

    result = dispatchRemoteCall(
        toolName="computer_ssh_exec",
        params={},
        endpoint=_endpoint(),
        executor=executor,
        holdTimeoutMs=100,
        sleepFn=lambda seconds: None,
    )

    assert result.ok is False
    assert result.phase == "connect"
    assert result.retryable is True
    assert "未执行、可安全重试" in result.error
