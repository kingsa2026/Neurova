# -*- coding: utf-8 -*-
"""P2-7（§6-19 / AGENTS.md §3）：懒建单例必须 DCL + RLock。

判据取**行为**，不取代码形态：让 N 个线程在同一时刻进入同一个 `get_xxx()`，
构造体用 barrier 强制它们真的重叠在一起——无锁形态下每个线程都会穿过
`if _x is None` 各建一份（先建的那份带着已注册的回调/已打开的连接被静默丢掉），
收口后必须只构造一次、且所有线程拿到同一个对象。

另两条钉的是"唯一实现"本身：缓存名写错时必须当场拒绝（写错=每次重建，正是
本模块要消灭的故障，不能留到运行时静默退化）；既有 `mod._x = None` 复位路径必须
继续成立（仓内测试与关停钩子都在用它，收口不许换掉存储位置）。
"""

import importlib
import sys
import threading
from pathlib import Path
from typing import List

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# (模块, 类名, getter, 缓存全局名)——三处都是构造无外部副作用的真站点
RACE_SITES = [
    ("neurova.collaboration.neurflow.dag", "DAGValidator", "get_dag_validator", "_dag_validator"),
    ("neurova.agent.protocols.capability_discovery", "CapabilityDiscovery", "get_capability_discovery", "_global_discovery"),
    ("neurova.agent.protocols.dead_letter_queue", "DeadLetterQueue", "get_dead_letter_queue", "_global_dlq"),
]

THREADS = 8

# 只降不升的棘轮基线（§6-19 后续批次清到底时，连同这条一起删）
NON_REENTRANT_DCL_BASELINE = 165


