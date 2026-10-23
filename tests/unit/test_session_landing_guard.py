# -*- coding: utf-8 -*-
"""会话落点隔离守卫：跑测期间 SessionManager 不得指向仓库真实会话库

判据全文与成因见 `tests/conftest.py::_guardSessionLandingIsIsolated` 与
`audit-reports/simplification-audit-2026-10-05.md` §6-29。要点两条：

1. `chdir` 隔离不了数据根落点——`c2cb809c`(09-22) 把兜底落点收进数据根之后，
   凡靠切 CWD 隔离会话目录的用例都在读写仓库 `data/sessions/`；
2. 目录内容判据不可用——要么全树指纹太贵（实测 4.71ms/次 × 每用例 2 次），
   要么退化成文件清单差集，而清单差**看不见原地改写与等量搬移**（本条取证时
   `test_session_archive` 就是报 added=0 却实际搬动 15 个真实文件）。

所以判据钉在装配点：单例存在且 `_sessions_dir == <仓库>/data/sessions` 即红。
探针全走行为（子进程真跑一条用例），不读 pytest 内部属性——同
`test_repo_root_pollution_guard.py` 的取向。
"""

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

#: 本档在 `tests/unit/` 下（比 `tests/unit/ci/` 少一层）——N 必须是 2，写成 3 会解到仓外，
#: 那时「仓根没有新增条目」读的是空目录，判据看着绿、其实一句话都没说。
REPO_ROOT = Path(__file__).resolve().parents[2]
#: 探针刻意落点的路径锚，必须写在模块级：绑在函数里的名字，面自证棘轮的取数口认不出，整档会静默掉出它的面。
#: 回收上限：`<repo>/data`。**先写这一条**，`SESSIONS_DIR` 由它派生——反过来的话
#: `DATA_DIR = SESSIONS_DIR.parent` 是纯派生表达式，面自证棘轮解不出静态落点（`dynamic`），
#: 而 `<repo>/data/sessions` 在探针造出它之前并不存在（解成 `missing`），两条都会被点名。
DATA_DIR = REPO_ROOT / "data"
SESSIONS_DIR = DATA_DIR / "sessions"


def _cleanupProbeRealLanding():
    """删掉探针**刻意**建出的 `<repo>/data/sessions`，并逐级回收空祖先。

    只在目录为空（探针没往里写过会话）时删；非空说明有真实数据，
    宁可留着让人看见也不静默删（这里不吞异常的另一面）。
    回收上限是 `<repo>/data`：再往上不是本探针建的，不碰。
    空判定只看**一个**目录（`SESSIONS_DIR`）：它删空之后祖先才可能空，而祖先是从模块级
    常量 `DATA_DIR` 取的同一条路径——不再就地拼 `<repo>/data`，面自证棘轮才不会把
    「可能尚不存在的中间目录」解成 `missing`。
    """
    def emptyDir(directory):
        # 先 `is_dir()` 再枚举：目录不在时"没读到"不等于"空了"；枚举本身只能对着
        # 模块级常量发起——把落点转进参数的写法，面自证棘轮解不出根、这一档会整档掉出它的面。
        return directory.is_dir() and not any(directory.iterdir())

    try:
        if emptyDir(SESSIONS_DIR):
            SESSIONS_DIR.rmdir()
        # 再回收 `data/`：它**只在确实空了**时删（非空说明有别的真实数据，留着让人看见）。
        if emptyDir(DATA_DIR):
            DATA_DIR.rmdir()
    except OSError:
        pass


#: 子进程 pytest 的等待上界；消费它的四格各带 +60s 的父墙（父墙 ≤ 子墙时先到点的是
#: 全局 30s，Windows 侧 thread 法超时＝终止整个进程，§6-402 批 K）。
CHILD_PYTEST_WALL_S = 180


