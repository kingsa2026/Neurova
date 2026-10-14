# -*- coding: utf-8 -*-
"""Issue #55 死代码收敛守卫：`neurova/performance.py` 已删，缓存实现只留一份。

背景：仓库里有两份 MemoryCache 实现——
- ``neurova/memory/core/cache.py``（真实载体，core/cache.py 与其 re-export、
  performance 消费）；
- ``neurova/performance.py``（只 re-export memory/core/cache 的 MemoryCache，
  自带一份 cached 装饰器与 PerformanceMonitor）。全仓引用只有它自己的测试，
  生产零调用 —— 典型的"看着像能用的重复入口"。

处置：删除 performance.py 与其测试（死代码），缓存收敛到
``memory/core/cache.py``（+ ``core/cache.py`` 的全局实例门面）。原 performance
测试里对真实载体的契约断言已由 tests/unit/memory/test_cache_*.py 覆盖。

**2026-10-14 批 45 改判（用户点单 G＝裁定 B）**：上面那句"收敛到 memory/core/cache.py
+ core/cache.py 门面"**不是终局**——两层面各自登记一条全局实例（`memory_global` 与
`core_global`），同一个进程在 /metrics 里就被记成两列；`cache_get/set/delete/clear`
四个便捷函数全仓零消费者；`memory_layer/cache.py` 薄壳自陈已废弃却仍是唯一一条
`neurova.memory.cache` 别名的落点（还是那条真循环的载体）。现收成一条：
实装住在 ``neurova/core/cache.py``，两份门面全部退役。
本守卫因此从"允许两份薄门面"改成"不得再出现任何再导出门面"。

本守卫防止死模块与退役门面被"顺手加回来"。
"""

from pathlib import Path

import pytest

from tests import ast_scan

PROJECT_ROOT = Path(__file__).resolve().parents[3]
NEUROVA = PROJECT_ROOT / "neurova"

# 唯一允许的 MemoryCache 实现载体
CANONICAL_CACHE = "neurova/core/cache.py"

# 已退役的再导出门面：批 45 之后不得存在，也不得被 import
# （曾以 KNOWN_REEXPORT_SHIMS 的形式被本守卫当作合法形状钉着——那份判断已被改判）
RETIRED_SHIMS = (
    "neurova/memory/core/cache.py",
    "neurova/memory/core/__init__.py",
    "neurova/cognitive_layers/memory_layer/cache.py",
)


#: 已删模块名：文本预筛词（含 `neurova.performance` 字样的文件才需要解析）
REMOVED_MODULE = "neurova.performance"


def _iterProductionPy():
    """生产侧源码路径（解析走 `tests/ast_scan.py` 的共享预算）。"""
    return ast_scan.filesUnder(NEUROVA)


class TestPerformanceModuleRemoved:
    def test_file_gone(self):
        assert not (NEUROVA / "performance.py").exists(), (
            "neurova/performance.py 是生产零调用的死代码（重复的 MemoryCache/"
            "PerformanceMonitor），不得重新加回"
        )

    def test_no_production_reference(self):
        """生产侧不得 import 已删模块（判据是 `import` 语句，不是文本里提过）。

        解析走 `tests/ast_scan.py`（Issue #148）：全仓 `ast.parse` 单跑 5s、与
        受保护子集其余 170 个文件共享机器时必然逼近 30s 默认墙钟；`importsOf`
        只解析文本里出现过模块名的文件，与代码总量脱钩。
        """
        offenders = [
            f"{ast_scan.relativeToRepo(path)}:{lineno}"
            for path, lineno in ast_scan.importsOf(
                ast_scan.nodeScan(NEUROVA, hints=(REMOVED_MODULE,)), REMOVED_MODULE)
        ]
        assert not offenders, f"仍有代码引用已删除的 neurova.performance: {offenders}"

    def test_no_test_reference(self):
        """测试也不得 import 已删模块（本守卫文件自身只谈字符串，不 import）。

        解析范围用 `tests/ast_scan.py` 的共享预算；本文件按名字排除，
        否则文档里那句 ``neurova.performance`` 会被自己的判据读到。
        """
        offenders = []
        for path, lineno in ast_scan.importsOf(
                ast_scan.nodeScan(PROJECT_ROOT / "tests", hints=(REMOVED_MODULE,)),
                REMOVED_MODULE):
            if path.name == Path(__file__).name:
                continue
            offenders.append(f"{ast_scan.relativeToRepo(path)}:{lineno}")
        assert not offenders, f"测试仍引用已删除的 neurova.performance: {offenders}"


class TestSingleMemoryCacheImplementation:
    def test_only_one_memory_cache_class_definition(self):
        """MemoryCache 只允许有一个类定义（薄门面只 re-export，不重写）。

        `classDefsIn` 走共享解析预算与文本预筛：没有 `class MemoryCache` 字样的
        文件不解析，判据与代码总量脱钩。
        """
        definitions = [
            ast_scan.relativeToRepo(path)
            for path, _lineno in ast_scan.classDefsIn(NEUROVA, "MemoryCache")
        ]
        assert definitions == [CANONICAL_CACHE], (
            f"MemoryCache 实现应为 {CANONICAL_CACHE} 独一份，实际: {definitions}\n"
            "重复实现会导致缓存语义分叉（TTL/LRU 行为不一致）。"
        )

    @pytest.mark.parametrize("shim", RETIRED_SHIMS)
    def test_reexport_shimsStayRetired(self, shim):
        """批 45 退役的两层面不得复活——留门面＝留第二条全局实例与第二条读取路径。"""
        assert not (PROJECT_ROOT / shim).is_file(), (
            f"{shim} 是缓存的再导出门面，批 45 已按 §6/§7 退役；"
            "要消费缓存请直接从 neurova/core/cache.py 取"
        )

    def test_canonicalModuleHoldsTheRealContract(self):
        """选定那份必须真有全局实例与实现本体——别把收口做成"只剩一个空名字"。

        反空转配对格：`MemoryCache` 的定义必须就在这个模块里（`__module__` 自证），
        否则 `CANONICAL_CACHE == definitions` 那条会被一次 re-export 蒙过去。
        """
        from neurova.core.cache import MemoryCache, get_global_cache

        assert MemoryCache.__module__ == "neurova.core.cache"
        assert isinstance(get_global_cache(), MemoryCache)
