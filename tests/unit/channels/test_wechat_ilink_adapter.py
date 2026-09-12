# -*- coding: utf-8 -*-
"""WeChatILinkAdapter 端到端契约测试（真实协议语义，网络全 fake）。

钉死：
- 无 token 诚实拒连；有 token getconfig 校验通过才连接并启动长轮询；
- 入站 message_type!=1 过滤、context_token 去重、文本内容去重；
- 收消息 → _emit_event 送达 ChannelMessage（chat_id/metadata 完整）；
- 回复必须携带该用户最近 context_token（缓存落盘 sidecar），无缓存诚实 None；
- 语音优先平台 ASR 文本，无 ASR 走 audio_bytes（NV voice_precheck 契约）；
- 表单直填 token connect 成功后落盘 token 文件（重启免扫码）。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from neurova.channels.base import ChannelConfig, ChannelEventType
from neurova.channels.wechat_ilink import WeChatILinkAdapter


class FakeClient:
    def __init__(self, getconfig_ok=True, batches=None, download=b"PNG", upload_ok=True):
        self.getconfig_ok = getconfig_ok
        self.batches = list(batches or [])
        self.download = download
        self.upload_ok = upload_ok
        self.sent_texts = []
        self.started = False
        self.stopped = False
        self._empty_wait = asyncio.Event()

    async def start(self):
        self.started = True

    async def stop(self):
        self.stopped = True
        self._empty_wait.set()

    async def getconfig(self, ilink_user_id="", context_token=""):
        if not self.getconfig_ok:
            raise RuntimeError("401 unauthorized")
        return {"ret": 0}

    async def getupdates(self, cursor=""):
        if self.batches:
            return self.batches.pop(0)
        # 无更多消息：挂起直至 stop（模拟长轮询）
        await self._empty_wait.wait()
        return {"ret": -1, "msgs": []}

    async def download_media(self, url, aes_key_b64="", encrypt_query_param=""):
        return self.download

    async def send_text(self, to_user_id, text, context_token):
        self.sent_texts.append((to_user_id, text, context_token))
        return {"ret": 0, "msg_id": "m-1"}


def _cfg(tmp_path, **extra):
    ex = {"token_file": str(tmp_path / "bot_token"), **extra}
    return ChannelConfig(channel_type="wechat", enabled=True, extra=ex)


def _msg(text="你好", ctx="ctx-1", user="u1@im.wechat", mtype=1, **kw):
    m = {
        "from_user_id": user, "message_type": mtype, "context_token": ctx,
        "item_list": [{"type": 1, "text_item": {"text": text}}],
    }
    m.update(kw)
    return m


@pytest.fixture
def received():
    events = []

    async def cb(event_type, message):
        events.append((event_type, message))

    return events, cb


async def _wait_for(pred, timeout=2.0):
    for _ in range(int(timeout * 50)):
        if pred():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("condition not met in time")


@pytest.mark.asyncio
async def test_connect_without_token_honest_false(tmp_path, received):
    a = WeChatILinkAdapter(_cfg(tmp_path))  # 无 bot_token、无 token 文件
    assert await a.connect() is False
    assert a.is_connected is False


@pytest.mark.asyncio
async def test_connect_validates_and_starts_poll(tmp_path, received):
    a = WeChatILinkAdapter(_cfg(tmp_path, bot_token="tok-9"))
    fake = FakeClient(batches=[{"ret": 0, "msgs": [_msg()], "get_updates_buf": "c2"}])
    a._client = fake
    events, cb = received
    a.set_event_callback(cb)

    assert await a.connect() is True
    assert fake.started
    await _wait_for(lambda: len(events) == 1)
    et, m = events[0]
    assert et == ChannelEventType.MESSAGE_RECEIVED
    assert m.content == "你好"
    assert m.chat_id == "u1@im.wechat"
    assert m.metadata["wechat_context_token"] == "ctx-1"
    assert a._cursor == "c2"
    # 表单直填 token 落盘（重启免扫码）
    assert Path(tmp_path / "bot_token").read_text(encoding="utf-8") == "tok-9"
    await a.disconnect()
    assert fake.stopped


@pytest.mark.asyncio
async def test_connect_bad_token_honest_false(tmp_path):
    a = WeChatILinkAdapter(_cfg(tmp_path, bot_token="bad"))
    fake = FakeClient(getconfig_ok=False)
    a._client = fake
    assert await a.connect() is False
    assert fake.stopped  # 校验失败必须关 client，不泄漏连接


@pytest.mark.asyncio
async def test_filters_non_user_and_duplicates(tmp_path, received):
    batches = [{"ret": 0, "msgs": [
        _msg("回声", ctx="ctx-echo", mtype=2),   # bot 回显 → 过滤
        _msg("重复", ctx="ctx-dup"),              # 首次
        _msg("重复", ctx="ctx-dup"),              # context_token 去重
        _msg("重发", ctx="ctx-new", user="u1@im.wechat"),  # 同用户同文本? 内容不同 → 通过
    ]}]
    a = WeChatILinkAdapter(_cfg(tmp_path, bot_token="t"))
    a._client = FakeClient(batches=batches)
    events, cb = received
    a.set_event_callback(cb)
    await a.connect()
    await _wait_for(lambda: len(events) >= 1)
    await asyncio.sleep(0.1)
    contents = [m.content for _, m in events]
    assert contents == ["重复", "重发"]
    await a.disconnect()


@pytest.mark.asyncio
async def test_send_uses_cached_context_and_persists(tmp_path, received):
    a = WeChatILinkAdapter(_cfg(tmp_path, bot_token="t"))
    fake = FakeClient(batches=[{"ret": 0, "msgs": [_msg("问", ctx="ctx-77")]}])
    a._client = fake
    events, cb = received
    a.set_event_callback(cb)
    await a.connect()
    await _wait_for(lambda: len(events) == 1)

    mid = await a.send_message("u1@im.wechat", "答")
    assert mid == "m-1"
    assert fake.sent_texts == [("u1@im.wechat", "答", "ctx-77")]
    # context 落盘 sidecar，重启后可回
    sidecar = Path(tmp_path / "wechat_context_tokens.json")
    assert json.loads(sidecar.read_text(encoding="utf-8"))["u1@im.wechat"] == "ctx-77"
    await a.disconnect()


@pytest.mark.asyncio
async def test_send_without_context_honest_none(tmp_path):
    a = WeChatILinkAdapter(_cfg(tmp_path, bot_token="t"))
    a._client = FakeClient()
    await a.connect()
    assert await a.send_message("stranger@im.wechat", "hi") is None
    await a.disconnect()


@pytest.mark.asyncio
async def test_voice_prefers_platform_asr_then_audio_bytes(tmp_path, received):
    voice_asr = {
        "from_user_id": "u2@im.wechat", "message_type": 1, "context_token": "vc-1",
        "item_list": [{"type": 3, "voice_item": {"text_item": {"text": "转写好了"}}}],
    }
    voice_raw = {
        "from_user_id": "u2@im.wechat", "message_type": 1, "context_token": "vc-2",
        "item_list": [{"type": 3, "voice_item": {
            "media": {"encrypt_query_param": "eq", "aes_key": "k"}}}],
    }
    a = WeChatILinkAdapter(_cfg(tmp_path, bot_token="t"))
    a._client = FakeClient(batches=[{"ret": 0, "msgs": [voice_asr, voice_raw]}],
                           download=b"WAVDATA")
    events, cb = received
    a.set_event_callback(cb)
    await a.connect()
    await _wait_for(lambda: len(events) == 2)
    assert events[0][1].content == "转写好了"
    assert events[1][1].message_type == "voice"
    assert events[1][1].metadata["audio_bytes"] == b"WAVDATA"
    await a.disconnect()


@pytest.mark.asyncio
async def test_image_downloaded_to_disk(tmp_path, received):
    img = {
        "from_user_id": "u3@im.wechat", "message_type": 1, "context_token": "ic-1",
        "item_list": [{"type": 2, "image_item": {
            "media": {"encrypt_query_param": "eq", "aes_key": "k"}, "aeskey": "ab" * 16}}],
    }
    a = WeChatILinkAdapter(_cfg(tmp_path, bot_token="t",
                                media_directory=str(tmp_path / "media")))
    a._client = FakeClient(batches=[{"ret": 0, "msgs": [img]}], download=b"\x89PNG")
    events, cb = received
    a.set_event_callback(cb)
    await a.connect()
    await _wait_for(lambda: len(events) == 1)
    m = events[0][1]
    assert m.message_type == "image"
    p = Path(m.metadata["image_path"])
    assert p.read_bytes() == b"\x89PNG"
    await a.disconnect()


@pytest.mark.asyncio
async def test_validation_surface_matches_legacy_contract(tmp_path):
    """_wechat_authenticated 依赖 mode/_ilink_initialized 校验面——新适配器必须暴露，
    否则 test_connection 对 ilink 恒假失败（回归钉）。"""
    from neurova.api.endpoints.channel_config import _wechat_authenticated

    a = WeChatILinkAdapter(_cfg(tmp_path, bot_token="t"))
    a._client = FakeClient()
    assert a.mode == "ilink"
    assert _wechat_authenticated(a) is False  # 未连接
    assert await a.connect() is True
    assert _wechat_authenticated(a) is True   # 已连接=已认证
    await a.disconnect()
    assert _wechat_authenticated(a) is False
