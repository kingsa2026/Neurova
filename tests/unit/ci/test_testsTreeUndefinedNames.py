# -*- coding: utf-8 -*-
"""测试树自己的未定义名判据（审计 TEST-04）。

静态门禁只看 `neurova/` 与 `scripts/`（生产面）；测试树的隐藏未定义名因此无人守护。
审计实测的形态：`__main__` 入口调 `pytest.main` 却没 import pytest、lambda 里用未定义
的模块级常量、返回注解缺 `Any`、字符串注解引用只在 setUp 内导入的类名。共同点是
**当前分支不触发**——pytest 不进入脚本入口、注解在 PEP 563 下不求值——所以 19 个用例
全绿，缺陷却留在文件里，下次改分支或直接 `python 文件` 跑就炸。

判据：pyflakes 在整棵 `tests/` 树上零 `undefined name`。两条**故意**的阴性对照
（`test_post_chat_pipeline_safe_step.py` 验 NameError 不被吞、`test_anonymizeReachesTheEngine.py`
验未定义注解名求值必炸）在命中行带 `# noqa: F821`，按其字面用途豁免——它们是"要它炸"
的用例，删掉才是把判据挪走。
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

#: pyflakes 一行的读数：`<file>:<行>:<列>: undefined name 'x'`
_UNDEFINED_LINE = re.compile(r"^(?P<file>.+?):(?P<row>\d+):\d+: undefined name (?P<name>'.+'|\".+\")$")

#: "要它炸"的阴性对照标记：命中行显式声明豁免（只认行内标记，不认文件级全局豁免）
_INTENTIONAL_MARK = "noqa: F821"


def _noqaLines(path: Path) -> set:
    """文件内带 `noqa: F821` 的行号集合。"""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return set()
    return {
        index
        for index, line in enumerate(text.splitlines(), start=1)
        if _INTENTIONAL_MARK in line
    }


def _undefinedReadings() -> list:
    """pyflakes 跑整棵 tests/，返回未被行内豁免的 `undefined name` 读数。"""
    proc = subprocess.run(
        [sys.executable, "-m", "pyflakes", "tests"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        timeout=120,
    )
    readings = []
    for line in (proc.stdout or "").splitlines():
        match = _UNDEFINED_LINE.match(line)
        if not match:
            continue
        path = REPO_ROOT / match.group("file")
        if int(match.group("row")) in _noqaLines(path):
            continue
        readings.append(line)
    return readings


class TestTestsTreeHasNoHiddenUndefinedNames:
    @pytest.mark.timeout(180)
    def testNoUndefinedNameInTestsTree(self):
        try:
            import pyflakes  # noqa: F401
        except ImportError:  # pragma: no cover - 精简环境缺工具时明确跳过，不伪装成绿
            pytest.skip("未安装 pyflakes，无法取数（CI 的 static-gate 腿会自己装）")
        readings = _undefinedReadings()
        assert readings == [], (
            "测试树存在未定义名（当前分支未触发，改分支/直接运行即炸）：\n" + "\n".join(readings)
        )