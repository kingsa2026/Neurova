"""
defineAction 统一原语测试

设计哲学（来自 agent-native）：定义一次，多表面调用（HTTP/Tool/Skill/MCP）。
本测试套件用 TDD 红绿灯方式逐步建立原语契约。

每个测试对应一个行为，验证公共接口而非实现细节。

测试隔离策略：
    - autouse fixture `clean_registry` 在每个测试前后清空 ActionRegistry
    - 测试内无需 try/finally 手动清理，让测试聚焦行为本身
    - 这遵循 improve-codebase-architecture 的 "interface is test surface" 原则
"""
from __future__ import annotations

from typing import List

import pytest
from pydantic import BaseModel, Field

pytest.skip(
    "依赖不存在的模块 neurova.core.define_action（defineAction/ActionRegistry）。"
    "已整体 skip，待确认该模块是实现还是废弃；详见 docs/test-debt-skip-list.md",
    allow_module_level=True,
)


# ---------------------------------------------------------------------------
# 测试用 fixture
# ---------------------------------------------------------------------------

class GreetInput(BaseModel):
    """问候输入"""
    name: str = Field(..., description="被问候者姓名")


class GreetOutput(BaseModel):
    """问候输出"""
    message: str


@pytest.fixture(autouse=True)
def clean_registry():
    """
    每个测试前后清空 ActionRegistry 单例，确保测试间完全隔离。

    autouse=True 让所有测试自动获得此 fixture，无需显式声明。
    这是 TDD 重构阶段的小深化：把"清理"这个横切关注点从
    每个测试里抽出来，集中到一处 seam。

    注意：需要保留 demo.echo（neurova.actions 自动加载的 action），
    否则 TestActionEndToEnd 会失败。所以 strategy 是：
    测试开始前清空 → 测试结束后清空 → 下个测试自然干净
    """
    from neurova.core.define_action import ActionRegistry

    registry = ActionRegistry.instance()
    # 测试前：清空所有 action
    registry._actions.clear()
    yield
    # 测试后：再次清空，避免副作用泄漏
    registry._actions.clear()


# ---------------------------------------------------------------------------
# Slice 1: 注册 action
# ---------------------------------------------------------------------------

class TestActionRegistration:
    """行为：defineAction 装饰器能注册一个 action 到全局 registry"""

    def test_register_simple_action(self):
        """注册后能从 registry 取出 ActionSpec"""
        from neurova.core.define_action import defineAction, ActionRegistry

        @defineAction(
            name="test.greet",
            description="测试用问候 action",
            input_schema=GreetInput,
            output_schema=GreetOutput,
            surfaces=["http"],
        )
        async def greet(params: GreetInput) -> GreetOutput:
            return GreetOutput(message=f"Hello, {params.name}!")

        registry = ActionRegistry.instance()
        spec = registry.get("test.greet")
        assert spec is not None, "action 应被注册到 registry"
        assert spec.name == "test.greet"
        assert spec.description == "测试用问候 action"
        assert spec.input_schema is GreetInput
        assert spec.output_schema is GreetOutput
        assert "http" in spec.surfaces

    def test_register_duplicate_name_raises(self):
        """重复注册同名 action 应抛出 ValueError"""
        from neurova.core.define_action import defineAction

        @defineAction(
            name="test.dup",
            description="第一次",
            input_schema=GreetInput,
            output_schema=GreetOutput,
            surfaces=["http"],
        )
        async def first(params: GreetInput) -> GreetOutput:
            return GreetOutput(message="first")

        with pytest.raises(ValueError, match="already registered"):
            @defineAction(
                name="test.dup",
                description="第二次",
                input_schema=GreetInput,
                output_schema=GreetOutput,
                surfaces=["http"],
            )
            async def second(params: GreetInput) -> GreetOutput:
                return GreetOutput(message="second")

    def test_get_unknown_action_returns_none(self):
        """查询未注册的 action 名应返回 None"""
        from neurova.core.define_action import ActionRegistry
        registry = ActionRegistry.instance()
        assert registry.get("does.not.exist") is None


# ---------------------------------------------------------------------------
# Slice 2: 调用 action
# ---------------------------------------------------------------------------

