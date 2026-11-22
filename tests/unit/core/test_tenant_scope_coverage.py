# -*- coding: utf-8 -*-
"""S5 租户过滤集中化·余量扫荡批一（api/endpoints 侧）覆盖判据。

批一清单内每个文件不得再含裸 tenant 过滤模式（grep 级断言）：
  - 形态一 SQL 拼接：裸 ``tenant_id = ?`` 子句一律收口到
    ``neurova.core.tenant_scope.tenant_sql_where``；
  - 形态二/三（内存谓词/行级比较）中与助手语义不同构的写法列入白名单，
    并在此钉住「确因语义不同而保留」——白名单行被误删即红，防止后续
    批次不看语义差异盲目改写（行为必须逐字节一致）。
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
ENDPOINTS_DIR = REPO_ROOT / "neurova" / "api" / "endpoints"

# 裸 SQL 租户子句（形态一）：批一清单内一律禁止，须走 tenant_sql_where。
RAW_SQL_TENANT_CLAUSE = re.compile(r"tenant_id\s*=\s*\?")

# 批一扫荡清单：api/endpoints 下含「按租户过滤/比对」消费点的文件。
BATCH1_FILES = (
    "knowledge_ontology_iri.py",
    "knowledge_enterprise.py",
    "knowledge_ontology.py",
    "generation.py",
    "external_agents_api.py",
    "chat.py",
    "knowledge_graph_api.py",
)

# 迁移接线断言：这些文件本批收口到 tenant_sql_where（写入 → 读取闭环）。
TENANT_SQL_WHERE_WIRED = (
    "knowledge_ontology_iri.py",
    "knowledge_enterprise.py",
    "knowledge_ontology.py",
)

# 白名单：与 tenant_scope 三助手语义不同构、本批明确保留的比对点。
# 每条 = (文件, 必须仍存在的原文片段, 保留理由)。
WHITELIST = (
    (
        "generation.py",
        "if rec_tenant and rec_tenant != cur_tenant:",
        "存量记录无租户时放行（rec_tenant 空串不拦截）；tenant_matches 会把空读成 default 拒绝，语义不同构",
    ),
    (
        "external_agents_api.py",
        "if runTenant and requesterTenant and runTenant != requesterTenant:",
        "run 租户与请求者租户双空放行（历史存量），且请求者租户来自 identity_context 而非 user 行",
    ),
    (
        "chat.py",
        "if speaker_dept != agent_dept:",
        "部门根标量门：agent_dept 为空须拒绝，非「user 行 vs 数据行」同构比对",
    ),
    (
        "knowledge_enterprise.py",
        'if str(tid or "").strip() == tenant:',
        "共享目标自租户跳过的输入校验，非数据行过滤",
    ),
    (
        "knowledge_graph_api.py",
        'if str(tenant_id or "default") == "default":',
        "default 租户走 app-state manager 回退分支，非租户过滤",
    ),
)


def _readEndpoint(name: str) -> str:
    return (ENDPOINTS_DIR / name).read_text(encoding="utf-8")


def test_batch1FilesContainNoRawSqlTenantClause():
    """批一清单内不得再有裸 ``tenant_id = ?`` SQL 子句（形态一收口）。"""
    for name in BATCH1_FILES:
        text = _readEndpoint(name)
        hit = RAW_SQL_TENANT_CLAUSE.search(text)
        assert hit is None, (
            "%s 仍含裸 SQL 租户子句 %r——应改用 tenant_scope.tenant_sql_where"
            % (name, hit.group(0) if hit else "")
        )


def test_batch1SqlSitesWiredToTenantSqlWhere():
    """本批迁移点须真实接线 tenant_sql_where（单一事实源，不许只删不接）。"""
    for name in TENANT_SQL_WHERE_WIRED:
        assert "tenant_sql_where" in _readEndpoint(name), (
            "%s 未接线 tenant_scope.tenant_sql_where" % name
        )


def test_semanticVariantWhitelistPointsStillPresent():
    """白名单点必须原样保留：这些写法与助手语义不同构，误删/误改即红。"""
    for name, fragment, reason in WHITELIST:
        assert fragment in _readEndpoint(name), (
            "%s 的白名单保留点被改动（%s）——该点因语义不同构而保留，"
            "迁移动手前先核对行为差异" % (name, reason)
        )
