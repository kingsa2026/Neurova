"""QwenPaw 对照批 A1：渠道子进程隔离 + 握手期依赖审计。

红灯（实现前）：channels/ 下不存在 runner_spec/runner_protocol/runner_main/
runner_bridge——"渠道以独立子进程运行、握手核对依赖与源码版本"能力缺位。
绿灯断言：
- runner 真跑在**另一个进程**（pid 不同），宿主不受其崩溃影响；
- 依赖审计缺失 → 握手 fail-closed，子进程被终止；
- 源码版本不一致 → 握手拒绝；
- 崩溃后 supervisor 有限重启，宿主进程始终存活；
- 子进程环境按白名单收敛（宿主非白名单变量不外泄）。
"""

import asyncio
import os
import time

import pytest

from neurova.channels.base import ChannelConfig
from neurova.channels.runner_bridge import (
    ChannelProcessSupervisor,
    RunnerChannelAdapter,
    RunnerHost,
    _childEnvironment,
)
from neurova.channels.runner_protocol import (
    DependencyAuditError,
    decodeFrame,
    encodeFrame,
)
from neurova.channels.runner_spec import LaunchSpec


def _echoSpec(**overrides) -> LaunchSpec:
    payload = {
        "channel_type": "echo",
        "entrypoint": "builtin:echo",
        "required_deps": [],
    }
    payload.update(overrides)
    return LaunchSpec.from_dict(payload)


def test_frame_roundtrip():
    payload = {"op": "hello", "n": 3, "文本": "中文帧"}
    raw = encodeFrame(payload)
    assert decodeFrame(raw[4:]) == payload


def test_child_environment_strips_non_whitelisted_keys():
    os.environ["NEUROVA_RUNNER_TEST_SECRET"] = "should-not-leak"
    try:
        env = _childEnvironment(_echoSpec(private_env_keys=[]))
        assert "NEUROVA_RUNNER_TEST_SECRET" not in env
        assert "PYTHONPATH" in env
    finally:
        os.environ.pop("NEUROVA_RUNNER_TEST_SECRET", None)


class TestRunnerIsolation:

    def test_runner_runs_in_separate_process(self):
        host = RunnerHost(_echoSpec())
        hello = host.start()
        try:
            assert hello["op"] == "hello"
            assert hello["pid"] != os.getpid(), "runner 必须跑在独立子进程"
            assert host.is_alive()
            pong = host.sendRequest({"op": "ping"}, timeout=10)
            assert pong["op"] == "pong"
            sent = host.sendRequest(
                {"op": "send", "chat_id": "c1", "content": "你好"}, timeout=10)
            assert sent["ok"] is True and sent["echo"] == "你好"
        finally:
            host.terminate()
        assert not host.is_alive()

    def test_handshake_rejects_missing_dependency(self):
        host = RunnerHost(_echoSpec(
            required_deps=["definitely_missing_module_xyz"]))
        with pytest.raises(DependencyAuditError):
            host.start()
        # fail-closed：审计未过的子进程必须已被终止
        assert host.proc.poll() is not None

    def test_handshake_rejects_revision_mismatch(self):
        # 子进程回带**实测**版本（真实 git 短码），与规格里的假版本不一致 → 拒
        host = RunnerHost(_echoSpec(source_revision="deadbeef123"))
        with pytest.raises(DependencyAuditError):
            host.start()
        assert host.proc.poll() is not None

    def test_runner_crash_keeps_host_alive(self):
        crashes = []
        host = RunnerHost(_echoSpec(), on_crash=lambda h: crashes.append(h.pid))
        host.start()
        host.sendRequest({"op": "ping"}, timeout=10)
        old_pid = host.pid
        host.sendRaw({"op": "crash", "code": 3})
        deadline = time.time() + 10
        while host.is_alive() and time.time() < deadline:
            time.sleep(0.05)
        assert not host.is_alive(), "子进程应已崩溃退出"
        assert crashes == [old_pid], "崩溃回调应被触发且只触发一次"
        # 宿主进程仍存活（本测试能继续跑本身就是证据）

    def test_supervisor_restarts_after_crash(self):
        supervisor = ChannelProcessSupervisor(max_restarts=2)
        adapter = supervisor.launch(_echoSpec(), ChannelConfig(channel_type="echo"))
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(adapter.connect())
            first_pid = adapter.host.pid
            assert first_pid != os.getpid()
            adapter.host.sendRaw({"op": "crash", "code": 3})
            deadline = time.time() + 15
            status = supervisor.status().get("echo") or {}
            while time.time() < deadline:
                status = supervisor.status().get("echo") or {}
                if status.get("restarts", 0) >= 1 and status.get("alive"):
                    break
                time.sleep(0.05)
            assert status.get("restarts", 0) >= 1, "崩溃后应有限重启"
            assert status.get("alive") is True, "重启后的 runner 应存活"
            assert status.get("pid") not in (None, first_pid), "重启后是新进程"
        finally:
            loop.close()
