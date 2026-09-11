"""RES-P1-3 防回归：camofox stdout 管道排空 + 空闲自动停机真正落地

历史缺陷（叠加）：
1. `subprocess.Popen(stdout=subprocess.PIPE, stderr=subprocess.STDOUT)` 后无人读取
   → node 进程写满管道缓冲（Windows ~64KB）后整体卡死，health 探测失败，
   computer-use 工具链挂起。
2. 空闲自动停机只 `self._stop_requested.set()`，该 Event 无任何读者
   → 设计中的"空闲 N 秒杀进程"从未生效，闲置浏览器数百 MB RAM 一直占用。

契约：
1. 启动后有 daemon 线程持续消费 process.stdout（逐行 decode errors="replace" 落 DEBUG 日志）
2. 监控线程 idle 命中后真正调用停机流程（杀进程），而非 set 一个无人读的标志
3. `_stop_from_monitor` 必须线程安全：不依赖外部事件循环（asyncio.run 自建循环）
4. 全程 fake 进程对象，不拉起真实 node/浏览器进程，不发生真实网络请求
"""

import asyncio
import io
import logging
import threading
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_proc_with_stdout(data: bytes = b"camofox ready\nlistening on 9377\n"):
    """带可迭代 stdout 的 fake 进程（io.BytesIO 逐行产出 bytes）"""
    proc = MagicMock()
    proc.pid = 12345
    proc.stdout = io.BytesIO(data)
    proc.poll = MagicMock(return_value=None)  # 存活
    proc.terminate = MagicMock(return_value=None)
    proc.kill = MagicMock(return_value=None)
    proc.wait = MagicMock(return_value=0)
    return proc


def _make_alive_proc():
    """无 stdout 数据但存活的 fake 进程（is_running 需要它）"""
    proc = MagicMock()
    proc.pid = 999
    proc.stdout = io.BytesIO(b"")
    proc.poll = MagicMock(return_value=None)
    proc.terminate = MagicMock(return_value=None)
    proc.kill = MagicMock(return_value=None)
    proc.wait = MagicMock(return_value=0)
    return proc


# ── 1. stdout 排空 ──────────────────────────────────────────


class TestStdoutDrain:
    def test_drain_stdout_consumes_all_lines(self, caplog):
        """drain 必须逐行消费管道（bytes → decode errors=replace → DEBUG 日志）"""
        from neurova.computer_use.camofox_supervisor import CamofoxSupervisor

        s = CamofoxSupervisor({"cleanup_on_stop": False})
        proc = _make_proc_with_stdout(b"line-one\nline-two\n")

        with caplog.at_level(logging.DEBUG, logger="neurova.computer_use.camofox_supervisor"):
            s._drain_stdout(proc)  # 同步执行，无残留线程

        assert proc.stdout.tell() == len(b"line-one\nline-two\n"), (
            "stdout 管道未被读空——子进程写满缓冲后会整体卡死（RES-P1-3 ①）"
        )
        logged = [r.getMessage() for r in caplog.records]
        assert any("line-one" in m for m in logged), f"stdout 行应落 DEBUG 日志，实际: {logged}"
        assert any("line-two" in m for m in logged)

    def test_drain_stdout_replaces_invalid_utf8(self, caplog):
        """非法 UTF-8 字节不得让 drain 线程崩溃，errors=replace 兜底"""
        from neurova.computer_use.camofox_supervisor import CamofoxSupervisor

        s = CamofoxSupervisor({"cleanup_on_stop": False})
        proc = _make_proc_with_stdout(b"bad-\xff\xfe-bytes\n")

        with caplog.at_level(logging.DEBUG, logger="neurova.computer_use.camofox_supervisor"):
            s._drain_stdout(proc)  # 不抛

        assert proc.stdout.tell() == len(b"bad-\xff\xfe-bytes\n")
        assert any("bad-" in r.getMessage() for r in caplog.records)

    @pytest.mark.asyncio
    async def test_spawn_starts_daemon_drain_thread(self):
        """_spawn_and_wait_ready 启动进程后必须立即起 daemon drain 线程消费管道"""
        from neurova.computer_use import camofox_supervisor as mod
        from neurova.computer_use.camofox_supervisor import CamofoxSupervisor

        s = CamofoxSupervisor({"cleanup_on_stop": False, "startup_timeout": 2})
        proc = _make_proc_with_stdout(b"boot-ok\n")

        # 捕获模块内构造的线程（BytesIO 读完即退出，事后 enumerate 抓不到）
        created = []
        real_thread_cls = threading.Thread

        def spy_thread(*args, **kwargs):
            t = real_thread_cls(*args, **kwargs)
            created.append(t)
            return t

        with patch.object(mod.threading, "Thread", spy_thread), patch.object(
            mod, "subprocess"
        ) as mock_subproc, patch.object(
            s, "_probe_health_via_client", AsyncMock(return_value=True)
        ), patch.object(s, "_collect_descendant_pids", return_value=[12345]):
            mock_subproc.Popen = MagicMock(return_value=proc)
            ok = await s._spawn_and_wait_ready()

        assert ok is True
        drain_threads = [t for t in created if t.name == "camofox-stdout-drain"]
        assert drain_threads, (
            "启动进程后没有创建 stdout drain 线程——管道写满即死锁（RES-P1-3 ①）"
        )
        assert all(t.daemon for t in drain_threads), "drain 线程必须是 daemon"

        # 等 drain 线程读完，验证管道被消费
        for t in drain_threads:
            t.join(timeout=2.0)
        assert proc.stdout.tell() == len(b"boot-ok\n")


