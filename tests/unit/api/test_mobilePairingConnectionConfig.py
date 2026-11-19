"""配对连接方式选择（档一）的 API 咬合守卫。

面板三选一（直连 / 自定义对外地址 / 自建中继）落在三个端点上：
- `GET  /api/v1/mobile/pairing/connection-config`（admin）——读当前配置（令牌只回掩码）；
- `PUT  /api/v1/mobile/pairing/connection-config`（admin）——写配置并**立即重建出站 agent**；
- `POST /api/v1/mobile/pairing/connection-config/preflight`（admin）——对所填地址做
  连通性预检，结果如实回（连不上就是 ok=False + 原因，不静默降级）。

判据核心（行为读数，不是"存了就算"）：
1. 选了 custom，`generate → confirm` 发给设备的 `ws_url` 必须**就是**那个地址
   （手机照着它连）——这是本功能的全部意义；
2. 选了 relay 但中继没注册上，发码必须被 503 `tunnel_not_ready` 拦下（设计方案 §8-S0.5）；
3. 选了 direct，即使 env 里配了广播地址，发出去的也是入站地址；
4. 准入令牌全文不出读口；
5. 非管理员 403（角色门走真实 strictIdentityGate 链）。
"""
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api import deps as apiDeps
from neurova.tunnel import connection_config as CC

PREFIX = "/api/v1/mobile"

ADMIN = {"user_id": "1", "username": "root-admin", "role": "admin",
         "neuser_id": "1", "tenant_id": "default"}
PLAIN_USER = {"user_id": "10006", "username": "chatverify", "role": "user",
              "neuser_id": "10006", "tenant_id": "default"}


@pytest.fixture()
def api(monkeypatch):
    """隔离面：配对码/在册表清空 + 连接配置文件清盘 + env 基线 + 身份门可切换。"""
    from neurova.api.endpoints import mobile_pairing as MP

    MP._pairing_codes.clear()
    MP.resetDeviceRegistry()
    path = CC.configFilePath()
    if path.exists():
        path.unlink()
    monkeypatch.setenv("NEUROVA_ADVERTISED_BASE_URL", "https://env-advertised.example.com")
    monkeypatch.delenv("NEUROVA_TUNNEL_RELAY_URL", raising=False)
    monkeypatch.delenv("NEUROVA_TUNNEL_ENROLLMENT_TOKEN", raising=False)

    # 出站 agent 每测重建为"未配置"态：env 的中继变量已删，谁也别带着上一测的连接进来
    from neurova.tunnel.agent import TunnelAgent, setTunnelAgent

    setTunnelAgent(TunnelAgent())

    app = FastAPI()

    @app.get("/health")
    async def _health():  # 探针目标：预检（无 url）会打这个入站来源
        return {"status": "ok"}

    app.include_router(MP.router, prefix=PREFIX)
    current = {"identity": ADMIN}
    app.dependency_overrides[apiDeps.strictIdentityGate] = lambda: current["identity"]
    # 发码面走它自己的 JWT 依赖（与 admin 门是两条链）：同样按当前身份放行
    app.dependency_overrides[MP._get_current_user_id] = lambda: current["identity"]["user_id"]
    client = TestClient(app)

    yield {"client": client, "app": app, "MP": MP, "current": current}
    app.dependency_overrides.clear()
    MP._pairing_codes.clear()
    MP.resetDeviceRegistry()
    if path.exists():
        path.unlink()


def _confirmedWsUrl(c) -> str:
    gen = c.post(f"{PREFIX}/pairing/generate",
                 json={"device_name": "probe", "device_type": "mobile"}).json()
    conf = c.post(f"{PREFIX}/pairing/confirm",
                  json={"code": gen["code"], "device_name": "probe", "device_id": "dev-1"})
    assert conf.status_code == 200, conf.text
    return conf.json()["ws_url"]


class TestAuthGate:
    def test_non_admin_is_forbidden(self, api):
        api["current"]["identity"] = PLAIN_USER
        c = api["client"]
        assert c.get(f"{PREFIX}/pairing/connection-config").status_code == 403
        assert c.put(f"{PREFIX}/pairing/connection-config",
                     json={"mode": "direct"}).status_code == 403
        assert c.post(f"{PREFIX}/pairing/connection-config/preflight",
                      json={"url": "http://127.0.0.1:9"}).status_code == 403

    def test_admin_reads_default_view(self, api):
        c = api["client"]
        res = c.get(f"{PREFIX}/pairing/connection-config")
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["mode"] == "auto"
        assert body["has_relay_enrollment_token"] is False


class TestPutValidation:
    def test_unknown_mode_422(self, api):
        c = api["client"]
        res = c.put(f"{PREFIX}/pairing/connection-config", json={"mode": "cloudflare"})
        assert res.status_code == 422, res.text

    def test_custom_mode_requires_url_422(self, api):
        c = api["client"]
        res = c.put(f"{PREFIX}/pairing/connection-config",
                    json={"mode": "custom", "custom_advertised_url": ""})
        assert res.status_code == 422, res.text

    def test_relay_mode_requires_token_422(self, api):
        c = api["client"]
        res = c.put(f"{PREFIX}/pairing/connection-config",
                    json={"mode": "relay", "relay_url": "wss://my-relay.example.com",
                          "relay_enrollment_token": ""})
        assert res.status_code == 422, res.text


