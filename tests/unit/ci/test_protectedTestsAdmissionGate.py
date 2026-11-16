# -*- coding: utf-8 -*-
"""受保护子集**收录门**：红灯文件在转绿前不得进 protected_tests*.txt（教义第 3 条）。

## 为什么 CI 分片不算这道门

`test_protected_subset_shards.py` 钉住的是"清单的形"（存在、不重复、索引≡分片并集、
两侧同喂法）；CI 分片跑的是"清单的实"——但那已经是**合并之后**的事。缺的是收录当下
（提交进清单的那一笔）就能红的门：有人把当前还红的测试文件登记进清单，分片守卫照常绿
（它只对形状负责），红灯文件躺进 CI 清单反而把整条 unit-tests 腿拖红，事故定位还绕。

本门只校验**增量**：本次 diff 新增收录的条目逐文件单跑，红即拒。全量 4187 条不在此跑
（那正是分片存在的理由）；已收录条目的健康由 CI 分片与 nightly（`protected_subset_nightly.py`）
负责，不重复造第二份全量。

判据：
1. 新增收录文件单跑 pytest，非零退出（含收集失败、零收集）即拒，**点名文件与退出码**；
2. 注释行、空行、上下文行不算新增收录；
3. 无新增收录（没动清单）必须放行——门只拦"往清单里塞红灯"这一件事。
"""

from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
_CI_DIR = PROJECT_ROOT / "scripts" / "ci"
if str(_CI_DIR) not in sys.path:
    sys.path.insert(0, str(_CI_DIR))

admission = importlib.import_module("protected_tests_admission_check")


def _check(files: list, tmp_path: Path) -> tuple:
    return admission.checkFiles(files, python=sys.executable, timeout=180, cwd=tmp_path)


class TestAdmissionGate:
    def testGreenProbePasses(self, tmp_path):
        probe = tmp_path / "test_admission_green_probe.py"
        probe.write_text("def test_admission_probe_passes():\n    assert True\n", encoding="utf-8")
        ok, report = _check([str(probe)], tmp_path)
        assert ok, f"全绿的收录候选被拒——门误伤：{report}"

    def testRedProbeIsRejectedAndNamed(self, tmp_path):
        probe = tmp_path / "test_admission_red_probe.py"
        probe.write_text(
            "def test_admission_probe_fails():\n"
            "    assert False, 'admission probe red'\n", encoding="utf-8")
        ok, report = _check([str(probe)], tmp_path)
        assert not ok, "红灯候选被放行——收录门空转"
        joined = "\n".join(report)
        assert probe.name in joined, "拒绝时没点名红灯文件"
        assert "红灯" in joined or "教义第 3 条" in joined, "拒绝理由没有挂教义条款"

    def testCollectionErrorIsRejected(self, tmp_path):
        probe = tmp_path / "test_admission_broken_probe.py"
        probe.write_text("def broken(:\n", encoding="utf-8")
        ok, report = _check([str(probe)], tmp_path)
        assert not ok, "收集失败（语法错误）的候选被放行"
        assert probe.name in "\n".join(report)

    def testZeroCollectedIsRejected(self, tmp_path):
        probe = tmp_path / "test_admission_empty_probe.py"
        probe.write_text("VALUE = 1\n", encoding="utf-8")
        ok, report = _check([str(probe)], tmp_path)
        assert not ok, "零收集的候选被放行——收了等于没测"

    def testEmptyListPasses(self, tmp_path):
        ok, _report = _check([], tmp_path)
        assert ok, "空清单也要跑测＝门在没东西可拦时制造噪音"


class TestAdmissionParsing:
    def testParseAdmissionsTakesAddedNonCommentLinesOnly(self):
        diff = (
            "diff --git a/scripts/ci/protected_tests.txt b/scripts/ci/protected_tests.txt\n"
            "--- a/scripts/ci/protected_tests.txt\n"
            "+++ b/scripts/ci/protected_tests.txt\n"
            "@@ -1,3 +1,5 @@\n"
            " tests/unit/keep_me.py\n"
            "+tests/unit/ci/test_new_green.py\n"
            "+# 注释行不算收录\n"
            "+\n"
            " tests/unit/also_keep.py\n"
            "+tests/unit/ci/test_another_green.py\n"
        )
        assert admission.parseAdmissions(diff) == [
            "tests/unit/ci/test_new_green.py",
            "tests/unit/ci/test_another_green.py",
        ]

    def testUnchangedIndexMeansNoAdmissions(self):
        """真仓当前工作树：本次没动任何清单 → 待收录为空 → 门放行（不误伤）。"""
        diff = subprocess.run(
            ["git", "diff", "--cached", "-U0", "--",
             "scripts/ci/protected_tests.txt",
             "scripts/ci/protected_tests.1.txt",
             "scripts/ci/protected_tests.2.txt",
             "scripts/ci/protected_tests.3.txt"],
            cwd=str(PROJECT_ROOT), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=30).stdout
        assert admission.parseAdmissions(diff) == [], (
            "清单没动却判出新增收录——取数口把上下文/删除行当成了新增")
