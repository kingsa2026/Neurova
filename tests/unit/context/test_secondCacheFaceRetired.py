# -*- coding: utf-8 -*-
"""第二座上下文缓存已退役，不许长回来（§6-107；§9 序 4 复算改判的常驻面）。

改判经过（原登记在 §6-104 是"需人裁"，本轮按用户采纳改判为"可删"，理由三条）：

1. **不是唯一实装**——现役组装链早有这两件事的实装：
   - 组装结果缓存：`neurova/context_pool.py:1469-1485 build_context_for_model()`，
     键 `isolation_key:model`，靠 `_cache_version` 失效（写点 `:275/:292/:339/:1393` 递增）；
     另有一处折叠摘要缓存槽 `neurova/context/orchestrator.py:903-937`。
   - 跨重启持久化：`neurova/context/eviction_ledger_db.py` 的 SQLite WAL+FTS5 与
     `context_ledger` 版本域（v1 三列 / v2 trigram / v3 `pool_hash`），
     且这条契约的常驻判据在册（`scripts/ci/protected_tests.txt` 的
     `tests/unit/context/test_context_deadline_disposal.py` 等）——**注意
     `tests/unit/context/test_context_persistence_restart.py` 判的是池+台账，
     与被退役的 `neurova/context_persistence.py` 同名不同物**。
2. **它今天连构造都过不去**（不是"没接线的可用能力"）：
   `context_cache.py:92` 默认 `enable_persistence=True` → `:138` 直接
   `ContextPersistence()`，而 `context_persistence.py:30` 的签名要求必填 `data_dir`
   ⇒ TypeError，而 `:139` 只 `except ImportError` 接不住；`:209-211` 又向
   `load_context(session_id, agent_id, channel)` 传 `user_id=`，被 `:216` 的宽
   `except Exception` 吞成一句 warning——"从持久化加载"永远失败却看起来正常。
3. **口径与现役不同源**：它的键是裸冒号拼的四维串（`:559-571`，可选段可致前缀歧义），
   而池侧 `context_pool.py:116-120` 强制校验 `isolation_key` 不得含分隔符；
   它也没有内容指纹/版本失效（只有时间/容量/LRU `:427/:471/:606/:669`）。
   这正是 `context/eviction_ledger_db.py:84-86,176-182` 记过的同型坑：
   两个域的值不相等 ⇒ 按它寻址必然全员落空。

退役面：`neurova/context_cache.py`(724) + `neurova/context_persistence.py`(380) +
只测它们自己的两份测试（`tests/unit/context/test_context_cache_persistence.py` 196 行，
用 `__new__` 绕开构造注 mock；`tests/integration/test_context_cache_compression.py` 118 行，
用已不存在的形参与不存在的属性，HEAD 预存红——随本批一并摘除，见台账）。

与 §6-51 的边界：那一格说的是 `UnifiedContextInjector` 内部那张 `self._cache`
（`neurova/context/injector.py:135/1108-1121`，`build_context` 全程不读它），
**与本批无关、不在本格射程**，仍按 §6-51 单独裁。本格只守"第二座缓存不许回来"。
"""
from __future__ import annotations

import ast
from pathlib import Path

from tests import ast_scan

import pytest

REPO = Path(__file__).resolve().parents[3]
PROD_ROOT = REPO / "neurova"
TESTS_ROOT = REPO / "tests"

#: 已退役的名字（ dotted 模块名 → 曾经的位置）。名单不写死路径：判据要能抓到
#: "换个目录再长回来"，所以按**被导入的名字**判而不是按文件位置判。
RETIRED = frozenset({"neurova.context_cache", "neurova.context_persistence"})

pytestmark = pytest.mark.timeout(60)


def _retiredImports(root: Path) -> list[str]:
    """`root` 树里仍引用这两座已退役缓存的落点（四种取法都认）。

    取数走 `tests/ast_scan` 的共享入口 `importersOfModule`：它自己按**末段名**预筛
    （`context_cache` / `context_persistence`——那是判据的充分条件），且相对形、
    父包取名形都在面内。此前这里是私有 `_importedNames`，只认 `node.module` 原文且
    显式跳过 `node.level`——`from neurova import context_cache` 这一形（真引用）看不见。
    显示名：仓内给仓库相对路径，仓外（注入探针落在 tmp 下）只给文件名，
    否则判据自己会抛 `ValueError` 冒名成被测故障。
    """
    hits = []
    for retired in sorted(RETIRED):
        for rel, _lineno, _form in ast_scan.importersOfModule(root, retired):
            shown = rel if rel.startswith(("neurova/", "tests/", "scripts/", "docs/")) \
                else Path(rel).name
            hits.append(f"{shown} → {retired}")
    return sorted(hits)