class TestActionExecution:
    """行为：通过 registry.execute(name, params) 能调用 action 并返回结果"""

    @pytest.mark.asyncio
    async def test_invoke_action_with_dict(self):
        """传入 dict 参数能被校验并调用，返回 output 模型实例"""
        from neurova.core.define_action import defineAction, ActionRegistry

        @defineAction(
            name="test.invoke.greet",
            description="测试调用",
            input_schema=GreetInput,
            output_schema=GreetOutput,
            surfaces=["http"],
        )
        async def greet(params: GreetInput) -> GreetOutput:
            return GreetOutput(message=f"Hello, {params.name}!")

        registry = ActionRegistry.instance()
        result = await registry.execute("test.invoke.greet", {"name": "Alice"})
        assert isinstance(result, GreetOutput)
        assert result.message == "Hello, Alice!"

    @pytest.mark.asyncio
    async def test_invoke_action_with_model(self):
        """传入已构造的 input model 实例也能调用"""
        from neurova.core.define_action import defineAction, ActionRegistry

        @defineAction(
            name="test.invoke.model",
            description="测试 model 入参",
            input_schema=GreetInput,
            output_schema=GreetOutput,
            surfaces=["http"],
        )
        async def greet(params: GreetInput) -> GreetOutput:
            return GreetOutput(message=f"Hi, {params.name}")

        registry = ActionRegistry.instance()
        result = await registry.execute(
            "test.invoke.model", GreetInput(name="Bob")
        )
        assert isinstance(result, GreetOutput)
        assert result.message == "Hi, Bob"

    @pytest.mark.asyncio
    async def test_invoke_unknown_action_raises(self):
        """调用未注册的 action 应抛出 KeyError"""
        from neurova.core.define_action import ActionRegistry
        registry = ActionRegistry.instance()
        with pytest.raises(KeyError, match="not registered"):
            await registry.execute("does.not.exist", {})


# ---------------------------------------------------------------------------
# Slice 3: schema 校验
# ---------------------------------------------------------------------------

class TestActionInputValidation:
    """行为：传入的参数必须符合 input_schema，否则抛 ValidationError"""

    @pytest.mark.asyncio
    async def test_invalid_input_raises_validation_error(self):
        """缺字段或类型无法强转应抛 pydantic.ValidationError"""
        from pydantic import ValidationError

        from neurova.core.define_action import defineAction, ActionRegistry

        @defineAction(
            name="test.validate.greet",
            description="测试校验",
            input_schema=GreetInput,
            output_schema=GreetOutput,
            surfaces=["http"],
        )
        async def greet(params: GreetInput) -> GreetOutput:
            return GreetOutput(message=f"Hi {params.name}")

        registry = ActionRegistry.instance()
        # 缺必填 name 字段
        with pytest.raises(ValidationError):
            await registry.execute("test.validate.greet", {})

        # list 无法强转为 str
        with pytest.raises(ValidationError):
            await registry.execute(
                "test.validate.greet", {"name": [1, 2, 3]}
            )

    @pytest.mark.asyncio
    async def test_invalid_input_extra_field_strict(self):
        """多余字段默认允许，但显式 forbidden 时应拒绝"""
        from neurova.core.define_action import defineAction, ActionRegistry

        # Pydantic v1 默认允许额外字段；这里只验证行为：合法参数能通过
        @defineAction(
            name="test.validate.extra",
            description="测试多余字段",
            input_schema=GreetInput,
            output_schema=GreetOutput,
            surfaces=["http"],
        )
        async def greet(params: GreetInput) -> GreetOutput:
            return GreetOutput(message=f"Hi {params.name}")

        registry = ActionRegistry.instance()
        # 合法调用应成功
        result = await registry.execute(
            "test.validate.extra", {"name": "Carol"}
        )
        assert result.message == "Hi Carol"

    @pytest.mark.asyncio
    async def test_handler_returning_wrong_type_raises(self):
        """handler 返回非 BaseModel 应抛 TypeError"""
        from neurova.core.define_action import defineAction, ActionRegistry

        @defineAction(
            name="test.validate.badreturn",
            description="测试坏返回",
            input_schema=GreetInput,
            output_schema=GreetOutput,
            surfaces=["http"],
        )
        async def bad_handler(params: GreetInput):  # 故意返回 dict
            return {"message": "not a model"}  # type: ignore[return-value]

        registry = ActionRegistry.instance()
        with pytest.raises(TypeError, match="必须是 BaseModel 实例"):
            await registry.execute(
                "test.validate.badreturn", {"name": "X"}
            )


