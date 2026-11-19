"""连接方式配置（档一）的模块级契约。

`neurova/tunnel/connection_config.py` 是「手机从哪条路回连」的**唯一**配置源：
模式（auto/direct/custom/relay）+ 自定义对外地址 + 自建中继地址与准入令牌，
落盘在数据根的 `tunnel/connection_config.json`。本文件钉：

- 优先级：显式选择（custom/direct/relay）压过环境变量；auto 保持既有行为
  （env 的 advertised/relay 照旧生效）——存量部署不被这次改动悄悄换道。
- 凭据卫生：准入令牌只回**掩码视图**，全文不出读口。
- 校验：模式枚举、custom 必填合法 http(s) 地址、relay 必填地址+令牌，fail-fast。
- agent 重建：配置变更后能按生效值造出新的出站 agent（direct 下不配中继）。
"""
import json

import pytest

from neurova.tunnel import connection_config as CC


@pytest.fixture(autouse=True)
def _cleanConfigFile(monkeypatch):
    """每测清盘：配置文件删掉，env 三键设成可辨识的基线值。"""
    path = CC.configFilePath()
    if path.exists():
        path.unlink()
    monkeypatch.setenv("NEUROVA_ADVERTISED_BASE_URL", "https://env-advertised.example.com")
    monkeypatch.setenv("NEUROVA_TUNNEL_RELAY_URL", "wss://env-relay.example.com")
    monkeypatch.setenv("NEUROVA_TUNNEL_ENROLLMENT_TOKEN", "env-token-abcdef")
    yield
    if path.exists():
        path.unlink()


class TestDefaults:
    def test_default_mode_is_auto_and_env_still_works(self):
        view = CC.getConnectionConfig()
        assert view["mode"] == "auto"
        # auto = 存量行为：env 广播地址照旧生效
        assert CC.effectiveAdvertisedBaseUrl() == "https://env-advertised.example.com"
        relayUrl, token, configured = CC.effectiveRelaySettings()
        assert (relayUrl, token, configured) == (
            "wss://env-relay.example.com", "env-token-abcdef", True)

    def test_persisted_file_round_trip(self):
        CC.setConnectionConfig(mode="custom",
                               customAdvertisedUrl="https://pair.example.com")
        raw = json.loads(CC.configFilePath().read_text(encoding="utf-8"))
        assert raw["mode"] == "custom"
        assert raw["custom_advertised_url"] == "https://pair.example.com"
        view = CC.getConnectionConfig()
        assert view["mode"] == "custom"


class TestPrecedence:
    def test_custom_url_wins_over_env(self):
        CC.setConnectionConfig(mode="custom",
                               customAdvertisedUrl="https://pair.example.com")
        assert CC.effectiveAdvertisedBaseUrl() == "https://pair.example.com"

    def test_direct_forces_inbound_even_with_env_set(self):
        CC.setConnectionConfig(mode="direct")
        assert CC.effectiveAdvertisedBaseUrl() == ""

    def test_relay_mode_uses_persisted_relay_not_env(self):
        CC.setConnectionConfig(mode="relay",
                               relayUrl="wss://my-relay.example.com",
                               relayEnrollmentToken="my-token-123456")
        relayUrl, token, configured = CC.effectiveRelaySettings()
        assert (relayUrl, token, configured) == ("wss://my-relay.example.com",
                                                 "my-token-123456", True)
        # relay 模式的对外地址来自隧道路由，不再广播 env 地址
        assert CC.effectiveAdvertisedBaseUrl() == ""


class TestSecretHygiene:
    def test_token_never_returned_in_full(self):
        CC.setConnectionConfig(mode="relay",
                               relayUrl="wss://my-relay.example.com",
                               relayEnrollmentToken="super-secret-token-987654")
        view = CC.getConnectionConfig()
        assert "super-secret-token-987654" not in json.dumps(view)
        assert view["has_relay_enrollment_token"] is True
        assert view["relay_enrollment_token_masked"].endswith("7654")
        # 掩码视图不该等于全文
        assert view["relay_enrollment_token_masked"] != "super-secret-token-987654"

    def test_empty_token_reports_absent(self):
        view = CC.getConnectionConfig()
        assert view["has_relay_enrollment_token"] is False
        assert view["relay_enrollment_token_masked"] == ""


class TestValidation:
    def test_unknown_mode_rejected(self):
        with pytest.raises(ValueError, match="mode"):
            CC.setConnectionConfig(mode="cloudflare")

    def test_custom_mode_requires_url(self):
        with pytest.raises(ValueError, match="custom_advertised_url"):
            CC.setConnectionConfig(mode="custom", customAdvertisedUrl="")

    def test_custom_mode_rejects_non_http_scheme(self):
        with pytest.raises(ValueError, match="http"):
            CC.setConnectionConfig(mode="custom", customAdvertisedUrl="ftp://pair.example.com")

    def test_relay_mode_requires_url_and_token(self):
        with pytest.raises(ValueError, match="relay_url"):
            CC.setConnectionConfig(mode="relay", relayUrl="")
        with pytest.raises(ValueError, match="token"):
            CC.setConnectionConfig(mode="relay", relayUrl="wss://my-relay.example.com",
                                   relayEnrollmentToken="")


class TestAgentRebuild:
    def test_agent_built_from_direct_mode_has_no_relay(self):
        CC.setConnectionConfig(mode="direct")
        agent = CC.buildAgentFromSettings()
        status = agent.tunnelStatus()
        assert status["configured"] is False

    def test_agent_built_from_relay_mode_carries_persisted_settings(self):
        CC.setConnectionConfig(mode="relay",
                               relayUrl="wss://my-relay.example.com",
                               relayEnrollmentToken="my-token-123456")
        agent = CC.buildAgentFromSettings()
        status = agent.tunnelStatus()
        assert status["configured"] is True
        assert agent.relayUrl == "wss://my-relay.example.com"
        assert agent.enrollmentToken == "my-token-123456"

    def test_stable_instance_id_matches_env_builder(self):
        """同一数据根下，两条构建路径必须拿到同一个 instanceId——
        否则重注册换 routeId，已配对设备就得重扫（agent.py 的头号不变量）。"""
        from neurova.tunnel.agent import buildAgentFromEnv

        CC.setConnectionConfig(mode="relay",
                               relayUrl="wss://my-relay.example.com",
                               relayEnrollmentToken="my-token-123456")
        viaConfig = CC.buildAgentFromSettings()
        viaEnv = buildAgentFromEnv()
        assert viaConfig.instanceId == viaEnv.instanceId
        assert viaConfig.instanceId.startswith("nv-")
