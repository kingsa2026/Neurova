"""`auto_analyze_emotion` 开关必须被消费

根因：`AddMemoryRequest.auto_analyze_emotion`（对外契约，前端类型也 advertise 这个字段）
一路传进 `manager.remember`，此前落 `**kwargs` 无人读取（该处注释自陈"其余控制参数
(留 kwargs)"），而自动情感标注在 `remember` 里**无条件执行**——参数声明了"可以关"，
行为上关不掉。属 AGENTS.md §2 点名的"只写不读的配置"。

判据双向，防止修法把主链路一起关掉：关掉开关不得落情绪行；默认（不传）照旧自动标注，
且必须是非 neutral——即收口前的实际行为不变。
"""

import types

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.endpoints.memory import router as memoryRouter
from neurova.api.error_handlers import register_error_handlers
from neurova.cognitive_layers.memory_layer.manager import MemoryManager
from neurova.cognitive_layers.memory_layer.modules.emotion_module import EmotionType
from tests.auth_headers import bearerHeaders

# C1（P3-12，2026-10-08）：写类请求的路由级门判的是「有没有凭证」，
# dependency_overrides 替不掉它；改签生产同一个函数产出的真 JWT，身份由凭证解析出来。
ALICE_HDR = bearerHeaders("alice")
EMOTIONAL_TEXT = "那次失败让我很沮丧，太伤心了"


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
    return testClient


def _remember(client, **body) -> str:
    r = client.post("/api/v1/memory",
                    json={"content": EMOTIONAL_TEXT, "auto_classify": False, **body},
                    headers=ALICE_HDR)
    assert r.status_code == 200, r.text
    return r.json()["data"]["memory_id"]


def test_switchOffSuppressesAutoAnnotation(client, manager):
    memoryId = _remember(client, auto_analyze_emotion=False)

    assert manager.emotion_module.get_emotion(memoryId) is None, (
        "auto_analyze_emotion=False 仍被自动标注，说明开关无人读取"
    )


def test_defaultStillAnnotates(client, manager):
    memoryId = _remember(client)

    state = manager.emotion_module.get_emotion(memoryId)
    assert state is not None, f"默认口径应自动标注情绪，实得 {state}"
    assert state.primary_emotion != EmotionType.NEUTRAL, (
        f"含情感词的文本应被标注为非 neutral，实得 {state.primary_emotion}"
    )
