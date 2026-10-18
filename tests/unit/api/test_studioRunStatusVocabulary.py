# -*- coding: utf-8 -*-
"""Studio runs 状态词汇表的单源收口（台账 §6-80 第四格的续作，教义第 6 条）。

E 批改前端时撞到的事实：生产写侧有 `done_with_fallback` 这第三种终态，读侧只认两种，
已完成的长任务被一路轮询到超时。当时只把前端那份对齐了，**词汇表本身仍然散在四处**：
`studio_api` 两处、`services` 三处、建表默认与启动收敛各一处，前端另有一份 TS 字面量。
下一次再加一种终态（比如 `cancelled`）时，漏认一处就是同一格复发。

判据三档：
1. 写侧不许写字面量——`add_run(`/`update_run(` 的实参里出现四个状态值之一即红（AST）；
2. 终态集合与实际写入值必须咬合——真跑一次端点，落库状态要在这个集合里；
3. **跨语言双向对齐**——TS 那份 `TERMINAL_STATUSES` 与 Python 的
   `RUN_TERMINAL_STATUSES` 逐元素相等。前端拿不到 Python 常量，这份相等关系只能由判据钉，
   否则"生产加终态、前端漏认"没有任何东西会报红。
"""
from __future__ import annotations

import ast
import io
import re
from pathlib import Path

from tests import ast_scan

import pytest

from neurova.aigc_studio import store as studio_store

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PRODUCTION = PROJECT_ROOT / "neurova"
TS_READSIDE = PROJECT_ROOT / "NeurUI" / "src" / "composables" / "useStudioRun.ts"

#: 写侧判据用的**测试侧**取值表：刻意不从 `store` 导入——那样一旦常量还不存在，
#: 本文件会先撞 ImportError，红就落在"新符号没建"而不是"写侧在写字面量"这个行为上。
#: 这四个值是 runs 表的全部终态/非终态取值，任何合理实现都得包含它们。
STATUS_VALUES = {"running", "done", "done_with_fallback", "failed"}

pytestmark = pytest.mark.timeout(60)


def _vocab():
    """延迟导入常量。

    放在模块级会让"常量尚未存在"的那一侧（改前）先撞 ImportError 而整文件收集失败——
    那样写侧那条判据根本没跑，红的就不是行为。故只在这三条需要 Python 词汇表的用例里取。
    """
    from neurova.aigc_studio.store import (
        RUN_FAILED,
        RUN_RUNNING,
        RUN_TERMINAL_STATUSES,
    )

    return RUN_RUNNING, RUN_FAILED, RUN_TERMINAL_STATUSES


def _statusLiteralsInRunWrites():
    """`add_run(...)` / `update_run(...)` 实参里出现的状态字面量（AST，不数注释）。"""
    offenders = []
    surface = len(ast_scan.filesUnder(PRODUCTION))
    assert surface > 500, (
        f"扫描面现读 {surface} 个 .py（根＝neurova/）——状态词汇是生产侧的契约，"
        "测试里出现的同名字符串是夹具不是第二份定义，故域明写在生产侧")
    # 枚举与解析走 tests/ast_scan 的共享预算（不私有 rglob + ast.parse——
    # 后者把判据成本绑在代码总量上，见 tests/unit/test_ci_ast_scan_budget_guard.py）。
    for path, tree in ast_scan.parsedModules(PRODUCTION, ".py"):
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = getattr(fn, "attr", None)
            if name not in {"add_run", "update_run"}:
                continue
            for lit in ast.walk(node):
                if isinstance(lit, ast.Constant) and lit.value in STATUS_VALUES:
                    offenders.append(
                        f"{path.relative_to(PRODUCTION)}:{node.lineno} -> {lit.value!r}"
                    )
    return offenders


class TestWriteSideUsesTheSingleSource:
    def test_noRunStatusLiteralsAtWriteSites(self):
        offenders = _statusLiteralsInRunWrites()
        assert offenders == [], (
            "runs 状态又回到字面量了（同一词汇表的第二份定义）：\n  " + "\n  ".join(offenders)
        )

class TestTerminalSetMatchesWhatProductionWrites:
    def test_reopenConvergenceWritesAStatusInTheSet(self, tmp_path):
        """启动收敛落的终态必须是词汇表里的那个，不能是自由字符串。"""
        db = str(tmp_path / "v.db")
        first = studio_store.StudioStore(db_path=db)
        row = first.add_run({"project_id": "p1", "kind": "videos"})
        first.close()

        second = studio_store.StudioStore(db_path=db)
        _, RUN_FAILED, RUN_TERMINAL_STATUSES = _vocab()
        back = next(r for r in second.list_runs("p1") if r["id"] == row["id"])
        assert back["status"] in RUN_TERMINAL_STATUSES, (
            f"收敛写了一个不在终态集合里的值：{back['status']!r}——轮询侧无从收尾"
        )
        assert back["status"] == RUN_FAILED
        second.close()

    def test_runningIsNotTerminal(self):
        RUN_RUNNING, _, RUN_TERMINAL_STATUSES = _vocab()
        assert RUN_RUNNING not in RUN_TERMINAL_STATUSES, (
            "running 进了终态集合＝前端第一次轮询就收工，长任务读数会假完成"
        )


class TestFrontendReadSideStaysAligned:
    def test_typescriptTerminalSetEqualsPythonSet(self):
        """跨语言的两份集合必须逐元素相等（读侧漏认一种终态就是 §6-80 第四格复发）。"""
        src = io.open(TS_READSIDE, encoding="utf-8").read()
        block = re.search(r"TERMINAL_STATUSES\s*=\s*new Set\(\[(.*?)\]\)", src, re.S)
        assert block, "前端那份终态集合找不到（改名了？把判据一起带过去，别让它裸奔）"
        tsSet = set(re.findall(r"['\"]([^'\"]+)['\"]", block.group(1)))
        _, _, RUN_TERMINAL_STATUSES = _vocab()
        assert tsSet == set(RUN_TERMINAL_STATUSES), (
            f"前后端终态集合分叉：TS={sorted(tsSet)} Python={sorted(RUN_TERMINAL_STATUSES)}"
            "——生产新增终态而读侧未跟，长任务会被轮询到超时"
        )
