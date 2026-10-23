"""`neurova/execution_layers` 的传输那半退役判据（票④包 4）。

这个文件 719 行是**两半**，必须分开判——整包判死会误杀在役符号（台账早先记过这一形）：
- **运行时那半在役**：`RuntimeType`／`LocalExecutor`／`DockerExecutor`／`RuntimeFactory`／
  `RuntimeManager`／`get_runtime_manager` 各有 1–3 个生产文件取用（`computer_use/__init__.py:496/501`、
  `sandbox/exec_sandbox.py:421`、`skill_system/core.py:705/743`、`tool_executor.py:5692`）；
- **传输那半从未接线**：`TransportType`／`ExecutionTransport`／`HTTPTransport`／`WebSocketTransport`／
  `TransportFactory` 的生产档取用与测试档取用**现读全为 0**。别被同名骗了：
  `execution_engine/mcp_manager.py:29` 那个 `TransportType` 是**它自己的一份枚举**，与这里无关
  （那份枚举随 §6-334 的 D 票于 §6-349 整档退役；同名陷阱的**口径**留着，不随文件消失）。
- 还有一处更隐蔽的：**API 谎**。`execute_skill()` 签名里有 `transport` 参数、docstring 写着
  "传输层（可选）"，函数体从头到尾没用过它——调用方传什么都被静默丢弃。这类"接了不用的参数"
  比死代码更坏，因为它在契约上承诺了一件不做的事。

判据两轨：主格钉"传输那半不再是顶层定义、且全仓无代码引用"；交付锁钉"运行时那半一条没被删过头"
（工厂造得出本地运行时、单例语义不变、真 `exec` 得回来），外加一格钉那个假参数确实从签名上消失。
"""
from __future__ import annotations

import ast
import sys
import pathlib
import sys

from tests import ast_scan

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
INIT = REPO_ROOT / "neurova" / "execution_layers" / "__init__.py"

#: 传输那半（零消费者、零测试覆盖）——退役对象
TRANSPORT_SURFACE = ("TransportType", "ExecutionTransport", "HTTPTransport",
                     "WebSocketTransport", "TransportFactory")


def _topLevelNames() -> dict:
    tree = ast.parse(INIT.read_text(encoding="utf-8", errors="replace"))
    kinds = {}
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            kinds[node.name] = "class"
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # AsyncFunctionDef 必须一起认：`execute_skill` 就是 async def，
            # 只认 FunctionDef 会让那一格**恒绿**（本会话第一次修完又踩到同族）。
            kinds[node.name] = "def"
    return kinds


def _importsFromThisModule(tree: ast.AST, rel: str) -> set:
    """该文件**经导入通道**从本模块取走的名字（输入是一棵已解析的树＋仓内相对路径）。

    为什么不按符号名扫全仓（第一版就是这么写的，被自己抓红）：`TransportType` 这个名字在
    `execution_engine/mcp_manager.py:29` 曾有**另一份同名枚举**（§6-349 已整档退役），按名扫会把
    在役符号判成「还在引用已退役面」。Python 里「消费某模块的名字」只有一条通道——从该模块导入
    （或 `module.Name` 属性访问），判这条既无误伤也不漏。

    枚举与解析归 `tests/ast_scan` 的共享预算（§6-314 的 D22：判据里不再自己 `glob + ast.parse`）。
    绝对名一律由 `ast_scan.resolveImportModule` 解——只按 `node.module` 原文比对看不见相对形，
    那会把"还在导入"读成零引用（§6-212 记过的同一族）。
    """
    taken = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (
                (node.module or "").endswith("execution_layers")
                or ast_scan.resolveImportModule(rel, node).endswith("execution_layers")):
            taken.update(a.name for a in node.names)
        elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) \
                and node.value.id == "execution_layers":
            taken.add(node.attr)
    return taken


