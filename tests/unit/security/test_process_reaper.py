# -*- coding: utf-8 -*-
"""U10 进程树清算（security/process_reaper）：先红后绿。

红（既有行为）：池条目清算走逐 pid terminate，三层进程树（父 spawn 子、
子 spawn 孙，各长眠）只死根，子/孙进程残留（psutil/tasklist 仍可查到）。
绿（本卡目标）：kill_tree / reap_tree 按树清算——Windows 用 PowerShell
CIM 快照建 pid→ppid 映射、自根 BFS 收集全树、按 20/批 taskkill /F；
POSIX 优先 os.killpg，不成组退化逐 pid SIGTERM→宽限→SIGKILL；
清算后复查零残留。

跳过条件：无权限派生子进程的受限环境（沙箱/CI）显式 pytest.skip，
不产生假红/假绿；树未按时建好则带现场信息 fail，不留长眠进程。
"""
import errno
import json
import os
import signal
import subprocess
import sys
import time
from types import SimpleNamespace

import psutil
import pytest

from neurova.agent.neuacp.process_pool import NeuacpProcessPool, poolKey

#: 三层进程树脚本：layer 0=父 1=子 2=孙，各自 spawn 下一层后长眠 300s，
#: 并把 {layer, pid, child} 追加写入信息文件供测试核对树形。
TREE_SCRIPT = """
import json, os, subprocess, sys, time


def main():
    infoPath, layer = sys.argv[1], int(sys.argv[2])
    childPid = None
    if layer < 2:
        child = subprocess.Popen(
            [sys.executable, os.path.abspath(__file__), infoPath, str(layer + 1)],
            cwd=os.path.dirname(os.path.abspath(__file__)))
        childPid = child.pid
    with open(infoPath, "a", encoding="utf-8") as handle:
        handle.write(json.dumps({"layer": layer, "pid": os.getpid(),
                                 "child": childPid}) + chr(10))
    time.sleep(300)


if __name__ == "__main__":
    main()
"""


class FakeProc:
    """无 pid 的池进程替身：只满足 is_alive/terminate 鸭子面（同既有池测试形态）。"""

    def __init__(self):
        self._alive = True
        self.terminated = False

    @property
    def is_alive(self):
        return self._alive and not self.terminated

    def terminate(self):
        self.terminated = True


def _reaper():
    """取被测模块；红灯阶段（未实现）以明确信息失败，不静默跳过。"""
    try:
        from neurova.security import process_reaper as reaperModule
    except ImportError as exc:
        pytest.fail(f"U10 未实现：neurova.security.process_reaper 不可导入（{exc}）")
    return reaperModule


def _readEntries(infoPath):
    """解析树信息文件 → {layer: pid}。"""
    entries = {}
    try:
        text = infoPath.read_text(encoding="utf-8")
    except OSError:
        return entries
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict) and "layer" in record and "pid" in record:
            entries[int(record["layer"])] = int(record["pid"])
    return entries


def buildTree(tmpPath, layers=3):
    """构建三层真实进程树；返回含 parent/child/grand pid 的句柄。

    派生被拒（权限受限环境）→ 显式 skip；超时未建好 → 带现场 fail。
    """
    script = tmpPath / "u10_tree_script.py"
    script.write_text(TREE_SCRIPT, encoding="utf-8")
    info = tmpPath / "u10_tree_info.jsonl"
    try:
        proc = subprocess.Popen(
            [sys.executable, str(script), str(info), "0"],
            cwd=str(tmpPath),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (PermissionError, OSError) as exc:
        pytest.skip(f"当前环境无权限派生子进程，跳过进程树实作验证: {exc}")
    deadline = time.time() + 60
    entries = {}
    while time.time() < deadline:
        if proc.poll() is not None:
            break  # 树脚本提前退出 → 下方按现场判失败
        entries = _readEntries(info)
        if len(entries) >= layers:
            break
        time.sleep(0.05)
    entries = _readEntries(info)
    if len(entries) < layers or proc.poll() is not None:
        _reapAll(SimpleNamespace(proc=proc, pids=[proc.pid]))
        pytest.fail(
            "三层进程树未能建立（受限环境请检查子进程权限）: "
            f"exitcode={proc.poll()} 已就绪层={sorted(entries)} "
            f"信息文件={info.read_text(encoding='utf-8') if info.exists() else '<无>'!r}")
    return SimpleNamespace(
        proc=proc,
        parent_pid=proc.pid,
        child_pid=entries[1],
        grand_pid=entries[2],
        pids=[proc.pid, entries[1], entries[2]],
    )


def _reapAll(tree):
    """兜底清理：强杀全树并收尸，断言失败也不向测试机泄漏长眠进程。"""
    for pid in getattr(tree, "pids", []):
        try:
            psutil.Process(pid).kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.Error):
            pass
    proc = getattr(tree, "proc", None)
    if proc is not None:
        try:
            proc.wait(timeout=10)
        except Exception:  # noqa: BLE001 - 收尸失败不再放大
            pass


