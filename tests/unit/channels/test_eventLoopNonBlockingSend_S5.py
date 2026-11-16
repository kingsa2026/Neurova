"""P1-16 红灯：渠道适配器 async 发送路径直调同步 HTTP，阻塞事件循环。

ChannelManager.send_message 是所有渠道回复与工作流审批通知的唯一出口，
跑在主事件循环上——同步 HTTP 直调一次 10-30s，全进程请求排队。
判据：发送期间事件循环心跳（asyncio.sleep 实际返回间隔）必须远小于
假 HTTP 的阻塞时长；同步直调（红）≈ 阻塞时长，to_thread（绿）≈ 心拍周期。
对照范本：feishu.py:611 / qq_ws.py:391 / mqtt.py:420 / wecom.py:342。
"""

import asyncio
import time

import pytest

import neurova.channels.qq as qq_mod
import neurova.channels.qclaw_service as qclaw_service_mod
import neurova.channels.wechat_messaging as wechat_messaging_mod
import neurova.channels.qqbot as qqbot_mod
from neurova.channels.base import ChannelConfig
from neurova.channels.discord import DiscordAdapter
from neurova.channels.models import ContentType, MessageChannel, UnifiedMessage
from neurova.channels.qclaw import QClawAdapter
from neurova.channels.qclaw_service import QClawService
from neurova.channels.qq import QQAdapter
from neurova.channels.qqbot import QQBotAdapter
from neurova.channels.telegram_adapter import TelegramAdapter
from neurova.channels.voice import VoiceAdapter
from neurova.channels.wechat import WeChatAdapter

BLOCK_SECONDS = 0.6


async def _measureLoopGapDuring(send_coro_factory):
    """测量 send_coro_factory() 首个执行片是否同步阻塞事件循环。

    心跳定时器在 send 任务首次运行**之前**就排上：若 send 在首个执行片内
    直调同步 HTTP，循环被卡 BLOCK_SECONDS，心跳只能等阻塞结束才触发
    （gap≈阻塞时长＝红）；to_thread 后心跳按 0.05s 正常返回（gap≈0.05＝绿）。
    阈值取 BLOCK_SECONDS/2，两侧余量充足、分离干净。
    """
    loop = asyncio.get_running_loop()
    heartbeat_start = loop.time()
    task = asyncio.create_task(send_coro_factory())
    await asyncio.sleep(0.05)
    gap = loop.time() - heartbeat_start
    result = await asyncio.wait_for(task, timeout=BLOCK_SECONDS * 5)
    assert gap < BLOCK_SECONDS / 2, (
        f"事件循环心跳间隔 {gap:.2f}s ≥ {BLOCK_SECONDS / 2:.2f}s："
        f"发送路径在事件循环线程内直调同步 HTTP"
    )
    return result


class _SlowResp:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


def _slowRequestsPost(monkeypatch, target_mod, payload, status_code=200):
    """给目标模块的 requests.post 打上「睡 BLOCK_SECONDS 再回包」的桩。"""

    def slow_post(url, **kwargs):
        time.sleep(BLOCK_SECONDS)
        return _SlowResp(payload, status_code)

    monkeypatch.setattr(target_mod.requests, "post", slow_post)


@pytest.mark.asyncio
async def test_discord_send_does_not_block_event_loop():
    adapter = DiscordAdapter()
    adapter._initialized = True

    class _Session:
        def post(self, url, headers=None, json=None, timeout=None):
            time.sleep(BLOCK_SECONDS)
            return _SlowResp({"id": "M1"})

    adapter.session = _Session()
    msg_id = await _measureLoopGapDuring(lambda: adapter.send_message("chan1", "hello"))
    assert msg_id == "M1"


@pytest.mark.asyncio
async def test_qq_send_does_not_block_event_loop(monkeypatch):
    adapter = QQAdapter()
    adapter.access_token = "tok"
    adapter.token_expire_time = time.time() + 9999  # _ensure_token 直接过，别撞令牌接口
    _slowRequestsPost(monkeypatch, qq_mod, {"id": "Q1"})
    msg_id = await _measureLoopGapDuring(lambda: adapter.send_message("123456", "hello"))
    assert msg_id == "Q1"


