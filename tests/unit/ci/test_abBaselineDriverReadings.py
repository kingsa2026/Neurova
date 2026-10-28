"""宽域 A/B 驱动（`scripts/ci/ab_baseline.py`）的读数契约判据。

这条档钉的是**缺件本身**（§6-356 登记的「`scripts/ab_compare.sh` 缺件」那条）：
Skill 的速查表一直把一个 A/B 脚本当既有件列着，而 `git ls-files scripts/` 现读没有它——
首批按该路径调用时命令尾接了 `tail`，退出码被读成 0，于是"A/B 跑过了"是假的（形态集 211/221）。

为什么落地形态不是 `.sh` 而是 `scripts/ci/ab_baseline.py`（三条实据）：
① 本仓另有一个**生产符号** `ab_compare`（`neurova/evolution/service.py` 的双臂试评，台账里
   十几处以 `ab_compare` 指它）——同一个词在一仓之内指两样东西，正是教义第 6 条的命名面；
② 常驻判据要能在 Windows 与 CI 两种宿主上用**本仓唯一跑测解释器**跑起来，不该赌 PATH 里有 bash；
③ 台账 §6-332 记过 MSYS 的 `TMPDIR`/`MSYS_NO_PATHCONV` 坑：bash 侧与原生 git 侧对同一个
   `/tmp/...` 解析成两个目录，基线树于是只剩铺进去的那格——那是脚本形态自带的宿主耦合，
   Python 侧不涉及路径转换，这一类坑从形制上消失。

判据形态全部走"喂进去什么读数、就该出什么标记"的行为断言：合成 git 仓 + 真 pytest 子进程，
外加 canned 日志文本喂取数口。每一格都要求**能红**（见末尾那格反向控制）。
"""
import json
import importlib.util
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "ci" / "ab_baseline.py"

#: 本档子进程预算的唯一出处（§6-402 批 K 同一口径：子墙一处定义，父墙由它 ＋余量导出）。
#: `git` 那几枚读的是索引/工作树，毫秒级；A/B 驱动那几枚真起**嵌套 pytest**（一次调用两趟，
#: 实测最重的一格 5.59s），60s 已是十倍余量——全局 30s 那道墙比子墙先到，报出来的就是
#: "整场跑测没了"而不是这条诚实的 TimeoutExpired。
_GIT_WALL_S = 30
_DRIVER_WALL_S = 60
pytestmark = pytest.mark.timeout(_DRIVER_WALL_S + 60)


