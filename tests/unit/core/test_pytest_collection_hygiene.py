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
import os
import subprocess
import sys
from pathlib import Path

import pytest

#: 跨文件 AST 判据的唯一入口（Issue #148）：不自己 `rglob` + `ast.parse`。
PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests import ast_scan

_TESTS_DIR = Path(__file__).resolve().parents[2]
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_CASE_PREFIX = "test"
_CLASS_PREFIX = "Test"
_GUARD_SELF_PATTERN = "test_"

#: 本档那格真收集是**另起一个解释器**跑 `pytest --collect-only` 的：子进程要重新
#: 起 pytest、读活配置、加载插件，与父进程里已有的进程内状态无关。全局的
#: `timeout = 30` 是给"进程内一格"定的，转嫁给子进程就是拿子进程的冷启动去撞
#: 进程内的闸——2026-10-13 的 CI 上它正是这么红的（`unit-tests` 腿唯一一条失败：
#: `Failed: Timeout (>30.0s) from pytest-timeout`，而本档此前从未红过）。
#: 子进程侧另给一个显式上界，超时是**诚实失败**（TimeoutExpired 带命令与秒数）
#: 而不是被父进程的闸半路掐死、连子进程在干什么都读不到。
_COLLECT_SUBPROCESS_TIMEOUT = 120


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


def _testFilesUnder(root: Path) -> list:
    """`root` 下的测试文件清单（枚举走共享源 `ast_scan.filesUnder`，排序稳定）。

    与旧口径 `root.rglob("test_*.py")` 等价：`rglob("test_*.py")` 匹配的就是
    名字以 `test_` 开头、以 `.py` 结尾的文件。
    """
    return sorted(p for p in ast_scan.filesUnder(root)
                  if p.name.startswith("test_") and p.suffix == ".py")


def _declaredCases(path: Path, classPatterns: list) -> list:
    """列出 pytest **真的会走到名字判定**的用例名。

    pytest 不下潜函数体内定义的函数与类，故只走模块级 + 被收集类（含其嵌套类）；
    把不可达的定义算进来只会制造假阳。模块级与类方法共用同一份
    `python_functions`（pytest 侧本就如此），容器标记只影响报错措辞。

    解析走共享源的一次性入口 `ast_scan.transientTree`：本判据对每个测试文件
    **只解析一次**（不存在第二次命中），保留常驻语法树没有收益、成本却照付 ——
    实测保留型入口下 12 个消费方同进程跑，gen2 GC 合计 8.5s、单次峰值 1.26s，
    进程末存活 143 万 ast 节点（见 `tests/unit/test_ci_ast_scan_budget_guard.py`
    的 `TestOneShotScanDoesNotRetainTrees`）。
    """
    try:
        tree = ast_scan.transientTree(path)
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
    for path in _testFilesUnder(root):
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


def _emptyTestModulesUnder(root: Path) -> list:
    """`test_*.py` 却 **0 字节**：文件名进收集面，内容一条用例也不贡献。

    与本文件主题同源：都是"看起来在守，其实没跑"。`test_noTestCaseNameIsUncollectable`
    走 AST 数名字，空文件自然数出 0 条不合规 —— 数不出这个形状，所以另立一格。
    """
    return [p.relative_to(root).as_posix()
            for p in _testFilesUnder(root) if p.stat().st_size == 0]


def test_noEmptyTestModules():
    """测试根下不得留 0 字节的 `test_*.py`（`__init__.py` 不在收集名内，不受本格约束）。

    危害不是"占一行目录"：这类文件的名字通常写着某项安全/回归主题，
    于是"有这个名字"被当成"有这项覆盖"——`grep` 到文件名的人会以为那条链已被守过。
    """
    offenders = _emptyTestModulesUnder(_TESTS_DIR)

    assert not offenders, (
        "以下测试模块 0 字节，收集时以 0 用例混在通过数里（名字像覆盖，实为空白）:\n"
        + "\n".join(offenders) + "\n"
        "要么补上真断言，要么删掉——留着就是给「这项有测」留一张空票"
    )


