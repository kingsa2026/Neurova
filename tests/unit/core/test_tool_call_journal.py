# -*- coding: utf-8 -*-
"""工具调用账本测试（对照报告 B4-2 / 实施计划项 2：先记账再执行、unknown 不重放）。

三层锁定：
1. ToolCallJournal 存储层——begin 幂等（同 key 同条目）、settle 终态、结果留档；
2. run() 编排层——首执落账、同 key 重放不二次执行、unknown 封锁、失败回放、
   关闭开关直通；
3. ToolExecutor.execute 集成——外部写工具两次同参调用只执行一次。
"""
import asyncio
import os

import pytest


@pytest.fixture()
def journal(tmp_path):
    from neurova.core.tool_call_journal import ToolCallJournal

    j = ToolCallJournal(db_path=tmp_path / "tool_journal.db")
    yield j
    j.close()


class TestJournalStorage:
    def test_begin_creates_running_entry(self, journal):
        entry, claimed = journal.begin("k1", "gmail_send", scope="u:s", owner="call-1")
        assert claimed is True
        assert entry.id > 0
        assert entry.status == "running"
        assert entry.tool_name == "gmail_send"

    def test_begin_same_key_returns_same_entry(self, journal):
        a, firstClaimed = journal.begin("k1", "gmail_send", scope="u:s", owner="call-1")
        b, secondClaimed = journal.begin("k1", "gmail_send", scope="u:s", owner="call-1")
        assert firstClaimed is True
        assert secondClaimed is False
        assert a.id == b.id

    def test_settle_succeeded_stores_result(self, journal):
        entry, _claimed = journal.begin("k1", "gmail_send", scope="u:s", owner="call-1")
        journal.settle(entry.id, "succeeded", result_json='{"ok": true}', owner="call-1")
        row = journal.get_by_key("k1")
        assert row.status == "succeeded"
        assert row.result_json == '{"ok": true}'
        assert row.settled_at is not None

    def test_settle_unknown_kept(self, journal):
        entry, _claimed = journal.begin("k1", "gmail_send", scope="u:s", owner="call-1")
        journal.settle(entry.id, "unknown", error_class="TimeoutError", owner="call-1")
        row = journal.get_by_key("k1")
        assert row.status == "unknown"
        assert row.error_class == "TimeoutError"

    def test_compute_key_param_order_insensitive(self):
        from neurova.core.tool_call_journal import computeKey

        a = computeKey("gmail_send", {"to": "x", "subject": "y"}, "u:s", "call-1")
        b = computeKey("gmail_send", {"subject": "y", "to": "x"}, "u:s", "call-1")
        assert a == b

    def test_compute_key_scope_sensitive(self):
        from neurova.core.tool_call_journal import computeKey

        assert computeKey("t", {"a": 1}, "u1:s1", "call-1") != computeKey("t", {"a": 1}, "u2:s1", "call-1")

    def test_compute_key_call_id_sensitive(self):
        from neurova.core.tool_call_journal import computeKey

        assert computeKey("t", {"a": 1}, "u:s", "call-1") != computeKey("t", {"a": 1}, "u:s", "call-2")


class TestRunJournaled:
    def test_first_call_executes_and_settles(self, journal):
        calls = []

        async def invoke():
            calls.append(1)
            return {"ok": True}

        from neurova.core.tool_call_journal import computeKey

        key = computeKey("t", {"a": 1}, "u:s", "call-1")
        result = asyncio.run(
            journal.run(key, "t", "u:s", invoke, is_success=lambda r: True, owner="call-1")
        )
        assert result == {"ok": True}
        assert len(calls) == 1
        assert journal.get_by_key(key).status == "succeeded"

    def test_same_key_replays_without_second_execute(self, journal):
        calls = []

        async def invoke():
            calls.append(1)
            return {"ok": True, "n": len(calls)}

        from neurova.core.tool_call_journal import computeKey

        key = computeKey("t", {"a": 1}, "u:s", "call-1")
        first = asyncio.run(journal.run(key, "t", "u:s", invoke, is_success=lambda r: True, owner="call-1"))
        second = asyncio.run(journal.run(key, "t", "u:s", invoke, is_success=lambda r: True, owner="call-1"))
        assert len(calls) == 1  # 第二次不得触达工具
        assert first.get("replayed") is None
        assert second.get("n") == 1
        assert second.get("replayed") is True

    def test_transport_error_marks_unknown_and_blocks_retry(self, journal):
        calls = []

        async def invoke():
            calls.append(1)
            raise ConnectionError("connection reset by peer")

        from neurova.core.tool_call_journal import computeKey

        key = computeKey("t", {"a": 1}, "u:s", "call-1")
        with pytest.raises(ConnectionError):
            asyncio.run(journal.run(key, "t", "u:s", invoke, is_success=lambda r: True, owner="call-1"))
        assert journal.get_by_key(key).status == "unknown"

        # 结果未知：同 key 重试不得再次执行，返回结构化拦截
        blocked = asyncio.run(journal.run(key, "t", "u:s", invoke, is_success=lambda r: True, owner="call-1"))
        assert len(calls) == 1
        assert blocked.get("code") == "tool_result_unknown"
        assert blocked.get("replayed") is None

    def test_deterministic_failure_replays_failure(self, journal):
        calls = []

        async def invoke():
            calls.append(1)
            return {"error": "参数不合法"}

        from neurova.core.tool_call_journal import computeKey

        key = computeKey("t", {"a": 1}, "u:s", "call-1")
        first = asyncio.run(journal.run(key, "t", "u:s", invoke, is_success=lambda r: "error" not in r, owner="call-1"))
        assert first == {"error": "参数不合法"}
        second = asyncio.run(journal.run(key, "t", "u:s", invoke, is_success=lambda r: "error" not in r, owner="call-1"))
        assert len(calls) == 1
        assert second.get("error") == "参数不合法"
        assert second.get("replayed") is True

    def test_disabled_journal_passes_through(self, tmp_path):
        os.environ["NEUROVA_TOOL_JOURNAL"] = "0"
        try:
            calls = []

            async def invoke():
                calls.append(1)
                return {"ok": True}

            from neurova.core.tool_call_journal import ToolCallJournal, computeKey

            j = ToolCallJournal(db_path=tmp_path / "j.db", enabled=False)
            key = computeKey("t", {"a": 1}, "u:s", "call-1")
            asyncio.run(j.run(key, "t", "u:s", invoke, is_success=lambda r: True, owner="call-1"))
            asyncio.run(j.run(key, "t", "u:s", invoke, is_success=lambda r: True, owner="call-1"))
            assert len(calls) == 2  # 关闭开关：不记账不拦截
        finally:
            os.environ.pop("NEUROVA_TOOL_JOURNAL", None)


