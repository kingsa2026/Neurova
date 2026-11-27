# -*- coding: utf-8 -*-
"""neurova/tool_executor.py 尺寸棘轮：拆分只降不升。

参考 tests/unit/agent/test_agent_core_size_ratchet.py 的 `agent_core.py`
只降不升纪律。`ToolExecutor` 当前是超大类；先钉住 `tool_executor.py`
不再增长，再按 `docs/05-reports/全仓逐文件审计报告_2026-11-25.md` OPT-02
分批下沉纯函数、进程状态、工具族。

不改 `_builtin_dispatch`、`_BUILTIN_SCHEMAS`、`_execute_single_tool*`
顺序、`on_tool_executed` 单一咽喉；只钉文件行数不回填。
"""
import io
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
TOOL_EXECUTOR = PROJECT_ROOT / "neurova" / "tool_executor.py"

#: 起点只降不升；拆完一个阶段后应把本值下调到新实测值。
TOOL_EXECUTOR_LINE_BUDGET = 2000


def testToolExecutorFileDoesNotGrow():
    lines = io.open(TOOL_EXECUTOR, encoding="utf-8").read().splitlines()
    assert len(lines) <= TOOL_EXECUTOR_LINE_BUDGET, (
        f"neurova/tool_executor.py 当前 {len(lines)} 行，超过只降不升基线 "
        f"{TOOL_EXECUTOR_LINE_BUDGET}。拆分只降不升；新功能不得回填超大类。"
    )
