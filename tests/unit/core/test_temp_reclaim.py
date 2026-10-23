"""pytest 临时目录「锁主判活即回收」。

根因（2026-09-21 E 盘 22.37 GB 残留取证）：pytest 会话被强杀时 `atexit` 不执行，
`pytest-<N>/.lock` 就永久留在那个目录里；而回收侧把锁的有效期定为
`LOCK_TIMEOUT = 60*60*24*3`——**三天**。这三天内每一轮会话的 GC 都会跳过该目录，
于是"会话被杀 → 目录免疫三天 → 三天窗口内所有被杀会话叠起来"成为稳态。

本模块在会话启动时主动判断锁主进程是否真的还存在，**确证已死**才回收，把三天
窗口压成"下一轮会话"。判据拿不准时一律不删：宁可留一个目录等 pytest 自己收，
也不能误删并发会话正在写的临时目录。
"""

from __future__ import annotations

import getpass
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from types import SimpleNamespace

import pytest

from tests import temp_reclaim
from tests.temp_reclaim import holderIsDead, processStartedAt, reclaimDeadLockedDirs, sessionTempRoot


def _makeSessionDir(root: Path, number: int, pid: int) -> Path:
    """造一个形如 pytest-<number> 的会话目录。

    `.lock` 按 pytest 的真实形态来：`create_cleanup_lock` 用
    `os.open(..., O_WRONLY|O_CREAT|O_EXCL)` 建的是**文件**，内容就是持有者的 pid。
    """
    sessionDir = root / "pytest-{}".format(number)
    sessionDir.mkdir(parents=True)
    (sessionDir / ".lock").write_text(str(pid), encoding="utf-8")
    (sessionDir / "artifact.txt").write_text("payload", encoding="utf-8")
    return sessionDir


def test_reclaimsSessionDirWhoseLockHolderIsDead(tmp_path):
    deadDir = _makeSessionDir(tmp_path, number=101, pid=4242)

    removed = reclaimDeadLockedDirs(tmp_path, holderIsDead=lambda pid, lockMtime: True)

    assert removed == [deadDir]
    assert not deadDir.exists(), "锁主已确证死亡，目录连同 .lock 应被一并回收"


def test_keepsSessionDirWhoseLockHolderIsAlive(tmp_path):
    liveDir = _makeSessionDir(tmp_path, number=102, pid=os.getpid())

    removed = reclaimDeadLockedDirs(tmp_path, holderIsDead=lambda pid, lockMtime: False)

    assert removed == []
    assert liveDir.exists(), "锁主还活着，绝不能碰——那可能是另一个并发会话正在写的目录"


def test_keepsDirectoryWithoutLockFile(tmp_path):
    """没有 `.lock` 就无从判活，交给 pytest 自己的 keep=3 回收，不猜。"""
    locklessDir = tmp_path / "pytest-103"
    locklessDir.mkdir()

    removed = reclaimDeadLockedDirs(tmp_path, holderIsDead=lambda pid, lockMtime: True)

    assert removed == []
    assert locklessDir.exists()


def test_keepsSessionDirWithUnparsableLock(tmp_path):
    """锁内容坏掉时判活依据不可信，宁可不删。"""
    corruptDir = tmp_path / "pytest-104"
    corruptDir.mkdir()
    (corruptDir / ".lock").write_text("not-a-pid", encoding="utf-8")

    removed = reclaimDeadLockedDirs(tmp_path, holderIsDead=lambda pid, lockMtime: True)

    assert removed == []
    assert corruptDir.exists()


def test_ignoresEntriesThatAreNotNumberedSessionDirs(tmp_path):
    """只认 `pytest-<数字>` 形态，TEMP 里的其他内容一律不碰。"""
    others = [tmp_path / "pytest-current", tmp_path / "pytest-abc", tmp_path / "garbage-1",
              tmp_path / "neurovaMoeState-x"]
    for other in others:
        other.mkdir()
    (tmp_path / "pytest-lockfile.txt").write_text("x", encoding="utf-8")

    removed = reclaimDeadLockedDirs(tmp_path, holderIsDead=lambda pid, lockMtime: True)

    assert removed == []
    for other in others:
        assert other.exists()
    assert (tmp_path / "pytest-lockfile.txt").exists()


def test_reportsHolderDeadWhenProcessDoesNotExist():
    assert holderIsDead(4242, lockMtime=1000.0, probe=lambda pid: None) is True


def test_reportsHolderAliveWhenProcessStartedBeforeTheLock():
    assert holderIsDead(4242, lockMtime=1000.0, probe=lambda pid: 900.0) is False


def test_reportsHolderDeadWhenProcessStartedLongAfterTheLock():
    """pid 会被操作系统回收复用。进程比锁还「新」，说明它不是当初写锁的那个进程。"""
    assert holderIsDead(4242, lockMtime=1000.0, probe=lambda pid: 5000.0) is True