def _loadDriver():
    spec = importlib.util.spec_from_file_location("abBaselineDriver", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


#: 两种真实存在的汇总行形态（`addopts` 含 `-v` 时被 `=` 包裹；无 `-v` 的仓是裸行）。
#: 锚 `^` 的写法在前者 0 命中——那正是"整轮扫描静默作废"的入口。
WRAPPED_LOG = textwrap.dedent("""\
    ========================= test session starts ==========================
    collected 17 items
    tests/unit/x/test_a.py::test_one FAILED                           [ 50%]
    tests/unit/x/test_b.py::test_two PASSED                          [100%]
    ======================= short test summary info ========================
    FAILED tests/unit/x/test_a.py::test_one - AssertionError: 1 == 2
    ERROR tests/unit/x/test_c.py::test_three - FileNotFoundError
    ======== 1 failed, 15 passed, 1 error, 2 warnings in 4.21s ========
    """)

BARE_LOG = textwrap.dedent("""\
    collected 4 items
    FAILED tests/t.py::test_a - assert False
    1 failed, 2 passed, 1 error in 0.31s
    """)


class TestTheScriptIsTheMissingPiece:
    """缺件这一格就是本批的红灯本体：脚本不在场，此前任何"A/B 已跑"的说法都没有落点。"""

    def test_scriptExistsAndIsTracked(self):
        assert SCRIPT.is_file(), f"A/B 驱动不在场：{SCRIPT}（缺件时任何「A/B 已跑」都无法复核）"
        tracked = subprocess.run(
            ["git", "ls-files", "--", "scripts/ci/ab_baseline.py"],
            cwd=str(REPO_ROOT), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=_GIT_WALL_S).stdout.strip()
        assert tracked, "脚本在磁盘上但没进跟踪：CI 与别人的工作树里它不存在"


class TestSummaryReaderKeepsBothShapes:
    def test_wrappedSummaryIsRead(self):
        assert _loadDriver().parseSummary(WRAPPED_LOG) == {
            "failed": 1, "passed": 15, "errors": 1}

    def test_bareSummaryIsRead(self):
        assert _loadDriver().parseSummary(BARE_LOG) == {
            "failed": 1, "passed": 2, "errors": 1}

    def test_noSummaryIsNotReadAsGreen(self):
        assert _loadDriver().parseSummary("Traceback...\nINTERNALERROR\n") is None

    def test_failureSetIsExtractedNotCounted(self):
        assert _loadDriver().extractFailures(WRAPPED_LOG) == {
            "tests/unit/x/test_a.py::test_one", "tests/unit/x/test_c.py::test_three"}

    def test_appLogErrorLineIsNotATestNode(self):
        """应用日志的 `ERROR logger:module.py:line` 不是 pytest 短汇总行。

        实测（§6-371）：cognitive 组预存红会在输出里打 `ERROR neurova.agent.chat_pipeline:...`，
        旧抽取口的 `\\S+` 把它当成一条测试节点——汇总 16 条红被抽成 18 条，对账闸判 AB_FAIL。
        """
        log = WRAPPED_LOG + "ERROR neurova.agent.chat_pipeline:chat_pipeline.py:304 - boom\n"
        assert _loadDriver().extractFailures(log) == {
            "tests/unit/x/test_a.py::test_one", "tests/unit/x/test_c.py::test_three"}

    def test_nulBytesDoNotBlindTheReader(self):
        #: 重定向落盘带 NUL 时，按"二进制文件"处理的外层取数会只回一句 Binary file matches，
        #: 于是抽取 0 条而汇总明明报着红——抽取口必须按文本读。
        assert _loadDriver().extractFailures(
            "\x00" + WRAPPED_LOG.replace("[ 50%]", "[\x0050%]")) == {
            "tests/unit/x/test_a.py::test_one", "tests/unit/x/test_c.py::test_three"}


class TestReconciliationGates:
    """两侧的"汇总报了几条"与"实际抽到几条"必须对账——差集判读的前提是取数口自己没坏。"""

    def test_summaryCountWithoutAnyExtractedLineIsFail(self):
        log = "======== 7 failed, 10 passed in 2.15s ========\n"
        verdict = _loadDriver().reconcile(log)
        assert verdict["ok"] is False
        assert "7" in verdict["reason"] and "0" in verdict["reason"]

    def test_extractedCountBelowSummaryIsFail(self):
        log = WRAPPED_LOG.replace(
            "======== 1 failed, 15 passed, 1 error",
            "======== 5 failed, 15 passed, 4 error")
        assert _loadDriver().reconcile(log)["ok"] is False

    def test_consistentLogPassesReconciliation(self):
        assert _loadDriver().reconcile(WRAPPED_LOG)["ok"] is True

    def test_missingNodeInBaselineIsFailNotNoDifference(self):
        #: 仅本树红那格若在基线树里找不到节点（多半是 `-c` 漏给），"两侧失败集一致"就是假结论
        outcome = _loadDriver().classify(
            baselineFailures=set(), treeFailures={"tests/t.py::test_new"},
            baselineCollectable=set(), reruns=[])
        assert outcome["marker"] == "AB_FAIL"
        assert "tests/t.py::test_new" in outcome["detail"]

    def test_identicalFailureSetsArePass(self):
        both = {"tests/t.py::test_old"}
        outcome = _loadDriver().classify(both, both, {"tests/t.py::test_old"}, reruns=[])
        assert outcome["marker"] == "AB_PASS"

    def test_onlyTreeRedThatIsGreenOnRerunIsRegression(self):
        outcome = _loadDriver().classify(
            baselineFailures=set(), treeFailures={"tests/t.py::test_a"},
            baselineCollectable={"tests/t.py::test_a"},
            reruns=[("tests/t.py::test_a", [True, False, False])])
        assert outcome["marker"] == "AB_REGRESSION"

    def test_onlyTreeRedRedEveryTimeIsPreexisting(self):
        outcome = _loadDriver().classify(
            baselineFailures=set(), treeFailures={"tests/t.py::test_a"},
            baselineCollectable={"tests/t.py::test_a"},
            reruns=[("tests/t.py::test_a", [True, True, True])])
        assert outcome["marker"] == "AB_PASS"
        assert "tests/t.py::test_a" in outcome["preexisting"]


@pytest.mark.timeout(300)
class TestEndToEndOnSyntheticRepos:
    """真 git worktree＋真 pytest 子进程跑通四种标记，才叫这脚本能用。"""

    @staticmethod
    def _gitEnvironment() -> dict:
        """合成仓的 git 子进程环境：把**继承来的**签名配置摘掉。

        判据问的是「驱动能不能在合成仓上跑出四种标记」，不是「宿主配没配好 git」。
        而开发容器常带 `commit.gpgsign=true` + 一个本宿主没有的 `gpg.program`
        （CNB 开发环境实测 `gpg.program=cnb-gpgsign`），于是 `git commit` 直接
        `error: gpg failed to sign the data` / 退 128 —— 红在前置上，读的人会去查驱动。
        显式传 `-c commit.gpgsign=false` 把这个外部依赖根除，不改宿主配置。
        """
        return {**os.environ, "GIT_CONFIG_COUNT": "1",
                "GIT_CONFIG_KEY_0": "commit.gpgsign",
                "GIT_CONFIG_VALUE_0": "false"}

    @staticmethod
    def _makeRepo(tmp_path: Path, *, body="return 1", expected=1):
        if shutil.which("git") is None:
            pytest.skip("本宿主没有 git，合成仓起不来（不是通过，是没跑）")
        repo = tmp_path / "subject"
        repo.mkdir()
        # 两道准入闸的文件形状（驱动按它们判 AB_SKIP）
        (repo / "pyproject.toml").write_text("[pytest]\n", encoding="utf-8")
        ci = repo / "scripts" / "ci"
        ci.mkdir(parents=True)
        (ci / "protected_tests.txt").write_text("tests/test_contract.py\n", encoding="utf-8")
        (repo / "app").mkdir()
        (repo / "app" / "__init__.py").write_text("", encoding="utf-8")
        (repo / "app" / "logic.py").write_text(
            f"def answer():\n    {body}\n", encoding="utf-8")
        tests = repo / "tests"
        tests.mkdir()
        (tests / "test_contract.py").write_text(
            "from app.logic import answer\n\n"
            "def test_answer():\n"
            f"    assert answer() == {expected}\n", encoding="utf-8")
        # 宿主签名配置的隔离由 `_gitEnvironment()` 一处给（`GIT_CONFIG_*` 传下去）；
        # 命令里不再写第二份 `-c commit.gpgsign=false`：两处各写一遍时，改一处另一处静默失效
        # （宿主 `commit.gpgsign=true` 而签名程序不可用时，合成仓的 commit 会以 128 炸掉）。
        for args in (["init", "-q"], ["add", "."],
                     ["-c", "user.email=t@t", "-c", "user.name=t",
                      "commit", "-q", "-m", "base"]):
            subprocess.run(["git"] + args, cwd=str(repo), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", check=True,
                           env=TestEndToEndOnSyntheticRepos._gitEnvironment(),
                           timeout=_GIT_WALL_S)
        return repo

    def _run(self, repo: Path, tmp_path: Path, extra=()):
        #: 子端也要钉（`test_subprocessTextEncodingRatchet` 那道闸问的是两头，只钉父端算半修）
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "-k", "HEAD", "-n", "2",
             "--root", str(repo), "--tmp", str(tmp_path / "abtmp"), *extra,
             "--", "tests"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            env={**self._gitEnvironment(), "PYTHONIOENCODING": "utf-8"},
            timeout=_DRIVER_WALL_S)
        return proc

    def test_noDifferenceYieldsPass(self, tmp_path):
        repo = self._makeRepo(tmp_path)
        proc = self._run(repo, tmp_path)
        assert "AB_PASS" in proc.stdout, proc.stdout + proc.stderr
        assert proc.returncode == 0

    def test_treeOnlyRedThatIsGreenInBaselineYieldsRegression(self, tmp_path):
        #: 本树把生产改坏（return 2）而判据仍断 ==1，并把这份判据铺进基线 ⇒ 仅本树红且基线复跑全绿
        repo = self._makeRepo(tmp_path)
        (repo / "tests" / "test_extra.py").write_text(
            "from app.logic import answer\n\n\ndef test_extra():\n"
            "    assert answer() == 1\n", encoding="utf-8")
        (repo / "app" / "logic.py").write_text(
            "def answer():\n    return 2\n", encoding="utf-8")
        proc = self._run(repo, tmp_path, extra=("-c", "tests/test_extra.py"))
        assert "AB_REGRESSION" in proc.stdout, proc.stdout + proc.stderr
        assert proc.returncode != 0

    def test_missingCriteriaCopyYieldsFail(self, tmp_path):
        #: 同上一格，但 `-c` 没给 ⇒ 那条红在基线树里根本没有节点，"两侧一致"是假的
        repo = self._makeRepo(tmp_path)
        (repo / "tests" / "test_extra.py").write_text(
            "from app.logic import answer\n\n\ndef test_extra():\n"
            "    assert answer() == 1\n", encoding="utf-8")
        (repo / "app" / "logic.py").write_text(
            "def answer():\n    return 2\n", encoding="utf-8")
        proc = self._run(repo, tmp_path)
        assert "AB_FAIL" in proc.stdout, proc.stdout + proc.stderr

    def testRepoShapeGateSkipsLoudly(self, tmp_path):
        #: 非本仓形态（没有受保护子集清单）要显式说"没跑"，不许回一句全绿
        repo = tmp_path / "bare"
        repo.mkdir()
        (repo / "tests").mkdir()
        (repo / "tests" / "test_ok.py").write_text("def test_ok():\n    assert True\n",
                                                  encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "-k", "HEAD", "--root", str(repo),
             "--tmp", str(tmp_path / "abtmp"), "--", "tests"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"}, timeout=_DRIVER_WALL_S)
        assert "AB_SKIP" in proc.stdout, proc.stdout + proc.stderr

    def testCp936StdoutDoesNotEatTheVerdict(self, tmp_path):
        #: 宿主默认 stdout 是 cp936 时，读数里那个箭头会把驱动自己打死（退出码 1、stdout 空）——
        #: 红会指向脚本而不是被测行为。修在产生侧：脚本自己把 stdout 钉成 utf-8。
        repo = self._makeRepo(tmp_path)
        env = {**self._gitEnvironment(), "PYTHONIOENCODING": "gbk"}
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "-k", "HEAD", "-n", "1",
             "--root", str(repo), "--tmp", str(tmp_path / "abtmp"), "--", "tests"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", env=env,
            timeout=_DRIVER_WALL_S)
        assert "AB_PASS" in proc.stdout, proc.stdout + proc.stderr
        assert proc.returncode == 0


