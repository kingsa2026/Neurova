"""S5 租户过滤集中化试点：neurova/core/tenant_scope.py 助手单测 + 三形态行为一致断言。

判据（拍板 D-S3：试点三处、行为逐字节一致）：
- resolve_tenant / tenant_matches / tenant_sql_where 覆盖三种散落形态的共性；
- 每种形态都用**迁移前现状公式**与助手公式对同输入比结果，钉住逐字节一致；
- 缺省语义与 api/auth.py 的身份缺省同源：无 tenant_id 落 "default"（不改 auth.py）。
"""

from neurova.core.tenant_scope import resolve_tenant, tenant_matches, tenant_sql_where


# ---------------------------------------------------------------------------
# resolve_tenant：缺省 default 语义（含空/None 处理）
# ---------------------------------------------------------------------------

def test_resolveTenantDictValuePassthrough():
    assert resolve_tenant({"tenant_id": "t1"}) == "t1"


def test_resolveTenantMissingKeyFallsBackDefault():
    assert resolve_tenant({"user_id": "u1"}) == "default"


def test_resolveTenantNoneAndEmptyFallBackDefault():
    assert resolve_tenant(None) == "default"
    assert resolve_tenant({}) == "default"
    assert resolve_tenant({"tenant_id": None}) == "default"
    assert resolve_tenant({"tenant_id": ""}) == "default"
    assert resolve_tenant({"tenant_id": 0}) == "default"


def test_resolveTenantBlankStringKeptAsIs():
    """现状公式（…or "default"）对非空字符串原样保留——空白串不落 default。"""
    assert resolve_tenant({"tenant_id": "   "}) == "   "


def test_resolveTenantObjectAttrForm():
    class _UserObj:
        tenant_id = "tobj"

    class _UserBare:
        pass

    assert resolve_tenant(_UserObj()) == "tobj"
    assert resolve_tenant(_UserBare()) == "default"


def test_resolveTenantMatchesLegacyUserTenantFormula():
    """形态二现状公式（teams_api._userTenant）逐字节一致。"""

    def legacyUserTenant(user):
        return str((user or {}).get("tenant_id") or "default")

    samples = (None, {}, {"tenant_id": "t1"}, {"tenant_id": ""},
               {"tenant_id": None}, {"tenant_id": 0}, {"tenant_id": "t2"})
    for u in samples:
        assert resolve_tenant(u) == legacyUserTenant(u)


# ---------------------------------------------------------------------------
# tenant_sql_where：形态一（agent_run_store.list_runs_for_audit 的 SQL 拼接）
# ---------------------------------------------------------------------------

def test_sqlWhereNormalReturnsColumnAndParam():
    assert tenant_sql_where("t1") == ("tenant_id=?", ["t1"])


def test_sqlWhereAliasPrependsPrefix():
    assert tenant_sql_where("t1", alias="r") == ("r.tenant_id=?", ["t1"])
    assert tenant_sql_where("t1", alias="agent_runs") == ("agent_runs.tenant_id=?", ["t1"])


def test_sqlWhereBlankMeansNoFilter():
    assert tenant_sql_where("") == ("", [])
    assert tenant_sql_where(None) == ("", [])
    assert tenant_sql_where("   ") == ("", [])


def test_sqlWhereMatchesLegacy拼接公式():
    """形态一现状公式：非空才追加 where+param，参数取 str(tenant_id).strip()。"""

    def legacyWhere(tenant_id):
        where, params = [], []
        if str(tenant_id or "").strip():
            where.append("tenant_id=?")
            params.append(str(tenant_id).strip())
        return where, params

    samples = ("t1", "", None, "   ", "  t2  ", 0, "0")
    for tid in samples:
        # 迁移后消费方式：片段非空才 where.append + params.extend
        where, params = [], []
        clause, clauseParams = tenant_sql_where(tid)
        if clause:
            where.append(clause)
            params.extend(clauseParams)
        legacyWhereList, legacyParams = legacyWhere(tid)
        assert where == legacyWhereList
        assert params == legacyParams


# ---------------------------------------------------------------------------
# tenant_matches：形态二（teams_api.list_teams 内存谓词）
#                 与形态三（knowledge_core._factStoreForTenant 行级比较）统一判定
# ---------------------------------------------------------------------------

def test_tenantMatchesSameTenantTrue():
    assert tenant_matches({"tenant_id": "t1"}, {"tenant_id": "t1"}) is True


def test_tenantMatchesCrossTenantFalse():
    assert tenant_matches({"tenant_id": "t1"}, {"tenant_id": "t2"}) is False


def test_tenantMatchesBothDefaultWhenMissing():
    assert tenant_matches({}, {}) is True
    assert tenant_matches({"user_id": "u1"}, {"name": "row"}) is True


def test_tenantMatchesNoneRowNeverMatches():
    """形态三现状先判 fact is None（404 短路）；row=None 不该被判成同租户。"""
    assert tenant_matches({"tenant_id": "default"}, None) is False
    assert tenant_matches(None, None) is False


def test_tenantMatchesLegacy行级取值比较公式():
    """形态三现状公式：str(user.get(...) or "default") == str(row.get(...) or "default")。"""

    def legacyRowCompare(user, row):
        return str(user.get("tenant_id") or "default") == str(row.get("tenant_id") or "default")

    cases = [
        ({"tenant_id": "t1"}, {"tenant_id": "t1"}),
        ({"tenant_id": "t1"}, {"tenant_id": "t2"}),
        ({}, {"tenant_id": None}),
        ({"tenant_id": ""}, {}),
        ({"tenant_id": "default"}, {"tenant_id": "default"}),
        ({"tenant_id": "   "}, {"tenant_id": "   "}),
    ]
    for u, row in cases:
        assert tenant_matches(u, row) == legacyRowCompare(u, row)
