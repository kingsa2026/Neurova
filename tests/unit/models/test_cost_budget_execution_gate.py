"""成本预算必须经管理面注册，并在真实 LLM attempt 前执行。"""

import asyncio
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from neurova.api.endpoints import budget_api
from neurova.llm.multi_model_client import MultiModelLLMClient
from neurova.models.cost_budget import (
    BudgetConfig,
    BudgetScope,
    get_budget_service,
    reset_budget_service,
)


@pytest.fixture
def budgetService():
    reset_budget_service()
    yield get_budget_service()
    reset_budget_service()


def _register(service, agentId, amount):
    now = datetime.now()
    service.manager.register_budget(BudgetConfig(
        scope=BudgetScope.HOURLY,
        identifier=agentId,
        amount=Decimal(amount),
        period_start=now - timedelta(minutes=1),
        period_end=now + timedelta(hours=1),
    ))


def testAdminCreateEndpointRegistersUsableBudget(budgetService):
    request = budget_api.BudgetCreate(scope="hourly", identifier="agent-api", amount=2.5)

    response = asyncio.run(budget_api.create_budget(request, budgetService, {"user_id": "admin"}))

    assert response["scope"] == "hourly"
    assert response["identifier"] == "agent-api"
    assert budgetService.manager.get_remaining(BudgetScope.HOURLY, "agent-api") == Decimal("2.5")


@pytest.mark.parametrize("scope", [BudgetScope.AGENT, BudgetScope.DAILY, BudgetScope.MONTHLY])
def testCustomAgentPeriodBudgetBlocksAttempt(budgetService, scope):
    now = datetime.now()
    budgetService.manager.register_budget(BudgetConfig(
        scope=scope,
        identifier="agent-custom",
        amount=Decimal("0"),
        period_start=now - timedelta(minutes=1),
        period_end=now + timedelta(days=31),
    ))

    reason = budgetService.check_llm_call_allowed("agent-custom", "openai", "gpt-4o")

    assert reason is not None
    assert scope.value in reason


def testOverBudgetAttemptNeverCallsProvider(budgetService, monkeypatch):
    _register(budgetService, "agent-gate", "0")
    calls = []

    class FakeClient:
        async def chat(self, messages, **kwargs):
            calls.append(messages)
            return SimpleNamespace(content="should-not-run", usage=None)

    modelClient = SimpleNamespace(
        client=FakeClient(),
        provider=SimpleNamespace(id="openai"),
        model="gpt-4o",
        increment_request=lambda **kwargs: None,
    )
    multi = object.__new__(MultiModelLLMClient)
    multi._clients = {f"openai/gpt-4o": modelClient}
    multi._provider_manager = SimpleNamespace(list_providers=lambda **kwargs: [])
    monkeypatch.setattr(multi, "_get_client_for_request", lambda *args, **kwargs: modelClient)
    monkeypatch.setattr(multi, "_get_retry_guard", lambda client: (
        __import__("neurova.llm.providers.rate_limiter", fromlist=["RetryConfig"]).RetryConfig(max_attempts=1),
        __import__("neurova.llm.providers.rate_limiter", fromlist=["CircuitBreaker"]).CircuitBreaker(),
    ))
    from neurova.models.cost_tracking import set_llm_cost_context

    set_llm_cost_context(agent_id="agent-gate")
    from neurova.llm.multi_model_client import _usageAgentId
    assert _usageAgentId() == "agent-gate"
    assert budgetService.check_llm_call_allowed("agent-gate", "openai", "gpt-4o")
    result = asyncio.run(multi.chat(
        [{"role": "user", "content": "hello"}],
        model="gpt-4o",
        provider_id="openai",
    ))

    assert result["success"] is False, result
    assert result["budget_exceeded"] is True
    assert "预算超支" in result["error"]
    assert calls == []


def testOverBudgetStreamNeverCallsProvider(budgetService, monkeypatch):
    _register(budgetService, "agent-stream", "0")
    calls = []

    class FakeClient:
        async def chat_stream_async(self, messages, **kwargs):
            calls.append(messages)
            if False:
                yield None

    modelClient = SimpleNamespace(
        client=FakeClient(),
        provider=SimpleNamespace(id="openai"),
        model="gpt-4o",
        increment_request=lambda **kwargs: None,
    )
    multi = object.__new__(MultiModelLLMClient)
    multi._clients = {f"openai/gpt-4o": modelClient}
    multi._provider_manager = SimpleNamespace(list_providers=lambda **kwargs: [])
    monkeypatch.setattr(multi, "_get_client_for_request", lambda *args, **kwargs: modelClient)
    from neurova.models.cost_tracking import set_llm_cost_context

    set_llm_cost_context(agent_id="agent-stream")

    async def consume():
        return [item async for item in multi.chat_stream(
            [{"role": "user", "content": "hello"}],
            model="gpt-4o",
            provider_id="openai",
        )]

    events = asyncio.run(consume())
    assert events[0]["budget_exceeded"] is True
    assert calls == []


def testNativeClientCostIsSettledOnce(tmp_path, monkeypatch):
    import sqlite3
    from neurova.llm_client import LLMResponse
    from neurova.models.cost_store import LlmCostStore

    dbPath = tmp_path / "native_cost.db"
    LlmCostStore.install(str(dbPath))
    try:
        class NativeClient:
            pass

        modelClient = SimpleNamespace(
            client=NativeClient(),
            provider=SimpleNamespace(id="anthropic"),
            model="claude-3-sonnet",
            increment_request=lambda **kwargs: None,
        )
        multi = object.__new__(MultiModelLLMClient)

        async def response(*args, **kwargs):
            return LLMResponse(
                content="ok", model="claude-3-sonnet",
                usage={"prompt_tokens": 1000, "completion_tokens": 1000},
            )

        monkeypatch.setattr(multi, "_chat_with_retry", response)
        result = asyncio.run(multi._chat_single_attempt(
            modelClient, [{"role": "user", "content": "hello"}]
        ))
        assert result["success"] is True
        conn = sqlite3.connect(str(dbPath))
        try:
            rows = conn.execute(
                "SELECT provider, model, input_tokens, output_tokens FROM llm_calls"
            ).fetchall()
        finally:
            conn.close()
        assert rows == [("anthropic", "claude-3-sonnet", 1000, 1000)]
    finally:
        LlmCostStore.uninstall()


def testBudgetServiceFailureDoesNotBlockCall(budgetService, monkeypatch):
    def broken():
        raise RuntimeError("budget unavailable")

    monkeypatch.setattr("neurova.models.cost_budget.get_budget_service", broken)
    modelClient = SimpleNamespace(
        client=object(), provider=SimpleNamespace(id="openai"), model="gpt-4o"
    )
    MultiModelLLMClient._ensureBudgetAllowed(modelClient)
