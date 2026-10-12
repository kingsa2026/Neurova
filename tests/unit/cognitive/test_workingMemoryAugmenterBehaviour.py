# -*- coding: utf-8 -*-
"""`WorkingMemoryAugmenter` 这个类本身的行为（台账 §6-133 分流里判「补」的那一档）。

## 为什么这一格是真缺口，不是顺手加

`tests/unit/cognitive/test_working_memory_comprehensive.py` 是 §6-133 点名的 26 个
「名字像覆盖、实则 0 用例」文件之一：docstring 写着"全面单元测试"，正文只剩
`try: import … / pytestmark = skipif(not _HAS_WORKING_MEMORY, reason="…API changed…")`。
实测那条 import **今天就能成功**（`.venv/Scripts/python.exe -c "import …"` 回 OK）
⇒ `skipif` 恒假、模块收集 0 条 ⇒ 它既不跳、也不跑，只留下"这个名字"。

复算替代面时找到的只有 mock 版：`tests/test_memory/test_mem_core.py:112,147` 与
`tests/unit/core/test_mem_core_bugfix.py:184` 全是 `@patch(...WorkingMemoryAugmenter)`
——**把主体换成替身**去断装配。于是这个类自己那三条契约（容量上界、淘汰顺序、
cache-miss 与 cached-None 的分别）在仓内一条判据都没有，而它就在生产路上
（`neurova/mem_core.py:725` 实例化、`neurova/memory/__init__.py:52,180` 导出）。

淘汰顺序与 `_MISSING` 那两条正是文件头注释自陈的 Bug 1 / Bug 2 修复
（`:40-41` 锁、`:64-66` sentinel）——修过却没有判据钉住，就是"下次有人改回去没人知道"。
"""

from __future__ import annotations

import ast
import threading
import time
from pathlib import Path

import pytest

from neurova.cognitive_layers.memory_layer.working_memory import (
    WorkingMemoryAugmenter,
    _MISSING,
)


def _pastTick():
    """等 `time.time()` 真正前进一格再返回。

    淘汰的二级键与 `get_recent` 的排序都吃 `time.time()`，而本机这个读数的粒度不是 1µs
    ——同一毫秒内写入的两条会**并列**，`sorted` 于是按字典插入序决定，测试就会跟着
    机器负载变红（§6-96 记过的"按实测时钟粒度取样"同一条坑）。
    与其猜一个 sleep 时长，不如直接等读数变化：这格慢一点，但在任何机器上都是确定的。
    """
    base = time.time()
    deadline = time.monotonic() + 1.0
    while time.time() <= base:
        if time.monotonic() > deadline:
            pytest.fail("本机 time.time() 在一秒内没有前进，无法构造可判定的访问顺序")


class TestCapacityIsABound:
    def test_sizeNeverExceedsCapacity(self):
        wm = WorkingMemoryAugmenter(capacity=5)

        for i in range(40):
            wm.add(f"k{i}", i)

        assert wm.get_stats()["size"] == 5, (
            "写满之后还在长——容量只是个装饰，工作记忆会随对话无界增长")

    def test_statsKeysAreTheRealOnes(self):
        """按**真产物键集合**核，不按想象写（§6-145 那格教训：夹具发明键名会全绿而面板空着）。"""
        wm = WorkingMemoryAugmenter(capacity=3)

        assert set(wm.get_stats()) == {"size", "capacity"}
        assert wm.get_stats()["capacity"] == 3

    def test_zeroCapacityDoesNotCrash(self):
        wm = WorkingMemoryAugmenter(capacity=0)

        for i in range(3):
            wm.add(f"k{i}", i)

        assert wm.get_stats()["size"] <= 1, (
            "capacity=0 时淘汰逻辑没接住：要么崩，要么变成无界")

    def testConfigMaxItemsOverridesThePositionalCapacity(self):
        """`config` 分支（`working_memory.py:45-48`）现在就没人断过；写反了就悄悄回到默认值。"""
        fromConfig = WorkingMemoryAugmenter(capacity=100, config={"max_items": 4})

        assert fromConfig.capacity == 4

        for i in range(10):
            fromConfig.add(f"k{i}", i)
        assert fromConfig.get_stats()["size"] == 4

    def testConfigWithoutMaxItemsKeepsThePositionalCapacity(self):
        wm = WorkingMemoryAugmenter(capacity=7, config={"other": 1})

        assert wm.capacity == 7, "config 存在但没带 `max_items` 时不许把容量抹成默认值"


