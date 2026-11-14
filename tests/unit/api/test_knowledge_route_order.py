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
# 2026-11-05 升级计划随批补登记 B2/B5/B6 四条（validate / pipeline 两条 / export.ttl）。
_KB_ROUTES = [
    # 2026-11-14 P2-9 随批再收口：以 kb.router 实测多重集重登记（此前清单停在
    # 2026-11-05，C2 的 llm-advice、U5 的 webhook/* 与 ontology 后续路由均未登记，
    # 守护带病漂红）。此后新增路由必须随批更新本清单（多重集相等，不锁注册顺序）。
    ('', 'GET'),
    ('', 'POST'),
    ('/alias-candidates', 'GET'),
    ('/alias-candidates/{candidate_id}/approve', 'POST'),
    ('/alias-candidates/{candidate_id}/reject', 'POST'),
    ('/annotations', 'GET'),
    ('/annotations', 'POST'),
    ('/annotations/export', 'GET'),
    ('/annotations/{annotation_id}', 'DELETE'),
    ('/annotations/{annotation_id}', 'PUT'),
    ('/audit/conflict-eval', 'POST'),
    ('/audit/conflict-metrics', 'GET'),
    ('/audit/conflict-metrics', 'POST'),
    ('/audit/entry-feedback', 'GET'),
    ('/audit/evaluation/compare', 'POST'),
    ('/audit/expiry', 'POST'),
    ('/audit/index-health', 'GET'),
    ('/audit/ingest', 'GET'),
    ('/audit/ingest/resume', 'POST'),
    ('/audit/lifecycle', 'GET'),
    ('/audit/redundancy', 'GET'),
    ('/audit/reindex', 'POST'),
    ('/audit/retrieval-metrics', 'GET'),
    ('/collections', 'GET'),
    ('/collections', 'POST'),
    ('/collections/{mapping_id}', 'DELETE'),
    ('/configs', 'GET'),
    ('/configs', 'POST'),
    ('/configs/{config_id}', 'DELETE'),
    ('/configs/{config_id}', 'GET'),
    ('/configs/{config_id}', 'PUT'),
    ('/configs/{config_id}/sync', 'POST'),
    ('/conflicts', 'GET'),
    ('/conflicts/{conflict_id}', 'GET'),
    ('/conflicts/{conflict_id}/llm-advice', 'POST'),
    ('/conflicts/{conflict_id}/resolve', 'POST'),
    ('/deleted', 'GET'),
    ('/documents/{document_id}', 'GET'),
    ('/enterprise/sources', 'GET'),
    ('/enterprise/sources', 'POST'),
    ('/enterprise/sources/{source_id}', 'DELETE'),
    ('/enterprise/sources/{source_id}', 'GET'),
    ('/enterprise/sources/{source_id}/health', 'GET'),
    ('/enterprise/sources/{source_id}/ingest', 'POST'),
    ('/enterprise/sources/{source_id}/media', 'POST'),
    ('/evaluation/baseline', 'GET'),
    ('/facts/baselines', 'GET'),
    ('/facts/baselines', 'POST'),
    ('/facts/{fact_id}/adoption', 'POST'),
    ('/facts/{fact_id}/history', 'GET'),
    ('/facts/{fact_id}/lineage', 'GET'),
    ('/facts/{fact_id}/rollback', 'POST'),
    ('/facts/{fact_id}/turtle', 'GET'),
    ('/foundation/expiry', 'POST'),
    ('/foundation/integrity', 'GET'),
    ('/foundation/usage', 'GET'),
    ('/geo', 'GET'),
    ('/graph/instances', 'POST'),
    ('/import', 'POST'),
    ('/import-url', 'POST'),
    ('/ingress-tasks', 'GET'),
    ('/ingress-tasks/{task_id}', 'GET'),
    ('/ingress-tasks/{task_id}/cancel', 'POST'),
    ('/mcp/sources', 'GET'),
    ('/mcp/sources', 'POST'),
    ('/mcp/sources/tools', 'POST'),
    ('/mcp/sources/{source_id}', 'DELETE'),
    ('/mcp/sources/{source_id}', 'PUT'),
    ('/mcp/sources/{source_id}/pull', 'POST'),
    ('/observability/default-off', 'GET'),
    ('/ontology/abduce', 'POST'),
    ('/ontology/accountability', 'GET'),
    ('/ontology/actions', 'GET'),
    ('/ontology/actions', 'POST'),
    ('/ontology/actions/{action_id}', 'DELETE'),
    ('/ontology/artifacts', 'GET'),
    ('/ontology/artifacts/{sha256}/content', 'GET'),
    ('/ontology/artifacts/{sha256}/verify', 'GET'),
    ('/ontology/blocking-stats', 'GET'),
    ('/ontology/chunk-strategies', 'GET'),
    ('/ontology/chunk-strategies', 'POST'),
    ('/ontology/chunk-strategies/{strategy_id}', 'DELETE'),
    ('/ontology/communities', 'GET'),
    ('/ontology/communities/detect', 'POST'),
    ('/ontology/communities/refresh', 'POST'),
    ('/ontology/community-search', 'POST'),
    ('/ontology/conflict-policy/{term_id}', 'GET'),
    ('/ontology/cq-matrix', 'GET'),
    ('/ontology/decisions', 'GET'),
    ('/ontology/decisions', 'POST'),
    ('/ontology/decisions/precedents', 'GET'),
    ('/ontology/decisions/{decision_id}/links', 'POST'),
    ('/ontology/decisions/{decision_id}/trace', 'GET'),
    ('/ontology/derivations/{fact_id}', 'GET'),
    ('/ontology/domain-packs', 'GET'),
    ('/ontology/domain-packs/{pack_id}/attribution', 'GET'),
    ('/ontology/domain-packs/{pack_id}/import', 'POST'),
    ('/ontology/domain-packs/{pack_id}/integrity', 'GET'),
    ('/ontology/export.csv', 'GET'),
    ('/ontology/export.cypher', 'GET'),
    ('/ontology/export.gexf', 'GET'),
    ('/ontology/export.graphml', 'GET'),
    ('/ontology/export.jsonld', 'GET'),
    ('/ontology/export.owl', 'GET'),
    ('/ontology/export.prov', 'GET'),
    ('/ontology/export.shacl', 'GET'),
    ('/ontology/export.ttl', 'GET'),
    ('/ontology/functions', 'GET'),
    ('/ontology/functions', 'POST'),
    ('/ontology/functions/{function_id}', 'DELETE'),
    ('/ontology/functions/{function_id}/compute', 'POST'),
    ('/ontology/impact', 'GET'),
    ('/ontology/import-artifact/latest', 'GET'),
    ('/ontology/import-rdf', 'POST'),
    ('/ontology/iri/{iri:path}', 'GET'),
    ('/ontology/namespaces', 'GET'),
    ('/ontology/pipeline/diff', 'GET'),
    ('/ontology/pipeline/rollback', 'POST'),
    ('/ontology/pipeline/run', 'POST'),
    ('/ontology/quality', 'GET'),
    ('/ontology/relation-candidates', 'GET'),
    ('/ontology/relation-candidates/{candidate_id}/approve', 'POST'),
    ('/ontology/relation-candidates/{candidate_id}/reject', 'POST'),
    ('/ontology/rules', 'POST'),
    ('/ontology/rules/{rule_id}', 'DELETE'),
    ('/ontology/rules/{rule_id}', 'PUT'),
    ('/ontology/schema', 'GET'),
    ('/ontology/settings', 'GET'),
    ('/ontology/settings', 'PUT'),
    ('/ontology/shapes', 'GET'),
    ('/ontology/shapes', 'POST'),
    ('/ontology/shapes/{shape_id}', 'DELETE'),
    ('/ontology/shapes/{shape_id}', 'PUT'),
    ('/ontology/simulations', 'GET'),
    ('/ontology/simulations', 'POST'),
    ('/ontology/sparql', 'POST'),
    ('/ontology/state-machines', 'GET'),
    ('/ontology/state-machines', 'POST'),
    ('/ontology/state-machines/{term_id}', 'DELETE'),
    ('/ontology/terms', 'GET'),
    ('/ontology/terms', 'POST'),
    ('/ontology/terms/{term_id}', 'DELETE'),
    ('/ontology/terms/{term_id}', 'PUT'),
    ('/ontology/validate', 'POST'),
    ('/ontology/webhook/config', 'GET'),
    ('/ontology/webhook/dedup-stats', 'GET'),
    ('/ontology/webhook/receive', 'POST'),
    ('/ontology/webhook/rotate', 'POST'),
    ('/ontology/webhook/simulate', 'POST'),
    ('/preview-chunking', 'POST'),
    ('/public-submissions', 'GET'),
    ('/search', 'POST'),
    ('/{knowledge_id}', 'DELETE'),
    ('/{knowledge_id}', 'GET'),
    ('/{knowledge_id}', 'PUT'),
    ('/{knowledge_id}/chunks', 'GET'),
    ('/{knowledge_id}/chunks/{index}', 'PUT'),
    ('/{knowledge_id}/chunks/{index}/revisions', 'GET'),
    ('/{knowledge_id}/restore', 'POST'),
    ('/{knowledge_id}/review-public', 'POST'),
    ('/{knowledge_id}/revisions', 'GET'),
    ('/{knowledge_id}/revisions/{revision_index}/rollback', 'POST'),
    ('/{knowledge_id}/share', 'POST'),
    ('/{knowledge_id}/submit-public', 'POST'),
    ('/{knowledge_id}/unshare', 'POST'),
    ('/{knowledge_id}/versions', 'GET'),
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