class TestAddressFollowsTheChoice:
    def test_custom_mode_hands_out_that_address(self, api):
        c = api["client"]
        res = c.put(f"{PREFIX}/pairing/connection-config",
                    json={"mode": "custom",
                          "custom_advertised_url": "https://pair.example.com"})
        assert res.status_code == 200, res.text
        wsUrl = _confirmedWsUrl(c)
        parts = urlsplit(wsUrl)
        assert parts.scheme == "wss" and parts.netloc == "pair.example.com", wsUrl

    def test_direct_mode_forces_inbound_even_with_env_advertised(self, api):
        c = api["client"]
        res = c.put(f"{PREFIX}/pairing/connection-config", json={"mode": "direct"})
        assert res.status_code == 200, res.text
        wsUrl = _confirmedWsUrl(c)
        parts = urlsplit(wsUrl)
        # 入站地址 = 测试基址 testserver；env 里那条广播地址必须被绕开
        assert parts.netloc == "testserver" and parts.scheme == "ws", wsUrl

    def test_relay_mode_blocks_generate_until_registered(self, api):
        c = api["client"]
        res = c.put(f"{PREFIX}/pairing/connection-config",
                    json={"mode": "relay", "relay_url": "wss://relay.invalid",
                          "relay_enrollment_token": "tok-123456"})
        assert res.status_code == 200, res.text
        # 中继没真的注册上（via_relay 不可达）⇒ 发码被诚实拦下
        gen = c.post(f"{PREFIX}/pairing/generate",
                     json={"device_name": "probe", "device_type": "mobile"})
        assert gen.status_code == 503, gen.text
        assert gen.json()["detail"]["code"] == "tunnel_not_ready"


class TestAgentRebuild:
    def test_put_relay_rebuilds_agent_with_new_settings(self, api):
        from neurova.tunnel.agent import getTunnelAgent

        c = api["client"]
        res = c.put(f"{PREFIX}/pairing/connection-config",
                    json={"mode": "relay", "relay_url": "wss://relay.invalid",
                          "relay_enrollment_token": "tok-123456"})
        assert res.status_code == 200, res.text
        status = getTunnelAgent().tunnelStatus()
        assert status["configured"] is True

    def test_put_direct_disables_the_agent(self, api):
        from neurova.tunnel.agent import getTunnelAgent

        c = api["client"]
        res = c.put(f"{PREFIX}/pairing/connection-config",
                    json={"mode": "relay", "relay_url": "wss://relay.invalid",
                          "relay_enrollment_token": "tok-123456"})
        assert res.status_code == 200, res.text
        res = c.put(f"{PREFIX}/pairing/connection-config", json={"mode": "direct"})
        assert res.status_code == 200, res.text
        assert getTunnelAgent().tunnelStatus()["configured"] is False


class TestSecretHygiene:
    def test_token_full_text_never_leaves_the_read_side(self, api):
        c = api["client"]
        token = "super-secret-enrollment-token-987654"
        res = c.put(f"{PREFIX}/pairing/connection-config",
                    json={"mode": "relay", "relay_url": "wss://relay.invalid",
                          "relay_enrollment_token": token})
        assert res.status_code == 200, res.text
        read = c.get(f"{PREFIX}/pairing/connection-config")
        assert token not in read.text
        view = read.json()
        assert view["has_relay_enrollment_token"] is True
        assert view["relay_enrollment_token_masked"].endswith("7654")


class TestPreflight:
    def test_unreachable_url_reports_failure_honestly(self, api):
        c = api["client"]
        res = c.post(f"{PREFIX}/pairing/connection-config/preflight",
                     json={"url": "http://127.0.0.1:9"})
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["ok"] is False
        assert body["error"], "连不上必须带原因"

    def test_reachable_url_reports_ok_with_latency(self, api):
        server = ThreadingHTTPServer(("127.0.0.1", 0), _HealthHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            c = api["client"]
            res = c.post(f"{PREFIX}/pairing/connection-config/preflight",
                         json={"url": f"http://127.0.0.1:{server.server_port}"})
            assert res.status_code == 200, res.text
            body = res.json()
            assert body["ok"] is True, body
            assert body["status_code"] == 200
            assert isinstance(body["latency_ms"], (int, float))
        finally:
            server.shutdown()
            server.server_close()

    def test_empty_url_probes_the_inbound_origin(self, api):
        """auto/direct 模式（不填 url）＝ 探入站来源——管理端到达后端的那个地址，
        也是同网段手机直连会用到的地址。预检按钮因此**任何模式都可点**。

        TestClient 的 base_url（testserver）不是真实可解析主机 ⇒ 探测走诚实失败
        路径；"可达"那一半由上面显式 url 的用例（本地 http.server）覆盖。
        """
        c = api["client"]
        res = c.post(f"{PREFIX}/pairing/connection-config/preflight", json={})
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["url"] == "http://testserver", body
        assert body["ok"] is False
        assert body["error"], "连不上必须带原因"


class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 - http.server 的命名
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"status":"ok"}')

    def log_message(self, *args):  # 静默测试输出
        return
