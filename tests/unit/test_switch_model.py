"""红绿灯 TDD 测试：模型热切换端点 (C1 / P0 阻塞点)。

全链路根因：前端 ModelPage 切模型 -> POST /models/switch
-> model.py: switch_model 调用 `agent.rebuild_loop(model=body.model_id)`，
但 Agent.rebuild_loop 的真实签名是 `rebuild_loop(self, model_name)`。
关键字名错误 -> TypeError -> except 捕获后 raise HTTPException(500)
-> 模型热切换永远失败。

测试用 FakeAgent 暴露真实签名 rebuild_loop(self, model_name)，
直接调用 endpoint 函数以精确复现/验证该 bug。
"""
from __future__ import annotations

import asyncio
from starlette.requests import Request

from neurova.api.endpoints import model as model_module


class FakeAgent:
    """最小替身，暴露与 agent_core.Agent 一致的 rebuild_loop 签名。"""

    def __init__(self) -> None:
        self.rebuild_calls: list[str] = []

    def rebuild_loop(self, model_name: str) -> bool:
        # 与 neurova/agent_core.py: Agent.rebuild_loop(self, model_name) 一致
        self.rebuild_calls.append(model_name)
        return True


def _make_request() -> Request:
    scope = {"type": "http", "method": "POST", "path": "/switch", "headers": []}
    return Request(scope)


def test_switch_model_passes_model_name_keyword(monkeypatch):
    """switch_model 必须以 model_name= 关键字调用 rebuild_loop。"""
    agent = FakeAgent()
    monkeypatch.setattr(model_module, "_get_agent", lambda agent_id="default": agent)
    body = model_module.SwitchModelRequest(model_id="qwen2.5-72b", agent_id="agent_1")
    resp = asyncio.run(model_module.switch_model(_make_request(), body))
    assert resp["data"]["loop_rebuilt"] is True
    assert agent.rebuild_calls == ["qwen2.5-72b"]


def test_switch_model_missing_agent_returns_404(monkeypatch):
    """回归保护：找不到 agent 时仍返回 404，不破坏现有行为。"""
    monkeypatch.setattr(model_module, "_get_agent", lambda agent_id="default": None)
    body = model_module.SwitchModelRequest(model_id="x", agent_id="ghost")
    try:
        asyncio.run(model_module.switch_model(_make_request(), body))
        assert False, "expected HTTPException 404"
    except Exception as e:  # noqa: BLE001 - 验证状态码
        assert getattr(e, "status_code", None) == 404
