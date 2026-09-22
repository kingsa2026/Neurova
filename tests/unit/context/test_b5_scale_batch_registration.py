# -*- coding: utf-8 -*-
"""B5 规模批（Issue #90 · PR #138）的判据文件必须真被 CI 跑到。

根因（本批实测，2026-09-22）：PR #138 交付了三条新用例文件
（单趟打分 / 候选集上界、召回额度地板、窗口折叠计量），却**没有**把它们登记进
`scripts/ci/protected_tests.txt`。于是出现一种"绿得毫无意义"的状态：

- 文件在仓库里、单跑全绿、CI 全绿；
- 而受保护子集里对它们的命中数是 **0** —— CI 从未跑过这三条判据。

这不是"少登记一行"，而是受保护子集的一半语义失效：清单声称"这些回归有人守"，
实际没有任何机制保证**新写的判据**进入清单。Issue #109 的事故是清单指向不存在的
文件（跑不起来）；本次是反向形态——文件存在但清单里没有（跑不到）。
两种形态都会让"CI 绿"与"判据真跑过"变成两件事，故一并钉住。
"""

from __future__ import annotations

import io
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PROTECTED = PROJECT_ROOT / "scripts" / "ci" / "protected_tests.txt"

#: B5 规模批（PR #138）交付的判据文件。
BATCH_FILES = (
    "tests/unit/context/test_drawer_scale_scoring.py",
    "tests/unit/context/test_recall_budget_floor.py",
    "tests/unit/context/test_window_token_metering.py",
)


def _listed() -> set:
    raw = io.open(PROTECTED, encoding="utf-8").read()
    return {
        line.split("#", 1)[0].strip()
        for line in raw.splitlines()
        if line.split("#", 1)[0].strip()
    }


def test_b5_batch_files_are_registered():
    """反向自证：从清单里摘掉任一条 → 本用例转红。"""
    missing = [rel for rel in BATCH_FILES if rel not in _listed()]
    assert not missing, (
        "B5 规模批的判据文件不在受保护子集里 —— CI 不会跑它们，"
        f"'全绿'与'判据真跑过'不是同一件事：{missing}\n"
        "修复：加进 scripts/ci/protected_tests.txt（该文件单跑全绿后登记）。"
    )


def test_registered_files_are_tracked_by_git():
    """清单条目必须真被 git 跟踪：未跟踪 = CI 上 `file or directory not found`。"""
    if not (PROJECT_ROOT / ".git").exists():
        return
    result = subprocess.run(
        ["git", "ls-files", *BATCH_FILES],
        cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=60,
    )
    tracked = {
        line.strip() for line in result.stdout.splitlines() if line.strip()
    }
    assert tracked == set(BATCH_FILES), (
        f"清单里登记了未被 git 跟踪的文件：{sorted(set(BATCH_FILES) - tracked)}"
    )


def test_guard_itself_is_registered():
    """守卫自己也得进清单，否则本文件的判据在 CI 上根本不执行。"""
    rel = "tests/unit/context/test_b5_scale_batch_registration.py"
    assert rel in _listed(), (
        f"{rel} 不在受保护子集 —— 本守卫的判据在 CI 上不会执行。"
    )