def waitGone(pids, timeout=8.0):
    """轮询等待 pid 全部消失；超时返回仍存活清单。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        alive = [pid for pid in pids if psutil.pid_exists(pid)]
        if not alive:
            return []
        time.sleep(0.05)
    return [pid for pid in pids if psutil.pid_exists(pid)]


def _absentPid():
    """挑一个当前不存在的 pid（避开全部存活 pid）。"""
    alive = set(psutil.pids())
    candidate = 4
    while candidate in alive and candidate < 1 << 22:
        candidate += 1
    assert candidate not in alive
    return candidate


# ── 红→绿锚点：池清算路径必须收割整棵树 ─────────────────────────────────


def test_poolCleanupReapsWholeTree(tmp_path):
    """池 sweepIdle 清算持有真实进程的条目后，子/孙进程不得残留。

    现状（红）：_closeProcess 逐 pid terminate，孙进程仍存活。
    U10 接线 kill_tree 后（绿）：复查零残留。
    """
    tree = buildTree(tmp_path)
    pool = NeuacpProcessPool(maxProcs=1, idleSeconds=0.05)
    key = poolKey("t1", "u10tree", ["sleeper"], "")
    try:
        entry = pool.acquire(key, lambda: tree.proc)
        pool.release(key, entry)
        time.sleep(0.3)
        assert pool.sweepIdle() == 1
        try:
            tree.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass  # 根进程生死由下方 pid 断言诚实暴露
        alive = waitGone(tree.pids)
        assert not alive, (
            "池清算后进程树仍有残留（逐 pid terminate 杀不到子/孙进程）: "
            f"存活 pid={alive}")
    finally:
        _reapAll(tree)
        pool.shutdown()


def test_poolCleanupUsesKillTreeForRealPid(tmp_path, monkeypatch):
    """接线证据：池清算对带真实 pid 的进程调 kill_tree（而非只逐 pid terminate）。"""
    reaper = _reaper()
    seen = []
    realKillTree = reaper.kill_tree

    def spyKillTree(pid, grace_seconds=5.0):
        seen.append(pid)
        return realKillTree(pid, grace_seconds=grace_seconds)

    monkeypatch.setattr(reaper, "kill_tree", spyKillTree)
    try:
        proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(120)"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (PermissionError, OSError) as exc:
        pytest.skip(f"当前环境无权限派生子进程，跳过: {exc}")
    pool = NeuacpProcessPool(maxProcs=1, idleSeconds=0.05)
    key = poolKey("t1", "u10popen", ["sleeper"], "")
    try:
        entry = pool.acquire(key, lambda: proc)
        pool.release(key, entry)
        time.sleep(0.3)
        assert pool.sweepIdle() == 1
        assert seen == [proc.pid], f"池清算应经 kill_tree(pid) 收割: {seen}"
        assert not waitGone([proc.pid]), "kill_tree 接线后进程应已退出"
    finally:
        try:
            proc.kill()
        except psutil.Error:
            pass
        try:
            proc.wait(timeout=5)
        except Exception:  # noqa: BLE001
            pass
        pool.shutdown()


def test_poolFakeWithoutPidKeepsLegacyTerminate(monkeypatch):
    """无 pid 替身（既有池测试形态）不触发树清算，仍走原单 pid terminate 降级。"""
    reaper = _reaper()
    calls = []
    monkeypatch.setattr(reaper, "kill_tree",
                        lambda pid, grace_seconds=5.0: calls.append(pid) or [])
    pool = NeuacpProcessPool(maxProcs=1, idleSeconds=0.05)
    fake = FakeProc()
    key = poolKey("t1", "u10fake", ["x"], "")
    try:
        entry = pool.acquire(key, lambda: fake)
        pool.release(key, entry)
        time.sleep(0.2)
        assert pool.sweepIdle() == 1
        assert fake.terminated, "无 pid 替身仍应经原 terminate 路径关闭"
        assert calls == [], "无 pid 对象不得触发 kill_tree（防误杀任意 pid）"
    finally:
        pool.shutdown()


# ── kill_tree 实作（真实进程树） ─────────────────────────────────────────


def test_killTreeRemovesThreeLayerTree(tmp_path):
    """kill_tree 对三层真实进程树清算后复查零残留。"""
    reaper = _reaper()
    tree = buildTree(tmp_path)
    try:
        results = reaper.kill_tree(tree.parent_pid, grace_seconds=5)
        assert isinstance(results, list) and len(results) >= 3
        assert {item.pid for item in results} >= set(tree.pids)
        failed = [item for item in results if not item.ok]
        assert not failed, f"清算存在失败项: {failed}"
        try:
            tree.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
        alive = waitGone(tree.pids)
        assert not alive, f"kill_tree 后仍残留: pid={alive}"
    finally:
        _reapAll(tree)


def test_killTreeOnAbsentPidIsHonestIdempotentSuccess():
    """目标 pid 不存在：目标态（无此进程）已达成，ok=True 且 detail 注明。"""
    reaper = _reaper()
    absent = _absentPid()
    results = reaper.kill_tree(absent)
    assert len(results) == 1
    assert results[0].pid == absent
    assert results[0].ok is True
    assert results[0].detail, "幂等成功也须诚实注明（已退出/不存在）"


def test_killTreeRefusesSelfAndInvalidPids():
    """安全护栏：拒绝清算自身与非法 pid，且不伤及当前进程。"""
    reaper = _reaper()
    mine = os.getpid()
    results = reaper.kill_tree(mine)
    assert len(results) == 1 and results[0].pid == mine
    assert results[0].ok is False
    assert psutil.pid_exists(mine), "拒绝清算自身后当前进程必须仍然存活"
    bad = reaper.kill_tree(-1)
    assert len(bad) == 1 and bad[0].pid == -1 and bad[0].ok is False


# ── Windows 形态：CIM 快照 BFS + 20/批 taskkill（逻辑单测，注入替身） ────


def test_parseProcessMapFromCsv():
    reaper = _reaper()
    csvText = '"ProcessId","ParentProcessId"\r\n"123","4"\r\n"456","123"\r\n'
    assert reaper.parseProcessMap(csvText) == {123: 4, 456: 123}


def test_collectTreeBfsRootFirst():
    reaper = _reaper()
    mapping = {1: 0, 2: 1, 3: 1, 4: 2, 5: 2, 6: 3}
    assert reaper.collectTree(1, mapping) == [1, 2, 3, 4, 5, 6]
    # 根不在快照：仅返回根（由上层按"已退出"诚实上报）
    assert reaper.collectTree(999, mapping) == [999]


def test_windowsReapBatchesTaskkillTwentyPerCall(monkeypatch):
    """25 个目标按 20/批拆批；根优先；杀后复查全死 → 逐 pid ok。"""
    reaper = _reaper()
    mapping = {1: 0}
    for pid in range(2, 22):  # 20 个直接子进程
        mapping[pid] = 1
    for pid in range(22, 26):  # 4 个孙进程
        mapping[pid] = 2
    batches = []
    snapshots = [mapping, {}]  # 杀前全量、杀后清空

    monkeypatch.setattr(reaper, "winProcessMap", lambda: snapshots.pop(0) if snapshots else {})
    monkeypatch.setattr(reaper, "_taskkillBatch",
                        lambda pids: batches.append(list(pids)) or (True, ""))
    results = reaper._reapWindows(1)
    assert batches, "必须发起批量 taskkill"
    assert all(len(chunk) <= reaper.TASKKILL_BATCH for chunk in batches)
    assert sum(len(chunk) for chunk in batches) == 25
    assert batches[0][0] == 1, "BFS 根优先：根必须在首批"
    assert len(results) == 25 and all(item.ok for item in results)


def test_windowsReapReportsSurvivorsHonestly(monkeypatch):
    """taskkill 后仍在快照中的 pid → ok=False 带 detail；不吞失败。"""
    reaper = _reaper()
    mapping = {1: 0, 2: 1, 3: 1}
    monkeypatch.setattr(reaper, "winProcessMap", lambda: mapping)
    monkeypatch.setattr(reaper, "_taskkillBatch", lambda pids: (False, "拒绝访问"))

    def fakeAncestor(pid, parentMap, treeSet):
        return False

    monkeypatch.setattr(reaper, "_ancestorInTree", fakeAncestor)
    results = reaper._reapWindows(1)
    byPid = {item.pid: item for item in results}
    assert byPid[1].ok is False and "拒绝访问" in byPid[1].detail
    assert byPid[2].ok is False and byPid[3].ok is False


# ── POSIX 形态：killpg 优先 / 退化逐 pid SIGTERM→宽限→SIGKILL（逻辑单测）──


def test_posixReapGroupGracefulExit(monkeypatch):
    """根为进程组长：killpg(SIGTERM) 一次收组，宽限期内全退 → 不升级。"""
    reaper = _reaper()
    killpgLog = []
    killLog = []
    monkeypatch.setattr(reaper, "_posixTreePids", lambda root: [200, 201])
    monkeypatch.setattr(os, "getpgid", lambda pid: 200, raising=False)
    monkeypatch.setattr(os, "killpg",
                        lambda pgid, sig: killpgLog.append((pgid, sig)), raising=False)
    monkeypatch.setattr(os, "kill", lambda pid, sig: killLog.append((pid, sig)), raising=False)
    monkeypatch.setattr(reaper, "_posixAlive", lambda pid: False)
    results = reaper._reapPosix(200, grace_seconds=0.05)
    assert killpgLog == [(200, signal.SIGTERM)]
    assert killLog == [], "组级路径成功时不得退化逐 pid"
    assert len(results) == 2 and all(item.ok for item in results)


def test_posixReapDegradesToPerPidSignalEscalation(monkeypatch):
    """不成组：逐 pid SIGTERM → 宽限超时 → 逐 pid SIGKILL。"""
    reaper = _reaper()
    killLog = []
    monkeypatch.setattr(reaper, "_posixTreePids", lambda root: [100, 101, 102])

    def fakeGetpgid(pid):
        raise ProcessLookupError(errno.ESRCH, "no such process")

    monkeypatch.setattr(os, "getpgid", fakeGetpgid, raising=False)
    monkeypatch.setattr(os, "kill", lambda pid, sig: killLog.append((pid, sig)), raising=False)
    monkeypatch.setattr(reaper, "_posixAlive", lambda pid: True)  # 宽限期内不退
    results = reaper._reapPosix(100, grace_seconds=0.05)
    sigterm = getattr(signal, "SIGTERM", 15)
    sigkill = getattr(signal, "SIGKILL", 9)  # Windows 无 SIGKILL 常量，同值回退
    sigterms = [pid for pid, sig in killLog if sig == sigterm]
    sigkills = [pid for pid, sig in killLog if sig == sigkill]
    assert sigterms == [100, 101, 102]
    assert sigkills == [100, 101, 102], "宽限超时必须逐 pid 升级 SIGKILL"
    assert len(results) == 3 and all(item.ok for item in results)


def test_killTreeDispatchesByPlatform(monkeypatch):
    """统一入口按平台自动选择：win32 → _reapWindows，其余 → _reapPosix。"""
    reaper = _reaper()
    hits = []
    monkeypatch.setattr(reaper, "_reapWindows",
                        lambda pid, batch_size=20: hits.append(("win", pid))
                        or [reaper.PerProcessResult(pid, True)])
    monkeypatch.setattr(reaper, "_reapPosix",
                        lambda pid, grace_seconds=5.0: hits.append(("posix", pid))
                        or [reaper.PerProcessResult(pid, True)])
    monkeypatch.setattr(sys, "platform", "win32")
    reaper.kill_tree(11)
    monkeypatch.setattr(sys, "platform", "linux")
    reaper.kill_tree(22, grace_seconds=1)
    assert hits == [("win", 11), ("posix", 22)]