def test_treatsTinyClockSkewAsTheSameProcess():
    """进程创建时间与文件 mtime 来自不同时钟源，有取整误差；晚一丁点不能误杀活会话。"""
    assert holderIsDead(4242, lockMtime=1000.0, probe=lambda pid: 1000.5) is False


def test_recognizesOwnProcessAsExisting():
    startedAt = processStartedAt(os.getpid())

    assert startedAt is not None, "本进程必然存在"
    assert startedAt <= time.time(), "取到的必须是过去的时刻；0.0 表示该平台取不到启动时间"


def test_keepsOwnLiveSessionViaRealProbe():
    assert holderIsDead(os.getpid(), lockMtime=time.time(), probe=processStartedAt) is False


def test_returnsNoneForPidThatWasNeverAlive():
    """锁主已消失的确证路径。

    不用"刚 wait() 掉的子进程"做样本：Windows 上进程对象要等**所有**句柄关闭才消失，
    父进程仍持句柄时 OpenProcess 依然成功。真实残留锁的持有者是孤儿进程，没人持句柄，
    所以这里用必然不存在的 pid 取证。
    """
    assert processStartedAt(0xFFFFFFFF) is None


def test_composesToDeadForVanishedHolder():
    assert holderIsDead(0xFFFFFFFF, lockMtime=time.time(), probe=processStartedAt) is True


def _stubSession(basetemp):
    return SimpleNamespace(config=SimpleNamespace(option=SimpleNamespace(basetemp=basetemp)))


def test_returnsEmptyWhenTempRootDoesNotExist(tmp_path):
    """新机器上 TEMP 根目录可能还没被建出来，这不该算异常。"""
    missing = tmp_path / "notCreatedYet"

    assert reclaimDeadLockedDirs(missing, holderIsDead=lambda pid, mtime: True) == []


def test_keepsReclaimingSiblingsWhenOneRemovalFails(tmp_path):
    """单个目录被占用不能中断整轮清扫，也不能静默——必须报警。"""
    blocked = _makeSessionDir(tmp_path, number=201, pid=0xFFFFFFFF)
    reclaimed = _makeSessionDir(tmp_path, number=202, pid=0xFFFFFFFF)

    def flakyRemove(path):
        if path.name == blocked.name:
            raise PermissionError("目录被占用")
        shutil.rmtree(path)

    with pytest.warns(UserWarning, match=str(blocked.name)):
        removed = reclaimDeadLockedDirs(tmp_path, holderIsDead=lambda pid, mtime: True,
                                        remove=flakyRemove)

    assert removed == [reclaimed]
    assert blocked.exists()
    assert not reclaimed.exists()


def test_sessionStartWiresReclaim(tmp_path, monkeypatch):
    """钩子必须真的挂在会话启动上，否则这个模块就是没有调用方的死代码。"""
    deadDir = _makeSessionDir(tmp_path, number=301, pid=0xFFFFFFFF)
    liveDir = _makeSessionDir(tmp_path, number=302, pid=os.getpid())
    monkeypatch.setattr(temp_reclaim, "sessionTempRoot", lambda: tmp_path)

    temp_reclaim.pytest_sessionstart(_stubSession(basetemp=None))

    assert not deadDir.exists()
    assert liveDir.exists(), "本会话自己的目录必须保留"


def test_sessionStartSkippedWhenBasetempGiven(tmp_path, monkeypatch):
    """显式 --basetemp 时 pytest 自己会清空该目录，不在这套约定下，别乱动。"""
    kept = _makeSessionDir(tmp_path, number=303, pid=0xFFFFFFFF)
    monkeypatch.setattr(temp_reclaim, "sessionTempRoot", lambda: tmp_path)

    temp_reclaim.pytest_sessionstart(_stubSession(basetemp=tmp_path / "given"))

    assert kept.exists()


def test_sessionTempRootFollowsPytestConvention():
    root = sessionTempRoot()

    assert root.parent == Path(tempfile.gettempdir())
    assert root.name.startswith("pytest-of-")


