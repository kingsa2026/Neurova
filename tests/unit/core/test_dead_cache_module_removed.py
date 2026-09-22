# -*- coding: utf-8 -*-
"""Issue #55 死代码收敛守卫：neurova/performance.py 已删，缓存实现只留一份。

背景：仓库里有两份 MemoryCache 实现——
- ``neurova/memory/core/cache.py``（真实载体，core/cache.py 与其 re-export、
  performance 消费）；
- ``neurova/performance.py``（只 re-export memory/core/cache 的 MemoryCache，
  自带一份 cached 装饰器与 PerformanceMonitor）。全仓引用只有它自己的测试，
  生产零调用 —— 典型的"看着像能用的重复入口"。

处置：删除 performance.py 与其测试（死代码），缓存收敛到
``memory/core/cache.py``（+ ``core/cache.py`` 的全局实例门面）。原 performance
测试里对真实载体的契约断言已由 tests/unit/memory/test_cache_*.py 覆盖。

本守卫防止死模块被"顺手加回来"。
"""

import ast
import io
from pathlib import Path

import pytest

from tests import ast_scan

PROJECT_ROOT = Path(__file__).resolve().parents[3]
NEUROVA = PROJECT_ROOT / "neurova"

# 唯一允许的 MemoryCache 实现载体
CANONICAL_CACHE = "neurova/memory/core/cache.py"

# 允许 re-export 该实现的薄门面（不含第二套实现），值为其导入来源
KNOWN_REEXPORT_SHIMS = {
    "neurova/core/cache.py": "memory.core.cache",
    "neurova/cognitive_layers/memory_layer/cache.py": "core.cache",
}


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

    @pytest.mark.parametrize("shim,source", sorted(KNOWN_REEXPORT_SHIMS.items()))
    def test_shim_is_reexport_only(self, shim, source):
        src = io.open(PROJECT_ROOT / shim, encoding="utf-8").read()
        assert f"{source} import" in src, (
            f"{shim} 应是 {source} 的 re-export 薄门面"
        )
        assert "class MemoryCache" not in src, f"{shim} 不得自带第二套 MemoryCache 实现"

    def test_core_cache_facade_exposes_global_instance(self):
        from neurova.core.cache import get_global_cache
        from neurova.memory.core.cache import MemoryCache

        assert isinstance(get_global_cache(), MemoryCache)