def test_noCodeAnywhereImportsTheRetiredTransportSurface():
    """主格②：全仓（生产＋测试）不许再经导入通道取走那五个名字＋那个假 helper。

    取数走共享预算：`sourceRefsUnder` 枚举＋文本预筛（判据要求模块名以 `execution_layers` 结尾，
    连这串字样都没有的文件不可能命中 ⇒ 充分条件），解析走 `transientTree`（本档只扫一遍，
    不留常驻语法树）。§6-314 的 D22 收的就是"判据自己 `rglob + ast.parse`"这个形态。
    """
    retired = set(TRANSPORT_SURFACE) | {"execute_skill"}
    offenders = []
    surface = len(ast_scan.sourceRefsUnder(ast_scan.REPO_ROOT, ".py"))
    assert surface > 3000, f"扫描面现读 {surface} 个 .py（根＝仓根）——根被改窄时「半区没复活」不代表退役成立"
    for ref in ast_scan.sourceRefsUnder(ast_scan.REPO_ROOT, ".py",
                                         ast_scan.textHints("execution_layers")):
        if ref.path == INIT:
            continue
        hit = retired & _importsFromThisModule(
            ast_scan.transientTree(ref.path), ast_scan.relativeToRepo(ref.path))
        if hit:
            offenders.append((ast_scan.relativeToRepo(ref.path), sorted(hit)))
    assert not offenders, f"这些地方还在从该模块导入已退役名字：{offenders}"


def test_runtimeHalfStillProducesAWorkingLocalRuntime():
    """交付锁①：删的是死半区，运行时那条活路必须照常能用（含真 exec 一个返回值）。

    名字按**现役工厂真名**取（`RuntimeFactory.create`，不是 `create_runtime`——第一版按印象写，
    被自己的红纠正）。
    """
    import asyncio

    from neurova.execution_layers import (
        LocalExecutor, RuntimeFactory, RuntimeManager, RuntimeType, get_runtime_manager)

    runtime = RuntimeFactory.create(RuntimeType.LOCAL)
    assert isinstance(runtime, LocalExecutor), f"工厂给的不是本地运行时：{type(runtime).__name__}"
    assert RuntimeFactory.list_supported_types() == [RuntimeType.LOCAL, RuntimeType.DOCKER]
    assert get_runtime_manager() is get_runtime_manager(), "单例语义被动过"
    assert isinstance(get_runtime_manager(), RuntimeManager)
    # 解释器按**本进程那个**取：POSIX 上只有 `python3`，写死 `python` 时红的是探针
    # （`FileNotFoundError: 'python'`），不是"运行时半区删错了"。
    result = asyncio.run(runtime.exec(command=sys.executable, args=["-c", "print(1)"], timeout=30))
    assert result.success and "1" in (result.stdout or ""), f"本地运行时执行不回来：{result}"


def test_transportHalfIsNoLongerDeclaredInThatModule():
    """主格①：传输那五个符号不再是本模块的顶层定义，`__all__` 里也不许留名。"""
    kinds = _topLevelNames()
    left = [n for n in TRANSPORT_SURFACE if n in kinds]
    declared = [n for n in TRANSPORT_SURFACE
                if n in {c.value for c in ast.walk(ast.parse(INIT.read_text(encoding="utf-8")))
                          if isinstance(c, ast.Constant) and isinstance(c.value, str)}]
    assert not left, f"传输那半还留着顶层定义：{left}"
    assert not declared, f"`__all__`／字符串面还挂着已退役的传输名：{declared}"


def test_executeSkillHelperIsGoneWithItsLie():
    """交付锁②：那个"接了 transport 却从头到尾不用"的模块级 helper 一并收掉。

    `execute_skill()`（原 `:593`）全仓**无人从本模块导入它**（技能执行的真咽喉是
    `tool_executor.execute_skill_tool` → `SkillRegistry.execute_skill`，与本模块无关），
    而它签名上承诺的 `transport` 参数在函数体里一次都没出现——"接了不用的参数"比死代码更坏，
    因为它在契约上写了一件不做的事。所以随传输那半一起删，而不是留着骗下一个调用方。
    """
    names = _topLevelNames()
    assert "execute_skill" not in names, "`execute_skill` 还在：那条假参数就还在骗人"
    importers = []
    for ref in ast_scan.sourceRefsUnder(ast_scan.PRODUCTION_ROOT, ".py",
                                        ast_scan.textHints("execution_layers")):
        if ref.path == INIT:
            continue
        rel = ast_scan.relativeToRepo(ref.path)
        for node in ast.walk(ast_scan.transientTree(ref.path)):
            if isinstance(node, ast.ImportFrom) and (
                    (node.module or "").endswith("execution_layers")
                    or ast_scan.resolveImportModule(rel, node).endswith("execution_layers")):
                if any(a.name == "execute_skill" for a in node.names):
                    importers.append(rel)
    assert not importers, f"这些文件还从该模块导入 execute_skill：{sorted(set(importers))}"
