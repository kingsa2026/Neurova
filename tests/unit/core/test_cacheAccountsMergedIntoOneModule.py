# -*- coding: utf-8 -*-
"""缓存三本账收成一条事实源（§6-201 登记的「要不要收成一条」＝用户点单 G，裁定 B）。

收口前的实状（本批现算）：
- `neurova/memory/core/cache.py`(574 行)＝唯一实装，另有全局实例注册名 `memory_global`
  （手写 `threading.Lock` 的 DCL）与 `cached` 装饰器；
- `neurova/core/cache.py`(84 行)＝门面，第二个全局实例注册名 `core_global`（走 `lazySingleton`）
  加四个便捷函数 `cache_get/cache_set/cache_delete/cache_clear`——**全仓零消费者**（除自身与
  `__all__`，现读 0 处），属 §2 的"写出无人读"；
- `neurova/cognitive_layers/memory_layer/cache.py`(21 行)＝自陈已废弃的薄壳，4 个未用 import，
  `docs/04-plans/stub-cleanup-plan.md` 里就写着"设计文档明确要删除"；
- `api/endpoints/settings.py` 的「清缓存」端点越过公开口直接读私有 `_cache_registry`
  （且同时 import 了公开的 `iter_caches` 却没用）。

两条全局实例注册名意味着：一旦有人从任一门面取实例，`/metrics` 的命中率就会把同一个
进程里的缓存记成两列；`iter_caches()` 的消费者无法知道哪一列才是真的。本档钉的是
「一条实现、一条注册名、注册表不出本模块」。
"""

import ast
import importlib
from pathlib import Path

import pytest

from tests import ast_scan

PROJECT_ROOT = Path(__file__).resolve().parents[3]
NEUROVA = PROJECT_ROOT / "neurova"

CANONICAL = "neurova/core/cache.py"
RETIRED_FILES = (
    "neurova/memory/core/cache.py",
    "neurova/memory/core/__init__.py",
    "neurova/cognitive_layers/memory_layer/cache.py",
)
RETIRED_MODULES = (
    "neurova.memory.core.cache",
    "neurova.memory.core",
    "neurova.cognitive_layers.memory_layer.cache",
)
# 门面那四个便捷函数：零消费者，按 §2 断点条款退役后不得复活
RETIRED_FUNCS = {"cache_get", "cache_set", "cache_delete", "cache_clear"}


def _canonicalModule():
    return importlib.import_module("neurova.core.cache")


def test_onlyTheCanonicalCacheModuleExists():
    """三份退役档必须真的不在，而选定那份必须在——否则整档判据是绿的空话。"""
    for rel in CANONICAL, *RETIRED_FILES:
        exists = (PROJECT_ROOT / rel).is_file()
        if rel == CANONICAL:
            assert exists, f"选定的那一份不见了：{rel}（判据失去对象）"
        else:
            assert not exists, f"{rel} 是第二/第三本缓存账，按 §6/§7 已退役，不得存在"


@pytest.mark.parametrize("retired", RETIRED_MODULES)
def test_productionNoLongerImportsTheRetiredPaths(retired):
    """生产侧不得再 import 退役路径；判据走 AST，注释里提到退役路径不算命中。

    按模块逐个参数化而不是只扫一条：漏一条即留下一条活路（`from neurova.memory.core
    import cache as m` 那种包级形状就只被第三条覆盖到）。

    取数走共享入口 `importersOfModule`（末段名预筛＋四种取法都认）。此前是
    `importsOf(nodeScan(hints=(全名,)), 全名)`：相对形 `from .cache import X` 不含包前缀，
    既过不了文本预筛、也过不了 `node.module` 比对 ⇒ "零引用"可能是假零（§6-316 的窄面①）。
    """
    offenders = [f"{rel}:{lineno} [{form}]"
                 for rel, lineno, form in ast_scan.importersOfModule(NEUROVA, retired)]
    assert not offenders, f"仍有生产代码引用已退役的缓存路径 {retired}: {offenders}"


