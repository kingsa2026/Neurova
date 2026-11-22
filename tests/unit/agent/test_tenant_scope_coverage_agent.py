# -*- coding: utf-8 -*-
"""S5 租户过滤集中化·余量扫荡批二（agent/core 侧）覆盖判据。

批二清单内每个文件不得再含裸 tenant 过滤模式（grep 级断言）：
  - 形态 P1/P2（dict/attr 提取 + ``or "default"`` 兜底）一律收口到
    ``neurova.core.tenant_scope.resolve_tenant``；
  - 形态 P3（裸 ``tenant_id = ?`` SQL 子句）一律收口到
    ``tenant_scope.tenant_sql_where``；
  - 与助手语义不同构的写法（neuacp 进程池键/HMAC 凭据租户段、缓存键租户段）
    列入保留点白名单并钉住「确因语义不同而保留」——白名单行被误删即红，
    防止后续批次不看语义差异盲目改写（行为必须逐字节一致）。
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

# 裸提取模式（形态 P1/P2）：批二清单内一律禁止，须走 resolve_tenant。
BARE_DICT_EXTRACT = re.compile(r'get\("tenant_id"\)\s*or\s*"default"')
BARE_ATTR_EXTRACT = re.compile(r'getattr\([^()]*"tenant_id"[^()]*\)\s*or\s*"default"')
# 裸 SQL 租户子句（形态 P3）：批二清单内一律禁止，须走 tenant_sql_where。
RAW_SQL_TENANT_CLAUSE = re.compile(r"tenant_id\s*=\s*\?")

BARE_PATTERNS = (
    ("P1 dict 提取+default 兜底", BARE_DICT_EXTRACT),
    ("P2 attr 提取+default 兜底", BARE_ATTR_EXTRACT),
    ("P3 裸 SQL 租户子句", RAW_SQL_TENANT_CLAUSE),
)

# 批二扫荡清单：agent/core 侧含「按租户过滤/比对」消费点的文件
#（含 neuacp 4 文件——它们无过滤点，入清单是为了钉住「语义不同保留」判定）。
BATCH2_FILES = (
    "agent/approval_chain.py",
    "agent/chat_pipeline.py",
    "agent/swarm.py",
    "agent/graph_retriever_adapter.py",
    "agent/tkg_retriever_adapter.py",
    "agent/knowledge_retriever_adapter.py",
    "agent/memory_retrieval_chain.py",
    "agent/neuacp/acp_executor.py",
    "agent/neuacp/child_env.py",
    "agent/neuacp/plugin_executor.py",
    "agent/neuacp/process_pool.py",
    "knowledge/community_graph.py",
    "knowledge/chunk_dispatch.py",
    "knowledge/ingest_bridge.py",
    "knowledge/ingest_worker.py",
    "knowledge/graph_bridge.py",
    "knowledge/fts_index.py",
)

# 迁移接线断言：这些文件本批收口到 tenant_scope 助手（写入 → 读取闭环）。
TENANT_SCOPE_WIRED = (
    "agent/approval_chain.py",
    "agent/chat_pipeline.py",
    "agent/swarm.py",
    "agent/graph_retriever_adapter.py",
    "agent/tkg_retriever_adapter.py",
    "agent/knowledge_retriever_adapter.py",
    "knowledge/community_graph.py",
    "knowledge/chunk_dispatch.py",
    "knowledge/ingest_bridge.py",
    "knowledge/ingest_worker.py",
    "knowledge/graph_bridge.py",
    "knowledge/fts_index.py",
)

# 保留点白名单：与 tenant_scope 三助手语义不同构、本批明确保留的租户段。
# 每条 = (文件, 必须仍存在的原文片段, 保留理由)。
KEPT_POINTS = (
    (
        "agent/neuacp/acp_executor.py",
        '"tenant_id": self._run_tenant_id',
        "HMAC 作用域凭据的租户段（C4 run 级身份绑定），非租户过滤",
    ),
    (
        "agent/neuacp/plugin_executor.py",
        '"tenant_id": self._run_tenant_id',
        "HMAC 作用域凭据的租户段（C4 run 级身份绑定），非租户过滤",
    ),
    (
        "agent/neuacp/child_env.py",
        'run_credential_context.get("tenant_id")',
        "子进程环境注入的凭据租户段读取，非租户过滤",
    ),
    (
        "agent/neuacp/process_pool.py",
        'str(tenant or "default"),',
        "进程池键 (tenant, tool, ...) 的租户段归一，非 user 行提取",
    ),
    (
        "agent/memory_retrieval_chain.py",
        'str(metadata.get("tenant_id") or "")',
        "检索缓存键的租户段：缺省落空串（非 default）——改 resolve_tenant 会改变缓存键",
    ),
)


def _readSource(rel: str) -> str:
    return (REPO_ROOT / "neurova" / rel).read_text(encoding="utf-8")


def test_batch2FilesContainNoBareTenantFilterPattern():
    """批二清单内不得再有裸 tenant 过滤模式（P1/P2 提取、P3 SQL 子句）。"""
    failures = []
    for rel in BATCH2_FILES:
        text = _readSource(rel)
        for label, pattern in BARE_PATTERNS:
            for index, line in enumerate(text.splitlines(), start=1):
                if pattern.search(line):
                    failures.append(
                        "%s:%d 命中%s %r——应改用 neurova.core.tenant_scope 助手"
                        % (rel, index, label, line.strip())
                    )
    assert not failures, (
        "批二清单仍含 %d 处裸 tenant 过滤模式：\n%s" % (len(failures), "\n".join(failures))
    )


def test_batch2MigrationWiredToTenantScope():
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
