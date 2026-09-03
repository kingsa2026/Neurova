"""
记忆管理基础模型测试

测试目标：neurova/api/endpoints/memory/base.py
覆盖：数据模型、辅助函数
"""

import pytest
from neurova.api.endpoints.memory.base import (
    AddMemoryRequest, MemoryItem, router, _get_request_id,
)


class MockRequestState:
    def __init__(self, request_id=None):
        self.request_id = request_id


class MockRequest:
    def __init__(self, request_id=None):
        self.state = MockRequestState(request_id)


class TestAddMemoryRequest:
    """添加记忆请求模型"""

    def test_default_values(self):
        req = AddMemoryRequest(content="这是一条测试记忆")
        assert req.content == "这是一条测试记忆"
        assert req.category is None
        assert req.is_important is None
        assert req.is_crystallized is None
        assert req.emotion_score == 0.0
        assert req.perspective is None
        assert req.metadata is None
        assert req.auto_classify is True
        assert req.auto_analyze_emotion is True

    def test_auto_classify_disabled(self):
        req = AddMemoryRequest(content="test", auto_classify=False)
        assert req.auto_classify is False

    def test_emotion_score_range(self):
        req = AddMemoryRequest(content="test", emotion_score=0.5)
        assert req.emotion_score == 0.5
        req2 = AddMemoryRequest(content="test", emotion_score=-1.0)
        assert req2.emotion_score == -1.0

    def test_metadata(self):
        req = AddMemoryRequest(content="test", metadata={"source": "wechat"})
        assert req.metadata == {"source": "wechat"}

    def test_perspective(self):
        req = AddMemoryRequest(content="test", perspective="第一人称")
        assert req.perspective == "第一人称"

    def test_content_min_length(self,):
        """content 必须至少 1 个字符"""
        with pytest.raises(Exception):
            AddMemoryRequest(content="")

    def test_content_max_length(self):
        """content 最多 50000 字符"""
        with pytest.raises(Exception):
            AddMemoryRequest(content="a" * 50001)

    def test_category_with_special_categories(self):
        req = AddMemoryRequest(content="test", category="学习")
        assert req.category == "学习"


class TestMemoryItem:
    """记忆项模型"""

    def test_minimal_memory_item(self):
        item = MemoryItem(
            id="mem_001",
            agent_id="agent_001",
            content="测试记忆",
            category="general",
            temperature=0.5,
            lifecycle_stage="active",
            is_important=False,
            is_crystallized=False,
            emotion_score=0.0,
            access_count=0,
            created_at="2026-01-01T00:00:00",
        )
        assert item.id == "mem_001"
        assert item.agent_id == "agent_001"
        assert item.content == "测试记忆"
        assert item.last_accessed_at is None

    def test_memory_item_with_all_fields(self):
        item = MemoryItem(
            id="mem_002",
            agent_id="agent_001",
            content="重要记忆",
            category="important",
            temperature=0.9,
            lifecycle_stage="crystallizing",
            is_important=True,
            is_crystallized=True,
            emotion_score=0.8,
            access_count=42,
            created_at="2026-01-01T00:00:00",
            last_accessed_at="2026-06-01T12:00:00",
        )
        assert item.is_important is True
        assert item.is_crystallized is True
        assert item.access_count == 42
        assert item.last_accessed_at == "2026-06-01T12:00:00"


class TestRouter:
    """记忆管理路由"""

    def test_router_prefix(self):
        assert router.prefix == "/memories"

    def test_router_tags(self):
        assert router.tags == ["记忆管理"]

    def test_router_has_routes(self):
        assert len(router.routes) > 0


class TestGetRequestId:
    """_get_request_id 辅助函数"""

    def test_with_request(self):
        req = MockRequest(request_id="req_abc")
        assert _get_request_id(req) == "req_abc"

    def test_without_request_id(self):
        req = MockRequest()
        assert _get_request_id(req) is None

    def test_none_request(self):
        assert _get_request_id(None) is None
