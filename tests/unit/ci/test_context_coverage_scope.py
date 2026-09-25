# -*- coding: utf-8 -*-
"""T-09 第 6 项：上下文链路的覆盖率度量范围必须真的覆盖它（Issue #90）。

## 缺陷（改前实证）

`pyproject.toml` 的覆盖率 `include` 只有八个模块（工具层 / 安全层 / 两个端点），
注释写着「context/ 等待 P1-1 测试落地后加入」。该前置条件早已由 T-01…T-06 与
B4/B5/B6 满足：上下文是**唯一**被 `main.push` 九条流水线中覆盖率门禁单独漏掉的
域，于是「覆盖率 60%」这条门禁对这批新代码**零约束**——门禁绿得毫无意义。

## 契约

1. `include` 覆盖 `*/context/*.py` 与 `*/context_pool.py`；
2. 该度量范围加入后总覆盖率仍过 `fail_under`（不是把门禁改成必红）；
3. 度量范围**不空转**：`include` 的模式必须真命中文件（反向控制——写一个
   命中为空的 glob 会被本判据抓住）。
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

PYPROJECT = PROJECT_ROOT / "pyproject.toml"

CONTEXT_PATTERNS = ("*/context/*.py", "*/context_pool.py")


def _coverageInclude() -> list:
    with PYPROJECT.open("rb") as fh:
        return tomllib.load(fh)["tool"]["coverage"]["run"]["include"]


class TestContextIsMeasured:
    @pytest.mark.parametrize("pattern", CONTEXT_PATTERNS)
    def test_include_covers_context_modules(self, pattern):
        include = _coverageInclude()
        assert pattern in include, (
            f"覆盖率 include 不含 {pattern} —— 上下文链路的判据不受覆盖门禁约束。\n"
            f"（这正是 T-09 第 6 项：注释里的前置条件已由 T-01…T-06 / B4-B6 满足）\n"
            f"现 include = {include}"
        )

    def test_include_matches_real_files(self):
        """反向控制：每个 context 模式必须真命中文件，否则是空转配置。"""
        for pattern in CONTEXT_PATTERNS:
            matched = list(PROJECT_ROOT.glob(pattern))
            assert matched, f"{pattern} 命中为空 —— 这条度量范围是空转的"

    def test_threshold_has_single_source(self):
        """阈值只允许一处定义：CI 命令行。

        `pyproject` 的 `[tool.coverage.report]` 若也写一份 `fail_under`，
        两处会漂移（改一处忘另一处），且 coverage 只认其中一方——
        正是"同一契约两份定义"的形态（修复教义第 6 条）。
        """
        with PYPROJECT.open("rb") as fh:
            config = tomllib.load(fh)["tool"]["coverage"]
        assert "report" not in config or "fail_under" not in config.get("report", {}), (
            "pyproject 又写了一份 fail_under —— 阈值的事实源是 CI 命令行"
        )

        cnb = (PROJECT_ROOT / ".cnb.yml").read_text(encoding="utf-8")
        assert "--cov-fail-under=60" in cnb, "CI 命令行里的覆盖率阈值不见了"