# ── 2. 空闲自动停机 ─────────────────────────────────────────


class TestIdleAutoStop:
    def test_idle_hit_triggers_real_stop_path(self):
        """idle 命中必须走真实停机入口，而不是 set 一个无人读的 Event"""
        from neurova.computer_use.camofox_supervisor import CamofoxSupervisor

        s = CamofoxSupervisor({"idle_timeout": 1, "cleanup_on_stop": False})
        s._process = _make_alive_proc()
        s._last_activity = time.time() - 100
        s._managed_by_supervisor = True

        with patch.object(s, "_stop_from_monitor") as mock_stop:
            s._check_idle()
            mock_stop.assert_called_once(), "空闲超时后未触发停机——进程永不回收（RES-P1-3 ②）"

    def test_fresh_activity_does_not_stop(self):
        from neurova.computer_use.camofox_supervisor import CamofoxSupervisor

        s = CamofoxSupervisor({"idle_timeout": 1000, "cleanup_on_stop": False})
        s._process = _make_alive_proc()
        s._last_activity = time.time()

        with patch.object(s, "_stop_from_monitor") as mock_stop:
            s._check_idle()
            mock_stop.assert_not_called()

    def test_not_running_does_not_stop(self):
        from neurova.computer_use.camofox_supervisor import CamofoxSupervisor

        s = CamofoxSupervisor({"idle_timeout": 1, "cleanup_on_stop": False})
        s._process = None

        with patch.object(s, "_stop_from_monitor") as mock_stop:
            s._check_idle()
            mock_stop.assert_not_called()

    def test_stop_from_monitor_actually_kills_process(self):
        """_stop_from_monitor 必须线程安全地走到杀进程：terminate 被调用、_process 置空"""
        from neurova.computer_use.camofox_supervisor import CamofoxSupervisor

        s = CamofoxSupervisor({"cleanup_on_stop": False, "kill_grace": 1})
        proc = _make_alive_proc()
        s._process = proc
        s._managed_by_supervisor = True
        s._tracked_pids = []  # 不触发 taskkill 分支

        s._stop_from_monitor()  # 内部 asyncio.run(stop())，不依赖外部事件循环

        proc.terminate.assert_called_once()
        assert s._process is None
        assert s._managed_by_supervisor is False

    def test_monitor_thread_does_not_join_itself(self):
        """stop() 从监控线程自身触发时不得 join 当前线程（会 RuntimeError/死锁）"""
        from neurova.computer_use.camofox_supervisor import CamofoxSupervisor

        s = CamofoxSupervisor({"cleanup_on_stop": False, "kill_grace": 1})
        proc = _make_alive_proc()
        s._process = proc
        s._managed_by_supervisor = True
        s._tracked_pids = []
        s._monitor_running = True
        s._monitor_thread = threading.current_thread()  # 模拟：正在监控线程内

        s._stop_from_monitor()  # 不抛 RuntimeError("cannot join current thread")

        proc.terminate.assert_called_once()