def test_reverseProofDetectsAnEmptyTestModule(tmp_path):
    """反向自证：判定必须抓得到空模块，且不把"有内容但很少"误报成空。"""
    (tmp_path / "test_empty.py").write_bytes(b"")
    (tmp_path / "test_thin_but_real.py").write_text(
        "def test_one():\n    assert True\n", encoding="utf-8")

    found = _emptyTestModulesUnder(tmp_path)

    assert found == ["test_empty.py"], (
        "空模块判据要么空转（没抓到 test_empty.py），要么误报了非空模块：%s" % found)


#: 已登记的「零用例 test 模块」存量（2026-10-10 按**活配置**现取，逐条路径）。
#: 形态不是空白，而是**模块级语句**：`print`/裸 `assert`/`if __name__ == "__main__"` 的
#: 手工脚本留在了唯一测试根里（AGENTS.md §4「临时验证脚本即用即删，不留 tests/ 根目录」）。
#: 它们仍会在收集期被 import（副作用照跑），只是**一条用例都不产**——于是"这个名字"
#: 被当成"这项覆盖"。处置（删、迁 `tests/manual/`、或补成真用例）需逐文件裁，
#: 本表只保证两件事：**不许再长**，且**只能变短**。
#: 存量已按用户 2026-10-12 的裁定「乙 · 逐档分流」**清空**（台账 §6-133 → §6-162）：
#: 26 档去处的逐档依据见那条台账格，这里只留口径本身。
#: **空表不是"这条判据没内容了"**——它从这一天起是零容忍：任何新的
#: 「名字像用例集、实则 0 用例」的 `test_*.py` 落进唯一测试根，本档当场红。
#: 三条出路（按 AGENTS.md §4）：补成真用例、移出测试根、或作为手工配方落 `tests/manual/`
#: 且**不得**用 `test_` 前缀命名。
_ZERO_CASE_TEST_FILES_BASELINE: set = set()


def _zeroCaseTestFiles(root: Path, functionPatterns: list, classPatterns: list) -> list:
    """`root` 下**贡献 0 条可收集用例**的 `test_*.py`（按给定活口径）。"""
    found = []
    for path in _testFilesUnder(root):
        collected = [
            name for kind, name in _declaredCases(path, classPatterns)
            if kind != "类" and _matchesCollectionPattern(functionPatterns, name)
        ]
        if not collected:
            found.append(path.relative_to(root).as_posix())
    return found


def test_zeroCaseTestModulesStayOnTheRegisteredList(pytestconfig):
    """零用例清单与代码逐条对账：新增落点当场红，修好的必须从表里摘掉。"""
    functionPatterns = pytestconfig.getini("python_functions")
    classPatterns = pytestconfig.getini("python_classes")
    found = set(_zeroCaseTestFiles(_TESTS_DIR, functionPatterns, classPatterns))

    extra = sorted(found - _ZERO_CASE_TEST_FILES_BASELINE)
    assert not extra, (
        "又出现了「名字像用例集、实则 0 用例」的 test 模块：%s\n"
        "要么补成真用例，要么移出测试根（临时脚本按 §4 即用即删，或落 `tests/manual/`）"
        % extra)

    stale = sorted(_ZERO_CASE_TEST_FILES_BASELINE - found)
    assert not stale, (
        "这些存量已经不再是零用例了，却还留在表里替不存在的事背书：%s —— 摘掉它们再提交"
        % stale)


