"""测试实时记忆流"""
import pytest
from neurova.memory import MemoryStream


def test_memory_stream_record():
    """测试记录事件"""
    stream = MemoryStream()
    
    event = stream.record(
        event_type=MemoryStream.EVENT_NEW,
        content="测试记忆",
        metadata={'category': 'test'}
    )
    
    assert event.type == 'new'
    assert event.content == "测试记忆"


def test_memory_stream_get():
    """测试获取事件流"""
    stream = MemoryStream()
    
    for i in range(10):
        stream.record(event_type='new', content=f"记忆{i}")
    
    events = stream.get_stream(limit=5)
    assert len(events) == 5


def test_memory_stream_filter():
    """测试事件过滤"""
    stream = MemoryStream()
    
    stream.record(event_type='new', content="新记忆")
    stream.record(event_type='recall', content="回忆")
    stream.record(event_type='new', content="另一条新记忆")
    
    events = stream.get_stream(event_type='new')
    assert len(events) == 2


def test_memory_stream_stats():
    """测试事件统计"""
    stream = MemoryStream()
    
    stream.record(event_type='new', content="记忆1")
    stream.record(event_type='recall', content="回忆")
    stream.record(event_type='new', content="记忆2")
    
    stats = stream.stats()
    assert stats['total_events'] == 3
    assert stats['type_counts']['new'] == 2
    assert stats['type_counts']['recall'] == 1


def test_memory_stream_max_events():
    """测试最大事件数量限制"""
    stream = MemoryStream(max_events=5)
    
    for i in range(10):
        stream.record(event_type='new', content=f"记忆{i}")
    
    assert len(stream.get_stream()) == 5


def test_memory_stream_export():
    """测试导出事件流"""
    stream = MemoryStream()
    stream.record(event_type='new', content="测试")
    
    json_export = stream.export(format='json')
    assert '测试' in json_export
    assert 'new' in json_export


def test_memory_event_to_dict():
    """测试事件序列化"""
    event = MemoryEvent(
        event_type='new',
        memory_id='mem_123',
        content="这是测试内容",
        metadata={'key': 'value'}
    )
    
    d = event.to_dict()
    assert d['type'] == 'new'
    assert d['memory_id'] == 'mem_123'
    assert d['content'] == "这是测试内容"
    assert d['metadata'] == {'key': 'value'}
    assert 'timestamp' in d
    assert 'id' in d
