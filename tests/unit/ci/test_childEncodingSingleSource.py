# -*- coding: utf-8 -*-
"""子进程写侧编码 helper 全仓只准一处实装（§6-490；教义第 6/7 条：先比后合，其余退役）。

现读取证：同一份 `_utf8ChildEnv()` 在仓内有**三处逐字相同**的定义——
`neurova/web_reach/reach.py:53`、`scripts/ci_static_gate.py:97`、
`scripts/ci/protected_subset_nightly.py:46`，函数体与 docstring 全等 ⇒ 合并是**零行为差异**的纯退役。
选定落点在生产侧 `neurova/core/text_encoding.py`：scripts 可以 import 生产包，反向（生产 import
`scripts/`）是方向错。

四件事缺一不可：

1. 数实装处数——`neurova/` + `scripts/` 跟踪面只准一处，且在选定模块；
2. 三处旧 caller 不得再自带同名定义；
3. 接线格——caller 的 `env=` 实参必须真的取自单源（只删定义不接线，等于把钉拆了没补）；
4. 行为格——真调 `utf8ChildEnv()`：键钉成 utf-8、父环境照继承。只数定义不验行为，
   「import 得到却用错」这一形就没人管。

另有一条反向钉（第 5 格）咬住棘轮档那份登记名单不许成为空文：名单里的每个名字都得能在
生产面找到真带键的实装。判据认单源形态而不验单源存在，就是拿一个名字换一处假绿。
"""

import ast
import importlib
from pathlib import Path

import pytest

from tests.ast_scan import REPO_ROOT, parseSource, relativeToRepo, sourceCode, trackedPyPaths

SINGLE_SOURCE_REL = "neurova/core/text_encoding.py"
SINGLE_SOURCE_FUNC = "utf8ChildEnv"

#: 现状的三处平行实装（§6-490 开工前现读；退役后它们只准留调用点）。
OLD_DEFINERS = (
    "neurova/web_reach/reach.py",
    "scripts/ci_static_gate.py",
    "scripts/ci/protected_subset_nightly.py",
)

#: 棘轮档里那份「跨文件单源 helper」登记名单的落点（名单唯一出处，本档只读不另抄一份）。
RATCHET_FILE_REL = "tests/unit/ci/test_subprocessTextEncodingRatchet.py"


def _pinnedReturners(relPath: str) -> list:
    """该文件里「返回带 PYTHONIOENCODING 键的 dict」的函数：[(函数名, 行号)]。"""
    tree = parseSource(sourceCode(REPO_ROOT / relPath), filename=relPath)
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for inner in ast.walk(node):
            if not isinstance(inner, ast.Return) or inner.value is None:
                continue
            value = inner.value
            if isinstance(value, ast.Dict) and any(
                    isinstance(k, ast.Constant) and k.value == "PYTHONIOENCODING"
                    for k in value.keys):
                found.append((node.name, node.lineno))
                break
            if (isinstance(value, ast.Call) and isinstance(value.func, ast.Name)
                    and value.func.id == "dict"
                    and any(kw.arg == "PYTHONIOENCODING" for kw in value.keywords)):
                found.append((node.name, node.lineno))
                break
    return found


def _allPinnedReturners() -> list:
    rows = []
    for rel in trackedPyPaths("neurova", "scripts"):
        for name, line in _pinnedReturners(rel):
            rows.append((rel, name, line))
    return rows


def _loadSingleSource():
    try:
        return importlib.import_module("neurova.core.text_encoding")
    except ModuleNotFoundError as exc:      # 红灯阶段：不许把缺模块读成 collection error
        raise AssertionError(
            "单源模块 neurova/core/text_encoding.py 不存在（%s）——"
            "三份逐字相同的 `_utf8ChildEnv()` 还没收口" % exc) from None