def test_reverseProofDetectsAZeroCaseModule(tmp_path):
    """反向自证：只有模块级语句的文件必须被点名，真有用例的不得误报。"""
    (tmp_path / "test_script_only.py").write_text(
        "print('manual probe')\nassert 1 + 1 == 2\n", encoding="utf-8")
    (tmp_path / "test_real.py").write_text(
        "def test_one():\n    assert True\n\n\n"
        "class TestTwo:\n    def test_inner(self):\n        assert True\n",
        encoding="utf-8",
    )

    found = _zeroCaseTestFiles(tmp_path, ["test_*", "test[A-Z]*"], ["Test*"])

    assert found == ["test_script_only.py"], (
        "零用例判据要么空转（没抓到 test_script_only.py），要么误报了真用例文件：%s" % found)




#: 已登记的「文件名收不到、内容却是用例」存量。**现表为空＝零容忍口径生效**：任何新增者当场红。
#: 表里原有两条（`language/testOutOfBoxDefaultLayer.py`、`unit/api/testRetiredGlobalLanguageDefault.py`）
#: 登记时是另一会话的在途件、当时尚未跟踪，故只署名不代改；两档此后都已入库并各自逐文件单跑全绿
#: （17 passed / 15 passed），已按本表自述的第一条出路收进 `test_` 前缀，署名进
#: `tests/unit/ci/protectedSubsetRetired.txt`。**留过期的行就是替不存在的事背书**——`stale` 那一向判据
#: 正是为这一刻准备的，摘表与改名必须同批完成。
#: 三条出路（与 `_ZERO_CASE_TEST_FILES_BASELINE` 同）：按活的 `python_files` 改名
#: （`test_` 前缀 + 驼峰其余，例：`test_sessionIdShapeAcrossReadPaths.py`）、
#: 移出唯一测试根、或作为手工配方落 `tests/manual/`。
#: 本档自己就踩过一次——新判据先写成 `testSessionIdShapeAcrossReadPaths.py`，
#: 显式给路径跑得全绿、目录跑与 CI 却一条都不收
#: （见 `test_reverseProofShowsSuchAFileSilentlyDoesNotRun`）。
_UNCOLLECTABLE_FILE_BASELINE: set = set()

#: 按设计不参与目录收集的目录（活体配方、退役存档、运行器；AGENTS.md §2 列的结构）。
_NON_COLLECTED_TEST_DIRS = ("manual", "archive", "runners")


def _bearsCases(path: Path, classPatterns: list) -> bool:
    """文件里有没有"看起来是用例"的模块级定义（函数名或类名以 test/Test 起头）。"""
    for kind, name in _declaredCases(path, classPatterns):
        if name.startswith(_CASE_PREFIX) or name.startswith(_CLASS_PREFIX):
            return True
    return False


def _uncollectableFileNames(root: Path, filePatterns: list, classPatterns: list) -> list:
    """`root` 下**内容是用例、文件名却不在活的 `python_files` 口径内**的 .py（相对路径逐条）。

    口径来自事实源（`pytestconfig.getini("python_files")`），这里不抄模式；
    `conftest.py`/`__init__.py` 不是用例容器，`tests/manual|archive/` 按设计只显式跑。
    """
    found = []
    for path in sorted(ast_scan.filesUnder(root)):
        if path.suffix != ".py" or path.name in ("conftest.py", "__init__.py"):
            continue
        # 前导下划线是"辅助件/被别的档点名跑的子进程探针"的既有记号——它不是"以为自己在跑"
        # 的那种文件。（顺带记一笔：`tests/unit/_diag_*.py` 三档已被跟踪却零引用方，
        # 属死档候选，另批裁，本档不据它放口径。）
        if path.name.startswith("_"):
            continue
        if any(part in _NON_COLLECTED_TEST_DIRS for part in path.relative_to(root).parts[:-1]):
            continue
        if _matchesCollectionPattern(filePatterns, path.name):
            continue
        if _bearsCases(path, classPatterns):
            found.append(path.relative_to(root).as_posix())
    return found


