"""隧道准入、route 归属与「发码前先问通道」（设计方案 §4.4／§5.2，S2＋S0.5 批）。

为什么这些要单独立判据：中继是本设计**新引入的攻击面**。服务端向它注册时若不带准入凭据，
任何人都能注册一个撞名的 `routeId`，把别人手机侧的流量接走——这条一旦漏，
整套配对与身份链都白做。同理，`routeId` 必须由 (凭据, instanceId) **派生**而不是调用方自报，
否则"抢名"就是注册接口的默认行为。

第二组判据是通道读数：配了中继又没注册上时发出的二维码，手机扫了必然连不上。
那种时刻把面板渲染成"等待扫码"就是把故障扮成进行中（AGENTS §2）。

跑法：`.venv/Scripts/python.exe -m pytest -q tests/unit/tunnel -p no:cacheprovider`
"""
import os
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_tunnel_01234567")

from neurova.api.endpoints import mobile_pairing as MP  # noqa: E402
from neurova.relay.app import RelayState, _routeIdFor, create_relay_app  # noqa: E402
from neurova.tunnel import protocol  # noqa: E402
from neurova.tunnel.agent import TunnelAgent  # noqa: E402

TOKEN_A = "enrollment-token-aaaa"
TOKEN_B = "enrollment-token-bbbb"
PREFIX = "/api/v1/mobile"


# ---------------------------------------------------------------------------
# 准入与 routeId 归属
# ---------------------------------------------------------------------------


class TestEnrollmentAdmission:
    def test_state_rejects_missing_and_wrong_tokens(self):
        state = RelayState(TOKEN_A)
        assert state.admits(TOKEN_A) is True, "正向格：对的凭据必须放行"
        assert state.admits(None) is False
        assert state.admits("") is False
        assert state.admits(TOKEN_B) is False, "错的凭据被放行＝任何人都能注册"

    def test_empty_enrollment_token_refuses_to_build(self):
        """空凭据等于"没有入口的闸门"，中继必须拒绝启动而不是默认放开。"""
        with pytest.raises(ValueError):
            RelayState("")

    def test_route_id_is_derived_not_self_reported(self):
        """同 (凭据, instanceId) 必得同一 routeId；换凭据不得撞到别人的名字。"""
        first = _routeIdFor(TOKEN_A, "nv-instance-1")
        assert first == _routeIdFor(TOKEN_A, "nv-instance-1"), "重注册换了名字＝已配对设备要重扫"
        assert first != _routeIdFor(TOKEN_B, "nv-instance-1"), "换凭据仍撞名＝可以抢注别人的 route"
        assert first != _routeIdFor(TOKEN_A, "nv-instance-2")

    def test_control_websocket_without_valid_enrollment_is_closed(self):
        app = create_relay_app(TOKEN_A)
        with TestClient(app) as c:
            with pytest.raises(Exception) as raised:
                with c.websocket_connect(
                        f"{protocol.RELAY_CONTROL_PATH}?{protocol.ENROLLMENT_TOKEN_PARAM}=wrong"
                        "&instanceId=nv-x"):
                    pass
            assert getattr(raised.value, "code", None) == 4401, (
                f"错凭据的控制连接被回成 {raised.value!r}，不是 4401 拒绝")

    def test_control_websocket_with_valid_enrollment_gets_a_route(self):
        app = create_relay_app(TOKEN_A)
        with TestClient(app) as c:
            with c.websocket_connect(
                    f"{protocol.RELAY_CONTROL_PATH}?{protocol.ENROLLMENT_TOKEN_PARAM}={TOKEN_A}"
                    "&instanceId=nv-stable") as ws:
                registered = ws.receive_json()
        assert registered["type"] == protocol.FRAME_REGISTERED, registered
        assert registered["routeId"] == _routeIdFor(TOKEN_A, "nv-stable"), (
            "注册回的 routeId 不是派生那一个——入口将无法对上这条隧道")


# ---------------------------------------------------------------------------
# 未就绪时的诚实失败
# ---------------------------------------------------------------------------


class TestNotReadyFailsHonestly:
    def test_http_entry_without_agent_returns_503_with_named_code(self):
        """agent 没注册时必须显式 503 ＋ 点名 `tunnel_not_ready`，不静默重发也不 200 空体。"""
        app = create_relay_app(TOKEN_A)
        routeId = _routeIdFor(TOKEN_A, "nv-offline")
        with TestClient(app) as c:
            resp = c.get(f"{protocol.RELAY_ROUTE_PREFIX}{routeId}/api/v1/mobile/pairing/status/1")
        assert resp.status_code == 503, f"回的是 {resp.status_code}：{resp.text[:120]}"
        assert resp.json()["code"] == protocol.TUNNEL_ERROR_CODES[0], resp.json()

    def test_ws_entry_without_agent_closes_with_named_reason(self):
        app = create_relay_app(TOKEN_A)
        routeId = _routeIdFor(TOKEN_A, "nv-offline")
        with TestClient(app) as c:
            with pytest.raises(Exception) as raised:
                with c.websocket_connect(f"{protocol.RELAY_ROUTE_PREFIX}{routeId}/ws"):
                    pass
        assert getattr(raised.value, "code", None) == 4503, repr(raised.value)


