"""P2-19：渠道 Runner 生产工厂接线与生命周期回归。

只使用 `builtin:echo` 子进程，不连接任何真实渠道。
"""

from __future__ import annotations

import asyncio
import os
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from neurova.api.endpoints import channel_config
from neurova.channels.base import ChannelConfig
from neurova.channels.manager import ChannelManager
from neurova.channels.runner_bridge import ChannelProcessSupervisor, RunnerChannelAdapter
from neurova.channels.runner_protocol import DependencyAuditError
from neurova.channels.runner_spec import LaunchSpec


@pytest.fixture()
def manager():
    ChannelManager._instance = None
    instance = ChannelManager.get_instance()
    yield instance
    ChannelManager._instance = None


def _spec(**overrides) -> LaunchSpec:
    payload = {
        "channel_type": "echo",
        "entrypoint": "builtin:echo",
        "agent_id": "agent-a",
        "instance_key": "agent-a:echo",
        "required_deps": [],
    }
    payload.update(overrides)
    return LaunchSpec.from_dict(payload)


def test_runner_is_opt_in_and_default_factory_is_unchanged(manager):
    config = ChannelConfig(channel_type="feishu", app_id="app", app_secret="secret")

    adapter = channel_config._create_adapter("feishu", config, agent_id="default", manager=manager)

    assert adapter is not None
    assert not isinstance(adapter, RunnerChannelAdapter), "未显式开启 runner 却默认走子进程"


def test_factory_rejects_raw_secret_without_environment_reference(manager):
    from fastapi import HTTPException

    config = ChannelConfig(
        channel_type="feishu",
        app_secret="must-not-enter-process-argv",
        extra={"runner": {"enabled": True, "entrypoint": "builtin:echo"}},
    )

    with pytest.raises(HTTPException) as raised:
        channel_config._create_adapter("feishu", config, agent_id="agent-a", manager=manager)

    assert raised.value.status_code == 400
    assert "secret_env" in raised.value.detail


def test_factory_rejects_raw_extra_secret(manager):
    from fastapi import HTTPException

    config = ChannelConfig(
        channel_type="echo",
        extra={"runner": {"enabled": True, "entrypoint": "builtin:echo"},
               "bot_token": "must-not-enter-process-argv"},
    )

    with pytest.raises(HTTPException) as raised:
        channel_config._create_adapter("echo", config, agent_id="agent-a", manager=manager)

    assert raised.value.status_code == 400
    assert "extra.bot_token" in raised.value.detail


def test_factory_moves_extra_secret_to_environment_reference(manager, monkeypatch):
    monkeypatch.setenv("RUNNER_BOT_TOKEN", "child-only-secret")
    config = ChannelConfig(
        channel_type="echo",
        extra={"runner": {
            "enabled": True, "entrypoint": "builtin:echo",
            "secret_env": {"extra.bot_token": "RUNNER_BOT_TOKEN"},
        }, "bot_token": "child-only-secret"},
    )

    adapter = channel_config._create_adapter("echo", config, agent_id="agent-a", manager=manager)

    assert adapter.spec.channel_config["extra"]["bot_token"] == {"env": "RUNNER_BOT_TOKEN"}
    assert "child-only-secret" not in adapter.spec.to_json()


def test_stale_crash_callback_cannot_mark_new_generation(manager):
    supervisor = ChannelProcessSupervisor(manager=manager, max_restarts=0)
    first = supervisor.launch(_spec(instance_key="agent-a:echo"), ChannelConfig(channel_type="echo"))
    second = supervisor.launch(_spec(instance_key="agent-a:echo"), ChannelConfig(channel_type="echo"))
    callback = supervisor._makeCrashHandler(first.spec, first, 0)

    callback(first.host)

    assert supervisor._entries["agent-a:echo"]["adapter"] is second
    assert supervisor._entries["agent-a:echo"]["crashed"] is False


@pytest.mark.asyncio
async def test_bootstrap_unregisters_runner_after_connect_failure(monkeypatch, manager):
    adapter = SimpleNamespace(
        isRunner=True, channel_type="echo", connect=AsyncMock(return_value=False),
        set_event_callback=lambda _callback: None,
    )
    monkeypatch.setattr(channel_config, "_load_store", lambda: {
        "agents": {"agent-a": {"echo": {"enabled": True}}},
    })
    monkeypatch.setattr(channel_config, "_create_adapter_for_agent", lambda *args, **kwargs: adapter)

    stats = await channel_config.bootstrap_channel_adapters(manager)

    assert stats["failed"] == 1
    assert manager.get_adapter("echo", agent_id="agent-a") is None


