# -*- coding: utf-8 -*-
"""`ast.parse` 全仓只许一处出口：`ast_scan.parseSource`（违规即红）。

为什么要有它（实测，非推测）：受保护子集第 2 片曾出现

    SystemError: AST constructor recursion depth mismatch (before=126, after=176)

落在 `tests/unit/api/test_corsPolicyIsSingleSource.py`，而该档单跑、与邻居两两组合跑都绿
——它不是某条判据的断言错，是**进程态**的形状：`ast.parse` 的节点在 `__init__` 里按当时的
递归深度定 `lineno` / `col_offset` 的求解深度，同一进程里"从深栈解析"与"从浅栈解析"并存时，
足迹校验逐层比对就可能对不上。落点此前散在 430 处、237 个文件，这种不一致既不可 grep
也不可测：只能等它碰巧在某一格炸，炸点与真因还不在同一个文件。

诚实边界：本机没能用宿主复现那个 `SystemError`（试过深浅嵌套、同线程/跨线程并发、
`compile` 复核足迹），故本档钉的是**结构**（解析只有一个可改可测的入口），
不声称"那个偶发红已根修"——未复现就不写已根修。

于是把出口收成一处（教义第 6 条）：`tests/ast_scan.parseSource`。本档钉三件事：

1. 仓内 `.py` 里除那唯一出口外**没有**第二处 `ast.parse` 调用；
2. 反向控制——把一条 `ast.parse(...)` 语音塞进样本串，探测器必须报出（否则"全绿"
   与"探测器坏了"不可分辨）；
3. 出口本体在（`parseSource` 真的可调用、真的交出 `ast.AST`）。

为什么不判 `compile(..., PyCF_ONLY_AST)`：本仓零落点，写一条永不命中的判据就是空转；
真出现时会先被 `tests/unit/test_ci_ast_scan_budget_guard.py` 的解析原语表抓走
（那里按语义判解析面，本档只钉"出口唯一"）。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests import ast_scan
from tests.ast_scan import parseSource

REPO_ROOT = Path(__file__).resolve().parents[3]
#: 唯一出口所在的模块（本档与它自己都要豁免，否则判据会点名自己的源码）
EXIT_MODULE = Path(ast_scan.__file__).resolve()
#: 判据不得自指：本档正文里必然出现 `ast.parse` 这个词（解释缺陷要用原文）
SELF = Path(__file__).resolve()


def _scanRoots() -> list:
    """判仓内三片源码面：产品码、运维脚本、测试。与 `ast_scan.filesUnder` 同一剪枝口径。"""
    return [REPO_ROOT / "neurova", REPO_ROOT / "scripts", REPO_ROOT / "tests"]


def _callSites() -> list:
    """全仓 `ast.parse(...)` 的**调用**落点（`路径:行号`）。

    唯一的调用在出口模块里，故正常应为空。判的是 AST 调用点，不是文本里出现过这个词：
    `# 不做 rglob + ast.parse` 这类口径说明有一百多处，按行判等于禁止解释。
    """
    hits = []
    for root in _scanRoots():
        for path in ast_scan.filesUnder(root, ".py"):
            resolved = path.resolve()
            if resolved in (EXIT_MODULE, SELF):
                continue
            for node in ast.walk(parseSource(ast_scan.sourceCode(path))):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "parse"
                        and isinstance(node.func.value, ast.Name)
                        and node.func.value.id == "ast"):
                    hits.append(f"{path.relative_to(REPO_ROOT).as_posix()}:{node.lineno}")
    return sorted(hits)


def _callsAstParse(source: str) -> bool:
    """探测器本体（本档取数只有这一处）：源码里有没有 `ast.parse(...)` 调用。"""
    for node in ast.walk(parseSource(source)):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "parse"
                and isinstance(node.func.value, ast.Name) and node.func.value.id == "ast"):
            return True
    return False


class TestParseHasOneExit:
    def test_no_second_ast_parse_call_in_the_repo(self):
        """主格：仓内 `ast.parse` 的**真实调用**只许出现在唯一出口里。

        取数走 AST（按调用点判），不按文本行判——本仓正文里写着 `ast.parse` 这个词的
        注释与文档串有一百多处（"为什么不做 rglob + ast.parse"这类口径说明），
        按行判会把它们全部点名，那是判据在要求大家别写字解释自己的修法。
        """
        hits = _callSites()
        assert not hits, (
            "仓内出现了第二处 `ast.parse`（解析口径必须只有一处出口 "
            "`tests/ast_scan.parseSource`）：\n  " + "\n  ".join(hits)
            + "\n修法：改成 `from tests.ast_scan import parseSource` 并调它。"
            "解析栈深散在 200+ 个文件里时，"
            "`AST constructor recursion depth mismatch` 只会在某次组合里炸，"
            "炸点与真因还不在同一个文件。")

    def test_detector_namesASecondCopy(self):
        """反空转格：探测器必须认得"又写一处 `ast.parse`"这个动作本身。"""
        assert _callsAstParse("import ast\ntree = ast.parse('x = 1')\n"), (
            "探测器漏认 `ast.parse` 调用——上面那条「全仓没有第二处」在空转"
        )
        assert not _callsAstParse(
            "from tests.ast_scan import parseSource\ntree = parseSource('x = 1')\n"), (
            "探测器把唯一出口 `parseSource` 当成了第二处——判据会点名合规写法"
        )

    def test_the_exit_actuallyParses(self):
        """出口本体在：真的可调用、真的交出 `ast.AST`，且语法错照旧抛（不是吞异常）。"""
        assert isinstance(parseSource("x = 1\n"), ast.AST)
        with pytest.raises(SyntaxError):
            parseSource("def (:\n")