class TestEvictionOrder:
    def test_lowestImportanceGoesFirst(self):
        wm = WorkingMemoryAugmenter(capacity=2)
        wm.add("keep", "高", importance=0.9)
        wm.add("drop", "低", importance=0.1)

        wm.add("third", "新", importance=0.5)

        assert wm.get("drop") is _MISSING, (
            "淘汰没按重要性取最小者——低权重内容反而长期占着工作记忆")
        assert wm.get("keep") == "高"

    def test_sameImportanceEvictsTheStalestAccess(self):
        """同权重时按 `last_accessed` 淘汰最旧的（`:89-91` 那个二级键）。"""
        wm = WorkingMemoryAugmenter(capacity=2)
        wm.add("old", "旧")
        _pastTick()
        wm.add("new", "新")
        _pastTick()
        assert wm.get("old") == "旧"          # touch 之后 old 比 new 新
        _pastTick()
        wm.add("third", "第三")

        assert wm.get("new") is _MISSING, "同权重下淘汰了刚被访问过的那条，等于惩罚被读到"
        assert wm.get("old") == "旧"

    def test_evictOnEmptyDoesNotRaise(self):
        wm = WorkingMemoryAugmenter(capacity=1)
        wm._evict()

        assert wm.get_stats()["size"] == 0


class TestMissIsNotNone:
    def test_absentKeyReturnsTheSentinelNotNone(self):
        """Bug 2 的实质：`None` 是合法内容，不能同时当"没命中"用。"""
        wm = WorkingMemoryAugmenter(capacity=3)

        assert wm.get("nope") is _MISSING

    def test_storedNoneIsReadableAsNone(self):
        wm = WorkingMemoryAugmenter(capacity=3)
        wm.add("nul", None)

        assert wm.get("nul") is None, (
            "存了 None 却读成 miss——调用方 `is _MISSING` 判错，会把这条当成没缓存过而重算")

    def test_getTouchesAccessCountAndTime(self):
        wm = WorkingMemoryAugmenter(capacity=3)
        wm.add("a", "x")
        before = wm._items["a"].last_accessed

        wm.get("a")

        assert wm._items["a"].access_count == 1
        assert wm._items["a"].last_accessed >= before

    def test_removeReportsWhetherSomethingWentAway(self):
        wm = WorkingMemoryAugmenter(capacity=3)
        wm.add("a", "x")

        assert wm.remove("a") is True
        assert wm.remove("a") is False
        assert wm.get("a") is _MISSING

    def test_clearEmptiesAndKeepsCapacity(self):
        wm = WorkingMemoryAugmenter(capacity=4)
        for i in range(4):
            wm.add(f"k{i}", i)

        wm.clear()

        assert wm.get_stats() == {"size": 0, "capacity": 4}


class TestRecentWindow:
    def test_getRecentIsNewestFirstAndHonoursLimit(self):
        wm = WorkingMemoryAugmenter(capacity=5)
        for i in range(3):
            wm.add(f"k{i}", i)
            _pastTick()          # 真时间戳：不许把顺序断成插入序的巧合

        recent = wm.get_recent(limit=2)

        assert recent == [2, 1], recent

    def test_aReadBumpsTheItemIntoTheRecentWindow(self):
        """`get` 会 touch（`:71`），所以刚被读到的那条应排到最前——这是"工作记忆跟住当前注意力"的读数。"""
        wm = WorkingMemoryAugmenter(capacity=5)
        wm.add("a", "A")
        _pastTick()
        wm.add("b", "B")
        _pastTick()

        wm.get("a")

        assert wm.get_recent(limit=1) == ["A"], "读过的条目没进最前：touch 只更新了字段，没影响取用序"


