# -*- coding: utf-8 -*-
"""智能体温度回显红测（移动端/PC 编辑表单对齐批发现的回显缺口）

缺陷：create/update 经 _temperature_from_body_config 把温度落进
AgentConfig.llm_config.temperature（保存链真实生效），但 agent_to_info
的 config 回显字典没有 temperature——编辑表单重开后温度恒显示默认 0.7。

锁定行为（镜像 max_tokens 回显形态）：
1. POST /agents config.temperature=0.3 → GET 回显 config.temperature=0.3
2. PUT /agents/{id} config.temperature=1.5 → GET 回显 1.5（局部更新语义）
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


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


def test_get_agent_echoes_temperature_for_edit_form(client, env):
    client.post(
        "/v1/agents",
        json={"agent_id": "pc3", "name": "PC3", "config": {"temperature": 0.3}},
    )

    detail = client.get("/v1/agents/pc3").json()
    assert detail["config"]["temperature"] == 0.3

    # 局部更新语义：PUT 只出现的键覆盖
    resp = client.put("/v1/agents/pc3", json={"config": {"temperature": 1.5}})
    assert resp.status_code == 200, resp.text
    detail = client.get("/v1/agents/pc3").json()
    assert detail["config"]["temperature"] == 1.5


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
