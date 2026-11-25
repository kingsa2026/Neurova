# -*- coding: utf-8 -*-
"""S5 租户过滤集中化·余量扫荡批三（knowledge/ontology 全族）覆盖判据。

批三清单内每个文件不得再含裸 tenant 过滤模式（grep 级断言）：
  - 形态一 SQL 拼接：裸 ``tenant_id = ?`` 子句一律收口到
    ``neurova.core.tenant_scope.tenant_sql_where``；
  - 形态二/三（内存提取/行级比对）中与助手语义不同构的写法列入白名单，
    并在此钉住「确因语义不同而保留」——白名单行被误删即红，防止后续
    批次不看语义差异盲目改写（行为必须逐字节一致）。
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
ONTOLOGY_DIR = REPO_ROOT / "neurova" / "knowledge" / "ontology"

# 裸 SQL 租户子句（形态一）：批三清单内一律禁止，须走 tenant_sql_where。
RAW_SQL_TENANT_CLAUSE = re.compile(r"tenant_id\s*=\s*\?")
# 裸提取/比对（形态 P1）：``get("tenant_id") or "default"`` 缺省兜底一律禁止，
# 须走 resolve_tenant / tenant_matches。
BARE_DICT_EXTRACT = re.compile(r'get\("tenant_id"\)\s*or\s*"default"')

BARE_PATTERNS = (
    ("P3 裸 SQL 租户子句", RAW_SQL_TENANT_CLAUSE),
    ("P1 dict 提取+default 兜底", BARE_DICT_EXTRACT),
)

# 批三扫荡清单：knowledge/ontology 下含「按租户过滤/比对」消费点的文件
#（路径相对 ontology 目录）。
BATCH3_FILES = (
    "abduction.py",
    "accountability.py",
    "action_registry.py",
    "action_runtime.py",
    "artifact_store.py",
    "audit.py",
    "change_log.py",
    "decision_ledger.py",
    "derivation_ledger.py",
    "function_engine.py",
    "function_eval.py",
    "function_registry.py",
    "pipeline.py",
    "readiness.py",
    "relation_candidates.py",
    "rule_engine.py",
    "schema_suggester.py",
    "shapes.py",
    "simulation.py",
    "state_machine_registry.py",
    "term_registry.py",
    "turtle.py",
    "export/graph_exchange.py",
    "export/jsonld.py",
    "export/owl.py",
    "export/prov.py",
)

# 迁移接线断言：这些文件本批收口到 tenant_sql_where（写入 → 读取闭环）。
# U8（0f49f6128）把 export/graph_exchange.py 的行来源 SQL 迁到 graph_backend.py
# 门面（conceptTerms/activeTriples 的租户谓词在那边用 tenant_sql_where），
# 接线断言随 SQL 落点改指 graph_backend.py；graph_exchange.py 保留在裸模式扫描。
TENANT_SQL_WHERE_WIRED = tuple(
    rel for rel in BATCH3_FILES if rel != "export/graph_exchange.py"
) + ("graph_backend.py",)

# 白名单：与 tenant_scope 三助手语义不同构、本批明确保留的比对点。
# 每条 = (文件, 必须仍存在的原文片段, 保留理由)。
WHITELIST = (
    (
        "pipeline.py",
        'tenant = str(fromRow.get("tenant_id") or "default")',
        "基线行取租户做行间比对（from 基线 vs to 基线），无 user 一方；"
        "tenant_matches 是 user-vs-row 语义，不同构",
    ),
    (
        "pipeline.py",
        'if str(toRow.get("tenant_id") or "default") != tenant:',
        "跨租户基线 diff 拒绝是行间比对（to 基线 vs from 基线），"
        "非 user 行 vs 数据行过滤",
    ),
    (
        "rule_engine.py",
        'tenantId=str(tenantId or rule.get("tenant_id") or "default")',
        "推导事实准入的租户落款链式兜底（入参→规则行→default），"
        "写侧打戳取值，非读面过滤",
    ),
)


def _readSource(rel: str) -> str:
    return (ONTOLOGY_DIR / rel).read_text(encoding="utf-8")


def test_batch3FilesContainNoBareTenantFilterPattern():
    """批三清单内不得再有裸 tenant 过滤模式（P1 提取、P3 SQL 子句）。"""
    failures = []
    for rel in BATCH3_FILES:
        text = _readSource(rel)
        keptFragments = [fragment for name, fragment, _ in WHITELIST if name == rel]
        for label, pattern in BARE_PATTERNS:
            for index, line in enumerate(text.splitlines(), start=1):
                if any(fragment in line for fragment in keptFragments):
                    continue  # 白名单保留点：语义不同构，另行钉住存在性
                if pattern.search(line):
                    failures.append(
                        "ontology/%s:%d 命中%s %r——应改用 "
                        "neurova.core.tenant_scope 助手"
                        % (rel, index, label, line.strip())
                    )
    assert not failures, (
        "批三清单仍含 %d 处裸 tenant 过滤模式：\n%s" % (len(failures), "\n".join(failures))
    )


def test_batch3SqlSitesWiredToTenantSqlWhere():
    """本批迁移点须真实接线 tenant_sql_where（单一事实源，不许只删不接）。"""
    for rel in TENANT_SQL_WHERE_WIRED:
        assert "tenant_sql_where" in _readSource(rel), (
            "ontology/%s 未接线 neurova.core.tenant_scope.tenant_sql_where" % rel
        )


def test_semanticVariantWhitelistPointsStillPresent():
    """白名单点必须原样保留：这些写法与助手语义不同构，误删/误改即红。"""
    for rel, fragment, reason in WHITELIST:
        assert fragment in _readSource(rel), (
            "ontology/%s 的白名单保留点被改动（%r）——该点因语义不同构而保留，"
            "迁移动手前先核对行为差异：%s" % (rel, fragment, reason)
        )
