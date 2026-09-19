# -*- coding: utf-8 -*-
"""GET /memory/emotion/timeline 端点契约测试（2026-09-19，情绪变化时间轴）。

关键风险：memory/emotion.py 文件头注明 `/emotion/{emotion_type}` 路径参数路由
会吞掉其后注册的字面路由——timeline 必须排在它之前，否则请求会被按情绪类型处理。
"""
import os
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_timeline_0123456789")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.auth import get_current_user_or_default
from neurova.api.endpoints.memory.emotion import router

BASE = "/api/v1/memory"

_TIMELINE = {
    "range": "7d",
    "bucket": "day",
    "points": [
        {"ts": 1, "label": "09-13", "valence": None, "count": 0,
         "peak_emotion": None, "peak_intensity": None, "excerpt": ""},
        {"ts": 2, "label": "09-14", "valence": -0.4, "count": 2,
         "peak_emotion": "anger", "peak_intensity": 0.8, "excerpt": "网页搜索失败"},
    ],
}


@pytest.fixture
def mock_manager():
    mm = MagicMock()
    mm.get_emotion_timeline.return_value = _TIMELINE
    return mm


@pytest.fixture
def client(mock_manager):
    app = FastAPI()
    with patch(
        "neurova.api.endpoints.memory.emotion.get_memory_manager", return_value=mock_manager
    ):
        app.include_router(router, prefix=BASE)
        app.dependency_overrides[get_current_user_or_default] = lambda: {
            "user_id": "7",
            "neuser_id": "7",
            "role": "user",
        }
        yield TestClient(app)


def test_timeline_returns_bucketed_points(client, mock_manager):
    """若被 /emotion/{emotion_type} 吞掉，响应不会是这套桶结构。"""
    res = client.get(f"{BASE}/emotion/timeline", params={"agent_id": "default"})

    assert res.status_code == 200
    body = res.json()
    assert body["code"] == 0
    assert body["data"]["bucket"] == "day"
    assert body["data"]["points"][-1]["valence"] == -0.4
    assert body["data"]["points"][0]["valence"] is None
    assert body["data"]["points"][-1]["excerpt"] == "网页搜索失败"


def test_range_and_default_reach_manager(client, mock_manager):
    client.get(f"{BASE}/emotion/timeline", params={"range": "30d"})
    assert mock_manager.get_emotion_timeline.call_args.args[0] == "30d"

    client.get(f"{BASE}/emotion/timeline")
    assert mock_manager.get_emotion_timeline.call_args.args[0] == "7d"


def test_agent_id_selects_manager_scope(mock_manager):
    app = FastAPI()
    with patch(
        "neurova.api.endpoints.memory.emotion.get_memory_manager"
    ) as getter:
        getter.return_value = mock_manager
        app.include_router(router, prefix=BASE)
        app.dependency_overrides[get_current_user_or_default] = lambda: {
            "user_id": "7",
            "neuser_id": "7",
            "role": "user",
        }
        res = TestClient(app).get(f"{BASE}/emotion/timeline", params={"agent_id": "agent-9"})

    assert res.status_code == 200
    assert getter.call_args.args[0] == "agent-9"


def test_invalid_range_rejected_at_boundary(client):
    res = client.get(f"{BASE}/emotion/timeline", params={"range": "1y"})

    assert res.status_code == 422