class TestToolExecutorIntegration:
    def _executor(self, monkeypatch, counter):
        from types import SimpleNamespace

        from neurova.tool_executor import ToolExecutor

        ex = ToolExecutor(SimpleNamespace(current_session_id="sess-1"))
        from neurova.core import tool_call_journal
        from neurova.core.identity_context import set_request_user_id

        set_request_user_id("u-journal")

        async def fake_single(tool_name, params, skip_governance=False):
            counter.append((tool_name, json_digest(params)))
            if tool_name == "flaky_send":
                raise ConnectionError("connection reset by peer")
            return {"ok": True, "tool": tool_name}

        monkeypatch.setattr(ex, "_execute_single_tool", fake_single)
        # 能力面：未知工具（resolveToolCapability 返回 None）→ 按非只读记账
        monkeypatch.setattr(
            "neurova.agent.tool_coordinator.resolveToolCapability", lambda name: None
        )
        return ex

    def test_external_write_replays_same_call_and_runs_distinct_call(self, monkeypatch, tmp_path):
        monkeypatch.setenv("NEUROVA_TOOL_JOURNAL_DB", str(tmp_path / "j.db"))
        from neurova.core import tool_call_journal
        from neurova.core.identity_context import clear_request_user_id
        from neurova.core.turn_context import set_turn_tool_call_id

        tool_call_journal.reset_tool_call_journal()
        counter = []
        ex = self._executor(monkeypatch, counter)
        params = {"to": "a@b.c", "subject": "hi"}
        try:
            set_turn_tool_call_id("request-call-1")
            first = asyncio.run(ex.execute("gmail_send", params))
            second = asyncio.run(ex.execute("gmail_send", params))
            assert first.get("ok") is True
            assert second.get("replayed") is True
            assert len(counter) == 1
            set_turn_tool_call_id("request-call-2")
            third = asyncio.run(ex.execute("gmail_send", params))
            assert third.get("ok") is True
            assert third.get("replayed") is None
            assert len(counter) == 2
        finally:
            set_turn_tool_call_id(None)
            clear_request_user_id()
            tool_call_journal.reset_tool_call_journal()

    def test_readonly_tool_not_journaled(self, monkeypatch, tmp_path):
        monkeypatch.setenv("NEUROVA_TOOL_JOURNAL_DB", str(tmp_path / "j.db"))
        from neurova.core.tool_call_journal import reset_tool_call_journal

        reset_tool_call_journal()
        counter = []
        ex = self._executor(monkeypatch, counter)

        # 声明只读的能力 → 不记账：两次调用都真实执行
        from neurova.core.tool_capability import ToolCapability, WriteScope

        readonly = ToolCapability(readOnly=True, concurrentSafe=True, writeScopes=frozenset({WriteScope.NONE}))
        monkeypatch.setattr(
            "neurova.agent.tool_coordinator.resolveToolCapability", lambda name: readonly
        )
        asyncio.run(ex.execute("file_list", {"path": "x"}))
        asyncio.run(ex.execute("file_list", {"path": "x"}))
        assert len(counter) == 2


def json_digest(params):
    from neurova.core.tool_call_journal import computeKey

    return computeKey("probe", params, "scope", "probe-call")
