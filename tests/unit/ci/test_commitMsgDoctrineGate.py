# -*- coding: utf-8 -*-
"""commit-msg 提交门：修复教义第 2/3 条的**提交期**落点（先红后绿的顺序性与 LOC 去向）。

## 为什么钉在提交期而不是只靠事后审计

教义第 3 条要求"提交说明必须附红→绿的实测输出"，第 2 条要求"净新增 LOC 为正必须逐条列明
去向"。既有守卫 `test_commitLocClaimMatchesOwnNumstat.py` 只覆盖**已提交笔**（origin/main..HEAD
的推送窗口）的数字复算；本门补的是**提交准入**：正文连红绿证据或去向段都没有的 feat/fix，
在 `git commit` 当场就被拒，不进历史。

## 判据（都可证伪）

1. `feat:`/`fix:` 正文必须含「红灯」与「绿灯」证据，且**红灯先于绿灯**（先红后绿的顺序性）。
2. 生产池净增 LOC > 0 时，正文必须含池口径的 `+N/−M` 声明**且**写明「去向」——数字与
   numstat 的逐池相等由 `test_commitLocClaimMatchesOwnNumstat.py` 在推送窗口复算，本门
   只挡"没写"（分工：钩子管准入，既有守卫管对账，不重复造第二份复算）。
3. 豁免面：`Merge `/`Revert ` 开头全豁免；docs/chore/test/style/refactor/perf/ci/build
   豁免红绿（它们不新增生产行为），**不豁免** LOC 去向（教义第 2 条不分类型）。
4. 反空转：全合规样例必须放行——判据只红"缺证据"，不红"守规矩"。

词汇唯一出处：池名与 `+N/−M` 形态沿用 numstat 复算守卫的既有口径，本档不另写一份。
"""

from __future__ import annotations

import importlib
import os
import stat
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
_HOOK_DIR = PROJECT_ROOT / "scripts" / "githooks"
if str(_HOOK_DIR) not in sys.path:
    sys.path.insert(0, str(_HOOK_DIR))

commit_msg_check = importlib.import_module("commit_msg_check")


def _check(message: str, productionNet: int = 0) -> list:
    return commit_msg_check.check(message, productionNet=productionNet)


class TestRedGreenEvidenceGate:
    """红绿证据判据：缺一即拒，顺序反了即拒，全合规必须放行。"""

    def testFeatWithoutRedLightIsRejected(self):
        violations = _check(
            "fix(core): 修一处断链\n\n"
            "绿灯：tests/unit/ci/test_x.py 1 passed\n")
        assert any("红灯" in v for v in violations), (
            "feat/fix 缺红灯证据竟被放行——教义第 3 条的提交门空转")

    def testFeatWithoutGreenLightIsRejected(self):
        violations = _check(
            "fix(core): 修一处断链\n\n"
            "红灯：tests/unit/ci/test_x.py::test_y 先红（AssertionError: …）\n")
        assert any("绿灯" in v for v in violations), (
            "只有红灯没有绿灯＝只有失败没有修复证据，不得放行")

    def testGreenBeforeRedViolatesFirstRedThenGreen(self):
        violations = _check(
            "feat(core): 新功能\n\n"
            "绿灯：1 passed\n"
            "红灯：先跑的失败输出\n")
        assert any("先红后绿" in v for v in violations), (
            "绿灯写在红灯前面＝顺序性没有被钉住（先红后绿，不是先绿后红）")

    def testEvidenceKeywordMentionInMotivationDoesNotDecideOrder(self):
        """真实误伤（本批提交门首日实测）：动机段引述「补个绿灯测试充数」，
        「绿灯」二字的**首次出现**落到证据段之前，首现判序把合规提交拒了。
        顺序判据只认「红灯：」「绿灯：」证据段引导词，正文其他位置的"红灯/绿灯"
        字样（引述、比喻）不参与定位——否则教义自己的正文都过不了这道门。"""
        assert _check(
            "fix(x): 标题\n\n"
            "动机：不许\"写完实现补个绿灯测试充数\"。\n\n"
            "红灯：tests/unit/ci/test_x.py 实测红（AssertionError: …）\n"
            "绿灯：最小实现后 1 passed\n") == [], (
            "引述里的「绿灯」被当成证据段定位——顺序判据误伤合规提交")

    def testEmptyBodyFeatIsRejected(self):
        violations = _check("fix(core): 只有一行标题\n")
        assert violations, "空正文 feat 竟被放行"

    def testFullyCompliantMessagePasses(self):
        assert _check(
            "fix(core): 修一处断链\n\n"
            "红灯：tests/unit/ci/test_x.py::test_y 实测红（AssertionError: expects 1 got 2）\n"
            "绿灯：最小实现后同格转绿（1 passed）\n"
            "净 LOC：生产池 +4/−6，去向：收口重复取数口，删除平行实现\n",
            productionNet=-2) == [], "全合规样例被拒＝判据误伤守规矩的提交"

    def testNegativeNetNeedsNoLocSection(self):
        assert _check(
            "fix(core): 修一处断链\n\n"
            "红灯：实测红\n绿灯：转绿（1 passed）\n",
            productionNet=-5) == [], "净增≤0 本就满足第 2 条默认值，不该再要去向段"