def test_noTestBearingFileHasAnUncollectableFileName(pytestconfig):
    """按**活的** `python_files` 判定：文件名收不到的用例文件不得留在测试根（存量表只减不增）。

    危害与用例名那一族同源，只是更隐蔽：`pytest tests/unit/session` 这种目录跑**不报错也不失败**，
    整份文件一条都不跑；而显式 `pytest 那份文件` 又全绿——于是写它的人、看绿的人、
    和查"这项有没有测"的人都以为它守着了。
    """
    offenders = _uncollectableFileNames(
        _TESTS_DIR, list(pytestconfig.getini("python_files")),
        list(pytestconfig.getini("python_classes")))
    unexpected = sorted(set(offenders) - _UNCOLLECTABLE_FILE_BASELINE)
    stale = sorted(_UNCOLLECTABLE_FILE_BASELINE - set(offenders))

    assert not unexpected, (
        "这些文件的文件名不在活的 python_files 口径内，内容却写着用例 ⇒ 目录跑与 CI 静默不收：%s\n"
        "改名为 `test_` 前缀（其余驼峰）、移出测试根、或落 tests/manual/ 并去掉 test_ 前缀"
        % unexpected)
    assert not stale, (
        "存量表里这几条已经不再是「文件名收不到」了，却还留在表里替不存在的事背书：%s —— 摘掉再提交"
        % stale)


@pytest.mark.timeout(_COLLECT_SUBPROCESS_TIMEOUT + 30)
def test_reverseProofShowsSuchAFileSilentlyDoesNotRun(tmp_path, pytestconfig):
    """反向自证：同一份内容，`testFoo.py` 被目录跑静默丢掉、`test_foo.py` 收得到；
    探测器必须只点名前者，且不得误报没有用例的普通模块。"""
    (tmp_path / "testFooSilentlySkipped.py").write_text(
        "def test_one():\n    assert True\n", encoding="utf-8")
    (tmp_path / "test_fooCollected.py").write_text(
        "def test_two():\n    assert True\n", encoding="utf-8")
    (tmp_path / "notesHelper.py").write_text("VALUE = 1\n", encoding="utf-8")

    found = _uncollectableFileNames(
        tmp_path, list(pytestconfig.getini("python_files")),
        list(pytestconfig.getini("python_classes")))
    assert found == ["testFooSilentlySkipped.py"], (
        "探测器要么空转（没抓到 testFooSilentlySkipped.py），要么误报了普通模块：%s" % found)

    try:
        collected = subprocess.run(
            [sys.executable, "-m", "pytest", "-c", str(_PROJECT_ROOT / "pyproject.toml"),
             "-p", "no:cacheprovider", "--collect-only", "-q", str(tmp_path)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            # 写侧同样钉 UTF-8：本机 locale 是 cp936 时，收集清单里的中文文件名会在
            # 子进程 stdout 上按 locale 编码，读侧显式 utf-8 只会拿到替换字符。
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            cwd=str(tmp_path),
            # 子进程自己也得有上界：没有它，子进程真挂住时父进程只能靠 pytest-timeout
            # 的闸把它连同证据一起杀掉（本档 2026-10-13 的 CI 红相即此）；给了它，
            # 读到的是一条点名秒数的失败，而不是一条被掐断的静默。
            timeout=_COLLECT_SUBPROCESS_TIMEOUT)
    except subprocess.TimeoutExpired as exc:
        raise AssertionError(
            "子进程真收集超过 %ss 没回来——本档的靶（`python_files` 收不到的文件名）"
            "无法自证，判据不成立：%s" % (_COLLECT_SUBPROCESS_TIMEOUT, exc)) from exc
    listing = collected.stdout
    assert "test_fooCollected.py" in listing, (
        f"真收集连合规文件都没收（退出码 {collected.returncode}）：{listing[:400]}")
    assert "testFooSilentlySkipped" not in listing, (
        "被 `python_files` 挡掉的文件其实进得来 ⇒ 本档的靶不存在，"
        "那条「文件名收不到」的判据是在为空转作证：" + listing[:400])
