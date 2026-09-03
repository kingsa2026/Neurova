"""移动配对 WS 隔离与加固测试

审计修复 (docs/audit/three-tier-isolation-audit.md P0-4 / P1-8 / P2-12 / P3-18):
- session:list 原实现返回该 agent 下所有用户的完整会话 (含全部消息),
  任何已配对手机可拉取全员对话 → 必须按 user_id 过滤。
- session:create 原实现不绑定 user_id → 会话无归属。
- confirm_pairing 6 位配对码 300s TTL 无速率限制 → 每 IP 限流。
- 配对码用 random.randint (可预测) → 改 secrets。
- WS 连接无 per-user 上限 → DoS 友好, 加连接数上限。
"""

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from neurova.api.endpoints import mobile_pairing as mp
from neurova.api.endpoints.mobile_pairing import ConfirmPairingRequest


@pytest.fixture(autouse=True)
def clean_state(monkeypatch):
    """每个测试隔离模块级内存状态"""
    monkeypatch.setattr(mp, "_pairing_codes", {})
    monkeypatch.setattr(mp, "_paired_devices", {})
    monkeypatch.setattr(mp, "_user_devices", {})
    monkeypatch.setattr(mp, "_ws_connections", {})
    monkeypatch.setattr(mp, "_cancelled_sessions", {})
    monkeypatch.setattr(mp, "_confirm_attempts", {})
    monkeypatch.setattr(mp.MobileConnectionManager, "_instance", None)
    yield


class FakeWS:
    def __init__(self):
        self.sent = []
        self.closed = None
        self.accepted = False

    async def accept(self):
        self.accepted = True

    async def send_json(self, message):
        self.sent.append(message)

    async def close(self, code=1000, reason=""):
        self.closed = code


def _fake_request(host="10.0.0.1"):
    return SimpleNamespace(client=SimpleNamespace(host=host), headers={})


class TestSessionListIsolation:
    def test_session_list_scoped_to_ws_user(self, monkeypatch):
        captured = {}

        class StubSM:
            def list_sessions(self, agent_id="", user_id=""):
                captured["agent_id"] = agent_id
                captured["user_id"] = user_id
                return [{"session_id": "s1", "user_id": user_id}]

        monkeypatch.setattr("neurova.session_manager.get_session_manager", lambda: StubSM())

        ws = FakeWS()
        asyncio.run(mp._handle_session_list(ws, {"agent_id": "default"}, "user_42"))

        assert captured["user_id"] == "user_42"
        assert ws.sent and ws.sent[0]["type"] == "session:list"

    def test_session_create_binds_user(self, monkeypatch):
        captured = {}

        class StubSM:
            def create_session(self, agent_id="", user_id="", title=""):
                captured["agent_id"] = agent_id
                captured["user_id"] = user_id
                return "new_sid"

        monkeypatch.setattr("neurova.session_manager.get_session_manager", lambda: StubSM())

        ws = FakeWS()
        asyncio.run(mp._handle_session_create(ws, {"agent_id": "default"}, "user_42"))

        assert captured["user_id"] == "user_42"
        assert ws.sent and ws.sent[0]["type"] == "session:created"


class TestConfirmPairingRateLimit:
    def test_bruteforce_attempts_rate_limited(self):
        """同 IP 连续错误尝试超过阈值必须 429, 不能无限枚举 6 位配对码"""
        last_exc = None
        limited = False
        for _ in range(10):
            try:
                asyncio.run(
                    mp.confirm_pairing(
                        _fake_request(),
                        ConfirmPairingRequest(code="000000", device_name="evil"),
                    )
                )
            except HTTPException as e:
                if e.status_code == 429:
                    limited = True
                    break
                last_exc = e
        assert limited, f"10 次暴力尝试未被限流 (last={last_exc})"

    def test_rate_limit_is_per_ip(self):
        """不同 IP 的配额互不影响: IP1 用满 5 次配额后第 6 次被限流, IP2 不受影响"""
        # IP1: 前 5 次 404 (码不存在), 第 6 次必须 429
        statuses = []
        for _ in range(6):
            try:
                asyncio.run(
                    mp.confirm_pairing(
                        _fake_request(host="10.0.0.1"),
                        ConfirmPairingRequest(code="000000"),
                    )
                )
            except HTTPException as e:
                statuses.append(e.status_code)
        assert statuses[:5] == [404] * 5
        assert statuses[5] == 429

        # 换 IP 后配额独立 (此处 code 不存在 → 404, 而非 429)
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(
                mp.confirm_pairing(
                    _fake_request(host="10.0.0.2"),
                    ConfirmPairingRequest(code="000000"),
                )
            )
        assert exc_info.value.status_code == 404


class TestPairingCodeStrength:
    def test_pairing_code_does_not_use_mersenne_twister(self, monkeypatch):
        """配对码必须用 CSPRNG (secrets), 禁用 random.randint (P3-18)"""

        def _booby(*args, **kwargs):
            raise AssertionError("pairing code must use secrets, not random.randint")

        monkeypatch.setattr("random.randint", _booby)
        code = mp._generate_pairing_code()
        assert len(code) == 6 and code.isdigit()


class TestConnectionCap:
    def test_per_user_connection_cap(self):
        """单用户连接数超上限时拒绝新连接 (防止单用户耗尽资源)"""
        manager = mp.MobileConnectionManager.get_instance()
        sockets = []
        for i in range(mp.MAX_CONNECTIONS_PER_USER):
            ws = FakeWS()
            sockets.append(ws)
            ok = asyncio.run(manager.connect(ws, "user_1", f"conn_{i}"))
            assert ok is True

        extra = FakeWS()
        ok = asyncio.run(manager.connect(extra, "user_1", "conn_extra"))
        assert ok is False
        assert extra.accepted is False
