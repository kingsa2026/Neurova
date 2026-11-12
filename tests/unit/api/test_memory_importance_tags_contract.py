# -*- coding: utf-8 -*-
"""P1-4 记忆 importance/tags 契约红测（全库断点审计 2026-11-12）

缺陷：前端新建表单提交 importance（0-1）与 tags，但 AddMemoryRequest
字段面无这两个键——pydantic 静默丢弃；读侧 memory_to_dict 不输出
importance 键，页面重要性列渲染恒 0%。tags 同样蒸发（页面读 record.tags）。

契约口径（量纲归一）：
- 前端 importance 0-1（页内 ×100 渲染进度条）；存储层 0-100
  （memory_to_dict 的 is_important 判据 importance>=80 即此量纲）。
  写侧 ×100、读侧 ÷100。
- tags 走 metadata.tags（存储层既有形状：manager rec.tags→metadata["tags"]），
  读侧从 metadata.tags 提升为顶层 tags。
"""
import os
from unittest.mock import MagicMock, patch

import pytest

from tests.auth_headers import bearerHeaders

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_p1-4_memory_contract")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.endpoints.memory.crud import router
from neurova.api.auth import get_current_user_or_default

BASE = "/api/v1/memory"


@pytest.fixture
def mock_manager():
    mm = MagicMock()
    mm.remember.return_value = "mem_test_1"
    mm.recall.return_value = []
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
        client = TestClient(app, headers=bearerHeaders("7"))
        yield client


class TestAddMemoryImportanceTags:
    def test_importance_and_tags_reach_manager(self, app_client, mock_manager):
        resp = app_client.post(
            f"{BASE}",
            json={"content": "测试内容", "importance": 0.5, "tags": ["重要", "工作"]},
            params={"agent_id": "default"},
        )
        assert resp.status_code == 200, resp.text
        kwargs = mock_manager.remember.call_args.kwargs
        # 量纲归一：前端 0-1 → 存储 0-100
        assert kwargs["importance"] == 50.0
        # tags 走 metadata.tags（存储层单源形状）
        assert kwargs["metadata"]["tags"] == ["重要", "工作"]

    def test_no_tags_leaves_metadata_untouched(self, app_client, mock_manager):
        resp = app_client.post(
            f"{BASE}",
            json={"content": "测试内容"},
            params={"agent_id": "default"},
        )
        assert resp.status_code == 200
        kwargs = mock_manager.remember.call_args.kwargs
        assert not (kwargs["metadata"] or {}).get("tags")

    def test_share_fields_reach_manager(self, app_client, mock_manager):
        """P1-10 残留实装：共享组写入字段经 AddMemoryRequest 透传到 remember。"""
        resp = app_client.post(
            f"{BASE}",
            json={"content": "测试内容", "shared": True, "share_group_ids": ["g1", "g2"]},
            params={"agent_id": "default"},
        )
        assert resp.status_code == 200, resp.text
        kwargs = mock_manager.remember.call_args.kwargs
        assert kwargs["shared"] is True
        assert kwargs["share_group_ids"] == ["g1", "g2"]


class TestMemoryListContract:
    def test_list_outputs_importance_and_tags(self, app_client, mock_manager):
        mock_manager.recall.return_value = [
            {
                "id": "mem_1",
                "agent_id": "default",
                "content": "内容",
                "category": "general",
                "memory_type": "semantic",
                "importance": 80.0,
                "metadata": {"tags": ["a", "b"]},
                "created_at": "2026-11-12T00:00:00",
            }
        ]
        resp = app_client.get(f"{BASE}", params={"agent_id": "default"})
        assert resp.status_code == 200
        row = resp.json()["data"]["memories"][0]
        # 读侧 0-100 → 0-1，页面 ×100 渲染
        assert row["importance"] == 0.8
        assert row["tags"] == ["a", "b"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
