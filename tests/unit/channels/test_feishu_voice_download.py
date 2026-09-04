# -*- coding: utf-8 -*-
"""P1-12 断点③修复 — feishu 语音消息下载接线（file_key → audio_bytes）防回归

复审断链：feishu 适配器 audio 消息只产出 "[语音]" 占位文本，MediaMixin.download_media
是孤儿（未继承）、且走 JSON 解析拉不了二进制；voice_precheck 依赖 metadata.audio_bytes
但没人送字节 → 语音预转写对 feishu 永不触发。

修：
1. FeishuAdapter 补继承 AuthMixin（孤儿 Mixin 复活）+ `_download_media_bytes`
   （REST 二进制下载，Bearer token，10MB 上限）；
2. _handle_message_event 对 audio 消息：解析 file_key → 下载 →
   metadata.audio_bytes 送达 voice_precheck；失败静默降级占位。
"""
import asyncio
import os
import sys
import threading
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from neurova.channels.base import ChannelConfig
from neurova.channels.feishu import FeishuAdapter


def _adapter() -> FeishuAdapter:
    return FeishuAdapter(ChannelConfig(channel_type="feishu", app_id="cli_x", app_secret="s"))


class _FakeMsg:
    message_type = "audio"
    message_id = "om_123"
    chat_id = "oc_1"
    chat_type = "p2k"
    content = '{"file_key":"fk_abc","duration_ms":1800}'


class _FakeEvent:
    def __init__(self):
        self.event = MagicMock()
        self.event.message = _FakeMsg()
        s = MagicMock()
        s.sender_id.user_id = "u9"
        self.event.sender = s


class _MainLoopThread:
    """后台线程事件循环（对齐 test_channel_event_loop_safety 的模式）"""

    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def stop(self):
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(timeout=2)


class TestDownloadMediaBytes:
    def test_download_returns_bytes(self):
        ad = _adapter()
        ad._tenant_access_token = "tok"
        ad._token_expires_at = float("inf")
        fake_resp = MagicMock()
        fake_resp.status_code = 200
        fake_resp.content = b"OPUS_AUDIO_BYTES"
        with patch("requests.get", return_value=fake_resp) as get_mock:
            data = ad._download_media_bytes("om_123", "fk_abc")
        assert data == b"OPUS_AUDIO_BYTES"
        assert "om_123/resources/fk_abc" in get_mock.call_args.args[0]
        assert get_mock.call_args.kwargs["params"]["type"] == "file"

    def test_download_failure_returns_none(self):
        ad = _adapter()
        import requests as _rq

        ad._tenant_access_token = "tok"
        ad._token_expires_at = float("inf")
        with patch("requests.get", side_effect=_rq.RequestException("down")):
            assert ad._download_media_bytes("om_123", "fk") is None

    def test_download_size_limit(self):
        """超 10MB 拒收（防御大文件拖垮内存）"""
        ad = _adapter()
        ad._tenant_access_token = "tok"
        ad._token_expires_at = float("inf")
        fake_resp = MagicMock()
        fake_resp.status_code = 200
        fake_resp.headers = {"Content-Length": str(11 * 1024 * 1024)}
        with patch("requests.get", return_value=fake_resp):
            assert ad._download_media_bytes("om_123", "fk") is None

    def test_inherits_auth_mixin(self):
        """孤儿 Mixin 复活：adapter 必须有 tenant token 管理能力"""
        ad = _adapter()
        assert hasattr(ad, "_get_tenant_access_token")
        assert hasattr(ad, "_token_lock")


class TestAudioMessageWiring:
    def test_audio_event_attaches_audio_bytes(self):
        """audio 事件 → file_key 解析 → 下载 → metadata.audio_bytes 就位"""
        ad = _adapter()
        lt = _MainLoopThread()
        ad._main_loop = lt.loop
        emitted = {}

        async def _capture(self, evt, msg):
            emitted["msg"] = msg

        with patch.object(
            FeishuAdapter, "_emit_event", _capture
        ), patch.object(FeishuAdapter, "_download_media_bytes", return_value=b"VOICE_DATA") as dl_mock:
            try:
                ad._handle_message_event(MagicMock(), _FakeEvent())
                for _ in range(100):
                    if "msg" in emitted:
                        break
                    lt.thread.join(0.02)
            finally:
                lt.stop()

        dl_mock.assert_called_once_with("om_123", "fk_abc")
        msg = emitted.get("msg")
        assert msg is not None, "事件未被调度"
        assert msg.metadata.get("audio_bytes") == b"VOICE_DATA"

    def test_audio_download_failure_still_emits_placeholder(self):
        """下载失败 → 降级 "[语音]" 占位直通，事件照常发出（绝不丢消息）"""
        ad = _adapter()
        lt = _MainLoopThread()
        ad._main_loop = lt.loop
        emitted = {}

        async def _capture(self, evt, msg):
            emitted["msg"] = msg

        with patch.object(FeishuAdapter, "_emit_event", _capture), patch.object(
            FeishuAdapter, "_download_media_bytes", return_value=None
        ):
            try:
                ad._handle_message_event(MagicMock(), _FakeEvent())
                for _ in range(100):
                    if "msg" in emitted:
                        break
                    lt.thread.join(0.02)
            finally:
                lt.stop()

        msg = emitted.get("msg")
        assert msg is not None, "下载失败也必须发事件"
        assert msg.content == "[语音]"
        assert "audio_bytes" not in msg.metadata  # 无字节 → voice_precheck 走占位直通

    def test_text_message_untouched(self):
        """text 消息不触发下载（零开销）"""
        ad = _adapter()

        class _TextMsg(_FakeMsg):
            message_type = "text"
            content = '{"text":"你好"}'

        class _TextEvent(_FakeEvent):
            def __init__(self):
                super().__init__()
                self.event.message = _TextMsg()

        ad._emit_event = MagicMock()
        ad._main_loop = None  # 走 warning 分支也行，重点是没下载调用
        with patch.object(FeishuAdapter, "_download_media_bytes") as dl_mock:
            t = threading.Thread(target=lambda: ad._handle_message_event(MagicMock(), _TextEvent()))
            t.start()
            t.join(2)
        dl_mock.assert_not_called()
