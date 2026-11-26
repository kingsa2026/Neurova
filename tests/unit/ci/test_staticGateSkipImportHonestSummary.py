# -*- coding: utf-8 -*-
"""`--skip-import` 的汇总口径必须诚实（审计 TEST-03）。

旧行为：跳过导入巡检时 `results["imports"] = True`，汇总行照打「✅ 模块导入巡检：通过」、
末句照打「静态门禁全部通过」——**没执行的检查被记成通过的检查**。这正是"失败改写成
通过"的形态（教义第 2 条）：读数上看不出这一格是根本没跑还是跑绿了。

判据钉住三件事：
1. 跳过时汇总行必须写「已跳过」并点明「未执行」，不得出现「通过」；
2. 末句不得宣称「全部通过」——全量与跳过是两种口径；
3. 反向：正常跑完（导入巡检真的执行且通过）时，「通过」与「全部通过」必须原样回来，
   免得"收紧"变成把绿读数也删掉。

两条检查函数在边界处打桩（`check_syntax`/`check_pyflakes`/`check_imports` 是纯探测口，
不装配任何业务对象），本档只验汇总口径本身。
"""
from __future__ import annotations

import pytest

import scripts.ci_static_gate as gate


@pytest.fixture()
def probesPass(monkeypatch):
    """三格探测口全部给"通过"的读数——本档只检查汇总行怎么记账。"""
    monkeypatch.setattr(gate, "check_syntax", lambda: True)
    monkeypatch.setattr(gate, "check_pyflakes", lambda: True)
    monkeypatch.setattr(gate, "check_imports", lambda: (True, 42, 0, []))


def _run(monkeypatch, capsys, argv: list[str]) -> tuple[int, str]:
    monkeypatch.setattr(gate.sys, "argv", ["ci_static_gate.py", *argv])
    code = gate.main()
    return code, capsys.readouterr().out


class TestSkipImportIsReportedAsSkipped:
    def testSkippedImportCheckIsNotClaimedAsPassed(self, monkeypatch, capsys, probesPass):
        code, out = _run(monkeypatch, capsys, ["--skip-import"])
        importLines = [line for line in out.splitlines() if "模块导入巡检" in line]
        assert importLines, out
        assert any("已跳过" in line and "未执行" in line for line in importLines), out
        assert not any("模块导入巡检：通过" in line for line in importLines), out

    def testFinalLineDoesNotClaimEverythingPassedWhenSkipped(self, monkeypatch, capsys, probesPass):
        code, out = _run(monkeypatch, capsys, ["--skip-import"])
        assert code == 0, out
        assert "静态门禁全部通过" not in out, out
        assert "跳过" in out.splitlines()[-1], out


class TestExecutedChecksStillReadAsPassed:
    def testAllThreeExecutedKeepsPassWording(self, monkeypatch, capsys, probesPass):
        code, out = _run(monkeypatch, capsys, [])
        assert code == 0, out
        assert "✅ 模块导入巡检：通过" in out, out
        assert "静态门禁全部通过" in out, out
        assert "跳过" not in out, out