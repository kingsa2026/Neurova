"""knowledge 路由有序快照基线（2026-09-16 模块化拆分守护）。

knowledge.py 由单文件拆为聚合器 + 子路由模块，本文件钉死：
1. 全部路由路径-方法逐一保持（清单即 `_KB_ROUTES`，拆分不得丢路由）；
2. FastAPI 按注册顺序匹配：GET /{knowledge_id} 参数路由会遮蔽其后注册的
   字面 GET 路由（/configs /collections 等）——原文件靠物理行序保证字面
   GET 先注册，拆分后 include 顺序必须维持同序，此测试用「参数路由前的
   字面 GET 集合」直接守护遮蔽回归。
"""
import os

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_kb_order_012345")

from neurova.api.endpoints import knowledge as kb

from tests.route_table import registeredPathMethods

# knowledge.py 聚合路由多重集快照。2026-10-30 随 W2 审批面刷新：
# 此前快照停在拆分时的 34 条+评测路由，10-24 批次的 /ontology/* /mcp/sources*
# /geo /graph/instances 等一直未登记（守护带病漂红）；本次以 kb.router 实测
# 84 条收口，此后新增路由必须随批更新本清单（多重集相等，不锁注册顺序）。
_KB_ROUTES = [
    ("", "GET"), ("", "POST"),
    ("/search", "POST"),
    ("/preview-chunking", "POST"),
    ("/public-submissions", "GET"),
    ("/conflicts", "GET"),
    ("/conflicts/{conflict_id}", "GET"),
    ("/conflicts/{conflict_id}/resolve", "POST"),
    ("/evaluation/baseline", "GET"),
    ("/audit/redundancy", "GET"),
    ("/audit/lifecycle", "GET"),
    ("/audit/ingest", "GET"),
    ("/audit/ingest/resume", "POST"),
    ("/audit/conflict-metrics", "GET"), ("/audit/conflict-metrics", "POST"),
    ("/audit/conflict-eval", "POST"),
    ("/audit/evaluation/compare", "POST"),
    ("/audit/entry-feedback", "GET"),
    ("/audit/retrieval-metrics", "GET"),
    ("/audit/index-health", "GET"),
    ("/audit/reindex", "POST"),
    ("/audit/expiry", "POST"),
    ("/foundation/usage", "GET"),
    ("/foundation/integrity", "GET"),
    ("/foundation/expiry", "POST"),  # §6-103 起的整库到期收敛开关（管理员）
    ("/facts/{fact_id}/lineage", "GET"),
    ("/facts/{fact_id}/turtle", "GET"),
    ("/facts/{fact_id}/adoption", "POST"),
    ("/facts/{fact_id}/history", "GET"),
    ("/facts/{fact_id}/rollback", "POST"),
    ("/facts/baselines", "GET"), ("/facts/baselines", "POST"),
    ("/deleted", "GET"),
    ("/documents/{document_id}", "GET"),
    ("/{knowledge_id}/restore", "POST"),
    ("/{knowledge_id}/revisions", "GET"),
    ("/{knowledge_id}/chunks", "GET"),
    ("/{knowledge_id}/chunks/{index}/revisions", "GET"),
    ("/{knowledge_id}/chunks/{index}", "PUT"),
    ("/{knowledge_id}/share", "POST"),
    ("/{knowledge_id}/unshare", "POST"),
    ("/{knowledge_id}/submit-public", "POST"),
    ("/{knowledge_id}/review-public", "POST"),
    ("/configs", "GET"), ("/configs", "POST"),
    ("/configs/{config_id}", "GET"), ("/configs/{config_id}", "PUT"), ("/configs/{config_id}", "DELETE"),
    ("/configs/{config_id}/sync", "POST"),
    ("/collections", "GET"), ("/collections", "POST"),
    ("/collections/{mapping_id}", "DELETE"),
    ("/ingress-tasks", "GET"),
    ("/ingress-tasks/{task_id}", "GET"),
    ("/ingress-tasks/{task_id}/cancel", "POST"),
    ("/{knowledge_id}", "GET"), ("/{knowledge_id}", "PUT"), ("/{knowledge_id}", "DELETE"),
    ("/import", "POST"),
    ("/import-url", "POST"),
    # Issue #68 收口：精准回复命中表（/annotations*）由 console 域迁入知识域
    # ——唯一消费者是 KnowledgePage 的 AnnotationDrawer，标注是知识资产。
    # 注册顺序位于 GET /{knowledge_id} 之前（见下一测试的遮蔽守护）。
    ("/annotations", "GET"),
    ("/annotations", "POST"),
    ("/annotations/{annotation_id}", "PUT"),
    ("/annotations/{annotation_id}", "DELETE"),
    ("/annotations/export", "GET"),
    # 2026-10-24 批次：本体/实例编辑/租户化（S1–S3）+ GIS + MCP 信息源
    ("/ontology/schema", "GET"),
    ("/ontology/impact", "GET"),
    ("/ontology/terms", "POST"),
    ("/ontology/terms/{term_id}", "PUT"),
    ("/ontology/terms/{term_id}", "DELETE"),
    ("/ontology/rules", "POST"),
    ("/ontology/rules/{rule_id}", "PUT"),
    ("/ontology/rules/{rule_id}", "DELETE"),
    ("/graph/instances", "POST"),
    ("/geo", "GET"),
    ("/mcp/sources", "GET"), ("/mcp/sources", "POST"),
    ("/mcp/sources/tools", "POST"),
    ("/mcp/sources/{source_id}", "PUT"), ("/mcp/sources/{source_id}", "DELETE"),
    ("/mcp/sources/{source_id}/pull", "POST"),
    # specs/2026-10-30 W2：检索脱靶候选别名审批面（字面 GET，注册于参数路由之前）
    ("/alias-candidates", "GET"),
    ("/alias-candidates/{candidate_id}/approve", "POST"),
    ("/alias-candidates/{candidate_id}/reject", "POST"),
]


def _router_routes(router):
    return [(path, method)
            for path, methods in registeredPathMethods(router)
            for method in methods - {"HEAD", "OPTIONS"}]


def test_allRoutesPresentAfterSplit():
    """拆分后全部路由路径-方法逐一保持（多重集相等，不锁注册顺序）。

    除遮蔽顺序契约外（见下一测试），FastAPI 对同一路由集合的注册顺序
    不产生行为差异——锁全序是过度规约，会迫使子模块间虚假耦合。
    """
    assert sorted(_router_routes(kb.router)) == sorted(_KB_ROUTES)


def test_literal_get_routes_registered_before_parameterized_get():
    """遮蔽守护：全部字面 GET 必须先于 GET /{knowledge_id} 注册。

    FastAPI 按注册顺序匹配，GET /{knowledge_id} 若先注册会把
    /configs /collections /public-submissions /deleted /ingress-tasks 等
    字面 GET 吞成 404（knowledge_id="configs"）。原文件靠物理行序保证，
    拆分后靠 include 顺序维持——此断言与行序解耦，直接守护语义。
    """
    routes = _router_routes(kb.router)
    param_get_idx = routes.index(("/{knowledge_id}", "GET"))
    literal_gets = [r for r in routes if r[1] == "GET" and "{" not in r[0]]
    assert literal_gets, "字面 GET 路由集合不应为空"
    for path, method in literal_gets:
        assert routes.index((path, method)) < param_get_idx, (
            f"字面 GET {path} 注册在 GET /{{knowledge_id}} 之后 → 会被遮蔽"
        )
