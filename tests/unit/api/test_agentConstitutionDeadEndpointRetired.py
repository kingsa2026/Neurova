# -*- coding: utf-8 -*-
"""宪法死端点退役守卫（E1 卡，2026-11-18）。

根因（把报错恢复原状就会复现）：`neurova/api/endpoints/agent.py` 曾挂
`GET/PUT /api/v1/agents/{agent_id}/constitution`，内部以
`hasattr(agent, "get_constitution") / hasattr(agent, "update_constitution")`
防御式调用——但 Agent 类（`neurova/agent_core.py`）全仓**不存在**这两个方法，
于是 GET 恒返回 `{}`、PUT 静默 no-op 却报「Constitution updated」（谎报成功）。
真正生效的宪法规则通道是 `/v1/growth` 的 rules CRUD
（`neurova/api/endpoints/constitution_router.py`，前端 `growth.ts`）。

本守卫钉死两条不变量，防同一根因复活：
1. Agent 类不得再出现 `get_constitution` / `update_constitution` 属性
   （旧端点的 `hasattr` 防御正是靠这两个名字诈尸）；
2. 旧路由不再注册于 agent 路由表——挂上生产同款前缀、state 里备好目标
   agent 后打旧路径，必须「路由不存在」404。注意 agent 在册时旧 GET/PUT
   本可 200，故此 404 只能来自路由退役，不会与「agent 不存在」的 404 混淆。

实现注记：FastAPI ≥0.142 的 `include_router` 把子路由包进 `_IncludedRouter`
（不再摊平进 `app.routes`），逐层下钻才能看到真实路由——直接平铺遍历会
对旧路由失明。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.auth import get_current_user
from neurova.api.endpoints import agent as agent_ep

# 生产挂载前缀（与 neurova/api/endpoints/__init__.py 的 ENDPOINT_MODULES 同款）
_AGENT_PREFIX = "/v1/agents"


def test_agentClassHasNoConstitutionMethods():
    """Agent 类不得复活 get_constitution / update_constitution 方法。"""
    from neurova.agent_core import Agent

    for name in ("get_constitution", "update_constitution"):
        assert not hasattr(Agent, name), (
            f"Agent 类出现了 {name} 属性——旧宪法死端点的 hasattr 防御将随之复活，"
            f"GET 恒 {{}} / PUT 谎报成功的故障会原样回归。"
        )


def _iterRouteLeaves(routes):
    """递归展开路由树：叶子产出 (path, methods)；_IncludedRouter/嵌套 router/Mount 下钻。"""
    for route in routes:
        if hasattr(route, "original_router"):
            yield from _iterRouteLeaves(route.original_router.routes)
        elif hasattr(route, "routes"):
            yield from _iterRouteLeaves(route.routes)
        else:
            yield getattr(route, "path", ""), getattr(route, "methods", None) or set()


@pytest.fixture()
def agentApp(monkeypatch):
    """挂生产同款 agent router 的裸应用；state 备好目标 agent + admin 身份。"""
    app = FastAPI()
    app.include_router(agent_ep.router, prefix=_AGENT_PREFIX)
    app.dependency_overrides[get_current_user] = lambda: {
        "user_id": "u1",
        "role": "admin",
        "username": "admin",
    }
    # state 里备好目标 agent：旧端点在册时本可 200，路由退役后才会 404。
    # 属主 u1 + admin 身份 → 旧 PUT 的属主门也放行，排除 403 干扰。
    stubAgent = SimpleNamespace(config=SimpleNamespace(owner_user_id="u1"))
    monkeypatch.setattr(agent_ep, "_get_app_state", lambda: {"agents": {"default": stubAgent}})
    return app


def test_constitutionRoutesNoLongerRegistered(agentApp):
    """agent 路由表不得再含任何 constitution 路由。"""
    hits = []
    for path, methods in _iterRouteLeaves(agentApp.routes):
        if "constitution" in path:
            hits.append(f"{','.join(sorted(methods))} {path}")
    assert not hits, "旧宪法路由仍在注册表内：\n" + "\n".join(hits)


def test_constitutionEndpointsReturn404(agentApp):
    """GET/PUT 旧宪法端点必须 404（agent 在册+已登录，404 只能是路由退役）。"""
    client = TestClient(agentApp)
    getResp = client.get(f"{_AGENT_PREFIX}/default/constitution")
    assert getResp.status_code == 404, (
        f"GET 旧宪法端点未退役：{getResp.status_code} {getResp.text[:200]}"
    )
    putResp = client.put(
        f"{_AGENT_PREFIX}/default/constitution", json={"constitution": {"rules": []}}
    )
    assert putResp.status_code == 404, (
        f"PUT 旧宪法端点未退役：{putResp.status_code} {putResp.text[:200]}"
    )
