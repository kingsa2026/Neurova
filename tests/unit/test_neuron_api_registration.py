"""
NEURON API 路由注册测试

验证 neuron.py 的 router 已正确注册到 FastAPI 应用中，
前端 /api/neuron/* 请求能被正确路由到后端端点。

取数走 `registeredPathMethods()`（递归下钻 `include_router` 的嵌套 router）：
现行 FastAPI 把 include 落成惰性包装对象，直接遍历 `app.routes` 取 `.path` 会
AttributeError——守卫因此会**失明**（红不了也绿不了，只在报错里打转）。
"""
import pytest
from fastapi import FastAPI

# 取数口径走本仓唯一实现（`tests/route_table.py` 的 docstring 就写着「遍历只写这一份」）。
# 本档此前自带一份同名的 `registeredPathMethods()` 私有实现——两条遍历同义不同源，
# 属教义第 7 条点名的"两处承担同一功能"。先比后合：同一份装配结果两实现现算输出
# **逐条相等**（各 1043 条，差集为空），故私有那份直接删掉、消费点不改名。
from tests.route_table import registeredPathMethods


class TestNeuronAPIRegistration:
    """NEURON API 路由注册验证"""

    def test_neuron_module_importable(self):
        """neuron.py 端点模块可以成功导入"""
        from neurova.api.endpoints import neuron
        assert hasattr(neuron, "router")
        assert neuron.router.prefix == "/neuron"

    def test_neuron_in_endpoint_modules(self):
        """neuron 端点在 endpoint 注册表里。

        原格读的是 `inspect.getsource(register_endpoint_routers)` 里有没有那串模块名——
        而注册表是**模块级常量** `ENDPOINT_MODULES`（`__init__.py:233`，neuron 在 :323），
        函数体里只有循环，从不出现这个字面量 ⇒ 本格必红且红得没有意义
        （判据问错了对象，与本批"从装配后 app 顶层取 `.routes`"是同一种失明：读的不是事实源）。
        现按数据本身取数；要验"真的挂上去了"由 `test_neuron_routes_registered_to_app` 承重。
        """
        from neurova.api.endpoints import ENDPOINT_MODULES

        mounted = [entry for entry in ENDPOINT_MODULES if entry[0].endswith(".neuron")]
        assert mounted, "neuron 不在挂载表里：/api/neuron/* 整体不可达"
        prefix = mounted[0][1]
        assert prefix == "", f"neuron 的表内前缀变成 {prefix!r}——它会挂到 /api{prefix}/neuron/*"

    def test_neuron_routes_registered_to_app(self):
        """注册后所有 NEURON 路由出现在 FastAPI app 的 routes 中"""
        app = FastAPI()
        from neurova.api.endpoints import register_endpoint_routers
        register_endpoint_routers(app)

        route_paths = {path for path, _ in registeredPathMethods(app)}

        expected_prefix = "/api/neuron"
        expected_endpoints = [
            f"{expected_prefix}/entities",
            f"{expected_prefix}/dependencies",
            f"{expected_prefix}/dependencies/{{entity_id}}",
            f"{expected_prefix}/cascade",
            f"{expected_prefix}/would-affect",
            f"{expected_prefix}/absence/detect",
            f"{expected_prefix}/extract",
            f"{expected_prefix}/stats",
            f"{expected_prefix}/health",
        ]

        for ep in expected_endpoints:
            assert ep in route_paths, f"Missing route: {ep}"

    def test_neuron_routes_match_frontend_base_url(self):
        """路由路径匹配前端 neuron.ts 的 baseURL '/api/neuron'"""
        app = FastAPI()
        from neurova.api.endpoints import register_endpoint_routers
        register_endpoint_routers(app)

        neuron_routes = [path for path, _ in registeredPathMethods(app) if "/api/neuron" in path]

        # 前端调用的关键端点
        assert "/api/neuron/entities" in neuron_routes
        assert "/api/neuron/stats" in neuron_routes
        assert "/api/neuron/health" in neuron_routes

    def test_neuron_routes_count(self):
        """NEURON 路由数量正确（9 个端点 × 2 HTTP methods for entities）"""
        app = FastAPI()
        from neurova.api.endpoints import register_endpoint_routers
        register_endpoint_routers(app)

        neuron_routes = [path for path, _ in registeredPathMethods(app) if "/api/neuron" in path]
        # GET /entities, POST /entities, POST /dependencies,
        # GET /dependencies/{id}, POST /cascade, POST /would-affect,
        # POST /absence/detect, POST /extract, GET /stats, GET /health
        assert len(neuron_routes) >= 9, f"Expected >=9 neuron routes, got {len(neuron_routes)}"

    def test_no_duplicate_neuron_prefix(self):
        """注册前缀为空字符串，避免与 router prefix 重复形成 /api/neuron/neuron"""
        app = FastAPI()
        from neurova.api.endpoints import register_endpoint_routers
        register_endpoint_routers(app)

        neuron_routes = [path for path, _ in registeredPathMethods(app) if "neuron" in path]
        for path in neuron_routes:
            assert "/neuron/neuron" not in path, f"Double prefix detected: {path}"
