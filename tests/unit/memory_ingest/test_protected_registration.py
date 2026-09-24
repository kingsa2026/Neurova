# -*- coding: utf-8 -*-
"""memory_ingest 套件的判据文件必须真进 CI 受保护子集。

根因（Issue #81 复核，2026-09-22 实测）：设计 §6 三条硬规则点名的包层守卫
（整包校验 / 写入器 / 媒体 / 回合 / 记录 / 识别 / 记忆导入 / 七族转换器）共
14 个文件、197 条用例**不在** `scripts/ci/protected_tests.txt` 里——文件在仓、
逐文件单跑全绿、CI 也全绿，而受保护子集对它们命中 0，等于这些判据从未在 CI
上跑过。同批 4 个运行时锁文件倒是登记了，说明是**漏登记**，不是有意排除。
（对照 Issue #109：那是反向形态——清单指向不存在的文件。两者都会让"CI 绿"
与"判据真跑过"变成两件事。）

判据取**目录**而不是一份抄下来的文件名清单：本目录逐文件单跑确定全绿
（275 passed，2026-09-22），故目录下每个测试文件都必须进清单。新加文件自动
落在同一约束下，不靠人记得去补第二份名单。
"""

from __future__ import annotations

import io
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PACKAGE_TESTS = PROJECT_ROOT / "tests" / "unit" / "memory_ingest"
PROTECTED = PROJECT_ROOT / "scripts" / "ci" / "protected_tests.txt"
SELF_REL = "tests/unit/memory_ingest/test_protected_registration.py"


def _listedTests() -> set:
    """CI 实际跑的清单条目（唯一事实源）。"""
    raw = io.open(PROTECTED, encoding="utf-8").read()
    return {
        line.split("#", 1)[0].strip()
        for line in raw.splitlines()
        if line.split("#", 1)[0].strip()
    }


def _packageTestFiles() -> list:
    return sorted(
        f"tests/unit/memory_ingest/{path.name}"
        for path in PACKAGE_TESTS.glob("test_*.py")
    )


def test_every_package_test_file_is_registered():
    """反向自证：从清单里摘掉任一条 → 本用例转红。"""
    missing = [rel for rel in _packageTestFiles() if rel not in _listedTests()]
    assert not missing, (
        "memory_ingest 的判据文件不在受保护子集里 —— CI 不会跑它们，"
        f"'全绿'与'判据真跑过'不是同一件事：{missing}\n"
        "修复：逐文件单跑确认全绿后，加进 scripts/ci/protected_tests.txt。"
    )


def test_registered_package_files_are_tracked_by_git():
    """清单条目必须真被 git 跟踪：未跟踪 = CI 上 `file or directory not found`。"""
    if not (PROJECT_ROOT / ".git").exists():
        return
    files = _packageTestFiles()
    result = subprocess.run(
        ["git", "ls-files", *files],
        cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=60,
    )
    tracked = {line.strip() for line in result.stdout.splitlines() if line.strip()}
    assert tracked == set(files), (
        f"清单里登记了未被 git 跟踪的文件：{sorted(set(files) - tracked)}"
    )


def test_guard_itself_is_registered():
    assert SELF_REL in _listedTests(), (
        f"{SELF_REL} 不在受保护子集 —— 本守卫的判据在 CI 上不会执行。"
    )