#: 子进程那一趟 pytest 的等待上界。父墙必须由它导出且**严格高于**它：本仓
#: `pyproject.toml` 只声明 `timeout = 30`，Windows 侧 pytest-timeout 自动走 thread 法，
#: 超时不是「这一格红」而是终止整个进程——2026-10-23 早 `pytest tests/unit` 正是在
#: 44% 处消失在本格（§6-402 批 K）。
CHILD_PYTEST_WALL_S = 300
@pytest.mark.timeout(CHILD_PYTEST_WALL_S + 60)
def test_pytestInvokesTheHookWithoutAHandCall(tmp_path):
    """回收必须发生在 pytest **自己的**会话启动里，而不是只在单测里被手调一次。

    `test_sessionStartWiresReclaim` 把 stub session 手工喂给钩子，它只能证明
    "被调用时它管用"；而 2026-09-21 那版守卫的真实故障恰好是**没有任何人调用它**——
    钩子写在普通模块 `tests/temp_reclaim.py` 里，pytest 只从 conftest / 已注册插件
    收集钩子函数，于是 18 条判据全绿而回收从未跑过。判据必须走真子进程：
    注册丢了，本条就红。
    """
    tempRoot = tmp_path / "tempRoot"
    scratch = tempRoot / "pytest-of-{}".format(getpass.getuser())
    scratch.mkdir(parents=True)
    deadDir = _makeSessionDir(scratch, number=9101, pid=0xFFFFFFFF)
    liveDir = _makeSessionDir(scratch, number=9102, pid=os.getpid())

    env = os.environ.copy()
    for key in ("TEMP", "TMP", "TMPDIR"):
        env[key] = str(tempRoot)
    # 子进程是本仓的 pytest（Python 件）⇒ 两头一起钉死：子端强制 UTF-8 输出、父端按 UTF-8 解。
    # 只补父端 `encoding="utf-8"` 而不钉子端，等于把"父按 locale 解"换成"父按 utf-8 解子端
    # 按 cp936 写"——中文路径（本仓就在 `…\项目\Neurova` 下）会被替换成 U+FFFD，比原来更坏。
    env["PYTHONIOENCODING"] = "utf-8"

    repoRoot = Path(__file__).resolve().parents[3]
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", __file__,
         "-k", "reportsHolderDeadWhenProcessDoesNotExist",
         "-q", "-p", "no:cacheprovider", "--no-header"],
        cwd=str(repoRoot), env=env, capture_output=True, text=True,
        timeout=CHILD_PYTEST_WALL_S,
        encoding="utf-8", errors="replace",
    )

    assert completed.returncode == 0, "子会话没跑起来，本条判据失去观测对象：\n" + completed.stdout[-2000:]
    assert not deadDir.exists(), (
        "锁主已确证死亡的残留目录活过了一整轮 pytest 会话——"
        "说明 pytest_sessionstart 从未被 pytest 调用（钩子未注册）"
    )
    assert liveDir.exists(), "子会话不得把还活着的持有者目录一并删掉"


def test_reclaimClearsReadOnlyObjectsAndStillRemovesTheDeadDir(tmp_path):
    """**只读位挡住的死目录必须照删**——Windows 上这正是唯一会长期留存的残留形态。

    实测（2026-10-23 批 K 的分块跑测）：被强杀的会话在
    `pytest-<N>/…/.git/objects/…` 下留下**只读**文件（git 给 object 文件加 0444），
    `shutil.rmtree` 当场 `PermissionError [WinError 5] 拒绝访问`，回收侧只 warn 一句就
    **永久跳过**它。后果不是"难看"：本模块的全部意义是"把强杀残留从三天窗口压成下一轮"，
    而这一类残留一轮都收不掉——每开一轮跑测就从 `temp_reclaim.py:156` 打出一批同样的警告，
    警告里点名的目录数只增不减。
    清只读位**不是**放宽判据：授权来源始终是 `holderIsDead` 确证已死，只是把"删不动"
    与"不该删"这两种形态分开——后者由下一格负对照钉住。

    现查读数（2026-10-23，本机 TEMP 会话根）：10 个 `pytest-<N>` 目录里 **8 个含只读文件**，
    最早的一个是 2026-10-22 18:11 留下的——它们全都躲过了每一轮回收。
    """
    dead = _makeSessionDir(tmp_path, number=9199, pid=0xFFFFFFFF)
    objectDir = dead / "subject.git" / "objects" / "77"
    objectDir.mkdir(parents=True)
    blob = objectDir / "3cdb61c256951982bf071faf1e9ff277ab97e4"
    blob.write_bytes(b"payload")
    blob.chmod(stat.S_IREAD)
    assert not (blob.stat().st_mode & stat.S_IWRITE), (
        "前置没做成：这台机器上只读位没设上，本格会因『根本没有障碍』而假绿"
    )

    removed = reclaimDeadLockedDirs(tmp_path, holderIsDead=lambda pid, lockMtime: True)

    assert removed == [dead], (
        "只读文件让 rmtree 抛 PermissionError，回收侧 warn 完就跳过——死目录永久留存，"
        "每一轮跑测的日志都被它污染一次"
    )
    assert not dead.exists()


def test_doesNotTouchReadOnlyDirWhoseHolderIsStillLive(tmp_path):
    """负对照：清只读位不等于获得删除权——锁主还活着的只读目录一律不碰。"""
    live = _makeSessionDir(tmp_path, number=9200, pid=os.getpid())
    objectDir = live / "subject.git" / "objects" / "11"
    objectDir.mkdir(parents=True)
    blob = objectDir / "deadbeefdeadbeef"
    blob.write_bytes(b"x")
    blob.chmod(stat.S_IREAD)

    removed = reclaimDeadLockedDirs(tmp_path, holderIsDead=lambda pid, lockMtime: False)

    assert removed == [] and live.exists(), "锁主活着却把只读子树清了/删了＝误删并发会话的在写目录"
    assert not (blob.stat().st_mode & stat.S_IWRITE), "负对照不该顺手清只读位"



