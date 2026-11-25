# -*- coding: utf-8 -*-
"""CORE-16：Docker 执行不得阻塞事件循环，超时/停止必须能清掉容器。

根因：`async def start/exec` 内直接 `subprocess.run` / `Popen.communicate`
（阻塞整个事件循环）；`docker run --rm` 没有 `--name`，`_container_id` 从未
赋值——超时只杀 docker CLI，容器继续运行，`stop()` 也无从清理。

判据（真 asyncio 事件循环 + 可控子进程替身模拟外部 CLI）：
- 0.25s 的 docker 调用期间，50ms 心跳必须持续推进；
- 超时后按 `--name` 记录的容器名执行 `docker stop`，活动容器集合清空。
"""
from __future__ import annotations

import asyncio
import subprocess
import time
from types import SimpleNamespace

import pytest

import neurova.execution_layers as layers
from neurova.execution_layers import DockerExecutor


class _BlockingPopen:
    """模拟 docker CLI：communicate 阻塞 0.25s（真实 CLI 的同步等待）。"""

    last_cmd: list = []

    def __init__(self, cmd, **kwargs):
        type(self).last_cmd = list(cmd)
        self.returncode = 0
        self._done = False

    def communicate(self, timeout=None):
        time.sleep(0.25)
        self.returncode = 0
        self._done = True
        return b"ok", b""

    def poll(self):
        return self.returncode if self._done else None

    def kill(self):
        self._done = True
        self.returncode = -9


class _TimeoutPopen:
    """模拟超时：第一次 communicate 抛 TimeoutExpired，收尸后返回空。"""

    instances: list = []

    def __init__(self, cmd, **kwargs):
        self.cmd = list(cmd)
        self.calls = 0
        self.killed = False
        self.returncode = 0
        type(self).instances.append(self)

    def communicate(self, timeout=None):
        self.calls += 1
        if timeout is not None and self.calls == 1:
            raise subprocess.TimeoutExpired(self.cmd, timeout)
        self.returncode = -1
        return b"", b""

    def poll(self):
        return None if not self.killed else self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -9

    @property
    def container_name(self) -> str:
        idx = self.cmd.index("--name")
        return self.cmd[idx + 1]


@pytest.mark.asyncio
async def testDockerExecDoesNotBlockEventLoop(monkeypatch):
    monkeypatch.setattr(layers.subprocess, "Popen", _BlockingPopen)
    executor = DockerExecutor()
    ticks = 0

    async def heartbeat():
        nonlocal ticks
        while True:
            ticks += 1
            await asyncio.sleep(0.01)

    task = asyncio.create_task(heartbeat())
    try:
        before = ticks
        result = await executor.exec("echo", args=["hi"])
        advanced = ticks - before
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert result.success is True
    assert advanced >= 10, f"0.25s docker 调用期间心跳只推进 {advanced} 次——事件循环被阻塞"


@pytest.mark.asyncio
async def testTimeoutStopsNamedContainerAndClearsTracking(monkeypatch):
    stopped: list = []
    _TimeoutPopen.instances = []
    monkeypatch.setattr(layers.subprocess, "Popen", _TimeoutPopen)

    def fake_run(cmd, **kwargs):
        stopped.append(list(cmd))
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(layers.subprocess, "run", fake_run)

    executor = DockerExecutor()
    result = await executor.exec("sleep", args=["99"], timeout=0.02)

    assert result.exit_code == -1
    proc = _TimeoutPopen.instances[-1]
    assert "--name" in proc.cmd, f"docker run 未命名容器，超时后无从清理：{proc.cmd[:6]}"
    stop_cmds = [c for c in stopped if c[:2] == ["docker", "stop"]]
    assert stop_cmds and proc.container_name in stop_cmds[0], (
        f"超时后未按容器名 stop：{stop_cmds}"
    )
    assert executor._activeContainers == set(), "活动容器集合未清空"
    assert executor._container_id is None