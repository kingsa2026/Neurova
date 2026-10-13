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

探针自己的落点（`83dad089`，2026-10-09）：本文件的探针一度把临时用例写进**共享**
`tests/unit/`、又以 `cwd=REPO_ROOT` 起子进程，于是子进程建的顶层垃圾目录也落在共享仓库根。
`finally` 抹掉后本会话看不出错，但同一工作树里另一条并发会话会把它记给**自己的**无辜用例
（实测：§6-9 批的宽域 A/B 里 `test_candidate_statistics_come_from_real_prune_history`
的 teardown 报出 `zzPollutionProbeJunk`）。现改为在仓外 detached git worktree 里跑探针，
整模块共用一棵树，并由 `test_probeWritesStayOutOfTheSharedWorkingTree` 以轮询线程钉住
"共享根与共享 tests/unit 全程无痕"——判据走过程观测，事后检查会被 `finally` 抹平。
另：该笔提交正文写的净 LOC `+85/-16` 是估算，按 `git diff --numstat` 实数为 **112/8**，
在此勘误（本仓先例：不改历史，另笔落字）。

探针的墙钟额度和它的判据无关（2026-10-13 CI `cnb-elr-1k4pvclq5` 实测）：
两条探针用例在共享负载下撞 `pyproject.toml` 的 30s 默认墙钟转红，而它们要钉的
是"落点在自己那棵树里"这条**结构**事实。子进程 pytest 那一段因此显式放宽
（`_PROBE_PYTEST_TIMEOUT_S`）——把额度与契约分开，不让守卫自己成为偶发红源。
"""

import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

#: 探针子命令的超时额度——**超时不是被测契约**：本模块要钉的是"探针的落点在
#: 它自己那棵树里"，不是"子进程 pytest 多快"。额度按 `pyproject.toml` 的
#: `timeout = 30` 反推：起子进程 pytest 一段在共享负载下本就贴墙钟，留出余量
#: 免得本守卫自己成为偶发红源（实测 2026-10-13 CI `cnb-elr-1k4pvclq5`：
#: 两条探针用例撞 30s 默认墙钟转红）。
_PROBE_PYTEST_TIMEOUT_S = 240


def _topLevelEntries() -> set:
    return set(os.listdir(REPO_ROOT))


def _acquireProbeRoot() -> tuple[Path, Path]:
    """给探针一棵**自己独占**的仓库根：把装配面复制到临时目录，不借 git 元数据。

    为什么是整棵装配面而不是临时目录里摆几个文件：`tests/conftest.py` 的
    `REPO_ROOT = Path(__file__).resolve().parents[1]` 是按文件位置推的，子进程在这棵树
    里跑时，守卫快照的就是那棵树自己——机制原样跑到，共享工作树零痕迹。
    拼最小目录树要么复刻 conftest（第二份事实源），要么缺 `neurova/` 与
    `pyproject.toml` 的 addopts 让探针测的不再是同一套装配。

    为什么不再走 `git worktree add`（`83dad089` 的写法，本笔改掉）：那条路把守卫
    绑在一份**可写的 git 元数据**上，而 CI 容器只给源码树，`git worktree add` 当场
    退 2（连续三个构建 `cnb-mei-1k4odroc5` / `cnb-o9g-1k4oij3vm` / `cnb-l6f-1k4bi087n`
    的 `unit-tests` 腿同形），四条用例于是全部变成 setup ERROR——**而真正的报错
    （git 的 stderr）被 `capture_output=True` 吃掉**，只看得到一个裸
    `CalledProcessError`。守卫要的是"一棵自己独占的仓库根"，不是"git 能不能建
    worktree"；换成复制装配面即把这条外部依赖根除，且实测更快（0.22s / 33.5MB，
    原 worktree 整树检出约 12s）。

    复制的是**当前工作树这一份**（不是 HEAD 那份）：守卫本体若在本地有未提交改动，
    探针就该测改后的版本，否则改坏了也照样绿。
    """
    staging = Path(tempfile.mkdtemp(prefix="neurovaProbeRoot-"))
    root = staging / "tree"
    root.mkdir()
    shutil.copy2(REPO_ROOT / "pyproject.toml", root / "pyproject.toml")
    for entry in ("pytest.ini", "conftest.py"):
        candidate = REPO_ROOT / entry
        if candidate.is_file():
            shutil.copy2(candidate, root / entry)
    for entry in ("tests", "neurova"):
        shutil.copytree(
            REPO_ROOT / entry, root / entry,
            symlinks=True,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
    # 探针要在 `tests/unit/` 落临时用例（`_runPytestProbe`），而复制面按忽略表
    # 剪掉的正是空的字节码目录——`tests/unit` 本身在源树里必然存在，这里只兜底。
    (root / "tests" / "unit").mkdir(parents=True, exist_ok=True)
    return staging, root


def _releaseProbeRoot(staging: Path, root: Path) -> None:
    """整棵临时树一次删净（没有 git 侧的注册项要摘，故无 `worktree remove`）。"""
    shutil.rmtree(staging, ignore_errors=True)


def _runPytestProbe(root: Path, fileName: str, body: str, expectGreen: bool) -> str:
    """在探针独占的仓库根里跑一条临时用例，返回其输出（树由 `probeRoot` 夹具统一弃）。

    判据全走**行为**而不是读 pytest 内部属性：pytest 9 把夹具对象换成了
    `FixtureFunctionDefinition`，钉 `_pytestfixturefunction.autouse` 这类写法
    下次升级即碎，而且"属性存在"本身也证明不了守卫咬得住。
    """
    probeFile = root / "tests" / "unit" / fileName
    probeFile.write_text(textwrap.dedent(body), encoding="utf-8")
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", f"tests/unit/{fileName}",
             "-p", "no:cacheprovider", "-q", "--tb=short"],
            cwd=str(root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            timeout=_PROBE_PYTEST_TIMEOUT_S,
        )
        out = proc.stdout + proc.stderr
        if expectGreen:
            assert proc.returncode == 0, f"探针应当全绿却红了：\n{out[-700:]}"
        else:
            assert proc.returncode != 0, f"探针本该失败却全绿（守卫没咬住）：\n{out[-700:]}"
        return out
    finally:
        probeFile.unlink(missing_ok=True)


@pytest.fixture(scope="module")
def probeRoot():
    """本模块共用一棵探针仓库根。

    每条探针都新建/删除一次 worktree 的实测成本约 12s（整树检出），四条就是 48s——
    树里没有跨探针状态需要隔离（每条探针写的是自己那份临时用例文件，`finally` 即删），
    所以按模块建一次即可。
    """
    staging, root = _acquireProbeRoot()
    try:
        yield root
    finally:
        _releaseProbeRoot(staging, root)


def test_guardIsARegisteredFixture(probeRoot):
    """夹具必须真注册（能按名请求到），否则守卫只是文件里的一段文字。"""
    out = _runPytestProbe(
        probeRoot,
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


def test_guardFiresPerTestAndNamesTheOffender(probeRoot, tmp_path):
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
            probeRoot,
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


def test_cleanTestDoesNotTripTheGuard(probeRoot):
    """反证另一半：不落根目录的用例必须照常绿——守卫不能靠误伤逼人摘掉它。"""
    _runPytestProbe(
        probeRoot,
        "test_cleanProbe.py",
        """
        def test_nothingWritten():
            assert True
        """,
        expectGreen=True,
    )


def test_probeWritesStayOutOfTheSharedWorkingTree(probeRoot):
    """探针的落点必须是它自己独占的仓库根，不是全机共享的那棵工作树。

    这条盯的是**并发会话**的故障形态：探针在共享 `tests/unit/` 里落一个临时用例、
    又在共享仓库根建一个顶层垃圾目录，二者都在本会话结束后被 `finally` 抹掉——
    本会话的守卫因此看不出错。但另一条正在同一工作树里跑测的会话，其逐用例守卫
    会把这两个痕迹记到**它自己那条无辜用例**的账上（实测 2026-10-09：
    宽域 A/B 里 `test_candidate_statistics_come_from_real_prune_history` 的 teardown
    报出 `zzPollutionProbeJunk`，肇事者压根不是它）。守卫本身是对的，
    错在探针拿共享树当自己的实验台。

    判据走**过程观测**而不是事后检查：`finally` 会删掉痕迹，跑完再看永远干净。
    """
    junkName = "zzConcurrentProbeJunk"
    probeFileName = "test_sharedTreeProbe.py"
    probePath = REPO_ROOT / "tests" / "unit" / probeFileName
    junkPath = REPO_ROOT / junkName
    appeared = {"junk": False, "probeFile": False}
    stop = threading.Event()

    def _watch():
        while not stop.is_set():
            if junkPath.exists():
                appeared["junk"] = True
            if probePath.exists():
                appeared["probeFile"] = True
            time.sleep(0.005)

    watcher = threading.Thread(target=_watch, daemon=True)
    watcher.start()
    try:
        _runPytestProbe(
            probeRoot,
            probeFileName,
            f"""
            from pathlib import Path

            def test_polluteForObservation():
                (Path(__file__).resolve().parents[2] / "{junkName}").mkdir()
                assert True
            """,
            expectGreen=False,
        )
    finally:
        stop.set()
        watcher.join(timeout=5)
        shutil.rmtree(junkPath, ignore_errors=True)

    assert not appeared["junk"], "探针在共享仓库根建了顶层目录——并发会话的守卫会把它记给无辜用例"
    assert not appeared["probeFile"], "探针把临时用例写进了共享 tests/unit——并发会话可能收集到它"
