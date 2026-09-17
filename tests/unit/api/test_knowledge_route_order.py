"""knowledge 路由有序快照基线（2026-09-16 模块化拆分守护）。

knowledge.py 由单文件拆为聚合器 + 子路由模块，本文件钉死：
1. 全部 34 条路由路径-方法逐一保持（拆分不得丢路由）；
2. FastAPI 按注册顺序匹配：GET /{knowledge_id} 参数路由会遮蔽其后注册的
   字面 GET 路由（/configs /collections 等）——原文件靠物理行序保证字面
   GET 先注册，拆分后 include 顺序必须维持同序，此测试用「参数路由前的
   字面 GET 集合」直接守护遮蔽回归。
"""
import os

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_kb_order_012345")

from neurova.api.endpoints import knowledge as kb

# 拆分前 knowledge.py 的 34 条路由快照（按注册顺序）
_KB_ROUTES = [
    ("", "GET"),
    ("/search", "POST"),
    ("/preview-chunking", "POST"),
    ("", "POST"),
    ("/public-submissions", "GET"),
    ("/conflicts", "GET"),
    ("/conflicts/{conflict_id}/resolve", "POST"),
    ("/deleted", "GET"),
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
]


def _router_routes(router):
    return [(r.path, next(iter(r.methods - {"HEAD", "OPTIONS"})))
            for r in router.routes if getattr(r, "methods", None)]


def test_all_34_routes_present_after_split():
    """拆分后 34 条路由路径-方法逐一保持（多重集相等，不锁注册顺序）。

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
