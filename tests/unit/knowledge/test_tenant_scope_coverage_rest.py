# -*- coding: utf-8 -*-
"""S5 租户过滤集中化·余量扫荡批四（repository/foundation/enterprise/mcp_source/
state_event_bridge）覆盖判据。

批四清单内每个文件不得再含裸 tenant 过滤模式（grep 级断言）：
  - 形态 P1（dict 提取 + ``or "default"`` 兜底）一律收口到
    ``neurova.core.tenant_scope.resolve_tenant``；
  - 形态 P3（裸 ``tenant_id = ?`` SQL 子句，含别名前缀）一律收口到
    ``tenant_scope.tenant_sql_where``；
  - 形态 P4（sqlite3.Row 下标提取 + ``or "default"`` 兜底）经 ``dict(row)``
    转换后收口到 ``resolve_tenant``；
  - user 行 vs 数据行的内存比对收口到 ``tenant_matches``；
  - 与助手语义不同构的写法（写路打戳、双源 fallback、驼峰键 descriptor、
    排除式 ``!=`` 校验、参数链归一）列入保留点白名单并钉住「确因语义不同
    而保留」——白名单片段被误删即红，防止后续批次不看语义差异盲目改写
    （行为必须逐字节一致）。
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

# 裸提取模式（P1/P4）：批四清单内一律禁止，须走 resolve_tenant。
BARE_DICT_EXTRACT = re.compile(r'get\("tenant_id"\)\s*or\s*"default"')
BARE_ROW_EXTRACT = re.compile(r'\["tenant_id"\]\s*or\s*"default"')
# 裸 SQL 租户子句（P3）：批四清单内一律禁止，须走 tenant_sql_where。
RAW_SQL_TENANT_CLAUSE = re.compile(r"tenant_id\s*=\s*\?")

BARE_PATTERNS = (
    ("P1 dict 提取+default 兜底", BARE_DICT_EXTRACT),
    ("P4 Row 下标提取+default 兜底", BARE_ROW_EXTRACT),
    ("P3 裸 SQL 租户子句", RAW_SQL_TENANT_CLAUSE),
)

# 批四扫荡清单：repository/foundation/enterprise/mcp_source/state_event_bridge
# 下含「按租户过滤/比对」消费点的文件。
BATCH4_FILES = (
    "knowledge/repository.py",
    "knowledge/foundation/knowledge_facts.py",
    "knowledge/foundation/graph_walk.py",
    "knowledge/foundation/entry_ledger.py",
    "knowledge/foundation/temporal_facts.py",
    "knowledge/enterprise/registry.py",
    "knowledge/enterprise/schema_catalog.py",
    "knowledge/enterprise/nl2sql.py",
    "knowledge/mcp_source.py",
    "knowledge/state_event_bridge.py",
)

# 迁移接线断言：这些文件本批收口到 tenant_scope 助手（写入 → 读取闭环）。
TENANT_SCOPE_WIRED = BATCH4_FILES

# 保留点白名单：与 tenant_scope 三助手语义不同构、本批明确保留的租户段。
# 每条 = (文件, 必须仍存在的原文片段, 保留理由)。
KEPT_POINTS = (
    (
        "knowledge/mcp_source.py",
        'str(spec.get("tenant_id") or existing["tenant_id"])',
        "更新合并的双源 fallback（spec 缺租户回退既有行值），非单一行提取，"
        "resolve_tenant 无此语义",
    ),
    (
        "knowledge/state_event_bridge.py",
        'str(binding.get("tenantId") or "default")',
        "事件绑定 descriptor 的驼峰键 tenantId（显式随 descriptor 传递，"
        "AGENTS.md §3），非 tenant_id 列行提取",
    ),
    (
        "knowledge/enterprise/registry.py",
        'str(tenantOverride or descriptor.get("tenantId") or "default")',
        "投影目标租户的参数链归一（override → descriptor 驼峰键 → default），"
        "非 user/行提取",
    ),
    (
        "knowledge/mcp_source.py",
        '" tool_name=?, tool_args=?, agent_id=?, tenant_id=?, updated_at=?"',
        "UPDATE 的 SET 赋值列清单（写路打戳），非 WHERE 过滤，"
        "tenant_sql_where 不适用",
    ),
    (
        "knowledge/foundation/knowledge_facts.py",
        "AND tenant_id != ?",
        "基线冻结的排除式校验（拒绝引用他租户事实），tenant_sql_where 只提供"
        "等值过滤，语义不同构",
    ),
    (
        "knowledge/repository.py",
        'item["tenant_id"] = "default"',
        "存量行归一化写路打戳（缺省补 default），非读取过滤",
    ),
    (
        "knowledge/repository.py",
        'copy["tenant_id"] = target_tenant',
        "跨租户发布副本落库写路打戳，非读取过滤",
    ),
)


def _readSource(rel: str) -> str:
    return (REPO_ROOT / "neurova" / rel).read_text(encoding="utf-8")


def test_batch4FilesContainNoBareTenantFilterPattern():
    """批四清单内不得再有裸 tenant 过滤模式（P1/P4 提取、P3 SQL 子句）。

    白名单片段所在行豁免：它们与助手语义不同构而保留（写路 SET 赋值等），
    由 test_semanticVariantKeptPointsStillPresent 单独钉住不被误删。
    """
    keptByFile = {}
    for rel, fragment, _reason in KEPT_POINTS:
        keptByFile.setdefault(rel, []).append(fragment)
    failures = []
    for rel in BATCH4_FILES:
        text = _readSource(rel)
        keptFragments = keptByFile.get(rel, [])
        for label, pattern in BARE_PATTERNS:
            for index, line in enumerate(text.splitlines(), start=1):
                if pattern.search(line) and not any(f in line for f in keptFragments):
                    failures.append(
                        "%s:%d 命中%s %r——应改用 neurova.core.tenant_scope 助手"
                        % (rel, index, label, line.strip())
                    )
    assert not failures, (
        "批四清单仍含 %d 处裸 tenant 过滤模式：\n%s" % (len(failures), "\n".join(failures))
    )


def test_batch4MigrationWiredToTenantScope():
    """本批迁移点须真实接线 tenant_scope（单一事实源，不许只删不接）。"""
    for rel in TENANT_SCOPE_WIRED:
        assert "tenant_scope" in _readSource(rel), (
            "%s 未接线 neurova.core.tenant_scope" % rel
        )


def test_semanticVariantKeptPointsStillPresent():
    """保留点必须原样存在：这些租户段与助手语义不同构，误删/误改即红。"""
    for rel, fragment, reason in KEPT_POINTS:
        assert fragment in _readSource(rel), (
            "%s 的保留点 %r 被改动（%s）——该租户段因语义不同构而保留，"
            "迁移动手前先核对行为差异" % (rel, fragment, reason)
        )
