# -*- coding: utf-8 -*-
"""装配后路由表取数（跨 FastAPI 版本的唯一遍历口径）。

根因（Issue #112 后续·未接线断点）：现行 FastAPI 的 `include_router` 不再把子路由
**就地摊平**，而是往 `routes` 追加一个惰性包装对象（`_IncludedRouter`，带
`original_router` / `include_context`）。测试若直接 `for r in app.routes: r.path`
就会 `AttributeError`，或（用 `hasattr` 兜底时）**静默取空集**——守卫因此失明：
既报不出断点，也拿不到读数。`/api/evolution`、`/api/rag` 这两个「挂了零条路由」
的前缀能长期存活，正是因为没有任何守卫真正把装配后的路由表看全。

故遍历只写这一份，判据在装配侧（`neurova/api/app.py` 的挂载表、
`scripts/generate_api_inventory.py` 的挂载问题检测），测试只从这里取数。
"""


def _walkMounts(items, prefix=""):
    """装配结果 → `(完整路径, 叶子路由)` —— 包装层只贡献前缀，不产出行。"""
    for route in items:
        inner = getattr(route, "original_router", None)
        if inner is not None:
            context = getattr(route, "include_context", None)
            yield from _walkMounts(getattr(inner, "routes", []),
                                   prefix + (context.prefix if context else ""))
            continue
        path = getattr(route, "path", None)
        if path is not None:
            yield prefix + path, route


def mountedLeafRoutes(app) -> list:
    """装配后 `(完整路径, 叶子路由对象)` 列表——需要端点/依赖/快照时用它。"""
    return list(_walkMounts(getattr(app, "routes", [])))


def registeredPaths(app) -> list:
    """装配后应用/路由器的全部叶子路径（含挂载层前缀）。"""
    return [path for path, _ in _walkMounts(getattr(app, "routes", []))]


def registeredPathMethods(app) -> list:
    """装配后路由 `(路径, 方法集合)` ——方法一并取回，「路径在、方法不对」也是断点。"""
    return [(path, frozenset(getattr(route, "methods", None) or ()))
            for path, route in _walkMounts(getattr(app, "routes", []))]


def leafRoutes(app) -> list:
    """装配后的叶子路由对象（已摊平，含 `.endpoint` / `.name` / `.dependant`）。"""
    return [route for _, route in _walkMounts(getattr(app, "routes", []))]
