# -*- coding: utf-8 -*-
"""通用 KV 配置器只剩一份实现（§6-125；§9 序 5 批 E，用户裁 E-2）。

仓内原有两份通用 KV 配置器：`core/config.py:60`（分层版 354 行）与 `core/config_manager.py:21`
（简单版 118 行）。**两份的生产 import 复算都是 0**——`get_config_manager()`（`config.py:424`）
全仓零调用，grep 命中的十几处 `get_config_manager` 全是同名词不同物（`agent_config.py:438` 的
`AgentConfigManager` 工厂、`negative_screen_settings.py:84` 的 `_get_config_manager`）。既然两把
锁都无人用，教义 §2 的处置是收口成一份而不是并存，第 7 条的顺序是先比：

- 分层版是**超集**（`ConfigLevel` 分层 / `register_validator` / `on_change` / `bulk_set` / `export`）；
- 简单版只剩两格非超集：`clear()`（零消费者，不并）与 **load 侧的 warning-vs-error 分级**
  （"配置读不到"是可降级、"写盘失败"才是数据丢失）。后者是真长处，已并入 `config.py::load`，
  判据落点 `tests/unit/core/test_config_manager_persistence.py`。

本文件管的是**别再长出第二份**：简单版不得回到包里、无人可以再 import 它、且仓内不得再出现
第二个同时定义 `get` 与 `set` 的 `ConfigManager` 类。反向对照自证扫描器不是恒绿。
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests import ast_scan

REPO = Path(__file__).resolve().parents[3]
PKG = REPO / "neurova"
TESTS = REPO / "tests"
RETIRED = "neurova.core.config_manager"

pytestmark = pytest.mark.timeout(60)


def _importedNames(tree) -> list[str]:
    """一棵树里 AST 可见的导入目标。入参是**已解析的树**：枚举与解析走共享预算
    （`tests/ast_scan.py`，Issue #148：受保护子集里不得自带第二份全仓解析写法）。"""
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            out.append(node.module)
    return out


def _importers(root: Path) -> list[str]:
    found = []
    for p, tree in ast_scan.parsedModules(root):
        if any(n == RETIRED or n.startswith(RETIRED + ".") for n in _importedNames(tree)):
            try:
                shown = p.relative_to(REPO).as_posix()
            except ValueError:
                shown = p.relative_to(root).as_posix()   # 注入探针在 tmp 下（§6-107 的坑）
            found.append(shown)
    return found


def _kvConfigManagerClasses(root: Path) -> list[str]:
    """定义了名为 ConfigManager、且同时给出 get 与 set 的类（真正的 KV 面）。"""
    hits = []
    for p, tree in ast_scan.parsedModules(root, hints=("class ConfigManager",)):
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "ConfigManager":
                methods = {n.name for n in node.body
                           if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
                if {"get", "set"} <= methods:
                    try:
                        shown = p.relative_to(REPO).as_posix()
                    except ValueError:
                        shown = p.relative_to(root).as_posix()   # 同上：tmp 探针不在仓内
                    hits.append(f"{shown}:{node.lineno}")
    return hits


def test_retiredFileIsGone():
    assert not (PKG / "core" / "config_manager.py").is_file(), \
        "core/config_manager.py 又回到包里——第二份 KV 实现回来了"


def test_nobodyImportsTheRetiredModule():
    found = _importers(PKG) + _importers(TESTS)
    assert not found, f"退役的 KV 简单版又被人引用了：{found}"


def test_kvConfigManagerIsSingleSource():
    hits = _kvConfigManagerClasses(PKG)
    assert hits == ["neurova/core/config.py:60"], (
        f"通用 KV 配置器应当只有一份实现，现数：{hits}——"
        "长出第二份就先按教义第 7 条比优劣，再决定并到哪一份")


def test_livePlanningFacesUntouched():
    """反向对照（防删过头）：并过来的那格分级必须**落在 load 自己身上**，另有名的几份不同职
    实现不许被牵连。

    首稿写的是 `"json.JSONDecodeError" in config.py 全文` —— 当场假绿：那句话本就在
    `:402` 的 `_convert_env_value` 里躺着，把 load 的分级改回去这一格照样通过（存在性断言
    被别处同名满足，与 §6-106 那族同形）。现按 AST 取 `load` 函数体本身来判。
    """
    tree = ast.parse((PKG / "core" / "config.py").read_text(encoding="utf-8"))
    cls = next(n for n in ast.walk(tree)
               if isinstance(n, ast.ClassDef) and n.name == "ConfigManager")
    load = next(n for n in cls.body
                if isinstance(n, ast.FunctionDef) and n.name == "load")
    handled = {ast.unparse(h.type) for h in ast.walk(load)
               if isinstance(h, ast.ExceptHandler) and h.type is not None}
    assert any("JSONDecodeError" in h for h in handled), (
        f"load 的 except 没再单独接 JSONDecodeError，warning 分级被抹平成一律 error：{handled}")

    # 这几份是**领域面**（不实现 get/set 的 KV 契约），与本批无关，仍须在位
    assert (PKG / "shared_config.py").is_file()
    assert (PKG / "agent_config.py").is_file()


def test_scannerCatchesARevival(tmp_path):
    bad = tmp_path / "revival.py"
    bad.write_text(f"from {RETIRED} import ConfigManager\n", encoding="utf-8")
    assert _importers(tmp_path) == ["revival.py"]
    dup = tmp_path / "second_face.py"
    dup.write_text(
        "class ConfigManager:\n    def get(self, k, d=None):\n        return d\n"
        "    def set(self, k, v):\n        pass\n", encoding="utf-8")
    assert _kvConfigManagerClasses(tmp_path), "探测器抓不到新长出的第二份 KV 实现"

    bad.unlink()
    dup.unlink()
    assert not _importers(tmp_path)

    # 同名的**领域面**不得被误判成 KV 实现（判据过宽会把 `SharedConfigManager` 那类拖进射程）
    notKV = tmp_path / "domain_face.py"
    notKV.write_text("class ConfigManager:\n    def get_settings(self):\n        return {}\n",
                     encoding="utf-8")
    assert not _kvConfigManagerClasses(tmp_path), \
        "只定义 get_settings 的类被算成了 KV 实现——判据过宽"
