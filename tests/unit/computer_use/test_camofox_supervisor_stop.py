"""台账 #15/#16（2026-09-11）防回归：CamofoxSupervisor 收尾确定性

#16 _kill_process 弃用 API 现代化：`asyncio.get_event_loop().run_in_executor`
→ `asyncio.to_thread`。所有调用点（_spawn_and_wait_ready / stop / 监控线程
asyncio.run(self.stop())）均在运行中事件循环内 await——行为锚测试 + 源码级
弃用 API 消失断言。
#15 drain 线程收尾确定性：stop() 杀进程后对 stdout drain 线程
join(timeout=2)，超时放弃并 DEBUG 记录（daemon 线程不阻塞进程退出）。

完全隔离：进程对象全部 MagicMock/生成器，无真实 node/浏览器/网络/taskkill。
"""

import asyncio
import inspect
import subprocess
import sys
import threading
import time
from unittest.mock import MagicMock

import pytest

from neurova.computer_use.camofox_supervisor import CamofoxSupervisor

SCHED_LOGGER = "neurova.computer_use.camofox_supervisor"


@pytest.fixture
def supervisor():
    # cleanup_on_stop 关闭：隔离测试免触真实 ~/.camofox 清理
    return CamofoxSupervisor({"cleanup_on_stop": False})


def _fake_running_process(stdout_iter=None) -> MagicMock:
    proc = MagicMock()
    proc.poll.return_value = None  # is_running() == True
    proc.returncode = None
    if stdout_iter is not None:
        proc.stdout = stdout_iter
    return proc


# ── #16: _kill_process 现代化 ──


@pytest.mark.asyncio
async def test_kill_process_windows_batch_taskkill(supervisor, monkeypatch):
    """win32 分支行为锚：grace 等待后用跟踪 PIDs 批量 taskkill，状态复位"""
    supervisor._process = _fake_running_process()
    supervisor._managed_by_supervisor = True
    supervisor._tracked_pids = [111, 222, 333]

    killed = []
    monkeypatch.setattr(supervisor, "_taskkill_all", lambda pids: killed.append(list(pids)))

    await supervisor._kill_process()

    assert killed == [[111, 222, 333]]
    assert supervisor._process is None
    assert supervisor._managed_by_supervisor is False
    assert supervisor._tracked_pids == []


@pytest.mark.asyncio
async def test_kill_process_no_deprecated_get_event_loop(supervisor):
    """弃用 API 消失锚：_kill_process 源码不得再含 get_event_loop"""
    src = inspect.getsource(CamofoxSupervisor._kill_process)
    assert "get_event_loop" not in src
    assert "to_thread" in src


@pytest.mark.asyncio
async def test_kill_process_posix_graceful_fallback(supervisor, monkeypatch):
    """POSIX 分支行为锚：terminate → grace 超时 → kill -9，不走 taskkill"""
    monkeypatch.setattr(sys, "platform", "linux")

    proc = _fake_running_process()
    proc.wait.side_effect = [subprocess.TimeoutExpired("cmd", 5), 0]
    supervisor._process = proc
    supervisor._managed_by_supervisor = True
    supervisor._tracked_pids = [1]

    killed = []
    monkeypatch.setattr(supervisor, "_taskkill_all", lambda pids: killed.append(list(pids)))

    await supervisor._kill_process()

    proc.terminate.assert_called_once()
    proc.kill.assert_called_once()
    assert killed == [], "POSIX 分支不得走 Windows taskkill 路径"
    assert supervisor._process is None


@pytest.mark.asyncio
async def test_kill_process_noop_without_process(supervisor):
    """无进程时安全 no-op（_process None 直接返回）"""
    supervisor._process = None
    await supervisor._kill_process()
    assert supervisor._process is None


# ── #15: drain 线程 join 收尾 ──


@pytest.mark.asyncio
async def test_stop_joins_drain_thread_after_kill(supervisor):
    """杀进程后 drain 线程已自然退出 → join 立即返回，收尾确定"""
    supervisor._process = _fake_running_process(stdout_iter=iter([]))
    supervisor._managed_by_supervisor = True
    supervisor._start_stdout_drain(supervisor._process)
    drain_thread = supervisor._stdout_drain_thread
    assert drain_thread is not None

    await asyncio.wait_for(supervisor.stop(), timeout=10)

    assert not drain_thread.is_alive()
    assert supervisor._stdout_drain_thread is not None  # 引用保留（可观测）


@pytest.mark.asyncio
async def test_stop_joins_stuck_drain_with_timeout_and_abandons(supervisor, caplog):
    """drain 线程卡住 → stop() 有界等待 2s 后放弃（DEBUG 记录），不死锁"""
    release = threading.Event()
    release.clear()  # 未释放：drain 线程将持续阻塞

    def blocked_stdout_lines():
        # 生成器：释放前不出任何行、不结束（卡住的是 drain 线程的 for 循环）
        while not release.is_set():
            time.sleep(0.05)
        yield from ()

    stuck_stdout = blocked_stdout_lines()
    supervisor._process = _fake_running_process()
    supervisor._managed_by_supervisor = True

    # 手动构造卡住的 drain 线程（stdout 阻塞在 release 上）
    supervisor._stdout_drain_thread = threading.Thread(
        target=supervisor._drain_stdout,
        args=(MagicMock(stdout=stuck_stdout),),
        daemon=True,
        name="camofox-stdout-drain",
    )
    supervisor._stdout_drain_thread.start()
    drain_thread = supervisor._stdout_drain_thread
    await asyncio.sleep(0.1)  # 确认线程真的卡在 for 循环上
    assert drain_thread.is_alive()

    start = time.monotonic()
    with caplog.at_level(10, logger=SCHED_LOGGER):  # DEBUG
        await asyncio.wait_for(supervisor.stop(), timeout=10)
    elapsed = time.monotonic() - start

    # join(timeout=2) 生效：约 2s 放弃，不无限阻塞
    assert 1.9 <= elapsed < 6.0, f"stop() 应在 join 超时后放弃，实际耗时 {elapsed:.2f}s"
    assert drain_thread.is_alive(), "放弃后卡住的 daemon 线程允许存活（不阻塞 stop 返回）"
    abandon_logs = [r for r in caplog.records if "放弃等待" in r.getMessage()]
    assert abandon_logs, "join 超时必须落 DEBUG 放弃日志"

    # 收尾：释放阻塞线程，确认可正常退出
    release.set()
    drain_thread.join(timeout=3)
    assert not drain_thread.is_alive()


@pytest.mark.asyncio
async def test_start_stdout_drain_keeps_thread_reference(supervisor):
    """_start_stdout_drain 必须持线程引用（#15 前置：无引用则无法 join）"""
    supervisor._process = _fake_running_process(stdout_iter=iter([]))
    supervisor._start_stdout_drain(supervisor._process)
    assert supervisor._stdout_drain_thread is not None
    assert supervisor._stdout_drain_thread.name == "camofox-stdout-drain"
    supervisor._stdout_drain_thread.join(timeout=3)
    assert not supervisor._stdout_drain_thread.is_alive()
