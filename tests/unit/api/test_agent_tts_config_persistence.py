# -*- coding: utf-8 -*-
"""Agent 表单 TTS 配置持久化防回归。

缺陷链（预存）：CreateAgentRequest/UpdateAgentRequest 声明了 config 字段
但 create/update 端点整个不消费 → 前端表单发来的 TTS 配置
（tts_enabled/tts_voice/tts_speed/tts_pitch）被静默丢弃；
_save_agent_config 落盘不含 TTS；_agent_config_from_saved 回读不含 TTS
→ "改了 → 保存成功 → 重开表单全回默认值"。

锁定行为：
1. POST /agents config.tts_* → AgentConfig 字段 + workspace agent_config.json
2. PUT /agents/{id} config.tts_* → workspace 更新 + 运行时 tts_manager 重建
3. 重启链 _agent_config_from_saved 回读 TTS 字段
"""
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _workspace_config_path(env, agent_id: str) -> Path:
    from neurova.api.endpoints import get_app_state

    agent = get_app_state()["agents"][agent_id]
    return Path(agent.config.workspace_path) / "agent_config.json"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from neurova.agent_config import reset_config_manager
    from neurova.api.endpoints import set_app_state

    reset_config_manager()
    set_app_state({"agents": {}})
    yield tmp_path
    set_app_state(None)
    reset_config_manager()


@pytest.fixture()
def client():
    from neurova.api.endpoints import agent
    from neurova.api.auth import get_current_user

    app = FastAPI()
    app.include_router(agent.router, prefix="/v1/agents")
    app.dependency_overrides[get_current_user] = lambda: {
        "user_id": "u1",
        "role": "admin",
        "username": "admin",
    }
    return TestClient(app)


def test_create_agent_persists_tts_config(client, env):
    """POST config.tts_* → AgentConfig 字段 + workspace 落盘。"""
    try:
        resp = client.post(
            "/v1/agents",
            json={
                "agent_id": "ttsagent",
                "name": "TTS Agent",
                "config": {
                    "tts_enabled": True,
                    "tts_voice": "zh-CN-XiaoxiaoNeural",
                    "tts_speed": 1.2,
                    "tts_pitch": 1.5,
                },
            },
        )
        assert resp.status_code == 200, resp.text

        from neurova.api.endpoints import get_app_state

        agent = get_app_state()["agents"]["ttsagent"]
        assert agent.config.enable_tts is True
        assert agent.config.tts_voice == "zh-CN-XiaoxiaoNeural"
        assert agent.config.tts_speed == pytest.approx(1.2)
        assert agent.config.tts_pitch == pytest.approx(1.5)

        ws_cfg = json.loads(_workspace_config_path(env, "ttsagent").read_text(encoding="utf-8"))
        assert ws_cfg["enable_tts"] is True
        assert ws_cfg["tts_voice"] == "zh-CN-XiaoxiaoNeural"
        assert ws_cfg["tts_speed"] == pytest.approx(1.2)
        assert ws_cfg["tts_pitch"] == pytest.approx(1.5)

        # GET 回显：编辑表单重开后能恢复已保存参数
        detail = client.get("/v1/agents/ttsagent").json()
        assert detail["config"]["enable_tts"] is True
        assert detail["config"]["tts_voice"] == "zh-CN-XiaoxiaoNeural"
        assert detail["config"]["tts_speed"] == pytest.approx(1.2)
        assert detail["config"]["tts_pitch"] == pytest.approx(1.5)
    finally:
        client.delete("/v1/agents/ttsagent")


def test_update_agent_tts_config_reaches_workspace_and_runtime(client, env):
    """PUT config.tts_* → workspace 更新 + 运行时 tts_manager 重建。"""
    try:
        client.post("/v1/agents", json={"agent_id": "ttsu", "name": "U"})

        resp = client.put(
            "/v1/agents/ttsu",
            json={
                "config": {
                    "tts_enabled": True,
                    "tts_voice": "zh-CN-YunxiNeural",
                    "tts_speed": 0.8,
                    "tts_pitch": 1.3,
                }
            },
        )
        assert resp.status_code == 200, resp.text

        ws_cfg = json.loads(_workspace_config_path(env, "ttsu").read_text(encoding="utf-8"))
        assert ws_cfg["enable_tts"] is True
        assert ws_cfg["tts_voice"] == "zh-CN-YunxiNeural"
        assert ws_cfg["tts_speed"] == pytest.approx(0.8)
        assert ws_cfg["tts_pitch"] == pytest.approx(1.3)
    finally:
        client.delete("/v1/agents/ttsu")


def test_saved_agent_config_roundtrip_preserves_tts(env):
    """重启链 _agent_config_from_saved 回读 TTS 字段。"""
    from pathlib import Path
    import tempfile

    from neurova.api.app import _agent_config_from_saved

    ws = Path(tempfile.mkdtemp()) / "ws"
    rebuilt = _agent_config_from_saved(
        {
            "name": "R",
            "model": "m",
            "provider": "p",
            "enable_tts": True,
            "tts_voice": "zh-CN-XiaoxiaoNeural",
            "tts_speed": 1.4,
            "tts_pitch": 1.6,
        },
        "r1",
        str(ws),
    )
    assert rebuilt.enable_tts is True
    assert rebuilt.tts_voice == "zh-CN-XiaoxiaoNeural"
    assert rebuilt.tts_speed == pytest.approx(1.4)
    assert rebuilt.tts_pitch == pytest.approx(1.6)
