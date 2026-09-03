"""
LLM 调用 → usage_history 持久化传动轴测试（2026-09-03）

锁定：MultiModelLLMClient.chat_stream 在入账 usage_accounting 的同时，
必须把同一笔调用落盘到 UsageHistoryStore（SQLite，重启不归零），
user_id 取自请求级 ContextVar（identity_context）——缺失记 anonymous。
"""

import pytest
from types import SimpleNamespace

from neurova.core.identity_context import (
    clear_request_user_id,
    set_request_user_id,
)
from neurova.core.usage_history import (
    get_usage_history,
    reset_usage_history,
)
from neurova.llm.multi_model_client import MultiModelLLMClient


@pytest.fixture(autouse=True)
def _clean():
    reset_usage_history()
    clear_request_user_id()
    yield
    reset_usage_history()
    clear_request_user_id()


def _make_client(usage_extract: bool = True):
    """构造最小 client 桩：_get_client_for_request 返回带流式 generator 的客户端。"""

    async def chat_stream_async(messages, **kwargs):
        if usage_extract:
            yield SimpleNamespace(
                usage=SimpleNamespace(prompt_tokens=100, completion_tokens=30),
                content="hi",
                reasoning_content=None,
            )
        else:
            yield SimpleNamespace(usage=None, content="hi", reasoning_content=None)

    llm_client = MultiModelLLMClient.__new__(MultiModelLLMClient)
    llm_client._clients = {}  # 绕过 init（不触 refresh_all_providers）
    llm_client._current_provider_id = "p1"
    llm_client._current_model = "m1"

    provider = SimpleNamespace(id="p1")
    client = SimpleNamespace(
        model="m1",  # noqa: S105 - 测试桩模型名
        provider=provider,
        increment_request=lambda success: None,
        client=SimpleNamespace(
            chat_stream_async=chat_stream_async,
            count_tokens=lambda *a, **kw: 7,
            count_message_tokens=lambda *a, **kw: 11,
        ),
    )
    return llm_client, client


class TestStreamWiring:
    @pytest.mark.asyncio
    async def test_stream_call_persists_to_usage_history(self, monkeypatch):
        """流式 usage 落盘：模型/总量/user_id 通过 ContextVar 传递。"""
        llm_client, client = _make_client()
        monkeypatch.setattr(llm_client, "_get_client_for_request", lambda *a, **kw: client)
        set_request_user_id("u1")

        chunks = []
        async for chunk in llm_client.chat_stream(
            [{"role": "user", "content": "hi"}], model="m1", provider_id="p1"
        ):
            chunks.append(chunk)

        assert len(chunks) == 1
        total = get_usage_history().total(user_id="u1")
        assert total["tokens"] == 130
        assert total["calls"] == 1
        by_model = get_usage_history().model_totals(user_id="u1")
        assert by_model[0]["model"] == "m1"

    @pytest.mark.asyncio
    async def test_chat_call_persists_to_usage_history(self, monkeypatch):
        """非流式 chat 同一入账路径：usage 落盘 + user_id 透传。"""
        llm_client, client = _make_client()

        # 非流式底层：client.chat 是同步 API（wrap 在 asyncio.to_thread 中执行）
        def chat_sync(messages, **kwargs):
            return SimpleNamespace(
                content="hi",
                usage=SimpleNamespace(prompt_tokens=40, completion_tokens=10),
            )

        client.client.chat = chat_sync
        monkeypatch.setattr(llm_client, "_get_client_for_request", lambda *a, **kw: client)
        set_request_user_id("u3")

        resp = await llm_client.chat(
            [{"role": "user", "content": "hi"}], model="m1", provider_id="p1"
        )
        assert resp["success"] is True
        total = get_usage_history().total(user_id="u3")
        assert total["tokens"] == 50
        assert total["calls"] == 1

    @pytest.mark.asyncio
    async def test_missing_user_id_records_as_anonymous(self, monkeypatch):
        clear_request_user_id()
        llm_client, client = _make_client()
        monkeypatch.setattr(llm_client, "_get_client_for_request", lambda *a, **kw: client)

        async for _chunk in llm_client.chat_stream(
            [{"role": "user", "content": "hi"}], model="m1", provider_id="p1"
        ):
            pass

        total = get_usage_history().total(user_id="anonymous")
        assert total["tokens"] == 130

    @pytest.mark.asyncio
    async def test_no_usage_estimates_and_persists(self, monkeypatch):
        """网关不回传 usage → tiktoken 估值（estimated）仍落盘。"""
        llm_client, client = _make_client(usage_extract=False)
        monkeypatch.setattr(llm_client, "_get_client_for_request", lambda *a, **kw: client)
        set_request_user_id("u2")

        async for _chunk in llm_client.chat_stream(
            [{"role": "user", "content": "hi"}], model="m1", provider_id="p1"
        ):
            pass

        total = get_usage_history().total(user_id="u2")
        # 11 (prompt 估值) + 7 (completion 估值)
        assert total["tokens"] == 18