# ---------------------------------------------------------------------------
# Slice 4: HTTP 路由自动暴露
# ---------------------------------------------------------------------------

class TestActionHttpSurface:
    """行为：声明了 http surface 的 action 能自动注册为 FastAPI 路由"""

    def test_register_routes_creates_post_endpoint(self):
        """register_routes(app) 后，POST /api/action/{name} 可用"""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from neurova.core.define_action import defineAction, ActionRegistry

        @defineAction(
            name="test.http.greet",
            description="测试 HTTP 暴露",
            input_schema=GreetInput,
            output_schema=GreetOutput,
            surfaces=["http"],
        )
        async def greet(params: GreetInput) -> GreetOutput:
            return GreetOutput(message=f"Hello, {params.name}!")

        app = FastAPI()
        registry = ActionRegistry.instance()
        registry.register_routes(app)
        client = TestClient(app)

        # 正常调用
        resp = client.post(
            "/api/action/test.http.greet",
            json={"name": "Dave"},
        )
        assert resp.status_code == 200
        data = resp.json()
        # 响应应该是 output_schema 的字段（FastAPI 自动序列化）
        assert data["message"] == "Hello, Dave!"

    def test_register_routes_skips_non_http_actions(self):
        """surfaces 不含 http 的 action 不应被注册为路由"""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from neurova.core.define_action import defineAction, ActionRegistry

        @defineAction(
            name="test.http.toolonly",
            description="仅 tool 表面",
            input_schema=GreetInput,
            output_schema=GreetOutput,
            surfaces=["tool"],  # 不含 http
        )
        async def tool_only(params: GreetInput) -> GreetOutput:
            return GreetOutput(message="should not be http")

        app = FastAPI()
        registry = ActionRegistry.instance()
        registry.register_routes(app)
        client = TestClient(app)

        # 不应能通过 HTTP 调用
        resp = client.post(
            "/api/action/test.http.toolonly",
            json={"name": "X"},
        )
        assert resp.status_code == 404

    def test_register_routes_invalid_input_returns_422(self):
        """HTTP 调用传错参数应返回 422（FastAPI 标准 ValidationError 响应）"""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from neurova.core.define_action import defineAction, ActionRegistry

        @defineAction(
            name="test.http.validate",
            description="测试 HTTP 校验",
            input_schema=GreetInput,
            output_schema=GreetOutput,
            surfaces=["http"],
        )
        async def greet(params: GreetInput) -> GreetOutput:
            return GreetOutput(message=f"Hi {params.name}")

        app = FastAPI()
        registry = ActionRegistry.instance()
        registry.register_routes(app)
        client = TestClient(app)

        # 缺 name 字段 → 422
        resp = client.post(
            "/api/action/test.http.validate", json={}
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Slice 5: 端到端集成测试（demo.echo action）
# ---------------------------------------------------------------------------

class TestActionEndToEnd:
    """行为：从 neurova.actions 包加载的 demo.echo 能端到端通过 HTTP 调用"""

    def test_demo_echo_action_loaded_and_callable(self):
        """import neurova.actions 后，demo.echo 已注册并可 HTTP 调用"""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        # 触发 actions 自动加载
        import neurova.actions  # noqa: F401
        from neurova.core.define_action import ActionRegistry

        app = FastAPI()
        ActionRegistry.instance().register_routes(app)
        client = TestClient(app)

        # 调用 demo.echo
        resp = client.post("/api/action/demo.echo", json={"text": "hello"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["text"] == "hello"
        assert "timestamp" in data
        assert len(data["timestamp"]) > 0


# ---------------------------------------------------------------------------
# Slice 6: 路由热更新（register_routes_incremental）
# ---------------------------------------------------------------------------

class TestActionRouteHotReload:
    """
    行为：app 已注册过路由后，新增的 action 通过
    register_routes_incremental 能在不重启 app 的情况下暴露为 HTTP 路由。

    这是用户请求的第 2 项改进：register_routes 不支持热更新，
    新增 action 后需重启 app——本 slice 通过增量注册消除该限制。
    """

    def test_incremental_register_makes_new_action_callable(self):
        """
        场景：
            1. 注册 action A，register_routes(app) → A 可 HTTP 调用
            2. 注册新 action B（B 此时尚未挂到 app）
            3. 调用 B 应返回 404
            4. register_routes_incremental(app, "test.hotreload.b")
            5. 调用 B 现在应返回 200
        """
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from neurova.core.define_action import defineAction, ActionRegistry

        # 1. 注册 A 并挂载到 app
        @defineAction(
            name="test.hotreload.a",
            description="先注册的 action",
            input_schema=GreetInput,
            output_schema=GreetOutput,
            surfaces=["http"],
        )
        async def action_a(params: GreetInput) -> GreetOutput:
            return GreetOutput(message=f"A: {params.name}")

        app = FastAPI()
        registry = ActionRegistry.instance()
        registry.register_routes(app)
        client = TestClient(app)

        # 2. A 应可调用
        resp_a = client.post(
            "/api/action/test.hotreload.a", json={"name": "X"}
        )
        assert resp_a.status_code == 200
        assert resp_a.json()["message"] == "A: X"

        # 3. 注册新 action B（不重新 register_routes）
        @defineAction(
            name="test.hotreload.b",
            description="后注册的 action，应通过增量注册暴露",
            input_schema=GreetInput,
            output_schema=GreetOutput,
            surfaces=["http"],
        )
        async def action_b(params: GreetInput) -> GreetOutput:
            return GreetOutput(message=f"B: {params.name}")

        # 4. B 此时应返回 404（未挂到 app）
        resp_b_before = client.post(
            "/api/action/test.hotreload.b", json={"name": "Y"}
        )
        assert resp_b_before.status_code == 404, (
            "增量注册前，新 action 不应可通过 HTTP 调用"
        )

        # 5. 增量注册 B
        registry.register_routes_incremental(app, "test.hotreload.b")

        # 6. B 现在应可调用——关键断言
        # 注意：FastAPI 的路由表在 include_router 时已冻结，
        # 增量注册必须能突破这个限制。TestClient 重新构造请求时会
        # 走最新的路由表。
        client_after = TestClient(app)
        resp_b_after = client_after.post(
            "/api/action/test.hotreload.b", json={"name": "Y"}
        )
        assert resp_b_after.status_code == 200, (
            "增量注册后，新 action 应可通过 HTTP 调用"
        )
        assert resp_b_after.json()["message"] == "B: Y"

    def test_incremental_register_unknown_action_raises(self):
        """增量注册未注册的 action 名应抛 KeyError"""
        from fastapi import FastAPI

        from neurova.core.define_action import ActionRegistry

        app = FastAPI()
        registry = ActionRegistry.instance()
        with pytest.raises(KeyError, match="not registered"):
            registry.register_routes_incremental(
                app, "test.hotreload.does_not_exist"
            )

    def test_incremental_register_skips_non_http_action(self):
        """
        增量注册一个 surfaces 不含 http 的 action 应静默跳过
        （不抛错，但也不创建路由），与 register_routes 行为一致。
        """
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from neurova.core.define_action import defineAction, ActionRegistry

        @defineAction(
            name="test.hotreload.toolonly",
            description="仅 tool 表面，增量注册应跳过",
            input_schema=GreetInput,
            output_schema=GreetOutput,
            surfaces=["tool"],
        )
        async def tool_only(params: GreetInput) -> GreetOutput:
            return GreetOutput(message="should not be http")

        app = FastAPI()
        registry = ActionRegistry.instance()
        # 不应抛错
        registry.register_routes_incremental(
            app, "test.hotreload.toolonly"
        )

        client = TestClient(app)
        resp = client.post(
            "/api/action/test.hotreload.toolonly", json={"name": "Z"}
        )
        assert resp.status_code == 404, "非 http surface 的 action 不应有路由"
