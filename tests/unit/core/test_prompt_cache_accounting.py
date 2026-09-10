# -*- coding: utf-8 -*-
"""B1-5 Prompt Cache 记账 + B3-2 usage agent_id 列（QwenPaw #7342/#7207 对齐）。

契约：
1. usage_accounting.record 接受 cache_read_tokens/cache_write_tokens，
   snapshot 聚合与 last_call 携带同名字段。
2. usage_history SQLite 表带 cache_read_tokens/cache_write_tokens/agent_id
   列（老库自动 ALTER 迁移），record 写入，agent_token_totals 按 agent 聚合。
3. multi_model_client._extract_cache_tokens 兼容 OpenAI
   prompt_tokens_details.cached_tokens 与 Anthropic 风格
   cache_creation_input_tokens/cache_read_input_tokens。
4. analytics /usage 摘要带 cache 命中率与按 agent token 聚合。
"""
from __future__ import annotations

import os
import sqlite3
import threading
from types import SimpleNamespace

import pytest

from neurova.core.usage_accounting import TokenUsageAccounting, get_usage_accounting


class TestUsageAccountingCache:
    def test_record_accumulates_cache_tokens(self):
        acc = TokenUsageAccounting()
        acc.record(model="m1", provider="p1", prompt_tokens=100, completion_tokens=10,
                   cache_read_tokens=80, cache_write_tokens=20)
        acc.record(model="m1", provider="p1", prompt_tokens=50, completion_tokens=5,
                   cache_read_tokens=40, cache_write_tokens=0)
        snap = acc.snapshot()
        total = snap["total"]
        assert total["cache_read_tokens"] == 120
        assert total["cache_write_tokens"] == 20
        assert snap["by_model"]["m1"]["cache_read_tokens"] == 120

    def test_last_call_carries_cache(self):
        acc = TokenUsageAccounting()
        acc.record(model="m1", provider="p1", prompt_tokens=100, completion_tokens=10,
                   cache_read_tokens=80, cache_write_tokens=20)
        last = acc.last_call()
        assert last["cache_read_tokens"] == 80
        assert last["cache_write_tokens"] == 20

    def test_default_zero_no_breaking(self):
        acc = TokenUsageAccounting()
        acc.record(model="m1", provider="p1", prompt_tokens=1, completion_tokens=1)
        assert acc.snapshot()["total"]["cache_read_tokens"] == 0


class TestUsageHistoryCacheAgentColumns:
    @pytest.fixture
    def store(self, tmp_path):
        from neurova.core.usage_history import UsageHistoryStore, reset_usage_history

        reset_usage_history()
        st = UsageHistoryStore(db_path=str(tmp_path / "usage.db"))
        yield st
        reset_usage_history()

    def test_record_and_query_cache_agent(self, store):
        store.record(model="m1", provider="p1", prompt_tokens=100, completion_tokens=10,
                     cache_read_tokens=80, cache_write_tokens=20,
                     agent_id="agent-a", user_id="u1")
        rows = store.agent_token_totals()
        by_agent = {r["agent_id"]: r for r in rows}
        assert by_agent["agent-a"]["tokens"] == 110
        assert by_agent["agent-a"]["calls"] == 1

    def test_cache_totals_query(self, store):
        store.record(model="m1", provider="p1", prompt_tokens=100, completion_tokens=10,
                     cache_read_tokens=80, cache_write_tokens=20, user_id="u1")
        totals = store.cache_totals()
        assert totals["cache_read_tokens"] == 80
        assert totals["cache_write_tokens"] == 20

    def test_migration_from_legacy_schema(self, tmp_path):
        """旧库（无 cache/agent_id 列）打开时自动 ALTER，不丢既有行。"""
        from neurova.core.usage_history import UsageHistoryStore, reset_usage_history

        reset_usage_history()
        db = tmp_path / "legacy.db"
        conn = sqlite3.connect(str(db))
        conn.execute("""
            CREATE TABLE llm_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                usage_date TEXT NOT NULL,
                user_id TEXT NOT NULL DEFAULT 'anonymous',
                model TEXT NOT NULL,
                provider TEXT NOT NULL DEFAULT '',
                prompt_tokens INTEGER NOT NULL DEFAULT 0,
                completion_tokens INTEGER NOT NULL DEFAULT 0,
                total_tokens INTEGER NOT NULL DEFAULT 0,
                estimated INTEGER NOT NULL DEFAULT 0,
                first_token_ms INTEGER NOT NULL DEFAULT 0,
                duration_ms INTEGER NOT NULL DEFAULT 0
            )
        """)
        conn.execute(
            "INSERT INTO llm_usage (ts, usage_date, user_id, model, prompt_tokens,"
            " completion_tokens, total_tokens) VALUES ('t','2026-09-11','u','m',1,2,3)"
        )
        conn.commit()
        conn.close()

        st = UsageHistoryStore(db_path=str(db))
        # 旧行仍可聚合
        assert st.cache_totals()["cache_read_tokens"] == 0
        # 新列可写
        st.record(model="m2", prompt_tokens=10, completion_tokens=1,
                  cache_read_tokens=5, agent_id="agx")
        assert st.cache_totals()["cache_read_tokens"] == 5
        reset_usage_history()


class TestExtractCacheTokens:
    def test_openai_prompt_tokens_details(self):
        from neurova.llm.multi_model_client import MultiModelLLMClient

        usage = {"prompt_tokens": 100, "completion_tokens": 5,
                 "prompt_tokens_details": {"cached_tokens": 80}}
        read, write = MultiModelLLMClient._extract_cache_tokens(usage)
        assert read == 80
        assert write == 0

    def test_anthropic_style(self):
        from neurova.llm.multi_model_client import MultiModelLLMClient

        usage = SimpleNamespace(prompt_tokens=100, completion_tokens=5,
                                cache_read_input_tokens=64, cache_creation_input_tokens=30)
        read, write = MultiModelLLMClient._extract_cache_tokens(usage)
        assert read == 64
        assert write == 30

    def test_missing_fields_zero(self):
        from neurova.llm.multi_model_client import MultiModelLLMClient

        assert MultiModelLLMClient._extract_cache_tokens(None) == (0, 0)
        assert MultiModelLLMClient._extract_cache_tokens({"prompt_tokens": 1}) == (0, 0)


class TestAnalyticsCacheContract:
    def test_usage_summary_has_cache_fields(self):
        """/usage 摘要函数级契约：cache 命中率 + by_agent token 字段存在。"""
        import inspect

        from neurova.api.endpoints import analytics

        src = inspect.getsource(analytics.get_usage_stats)
        assert "cache_read_tokens" in src
        assert "cache_hit_rate" in src
        assert "agent_token_totals" in src
