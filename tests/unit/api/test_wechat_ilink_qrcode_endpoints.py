"""F-2/F-3 后端红绿测试：iLink 扫码非阻塞端点 + save/test needs_scan 契约。

契约：
- POST /channel-configs/wechat/ilink/qrcode：无 token → 生成二维码（只生成不等待，
  断言零轮询 GET）；已有有效 token → {"status": "ready"}；生成失败 → 诚实 5xx。
- GET /channel-configs/wechat/ilink/qrcode/status?qr_id=：单次轮询三态如实返回；
  confirmed → token 落盘。
- POST /channel-configs（save）：wechat iLink 无 token → success=True + needs_scan=True，
  且绝不创建适配器（避免 300s 阻塞轮询）；有 token → 行为不变（needs_scan=False）。
- POST /channel-configs/{type}/test：wechat 无 token → 诚实失败 {success: False,
  needs_scan: True}，绝不假成功；有 token → authenticate 真正执行（F-2）。

纪律：所有测试隔离 CONFIG_FILE 与 HOME/USERPROFILE，绝不触碰真实
data/channel_configs.json 与 ~/.Neurova/weixin_bot_token。
"""
from __future__ import annotations

import asyncio
import unittest.mock
from unittest.mock import AsyncMock, MagicMock

import pytest

import neurova.api.endpoints.channel_config as cc
from neurova.api.endpoints.channel_config import (
    ChannelConfigRequest,
    WechatIlinkQrcodeRequest,
    create_or_update_config,
    create_wechat_ilink_qrcode,
    get_wechat_ilink_qrcode_status,
)


