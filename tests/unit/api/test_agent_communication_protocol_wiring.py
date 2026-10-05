# -*- coding: utf-8 -*-
"""外部 Agent 通信端点的协议接线（版本协商 / 载荷上限 / 在线态）

本文件**刻意不 import** 待建的 `neurova.api.external_agent_protocol`：常量在测试侧
以「任何合理策略下都成立」的形式给出，这样在实现落地之前，这些用例是能跑的、
且因断言而失败——加载不了的测试证明不了它能抓住 bug。

限流**不在本文件断言**：它是 `RateLimitMiddleware` 的职责（见
`test_rate_limit_middleware_channel.py`），端点里不得再有第二处额度检查——
中间件在 handler 之前执行，端点级检查永远轮不到触发。

被测装配：`neurova.api.endpoints.agent_communication_api`。

行为约定：
- 不支持的版本 → 400；未声明版本 → 放行但响应里 protocol_negotiation 必须是 legacy。
- 载荷超限 → 413，且回显的上限值与真实执行的判据同源。
- 发消息要刷新 last_seen（现役只在握手/注册时写，导致超时判定会把所有 Agent 判离线）。
- 状态端点的 status 由 last_seen 派生，不再回恒真的 "online"。
"""

import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# 测试侧常量：刻意取"远超任何合理上限/窗口"的值，避免把策略数字写进测试。
OVERSIZED_BLOB_BYTES = 4 * 1024 * 1024  # 4 MB，必大于任何声明的 1 MB 级上限
STALE_SECONDS = 24 * 3600  # 24 小时前的活动，必落在任何在线窗口之外


@pytest.fixture()
def client(monkeypatch):
    """隔离装配：清模块级内存 store，覆盖鉴权，注入低额度 firewall。"""
    from neurova.api.endpoints import agent_communication_api as comm
    from neurova.core import firewall as firewall_mod

    comm._handshakes.clear()
    comm._messages.clear()
    comm._external_agents.clear()

    quota = firewall_mod.AgentFirewall(config_path=None)
    quota.update_global_rules({"external_rate_limit_per_minute": 2})
    monkeypatch.setattr(firewall_mod, "get_firewall", lambda *a, **k: quota)

    app = FastAPI()
    app.include_router(comm.router)
    # Depends 在模块导入时就把函数对象绑进了路由，monkeypatch 模块属性换不掉它——
    # 必须走 FastAPI 的 dependency_overrides，否则请求会撞 401「Not authenticated」。
    # 本域只剩一道合一门 `get_current_user_or_api_key`（JWT 与密钥同处判定），
    # 路由级 dependency 与各端点参数共享同一份缓存结果，所以只需覆盖这一处。
    app.dependency_overrides[comm.get_current_user_or_api_key] = lambda: {
        "user_id": "u1",
        "role": "user",
        "username": "u1",
    }
    return TestClient(app)


def _handshake(client, **overrides):
    body = {"agent_id": "ext-1", "agent_name": "External", "capabilities": ["chat"]}
    body.update(overrides)
    return client.post("/handshake", json=body)


def _seed_agent(client, agent_id="ext-1", last_seen=None):
    """把外部 Agent 塞进现役内存 store（端点读的即是这份）。"""
    from neurova.api.endpoints import agent_communication_api as comm

    record = {
        "agent_id": agent_id,
        "name": "External",
        "capabilities": ["chat"],
        "callback_url": None,
        "user_id": "u1",
        "last_seen": last_seen if last_seen is not None else time.time(),
        "status": "online",
    }
    comm._external_agents[agent_id] = record
    return record


def _send(client, content, target="ext-1"):
    return client.post(
        "/messages/send",
        json={"target_agent_id": target, "message_type": "text", "content": content},
    )


# ---------------------------------------------------------------------------
# 版本协商
# ---------------------------------------------------------------------------


def test_handshake_rejects_unsupported_protocol_version(client):
    resp = _handshake(client, supported_versions=["2.0"])
    assert resp.status_code == 400, resp.text
    assert "2.0" in resp.text


def test_handshake_marks_silent_client_as_legacy(client):
    resp = _handshake(client)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data.get("protocol_negotiation") == "legacy"
    assert data.get("server_protocol_version") == "1.0"


def test_handshake_reports_negotiated_when_version_matches(client):
    resp = _handshake(client, supported_versions=["1.0"])
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"].get("protocol_negotiation") == "negotiated"


# ---------------------------------------------------------------------------
# 载荷上限
# ---------------------------------------------------------------------------


def test_handshake_advertises_limits_the_server_actually_enforces(client):
    """握手回显必须与端点真实执行的判据同源。

    被退役的 communication_protocol 正是栽在这上面：它在响应里回显 max_message_size，
    却在整个文件里从不拦任何超限请求——回显成了谎报。
    """
    from neurova.api.external_agent_protocol import MAX_MESSAGE_BYTES

    resp = _handshake(client)
    data = resp.json()["data"]
    assert data.get("max_message_bytes") == MAX_MESSAGE_BYTES
    assert data.get("rate_limit_per_minute") == 2  # fixture 注入的 externalAgent 档


def test_send_message_rejects_oversized_payload(client):
    _seed_agent(client)
    resp = _send(client, {"blob": "x" * OVERSIZED_BLOB_BYTES})
    assert resp.status_code == 413, resp.text


# ---------------------------------------------------------------------------
# 在线态派生
# ---------------------------------------------------------------------------


def test_status_derives_idle_for_stale_agent(client):
    _seed_agent(client, "ext-2", last_seen=time.time() - STALE_SECONDS)
    resp = client.get("/external-agents/ext-2/status")
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"].get("status") == "idle"


def test_send_message_refreshes_agent_last_seen(client):
    """发消息是活动证据：陈旧 Agent 在收到投递后 last_seen 必须被刷新。"""
    stale = _seed_agent(client, "ext-3", last_seen=time.time() - STALE_SECONDS)
    _send(client, {"t": "ping"}, target="ext-3")
    assert stale["last_seen"] > time.time() - STALE_SECONDS / 2
