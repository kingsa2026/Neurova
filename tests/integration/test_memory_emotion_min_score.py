"""`GET /memory/emotion/{type}` 的 `min_score` 必须真的过滤

根因链有两截，缺一个都不算修好：

1. 端点收下 `min_score` 却没往下传（`emotion.py` 只传 emotion/limit）；
2. 阈值在 `manager.get_memories_by_emotion` 里被写死 0.3，签名上根本没有入口。

下游 `EmotionModule.get_emotional_memories(min_intensity=...)` 早就支持按强度过滤，
所以这是**接线**，不是新造能力。

判据取行为并配反向对照：高阈值只留强情绪那条；阈值降到写死值之下时两条都必须在
（防止修法退化成恒空）。情绪行经 `manager.emotion_module` 这个公开 property 写入，
即生产写入口，不碰私有字段。
"""

import types
import typing

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api import auth as auth_mod
from neurova.api.endpoints.memory import router as memoryRouter
from neurova.api.error_handlers import register_error_handlers
from neurova.cognitive_layers.memory_layer.manager import MemoryManager
from neurova.cognitive_layers.memory_layer.modules.emotion_module import (
    EmotionState,
    EmotionType,
)

ALICE = {"user_id": "alice", "username": "alice", "role": "user", "neuser_id": "ne-alice"}


@pytest.fixture
def manager(tmp_path):
    return MemoryManager(db_path=str(tmp_path / "mem.db"), agent_id="agent_a")


@pytest.fixture
def client(manager, monkeypatch):
    agent = types.SimpleNamespace(memory_manager=manager)
    state = types.SimpleNamespace(agents={"agent_a": agent}, get_agent=lambda *a, **k: agent)
    monkeypatch.setattr("neurova.api.app.get_app_state", lambda: state)

    app = FastAPI()
    register_error_handlers(app)
    app.include_router(memoryRouter, prefix="/api/v1/memory")
    testClient = TestClient(app)
    testClient.app.dependency_overrides[auth_mod.get_current_user_or_default] = lambda: ALICE
    return testClient


def _create(client, content: str) -> str:
    r = client.post("/api/v1/memory", json={"content": content, "auto_classify": False})
    assert r.status_code == 200, r.text
    return r.json()["data"]["memory_id"]


def _attachJoy(manager, memoryId: str, intensity: float):
    manager.emotion_module.set_emotion(
        memoryId,
        EmotionState(
            primary_emotion=EmotionType.JOY,
            intensity=intensity,
            valence=0.6,
            arousal=0.3,
        ),
    )


def _idsAt(client, minScore: float) -> typing.Set[str]:
    r = client.get("/api/v1/memory/emotion/joy", params={"min_score": minScore, "limit": 20})
    assert r.status_code == 200, r.text
    return {m["id"] for m in r.json()["data"]["memories"]}


def test_highThresholdExcludesWeakEmotion(client, manager):
    weakId = _create(client, "情感弱的一跳")
    strongId = _create(client, "情感强的一跳")
    _attachJoy(manager, weakId, 0.4)
    _attachJoy(manager, strongId, 0.9)

    assert _idsAt(client, 0.7) == {strongId}, (
        "min_score=0.7 应只留强度 0.9 的那条（0.4 仍在结果里=min_score 未透传下游）"
    )


def test_lowThresholdKeepsBoth(client, manager):
    weakId = _create(client, "情感弱的一跳")
    strongId = _create(client, "情感强的一跳")
    _attachJoy(manager, weakId, 0.4)
    _attachJoy(manager, strongId, 0.9)

    assert _idsAt(client, 0.0) == {weakId, strongId}
