# -*- coding: utf-8 -*-
"""P2-30：ZCode 排除规则不得吞掉正当源码脚本。"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ZCODEIGNORE = PROJECT_ROOT / ".zcodeignore"


def _ignored(tmp_path: Path, relative: str) -> bool:
    repository = tmp_path / "ignore-fixture"
    repository.mkdir()
    (repository / ".gitignore").write_text(ZCODEIGNORE.read_text(encoding="utf-8"), encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=repository, check=True, timeout=10)
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "-q", relative],
        cwd=repository,
        capture_output=True,
        timeout=10,
    )
    return result.returncode == 0


def _ignoredMany(tmp_path: Path, relatives: list[str]) -> list[str]:
    repository = tmp_path / "ignore-fixture"
    repository.mkdir()
    (repository / ".gitignore").write_text(ZCODEIGNORE.read_text(encoding="utf-8"), encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=repository, check=True, timeout=10)
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "--stdin", "-z"],
        cwd=repository,
        input="\0".join(relatives) + "\0",
        text=True,
        capture_output=True,
        timeout=20,
    )
    return [item for item in result.stdout.split("\0") if item]


def testAllTrackedPythonSourcesRemainVisibleToZCode(tmp_path):
    tracked = subprocess.check_output(
        ["git", "ls-files", "*.py"], cwd=PROJECT_ROOT, text=True, timeout=20,
    ).splitlines()
    assert tracked, "仓库没有已跟踪 Python 文件，判据无从作答"
    assert _ignoredMany(tmp_path, tracked) == []


@pytest.mark.parametrize(
    "relative",
    [
        "scripts/check_frontend_api_paths.py",
        "scripts/check_openapi_snapshot.py",
        "scripts/migrate_agent_layout_v3.py",
        "neurova/memory/scripts/verify_channels.py",
        "tests/runners/run_unit.py",
        "tests/unit/ci/test_zcodeignore_source_coverage.py",
    ],
)
def testProductionAndTestScriptsRemainVisibleToZCode(tmp_path, relative):
    assert not _ignored(tmp_path, relative), f"正当脚本被 .zcodeignore 排除：{relative}"


@pytest.mark.parametrize(
    "relative",
    [
        "check_admin.py",
        "run_audit_tests.py",
        "fix_app_py.py",
        ".env.local",
        "scripts/__pycache__/check_tool_catalog.cpython-312.pyc",
    ],
)
def testRealTemporaryAndSensitiveArtifactsStayExcluded(tmp_path, relative):
    assert _ignored(tmp_path, relative), f"临时或敏感件未被排除：{relative}"
