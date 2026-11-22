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


# ---------------------------------------------------------------------------
# S5 收尾批（私有 resolve 辅助收口）：下列文件的 _tenantOf/_tenant_of/_userTenant
# 一律内部委托 neurova.core.tenant_scope.resolve_tenant（对 dict 入参行为
# 逐字节一致），文件内不得再留私有租户提取公式。路径相对 neurova/ 根
# （含根级 mcp_ontology_server.py，不限于 api/endpoints/）。
# ---------------------------------------------------------------------------

RESOLVE_HELPER_FILES = (
    "api/endpoints/knowledge_graph_api.py",
    "api/endpoints/knowledge_nl2sql.py",
    "api/endpoints/knowledge_ossie.py",
    "api/endpoints/knowledge_enterprise.py",
    "api/endpoints/knowledge_observability.py",
    "api/endpoints/knowledge_ontology.py",
    "api/endpoints/knowledge_schema_suggester.py",
    "api/endpoints/teams_api.py",
    "mcp_ontology_server.py",
)

# 白名单=保留点：收口后文件内仍允许存在的租户提取行（空白归一化原文）。
# 均为内联调用点缺省回退（响应 dict 字面量/行级序列化/actor 取值），
# 非私有 resolve 辅助，迁移归后续批次；新增/复活的其他提取点即红。
RESOLVE_HELPER_WHITELIST = {
    "api/endpoints/knowledge_graph_api.py": (
        '"tenant_id": str(current_user.get("tenant_id") or "default"),',
    ),
    "api/endpoints/knowledge_ontology.py": (
        'tenantId=str(actor.get("tenant_id") or "default"),',
        'instanceTenant = str(current_user.get("tenant_id") or "default")',
    ),
    "api/endpoints/teams_api.py": (
        'tenant_id=str(team.get("tenant_id") or "default"),',
        '"tenant_id": str(current_user.get("tenant_id") or "default"),',
    ),
}


def _tenantExtractionLines(text: str) -> tuple:
    """文件内全部 ``str(<x>.get("tenant_id") or "default")`` 提取行（空白归一）。"""
    hits = []
    for line in text.splitlines():
        normalized = " ".join(line.split())
        if '.get("tenant_id")' in normalized and 'or "default"' in normalized:
            hits.append(normalized)
    return tuple(hits)


def test_privateTenantResolveHelpersDelegatedToTenantScope():
    """S5 收尾：清单文件的租户提取点须与白名单完全一致。

    私有 resolve 辅助（_tenantOf/_tenant_of/_userTenant）本体一律内部委托
    tenant_scope.resolve_tenant；白名单之外新增/复活的私有提取公式即红。
    """
    for rel in RESOLVE_HELPER_FILES:
        text = (REPO_ROOT / "neurova" / rel).read_text(encoding="utf-8")
        hits = _tenantExtractionLines(text)
        expected = tuple(
            " ".join(fragment.split())
            for fragment in RESOLVE_HELPER_WHITELIST.get(rel, ())
        )
        assert hits == expected, (
            "%s 的租户提取点与白名单不符：实际 %r，期望仅保留 %r"
            "——私有 resolve 辅助须内部委托 tenant_scope.resolve_tenant"
            % (rel, hits, expected)
        )
