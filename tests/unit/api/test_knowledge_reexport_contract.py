"""knowledge 聚合器 re-export 面契约（2026-09-16 拆分后冻结）。

knowledge.py 拆分后保留兼容 re-export：拆分前定义在本文件的符号，外部消费方
（knowledge_graph_api / neurova.knowledge.ingest_worker / 多个测试）仍经
`knowledge.<name>` 引用。本文件钉死这层兼容契约的两条不变量：

1. **消费面存在性 + 真身同一性** —— `_CONSUMED_SURFACE` 枚举当前全部经
   knowledge.<name> 引用的外部消费符号（生产侧经 AST 全仓扫描实证：
   knowledge_graph_api._default_llm_call ×2、ingest_worker._fetch_url +
   _import_file_data；测试侧为聚合器别名属性访问全集）。每个符号必须仍可从
   聚合器 getattr，且必须与真身叶子模块的符号是**同一对象**（is 比对）——
   re-export 指向陈旧拷贝或改绑到别的实现即红。`router` 是聚合器自组装对象，
   无真身可比，仅钉存在性。
2. **钉死清单不过期** —— 运行时重新扫描仓库（子串预滤 + AST），任何新增的
   `knowledge.<name>` 消费（新 from-import、新别名属性访问）不在清单内即红。
   这是有意的「先登记后消费」：新消费方出现时必须把符号加进
   `_CONSUMED_SURFACE` 并写明消费方，兼容面变更永远可见。

消费面来源核实记录（2026-09-16）：
- tests/unit/knowledge/test_multi_kb_router.py 的 `kb.kb_id` 等命中是同名局部
  桩对象属性，该文件不 import 聚合器，不属消费面；
- 全仓无 `import neurova.api.endpoints.knowledge`（无 asname）形态消费方。
"""
import ast
import importlib
from pathlib import Path

import pytest

import neurova.api.endpoints.knowledge as kb

_PKG_ROOT = Path(__file__).resolve().parents[3]  # tests/unit/api/ → 仓库根
_SCAN_ROOTS = ("neurova", "tests", "scripts")
_AGGREGATOR_MODULE = "neurova.api.endpoints.knowledge"
# 命中预滤子串的文件里，凡 import 了聚合器的都参与扫描；守卫测试自身排除，
# 避免扫描结果反馈进被钉清单形成自指。
_SCAN_EXCLUDED = {
    "test_knowledge_reexport_contract.py",
    "test_endpoints_module_layering.py",
}

#: 外部消费符号 → 真身叶子模块（None = 聚合器自组装对象，仅钉存在性）。
#: 新增消费方时在此登记符号 + 消费方说明；删除消费方后条目应同步清理。
_CONSUMED_SURFACE: dict[str, str | None] = {
    # ---- 生产消费方（AST 实证，懒导入于调用时刻）----
    "_default_llm_call": "knowledge_ingestion",  # knowledge_graph_api（图谱抽取 LLM 裁决）
    "_fetch_url": "knowledge_ingestion",         # neurova.knowledge.ingest_worker（网页摄取）
    "_import_file_data": "knowledge_ingestion",  # neurova.knowledge.ingest_worker（文件摄取）
    # ---- 测试消费方（聚合器别名属性访问全集，逐文件核实）----
    "KnowledgeSearchRequest": "knowledge_common",  # test_knowledge_chunking_api（请求模型构造）
    "_try_extract_to_graph": "knowledge_ingestion",  # test_knowledge_chunking_api
    "_validate_import_url": "knowledge_ingestion",  # test_knowledge_import（SSRF 守卫直调）
    "get_knowledge": "knowledge_core",             # test_knowledge_import
    "import_knowledge_file": "knowledge_ingestion",  # test_knowledge_chunking_api / import
    "preview_chunking": "knowledge_core",          # test_knowledge_preview_chunking
    "router": None,                                # 聚合器自组装：route_order / service_token_auth 等
    "search_knowledge": "knowledge_core",          # test_knowledge_chunking_api
    "sync_kb_config": "knowledge_remote",          # test_knowledge_integration_honesty
}


