"""红灯②：LLM 调用必须真的过配额闸口。

现状：配额管理器有 40+ 个 `check_*` / `increment_*` / `try_consume` 方法，
全仓生产代码**零调用点**——判定函数自己会算 `allowed=False`，但没有任何
生产路径去调它。于是「记账照记、额度照超」，配额是个装饰。

本测试钉住消费端：配额耗尽时 LLM 调用必须被**拒绝**（返回
`success=False` 且 `error` 点名配额），而不是继续打上游。
"""

import pytest

from neurova.core.identity_context import clear_request_user_id, set_request_user_id


@pytest.fixture
def quota(tmp_path, monkeypatch):
    import neurova.admin.resource_quota_manager as rqm

    monkeypatch.setattr(rqm, "_DEFAULT_DIR", str(tmp_path / "resource_quota"))
    rqm.reset_resource_quota_manager()
    yield rqm.get_resource_quota_manager()
    rqm.reset_resource_quota_manager()


@pytest.fixture(autouse=True)
def _identity():
    clear_request_user_id()
    yield
    clear_request_user_id()


class TestQuotaGateOnLLMCall:
    @pytest.mark.asyncio
    async def test_exhausted_quota_blocks_llm_call(self, quota, monkeypatch):
        """额度用尽 → 调用被拒，且不触达上游 client。"""
        monkeypatch.setattr(
            quota, "_custom_limits", {"max_llm_calls_per_day": 1}, raising=False
        )
        set_request_user_id("u_quota")
        quota.increment_llm_call("u_quota")  # 已用 1 / 上限 1 → 用尽

        from neurova.llm import multi_model_client as mmc

        client = mmc.MultiModelLLMClient.__new__(mmc.MultiModelLLMClient)
        called = {"n": 0}

        async def _never(*_a, **_k):
            called["n"] += 1
            return {"success": True}

        monkeypatch.setattr(client, "_get_client_for_request", lambda *a, **k: object())
        monkeypatch.setattr(client, "_chat_single_attempt", _never, raising=False)
        monkeypatch.setattr(mmc, "get_quota_manager", lambda: quota, raising=False)

        result = await client.chat([{"role": "user", "content": "hi"}])
        assert result["success"] is False
        assert "配额" in str(result.get("error") or ""), result
        assert called["n"] == 0, "额度用尽时不得触达上游"

    @pytest.mark.asyncio
    async def test_available_quota_lets_call_through_and_records(self, quota, monkeypatch):
        """额度未用尽 → 放行，并记账 +1。"""
        monkeypatch.setattr(
            quota, "_custom_limits", {"max_llm_calls_per_day": 5}, raising=False
        )
        set_request_user_id("u_ok")

        from neurova.llm import multi_model_client as mmc

        client = mmc.MultiModelLLMClient.__new__(mmc.MultiModelLLMClient)
        monkeypatch.setattr(client, "_get_client_for_request", lambda *a, **k: object())

        async def _ok(_c, _m, **k):
            return {"success": True, "response": None, "duration": 0.0,
                    "model": "m", "provider": "p"}

        monkeypatch.setattr(client, "_chat_single_attempt", _ok, raising=False)
        monkeypatch.setattr(mmc, "get_quota_manager", lambda: quota, raising=False)

        result = await client.chat([{"role": "user", "content": "hi"}])
        assert result["success"] is True
        assert quota.get_usage("u_ok").llm_call_count == 1

    @pytest.mark.asyncio
    async def test_quota_backend_failure_does_not_block(self, monkeypatch):
        """配额后端不可用 → fail-soft，不阻断对话。"""
        set_request_user_id("u_soft")

        from neurova.llm import multi_model_client as mmc

        client = mmc.MultiModelLLMClient.__new__(mmc.MultiModelLLMClient)
        monkeypatch.setattr(client, "_get_client_for_request", lambda *a, **k: object())

        async def _ok(_c, _m, **k):
            return {"success": True, "response": None, "duration": 0.0,
                    "model": "m", "provider": "p"}

        monkeypatch.setattr(client, "_chat_single_attempt", _ok, raising=False)

        def _boom():
            raise RuntimeError("quota backend down")

        monkeypatch.setattr(mmc, "get_quota_manager", _boom, raising=False)

        result = await client.chat([{"role": "user", "content": "hi"}])
        assert result["success"] is True


class TestQuotaGateOnStream:
    @pytest.mark.asyncio
    async def test_exhausted_quota_blocks_stream(self, quota, monkeypatch):
        """流式路径是前端主流量——闸口只装非流式等于没装。"""
        monkeypatch.setattr(
            quota, "_custom_limits", {"max_llm_calls_per_day": 1}, raising=False
        )
        set_request_user_id("u_stream")
        quota.increment_llm_call("u_stream")  # 用尽

        from neurova.llm import multi_model_client as mmc

        client = mmc.MultiModelLLMClient.__new__(mmc.MultiModelLLMClient)
        monkeypatch.setattr(client, "_get_client_for_request", lambda *a, **k: object())
        monkeypatch.setattr(mmc, "get_quota_manager", lambda: quota, raising=False)

        chunks = [c async for c in client.chat_stream([{"role": "user", "content": "hi"}])]
        assert chunks, "拒绝必须是一条可消费的流事件，而不是静默空流"
        assert any("配额" in str(c) for c in chunks), chunks

    @pytest.mark.asyncio
    async def test_available_quota_lets_stream_start(self, quota, monkeypatch):
        monkeypatch.setattr(
            quota, "_custom_limits", {"max_llm_calls_per_day": 5}, raising=False
        )
        set_request_user_id("u_stream_ok")

        from neurova.llm import multi_model_client as mmc

        client = mmc.MultiModelLLMClient.__new__(mmc.MultiModelLLMClient)
        monkeypatch.setattr(
            client, "_get_client_for_request", lambda *a, **k: None
        )  # 无可用 client → 立即返回，只验闸口记账
        monkeypatch.setattr(mmc, "get_quota_manager", lambda: quota, raising=False)

        [c async for c in client.chat_stream([{"role": "user", "content": "hi"}])]
        assert quota.get_usage("u_stream_ok").llm_call_count == 1
