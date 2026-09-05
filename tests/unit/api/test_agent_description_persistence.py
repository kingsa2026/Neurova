# -*- coding: utf-8 -*-
"""AgentConfig.description 字段化防回归（修复教义台账收口）。

缺陷链（预存）：AgentConfig 无 description 声明字段 →
- POST /agents 的 description 不进运行时 config，workspace 文件恒空串；
- PUT /agents/{id} 的 hasattr 守卫静默跳过，描述修改只落中枢登记面
  （data/agents/agents.json），workspace 与 GET 响应均不回显；
- 重启加载链（_agent_config_from_saved）靠动态属性回填——写侧缺失使
  动态回填永远读到空串，描述在"改→重启"间丢失。

根因修法：AgentConfig 声明 description 字段，create_agent 构造时透传。
锁定行为：
1. 字段存在且默认空串（存量构造零破坏）
2. POST 创建 → workspace agent_config.json 落盘描述
3. PUT 修改 → workspace 更新 + GET 响应回显（hasattr 守卫恢复语义）
4. 重启链 _agent_config_from_saved 回读 description
"""
import json
import tempfile
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _workspace_config_path(env, agent_id: str) -> Path:
    """从运行时 agent 自报的 workspace_path 定位 agent_config.json。

    create 端点的 workspace 是 __file__ 推导的仓库绝对路径（不吃 CWD
    chdir）——断言必须走 agent 自报路径，测试不留仓库污染。
    """
    from neurova.api.endpoints import get_app_state

    agent = get_app_state()["agents"][agent_id]
    return Path(agent.config.workspace_path) / "agent_config.json"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from neurova.agent_config import reset_config_manager
    from neurova.api.endpoints import set_app_state

    reset_config_manager()
    # 预置空 state（非 None）：create/update 走全运行时链（agent 挂进 state）
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


def test_agentconfig_has_description_field():
    """字段声明存在，默认空串（存量构造零破坏）。"""
    from neurova.agent_core import AgentConfig
    import tempfile
    from pathlib import Path

    cfg = AgentConfig(
        name="t", agent_id="t1", workspace_path=str(Path(tempfile.mkdtemp()))
    )
    assert cfg.description == ""
    cfg2 = AgentConfig(
        name="t", agent_id="t2", description="有描述",
        workspace_path=str(Path(tempfile.mkdtemp())),
    )
    assert cfg2.description == "有描述"


def test_create_agent_persists_description_to_workspace(client, env):
    try:
        resp = client.post(
            "/v1/agents",
            json={"agent_id": "descagent", "name": "Desc", "description": "创建即落盘"},
        )
        assert resp.status_code == 200, resp.text
        cfg_path = _workspace_config_path(env, "descagent")
        ws_cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        assert ws_cfg["description"] == "创建即落盘", ws_cfg
        detail = client.get("/v1/agents/descagent").json()
        assert detail["description"] == "创建即落盘"
    finally:
        # create 端点的 workspace 是仓库绝对路径——用 DELETE 端点完整清理
        client.delete("/v1/agents/descagent")


def test_update_agent_description_reaches_workspace(client, env):
    """PUT description → hasattr 守卫恢复语义：workspace 真实更新 + 响应回显。"""
    try:
        client.post(
            "/v1/agents",
            json={"agent_id": "uagent", "name": "U", "description": "旧描述"},
        )
        resp = client.put(
            "/v1/agents/uagent",
            json={"description": "新描述"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["description"] == "新描述"
        cfg_path = _workspace_config_path(env, "uagent")
        ws_cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        assert ws_cfg["description"] == "新描述", ws_cfg
    finally:
        client.delete("/v1/agents/uagent")


def test_saved_agent_config_roundtrip_preserves_description(env):
    """重启链 _agent_config_from_saved 回读 description（读侧契约锁定）。"""
    from pathlib import Path

    from neurova.agent_core import AgentConfig

    from neurova.api.app import _agent_config_from_saved

    ws = Path(tempfile.mkdtemp()) / "ws"
    cfg = AgentConfig(
        name="R", agent_id="r1", description="重启后仍在",
        workspace_path=str(ws),
    )
    assert cfg.description == "重启后仍在"
    rebuilt = _agent_config_from_saved(
        {"name": "R", "model": "m", "provider": "p", "description": "重启后仍在"},
        "r1",
        str(ws),
    )
    assert rebuilt.description == "重启后仍在"
