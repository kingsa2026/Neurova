"""资源台账 2026-09-12 ① 防回归：wechat connect() 假成功根修。

背景：`wechat.py` connect() 曾无条件 `return True`——无论认证是否成功都"已连接"，
channel manager 启动/发送/重启链路因此永不感知 iLink/wecom/official 的认证失败。

契约：
- 按当前 mode 检查对应初始化标志（_wecom_initialized/_ilink_initialized/
  _official_initialized）；未认证 → False + logger.warning 指明需先完成认证/扫码；
- 认证成功 → True 且置 `_connected`（与基类 is_connected 语义一致）；
- disconnect 复位 `_connected`（connect True 后 stop/restart 不得留脏连接态）；
- manager 启动链路把 False 当"被正常处理的未连接状态"：_connect_adapter 告警不抛、
  start() 走完、list_adapters connected=False、send_message 诚实 None。

纪律：fake requests（零真实网络）；HOME/USERPROFILE → tmp（token 文件事故硬隔离）。
"""

import asyncio

import pytest

import neurova.channels.wechat_auth as wa
from neurova.channels.manager import ChannelManager
from neurova.channels.wechat import WeChatAdapter


def _fake_resp(payload: dict):
    class _R:
        def json(self):
            return payload

    return _R()


class TestConnectHonest:
    """①：connect() 诚实反映当前 mode 的真实认证状态"""

    @pytest.mark.parametrize("mode", ["wecom", "ilink", "official"])
    def test_unauthenticated_false_for_every_mode(self, mode, caplog):
        adapter = WeChatAdapter()
        adapter.mode = mode
        with caplog.at_level("WARNING"):
            assert asyncio.run(adapter.connect()) is False, (
                f"{mode} 未认证成功时 connect() 不得假成功返回 True"
            )
        assert adapter._connected is False
        assert adapter.is_connected is False
        assert any("未连接" in r.getMessage() for r in caplog.records), (
            "connect 失败必须 warning 指明该渠道需先完成认证/扫码"
        )

    def test_ilink_unauthenticated_warning_points_to_scan_flow(self, caplog):
        adapter = WeChatAdapter()
        adapter.mode = "ilink"
        with caplog.at_level("WARNING"):
            assert asyncio.run(adapter.connect()) is False
        msgs = " ".join(r.getMessage() for r in caplog.records)
        assert "扫码" in msgs and "/wechat/ilink/qrcode" in msgs, (
            "iLink 未登录的 warning 必须引导扫码端点（与②的非阻塞契约闭环）"
        )

    def test_connect_true_after_fake_wecom_authenticate(self):
        adapter = WeChatAdapter()
        adapter.mode = "wecom"
        adapter._wecom_initialized = True
        assert asyncio.run(adapter.connect()) is True
        assert adapter._connected is True
        assert adapter.is_connected is True

    def test_connect_true_after_fake_official_authenticate(self):
        adapter = WeChatAdapter()
        adapter.mode = "official"
        adapter._official_initialized = True
        assert asyncio.run(adapter.connect()) is True
        assert adapter._connected is True

    def test_connect_true_after_real_ilink_authenticate(self, monkeypatch, tmp_path):
        """fake authenticate 成功（token verify 有效）→ connect 闭环 True"""
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        monkeypatch.setattr(wa.requests, "get", lambda *a, **k: _fake_resp({"valid": True}))
        monkeypatch.setattr(wa.requests, "post", lambda *a, **k: pytest.fail("不应触达网络轮询"))

        adapter = WeChatAdapter()
        assert adapter.authenticate({"mode": "ilink", "bot_token": "tok-1"}) is True
        assert asyncio.run(adapter.connect()) is True
        assert adapter.is_connected is True

    def test_disconnect_resets_connected(self):
        """connect 成功后 disconnect 必须复位 _connected（is_connected 语义闭环）"""
        adapter = WeChatAdapter()
        adapter._wecom_initialized = True
        assert asyncio.run(adapter.connect()) is True
        asyncio.run(adapter.disconnect())
        assert adapter._connected is False
        assert adapter.is_connected is False


class TestManagerHandlesConnectFalse:
    """①配套核实：manager 启动/发送链路把 connect False 当正常未连接状态处理"""

    @pytest.fixture()
    def manager(self):
        ChannelManager._instance = None
        m = ChannelManager()
        m.ingress_queue = False  # 测试钩子：跳过入站队列（不触真实 DB）
        yield m
        ChannelManager._instance = None

    def test_connect_adapter_logs_warning_and_does_not_raise(self, manager, caplog):
        adapter = WeChatAdapter()
        with caplog.at_level("WARNING"):
            assert asyncio.run(manager._connect_adapter(adapter)) is None
        assert any("failed to connect" in r.getMessage() for r in caplog.records), (
            "manager 对 connect False 的既有语义：logger.warning 记录，不抛异常"
        )

    def test_start_skips_unauthenticated_wechat_keeps_disconnected(self, manager):
        adapter = WeChatAdapter()
        adapter.config.enabled = True
        manager.register_adapter(adapter)
        asyncio.run(manager.start())  # 不得抛
        status = manager.list_adapters()["wechat"]
        assert status["connected"] is False
        assert status["enabled"] is True
        assert asyncio.run(manager.health_check())["adapters"]["wechat"]["connected"] is False

    def test_start_connects_authenticated_wechat(self, manager):
        adapter = WeChatAdapter()
        adapter.config.enabled = True
        adapter._wecom_initialized = True
        manager.register_adapter(adapter)
        asyncio.run(manager.start())
        assert manager.list_adapters()["wechat"]["connected"] is True

    def test_send_message_honest_none_when_not_connected(self, manager):
        """未认证 wechat：send_message 尝试 connect→False→诚实 None（不假发送）"""
        adapter = WeChatAdapter()
        manager.register_adapter(adapter)
        assert asyncio.run(manager.send_message("wechat", "chat1", "hi")) is None
