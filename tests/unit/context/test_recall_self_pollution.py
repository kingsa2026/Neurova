"""对照批 C4：recall 防自污染。

recall 族工具（recall_history/recall_query/recall_context_span/pool_search/
memory_search/voice_memory_search/graph_search）自身的调用与结果条目**不参与
召回**——否则查 "X" 会命中"上次 recall X 的结果"，检索被自身输出污染。

- 写侧：`_archive_conversation_to_pool` 归档 TOOL_CALL 条目时带 `tool_name`
  （从同批 assistant.tool_calls 反查 tool_call_id）；
- 读侧：`ContextPool.recall_evicted` 两源（持久台账/内存台账）都排除
  `metadata.tool_name` 命中 recall 族的条目。
"""

import threading

import pytest

from neurova.context.pool_models import ContextInput, ContextSource
from neurova.context_pool import ContextPool, _isRecallSelfRow


def _pool(*ledger_items) -> ContextPool:
    pool = object.__new__(ContextPool)  # 白盒：只挂 recall_evicted 所需状态
    pool._lock = threading.RLock()
    pool._eviction_ledger = list(ledger_items)
    pool._ledger_db = None
    pool.session_id = "sess-1"
    pool._allowedRecallItems = lambda items: items
    return pool


def _toolEntry(tool_name: str, content: str) -> ContextInput:
    return ContextInput(
        source=ContextSource.TOOL_CALL,
        content=content,
        metadata={"role": "tool", "tool_name": tool_name, "turn_id": "t1"},
    )


def _convEntry(content: str) -> ContextInput:
    return ContextInput(
        source=ContextSource.CONVERSATION,
        content=content,
        metadata={"role": "user", "turn_id": "t0"},
    )


class TestRecallSelfPollution:

    def test_recall_tool_result_excluded(self):
        pool = _pool(
            _toolEntry("recall_history", "recall 结果: 上周计划"),
            _convEntry("上周计划是修发布流程"),
        )
        picked = pool.recall_evicted(query="上周计划")
        contents = [c.content for c in picked]
        assert contents == ["上周计划是修发布流程"], \
            f"recall 自身结果不得参与召回，实际：{contents}"

    def test_all_recall_family_tools_excluded(self):
        pool = _pool(
            _toolEntry("recall_query", "q"),
            _toolEntry("recall_context_span", "q"),
            _toolEntry("pool_search", "q"),
            _toolEntry("memory_search", "q"),
            _convEntry("真历史内容"),
        )
        picked = pool.recall_evicted()
        assert [c.content for c in picked] == ["真历史内容"]

    def test_non_recall_tool_results_stay(self):
        pool = _pool(
            _toolEntry("web_search", "搜索到的资料"),
            _convEntry("对话原文"),
        )
        picked = pool.recall_evicted(query="")
        assert len(picked) == 2, "非检索族工具结果不排除"

    def test_persisted_row_metadata_json_also_filtered(self):
        # 持久台账行以 JSON 字符串携带 metadata（sqlite3.Row 形态）
        row = {"content": "recall 结果: X", "metadata": '{"tool_name": "recall_history"}',
               "turn_id": "t1", "session_id": "s", "evicted_at": "e", "chat_scope": "shared"}
        assert _isRecallSelfRow(row) is True


def test_archive_tags_tool_name_for_recall_pollution_guard():
    """归档打标接线钉住：orchestrator 归档 TOOL_CALL 条目时必须带 tool_name。"""
    import inspect

    from neurova.context import orchestrator

    source = inspect.getsource(
        orchestrator.ContextOrchestrator._archive_conversation_to_pool)
    assert "tool_name_by_call_id" in source, (
        "归档打标被删 = recall 防自污染失效（读侧无判据）"
    )
