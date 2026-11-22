# -*- coding: utf-8 -*-
"""U19 卡：shell 分段治理静态扫描器（scripts/check_shell_segments.py）契约。

- 检出能力：subprocess.run/Popen/call/check_output(shell=True)、os.system、
  paramiko ``exec_command``、asyncio.create_subprocess_shell，且命令串含
  拼接/格式化（f-string / + / .format / %）→ 必须标红（warning 档）；
- 豁免：plain 变量透传（无拼接）、shell=False、注释/字符串里的字样、
  tests/ 与 scripts/ 目录、ALLOW 登记文件、文件 import 了
  command_segments/governance 且在调用邻近（同一函数内）实际使用；
- 档位：默认 warning 恒退出 0；--strict 违规退出 1（误报清零后升档用）；
- 真实仓实跑：可执行、产出结构化结果。
"""
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

from scripts.check_shell_segments import (
    ALLOW_REGISTRY,
    SCAN_ROOT,
    VERIFIED_FALSE_POSITIVE_RATE,
    collectReport,
    findConcat,
    main,
    scanTree,
)

_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "check_shell_segments.py"

#: 一个标准的"拼接命令 + shell 执行"违规样例（多种形态共用）
_VIOLATOR = (
    "import subprocess\n"
    "\n\n"
    "def go(name):\n"
    "    return subprocess.run(f'ls {name}', shell=True)\n"
)


def _write(tmp_path: Path, rel: str, content: str) -> Path:
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


class TestDetection:
    """四类 shell 执行点 × 四类拼接形态：命中即标红。"""

    def _one(self, tmp_path: Path, body: str) -> list[dict]:
        _write(tmp_path, "sample.py", body)
        return scanTree(tmp_path, registry={})

    def test_fstringShellRun_flagged(self, tmp_path):
        hits = self._one(tmp_path, _VIOLATOR)
        assert len(hits) == 1
        assert hits[0]["file"].endswith("sample.py")
        assert hits[0]["line"] == 5
        assert "subprocess.run" in hits[0]["kind"]

    def test_plusConcat_flagged(self, tmp_path):
        hits = self._one(tmp_path, (
            "import subprocess\n\n\ndef go(name):\n"
            "    return subprocess.run('ls ' + name, shell=True)\n"
        ))
        assert len(hits) == 1

    def test_percentFormat_flagged(self, tmp_path):
        hits = self._one(tmp_path, (
            "import subprocess\n\n\ndef go(name):\n"
            "    return subprocess.run('ls %s' % name, shell=True)\n"
        ))
        assert len(hits) == 1

    def test_strCall_format_flagged(self, tmp_path):
        hits = self._one(tmp_path, (
            "import subprocess\n\n\ndef go(name):\n"
            "    return subprocess.run('ls {}'.format(name), shell=True)\n"
        ))
        assert len(hits) == 1

    def test_popenCall_flagged(self, tmp_path):
        hits = self._one(tmp_path, (
            "import subprocess\n\n\ndef go(name):\n"
            "    return subprocess.Popen(f'cat {name}', shell=True)\n"
        ))
        assert len(hits) == 1 and "Popen" in hits[0]["kind"]

    def test_fromSubprocessImport_flagged(self, tmp_path):
        hits = self._one(tmp_path, (
            "from subprocess import run\n\n\ndef go(name):\n"
            "    return run(f'ls {name}', shell=True)\n"
        ))
        assert len(hits) == 1

    def test_osSystem_flagged(self, tmp_path):
        hits = self._one(tmp_path, (
            "import os\n\n\ndef go(name):\n"
            "    return os.system('ls ' + name)\n"
        ))
        assert len(hits) == 1 and hits[0]["kind"] == "os.system"

    def test_paramikoExecCommand_flagged(self, tmp_path):
        hits = self._one(tmp_path, (
            "def go(client, name):\n"
            "    return client.exec_command('cat ' + name)\n"
        ))
        assert len(hits) == 1 and hits[0]["kind"] == "paramiko.exec_command"

    def test_createSubprocessShell_flagged(self, tmp_path):
        hits = self._one(tmp_path, (
            "import asyncio\n\n\nasync def go(name):\n"
            "    return await asyncio.create_subprocess_shell(f'echo {name}')\n"
        ))
        assert len(hits) == 1 and "create_subprocess_shell" in hits[0]["kind"]


