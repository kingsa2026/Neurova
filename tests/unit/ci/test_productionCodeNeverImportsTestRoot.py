# -*- coding: utf-8 -*-
"""生产码与运维脚本不得反向依赖测试根（P1-19 收口守卫）。

根因：``neurova/tool_executor.py``、``neurova/security/safe_expr.py``、
``neurova/workflow/scripted/validator.py`` 曾 ``from tests.ast_scan import
parseSource``，``scripts/`` 下另有 6 处同契约——``tests/``（AGENTS §4 整根
豁免跟踪的测试根）反向成为运行时事实源：任何不打包 tests/ 的发布形态
（wheel、仅含 neurova/ 的镜像）在 import 期即崩，工具执行 / 安全表达式 /
受限脚本三条链一起废。

修法（教义第 6 条，单一事实源）：共享解析预算唯一实现下沉
``neurova/core/ast_scan.py``；``tests/ast_scan.py`` 只留兼容薄转发。
本档钉住分层方向：``neurova/`` 与 ``scripts/`` 的 ``.py`` 里不得再出现
``import tests`` / ``from tests...`` 形式的真实 import（按 AST 调用点判，
注释与文档串里的"tests"字样不点名）。
"""

from __future__ import annotations

import ast
from pathlib import Path

from tests import ast_scan
from tests.ast_scan import parseSource

REPO_ROOT = Path(__file__).resolve().parents[3]


def _testsImportHits(root: Path) -> list:
    """``root`` 子树里 ``import tests`` / ``from tests ...`` 的真实落点（路径:行号）。"""
    hits: list = []
    for path in ast_scan.filesUnder(root, ".py"):
        tree = parseSource(ast_scan.sourceCode(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module == "tests" or module.startswith("tests."):
                    hits.append(f"{path.relative_to(REPO_ROOT).as_posix()}:{node.lineno}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "tests" or alias.name.startswith("tests."):
                        hits.append(f"{path.relative_to(REPO_ROOT).as_posix()}:{node.lineno}")
    return sorted(hits)


class TestProductionCodeNeverImportsTestRoot:
    def test_neurova_never_imports_tests_package(self):
        """主格：生产码不依赖测试根——不打包 tests/ 的发布形态不再 import 期即崩。"""
        hits = _testsImportHits(REPO_ROOT / "neurova")
        assert not hits, (
            "生产码出现了对 tests/ 的 import（测试根不得成为运行时事实源）：\n  "
            + "\n  ".join(hits)
            + "\n修法：把共享实现下沉到 neurova/（如 neurova/core/ast_scan.py），"
              "生产码改 import neurova.core.ast_scan；tests/ 侧只留兼容薄转发。")

    def test_scripts_never_import_tests_package(self):
        """同契约扫平：scripts/ 六处同款 import 一并收口到 neurova.core.ast_scan。"""
        hits = _testsImportHits(REPO_ROOT / "scripts")
        assert not hits, (
            "运维脚本出现了对 tests/ 的 import：\n  " + "\n  ".join(hits)
            + "\n修法：同生产码，改 import neurova.core.ast_scan。")

    def test_shared_budget_still_reachable_from_tests_side(self):
        """兼容面在：tests/ast_scan 薄转发仍交出同一个 parseSource 实现（743 行测试导入面不断）。"""
        from tests.ast_scan import parseSource as fromForwarder
        from neurova.core.ast_scan import parseSource as fromImpl
        assert fromForwarder is fromImpl, (
            "tests.ast_scan 与 neurova.core.ast_scan 必须是同一实现对象"
            "（薄转发不得复制第二份解析预算）")
        assert isinstance(parseSource("x = 1\n"), ast.AST)