class TestChildEncodingSingleSource:
    def test_exactlyOnePinnedHelperImplementationInRepo(self):
        """实装处数判据：全仓（生产面＋基建面）只准一处，且就在选定模块。"""
        rows = _allPinnedReturners()
        assert rows, "扫描面里一个带键 helper 都没认出来——判据已空转，先修识别器"
        offenders = sorted({(rel, name) for rel, name, _line in rows})
        assert offenders == [(SINGLE_SOURCE_REL, SINGLE_SOURCE_FUNC)], (
            "带 PYTHONIOENCODING 键的子环境 helper 有 %d 份实装：%s——"
            "教义第 6 条要求一处定义；三份逐字相同的实现里，改一份就留下两份说谎"
            % (len(offenders), offenders))

    def test_retiredCallersNoLongerDefineTheHelperThemselves(self):
        """三处旧 caller 必须退役自己的定义（留下就是第二、第三事实源）。"""
        stillDefining = [rel for rel in OLD_DEFINERS if _pinnedReturners(rel)]
        assert stillDefining == [], (
            "这些档还自带子环境 helper 定义：%s——按 §6-490 应删净并改指 %s"
            % (stillDefining, SINGLE_SOURCE_REL))

    def test_callersTakeEnvFromTheSingleSource(self):
        """接线判据：caller 的 `env=` 实参得真是单源那次调用——只删定义不接线等于把钉拆了。"""
        for rel in OLD_DEFINERS:
            tree = parseSource(sourceCode(REPO_ROOT / rel), filename=rel)
            pinnedFromSingleSource = False
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                for kw in node.keywords:
                    if kw.arg != "env" or not isinstance(kw.value, ast.Call):
                        continue
                    func = kw.value.func
                    fname = getattr(func, "id", None) or getattr(func, "attr", None)
                    if fname == SINGLE_SOURCE_FUNC:
                        pinnedFromSingleSource = True
            assert pinnedFromSingleSource, (
                "%s 里没有一处 `env=` 实参是从单源 %s() 取的——"
                "退役旧定义却没接线，那一处调用在运行时又回到本机码页"
                % (rel, SINGLE_SOURCE_FUNC))

    def test_singleSourcePinsTheChildWriteEndAndInheritsParentEnv(self, monkeypatch):
        """行为判据：真调它，键钉成 utf-8 且父环境照继承（父端读＋子端写两头都要在）。"""
        mod = _loadSingleSource()
        monkeypatch.setenv("NEUROVA_PIN_PROBE_PARENT", "carried-through")
        child = mod.utf8ChildEnv()
        assert child.get("PYTHONIOENCODING") == "utf-8", (
            "单源没钉子进程写侧（实得 %r）——父端按 utf-8 解、子端按 cp936 写就是半修（§6-225 那族）"
            % child.get("PYTHONIOENCODING"))
        assert child.get("NEUROVA_PIN_PROBE_PARENT") == "carried-through", (
            "单源把父环境丢了——用 {**os.environ, ...} 之外的构造形会静默清空子进程环境")

    def test_ratchetRegistryNamesHaveRealImplementations(self):
        """反向钉：棘轮档那份登记名单不许是空文——每个名字都要在生产面有真带键的实装。"""
        tree = parseSource(sourceCode(REPO_ROOT / RATCHET_FILE_REL), filename=RATCHET_FILE_REL)
        registered = None
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                    isinstance(t, ast.Name) and t.id == "SINGLE_SOURCE_CHILD_ENV_NAMES"
                    for t in node.targets):
                registered = {e.value for e in ast.walk(node.value)
                              if isinstance(e, ast.Constant) and isinstance(e.value, str)}
        assert registered is not None, (
            "%s 里没有模块级 `SINGLE_SOURCE_CHILD_ENV_NAMES`——判据跟一跳 import 靠的就是这份名单，"
            "没有它，收口单源的那一刻三处已修站点会被读成三处新半修" % RATCHET_FILE_REL)
        assert registered, "登记名单是空集合——空名单等于判据不跟 import，红会在下一次收口时才现形"
        implementors = {name for _rel, name, _line in _allPinnedReturners()}
        missing = sorted(registered - implementors)
        assert missing == [], (
            "名单里这些名字在生产面没有「返回带键 dict」的实装：%s——登记与实装脱钩，"
            "判据就会放行一个不存在的 helper 名" % missing)
