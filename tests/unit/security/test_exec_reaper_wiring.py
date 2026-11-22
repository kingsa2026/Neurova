# -*- coding: utf-8 -*-
"""U10 接线：exec/ssh 类工具的超时清算走 security/process_reaper.kill_tree（红→绿）。

契约（实施计划 U10 + 卡面要求）：
- exec/ssh 类命令的超时清算从"逐 pid terminate"换成 ``kill_tree``（按树收割，
  不留孙进程孤儿）；清算失败降级原逐 pid terminate 逻辑（行为兼容）。
- exec_command 会话进程在**起进程时**把整棵树的清算挂到本轮取消令牌——
  工具超时（KILL 处置）与用户停止都经令牌兑现。

红（现网行为）：tool_executor 没有 kill_tree 清算入口；逐 pid terminate
（单杀根进程）后孙进程残留；exec_command 会话清算不经 kill_tree。
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from neurova.core.cancel_token import resetTurnCancelToken  # noqa: E402
from neurova.tool_executor import ToolExecutor  # noqa: E402

POSIX = sys.platform != "win32"

#: 三层树里每层进程的存活时长（秒）。清算窗口必须短于它，否则是"自然退出"
#: 冒充清算成功——判据就假了。
TREE_LIFETIME_S = 30

#: 树清算的杀后复查窗口（秒）：CIM 快照×2 + 批量 taskkill 在慢机上可到数秒。
REAP_VERIFY_WINDOW_S = 20


def _spawnThreeLevelTree():
    """起一棵真实三层树：root → child → grandchild（各自长睡 TREE_LIFETIME_S）。

    POSIX 下根进程自立进程组（生产侧 spawnKwargsForKill 的同款前提）；
    Windows 无需成团（kill_tree 走 CIM 父子快照，不依赖进程组）。
    返回 (root_proc, descendants)——descendants 是起树时刻快照到的
    子/孙 pid（活体，供杀后逐一复判）。
    """
    child_source = (
        "import subprocess, sys, time\n"
        "subprocess.Popen([sys.executable, '-c', "
        f"'import time; time.sleep({TREE_LIFETIME_S})'])\n"
        f"time.sleep({TREE_LIFETIME_S})\n"
    )
    root = subprocess.Popen(
        [sys.executable, "-c", child_source],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=POSIX,
    )
    # 等 child/grandchild 真的起来（树不成形就断言，判的是空集）
    deadline = time.monotonic() + 10
    descendants = []
    while time.monotonic() < deadline:
        from neurova.security.process_reaper import winProcessMap

        try:
            parent_map = winProcessMap()
        except Exception:
            parent_map = {}
        kids = [p for p, pp in parent_map.items() if pp == root.pid]
        grandkids = [p for p, pp in parent_map.items() if pp in kids]
        descendants = kids + grandkids
        if len(descendants) >= 2:
            break
        time.sleep(0.3)
    return root, descendants


def _pidAlive(pid: int) -> bool:
    """单 pid 存活判（不依赖父子快照——根死后后代快照链会断）。"""
    if POSIX:
        try:
            import os

            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except OSError:
            return True
    out = subprocess.run(
        ["tasklist", "/FI", f"PID eq {pid}"], capture_output=True
    ).stdout.decode("gbk", "replace")
    return str(pid) in out


def _killPid(pid: int) -> None:
    if POSIX:
        subprocess.run(["kill", "-9", str(pid)], capture_output=True)
    else:
        subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)


def _makeExecutor() -> ToolExecutor:
    agent = SimpleNamespace(
        config=SimpleNamespace(user_id="u1", agent_id="a1"),
        tool_memory=MagicMock(),
        tool_lifecycle=None,
        _skill_registry=None,
        tool_router=None,
        _current_user_input="x",
        _tool_messages_list=[],
        append_tool_messages=lambda records: None,
    )
    return ToolExecutor(agent)


class TestReapToolProcessTree:
    def test_killTreeIsPrimaryAndReapsWholeTree(self, monkeypatch):
        """绿判据：清算入口优先走 kill_tree，父+子+孙全部退出。"""
        from neurova.tool_executor import reapToolProcessTree

        root, descendants = _spawnThreeLevelTree()
        try:
            assert len(descendants) >= 2, "三层树未成形，判据无法成立"
            killTreeCalls = []
            import neurova.security.process_reaper as reaper

            realKillTree = reaper.kill_tree

            def _spy(pid, grace_seconds=5.0):
                killTreeCalls.append(int(pid))
                return realKillTree(pid, grace_seconds=grace_seconds)

            monkeypatch.setattr(reaper, "kill_tree", _spy)
            outcome = reapToolProcessTree(root.pid, grace_seconds=REAP_VERIFY_WINDOW_S)
            assert killTreeCalls and killTreeCalls[0] == root.pid, (
                f"清算必须经 process_reaper.kill_tree 单源，实际调用: {killTreeCalls}")
            assert outcome.get("via") == "kill_tree", f"清算口径应是 kill_tree: {outcome}"
            assert outcome.get("reaped") is True, f"三层树应全灭: {outcome}"
            deadline = time.monotonic() + REAP_VERIFY_WINDOW_S
            while time.monotonic() < deadline and any(_pidAlive(p) for p in [root.pid, *descendants]):
                time.sleep(0.3)
            survivors = [p for p in [root.pid, *descendants] if _pidAlive(p)]
            assert not survivors, f"kill_tree 后树内仍有存活 pid: {survivors}"
        finally:
            if root.poll() is None:
                root.kill()
                root.wait(timeout=10)
            for pid in descendants:
                if _pidAlive(pid):
                    _killPid(pid)

    def test_perPidTerminateLeavesDescendants(self):
        """红判据（缺口实证）：逐 pid terminate 只杀根，孙进程残留。"""
        root, descendants = _spawnThreeLevelTree()
        try:
            assert len(descendants) >= 2, "三层树未成形，判据无法成立"
            # 旧逻辑形态：单 pid terminate（无 /T、不建树、无杀后复查）
            if POSIX:
                import os
                import signal

                os.kill(root.pid, signal.SIGTERM)
            else:
                subprocess.run(["taskkill", "/F", "/PID", str(root.pid)],
                               capture_output=True, timeout=15)
            root.wait(timeout=15)
            time.sleep(1.0)
            assert root.poll() is not None, "根进程应已退出"
            survivors = [p for p in descendants if _pidAlive(p)]
            assert survivors, (
                "逐 pid terminate 后未见残留后代（树未成形或已被连带回收），判据无法成立")
        finally:
            if root.poll() is None:
                root.kill()
                root.wait(timeout=10)
            # 清理残留，不污染跑测机
            for pid in descendants:
                if _pidAlive(pid):
                    _killPid(pid)

    def test_killTreeFailureDegradesToPerPidTerminate(self, monkeypatch):
        """兼容判据：kill_tree 失败时降级原逐 pid terminate，根进程仍被清算。"""
        from neurova.tool_executor import reapToolProcessTree

        proc = subprocess.Popen(
            [sys.executable, "-c", f"import time; time.sleep({TREE_LIFETIME_S})"],
            start_new_session=POSIX,
        )
        try:
            import neurova.security.process_reaper as reaper

            def _boom(pid, grace_seconds=5.0):
                raise OSError("注入：kill_tree 不可用")

            monkeypatch.setattr(reaper, "kill_tree", _boom)
            outcome = reapToolProcessTree(proc.pid)
            assert outcome.get("via") == "per_pid_fallback", f"应降级逐 pid: {outcome}"
            deadline = time.monotonic() + REAP_VERIFY_WINDOW_S
            while proc.poll() is None and time.monotonic() < deadline:
                time.sleep(0.2)
            assert proc.poll() is not None, "降级路径也必须清算根进程"
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=10)

    def test_rejectsSelfAndIllegalPid(self):
        from neurova.tool_executor import reapToolProcessTree

        import os

        assert reapToolProcessTree(os.getpid()).get("reaped") is False
        assert reapToolProcessTree(-1).get("reaped") is False
        assert reapToolProcessTree(0).get("reaped") is False


class TestExecSessionReaperWiring:
    @pytest.mark.asyncio
    async def test_execCommandSessionReapsTreeViaKillTree(self, monkeypatch):
        """绿判据：exec_command 会话的超时清算经 kill_tree（令牌置位即兑现）。"""
        import neurova.security.process_reaper as reaper
        from neurova.execution_engine import shell_sessions

        executor = _makeExecutor()
        killTreeCalls = []

        realKillTree = reaper.kill_tree

        def _spy(pid, grace_seconds=5.0):
            killTreeCalls.append(int(pid))
            return realKillTree(pid, grace_seconds=grace_seconds)

        monkeypatch.setattr(reaper, "kill_tree", _spy)
        # killProcessTree 的 POSIX 路径也委托 kill_tree，会把同一 pid 记两次；
        # Windows 路径走 taskkill /T，不进 kill_tree。两种形态都不影响判据：
        # 这里只断言"会话 pid 进过 kill_tree 调用面"。
        resetTurnCancelToken()
        try:
            result = await executor._execute_exec_command({
                "command": f"sleep {TREE_LIFETIME_S}",
                "yield_time_ms": 300,
            })
            assert result.get("status") == "running", f"长命令应处于 running: {result}"
            session_id = result.get("session_id")
            assert session_id is not None
            mgr = shell_sessions.get_shell_session_manager()
            session = mgr._sessions.get(int(session_id))
            assert session is not None, "会话应已在册"
            session_pid = session.proc.pid

            from neurova.core.cancel_token import getTurnCancelToken

            token = getTurnCancelToken()
            assert token is not None, "会话执行期必须有本轮取消令牌"
            token.cancel("timeout")
            deadline = time.monotonic() + REAP_VERIFY_WINDOW_S
            while session.proc.poll() is None and time.monotonic() < deadline:
                await asyncio.sleep(0.2)
            assert session.proc.poll() is not None, "令牌置位后会话进程必须退出"
            assert session_pid in killTreeCalls, (
                f"exec_command 会话清算必须经 kill_tree（U10 接线），"
                f"会话 pid={session_pid}，kill_tree 调用: {killTreeCalls}")
        finally:
            resetTurnCancelToken()
            await shell_sessions.get_shell_session_manager().kill_all()
            shell_sessions.reset_shell_session_manager()
