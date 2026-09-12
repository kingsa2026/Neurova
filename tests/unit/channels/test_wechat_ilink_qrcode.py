"""F-2/F-3 后端红绿测试：iLink 扫码两段式非阻塞拆分（wechat_auth 层）。

契约：
- `_request_ilink_qrcode()` 只生成二维码（一次 POST），绝不轮询（零次 GET）；
- `_poll_scan_once(qr_id)` 单次查询扫码状态，返回原始 status 语义
  （pending/scanned/confirmed/expired），网络异常诚实返回 error；
- `_wait_for_scan()` 复用 `_poll_scan_once`，行为兼容（confirmed 落盘 token）。
"""
from __future__ import annotations

import json
import types
from unittest.mock import MagicMock

import pytest

import neurova.channels.wechat_auth as wa
from neurova.channels.wechat_auth import WeChatAuthMixin


def _make_adapter(token_file: str = ""):
    """最小 iLink 适配器替身（不触碰真实网络/文件默认路径）。"""
    return types.SimpleNamespace(
        ILINK_API_BASE="https://ilink.example",
        ilink_bot_token="",
        ilink_token_file=token_file,
        _ilink_initialized=False,
    )


def _fake_response(payload: dict) -> MagicMock:
    resp = MagicMock()
    resp.json.return_value = payload
    return resp


class TestRequestIlinkQrcode:
    """生成段：一次 POST，绝不进入轮询。"""

    def test_success_returns_qr_fields(self, monkeypatch):
        post = MagicMock(return_value=_fake_response(
            {"success": True, "qr_code_url": "https://qr.example/x", "qr_id": "qr-1"}
        ))
        get = MagicMock()
        monkeypatch.setattr(wa.requests, "post", post)
        monkeypatch.setattr(wa.requests, "get", get)

        adapter = _make_adapter()
        mixin = WeChatAuthMixin(adapter)
        result = mixin._request_ilink_qrcode()

        assert result == {"qr_url": "https://qr.example/x", "qr_id": "qr-1"}
        post.assert_called_once()
        # 红线：生成段绝不轮询
        get.assert_not_called()

    def test_api_failure_returns_none(self, monkeypatch):
        post = MagicMock(return_value=_fake_response({"success": False, "msg": "boom"}))
        monkeypatch.setattr(wa.requests, "post", post)

        mixin = WeChatAuthMixin(_make_adapter())
        assert mixin._request_ilink_qrcode() is None

    def test_network_error_returns_none(self, monkeypatch):
        post = MagicMock(side_effect=wa.requests.RequestException("conn refused"))
        monkeypatch.setattr(wa.requests, "post", post)

        mixin = WeChatAuthMixin(_make_adapter())
        assert mixin._request_ilink_qrcode() is None


class TestPollScanOnce:
    """轮询段：单次 GET，三态 + error 如实返回。"""

    @pytest.mark.parametrize("api_status", ["pending", "scanned", "expired", "confirmed"])
    def test_single_poll_returns_status(self, monkeypatch, api_status):
        payload = {"status": api_status}
        if api_status == "confirmed":
            payload["bot_token"] = "tok-123"
        get = MagicMock(return_value=_fake_response(payload))
        monkeypatch.setattr(wa.requests, "get", get)

        mixin = WeChatAuthMixin(_make_adapter())
        result = mixin._poll_scan_once("qr-1")

        assert result["status"] == api_status
        if api_status == "confirmed":
            assert result["bot_token"] == "tok-123"
        get.assert_called_once()  # 单次轮询，无循环
        _, kwargs = get.call_args
        assert kwargs.get("timeout") == 10

    def test_network_error_returns_error_status(self, monkeypatch):
        get = MagicMock(side_effect=wa.requests.RequestException("timeout"))
        monkeypatch.setattr(wa.requests, "get", get)

        mixin = WeChatAuthMixin(_make_adapter())
        result = mixin._poll_scan_once("qr-1")

        assert result["status"] == "error"
        assert "message" in result


class TestGenerateQrCodeSplit:
    """拆分后 `_generate_qr_code` = 生成 + 等待，行为兼容；等待复用单次轮询。"""

    def test_generate_still_waits_for_scan(self, monkeypatch):
        """同步 connect 流程的旧契约保持：生成成功后进入等待，confirmed 即成功。"""
        post = MagicMock(return_value=_fake_response(
            {"success": True, "qr_code_url": "u", "qr_id": "qr-9"}
        ))
        get = MagicMock(return_value=_fake_response({"status": "confirmed", "bot_token": "t"}))
        monkeypatch.setattr(wa.requests, "post", post)
        monkeypatch.setattr(wa.requests, "get", get)
        monkeypatch.setattr(wa.time, "sleep", lambda s: None)

        token_file = "/tmp/f3-test/weixin_bot_token"
        adapter = _make_adapter(token_file=token_file)
        mixin = WeChatAuthMixin(adapter)
        assert mixin._generate_qr_code() is True
        assert adapter.ilink_bot_token == "t"
        assert adapter._ilink_initialized is True


class TestWaitForScanTokenPersistence:
    """confirmed 落盘：token 写入 token_file（路径显式指定，隔离 ~ 默认路径）。"""

    def test_confirmed_saves_token_to_file(self, monkeypatch, tmp_path):
        # 硬纪律：触碰 ~ 默认路径的测试必须先隔离 HOME/USERPROFILE
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("USERPROFILE", str(tmp_path))

        token_file = tmp_path / "weixin_bot_token"
        get = MagicMock(return_value=_fake_response(
            {"status": "confirmed", "bot_token": "live-token"}
        ))
        monkeypatch.setattr(wa.requests, "get", get)
        monkeypatch.setattr(wa.time, "sleep", lambda s: None)

        adapter = _make_adapter(token_file=str(token_file))
        mixin = WeChatAuthMixin(adapter)
        assert mixin._wait_for_scan("qr-2", timeout=5) is True
        assert token_file.read_text(encoding="utf-8") == "live-token"