def test_handshake_timeout_terminates_child(monkeypatch):
    import time
    from neurova.channels import runner_bridge

    class FakeProcess:
        def __init__(self):
            self.stdin = None
            self.stdout = None
            self.stderr = None
            self.pid = 123
            self.terminated = False

        def poll(self):
            return None

        def terminate(self):
            self.terminated = True

        def wait(self, timeout=None):
            return 0

    process = FakeProcess()
    monkeypatch.setattr(runner_bridge.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(runner_bridge, "HANDSHAKE_TIMEOUT_S", 0.05)
    monkeypatch.setattr(runner_bridge, "readFrame", lambda _stdout: time.sleep(0.2) or {})
    host = runner_bridge.RunnerHost(_spec())

    with pytest.raises(TimeoutError):
        host.start()

    assert process.terminated is True


def test_runner_child_config_preserves_credentials_and_extra(monkeypatch):
    from neurova.channels.runner_main import _channelConfigFromSpec

    monkeypatch.setenv("RUNNER_TEST_SECRET", "child-secret")
    spec = _spec(
        private_env_keys=["RUNNER_TEST_SECRET"],
        channel_config={
        "channel_type": "echo",
        "enabled": True,
        "app_id": "app-1",
        "app_secret": {"env": "RUNNER_TEST_SECRET"},
        "webhook_url": "https://example.invalid/hook",
        "use_stream": False,
        "extra": {"nested": {"keep": True}},
    })

    config = _channelConfigFromSpec(spec)

    assert config.channel_type == "echo"
    assert config.app_id == "app-1"
    assert config.app_secret == "child-secret"
    assert config.webhook_url == "https://example.invalid/hook"
    assert config.use_stream is False
    assert config.extra == {"nested": {"keep": True}}


def test_child_environment_only_forwards_declared_credentials(monkeypatch):
    from neurova.channels.runner_bridge import _childEnvironment

    monkeypatch.setenv("RUNNER_ALLOWED_SECRET", "allowed")
    monkeypatch.setenv("RUNNER_DENIED_SECRET", "denied")
    spec = _spec(private_env_keys=["RUNNER_ALLOWED_SECRET"])

    env = _childEnvironment(spec)

    assert env["RUNNER_ALLOWED_SECRET"] == "allowed"
    assert "RUNNER_DENIED_SECRET" not in env
    assert env["PYTHONPATH"].split(os.pathsep)[0] == spec.code_root


def test_supervisor_keys_same_channel_by_instance(manager):
    supervisor = ChannelProcessSupervisor(manager=manager, max_restarts=0)
    first = supervisor.launch(_spec(instance_key="agent-a:echo"), ChannelConfig(channel_type="echo"))
    second = supervisor.launch(
        _spec(agent_id="agent-b", instance_key="agent-b:echo"),
        ChannelConfig(channel_type="echo"),
    )
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(first.connect())
        loop.run_until_complete(second.connect())
        status = supervisor.status()
        assert set(status) == {"agent-a:echo", "agent-b:echo"}, status
    finally:
        loop.run_until_complete(first.disconnect())
        loop.run_until_complete(second.disconnect())
        loop.close()


def test_supervisor_restart_replaces_manager_adapter(manager):
    supervisor = ChannelProcessSupervisor(manager=manager, max_restarts=1)
    adapter = supervisor.launch(_spec(instance_key="agent-a:echo"), ChannelConfig(channel_type="echo"))
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(adapter.connect())
        manager.register_adapter(adapter, agent_id="agent-a")
        old = adapter
        old.host.sendRaw({"op": "crash", "code": 3})
        deadline = time.time() + 15
        current = old
        while time.time() < deadline:
            current = manager.get_adapter("echo", agent_id="agent-a")
            status = supervisor.status().get("agent-a:echo") or {}
            if current is not old and status.get("alive"):
                break
            time.sleep(0.05)
        assert current is not old, "崩溃换代后 ChannelManager 仍持有旧适配器"
        assert current.host is not None and current.host.is_alive()
    finally:
        if adapter.host and adapter.host.is_alive():
            loop.run_until_complete(adapter.disconnect())
        loop.close()


def test_factory_runner_handshake_failure_is_explicit(manager):
    config = ChannelConfig(
        channel_type="echo",
        extra={"runner": {
            "enabled": True,
            "entrypoint": "builtin:echo",
            "source_revision": "deadbeef123",
            "instance_key": "agent-a:echo",
        }},
    )

    adapter = channel_config._create_adapter("echo", config, agent_id="agent-a", manager=manager)

    assert isinstance(adapter, RunnerChannelAdapter)
    with pytest.raises(DependencyAuditError):
        asyncio.run(adapter.connect())
