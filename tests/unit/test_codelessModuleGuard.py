# -*- coding: utf-8 -*-
"""包树里不得存在"零语句模块"（除 docstring 外什么都没有的非 `__init__` .py）。

来历：`neurova/llm/client.py`（8 行）是 `7835c367` 那批 **pyc 骨架恢复**留下的占位文件，
docstring 自己写着「原始代码中此模块被重构到 `neurova.llm_client`，此文件为保持导入兼容性而创建」，
而正文只有一句注释——**import 它不会产生任何效果**。AST 复算：它在生产/测试两侧的引用面均为 **0**
（`neurova/`、`tests/`、`scripts/` 全扫），字符串形态的动态导入也没有（仓内唯一的动态入口
`plugins/plugin_manager.py:377` 按文件路径载插件，与包名无关）。
同批恢复出来的其它占位（`config_resolver`/`config_console`）早已在别处退役，只剩这一件。

为什么这类必须钉住而不是删掉拉倒：一个"看起来能 import"的名字会骗过人与工具——
按名字 grep 会命中、按名字 import 不报错，但它什么都不做；而"兼容性"这个说法
只有在**确实还有人从旧路径导入**时才成立，零消费者的兼容层就是纯粹的结构壳。
§9 序 4 那一行的 ≈2400 行预估也正是因此作废（见台账 §6-103）。

判据形态（吃过一次亏，谓词必须带反向对照）：
1. 现网为空集；
2. **`__init__.py` 不在射程内**——空包标记是 Python 的正常形态，现网 12 个
   docstring-only 的 `__init__.py` 一个都不许误伤（首版若只看"除 docstring 外无语句"
   就会把这 12 个全判成违规）；
3. 有语句的模块不得误伤（哪怕只有一行 `X = 1`）；
4. 注入探针：tmp 目录里造一枚零语句模块必须被抓到（防"扫空即绿"）；
5. 扫描根覆盖性：`neurova/` 至少要扫到几百个 .py，路径层级写错时当场红。
"""
from __future__ import annotations

import ast
from pathlib import Path

from tests import ast_scan

import pytest

REPO = Path(__file__).resolve().parents[2]
PKG_ROOT = REPO / "neurova"
pytestmark = pytest.mark.timeout(120)


def _hasNoStatement(tree: ast.AST) -> bool:
    """除 docstring / 注释外没有任何语句 ⇒ 这个模块 import 进来什么都不发生。"""
    return not [n for n in tree.body
                if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))]


def _codelessModules(root: Path) -> list[str]:
    """`root` 树里的零语句模块（`__init__.py` 除外——空包标记是正常形态）。

    枚举与解析走 tests/ast_scan 的共享预算（`parsedModules` 一次给出
    `(路径, 语法树)`），不私有 `rglob + ast.parse`——后者把判据成本绑在代码总量上
    （见 tests/unit/test_ci_ast_scan_budget_guard.py）。
    """
    found = []
    for path, tree in ast_scan.parsedModules(root, ".py"):
        if path.name == "__init__.py":
            continue
        if _hasNoStatement(tree):
            found.append(path.relative_to(root).as_posix())
    return found


def test_neurovaTreeHasNoCodelessModule():
    found = _codelessModules(PKG_ROOT)
    assert not found, (
        f"neurova/ 里有零语句模块：{found}\n"
        "它们让 `import neurova.x.y` 不报错却什么都不做；按名字 grep 还会命中。"
        "确有旧路径消费者时它才叫兼容层，零消费者就只是结构壳——"
        "要么接上消费者，要么连同引用一起退役。")


def test_injectedCodelessModuleIsCaught(tmp_path):
    """反向对照①：造一枚必须抓到——否则上面那条断言是"扫空即绿"。"""
    (tmp_path / "shim.py").write_text('"""占位。"""\n# 只有一句注释\n', encoding="utf-8")
    assert _codelessModules(tmp_path) == ["shim.py"]


def test_initMarkersAndRealModulesAreNotFlagged(tmp_path):
    """反向对照②：空 `__init__.py`、docstring-only `__init__.py`、有一行代码的模块都不许误伤。"""
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pkg2").mkdir()
    (tmp_path / "pkg2" / "__init__.py").write_text('"""门面。"""\n', encoding="utf-8")
    (tmp_path / "pkg3").mkdir()
    (tmp_path / "pkg3" / "__init__.py").write_text("X = 1\n", encoding="utf-8")
    (tmp_path / "one_liner.py").write_text("VALUE = 1\n", encoding="utf-8")
    assert _codelessModules(tmp_path) == [], f"误伤：{_codelessModules(tmp_path)}"

    # 现网实据：12 个 docstring-only 的 `__init__.py` 全部不在射程内
    inits = [p for p, tree in ast_scan.parsedModules(PKG_ROOT, ".py")
             if p.name == "__init__.py" and _hasNoStatement(tree)]
    assert len(inits) >= 5, "现网连一个空包标记都没有？扫描面或谓词变了，请复核"
    assert not _codelessModules(PKG_ROOT), (
        f"现网仍有零语句模块（本格与首格同判据，只是这里从反向对照视角看）：{_codelessModules(PKG_ROOT)}")


def test_scanRootActuallyCoversTheTree():
    """防"扫描根写错→无事发生却报绿"：覆盖性当场数一遍。"""
    modules = ast_scan.filesUnder(PKG_ROOT, ".py")
    assert len(modules) > 500, f"扫描根 {PKG_ROOT} 只覆盖 {len(modules)} 个 .py，层级写错了"