@pytest.mark.asyncio
async def test_qqbot_send_does_not_block_event_loop(monkeypatch):
    adapter = QQBotAdapter()
    adapter._initialized = True
    adapter.access_token = "t"

    def slow_api_request(method, endpoint, **kwargs):
        time.sleep(BLOCK_SECONDS)
        return {"retcode": 0, "data": {"message_id": "QB1"}}

    monkeypatch.setattr(adapter, "_api_request", slow_api_request)
    msg_id = await _measureLoopGapDuring(lambda: adapter.send_message("123456", "hello"))
    assert msg_id == "QB1"


@pytest.mark.asyncio
async def test_wechat_send_does_not_block_event_loop(monkeypatch):
    adapter = WeChatAdapter()
    adapter.mode = "wecom"
    adapter.kf_mode = False
    adapter.agentid = 1
    adapter.access_token = "t"
    monkeypatch.setattr(adapter, "_ensure_wecom_token", lambda: True)
    _slowRequestsPost(monkeypatch, wechat_messaging_mod, {"errcode": 0})
    result = await _measureLoopGapDuring(lambda: adapter.send_message("user1", "hello"))
    assert isinstance(result, str)


@pytest.mark.asyncio
async def test_qclaw_send_does_not_block_event_loop(monkeypatch):
    adapter = QClawAdapter(ChannelConfig(channel_type="qclaw", app_id="a", app_secret="s"))
    adapter.qclaw_service = QClawService()
    monkeypatch.setattr(adapter.qclaw_service, "get_access_token", lambda *a, **k: "tok")
    _slowRequestsPost(monkeypatch, qclaw_service_mod, {"common": {"code": 0}, "data": {"message_id": "C1"}})
    msg_id = await _measureLoopGapDuring(lambda: adapter.send_message("chat1", "hello"))
    assert msg_id == "C1"


@pytest.mark.asyncio
async def test_telegram_send_does_not_block_event_loop(monkeypatch):
    adapter = TelegramAdapter()
    adapter.bot_token = "t"
    adapter._initialized = True

    def slow_api_request(method, path, **kwargs):
        time.sleep(BLOCK_SECONDS)
        return {"ok": True, "result": {"message_id": 7}}

    monkeypatch.setattr(adapter, "_api_request", slow_api_request)
    # _send_text_message 返回 bool（ok=True），适配器按契约回落 "sent"
    msg_id = await _measureLoopGapDuring(lambda: adapter.send_message("123", "hello"))
    assert msg_id == "sent"


@pytest.mark.asyncio
async def test_voice_sms_and_call_do_not_block_event_loop(monkeypatch):
    adapter = VoiceAdapter(ChannelConfig(channel_type="voice"))
    adapter._connected = True

    class _Sid:
        sid = "V1"

    class _StubApi:
        def create(self, **kwargs):
            time.sleep(BLOCK_SECONDS)
            return _Sid()

    class _StubClient:
        calls = _StubApi()
        messages = _StubApi()

    adapter._client = _StubClient()

    call_id = await _measureLoopGapDuring(
        lambda: adapter.send_message("+8613800000000", "hi", "call")
    )
    assert call_id == "V1"

    sms_id = await _measureLoopGapDuring(
        lambda: adapter.send_message("+8613800000000", "hi", "sms")
    )
    assert sms_id == "V1"


@pytest.mark.asyncio
async def test_qqbot_ai_generation_path_does_not_block_event_loop(monkeypatch, tmp_path):
    """handle_ai_generation 全链（_send_typing + send_image）同契约扫平。"""
    adapter = QQBotAdapter()
    adapter._initialized = True
    monkeypatch.setattr(adapter, "media_directory", str(tmp_path))

    async def fake_text_to_image(self, prompt):
        return b"png-bytes"

    def slow_typing(self, message, content):
        time.sleep(BLOCK_SECONDS)

    def slow_send_image(chat_id, file_path="", **kwargs):
        time.sleep(BLOCK_SECONDS / 2)
        return True

    monkeypatch.setattr(qqbot_mod, "generate_text_to_image", fake_text_to_image)
    monkeypatch.setattr(qqbot_mod, "_send_typing", slow_typing)
    monkeypatch.setattr(adapter, "send_image", slow_send_image)

    message = UnifiedMessage(
        message_id="m1",
        channel=MessageChannel.QQBOT,
        content_type=ContentType.TEXT,
        content="生成图片 一只猫",
        user_id="u1",
        chat_id="123456",
    )
    handled = await _measureLoopGapDuring(lambda: adapter.handle_ai_generation(message))
    assert handled is True