class TestNotFlagged:
    """无拼接 / 非 shell / 注释字样：不得误报。"""

    def _one(self, tmp_path: Path, body: str) -> list[dict]:
        _write(tmp_path, "sample.py", body)
        return scanTree(tmp_path, registry={})

    def test_plainVariable_notFlagged(self, tmp_path):
        hits = self._one(tmp_path, (
            "import subprocess\n\n\ndef go(cmd):\n"
            "    return subprocess.run(cmd, shell=True)\n"
        ))
        assert hits == []

    def test_shellFalse_notFlagged(self, tmp_path):
        hits = self._one(tmp_path, (
            "import subprocess\n\n\ndef go(name):\n"
            "    return subprocess.Popen(['ls', name], shell=False)\n"
        ))
        assert hits == []

    def test_shellKwargMissing_notFlagged(self, tmp_path):
        hits = self._one(tmp_path, (
            "import subprocess\n\n\ndef go(name):\n"
            "    return subprocess.run(['ls', f'{name}'])\n"
        ))
        assert hits == []

    def test_commentAndStringMentions_notFlagged(self, tmp_path):
        hits = self._one(tmp_path, (
            "import subprocess\n"
            "# os.system('rm -rf /') 只是注释\n"
            "DOC = \"文档里提到 os.system('x')\"\n\n\n"
            "def go(cmd):\n"
            "    return subprocess.run(cmd, shell=True)\n"
        ))
        assert hits == []

    def test_nonShellSubprocess_notFlagged(self, tmp_path):
        hits = self._one(tmp_path, (
            "import subprocess\n\n\ndef go(cmd):\n"
            "    return subprocess.check_output(['git', 'status'])\n"
        ))
        assert hits == []


class TestGovernanceTraceability:
    """import 了 command_segments/governance 且调用邻近使用 → 豁免；只 import 不用 → 仍标红。"""

    def _one(self, tmp_path: Path, body: str) -> list[dict]:
        _write(tmp_path, "sample.py", body)
        return scanTree(tmp_path, registry={})

    def test_governanceImportUsedNearCall_notFlagged(self, tmp_path):
        hits = self._one(tmp_path, (
            "import subprocess\n"
            "from neurova.security.command_segments import parse_command_segments\n\n\n"
            "def go(name):\n"
            "    segs = parse_command_segments(f'ls {name}')\n"
            "    return subprocess.run(f'ls {name}', shell=True), segs\n"
        ))
        assert hits == []

    def test_localGovernanceImportUsedNearCall_notFlagged(self, tmp_path):
        hits = self._one(tmp_path, (
            "import subprocess\n\n\ndef go(name):\n"
            "    from neurova.security.governance import get_governance\n"
            "    gov = get_governance()\n"
            "    return subprocess.run(f'ls {name}', shell=True), gov\n"
        ))
        assert hits == []

    def test_governanceImportWithoutNearUse_stillFlagged(self, tmp_path):
        hits = self._one(tmp_path, (
            "import subprocess\n"
            "from neurova.security.governance import match_whitelist  # 只挂名未使用\n\n\n"
            "def go(name):\n"
            "    return subprocess.run(f'ls {name}', shell=True)\n"
        ))
        assert len(hits) == 1

    def test_governanceUseInOtherFunction_stillFlagged(self, tmp_path):
        hits = self._one(tmp_path, (
            "import subprocess\n"
            "from neurova.security.command_segments import parse_command_segments\n\n\n"
            "def other(cmd):\n"
            "    return parse_command_segments(cmd)\n\n\n"
            "def go(name):\n"
            "    return subprocess.run(f'ls {name}', shell=True)\n"
        ))
        assert len(hits) == 1