@pytest.fixture()
def isolated_env(tmp_path, monkeypatch):
    """隔离：配置文件 → tmp；HOME/USERPROFILE → tmp（防误写真实 token）。"""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setattr(cc, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(cc, "CONFIG_FILE", tmp_path / "channel_configs.json")
    return tmp_path


def _save_wechat_config(extra: dict):
    """直接落一份 wechat 已保存配置（绕过端点，聚焦被测端点）。"""
    cc._save_configs({"wechat": {"channel_type": "wechat", "enabled": True, "extra": extra}})


def _fake_response(payload: dict) -> MagicMock:
    resp = MagicMock()
    resp.json.return_value = payload
    return resp


class TestQrcodeEndpoint:
    def test_pending_without_token(self, isolated_env, monkeypatch):
        _save_wechat_config({"mode": "ilink", "bot_token": "", "token_file": ""})

        adapter = MagicMock()
        adapter._request_ilink_qrcode.return_value = {
            "qr_url": "https://qr.example/x",
            "qr_id": "qr-1",
        }
        poll_get = MagicMock()  # 生成段绝不允许轮询
        monkeypatch.setattr(cc, "create_wechat_adapter", MagicMock(return_value=adapter))
        monkeypatch.setattr(
            "neurova.channels.wechat_auth.requests.get", poll_get
        )

        result = asyncio.run(create_wechat_ilink_qrcode(WechatIlinkQrcodeRequest()))

        assert result["status"] == "pending"
        assert result["qr_url"] == "https://qr.example/x"
        assert result["qr_id"] == "qr-1"
        adapter._request_ilink_qrcode.assert_called_once()
        poll_get.assert_not_called()  # 红线：端点不进入 300s 等待

    def test_ready_when_saved_token_file_has_content(self, isolated_env):
        token_file = isolated_env / "weixin_bot_token"
        token_file.write_text("tok-1", encoding="utf-8")
        _save_wechat_config({"mode": "ilink", "token_file": str(token_file)})

        result = asyncio.run(create_wechat_ilink_qrcode(WechatIlinkQrcodeRequest()))

        assert result == {"status": "ready"}

    def test_ready_when_saved_bot_token_present(self, isolated_env):
        _save_wechat_config({"mode": "ilink", "bot_token": "tok-2"})

        result = asyncio.run(create_wechat_ilink_qrcode(WechatIlinkQrcodeRequest()))

        assert result == {"status": "ready"}

    def test_honest_failure_on_generate_error(self, isolated_env, monkeypatch):
        adapter = MagicMock()
        adapter._request_ilink_qrcode.return_value = None
        monkeypatch.setattr(cc, "create_wechat_adapter", MagicMock(return_value=adapter))

        with pytest.raises(Exception) as exc_info:
            asyncio.run(create_wechat_ilink_qrcode(WechatIlinkQrcodeRequest()))
        assert getattr(exc_info.value, "status_code", None) in (400, 502)

    def test_uses_saved_token_file_when_body_empty(self, isolated_env, monkeypatch):
        token_file = isolated_env / "saved_token"
        _save_wechat_config({"mode": "ilink", "token_file": str(token_file)})

        factory = MagicMock()
        monkeypatch.setattr(cc, "create_wechat_adapter", factory)

        asyncio.run(create_wechat_ilink_qrcode(WechatIlinkQrcodeRequest()))
        assert factory.call_args.kwargs.get("mode") == "ilink"
        adapter = factory.return_value
        assert adapter.ilink_token_file == str(token_file)


class TestStatusEndpoint:
    def test_single_poll_pending(self, isolated_env, monkeypatch):
        adapter = MagicMock()
        adapter._poll_scan_once.return_value = {"status": "pending"}
        monkeypatch.setattr(cc, "create_wechat_adapter", MagicMock(return_value=adapter))

        result = asyncio.run(get_wechat_ilink_qrcode_status(qr_id="qr-1"))

        assert result["status"] == "pending"
        adapter._poll_scan_once.assert_called_once_with("qr-1")  # 单次，无循环

    @pytest.mark.parametrize("api_status", ["scanned", "expired"])
    def test_states_returned_verbatim(self, isolated_env, monkeypatch, api_status):
        adapter = MagicMock()
        adapter._poll_scan_once.return_value = {"status": api_status}
        monkeypatch.setattr(cc, "create_wechat_adapter", MagicMock(return_value=adapter))

        result = asyncio.run(get_wechat_ilink_qrcode_status(qr_id="qr-1"))
        assert result["status"] == api_status

    def test_confirmed_saves_token_file(self, isolated_env, monkeypatch):
        """confirmed：真实落盘（走真实 _save_ilink_token，路径来自已保存配置）。"""
        token_file = isolated_env / "weixin_bot_token"
        _save_wechat_config({"mode": "ilink", "token_file": str(token_file)})

        real_adapter = cc.create_wechat_adapter(mode="ilink")
        real_adapter.ilink_token_file = str(token_file)
        get = MagicMock(return_value=_fake_response(
            {"status": "confirmed", "bot_token": "live-token"}
        ))
        monkeypatch.setattr("neurova.channels.wechat_auth.requests.get", get)
        monkeypatch.setattr(
            cc, "create_wechat_adapter", MagicMock(return_value=real_adapter)
        )

        result = asyncio.run(get_wechat_ilink_qrcode_status(qr_id="qr-2"))

        assert result["status"] == "confirmed"
        assert token_file.read_text(encoding="utf-8") == "live-token"

    def test_error_is_honest_http_error(self, isolated_env, monkeypatch):
        adapter = MagicMock()
        adapter._poll_scan_once.return_value = {"status": "error", "message": "boom"}
        monkeypatch.setattr(cc, "create_wechat_adapter", MagicMock(return_value=adapter))

        with pytest.raises(Exception) as exc_info:
            asyncio.run(get_wechat_ilink_qrcode_status(qr_id="qr-1"))
        assert getattr(exc_info.value, "status_code", None) == 502

    def test_missing_qr_id_rejected(self, isolated_env):
        with pytest.raises(Exception) as exc_info:
            asyncio.run(get_wechat_ilink_qrcode_status(qr_id=""))
        assert getattr(exc_info.value, "status_code", None) == 400


class TestSaveNeedsScan:
    def test_save_wechat_without_token_returns_needs_scan_and_skips_adapter(
        self, isolated_env, monkeypatch
    ):
        _create_adapter_spy = MagicMock(side_effect=AssertionError("不得创建适配器"))
        monkeypatch.setattr(cc, "_create_adapter", _create_adapter_spy)

        request = ChannelConfigRequest(
            channel_type="wechat",
            enabled=True,
            extra={"mode": "ilink", "bot_token": "", "token_file": ""},
        )
        result = asyncio.run(create_or_update_config(request))

        assert result["success"] is True
        assert result["needs_scan"] is True
        _create_adapter_spy.assert_not_called()

    def test_save_wechat_with_token_registers_adapter(self, isolated_env, monkeypatch):
        token_file = isolated_env / "weixin_bot_token"
        token_file.write_text("tok-3", encoding="utf-8")

        adapter = MagicMock()
        adapter.is_connected = False
        adapter.disconnect = AsyncMock()
        monkeypatch.setattr(cc, "_create_adapter", MagicMock(return_value=adapter))
        manager = MagicMock()
        monkeypatch.setattr(cc, "get_channel_manager", MagicMock(return_value=manager))

        request = ChannelConfigRequest(
            channel_type="wechat",
            enabled=True,
            extra={"mode": "ilink", "token_file": str(token_file)},
        )
        result = asyncio.run(create_or_update_config(request))

        assert result["success"] is True
        assert result["needs_scan"] is False
        manager.register_adapter.assert_called_once_with(adapter, agent_id="default")

    def test_save_non_wechat_channel_unchanged(self, isolated_env, monkeypatch):
        """向后兼容：其他渠道绝不带 needs_scan 阻断，适配器照常创建。"""
        adapter = MagicMock()
        monkeypatch.setattr(cc, "_create_adapter", MagicMock(return_value=adapter))
        manager = MagicMock()
        monkeypatch.setattr(cc, "get_channel_manager", MagicMock(return_value=manager))

        request = ChannelConfigRequest(
            channel_type="telegram",
            enabled=True,
            extra={"bot_token": "tg-token"},
        )
        result = asyncio.run(create_or_update_config(request))

        assert result["success"] is True
        assert result.get("needs_scan", False) is False
        manager.register_adapter.assert_called_once()


class TestWechatTestConnection:
    def test_without_token_honest_false_no_adapter(self, isolated_env, monkeypatch):
        """F-2 核心：无 token 测试连接 → 诚实失败 + 引导扫码，绝不假成功/阻塞。"""
        _create_adapter_spy = MagicMock(side_effect=AssertionError("不得创建适配器"))
        monkeypatch.setattr(cc, "_create_adapter", _create_adapter_spy)

        request = ChannelConfigRequest(
            channel_type="wechat",
            extra={"mode": "ilink", "bot_token": ""},
        )
        result = asyncio.run(cc.test_connection("wechat", request))

        assert result.success is False
        assert result.needs_scan is True
        _create_adapter_spy.assert_not_called()

    def test_with_token_authenticate_really_runs(self, isolated_env, monkeypatch):
        """有 token 测试连接 → 真实协议适配器 connect 的 getconfig 校验执行并通过。

        2026-09-13 ilink 端到端移植：test_connection 对 ilink 走
        wechat_ilink.WechatILinkAdapter（真实协议），凭据校验由虚构 /auth/verify
        换为有界 getconfig（ilinkai.weixin.qq.com）。
        """
        token_file = isolated_env / "weixin_bot_token"
        token_file.write_text("tok-4", encoding="utf-8")

        getconfig = AsyncMock(return_value={"ret": 0})
        monkeypatch.setattr(
            "neurova.channels.wechat_ilink_client.ILinkClient.getconfig", getconfig)
        monkeypatch.setattr(
            "neurova.channels.wechat_ilink_client.ILinkClient.start", AsyncMock())
        monkeypatch.setattr(
            "neurova.channels.wechat_ilink_client.ILinkClient.stop", AsyncMock())
        # 轮询挂起不真发网络（connect 成功后 test_connection 会 disconnect 取消）
        monkeypatch.setattr(
            "neurova.channels.wechat_ilink_client.ILinkClient.getupdates",
            AsyncMock(side_effect=asyncio.CancelledError))

        request = ChannelConfigRequest(
            channel_type="wechat",
            extra={"mode": "ilink", "token_file": str(token_file)},
        )
        result = asyncio.run(cc.test_connection("wechat", request))

        assert result.success is True
        getconfig.assert_awaited_once()  # 真实凭据校验发生

    def test_with_invalid_token_honest_false(self, isolated_env, monkeypatch):
        """token 无效（getconfig 校验失败）→ 诚实失败，绝不假阳性。"""
        token_file = isolated_env / "weixin_bot_token"
        token_file.write_text("bad-token", encoding="utf-8")

        getconfig = AsyncMock(side_effect=RuntimeError("401 unauthorized"))
        monkeypatch.setattr(
            "neurova.channels.wechat_ilink_client.ILinkClient.getconfig", getconfig)
        monkeypatch.setattr(
            "neurova.channels.wechat_ilink_client.ILinkClient.start", AsyncMock())
        monkeypatch.setattr(
            "neurova.channels.wechat_ilink_client.ILinkClient.stop", AsyncMock())

        request = ChannelConfigRequest(
            channel_type="wechat",
            extra={"mode": "ilink", "token_file": str(token_file)},
        )
        result = asyncio.run(cc.test_connection("wechat", request))

        assert result.success is False
        assert result.needs_scan is False