class TestDriverIsNotVacuous:
    """反向控制：取数口坏掉时这几格必须红——不然整套契约可以空转通过。"""

    def test_anchorOnlyReaderWouldMissTheWrappedLine(self):
        #: `^[0-9]+ (failed|passed)` 那种锚法在本仓（`addopts` 含 `-v`）0 命中，
        #: 所以取数口必须全行匹配——这格钉的就是它不许退化成锚法。
        reading = _loadDriver().parseSummary(WRAPPED_LOG)
        assert reading is not None and reading["failed"] == 1

    def test_verdictPayloadIsJsonAndSelfDescribing(self, tmp_path):
        #: 取数口坏掉时上面那些格会红，但「标记打对了却没给人复核用的读数」是另一种空转——
        #: 驱动必须能吐一份机器可用的两侧计数。
        if not shutil.which("git"):
            pytest.skip("本宿主没有 git")
        repo = TestEndToEndOnSyntheticRepos._makeRepo(tmp_path)
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "-k", "HEAD", "-n", "1", "--json",
             "--root", str(repo), "--tmp", str(tmp_path / "abtmp"), "--", "tests"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            env={**TestEndToEndOnSyntheticRepos._gitEnvironment(), "PYTHONIOENCODING": "utf-8"},
            timeout=_DRIVER_WALL_S)
        payload = [json.loads(ln) for ln in proc.stdout.splitlines() if ln.startswith("{")]
        assert payload, "带 `--json` 却没给出机器可读读数"
        assert {"marker", "baseline", "tree"} <= set(payload[0])
