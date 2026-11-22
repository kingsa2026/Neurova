# -*- coding: utf-8 -*-
"""U2 卡：出站 HTTP 静态扫描器（scripts/check_outbound_fetch.py）契约。

- 全仓实跑：neurova/ 下直用 requests/httpx/aiohttp/urllib.request 的文件
  必须全部登记在 ALLOW_REGISTRY——断言零违规（退出码 0）；
- 登记表完整性：登记的路径必须真实存在（防改名后成死条目）；
- 检出能力：未登记的直用文件必须被标红；经 safe_fetch 的文件不标红。
"""
from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.check_outbound_fetch import ALLOW_REGISTRY, SCAN_ROOT, flagLines, scanTree

_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "check_outbound_fetch.py"


class TestFullRepoScan:
    def test_wholeRepo_hasZeroViolations(self):
        """对全仓实跑扫描脚本：所有直用 HTTP 库的文件均已登记（目标遗留=0 违规）。"""
        result = subprocess.run(
            # -X utf8：Windows 子进程管道输出强制 UTF-8（-I 隐含 -E，env 变量不生效）
            [sys.executable, "-I", "-X", "utf8", str(_SCRIPT)],
            capture_output=True, text=True, encoding="utf-8", timeout=120,
        )
        assert result.returncode == 0, (
            f"存在未登记的直用 HTTP 库文件，先迁移到 safe_fetch/url_guard 或登记：\n"
            f"{result.stdout}\n{result.stderr}"
        )
        assert "通过" in (result.stdout or "")

    def test_scanTreeOnRepo_matchesScriptExit(self):
        assert scanTree(SCAN_ROOT) == [], "scanTree 与脚本 CLI 判定必须一致"


class TestRegistryIntegrity:
    def test_registeredFiles_existOnDisk(self):
        missing = [k for k in ALLOW_REGISTRY if not (SCAN_ROOT.parent / k).exists()]
        assert missing == [], f"登记表含不存在文件（已改名/删除须同步移除）：{missing}"

    def test_securityDoorAndEngine_areRegistered(self):
        assert "neurova/security/safe_fetch.py" in ALLOW_REGISTRY
        assert "neurova/http_fetch.py" in ALLOW_REGISTRY

    def test_everyEntry_hasReason(self):
        empty = [k for k, v in ALLOW_REGISTRY.items() if not str(v or "").strip()]
        assert empty == [], f"登记必须逐条带理由：{empty}"


class TestDetection:
    def _scanTmp(self, tmp_path: Path, content: str, registry=None):
        (tmp_path / "sample.py").write_text(content, encoding="utf-8")
        return scanTree(tmp_path, registry=registry)

    def test_directRequestsImport_flagged(self, tmp_path):
        hits = self._scanTmp(tmp_path, "import requests\n\n\ndef go():\n    return requests.get('http://x')\n")
        assert len(hits) == 1 and hits[0]["file"].endswith("sample.py")

    def test_functionLevelHttpxImport_flagged(self, tmp_path):
        hits = self._scanTmp(tmp_path, "def go():\n    import httpx\n    return httpx.get('http://x')\n")
        assert len(hits) == 1

    def test_urlopenCall_flagged(self, tmp_path):
        hits = self._scanTmp(tmp_path, "from urllib.request import urlopen\n\n\ndef go():\n    return urlopen('http://x')\n")
        assert len(hits) == 1

    def test_aiohttpImport_flagged(self, tmp_path):
        hits = self._scanTmp(tmp_path, "async def go():\n    import aiohttp\n    async with aiohttp.ClientSession() as s:\n        return s\n")
        assert len(hits) == 1

    def test_safeFetchUsage_notFlagged(self, tmp_path):
        hits = self._scanTmp(tmp_path, (
            "from neurova.security.safe_fetch import safe_fetch\n"
            "\n\n"
            "def go():\n    return safe_fetch('http://x', timeout=3).text\n"
        ))
        assert hits == []

    def test_registryEntry_suppressesFlag(self, tmp_path):
        content = "import requests\n"
        (tmp_path / "sample.py").write_text(content, encoding="utf-8")
        registered = {str(tmp_path / "sample.py"): "测试登记：等效防护"}
        assert scanTree(tmp_path, registry=registered) == []

    def test_testsDir_notScanned(self, tmp_path):
        tests = tmp_path / "tests"
        tests.mkdir()
        (tests / "t.py").write_text("import requests\n", encoding="utf-8")
        assert scanTree(tmp_path, registry={}) == []

    def test_flagLines_ignoresCommentLines(self):
        assert flagLines("# import requests\n") == []
        assert flagLines("import requests\n") == [1]
