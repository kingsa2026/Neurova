# -*- coding: utf-8 -*-
"""usage_history.agent_id 写侧归因（fullrepo 审计 2026-11-18 C 组）。

红灯依据：usage_history.record 的全仓生产写点仅 multi_model_client.py
两处（chat / chat_stream），调用块均不传 agent_id ⇒ 列恒空串，读侧
agent_token_totals() 与 analytics 按 agent 用量视图恒落 "default" 桶。

修法（单一事实源）：record 改从 cost_tracking 既有 `_llm_cost_ctx`
（get_llm_cost_context()）读 agent_id——ChatPipeline 每轮已写入
（set_llm_cost_context），不新造第二条身份 ContextVar；无上下文留
空串（fail-soft，不臆造归属）。
"""
import asyncio
from types import SimpleNamespace

import pytest

from neurova.core.usage_history import get_usage_history, reset_usage_history
from neurova.models.cost_tracking import set_llm_cost_context
from neurova.llm.multi_model_client import MultiModelLLMClient
from neurova.llm.provider_manager import LoadBalancingStrategy


@pytest.fixture(autouse=True)
def _clean_history(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path / "data"))
    reset_usage_history()
    yield
    reset_usage_history()


def _manager_with_stub_result(result):
    manager = MultiModelLLMClient(strategy=LoadBalancingStrategy.PRIORITY_FIRST)
    config = manager._provider_manager.add_provider(
        name="P", provider="OpenAI", base_url="https://api.openai.com/v1",
        api_key="sk-test", default_model="gpt-4o")
    manager.set_active_model(config.id, "gpt-4o")

    async def _fake_retry(client, messages, bypass_guard=False, **kwargs):
        return result

    manager._chat_with_retry = _fake_retry
    return manager


def _result():
    return SimpleNamespace(content="hi", response_id="r1",
                           usage={"prompt_tokens": 11, "completion_tokens": 7})


def run(coro):
    return asyncio.run(coro)


class TestUsageRowCarriesAgentContext:
    def test_single_attempt_records_agent_id_from_cost_context(self):
        manager = _manager_with_stub_result(_result())
        set_llm_cost_context(agent_id="agent-under-test", session_id="s1", turn_id="t1")
        try:
            client = manager.get_current_client()
            resp = run(manager._chat_single_attempt(
                client, [{"role": "user", "content": "q"}]))
            assert resp.get("success") is True, resp
            totals = get_usage_history().agent_token_totals()
            assert totals, "usage 行未落库"
            assert totals[0]["agent_id"] == "agent-under-test", totals
            assert totals[0]["calls"] == 1, totals
        finally:
            set_llm_cost_context()

    def test_without_context_row_agent_id_stays_empty(self):
        """无上下文 fail-soft：列留空串（读侧归 default 桶），不臆造归属。"""
        manager = _manager_with_stub_result(_result())
        client = manager.get_current_client()
        resp = run(manager._chat_single_attempt(
            client, [{"role": "user", "content": "q"}]))
        assert resp.get("success") is True, resp
        totals = get_usage_history().agent_token_totals()
        assert totals, "usage 行未落库"
        assert totals[0]["agent_id"] == "", totals