def test_runtimeStringImportsAvoidTheRetiredPathsToo():
    """`importlib.import_module("<退役路径>")` 这一形 AST 的 importsOf 看不见，单独数一遍。"""
    offenders = []
    for path, node in ast_scan.nodeScan(NEUROVA, hints=("import_module",)):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", "")
        if name != "import_module" or not node.args:
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str) \
                and first.value.startswith(RETIRED_MODULES):
            offenders.append(f"{ast_scan.relativeToRepo(path)}:{node.lineno}")
    assert not offenders, f"运行期字符串导入仍指向退役缓存路径: {offenders}"


def test_globalCacheHoldsOneRegisteredName():
    """进程默认缓存只能有一条注册名——两条门面各自登记，/metrics 就把一个进程记成两列。"""
    mod = _canonicalModule()
    missing = [name for name in ("get_global_cache", "iter_caches", "reset_global_cache")
               if not hasattr(mod, name)]
    assert not missing, (
        f"选定那份没暴露 {missing}——收口的意思是「一条账搬进这一份」，"
        "不是把它掏空成只剩一个名字")

    mod.reset_global_cache()
    try:
        mod.get_global_cache()
        names = [name for name, _stats in mod.iter_caches()]
        assert names == ["default"], (
            f"全局缓存在注册表里应当只有一条 'default'，实得 {names}"
            "——两条以上＝同一个进程被 /metrics 记成多列缓存")
    finally:
        mod.reset_global_cache()


def test_registryStaysPrivateToItsOwningModule():
    """`_cache_registry` 不得被别的模块读——跨模块拿私有名就是第二条读取路径。"""
    hits = [
        f"{ast_scan.relativeToRepo(path)}:{node.lineno}"
        for path, node in ast_scan.nodeScan(NEUROVA, hints=("_cache_registry",))
        if isinstance(node, ast.Name) and node.id == "_cache_registry"
        and ast_scan.relativeToRepo(path) != CANONICAL
    ]
    assert not hits, f"这些模块绕过公开口直接引用私有注册表: {hits}"


def test_clearAllCachesHasAPublicEntryAndActsOnRealObjects():
    """「清缓存」必须有一个住在实装侧的公开入口，且作用在真实对象上（不是恒真端点）。"""
    mod = _canonicalModule()
    clearAll = getattr(mod, "clearRegisteredCaches", None)
    assert callable(clearAll), (
        "neurova.core.cache 没有公开的 clearRegisteredCaches()——"
        "设置页端点此前直接伸手拿私有 _cache_registry，等于在实装外面又写一条读取路径")

    probeA = mod.MemoryCache(capacity=8)
    probeB = mod.MemoryCache(capacity=8)
    probeA.set("k1", 1)
    probeA.set("k2", 2)
    probeB.set("k3", 3)
    mod.register_cache("probeA", probeA)
    mod.register_cache("probeB", probeB)
    try:
        cleared = clearAll()
        assert cleared["probeA"] == 2 and cleared["probeB"] == 1, f"逐条计数不对: {cleared}"
        assert len(probeA) == 0 and len(probeB) == 0, "登记着的缓存没被清空"
    finally:
        mod.unregister_cache("probeA")
        mod.unregister_cache("probeB")


def test_zeroConsumerConvenienceFaceStaysRetired():
    """门面那四个便捷函数全仓零消费者——退役后不得在任何生产模块里复活。

    一次扫描数四个（同名定义点归拢报），不分参数化：这一条不变量是「这四个都不许在」，
    拆成四格只会把同一份解析预算付四遍。
    """
    found = {}
    for path, node in ast_scan.nodeScan(NEUROVA, hints=tuple(RETIRED_FUNCS)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in RETIRED_FUNCS:
            found.setdefault(node.name, []).append(
                f"{ast_scan.relativeToRepo(path)}:{node.lineno}")
    assert not found, (
        f"零消费者的便捷面又出现了 {found}——留着就是第二条『写而没人读』的账（§2 断点条款）")


def _functionDefs(funcName):
    """扫生产侧所有同名函数定义（用共享解析预算，不私开一次 rglob+parse）。"""
    for path, tree in ast_scan.parsedModules(NEUROVA):
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == funcName:
                yield path, node.lineno