def test_noProductionImportOfRetiredCaches():
    """生产侧不得再引用这两座（退役时生产引用面实测为 0）。"""
    assert not _retiredImports(PROD_ROOT), (
        f"生产树里又长出对已退役缓存的引用：{_retiredImports(PROD_ROOT)}")


def test_noTestImportOfRetiredCaches():
    """测试侧也不得留着——留着就是测试替一个不存在的契约作证。"""
    assert not _retiredImports(TESTS_ROOT), (
        f"tests/ 里还有对已退役缓存的引用：{_retiredImports(TESTS_ROOT)}\n"
        "（`test_context_persistence_restart.py` 判的是池+SQLite 台账，与被退役的"
        "`neurova/context_persistence.py` 同名不同物，不会命中本格。）")


def test_retiredModuleFilesAreGone():
    """两个文件本身不许再出现在包树里（防止退役面被悄悄改回来）。

    首版这里写成 `context_*.py` 通配，直接把**现役**的 `context_pool.py` 与
    `context_pool_registry.py` 一起判成违规——通配符做退役判据必然过宽，
    下一轮的处置就是"放宽守卫"而不是"修代码"。名单按退役名点名列出。
    """
    back = [n for n in ("context_cache.py", "context_persistence.py")
            if (PROD_ROOT / n).is_file()]
    assert not back, f"已退役的模块文件又出现在包树里：{back}"


def test_livePoolCacheContractStillHolds():
    """反向对照（防删过头）：现役那座必须还在——键与失效口径都在 `context_pool.py`。

    本批删的是"第二座"，池缓存是唯一实装；它要是被顺手带走，上面三格会全绿而
    组装链已经失去缓存。所以这一格必须在删除前后都绿。
    """
    src = (PROD_ROOT / "context_pool.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    names = {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert "build_context_for_model" in names, "现役组装结果缓存的入口不见了"
    assert "_cache_version" in src and "_last_build_version" in src, (
        "池缓存的失效口径（版本号）不见了——现役链改成每次都重算，或缓存被换成了另一套")
    # §6-51 那座注入器缓存在本批之后仍按原样在册（本批不动它，边界自证）
    inj = (PROD_ROOT / "context" / "injector.py").read_text(encoding="utf-8")
    assert "self._cache" in inj, "注入器那座（§6-51 另案）不该被本批带走"


def test_scannerCatchesARevival(tmp_path):
    """注入探针：造一处对已退役名字的 import 必须被抓到——否则前三格是"扫空即绿"。"""
    probe = tmp_path / "revival.py"
    probe.write_text(
        "from neurova.context_cache import ContextCacheManager\n", encoding="utf-8")
    assert _retiredImports(tmp_path) == ["revival.py → neurova.context_cache"]

    # 父包取名形：真引用，旧口径（只比 node.module 原文）看不见这一形，故单列一枚探针
    viaParent = tmp_path / "via_parent.py"
    viaParent.write_text("from neurova import context_persistence\n", encoding="utf-8")
    assert _retiredImports(tmp_path) == [
        "revival.py → neurova.context_cache",
        "via_parent.py → neurova.context_persistence",
    ], "父包取名形没被抓到——导入通道判据又在学旧口径只比一种取法"

    # 反证：现役池缓存的导入不该被误伤（谓词过宽会让下一轮直接放宽守卫）
    ok = tmp_path / "live.py"
    ok.write_text("from neurova.context_pool import ContextPool\n", encoding="utf-8")
    okParent = tmp_path / "live_parent.py"
    okParent.write_text("from neurova import context_pool\n", encoding="utf-8")
    probe.unlink()
    viaParent.unlink()
    assert not _retiredImports(tmp_path), f"误伤了现役池：{_retiredImports(tmp_path)}"