class TestLockIsReentrantAndHoldsUnderThreads:
    def test_addInsideEvictPathDoesNotDeadlock(self):
        """`add` → `_evict` 是同一线程的重入链（`:40-41` 写明用 RLock 的原因）。

        换成普通 Lock 这里会**卡死**而不是报错——本仓全局 timeout 30s 会把它杀成挂起，
        所以这格带一个看门狗：跑不完就红，而不是让整档跟着挂。
        """
        wm = WorkingMemoryAugmenter(capacity=1)
        done = threading.Event()

        def work():
            for i in range(200):
                wm.add(f"k{i}", i)
            done.set()

        t = threading.Thread(target=work, daemon=True)
        t.start()
        assert done.wait(timeout=20), "重入链上死锁了（RLock 被换成 Lock 的形态）"
        t.join(timeout=1)

    def testConcurrentAddsStayWithinCapacity(self):
        """共享 `_items` 有锁（Bug 1）：并发写不许把上界冲破，也不许丢计数。"""
        wm = WorkingMemoryAugmenter(capacity=20)
        barrier = threading.Barrier(4)

        def work(worker: int):
            barrier.wait()
            for i in range(50):
                wm.add(f"w{worker}-{i}", i)

        threads = [threading.Thread(target=work, args=(w,), daemon=True) for w in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=20)

        size = wm.get_stats()["size"]
        assert size == 20, f"并发后 size={size}，期望恰好等于上界 20（冲破＝锁没护住；不足＝写丢了）"


class TestTheShellsClaimIsNowBacked:
    """反空转：这一档必须真的在测那个类，而不是测一个自洽的替身。"""

    def test_thisFileUsesNoTestDoubles(self):
        """本档一旦引入替身，就退回 `test_mem_core*.py` 那种"断装配不断行为"的形态。

        按 **AST 的调用/装饰器形态**判，不按"文件里有没有这个词"判——上一版写的是
        源码文本包含检查，结果它把自己的断言字符串也当成了替身使用，恒红。
        """
        tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
        doubles = {"MagicMock", "Mock", "AsyncMock", "patch", "create_autospec"}
        used = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                name = getattr(func, "id", None) or getattr(func, "attr", None)
                if name in doubles:
                    used.add("%s@%s" % (name, node.lineno))
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for dec in node.decorator_list:
                    decName = getattr(dec, "id", None) or getattr(dec, "attr", None) or (
                        getattr(getattr(dec, "func", None), "attr", None))
                    if decName in doubles:
                        used.add("@%s@%s" % (decName, node.lineno))
        assert not used, "本档用了测试替身：%s" % sorted(used)

    def test_classUnderTestIsTheOneMemCoreInstantiates(self):
        """生产装配点（`mem_core.py:635` 那句 import）取的必须是本档测的**同一个模块对象**。

        本仓有同名遮蔽族（`memory_layer/conflict.py` 与 `memory_layer/channels/conflict.py`
        是两个不同体），测错一份会全绿而生产那条没被守——所以这格不是形式主义。
        """
        import importlib
        import inspect

        from neurova import mem_core
        from neurova.cognitive_layers.memory_layer import working_memory as wmModule

        line = next(l for l in inspect.getsource(mem_core).splitlines()
                    if "import WorkingMemoryAugmenter" in l)
        modulePath = line.split(" import ")[0].strip().removeprefix("from ").strip()
        resolved = importlib.import_module(modulePath)

        assert resolved is wmModule, (
            "装配点取的是另一份同名模块（%s），本档守的不是生产路上那个类" % modulePath)
        assert resolved.WorkingMemoryAugmenter is WorkingMemoryAugmenter