class TestExemptions:
    def test_allowRegistryEntry_suppresses(self, tmp_path):
        p = _write(tmp_path, "svc.py", _VIOLATOR)
        registry = {str(p): "等效治理：调用前已分段审批"}
        assert scanTree(tmp_path, registry=registry) == []

    def test_testsAndScriptsDirs_notScanned(self, tmp_path):
        _write(tmp_path, "app.py", _VIOLATOR)
        _write(tmp_path, "tests/t.py", _VIOLATOR)
        _write(tmp_path, "scripts/s.py", _VIOLATOR)
        hits = scanTree(tmp_path, registry={})
        assert [v["file"] for v in hits] == [str(tmp_path / "app.py")]

    def test_syntaxErrorFile_skipped(self, tmp_path):
        _write(tmp_path, "broken.py", "def go(:\n")
        _write(tmp_path, "ok.py", _VIOLATOR)
        hits = scanTree(tmp_path, registry={})
        assert len(hits) == 1 and hits[0]["file"].endswith("ok.py")


class TestCliModes:
    def test_warningMode_exitZeroDespiteViolations(self, tmp_path, capsys):
        _write(tmp_path, "svc.py", _VIOLATOR)
        assert main([], root=tmp_path) == 0
        out = capsys.readouterr().out
        assert "warning" in out and "svc.py" in out

    def test_strictMode_exitOneOnViolations(self, tmp_path):
        _write(tmp_path, "svc.py", _VIOLATOR)
        assert main(["--strict"], root=tmp_path) == 1

    def test_strictMode_exitZeroWhenClean(self, tmp_path):
        _write(tmp_path, "clean.py", "import subprocess\n\n\ndef go(cmd):\n    return subprocess.run(cmd, shell=True)\n")
        assert main(["--strict"], root=tmp_path) == 0


class TestFullRepoScan:
    def test_warningModeCli_exitsZero_withStructuredOutput(self):
        result = subprocess.run(
            [sys.executable, "-I", "-X", "utf8", str(_SCRIPT)],
            capture_output=True, text=True, encoding="utf-8", timeout=300,
        )
        assert result.returncode == 0, f"warning 档不得阻断：\n{result.stdout}\n{result.stderr}"
        assert "误报率" in (result.stdout or "")

    def test_collectReport_isStructured(self):
        report = collectReport()
        assert set(report) >= {
            "scannedFiles", "shellExecSites", "concatSites",
            "violations", "falsePositiveRate", "mode",
        }
        assert report["scannedFiles"] > 0
        assert report["mode"] == "warning"
        assert 0.0 <= report["falsePositiveRate"] <= 1.0
        for v in report["violations"]:
            assert {"file", "line", "snippet", "kind"} <= set(v)

    def test_scanTreeOnRepo_consistentWithReport(self):
        report = collectReport()
        assert report["violations"] == scanTree(SCAN_ROOT)


class TestAllowRegistry:
    def test_registeredFiles_existOnDisk(self):
        missing = [k for k in ALLOW_REGISTRY if not (SCAN_ROOT.parent / k).exists()]
        assert missing == [], f"登记表含不存在文件（已改名/删除须同步移除）：{missing}"

    def test_everyEntry_hasReason(self):
        empty = [k for k, v in ALLOW_REGISTRY.items() if not str(v or "").strip()]
        assert empty == [], f"登记必须逐条带理由：{empty}"


class TestVerifiedFalsePositiveRate:
    def test_rate_inValidRange(self):
        assert 0.0 <= VERIFIED_FALSE_POSITIVE_RATE <= 1.0


class TestFindConcat:
    def _expr(self, src: str) -> ast.AST:
        return ast.parse(src, mode="eval").body

    def test_concatVariants_detected(self):
        assert findConcat(self._expr('f"ls {x}"'))
        assert findConcat(self._expr('"ls " + x'))
        assert findConcat(self._expr('"ls %s" % x'))
        assert findConcat(self._expr('"ls {}".format(x)'))

    def test_plainExpressions_notDetected(self):
        assert not findConcat(self._expr("cmd"))
        assert not findConcat(self._expr("str(cmd)"))
        assert not findConcat(self._expr("const_cmd"))
