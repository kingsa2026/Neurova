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

REPO_ROOT = Path(__file__).resolve().parents[2]


def _runProbe(fileName: str, body: str, expectGreen: bool) -> str:
    """子进程跑一条临时探针用例（用完即删）。

    `NEUROVA_SESSIONS_DIR` 必须从环境里摘掉再启动：父进程正跑在自己的隔离夹具里，
    那个变量会随环境继承下去，探针测到的就不是"仓库默认行为"而是父进程的注入值。
    """
    import copy

    probeEnv = copy.deepcopy(os.environ)
    probeEnv.pop("NEUROVA_SESSIONS_DIR", None)
    probeFile = REPO_ROOT / "tests" / "unit" / fileName
    try:
        probeFile.write_text(textwrap.dedent(body), encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", f"tests/unit/{fileName}",
             "-p", "no:cacheprovider", "-q", "--tb=short"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=180,
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
