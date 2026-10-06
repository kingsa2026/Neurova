# -*- coding: utf-8 -*-
"""仓库根污染守卫：跑测期间新增的顶层条目必须当场点名肇事用例

三条缺陷登记在同一段历史里（`audit-reports/simplification-audit-2026-10-05.md` §6-26/27）：
仓库根反复长出 `MagicMock/…/.lifecycle_state.json`，而 `.gitignore:380` 的 `/MagicMock/`
让它对 `git status` 完全隐身——`84260bb4`(06-08) 排除、`dd03d67c`(09-02) 提交说明自陈
"根目录二次清理 + gitignore 防再生"、10-04 再现。三次都停在"清理 + 忽略"，
**没人能说出是哪条用例写的**，因为整场跑测的快照给不出归因。

本守卫的判据就一条：**单条用例执行前后，仓库根顶层条目集合不得新增**。
逐用例（而非整场）是归因的唯一来源；成本实测单次 listdir 0.10ms、每用例 2 次。

这里不放"已知会写根目录"的例外名单——一旦开口就重演"用 ignore 当止痛"。
真需要在根目录落东西的合法流程（构建产物等）应显式改 CWD 或走数据根锚点，
而不是让守卫闭嘴。
"""

import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _topLevelEntries() -> set:
    return set(os.listdir(REPO_ROOT))


def _runPytestProbe(fileName: str, body: str, expectGreen: bool) -> str:
    """在子进程里跑一条临时探针用例，返回其输出（探针即用完即删）。

    判据全走**行为**而不是读 pytest 内部属性：pytest 9 把夹具对象换成了
    `FixtureFunctionDefinition`，钉 `_pytestfixturefunction.autouse` 这类写法
    下次升级即碎，而且"属性存在"本身也证明不了守卫咬得住。
    """
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
        )
        out = proc.stdout + proc.stderr
        if expectGreen:
            assert proc.returncode == 0, f"探针应当全绿却红了：\n{out[-700:]}"
        else:
            assert proc.returncode != 0, f"探针本该失败却全绿（守卫没咬住）：\n{out[-700:]}"
        return out
    finally:
        probeFile.unlink(missing_ok=True)


def test_guardIsARegisteredFixture():
    """夹具必须真注册（能按名请求到），否则守卫只是文件里的一段文字。"""
    out = _runPytestProbe(
        "testFixtureRegistrationProbe.py",
        """
        def test_guardCanBeRequestedByName(_guardRepoRootAgainstPollution):
            assert _guardRepoRootAgainstPollution is None
        """,
        expectGreen=True,
    )
    assert "fixture '_guardRepoRootAgainstPollution' not found" not in out


def test_mockShapedEntriesAreNotSittingInTheRepoRoot():
    """静态反证：被 ignore 隐身的历史垃圾形态，本守卫仍要能当场看见。

    `MagicMock/` 这类目录名直接来自 mock 的 repr（`<MagicMock name='…' id='…'>`），
    合法目录不会长成这样，因此无需白名单也不会误报。
    """
    offenders = sorted(
        name
        for name in _topLevelEntries()
        if "Mock" in name or name.startswith("<") or name.endswith(">")
    )
    assert offenders == [], f"仓库根存在 mock 形态的污染目录：{offenders}——它们被 .gitignore 隐着，git status 看不见"


def test_guardFiresPerTestAndNamesTheOffender(tmp_path):
    """端到端三条一起证：autouse 生效、作用域是逐用例、报错点名条目与肇事用例。

    作用域判据藏在这里：整场（session）作用域的夹具只会在收尾时算总账，
    pytest 报的是无 nodeid 的 session teardown ERROR——那正是过去三次"清理 + 忽略"
    定位不到肇事者的原因，所以这条断言必须钉住"输出里出现用例名"。
    """
    junkName = "zzPollutionProbeJunk"
    junkDir = REPO_ROOT / junkName
    assert not junkDir.exists(), "上一次探测残留会污染快照基线"
    try:
        out = _runPytestProbe(
            "test_pollutionProbe.py",
            f"""
            from pathlib import Path

            def test_polluteRepoRoot():
                (Path(__file__).resolve().parents[2] / "{junkName}").mkdir()
                assert True
            """,
            expectGreen=False,
        )
    finally:
        shutil.rmtree(junkDir, ignore_errors=True)

    assert junkName in out, f"报错没点名新增条目：{out[-500:]}"
    assert "test_polluteRepoRoot" in out, f"报错没点名肇事用例（作用域不是逐用例）：{out[-500:]}"


def test_cleanTestDoesNotTripTheGuard():
    """反证另一半：不落根目录的用例必须照常绿——守卫不能靠误伤逼人摘掉它。"""
    _runPytestProbe(
        "test_cleanProbe.py",
        """
        def test_nothingWritten():
            assert True
        """,
        expectGreen=True,
    )
