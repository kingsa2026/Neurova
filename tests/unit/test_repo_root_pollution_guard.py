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


def _topLevelEntries() -> set:
    return set(os.listdir(REPO_ROOT))


def _lfsNeutralGit(argv: list, *, cwd: Path) -> subprocess.CompletedProcess:
    """跑一次**不依赖 Git LFS** 的 git 子命令，返回成品。

    为什么要这一层：CI 的 `python:3.12` 镜像里没有 `git-lfs`，而本仓是 LFS 仓库——
    `.git/hooks/post-checkout` 里那句 `command -v git-lfs || exit 2`（返回码 2）
    与 LFS 过滤器（`filter.lfs.process` 找不到 `git-lfs`，返回码 128）都会让
    `git worktree add` 整个失败，探针仓库根建不起来，四格判据全成 ERROR。
    实测本机复现两条症状（隐藏 `/usr/bin/git-lfs`）：

        $ git worktree add --detach <tmp> HEAD
        stderr: git-lfs filter-process: 1: git-lfs: not found
                fatal: the remote end hung up unexpectedly        # 返回码 128
        或 stderr: ... 'git-lfs' was not found on your path ...   # 返回码 2

    探针只借这棵树拿 `tests/conftest.py` 与 `neurova/`，**一个 LFS 大文件都不读**。
    故根修是让这次 checkout 不走 LFS：`core.hooksPath` 指向一个空的临时目录（跳过
    `post-checkout`），`filter.lfs.required=false` 且把四个 LFS 过滤器置空（跳过
    smudge——否则 `embedding/**/*.safetensors` 这类指针文件仍会触发 filter-process）。
    判据一个字没放宽：探针树里该有的文件一个不少（`neurova/` 78 个顶层条目、`tests/`
    与 `pyproject.toml` 齐备），只是 `*.safetensors` 保持指针形态——探针从不读它。
    """
    hooksDir = tempfile.mkdtemp(prefix="neurovaProbeHooks-")
    args = [
        "git",
        "-c", f"core.hooksPath={hooksDir}",
        "-c", "filter.lfs.required=false",
        "-c", "filter.lfs.process=",
        "-c", "filter.lfs.smudge=",
        "-c", "filter.lfs.clean=",
        *argv,
    ]
    try:
        return subprocess.run(
            args, cwd=str(cwd), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=180,
        )
    finally:
        shutil.rmtree(hooksDir, ignore_errors=True)


def _acquireProbeRoot() -> tuple[Path, Path]:
    """给探针一棵**自己独占**的仓库根：仓外 detached git worktree。

    为什么必须是整棵树而不是临时目录里摆几个文件：`tests/conftest.py` 的
    `REPO_ROOT = Path(__file__).resolve().parents[1]` 是按文件位置推的，子进程在
    worktree 里跑时，守卫快照的就是那棵树自己——机制原样跑到，共享工作树零痕迹。
    拼最小目录树要么复刻 conftest（第二份事实源），要么缺 `neurova/` 与
    `pyproject.toml` 的 addopts 让探针测的不再是同一套装配。
    """
    staging = Path(tempfile.mkdtemp(prefix="neurovaProbeRoot-"))
    root = staging / "tree"
    # `check=True` 的 `CalledProcessError.__str__` 只给 "returned non-zero exit
    # status N"，`capture_output` 收下的 stderr 一句都不带——实测 CI 上四格 ERROR
    # 就只有这一行，看不出是 git 缺席、HEAD 不可解析、还是 `worktree` 目录被占用
    # （`cnb-o5u-1k4od02gs` 的 pipeline-3）。这里改为自己收返回码并把 stderr 原文
    # 接进失败消息：诚实暴露，而不是让下一轮读者去猜（修复教义第 2 条）。
    # git 调用统一走 `_lfsNeutralGit`：CI 镜像没有 git-lfs，裸调用会被 LFS 钩子
    # 与过滤器拦死（详见该函数 docstring），而不是真实反映"这棵树建不起来"。
    proc = _lfsNeutralGit(
        ["worktree", "add", "--detach", str(root), "HEAD"], cwd=REPO_ROOT,
    )
    if proc.returncode != 0:
        shutil.rmtree(staging, ignore_errors=True)
        raise AssertionError(
            "探针仓库根建不起来：`git worktree add --detach <tmp>/tree HEAD` "
            f"在 {REPO_ROOT} 以返回码 {proc.returncode} 收场。\n"
            f"  stdout: {proc.stdout.strip()[:500]!r}\n"
            f"  stderr: {proc.stderr.strip()[:500]!r}\n"
            "常见成因：镜像里没有 git / 只有浅克隆而 HEAD 不可解析 / "
            "同一 git 目录被并发会话同时加挂。本守卫依赖 git 才能建独占仓库根，"
            "缺席时它是**测不了**而不是**通过**。（Git LFS 缺席不在此列——"
            "`_lfsNeutralGit` 已把 LFS 钩子与过滤器摘掉，不再构成成因。）"
        )
    # worktree 取的是 HEAD 那份 conftest；守卫本体若在工作树里有未提交改动，
    # 探针就该测**工作树这一份**，否则改坏了也照样绿。
    shutil.copy2(REPO_ROOT / "tests" / "conftest.py", root / "tests" / "conftest.py")
    return staging, root


def _releaseProbeRoot(staging: Path, root: Path) -> None:
    _lfsNeutralGit(["worktree", "remove", "--force", str(root)], cwd=REPO_ROOT)
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