class TestProductionNetLocGate:
    """生产池净增 > 0 必须列去向；测试/基建不计入生产池。"""

    def testPositiveNetWithoutDestinationIsRejected(self):
        violations = _check(
            "feat(core): 新功能\n\n"
            "红灯：先红\n绿灯：后绿\n",
            productionNet=12)
        assert any("去向" in v for v in violations), (
            "净增 12 行却不写去向竟被放行——教义第 2 条的提交门空转")

    def testPositiveNetWithDestinationPasses(self):
        assert _check(
            "feat(core): 新功能\n\n"
            "红灯：先红\n绿灯：后绿\n"
            "生产池 +12/−0（去向：新增 scripts/githooks/ 两道守卫）\n",
            productionNet=12) == []

    def testDocsTypeStillNeedsLocClaimWhenNetPositive(self):
        violations = _check("docs: 补一篇指南\n", productionNet=30)
        assert any("去向" in v for v in violations), (
            "docs 不豁免 LOC 去向——教义第 2 条不分提交类型")

    def testMergeAndRevertAreExempt(self):
        assert _check("Merge branch 'feature/x'\n", productionNet=99) == []
        assert _check('Revert "feat(core): x"\n\nThis reverts commit abc.\n',
                      productionNet=99) == []


class TestProductionPoolCalc:
    """numstat 行 → 生产池净增：tests/、test_*.py、*_test.py、__tests__、scripts/ci 不计入。"""

    def testTestAndCiPathsAreExcludedFromProduction(self):
        rows = [
            "10\t2\tneurova/api/endpoints/chat.py",
            "5\t1\ttests/unit/api/test_chat.py",
            "3\t0\tscripts/ci/some_gate.py",
            "2\t1\tNeurUI/src/utils/chat.test.ts",
            "1\t0\tNeurUI/src/components/ChatPanel.vue",
            "-\t-\tmedia/logo.png",
        ]
        # 生产池 = +10-2 +1-0 = 9；tests/scripts-ci/test.ts 不计；二进制行跳过
        assert commit_msg_check.productionNetFromNumstat(rows) == 9

    def testBinaryAndMalformedRowsDoNotCrash(self):
        assert commit_msg_check.productionNetFromNumstat(["-\t-\tx.png", "garbage"]) == 0


class TestHookWiring:
    """钩子落点：壳脚本存在且只做粘合；安装器可幂等安装到指定 hooks 目录。"""

    def testCommitMsgShellDelegatesToCheckScript(self):
        shell = (_HOOK_DIR / "commit-msg").read_text(encoding="utf-8")
        assert "commit_msg_check.py" in shell, "commit-msg 壳没有指向判据唯一出处"
        assert "rev-parse --show-toplevel" in shell, "壳须按仓根定位判据脚本"

    def testPreCommitShellDelegatesToAdmissionCheck(self):
        shell = (_HOOK_DIR / "pre-commit").read_text(encoding="utf-8")
        assert "protected_tests_admission_check.py" in shell, (
            "pre-commit 壳没有指向受保护子集收录门")

    def testInstallPutsBothHooksIntoTargetDirIdempotently(self, tmp_path):
        hooks = tmp_path / "hooks"
        hooks.mkdir()
        installer = importlib.import_module("install")
        installer.install(hooksDir=hooks)
        for name in ("commit-msg", "pre-commit"):
            target = hooks / name
            assert target.is_file(), f"{name} 未被安装"
            firstLine = target.read_text(encoding="utf-8").splitlines()[0]
            assert firstLine.startswith("#!/bin/sh"), f"{name} 缺 shebang（git 不会当 shell 钩子跑）"
            if os.name == "posix":
                assert target.stat().st_mode & stat.S_IXUSR, f"{name} 缺可执行位（git 不会执行它）"
        # 幂等：装第二遍不炸、内容不变
        before = (hooks / "commit-msg").read_text(encoding="utf-8")
        installer.install(hooksDir=hooks)
        assert (hooks / "commit-msg").read_text(encoding="utf-8") == before

    def testInstallDoesNotTouchForeignHooks(self, tmp_path):
        """已有的非本工具钩子（如 git-lfs 的 pre-push）必须原样保留。"""
        hooks = tmp_path / "hooks"
        hooks.mkdir()
        (hooks / "pre-push").write_text("#!/bin/sh\ngit lfs pre-push \"$@\"\n", encoding="utf-8")
        installer = importlib.import_module("install")
        installer.install(hooksDir=hooks)
        assert (hooks / "pre-push").read_text(encoding="utf-8") == (
            "#!/bin/sh\ngit lfs pre-push \"$@\"\n"), "install 动了别人的钩子"
