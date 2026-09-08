"""GET /memory memory_type 过滤 + 响应类型字段契约测试（TDD 红）

页签契约断裂修复：
  - 前端页签 key = memory_type（episodic/semantic/working/procedural/pattern/emotional）
  - 后端 GET /memory 接受 memory_type 参数并透传 manager.recall
  - 响应每行带 type 字段（MemoryType 枚举值），前端类型列不再恒空
  - POST /memory 接受 memory_type（此前 AddMemoryRequest 缺字段，类型被丢弃）
"""
import os
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_p0_fixes_0123456789")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.endpoints.memory.crud import router
from neurova.api.auth import get_current_user_or_default

BASE = "/api/v1/memory"


@pytest.fixture
def mock_manager():
    mm = MagicMock()
    mm.recall.return_value = []
    mm.get_stats.return_value = {"total_memories": 0}
    return mm


@pytest.fixture
def app_client(mock_manager):
    app = FastAPI()
    with patch("neurova.api.endpoints.memory.crud.get_memory_manager", return_value=mock_manager):
        app.include_router(router, prefix=BASE)
        app.dependency_overrides[get_current_user_or_default] = lambda: {
            "user_id": "7",
            "neuser_id": "7",
            "role": "user",
        }
        client = TestClient(app)
        yield client


class TestMemoryTypeFilter:
    def test_list_accepts_memory_type_param(self, app_client, mock_manager):
        """GET /memory?memory_type=episodic → recall 收到 memory_type。"""
        resp = app_client.get(f"{BASE}", params={"agent_id": "default", "memory_type": "episodic"})
        assert resp.status_code == 200
        assert mock_manager.recall.call_args.kwargs.get("memory_type") == "episodic"

    def test_list_without_memory_type_passes_none(self, app_client, mock_manager):
        """不传 memory_type → 行为与旧契约一致（None = 不过滤）。"""
        resp = app_client.get(f"{BASE}", params={"agent_id": "default"})
        assert resp.status_code == 200
        assert mock_manager.recall.call_args.kwargs.get("memory_type") in (None, "")

    def test_invalid_memory_type_rejected(self, app_client):
        """非法枚举值 400（fail-fast，不静默吞成全量）。"""
        resp = app_client.get(f"{BASE}", params={"agent_id": "default", "memory_type": "not_a_type"})
        assert resp.status_code == 422

    def test_create_accepts_memory_type(self, app_client, mock_manager):
        """POST /memory 带 memory_type=semantic → remember 收到。"""
        mock_manager.remember.return_value = "mem_000001"
        resp = app_client.post(
            f"{BASE}",
            params={"agent_id": "default"},
            json={"content": "测试", "memory_type": "semantic"},
        )
        assert resp.status_code == 200
        assert mock_manager.remember.call_args.kwargs.get("memory_type") == "semantic"


class TestResponseTypeField:
    def test_memory_to_dict_includes_type(self):
        """memory_to_dict 输出 type 字段（前端类型列数据源）。"""
        from datetime import datetime, timezone

        from neurova.api.endpoints.memory.base import memory_to_dict
        from neurova.cognitive_layers.memory_layer.models import (
            EmotionType,
            Memory,
            MemoryCategory,
            MemoryOrigin,
            MemoryType,
        )

        mem = Memory(
            id="m1",
            content="x",
            memory_type=MemoryType.EPISODIC,
            category=MemoryCategory.CONVERSATION,
            temperature=60.0,
            importance=50.0,
            origin=MemoryOrigin.AGENT,
            emotion=EmotionType.NEUTRAL,
            agent_id="a",
            neuser_id="n",
            user_id="u",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        d = memory_to_dict(mem)
        assert d["type"] == "episodic"

    def test_recall_dict_row_type_passthrough(self):
        """recall 返回的 to_dict() 行（dict 分支）同样带 type。"""
        from neurova.api.endpoints.memory.base import memory_to_dict

        row = {"id": "m2", "content": "x", "memory_type": "semantic", "category": "general"}
        d = memory_to_dict(row)
        assert d["type"] == "semantic"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
