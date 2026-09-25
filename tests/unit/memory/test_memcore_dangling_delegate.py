"""MemCore 委托完整性守卫（纯静态，不导入被测模块）。

存在理由：`unified_experience_recall` 曾把经验召回委托给 `self.recall`，而 MemCore
从未定义过 `recall`（同名方法在 `MemoryManager` 上，少了一层转发）。该缺陷长期不被
发现，是因为覆盖它的用例只断言 `hasattr` / `callable`——方法存在即绿，方法体是死是坏
无人验。本用例改为静态扫描 `self.<X>` 是否指向真实成员，委托目标缺失必红。

不在模块层导入 MemCore：`neurova.mem_core` 导入有副作用，会改变同目录其他用例的
共享状态（实测把 `test_neuHebb_curator` 的顺序依赖翻红）。这里只按源码文本判定。
"""

import ast
import pathlib

import pytest

_MEM_CORE = pathlib.Path(__file__).resolve().parents[3] / "neurova" / "mem_core.py"
_CLASS_NAME = "MemCore"


@pytest.fixture(scope="module")
def classNode():
    tree = ast.parse(_MEM_CORE.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == _CLASS_NAME:
            return node
    pytest.fail(f"{_MEM_CORE.name} 中找不到类 {_CLASS_NAME}，守卫需同步更新")


def _definedMembers(cls: ast.ClassDef) -> set:
    """类内可见的成员名：方法、类级赋值、self.X 落下的实例属性。"""
    names = set()
    for node in ast.walk(cls):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
        ):
            names.add(node.target.id)
        elif (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "self"
            and isinstance(node.ctx, (ast.Store, ast.Del))
        ):
            names.add(node.attr)
    return names


def test_classIsStaticallyResolvable(classNode):
    """守卫的前提：成员全部来自类体本身。前提破时必须红，不得静默放过。"""
    assert not classNode.bases, (
        f"{_CLASS_NAME} 新增了基类，类体外定义的成员无法静态判定，"
        "本守卫需改为运行时 dir() 判定"
    )
    dunder_getattr = next(
        (n for n in classNode.body
         if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "__getattr__"),
        None,
    )
    assert dunder_getattr is None, (
        f"{_CLASS_NAME} 定义了 __getattr__ 动态委托，静态判定会漏报，"
        "本守卫需改为运行时探测"
    )


def test_memCore_hasNoDanglingSelfDelegate(classNode):
    defined = _definedMembers(classNode)
    offenders = sorted(
        (node.lineno, node.attr)
        for node in ast.walk(classNode)
        if isinstance(node, ast.Attribute)
        and isinstance(node.ctx, ast.Load)
        and isinstance(node.value, ast.Name)
        and node.value.id == "self"
        and node.attr not in defined
    )
    detail = "；".join(f"mem_core.py:{line} -> self.{name}" for line, name in offenders)
    assert not offenders, (
        f"{_CLASS_NAME} 方法体引用了自身不存在的成员（调用必 AttributeError）：{detail}"
    )


def test_guardActuallyCatchesDanglingDelegate():
    """反向锁：若扫描失去判别力，上一用例会被静默放空。"""
    cls = ast.parse(
        "class MemCore:\n"
        "    def ok(self):\n"
        "        return self.alreadyDefined()\n"
        "    def alreadyDefined(self):\n"
        "        return 1\n"
        "    def broken(self):\n"
        "        return self.memberThatDoesNotExistAnywhere(1)\n"
    ).body[0]
    offenders = [
        (node.lineno, node.attr)
        for node in ast.walk(cls)
        if isinstance(node, ast.Attribute)
        and isinstance(node.ctx, ast.Load)
        and isinstance(node.value, ast.Name)
        and node.value.id == "self"
        and node.attr not in _definedMembers(cls)
    ]
    assert offenders == [(7, "memberThatDoesNotExistAnywhere")], (
        f"扫描器未精准抓到刻意植入的悬空委托，实得 {offenders}"
    )