# ---------------------------------------------------------------------------
# 隧道状态机（agent 侧读数）
# ---------------------------------------------------------------------------


class TestAgentStateReading:
    def test_unconfigured_agent_reports_disabled_and_does_not_dial(self):
        agent = TunnelAgent(relayUrl="", instanceId="nv-1")
        status = agent.tunnelStatus()
        assert status["state"] == "disabled", status
        assert status["configured"] is False

    def test_configured_but_unregistered_reads_as_not_via_relay(self):
        """面板与发码闸门读的是这一条：配了中继、还没注册上 ⇒ 不能发码。"""
        agent = TunnelAgent(relayUrl="https://relay.example", instanceId="nv-1")
        assert agent.tunnelStatus()["state"] == "probing"
        assert agent.tunnelStatus()["configured"] is True

    def test_registered_pseudo_state_exposes_route_for_address_building(self):
        agent = TunnelAgent(relayUrl="https://relay.example", instanceId="nv-1")
        agent.state = "via_relay"
        agent.routeId = "abc123def456"
        agent.lastHeartbeatAt = time.time()
        status = agent.tunnelStatus()
        assert status["route_id"] == "abc123def456"
        assert status["active_streams"] == 0


# ---------------------------------------------------------------------------
# 面板读数 + 发码闸门（S0.5）
# ---------------------------------------------------------------------------


@pytest.fixture()
def panel(monkeypatch):
    MP._pairing_codes.clear()
    MP._confirm_attempts.clear()
    MP.resetDeviceRegistry()
    app = FastAPI()
    app.include_router(MP.router, prefix=PREFIX)
    app.dependency_overrides[MP._get_current_user_id] = lambda: "kai"
    with TestClient(app, base_url="http://testserver", raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()
    MP._pairing_codes.clear()


class TestTunnelStatusFaceAndGenerateGate:
    def test_status_endpoint_is_gated_and_returns_the_state(self, panel, monkeypatch):
        from neurova.tunnel import agent as agentModule

        monkeypatch.setattr(agentModule, "_agent", TunnelAgent(relayUrl="", instanceId="nv-1"))
        resp = panel.get(f"{PREFIX}/pairing/tunnel/status")
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["state"] in protocol.TUNNEL_STATES, resp.json()
        assert resp.json()["data"]["address_source"] in protocol.ADDRESS_SOURCES

    def test_generate_is_refused_when_relay_configured_but_not_registered(self, panel, monkeypatch):
        """§5.5 第 6 条：闸门必须在**后端**，面板 disable 只是 UX。

        收窄说明（已回写设计文档）：只拒"配了中继又没注册上"这一形。
        把"没配中继"也拒掉会打死已上线的局域网/自建反代配对——
        规则与行为不符时以改规则为准，不是拿规则去杀功能。
        """
        from neurova.tunnel import agent as agentModule

        monkeypatch.setattr(agentModule, "_agent",
                            TunnelAgent(relayUrl="https://relay.example", enrollmentToken="t",
                                        instanceId="nv-1"))
        resp = panel.post(f"{PREFIX}/pairing/generate", json={"device_name": "probe"})
        assert resp.status_code == 503, f"配了中继没注册却仍发了码：{resp.status_code} {resp.text[:160]}"
        detail = resp.json()["detail"]
        assert detail["code"] == protocol.TUNNEL_ERROR_CODES[0], detail
        assert detail["tunnel_state"] == "probing", detail

    def test_generate_still_works_when_no_relay_is_configured(self, panel, monkeypatch):
        """反向格：闸门不得把局域网/反代那两条路一起关掉。"""
        from neurova.tunnel import agent as agentModule

        monkeypatch.setattr(agentModule, "_agent", TunnelAgent(relayUrl="", instanceId="nv-1"))
        resp = panel.post(f"{PREFIX}/pairing/generate", json={"device_name": "probe"})
        assert resp.status_code == 200, f"没配中继就发不了码了（局域网配对被杀）：{resp.text[:160]}"

    def test_relay_route_takes_precedence_over_advertised(self, panel, monkeypatch):
        """地址来源优先级：注册上的隧道 route > advertised > 入站（§5.2／§7）。"""
        from neurova.tunnel import agent as agentModule

        monkeypatch.setenv("NEUROVA_ADVERTISED_BASE_URL", "https://home.example.net")
        agent = TunnelAgent(relayUrl="https://relay.example", instanceId="nv-1")
        agent.state = "via_relay"
        agent.routeId = "route1234567"
        monkeypatch.setattr(agentModule, "_agent", agent)

        gen = panel.post(f"{PREFIX}/pairing/generate", json={"device_name": "probe"}).json()
        conf = panel.post(f"{PREFIX}/pairing/resolve", json={"ref": gen["ref"]}).json()

        assert "relay.example" in conf["ws_url"], conf["ws_url"]
        assert f"/t/route1234567/" in conf["ws_url"], conf["ws_url"]
        assert "home.example.net" not in conf["ws_url"], (
            f"隧道已注册却还发 advertised 那条地址：{conf['ws_url']}")
