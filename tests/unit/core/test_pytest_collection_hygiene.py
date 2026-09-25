# -*- coding: utf-8 -*-
"""pytest 收集卫生守卫（Issue #81 复核批）。

`def testFoo`（驼峰）、`def test`（裸名）、`class Test`（裸名）是同一条规则的三种写法：
名字**看起来是用例**，pytest 却收不到它 —— 既不报错也不失败，整份文件静默不跑。
工单 003 期间真实踩到（13 个用例 collected 0 items）。

事实源只有一处：**活的 pytest 配置**（`pyproject.toml` 的 `python_functions` /
`python_classes`）。本文件按 `pytestconfig.getini()` 读它，不在这里抄一份模式 ——
抄一份就是第二份事实源（教义第 6 条），配置改了守卫判的还是旧口径。
本文件此前的版本正是这么坏的：它把 `test[A-Z]*` 当成"收不到驼峰"，于是 15 个
驼峰用例被误报；而 pytest 的匹配语义是「前缀 或 glob」，`test[A-Z]*` 收得到
`def testFoo`。误报与漏报同一根因 —— 判据不在事实源上。

判定语义由 `test_matcherAgreesWithRealCollection` 用**真收集**反证，
守卫非空转由 `test_reverseProofDetectsAnUncollectableName` 反证。
"""

from __future__ import annotations

import ast
import fnmatch
import subprocess
import sys
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parents[2]
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_CASE_PREFIX = "test"
_CLASS_PREFIX = "Test"
_GUARD_SELF_PATTERN = "test_"


def _matchesCollectionPattern(patterns: list, name: str) -> bool:
    """与 pytest 同口径：前缀命中，或含通配符的模式按 glob 命中。

    对齐 `_pytest.python.PyCollector._matches_prefix_or_glob_option`：先试
    `name.startswith(option)`，再对含 `*?[` 的选项试 `fnmatch`。两处顺序与短路
    语义相同，故对任一 name 的判定与 pytest 逐字一致；一致性由真收集反证。
    """
    for pattern in patterns:
        if name.startswith(pattern):
            return True
        if any(char in pattern for char in "*?[") and fnmatch.fnmatch(name, pattern):
            return True
    return False


def _isUnittestCase(node: ast.ClassDef) -> bool:
    """继承 `unittest.TestCase` 的类由 unittest 收集器接管，不受 python_classes 约束。"""
    for base in node.bases:
        if isinstance(base, ast.Attribute) and base.attr == "TestCase":
            return True
        if isinstance(base, ast.Name) and base.id == "TestCase":
            return True
    return False


def _isCollectedClass(node: ast.ClassDef, classPatterns: list) -> bool:
    return _matchesCollectionPattern(classPatterns, node.name) or _isUnittestCase(node)


def _classMembers(node: ast.ClassDef, classPatterns: list) -> list:
    declared = []
    for child in node.body:
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            declared.append(("类方法", child.name))
        elif isinstance(child, ast.ClassDef):
            declared.append(("类", child.name))
            if _isCollectedClass(child, classPatterns):
                declared.extend(_classMembers(child, classPatterns))
    return declared


