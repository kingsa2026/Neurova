"""实时记忆流（MemoryStream）行为测试。

本文件原先针对一套并不存在的 API 写成（``MemoryStream.record(content=...)``、
``MemoryStream.EVENT_NEW``、``max_events=``、``MemoryEvent(content=...)``），
既从未通过、也从未被 CI 收集——它只是把真实符号的未定义引用藏在 pyproject 的
F821 豁免里。此处按 ``neurova.cognitive_layers.memory_layer.memory_stream``
的**真实契约**重写，覆盖记录 / 取流 / 过滤 / 统计 / 容量 / 导出 / 序列化七条。
"""

import json

import pytest

from neurova.memory import MemoryStream
from neurova.cognitive_layers.memory_layer.memory_stream import (
    MemoryEvent,
    MemoryEventType,
)


def _record(stream, event_type, *, memory_id="mem_1", agent_id="agent_1", **kwargs):
    """按真实 record 契约落一条事件。"""
    return stream.record(
        event_type=event_type,
        memory_id=memory_id,
        agent_id=agent_id,
        **kwargs,
    )


def test_memory_stream_record():
    """记录一条事件后，事件流里就有它。"""
    stream = MemoryStream()
    event = MemoryEvent(
        event_type=MemoryEventType.STORE,
        memory_id="mem_1",
        agent_id="agent_1",
        content_preview="测试记忆",
        metadata={"category": "test"},
    )
    stream.record_event(event)

    events = stream.get_stream()
    assert len(events) == 1
    assert events[0].memory_id == "mem_1"
    assert events[0].content_preview == "测试记忆"
    assert events[0].metadata == {"category": "test"}


def test_memory_stream_get_limit():
    """get_stream 的 limit 生效，且最新的在前。"""
    stream = MemoryStream()
    for i in range(10):
        _record(stream, MemoryEventType.STORE, memory_id=f"mem_{i}")

    events = stream.get_stream(limit=5)
    assert len(events) == 5
    assert events[0].memory_id == "mem_9"  # 最新在前


def test_memory_stream_filter_by_event_type():
    """按 event_type 过滤只返回匹配事件。"""
    stream = MemoryStream()
    _record(stream, MemoryEventType.STORE, memory_id="mem_a")
    _record(stream, MemoryEventType.RETRIEVE, memory_id="mem_b")
    _record(stream, MemoryEventType.STORE, memory_id="mem_c")

    events = stream.get_stream(event_type=MemoryEventType.STORE)
    assert len(events) == 2
    assert {e.memory_id for e in events} == {"mem_a", "mem_c"}


def test_memory_stream_filter_by_agent_id():
    """按 agent_id 过滤只返回该 agent 的事件。"""
    stream = MemoryStream()
    _record(stream, MemoryEventType.STORE, agent_id="agent_1")
    _record(stream, MemoryEventType.STORE, agent_id="agent_2")
    _record(stream, MemoryEventType.RETRIEVE, agent_id="agent_1")

    events = stream.get_stream(agent_id="agent_1")
    assert len(events) == 2


def test_memory_stream_stats():
    """统计口径：总数、各事件类型计数、各 agent 计数。"""
    stream = MemoryStream()
    _record(stream, MemoryEventType.STORE, agent_id="agent_1")
    _record(stream, MemoryEventType.RETRIEVE, agent_id="agent_1")
    _record(stream, MemoryEventType.STORE, agent_id="agent_2")

    stats = stream.get_stats()
    assert stats["total_events"] == 3
    assert stats["event_type_counts"]["store"] == 2
    assert stats["event_type_counts"]["retrieve"] == 1
    assert stats["agent_counts"]["agent_1"] == 2
    assert stats["agent_counts"]["agent_2"] == 1


def test_memory_stream_max_size():
    """max_size 上限生效：超出后只保留最新的 max_size 条。"""
    stream = MemoryStream(max_size=5)
    for i in range(10):
        _record(stream, MemoryEventType.STORE, memory_id=f"mem_{i}")

    assert stream.size == 5
    assert len(stream.get_stream()) == 5
    assert stream.get_stream()[0].memory_id == "mem_9"


def test_memory_stream_export_json():
    """export_json 输出可反序列化，且含事件载荷。"""
    stream = MemoryStream()
    _record(stream, MemoryEventType.STORE, memory_id="mem_1", content_preview="测试")

    payload = json.loads(stream.export_json())
    assert len(payload) == 1
    assert payload[0]["memory_id"] == "mem_1"
    assert payload[0]["content_preview"] == "测试"
    assert payload[0]["event_type"] == "store"


def test_memory_event_to_dict():
    """MemoryEvent.to_dict 的字段与枚举取值口径。"""
    event = MemoryEvent(
        event_type=MemoryEventType.STORE,
        memory_id="mem_123",
        agent_id="agent_1",
        content_preview="这是测试内容",
        metadata={"key": "value"},
    )

    d = event.to_dict()
    assert d["event_type"] == "store"
    assert d["memory_id"] == "mem_123"
    assert d["agent_id"] == "agent_1"
    assert d["content_preview"] == "这是测试内容"
    assert d["metadata"] == {"key": "value"}
    assert "timestamp" in d
