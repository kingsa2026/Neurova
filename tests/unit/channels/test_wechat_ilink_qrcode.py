"""F-2/F-3 后端红绿测试：iLink 扫码两段式非阻塞拆分（wechat_auth 层）。

契约：
- `_request_ilink_qrcode()` 只生成二维码（一次 POST），绝不轮询（零次 GET）；
- `_poll_scan_once(qr_id)` 单次查询扫码状态，返回原始 status 语义
  （pending/scanned/confirmed/expired），网络异常诚实返回 error；
- 台账②：`_authenticate_ilink` 无凭证只生成二维码即返回 False——
  `_wait_for_scan`/`_generate_qr_code` 300s 同步轮询已根除且不得复活。
"""
from __future__ import annotations

import inspect
import json
import time
import types
from unittest.mock import MagicMock

import pytest

import neurova.channels.wechat_auth as wa
from neurova.channels.wechat import WeChatAdapter
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


class TestAuthenticateIlinkNonBlocking:
    """台账②：创建/启动路径无凭证→只生成二维码（单次 POST）即诚实返回 False。

    修复前 `_authenticate_ilink` 走 `_generate_qr_code → _wait_for_scan`
    （requests.get + time.sleep(3) 循环，最长 300s），服务启动/程序化
    create_wechat_adapter 会阻塞调用线程 5 分钟。
    """

    def test_no_credentials_returns_false_without_polling(self, monkeypatch, tmp_path, caplog):
        # 硬纪律：触碰 token 路径的测试必须 HOME/USERPROFILE → tmp + 显式 tmp token_file 双保险
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("USERPROFILE", str(tmp_path))

        post = MagicMock(return_value=_fake_response(
            {"success": True, "qr_code_url": "https://qr.example/x", "qr_id": "qr-1"}
        ))
        get = MagicMock()
        sleep_forbidden = MagicMock(side_effect=AssertionError("禁止同步 sleep 轮询（台账②防复活）"))
        monkeypatch.setattr(wa.requests, "post", post)
        monkeypatch.setattr(wa.requests, "get", get)
        monkeypatch.setattr(wa.time, "sleep", sleep_forbidden)

        token_file = tmp_path / "weixin_bot_token"
        adapter = WeChatAdapter()
        t0 = time.monotonic()
        with caplog.at_level("WARNING"):
            ok = adapter.authenticate({"mode": "ilink", "bot_token": "", "token_file": str(token_file)})
        elapsed = time.monotonic() - t0

        assert ok is False, "无凭证必须诚实未认证（与① connect False 语义闭环）"
        assert adapter._ilink_initialized is False
        assert elapsed < 1.0, f"authenticate 耗时 {elapsed:.2f}s，疑似进入同步轮询等待"
        post.assert_called_once()  # 只生成二维码（单次 POST）
        get.assert_not_called()  # 红线：零轮询
        sleep_forbidden.assert_not_called()  # 红线：零 sleep
        assert any("/wechat/ilink/qrcode" in r.getMessage() for r in caplog.records), (
            "必须 warning 指引经扫码端点/渠道页完成登录"
        )
        assert not token_file.exists(), "未登录不得写 token 文件"

    def test_qrcode_generation_failure_still_returns_false_fast(self, monkeypatch, tmp_path):
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        post = MagicMock(return_value=_fake_response({"success": False}))
        get = MagicMock()
        monkeypatch.setattr(wa.requests, "post", post)
        monkeypatch.setattr(wa.requests, "get", get)

        adapter = WeChatAdapter()
        ok = adapter.authenticate(
            {"mode": "ilink", "bot_token": "", "token_file": str(tmp_path / "t")}
        )
        assert ok is False
        post.assert_called_once()
        get.assert_not_called()

    def test_existing_token_path_untouched_by_nonblocking_change(self, monkeypatch, tmp_path):
        """有 bot_token → 真实 verify 链路不变（不得误伤已认证路径）。"""
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        get = MagicMock(return_value=_fake_response({"valid": True}))
        post = MagicMock()
        monkeypatch.setattr(wa.requests, "get", get)
        monkeypatch.setattr(wa.requests, "post", post)

        adapter = WeChatAdapter()
        assert adapter.authenticate({"mode": "ilink", "bot_token": "tok-x",
                                     "token_file": str(tmp_path / "t")}) is True
        assert adapter._ilink_initialized is True
        get.assert_called_once()
        post.assert_not_called()


class TestBlockingWaitRootRemoved:
    """台账②根除断言：300s 同步轮询实现不得复活。"""

    def test_wait_for_scan_and_generate_qr_code_removed(self):
        assert not hasattr(WeChatAuthMixin, "_wait_for_scan"), (
            "_wait_for_scan（300s 同步轮询）已根除，不得复活"
        )
        assert not hasattr(WeChatAuthMixin, "_generate_qr_code"), (
            "_generate_qr_code（等待扫码旧 wrapper）已根除，不得复活"
        )

    def test_module_source_free_of_sync_scan_wait(self):
        src = inspect.getsource(wa)
        assert "_wait_for_scan" not in src and "_generate_qr_code" not in src
        assert "扫码登录超时" not in src, "同步轮询等待体不得以任何形式回归 wechat_auth"
