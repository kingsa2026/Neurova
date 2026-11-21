# -*- coding: utf-8 -*-
"""C4：探测零副作用——浅探测（默认）绝不运行子进程。

- 行为断言：probeTool / probeToolHealth(deep=False) / listCatalog 三条路径
  注入的 run_fn / subprocess 钩子被调用即失败（零子进程）；
- ``--version`` 深探测仅显式 ``deep=True``（管理面 /test 握手专用）；
- AST 级断言：catalog.py 源码中浅探测函数体内不得出现 subprocess /
  Popen / start_process 等调用——子进程调用只允许存在于 _defaultProbeRun
  单点（深探测缺省执行器）。
"""
import ast
import subprocess
from pathlib import Path

import pytest

from neurova.agent.neuacp import catalog as catalogModule
from neurova.agent.neuacp.catalog import (
    CATALOG,
    listCatalog,
    probeTool,
    probeToolHealth,
)

_TOOL = "gemini-cli"

#: 派生进程类调用黑名单（名字级；subprocess.* 属性调用单独判定）
_SPAWN_NAMES = {"Popen", "start_process", "system", "popen", "spawn",
                "check_output", "check_call"}


@pytest.fixture(autouse=True)
def _forbidSubprocess(monkeypatch):
    """零子进程硬闸：被测路径只要触碰 subprocess / 缺省探测执行器即失败。"""

    def _fail(*args, **kwargs):
        raise AssertionError("探测路径运行了子进程（零副作用被违反）")

    monkeypatch.setattr(subprocess, "run", _fail)
    monkeypatch.setattr(subprocess, "Popen", _fail)
    monkeypatch.setattr(catalogModule, "_defaultProbeRun", _fail)


@pytest.fixture(autouse=True)
def _fakeWhich(monkeypatch):
    """which 桩：所有命令视为已安装（which 是文件系统查名，不是子进程）。"""
    monkeypatch.setattr(catalogModule.shutil, "which", lambda name: f"/fake/{name}")


# ── 行为断言：三条浅探测路径零子进程 ──────────────────────────────────────


def test_probeToolNeverRunsSubprocess():
    """probeTool（目录/前端下拉路径）只做 which 级检查，绝不 spawn。"""
    for tool in (*CATALOG, "not-a-tool"):
        result = probeTool(tool)
        assert "installed" in result


def test_probeToolHealthShallowDefaultNeverRunsVersionProbe():
    """probeToolHealth 默认（deep=False）零子进程：run_fn 注入钩子不被触发。"""
    seen = []

    def run_fn(cmd, timeout_s):
        seen.append(list(cmd))
        return (0, "should-not-run", "")

    for tool, entry in CATALOG.items():
        result = probeToolHealth(tool, which_fn=lambda name: "/fake/x", run_fn=run_fn)
        if entry.get("disabled"):
            # 禁用工具在前置路径即返回 disabled，不进入 which/版本探测
            assert result["error"] == "disabled", f"{tool} 应报 disabled"
        else:
            assert result["installed"] is True, f"{tool} which 命中应 installed=True"
    assert seen == [], "浅探测路径不得运行 version 子进程"


def test_probeToolHealthShallowReturnsNoVersionWithoutError():
    """浅探测形态：installed 来自 which；version 未知（None）且无错误。"""
    result = probeToolHealth(_TOOL)
    assert result["installed"] is True
    assert result["version"] is None
    assert result["error"] is None
    assert result["install_hint"] == CATALOG[_TOOL]["install_hint"]


def test_probeToolHealthUnknownToolShallowNeverSpawns():
    """未知工具在浅探测下同样零子进程，返回 unknown_tool。"""
    result = probeToolHealth("no-such-tool")
    assert result["installed"] is False
    assert result["error"] == "unknown_tool"


def test_listCatalogNeverRunsSubprocess():
    """listCatalog（状态/目录轮询路径）零子进程。"""
    items = listCatalog()
    assert items and all("installed" in item and "capabilities" in item for item in items)


def test_deepProbeRunsVersionOnlyWhenExplicit():
    """显式 deep=True 才做 --version 深探测（run_fn 注入，版本如实解析）。"""
    seen = {}

    def run_fn(cmd, timeout_s):
        seen["cmd"] = list(cmd)
        return (0, "9.9.9\nbuild 1\n", "")

    result = probeToolHealth(_TOOL, which_fn=lambda name: "/fake/gemini",
                             run_fn=run_fn, deep=True)
    assert result["installed"] is True
    assert result["version"] == "9.9.9"
    assert result["error"] is None
    assert seen["cmd"] == [CATALOG[_TOOL]["command"][0], "--version"]


def test_deepProbeIsKeywordOnlyBackwardCompatible():
    """deep 为 keyword-only：旧位置传参不兼容（向后兼容=旧关键字调用不变）。"""
    with pytest.raises(TypeError):
        probeToolHealth(_TOOL, True)


# ── AST 级断言：浅探测函数体内禁绝子进程调用 ──────────────────────────────


def _catalogTree() -> ast.Module:
    source = Path(catalogModule.__file__).read_text(encoding="utf-8")
    return ast.parse(source)


def _findFunction(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"catalog.py 缺少函数 {name}")


def _isSpawnCall(call: ast.Call) -> bool:
    """子进程派生类调用判定：subprocess.* 调用或名字级 spawn 家族。"""
    func = call.func
    if isinstance(func, ast.Name):
        return func.id in _SPAWN_NAMES
    if isinstance(func, ast.Attribute):
        if isinstance(func.value, ast.Name) and func.value.id == "subprocess":
            return True
        return func.attr in _SPAWN_NAMES
    return False


@pytest.mark.parametrize("fnName", ["probeTool", "listCatalog", "probeToolHealth"])
def test_shallowProbeFunctionBodiesContainNoSubprocessCalls(fnName):
    """AST 级：浅探测函数体内不得出现 subprocess/Popen/start_process 等调用。

    深探测经 run_fn 注入执行（缺省实现单点收敛在 _defaultProbeRun），
    浅探测函数体自身不得直接派生子进程。
    """
    tree = _catalogTree()
    fn = _findFunction(tree, fnName)
    violations = [
        node for node in ast.walk(fn)
        if isinstance(node, ast.Call) and _isSpawnCall(node)
    ]
    assert violations == [], f"{fnName} 函数体内出现子进程调用: {violations}"


def test_subprocessCallsConfinedToDefaultProbeRun():
    """模块级收口：subprocess 派生调用只允许存在于 _defaultProbeRun 单点。"""
    tree = _catalogTree()
    probe = _findFunction(tree, "_defaultProbeRun")
    lo, hi = probe.lineno, probe.end_lineno
    outside = [
        (node.lineno, ast.dump(node.func))
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and _isSpawnCall(node)
        and not (lo <= node.lineno <= hi)
    ]
    assert outside == [], f"subprocess 调用逃逸出 _defaultProbeRun: {outside}"
