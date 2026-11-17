# -*- coding: utf-8 -*-
"""AgentInfo.created_at/last_active 投影赋值断链防回归（U1 复核移交，R7 修复）。

缺陷链（U1-产品拍板收尾 §3 复核实锤）：
- AgentInfo 声明 created_at/last_active（agent.py），但全部投影构造点
  （agent_to_info 的四处 AgentInfo(**info)、list/get 的 config_only 直构）
  从不赋值——实测响应恒 null；
- 事实源一直在写：中枢登记面 AgentConfigManager（data/agents/agents.json）
  create_agent 落 created_at、update_agent 刷 last_active，登记面字段齐全
  却零读取方——登记面字段只写不读 + 投影恒 null，断链两头都断；
- 鸿蒙 AgentsApi.createdAt（dc4cc4949 改读 created_at）因此恒空串。

根因修法：投影构造点统一从登记面读数；登记面无行的 agent（如 default
启动期直建、不经 POST 登记）保持 None——诚实未知，不用会漂移的文件
时间伪造（教义第 2 条诚实形态）。
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """真登记面（AgentConfigManager，落 tmp_path/data/agents）+ 真 state。"""
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
    from neurova.api.auth import get_current_user

    from neurova.api.endpoints import agent

    app = FastAPI()
    app.include_router(agent.router, prefix="/v1/agents")
    app.dependency_overrides[get_current_user] = lambda: {
        "user_id": "u1",
        "role": "admin",
        "username": "admin",
    }
    return TestClient(app)


def test_create_response_carries_created_at(client, env):
    """POST 创建响应必须带 created_at（事实源：登记面 create_agent 落点）。"""
    try:
        resp = client.post("/v1/agents", json={"agent_id": "tsagent", "name": "T"})
        assert resp.status_code == 200, resp.text
        created_at = resp.json()["created_at"]
        assert created_at is not None and created_at != "", resp.json()
        # 事实源耦合：响应值必须等于登记面 create_agent 落下的那一条
        from neurova.agent_config import get_config_manager

        expected = (get_config_manager().get_agent("tsagent") or {}).get("created_at")
        assert expected and created_at == expected, (created_at, expected)
    finally:
        client.delete("/v1/agents/tsagent")


def test_list_and_detail_carries_created_at(client, env):
    """GET 列表与详情投影必须回传登记面的 created_at/last_active。"""
    try:
        resp = client.post("/v1/agents", json={"agent_id": "tsagent2", "name": "T2"})
        assert resp.status_code == 200, resp.text

        listed = client.get("/v1/agents").json()
        row = next(a for a in listed if a["agent_id"] == "tsagent2")
        assert row["created_at"] is not None and row["created_at"] != "", row

        detail = client.get("/v1/agents/tsagent2").json()
        assert detail["created_at"] is not None and detail["created_at"] != "", detail
    finally:
        client.delete("/v1/agents/tsagent2")


def test_config_only_agent_carries_created_at(client, env):
    """仅登记面有行的 agent（未启动实例）投影也必须回传 created_at。"""
    from neurova.agent_config import get_config_manager

    assert get_config_manager().create_agent(
        agent_id="cfgonly", name="CfgOnly", description=""
    )
    expected = (get_config_manager().get_agent("cfgonly") or {}).get("created_at")
    detail = client.get("/v1/agents/cfgonly").json()
    assert detail["status"] == "config_only", detail
    assert detail["created_at"] is not None and detail["created_at"] != "", detail
    assert detail["created_at"] == expected, (detail["created_at"], expected)


def test_update_response_carries_created_at(client, env):
    """PUT 更新响应必须回传登记面 created_at（同契约生产方扫平，教义第 5 条）。"""
    from neurova.agent_config import get_config_manager

    try:
        resp = client.post("/v1/agents", json={"agent_id": "upagent", "name": "U"})
        assert resp.status_code == 200, resp.text
        expected = (get_config_manager().get_agent("upagent") or {}).get("created_at")
        assert expected, "登记面必须已落 created_at"

        resp = client.put("/v1/agents/upagent", json={"description": "改描述"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["created_at"] == expected, (
            resp.json()["created_at"],
            expected,
        )
    finally:
        client.delete("/v1/agents/upagent")


def test_unregistered_agent_reports_null_created_at(client, env):
    """登记面无行的 agent 投影保持 None——诚实未知，不许伪造文件时间兜底。

    真链路构造：端点创建（登记面有行）→ 用登记面 API 删行（state agent 仍在）
    → 详情投影读不到登记行 → created_at 必须为 null。
    """
    from neurova.agent_config import get_config_manager

    try:
        resp = client.post("/v1/agents", json={"agent_id": "noReg", "name": "N"})
        assert resp.status_code == 200, resp.text
        assert get_config_manager().delete_agent("noReg")

        detail = client.get("/v1/agents/noReg").json()
        assert detail["status"] == "running", detail
        assert detail["created_at"] is None, detail
    finally:
        client.delete("/v1/agents/noReg")