def _raceTheGetter(modulePath: str, clsAttr: str, getterName: str, globalName: str):
    """返回 (构造次数, 各线程拿到的对象列表)。barrier 保证构造真的重叠。"""
    module = importlib.import_module(modulePath)
    realClass = getattr(module, clsAttr)
    getter = getattr(module, getterName)
    priorValue = getattr(module, globalName)

    constructions: List[object] = []
    gate = threading.Barrier(THREADS)

    class Traced(realClass):
        def __init__(self, *args, **kwargs):
            try:
                gate.wait(timeout=1.0)
            except threading.BrokenBarrierError:
                pass  # 只有一条线程进来（=已收口）时等不到别人，照常构造
            super().__init__(*args, **kwargs)
            constructions.append(self)

    setattr(module, clsAttr, Traced)
    setattr(module, globalName, None)
    results: List[object] = []
    resultsLock = threading.Lock()
    ready = threading.Barrier(THREADS)

    def worker():
        ready.wait(timeout=1.0)
        value = getter()
        with resultsLock:
            results.append(value)

    try:
        threads = [threading.Thread(target=worker) for _ in range(THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)
        assert len(results) == THREADS, f"线程没跑齐：{len(results)}"
        return len(constructions), results
    finally:
        setattr(module, clsAttr, realClass)
        setattr(module, globalName, priorValue)


class TestLazySingletonRaceConstructsOnce:
    @pytest.mark.parametrize(
        "modulePath,clsAttr,getterName,globalName",
        RACE_SITES,
        ids=[s[2] for s in RACE_SITES],
    )
    def testConcurrentGettersBuildExactlyOneInstance(
        self, modulePath, clsAttr, getterName, globalName
    ):
        constructions, results = _raceTheGetter(modulePath, clsAttr, getterName, globalName)

        assert constructions == 1, (
            f"{getterName}() 在 {THREADS} 线程并发下构造了 {constructions} 次——"
            "判空没有双检锁护住，多余的那几份会被后写的覆盖，先建的连同其状态被静默丢弃"
        )
        assert len({id(o) for o in results}) == 1, (
            "并发调用者拿到了不同的对象：单例语义已破，各自注册的回调落在不同实例上"
        )


def _lazySingletonViolations(source: str, moduleName: str):
    """扫一段源码，返回"懒建单例没有双检锁"的命中点。

    两种形态都算：① 模块全局 `if G is None: G = ...`（既没用 lazySingleton 也没进 with 锁）；
    ② `cls._instance` 同形。判的是代码形态里**缺哪一环**，不是数字符——
    数字符的守卫会被 `if not G:` / `try/except` 之类换皮绕过。
    """
    import ast as _ast

    tree = _ast.parse(source)
    modGlobals = {
        t.id for n in tree.body if isinstance(n, _ast.Assign) for t in n.targets if isinstance(t, _ast.Name)
    } | {
        n.target.id for n in tree.body
        if isinstance(n, _ast.AnnAssign) and isinstance(n.target, _ast.Name)
    }
    hits = []
    for fn in [n for n in _ast.walk(tree)
               if isinstance(n, (_ast.FunctionDef, _ast.AsyncFunctionDef))]:
        declared = set()
        for st in fn.body:
            if isinstance(st, _ast.Global):
                declared |= set(st.names)
        scope = modGlobals | declared
        tested, assigned = set(), set()
        for node in _ast.walk(fn):
            if (isinstance(node, _ast.If) and isinstance(node.test, _ast.Compare)
                    and len(node.test.ops) == 1 and isinstance(node.test.ops[0], _ast.Is)
                    and isinstance(node.test.comparators[0], _ast.Constant)
                    and node.test.comparators[0].value is None):
                tested |= {x.id for x in _ast.walk(node.test.left) if isinstance(x, _ast.Name)}
            if isinstance(node, (_ast.Assign, _ast.AnnAssign)):
                tg = node.targets if isinstance(node, _ast.Assign) else [node.target]
                for t in tg:
                    if isinstance(t, _ast.Name):
                        assigned.add(t.id)
        lazy = (tested & assigned) & scope
        if not lazy:
            continue
        if any(isinstance(s, (_ast.With, _ast.AsyncWith)) for s in _ast.walk(fn)):
            continue  # 锁在内（手写 DCL 允许）
        decorated = any(
            isinstance(d, _ast.Call) and getattr(d.func, "id", "") == "lazySingleton"
            for d in fn.decorator_list
        )
        if not decorated:
            hits.append(f"{moduleName}::{fn.name} 缓存名 {sorted(lazy)}")
    # cls._instance 形态
    for cls in [n for n in _ast.walk(tree) if isinstance(n, _ast.ClassDef)]:
        for fn in [m for m in cls.body if isinstance(m, (_ast.FunctionDef, _ast.AsyncFunctionDef))]:
            tested, assigned = set(), set()
            for node in _ast.walk(fn):
                if (isinstance(node, _ast.If) and isinstance(node.test, _ast.Compare)
                        and len(node.test.ops) == 1 and isinstance(node.test.ops[0], _ast.Is)
                        and isinstance(node.test.comparators[0], _ast.Constant)
                        and node.test.comparators[0].value is None):
                    tested |= {
                        _ast.unparse(x) for x in _ast.walk(node.test.left) if isinstance(x, _ast.Attribute)
                    }
                if isinstance(node, _ast.Assign):
                    for t in node.targets:
                        if isinstance(t, _ast.Attribute):
                            assigned.add(_ast.unparse(t))
            if (tested & assigned) & {"cls._instance"} and not any(
                isinstance(s, _ast.With) for s in _ast.walk(fn)
            ):
                hits.append(f"{moduleName}::{cls.name}.{fn.name} 的 cls._instance 无锁")
    return hits


class TestNoLockFreeLazySingletonRemains:
    """常驻守卫：全仓不得再有"判空即建却不带锁"的懒建单例。"""

    def testWholePackageHasNoLockFreeLazySingleton(self):
        root = PROJECT_ROOT / "neurova"
        violations = []
        for path in sorted(root.rglob("*.py")):
            try:
                violations += _lazySingletonViolations(path.read_text(encoding="utf-8"), path.stem)
            except SyntaxError:
                continue
        assert not violations, "以下懒建单例没有双检锁（并发下会各建一份）：\n" + "\n".join(violations)

    def testGuardActuallyCatchesBothShapes(self):
        """自证判据咬得住：注入两种违规形态，必须都被点名。"""
        globalShape = (
            "_thing = None\n\n"
            "def get_thing():\n"
            "    global _thing\n"
            "    if _thing is None:\n"
            "        _thing = object()\n"
            "    return _thing\n"
        )
        clsShape = (
            "class Holder:\n"
            "    _instance = None\n\n"
            "    @classmethod\n"
            "    def get_instance(cls):\n"
            "        if cls._instance is None:\n"
            "            cls._instance = cls()\n"
            "        return cls._instance\n"
        )
        assert _lazySingletonViolations(globalShape, "shapeA"), "模块全局形态的裸判空没被逮住"
        assert _lazySingletonViolations(clsShape, "shapeB"), "cls._instance 形态的裸判空没被逮住"
        # 收口后的两种正形态都不该被报
        okGlobal = (
            "_thing = None\n\n"
            "@lazySingleton('_thing')\n"
            "def get_thing():\n"
            "    return object()\n"
        )
        okCls = (
            "import threading\n\n"
            "class Holder:\n"
            "    _instance = None\n"
            "    _instanceLock = threading.RLock()\n\n"
            "    @classmethod\n"
            "    def get_instance(cls):\n"
            "        if cls._instance is None:\n"
            "            with cls._instanceLock:\n"
            "                if cls._instance is None:\n"
            "                    cls._instance = cls()\n"
            "        return cls._instance\n"
        )
        assert not _lazySingletonViolations(okGlobal, "okA")
        assert not _lazySingletonViolations(okCls, "okB")

    def testNonReentrantSingletonLocksDoNotGrow(self):
        """AGENTS.md §3 要 RLock；仓内另有 165 处 DCL 用的是非可重入 `Lock`（本批实测计数）。

        这一格不在本批扫荡（改法是逐个把 `Lock()` 换成 `RLock()`，且只有"构造期回落
        到同一入口"才是真死锁，其余只是形态不合），先钉成**只降不升**的棘轮：
        新增一处即红；等 §6-19 后续批次把它清到底，连同这条基线一起删。
        """
        import ast as _ast

        root = PROJECT_ROOT / "neurova"
        count = 0
        for path in sorted(root.rglob("*.py")):
            try:
                tree = _ast.parse(path.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                continue
            lockKinds = {}
            for node in _ast.walk(tree):
                if isinstance(node, (_ast.Assign, _ast.AnnAssign)):
                    call = node.value
                    if isinstance(call, _ast.Call):
                        fname = call.func.attr if isinstance(call.func, _ast.Attribute) else getattr(call.func, "id", "")
                        tg = node.targets if isinstance(node, _ast.Assign) else [node.target]
                        for t in tg:
                            if isinstance(t, _ast.Name):
                                lockKinds[t.id] = fname
            for fn in [n for n in _ast.walk(tree)
                       if isinstance(n, (_ast.FunctionDef, _ast.AsyncFunctionDef))]:
                for w in [s for s in _ast.walk(fn) if isinstance(s, (_ast.With, _ast.AsyncWith))]:
                    innerNone = any(
                        isinstance(x.test, _ast.Compare) and len(x.test.ops) == 1
                        and isinstance(x.test.ops[0], _ast.Is)
                        and isinstance(x.test.comparators[0], _ast.Constant)
                        and x.test.comparators[0].value is None
                        for st in w.body for x in _ast.walk(st) if isinstance(x, _ast.If)
                    )
                    if not innerNone:
                        continue
                    names = [
                        it.context_expr.id if isinstance(it.context_expr, _ast.Name)
                        else it.context_expr.attr if isinstance(it.context_expr, _ast.Attribute) else ""
                        for it in w.items
                    ]
                    if any(lockKinds.get(nm) == "Lock" for nm in names):
                        count += 1
        assert count <= NON_REENTRANT_DCL_BASELINE, (
            f"DCL 用非可重入 Lock 的落点从基线 {NON_REENTRANT_DCL_BASELINE} 涨到 {count}"
            "——新单例请用 core.lazy_singleton.lazySingleton，别再加一把 Lock()"
        )
