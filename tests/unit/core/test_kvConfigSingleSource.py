"""通用 KV 配置器退役判据：环境助手仍在，重复实现不得复活。"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests import ast_scan
from tests.ast_scan import parseSource

REPO = Path(__file__).resolve().parents[3]
PKG = REPO / "neurova"
TESTS = REPO / "tests"
RETIRED = "neurova.core.config_manager"

pytestmark = pytest.mark.timeout(60)


def _importers(root: Path) -> list[str]:
    return sorted({rel for rel, _lineno, _form in ast_scan.importersOfModule(root, RETIRED)})


def _kvConfigManagerClasses(root: Path) -> list[str]:
    hits = []
    for ref in ast_scan.sourceRefsUnder(root, ".py", ast_scan.textHints("ConfigManager")):
        try:
            tree = parseSource(ref.code)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "ConfigManager":
                methods = {n.name for n in node.body
                           if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
                if {"get", "set"} <= methods:
                    hits.append(ref.path.as_posix())
    return hits


def test_retiredFileIsGone():
    assert not (PKG / "core" / "config_manager.py").is_file()


def test_nobodyImportsTheRetiredModule():
    found = _importers(PKG) + _importers(TESTS)
    assert not found, f"退役的 KV 简单版又被人引用了：{found}"


def test_kvConfigManagerIsFullyRetired():
    assert _kvConfigManagerClasses(PKG) == []


def test_environmentHelpersRemainLive():
    tree = parseSource((PKG / "core" / "config.py").read_text(encoding="utf-8"))
    names = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
    assert {"get", "get_int", "get_bool", "get_list", "loadEnvFile", "proxyUvicornArgs"} <= names
    assert (PKG / "shared_config.py").is_file()
    assert (PKG / "agent_config.py").is_file()


def test_scannerCatchesARevival(tmp_path):
    bad = tmp_path / "revival.py"
    bad.write_text(f"from {RETIRED} import ConfigManager\n", encoding="utf-8")
    assert [Path(path).name for path in _importers(tmp_path)] == ["revival.py"]

    viaParent = tmp_path / "via_parent.py"
    viaParent.write_text("from neurova.core import config_manager\n", encoding="utf-8")
    assert {Path(path).name for path in _importers(tmp_path)} == {"revival.py", "via_parent.py"}

    dup = tmp_path / "second_face.py"
    dup.write_text(
        "class ConfigManager:\n    def get(self, k, d=None):\n        return d\n"
        "    def set(self, k, v):\n        pass\n", encoding="utf-8")
    assert _kvConfigManagerClasses(tmp_path), "探测器抓不到新长出的第二份 KV 实现"

    bad.unlink()
    viaParent.unlink()
    dup.unlink()
    assert not _importers(tmp_path)

    notKV = tmp_path / "domain_face.py"
    notKV.write_text("class ConfigManager:\n    def get_settings(self):\n        return {}\n",
                     encoding="utf-8")
    assert not _kvConfigManagerClasses(tmp_path)
