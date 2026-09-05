"""推理链持久化门控回归测试

事故（2026-09-05）：finish_trace 每轮对话无条件将整条推理链（含"晚上好→晚上好呀"
这类寒暄）作为 EPISODIC/reasoning_trace 记忆持久化，且：
- 无任何消费方（get_recent_traces 全仓零调用）
- unified_retriever.retrieve 不带 category 过滤 → 寒暄链会被当相关记忆
  捞回上下文，形成回声污染

契约（本测试锁死，遵循"新扩展点默认关"项目约定）：
- 默认（未设 env）：finish_trace 只清理 _active_traces，不调用 engine.store
- NEUROVA_TRACE_PERSIST=1 时：恢复持久化行为
- 无论开关，trace 都从活跃表移除（不泄漏）
"""

import pytest
from unittest.mock import MagicMock


@pytest.fixture
def engine():
    from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import CognitiveStorageEngine
    return MagicMock(spec=CognitiveStorageEngine)


@pytest.fixture
def manager(engine):
    from neurova.cognitive_layers.memory_layer.reasoning_trace_manager import ReasoningTraceManager
    return ReasoningTraceManager(engine=engine)


def _run_trace(manager):
    tid = manager.start_trace("晚上好")
    manager.add_step(tid, "retrieve", "q", "找到 0 条记忆")
    manager.finish_trace(tid, "晚上好呀！😊", total_tokens=42)
    return tid


class TestTracePersistGate:
    def test_default_no_persist(self, manager, engine, monkeypatch):
        """默认不持久化：engine.store 不被调用"""
        monkeypatch.delenv("NEUROVA_TRACE_PERSIST", raising=False)
        tid = _run_trace(manager)
        engine.store.assert_not_called()
        assert tid not in manager._active_traces

    def test_env_on_persists(self, manager, engine, monkeypatch):
        """NEUROVA_TRACE_PERSIST=1 时恢复持久化"""
        monkeypatch.setenv("NEUROVA_TRACE_PERSIST", "1")
        tid = _run_trace(manager)
        engine.store.assert_called_once()
        node = engine.store.call_args[0][0]
        assert node.category == "reasoning_trace"
        assert node.trace_id == tid

    def test_invalid_env_treated_as_off(self, manager, engine, monkeypatch):
        """env 值非 "1" 一律视为关（与 NEUROVA_METACOG_GATE 同口径）"""
        monkeypatch.setenv("NEUROVA_TRACE_PERSIST", "true")
        _run_trace(manager)
        engine.store.assert_not_called()

    def test_trace_always_removed(self, manager, engine, monkeypatch):
        """开关两种状态下 trace 都从活跃表移除，不泄漏"""
        monkeypatch.delenv("NEUROVA_TRACE_PERSIST", raising=False)
        t1 = _run_trace(manager)
        assert t1 not in manager._active_traces
        monkeypatch.setenv("NEUROVA_TRACE_PERSIST", "1")
        t2 = _run_trace(manager)
        assert t2 not in manager._active_traces