def _runProbe(fileName: str, body: str, expectGreen: bool) -> str:
    """子进程跑一条临时探针用例（用完即删）。

    `NEUROVA_SESSIONS_DIR` 必须从环境里摘掉再启动：父进程正跑在自己的隔离夹具里，
    那个变量会随环境继承下去，探针测到的就不是"仓库默认行为"而是父进程的注入值。
    反过来 `PYTHONIOENCODING` 必须**显式钉上**：探针写侧与父进程读侧要同一个编码——
    本仓跑测常带这个变量，只靠继承就等于把红绿挂在"谁怎么起的"上（父端按 cp936 解子端
    写的 UTF-8 ⇒ reader 线程崩、`proc.stdout` 变 None ⇒ 报的是 TypeError 而不是落点缺陷）。
    """
    import copy

    probeEnv = copy.deepcopy(os.environ)
    probeEnv.pop("NEUROVA_SESSIONS_DIR", None)
    probeEnv["PYTHONIOENCODING"] = "utf-8"
    probeFile = REPO_ROOT / "tests" / "unit" / fileName
    # 探针会**刻意**把落点设回"仓库真实会话库"（这正是它要证的事），
    # 子进程构造 SessionManager 时 `mkdir` 便会在仓库根建出 `data/sessions/`。
    # 父进程的 `_guardRepoRootAgainstPollution` 会因此点名本用例——故探针退出后
    # 把这次**刻意的**落点收干净（只在它确实是探针建的空目录时删）。
    # 面读数：本档的清理路径以仓根为锚——锚指错了，「探针没在仓库里留下会话目录」这句就落在不存在的路径上。
    repoEntries = [p for p in REPO_ROOT.iterdir()]
    assert len(repoEntries) > 20, (
        f"仓根现读 {len(repoEntries)} 个条目（锚＝{REPO_ROOT}，会话落点＝{SESSIONS_DIR}）——"
        "量级不对＝锚指错，清理与判定都不来自代码")
    try:
        probeFile.write_text(textwrap.dedent(body), encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", f"tests/unit/{fileName}",
             "-p", "no:cacheprovider", "-q", "--tb=short"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=CHILD_PYTEST_WALL_S,
            env=probeEnv,
        )
        out = proc.stdout + proc.stderr
        if expectGreen:
            assert proc.returncode == 0, f"探针应当全绿却红了：\n{out[-800:]}"
        else:
            assert proc.returncode != 0, f"探针本该失败却全绿（守卫没咬住）：\n{out[-800:]}"
        return out
    finally:
        probeFile.unlink(missing_ok=True)
        _cleanupProbeRealLanding()


@pytest.mark.timeout(CHILD_PYTEST_WALL_S + 60)
def test_bareSessionManagerIsIsolatedByDefault():
    """默认隔离本身：什么都不设的 `SessionManager()` 也必须落在本用例 tmp 里。

    这条判据盯的是 `tests/conftest.py::_isolateSessionsLanding`——起真 app 的用例
    （TestClient → startup → console）会在自己那条里重新构造单例，没有默认隔离时
    它们全部读写仓库真实库（实测 16 条/7 文件，逐条补 env 属打补丁）。
    """
    _runProbe(
        "test_tmpSessionLandingDefaultProbe.py",
        '''
        from pathlib import Path


        def testBareSessionManagerLandsInTmp():
            from neurova.session_manager import SessionManager
            real = Path(__file__).resolve().parents[2] / "data" / "sessions"
            landing = Path(SessionManager()._sessions_dir)
            assert landing != real, "默认没设 env 时落点仍是仓库真实库：%s" % landing
            assert landing.name == "sessions", landing
        ''',
        expectGreen=True,
    )


@pytest.mark.timeout(CHILD_PYTEST_WALL_S + 60)
def test_explicitRealLandingTripsGuard():
    """显式把落点改回仓库真实库 → 收尾守卫必须当场红并点名。

    默认隔离挡的是"没设"，守卫挡的是"设错"——两条缺一不可：只有默认值时，
    一句 `setenv(真实路径)` 就能穿透；只有守卫时，起真 app 的每条用例都要自己补 env。
    """
    out = _runProbe(
        "test_tmpSessionLandingTripProbe.py",
        '''
        from pathlib import Path


        def testExplicitRealLanding(tmp_path, monkeypatch):
            from neurova.session_manager import SessionManager
            real = Path(__file__).resolve().parents[2] / "data" / "sessions"
            monkeypatch.setenv("NEUROVA_SESSIONS_DIR", str(real))
            SessionManager._instance = None
            assert SessionManager()._sessions_dir == real
        ''',
        expectGreen=False,
    )
    assert "本条用例让 SessionManager 单例落在仓库真实会话库" in out, out[-800:]


@pytest.mark.timeout(CHILD_PYTEST_WALL_S + 60)
def test_envIsolatedSessionManagerStaysGreen():
    """走 `NEUROVA_SESSIONS_DIR` 指到临时目录的正确形态 → 不得误伤。"""
    _runProbe(
        "test_tmpSessionLandingCleanProbe.py",
        """
        def testIsolatedSessionManager(tmp_path, monkeypatch):
            from neurova.session_manager import SessionManager
            monkeypatch.setenv("NEUROVA_SESSIONS_DIR", str(tmp_path / "sessions"))
            SessionManager._instance = None
            try:
                assert SessionManager()._sessions_dir == tmp_path / "sessions"
            finally:
                SessionManager._instance = None
        """,
        expectGreen=True,
    )


@pytest.mark.timeout(CHILD_PYTEST_WALL_S + 60)
def test_probeTouchingNoSessionManagerStaysGreen():
    """没碰过该模块的用例不得被拖进判据（无单例即无从归因）。"""
    _runProbe(
        "test_tmpSessionLandingUnrelatedProbe.py",
        """
        def testUnrelated():
            assert 1 + 1 == 2
        """,
        expectGreen=True,
    )
