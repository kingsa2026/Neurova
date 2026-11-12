# -*- coding: utf-8 -*-
"""P1-5 Agent 表单 max_tokens 消费面红测（全库断点审计 2026-11-12）

缺陷：前端提交 config.max_tokens，但 agent.py 对 max_tokens 零消费
（create/update 均不读）——"最大令牌"改了 → 保存成功 → 重开全回默认。
同病先例：TTS 字段（已修，见 test_agent_tts_config_persistence.py）与
温度（2026-09-10 断链修复）。system_prompt 经查后端无对应字段、
无任何消费方——按审计走"前端删输入框"路线，不在本测试面。

锁定行为（镜像 TTS 防回归三腿）：
1. POST /agents config.max_tokens → llm_config.max_tokens + workspace 落盘
2. PUT /agents/{id} config.max_tokens → llm_config 更新 + 落盘
3. 重启链 _agent_config_from_saved 回读 max_tokens
"""
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _workspace_config_path(agent_id: str) -> Path:
    from neurova.core.agent_workspaces import get_agent_config_path

    return get_agent_config_path(agent_id)


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


def test_create_agent_consumes_max_tokens(client, env):
    try:
        resp = client.post(
            "/v1/agents",
            json={"agent_id": "mt1", "name": "MT", "config": {"max_tokens": 8192}},
        )
        assert resp.status_code == 200, resp.text

        from neurova.api.endpoints import get_app_state

        agent = get_app_state()["agents"]["mt1"]
        assert agent.config.llm_config.max_tokens == 8192

        ws_cfg = json.loads(_workspace_config_path("mt1").read_text(encoding="utf-8"))
        assert ws_cfg["max_tokens"] == 8192

        # GET 回显：编辑表单重开后能恢复已保存参数
        detail = client.get("/v1/agents/mt1").json()
        assert detail["config"]["max_tokens"] == 8192
    finally:
        client.delete("/v1/agents/mt1")


def test_update_agent_max_tokens_reaches_llm_config_and_workspace(client, env):
    try:
        client.post("/v1/agents", json={"agent_id": "mt2", "name": "M2"})

        resp = client.put(
            "/v1/agents/mt2",
            json={"config": {"max_tokens": 4096}},
        )
        assert resp.status_code == 200, resp.text

        from neurova.api.endpoints import get_app_state

        agent = get_app_state()["agents"]["mt2"]
        assert agent.config.llm_config.max_tokens == 4096

        ws_cfg = json.loads(_workspace_config_path("mt2").read_text(encoding="utf-8"))
        assert ws_cfg["max_tokens"] == 4096
    finally:
        client.delete("/v1/agents/mt2")


def test_saved_agent_config_roundtrip_preserves_max_tokens(env):
    from pathlib import Path
    import tempfile

    from neurova.api.app import _agent_config_from_saved

    ws = Path(tempfile.mkdtemp()) / "ws"
    rebuilt = _agent_config_from_saved(
        {"name": "R", "model": "m", "provider": "p", "max_tokens": 8192},
        "r1",
        str(ws),
    )
    assert rebuilt.llm_config.max_tokens == 8192


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