@pytest.mark.parametrize("name,truth_module", sorted(_CONSUMED_SURFACE.items()))
def test_consumed_symbol_exists_and_aliases_truth(name: str, truth_module: str | None):
    """消费符号必须仍可从聚合器获取，且与真身叶子模块同一对象（is）。"""
    symbol = getattr(kb, name, None)
    assert symbol is not None, (
        f"knowledge.{name} 从聚合器消失——外部消费方正在依赖它，"
        "拆分/重构不得破坏 re-export 面（消费面清单见本文件 _CONSUMED_SURFACE）"
    )
    if truth_module is None:
        return
    truth = getattr(importlib.import_module(f"neurova.api.endpoints.{truth_module}"), name)
    assert symbol is truth, (
        f"knowledge.{name} 与真身 {truth_module}.{name} 不是同一对象："
        "re-export 被改绑到陈旧拷贝或别的实现，行为漂移将静默影响消费方"
    )


def test_lazy_consumers_of_production_symbols_resolve():
    """两个生产消费方模块可导入（其函数内懒导入等价于「模块导入 + getattr」，
    存在性用例已覆盖符号级；本用例覆盖消费方模块自身的可导入性不被拆分破坏）。"""
    for module_name in ("neurova.api.endpoints.knowledge_graph_api",
                        "neurova.knowledge.ingest_worker"):
        assert importlib.import_module(module_name) is not None


def _collect_consumed_names_from_repo() -> set[str]:
    """扫描仓库，收集当前真实存在的 knowledge.<name> 消费（两种形态）：

    - `from neurova.api.endpoints.knowledge import <name>`
    - 聚合器别名（import ... as <alias>）的属性访问 `<alias>.<name>`

    子串预滤（endpoints.knowledge / endpoints import knowledge）保证任何 import
    了聚合器的文件都不会漏网；扫描结果即「当前真实消费面」。
    """
    consumed: set[str] = set()
    for root_name in _SCAN_ROOTS:
        root = _PKG_ROOT / root_name
        if not root.is_dir():
            continue
        for path in root.rglob("*.py"):
            if "__pycache__" in path.parts or path.name in _SCAN_EXCLUDED:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            if "endpoints.knowledge" not in text and "endpoints import knowledge" not in text:
                continue
            tree = ast.parse(text, filename=str(path))
            aliases: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module == _AGGREGATOR_MODULE:
                    consumed.update(a.name for a in node.names if a.name != "*")
                elif isinstance(node, ast.Import):
                    for a in node.names:
                        if a.name == _AGGREGATOR_MODULE and a.asname:
                            aliases.add(a.asname)
                elif isinstance(node, ast.ImportFrom) and node.module == "neurova.api.endpoints":
                    for a in node.names:
                        if a.name == "knowledge" and a.asname:
                            aliases.add(a.asname)
            if aliases:
                for node in ast.walk(tree):
                    if (isinstance(node, ast.Attribute)
                            and isinstance(node.value, ast.Name)
                            and node.value.id in aliases):
                        consumed.add(node.attr)
    return consumed


def test_pinned_surface_covers_every_real_consumer():
    """钉死清单必须覆盖仓库里全部真实消费——新消费方出现而未登记即红。

    这是「清单不过期」守护：任何人写出新的 `knowledge.<name>` 引用而没把它
    登记进 _CONSUMED_SURFACE（并写明消费方），本用例立刻转红，兼容面变更
    永远以显式 diff 呈现，而不是悄悄发生在 re-export 块里。
    """
    unregistered = _collect_consumed_names_from_repo() - set(_CONSUMED_SURFACE)
    assert not unregistered, (
        f"发现未登记的 knowledge.<name> 消费符号：{sorted(unregistered)}。"
        "请把它们加入 _CONSUMED_SURFACE 并注明消费方——"
        "re-export 兼容面的每次扩大都必须是显式契约变更"
    )
