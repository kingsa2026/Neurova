# -*- coding: utf-8 -*-
"""W1b 扩展：dispatchRemoteCall 的 transparentExceptions 透传（唯一扩展点）。

- 默认空元组：既有行为逐字节不变（未知异常 → dispatch 相位失败信封，不上抛）；
- 命中透明名单：onEvent("remote_dispatch_result") 发出后**原样重抛**（同一异常
  对象、原 traceback），供调用方（tool_executor SSH 支路）对 U1 主机确认卡/
  指纹冲突保留自有处理；
- 未命中名单：仍走统一信封映射，不上抛；
- 透明优先于离线 hold：命中名单的 connect 相位可重试异常不进 hold 重试。
"""
from __future__ import annotations

import pytest

from neurova.computer_use.ssh_runner import (
    HostKeyConfirmationNeeded,
    HostKeyMismatchError,
    RemoteNotExecutedError,
)
from neurova.remote_exec.dispatch import dispatchRemoteCall
from neurova.remote_exec.registry import KIND_SSH, RemoteEndpoint


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


def _eventRecorder():
    events = []

    def record(name, payload):
        events.append((name, payload))

    return events, record


# ── 默认行为（不传 transparentExceptions）逐字节不变 ──


def test_defaultUnknownExceptionStillMapsToEnvelope():
    """默认空名单：未知异常照旧映射 dispatch 相位失败信封，不上抛。"""
    sentinel = RuntimeError("boom")

    def executor(params):
        raise sentinel

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
    assert "boom" in (result.error or "")


def test_defaultRemoteNotExecutedStillMappedNotRaised():
    """默认空名单：RemoteNotExecutedError 照旧映射信封，不上抛。"""

    def executor(params):
        raise RemoteNotExecutedError("SSH 连接失败: refused", phase="connect")

    result = dispatchRemoteCall(
        toolName="computer_ssh_exec",
        params={},
        endpoint=_endpoint(),
        executor=executor,
        holdTimeoutMs=0,
    )
    assert result.ok is False
    assert result.phase == "connect"


# ── 命中透明名单：原样重抛 ──


def test_transparentExceptionReraisedAsSameObjectAfterResultEvent():
    """命中名单：remote_dispatch_result 事件发出后，同一异常对象原样上抛。"""
    raised = HostKeyConfirmationNeeded(
        "SHA256:AAAA", host="h1", port=22, key_type="ssh-ed25519"
    )
    calls = []

    def executor(params):
        calls.append(1)
        raise raised

    events, recordEvent = _eventRecorder()
    with pytest.raises(HostKeyConfirmationNeeded) as excinfo:
        dispatchRemoteCall(
            toolName="computer_ssh_exec",
            params={"command": "uptime"},
            endpoint=_endpoint(),
            executor=executor,
            onEvent=recordEvent,
            transparentExceptions=(HostKeyConfirmationNeeded,),
        )

    assert excinfo.value is raised, "必须原样重抛同一异常对象（调用方按类型接卡）"
    assert calls == [1]
    names = [name for name, _ in events]
    assert names == ["remote_dispatch_start", "remote_dispatch_result"], names
    assert events[-1][1]["ok"] is False


def test_transparentMismatchReraisedForCallerFailClosed():
    """指纹冲突命中名单：原样上抛，调用方保留 fail-closed 处理。"""
    raised = HostKeyMismatchError(
        "SHA256:NEW", stored_fingerprint="SHA256:OLD", host="h1", port=22,
    )

    def executor(params):
        raise raised

    with pytest.raises(HostKeyMismatchError) as excinfo:
        dispatchRemoteCall(
            toolName="computer_ssh_exec",
            params={},
            endpoint=_endpoint(),
            executor=executor,
            transparentExceptions=(HostKeyConfirmationNeeded, HostKeyMismatchError),
        )
    assert excinfo.value is raised


def test_transparentMissStillMappedToEnvelope():
    """未命中名单：异常仍走统一信封映射，不上抛。"""

    def executor(params):
        raise HostKeyMismatchError(
            "SHA256:NEW", stored_fingerprint="SHA256:OLD", host="h1", port=22,
        )

    result = dispatchRemoteCall(
        toolName="computer_ssh_exec",
        params={},
        endpoint=_endpoint(),
        executor=executor,
        transparentExceptions=(HostKeyConfirmationNeeded,),
    )
    assert result.ok is False
    assert result.phase == "dispatch"
    assert "SHA256:NEW" in (result.error or "")


def test_transparentBeatsOfflineHold():
    """透明优先：命中名单的 connect 相位可重试异常不进 hold（零睡眠零重试）。"""
    raised = RemoteNotExecutedError(
        "SSH 连接失败: refused", phase="connect", retryable=True
    )

    def executor(params):
        raise raised

    sleeps = []
    with pytest.raises(RemoteNotExecutedError) as excinfo:
        dispatchRemoteCall(
            toolName="computer_ssh_exec",
            params={},
            endpoint=_endpoint(),
            executor=executor,
            holdTimeoutMs=10000,
            sleepFn=sleeps.append,
            transparentExceptions=(RemoteNotExecutedError,),
        )
    assert excinfo.value is raised
    assert sleeps == [], "命中透明名单不得进入离线 hold 重试"
