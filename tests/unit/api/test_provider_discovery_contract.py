"""模型发现链路对齐 QwenPaw — 契约测试（红绿灯 TDD）

锁定契约（对齐 QwenPaw provider_discovery.DiscoveryModelsResponse）：
1. discover 返回结构化元数据：success / models / discovered_count /
   last_synced_at / used_static_fallback / error_kind / message；
2. 失败不再静默空列表：error_kind 分类 + used_static_fallback=True
   （回退配置存量）；
3. 成功后 last_synced_at 持久化到 ProviderConfig；
4. GET /api/v1/providers/{id}/models/discover 响应 data 携带全部新字段；
5. POST /api/v1/models/probe-multimodal 支持 force 参数（真探测）。
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.llm.provider_manager import LLMProviderManager, reset_provider_manager


@pytest.fixture
def mgr(tmp_path):
    reset_provider_manager()
    m = LLMProviderManager(config={"config_path": str(tmp_path / "providers.json")})
    m.add_provider(
        name="T",
        provider="openai",
        base_url="https://example.test/v1",
        api_key="sk-test-1234567890",
        models=["existing-1"],
    )
    # 内置种子商合并后 keys[0] 不一定是测试商 — 用返回 id 精确定位
    m._pid = [p.id for p in m.list_providers() if p.name == "T"][0]
    yield m
    reset_provider_manager()


class TestDiscoverProviderModelsStructured:
    @pytest.mark.asyncio
    async def test_success_result_shape(self, mgr):
        def _Model(mid):
            from neurova.llm.providers.types import ModelInfo as _MI
            return _MI(id=mid, name=mid)

        class _Inst:
            async def fetch_models(self):
                return [_Model("existing-1"), _Model("new-1"), _Model("new-2")]

        mgr._get_provider_instance = lambda pid: _Inst()
        result = await mgr.discover_provider_models(mgr._pid)

        assert result["success"] is True
        assert {m.id for m in result["models"]} >= {"existing-1", "new-1", "new-2"}
        assert result["discovered_count"] == 2, "discovered_count = 本次新增数"
        assert result["last_synced_at"], "成功后应有同步时间"
        assert result["used_static_fallback"] is False
        assert result["error_kind"] is None

    @pytest.mark.asyncio
    async def test_last_synced_at_persisted(self, mgr):
        def _Model(mid):
            from neurova.llm.providers.types import ModelInfo as _MI
            return _MI(id=mid, name=mid)

        class _Inst:
            async def fetch_models(self):
                return [_Model("existing-1")]

        mgr._get_provider_instance = lambda pid: _Inst()
        await mgr.discover_provider_models(mgr._pid)

        provider = mgr.get_provider(mgr._pid)
        assert provider.models_last_synced_at, "last_synced_at 应持久化到 ProviderConfig"

    @pytest.mark.asyncio
    async def test_failure_returns_error_kind_and_fallback(self, mgr):
        class _Inst:
            async def fetch_models(self):
                raise ConnectionError("network unreachable")

        mgr._get_provider_instance = lambda pid: _Inst()
        result = await mgr.discover_provider_models(mgr._pid)

        assert result["success"] is False
        assert result["error_kind"] == "network"
        assert result["used_static_fallback"] is True, "失败应回退配置存量"
        assert [m.id for m in result["models"]] == ["existing-1"]

    @pytest.mark.asyncio
    async def test_auth_failure_error_kind(self, mgr):
        class _Inst:
            async def fetch_models(self):
                err = RuntimeError("401 unauthorized")
                err.status_code = 401
                raise err

        mgr._get_provider_instance = lambda pid: _Inst()
        result = await mgr.discover_provider_models(mgr._pid)

        assert result["success"] is False
        assert result["error_kind"] == "authentication"

    def test_fetch_provider_models_keeps_list_contract(self, mgr):
        """旧消费方（multi_model_client 404 重连）依赖 List 契约 — 保持不变。"""
        import asyncio

        def _Model(mid):
            from neurova.llm.providers.types import ModelInfo as _MI
            return _MI(id=mid, name=mid)

        class _Inst:
            async def fetch_models(self):
                return [_Model("existing-1")]

        mgr._get_provider_instance = lambda pid: _Inst()
        models = asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
            mgr.fetch_provider_models(mgr._pid)
        )
        assert isinstance(models, list)
        assert all(hasattr(m, "id") for m in models)


# ---------------------------------------------------------------------------
# API 层契约
# ---------------------------------------------------------------------------

@pytest.fixture
def client(mgr):
    from neurova.api.auth import get_current_user
    from neurova.api.endpoints import provider as provider_ep

    app = FastAPI()
    app.include_router(provider_ep.router, prefix="/api/v1/providers")
    original = provider_ep._get_provider_manager
    provider_ep._get_provider_manager = lambda current_user=None: mgr
    app.dependency_overrides[get_current_user] = lambda: {"user_id": "test", "role": "admin"}
    with TestClient(app) as c:
        yield c
    provider_ep._get_provider_manager = original
    app.dependency_overrides.clear()


class TestDiscoverEndpointContract:
    def test_discover_response_metadata_fields(self, client, mgr):
        def _Model(mid):
            from neurova.llm.providers.types import ModelInfo as _MI
            return _MI(id=mid, name=mid)

        class _Inst:
            async def fetch_models(self):
                return [_Model("existing-1"), _Model("new-1")]

        mgr._get_provider_instance = lambda pid: _Inst()
        resp = client.get(f"/api/v1/providers/{mgr._pid}/models/discover")
        assert resp.status_code == 200
        data = resp.json()["data"]
        for key in (
            "models",
            "success",
            "discovered_count",
            "last_synced_at",
            "used_static_fallback",
            "error_kind",
        ):
            assert key in data, f"discover 响应缺 {key}"


class TestProbeForceContract:
    def test_probe_endpoint_accepts_force(self, mgr):
        from neurova.api.endpoints import model as model_ep

        app = FastAPI()
        app.include_router(model_ep.router, prefix="/api/v1/models")
        original = model_ep._get_provider_manager
        model_ep._get_provider_manager = lambda current_user=None: mgr

        calls = []

        async def _fake_probe(model_id, provider_id=None, force=False):
            calls.append({"model_id": model_id, "force": force})
            return {"model_id": model_id, "probe_source": "probed", "supported": True}

        mgr.probe_model_multimodal = _fake_probe
        with TestClient(app) as c:
            resp = c.post("/api/v1/models/probe-multimodal", json={"model_id": "m-1", "force": True})
        model_ep._get_provider_manager = original

        assert resp.status_code == 200
        assert calls and calls[0]["force"] is True, "force 应透传到管理器"
