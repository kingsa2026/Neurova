"""
成本持久化主路径接线测试（TDD 防回归）

覆盖上一轮遗留的三处根因：
1. 装饰器是 async wrapper，套在同步 LLM 方法上会返回协程、破坏主路径；
2. 装饰器用 result.get('usage') 读 dict，但真实返回是 LLMResponse dataclass；
3. 记账只进内存预算，从未落盘到 SQLite 账本。

修好后：装饰器 sync/async 自适、能解析 LLMResponse、经 record_llm_cost 落盘 SQLite；
对生成器方法不改写返回（流式记账改在方法内，由 record_llm_cost 承担）。
"""
import asyncio
import inspect
import sqlite3
from dataclasses import dataclass, field
from decimal import Decimal

import pytest

from neurova.models import cost_store as cs
from neurova.models.cost_store import LlmCostStore, install_llm_cost_store, reset_llm_cost_store
from neurova.models.cost_tracking import (
    LLMProvider,
    record_llm_cost,
    track_llm_call,
    llm_cost_context,
    reset_cost_tracker,
)


@dataclass
class FakeLLMResponse:
    """镜像 neurova.llm_client.LLMResponse 的关键字段"""
    content: str = "ok"
    model: str = "gpt-4o"
    usage: dict = field(default_factory=dict)


@pytest.fixture
def store(tmp_path, monkeypatch):
    db = tmp_path / "cost_persist_test.db"
    monkeypatch.setenv("NEUROVA_LLM_COST_DB", str(db))
    reset_llm_cost_store()
    reset_cost_tracker()
    s = install_llm_cost_store(str(db))
    yield s
    reset_llm_cost_store()
    reset_cost_tracker()


def _row_count(s):
    with sqlite3.connect(str(s._db_path)) as conn:
        return conn.execute("SELECT COUNT(*) FROM llm_calls").fetchone()[0]


def _latest(s):
    with sqlite3.connect(str(s._db_path)) as conn:
        conn.row_factory = sqlite3.Row
        return dict(conn.execute("SELECT * FROM llm_calls ORDER BY rowid DESC LIMIT 1").fetchone())


# ── record_llm_cost：单一记账入口 ──────────────────────────────────

def test_record_llm_cost_persists_row(store):
    record_llm_cost(
        provider=LLMProvider.OPENAI,
        model="gpt-4o",
        usage={"prompt_tokens": 100, "completion_tokens": 50},
        agent_id="kai",
    )
    assert _row_count(store) == 1
    row = _latest(store)
    assert row["agent_id"] == "kai"
    assert row["provider"] == "openai"
    assert row["model"] == "gpt-4o"
    assert row["input_tokens"] == 100
    assert row["output_tokens"] == 50
    assert Decimal(str(row["cost"])) > Decimal("0")


def test_record_llm_cost_noop_without_store(monkeypatch):
    # 未装配账本时静默降级，绝不抛错（副路径纪律）
    reset_llm_cost_store()
    record_llm_cost(
        provider=LLMProvider.OPENAI, model="gpt-4o",
        usage={"prompt_tokens": 1}, agent_id="x",
    )  # 不抛异常即通过


# ── 装饰器：sync / async / generator 三类正确性 ───────────────────

def test_decorator_on_sync_returns_plain_value_not_coroutine(store):
    @track_llm_call(provider=LLMProvider.OPENAI, model="gpt-4o", agent_id="kai")
    def sync_call():
        return FakeLLMResponse(model="gpt-4o", usage={"prompt_tokens": 100, "completion_tokens": 20})

    result = sync_call()  # 关键：同步函数调用后不得返回协程
    assert not inspect.iscoroutine(result)
    assert isinstance(result, FakeLLMResponse)
    assert _row_count(store) == 1


def test_decorator_on_async_persists(store):
    @track_llm_call(provider=LLMProvider.OPENAI, model="gpt-4o", agent_id="kai")
    async def async_call():
        return FakeLLMResponse(model="gpt-4o", usage={"prompt_tokens": 30, "completion_tokens": 7})

    result = asyncio.run(async_call())
    assert isinstance(result, FakeLLMResponse)
    assert _row_count(store) == 1


def test_decorator_reads_usage_from_dataclass(store):
    # result 是 dataclass：模型名取 result.model，token 取 result.usage
    @track_llm_call(provider=LLMProvider.OPENAI, model="fallback", agent_id="kai")
    def sync_call():
        return FakeLLMResponse(model="gpt-4o", usage={"prompt_tokens": 5, "completion_tokens": 5})

    sync_call()
    row = _latest(store)
    assert row["model"] == "gpt-4o"  # 实际模型覆盖装饰器默认


def test_decorator_on_generator_not_broken(store):
    # 生成器方法（流式）不得被改写成协程；装饰器原样返回，交由方法内记账
    @track_llm_call(provider=LLMProvider.OPENAI, model="gpt-4o", agent_id="kai")
    def stream_call():
        yield FakeLLMResponse(usage={"prompt_tokens": 1})

    gen = stream_call()
    assert inspect.isgenerator(gen)
    chunks = list(gen)
    assert len(chunks) == 1
    # 装饰器对生成器不做自动落盘（流式记账在方法体内显式调用）
    assert _row_count(store) == 0


def test_context_var_attributes_agent_session_turn(store):
    # ChatPipeline 每轮设置 contextvar，未显式传 agent 的记账自动归属
    with llm_cost_context(agent_id="kai", session_id="s-1", turn_id="t-1"):
        record_llm_cost(
            provider=LLMProvider.OPENAI, model="gpt-4o",
            usage={"prompt_tokens": 10, "completion_tokens": 5},
        )  # 不传 agent_id
    row = _latest(store)
    assert row["agent_id"] == "kai"
    assert row["session_id"] == "s-1"
    assert row["turn_id"] == "t-1"


def test_explicit_agent_overrides_context(store):
    with llm_cost_context(agent_id="from_ctx"):
        record_llm_cost(
            provider=LLMProvider.OPENAI, model="gpt-4o",
            usage={"prompt_tokens": 1}, agent_id="explicit",
        )
    assert _latest(store)["agent_id"] == "explicit"