def _declaredCases(path: Path, classPatterns: list) -> list:
    """列出 pytest **真的会走到名字判定**的用例名。

    pytest 不下潜函数体内定义的函数与类，故只走模块级 + 被收集类（含其嵌套类）；
    把不可达的定义算进来只会制造假阳。模块级与类方法共用同一份
    `python_functions`（pytest 侧本就如此），容器标记只影响报错措辞。
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
    except SyntaxError:
        return []
    declared = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            declared.append(("模块级函数", node.name))
        elif isinstance(node, ast.ClassDef):
            declared.append(("类", node.name))
            if _isCollectedClass(node, classPatterns):
                declared.extend(_classMembers(node, classPatterns))
    return declared


def _uncollectableIn(root: Path, functionPatterns: list, classPatterns: list) -> list:
    """`root` 下名字以 test / Test 开头、但按给定模式收不到的落点（逐条点名）。"""
    found = []
    for path in sorted(root.rglob("test_*.py")):
        rel = path.relative_to(root)
        for kind, name in _declaredCases(path, classPatterns):
            if kind == "类":
                if name.startswith(_CLASS_PREFIX) and not _matchesCollectionPattern(
                    classPatterns, name
                ):
                    found.append("%s → 类 %s（收集规则 %s 收不到）" % (rel, name, classPatterns))
            elif name.startswith(_CASE_PREFIX) and not _matchesCollectionPattern(
                functionPatterns, name
            ):
                found.append(
                    "%s → %s %s（收集规则 %s 收不到，会静默不跑）"
                    % (rel, kind, name, functionPatterns)
                )
    return found


def _guardSelfCaseNames() -> list:
    """本守卫自己的用例名不得依赖驼峰模式。

    理由不是审美：守卫是锁住收集规则的那条线。若它自己要靠 `test[A-Z]*` 才被收集，
    那么有人收窄该模式时，守卫会**和被它守护的文件一起**静默消失 —— 没有任何一处会响亮。
    """
    text = Path(__file__).read_text(encoding="utf-8")
    found = []
    for node in ast.parse(text).body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name.startswith(_CASE_PREFIX) and not _matchesCollectionPattern(
            [_GUARD_SELF_PATTERN], node.name
        ):
            found.append(node.name)
    return found


def test_noTestCaseNameIsUncollectable(pytestconfig):
    """按**活配置**判定：看起来像用例、活配置却收不到的名字逐条点名。

    点名即须处置（改名，或改配置并说明）——"以 test 开头却不是用例"本身就是
    应当消失的形状：pytest 默认的前缀口径会把它当用例收走，得到的是一条恒真的假绿。
    """
    functionPatterns = pytestconfig.getini("python_functions")
    classPatterns = pytestconfig.getini("python_classes")
    offenders = _uncollectableIn(_TESTS_DIR, functionPatterns, classPatterns)

    assert not offenders, (
        "以下名字不会被 pytest 收集，会静默不跑:\n" + "\n".join(offenders)
    )


def test_guardItselfUsesNamesThatSurviveANarrowedRule():
    offenders = _guardSelfCaseNames()
    assert not offenders, (
        "守卫自身用例名不得依赖驼峰模式 —— 否则收集规则一收窄，"
        "守卫与被守护的文件会一起静默消失：%s" % offenders
    )


def test_reverseProofDetectsAnUncollectableName(tmp_path):
    """反向自证：判定不得空转 —— 收窄规则时必须真的报出来，合规的不得误报。

    两臂都喂显式模式：本判定是参数化的纯函数，反证它"会报"就该由输入构造，
    不能靠改本仓 pyproject（那会让这条反证自己也依赖一份被改过的配置）。
    """
    fixture = tmp_path / "test_fixture.py"
    fixture.write_text(
        "def test():\n    return {'status': 'ok'}\n\n\n"
        "def test_snake():\n    assert True\n\n\n"
        "class TestKept:\n"
        "    def testMethodCamel(self):\n        assert True\n",
        encoding="utf-8",
    )

    narrowedFunctions = _uncollectableIn(tmp_path, ["test_*"], ["Test*"])
    assert any("类方法 testMethodCamel（" in item for item in narrowedFunctions), (
        "收窄函数规则后驼峰用例未被点名，守卫已空转：%s" % narrowedFunctions
    )

    narrowedClasses = _uncollectableIn(tmp_path, ["test_*", "test[A-Z]*"], ["TestCase*"])
    assert any("类 TestKept（" in item for item in narrowedClasses), (
        "收窄类规则后以 Test 开头的类未被点名，守卫已空转：%s" % narrowedClasses
    )

    livePatterns = _uncollectableIn(tmp_path, ["test_*", "test[A-Z]*"], ["Test*"])
    assert not any(
        "test_snake" in item or "testMethodCamel" in item or "TestKept" in item
        for item in livePatterns
    ), "合规用例被误报（误报即失真）：%s" % livePatterns
    assert any("模块级函数 test（" in item for item in livePatterns), (
        "裸名 def test 在活口径下未被点名：%s" % livePatterns
    )
