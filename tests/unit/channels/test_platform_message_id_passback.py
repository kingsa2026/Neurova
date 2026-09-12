# -*- coding: utf-8 -*-
"""任务3（资源型修复登记台账 2026-09-11 渠道域收尾）：平台真实 message_id 回传。

缺陷：B-4 后 discord/qqbot/qq 的 _send_unified 仅返回 bool，基类签名
send_message 只能回落本地生成 id——但三家 API 响应体都含平台真实消息 ID：
- discord: 响应 JSON `id`（消息对象雪花 ID）
- qq:      响应 JSON `id`（频道消息对象 / v2 群聊·C2C 响应同字段）
- qqbot:   OneBot 响应 `data.message_id`（/send_group_msg、/send_private_msg）

契约：
- _send_unified 返回 Optional[str]：成功=平台真实 ID（响应无 ID 时回落
  message.message_id 本地生成），失败=None；
- send_message 透传真实 ID；
- 布尔语义兼容锁存：成功=非空 str（真）、失败=None（假）——既有
  `if result:` 调用方语义不回退（qqbot._send_typing 忽略返回值，同样兼容）。

全测试 mock/fake，不触真实网络。
"""

import time

import pytest

import neurova.channels.qq as qq_mod
from neurova.channels.discord import DiscordAdapter
from neurova.channels.models import ContentType, MessageChannel, UnifiedMessage
from neurova.channels.qq import QQAdapter
from neurova.channels.qqbot import QQBotAdapter

PLATFORM_ID = "PLATFORM_REAL_ID_0001"


class _Resp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status
        self.text = "" if isinstance(payload, Exception) else str(payload)

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


# ============================================================
# Discord（响应 JSON id）
# ============================================================


def _discord_adapter_with(resp):
    adapter = DiscordAdapter()
    adapter._initialized = True

    class _Session:
        def post(self, url, headers=None, json=None, timeout=None):
            return resp

    adapter.session = _Session()
    return adapter


@pytest.mark.asyncio
async def test_discord_send_message_returns_platform_id():
    """mock 响应含平台 ID 时 send_message 必须返回该 ID（原只回本地生成 id）"""
    adapter = _discord_adapter_with(_Resp({"id": PLATFORM_ID}))
    assert await adapter.send_message("chan1", "hello") == PLATFORM_ID


@pytest.mark.asyncio
async def test_discord_send_message_falls_back_without_id_in_response():
    """响应无 id 字段 → 回落现有本地生成 id（非空 str）"""
    adapter = _discord_adapter_with(_Resp({}))
    msg_id = await adapter.send_message("chan1", "hello")
    assert isinstance(msg_id, str) and msg_id


@pytest.mark.asyncio
async def test_discord_send_message_non_json_success_body_falls_back():
    """成功状态但响应体非 JSON → 回落本地 id，不得误判失败"""
    adapter = _discord_adapter_with(_Resp(ValueError("no body")))
    msg_id = await adapter.send_message("chan1", "hello")
    assert isinstance(msg_id, str) and msg_id


@pytest.mark.asyncio
async def test_discord_send_message_failure_returns_none():
    adapter = _discord_adapter_with(_Resp({"message": "boom"}, status=500))
    assert await adapter.send_message("chan1", "hello") is None


# ============================================================
# QQBot / OneBot（data.message_id）
# ============================================================


def _qqbot_adapter_with(api_payload, monkeypatch):
    adapter = QQBotAdapter()
    adapter._initialized = True
    monkeypatch.setattr(adapter, "_api_request", lambda method, endpoint, **kw: api_payload)
    return adapter


def _qqbot_unified_msg():
    return UnifiedMessage(
        message_id="temp",
        channel=MessageChannel.QQBOT,
        content_type=ContentType.TEXT,
        content="typing",
        user_id="u1",
        chat_id="12345",
    )


@pytest.mark.asyncio
async def test_qqbot_send_message_returns_platform_id(monkeypatch):
    """OneBot data.message_id（整型）必须以 str 形式透传"""
    adapter = _qqbot_adapter_with({"retcode": 0, "data": {"message_id": 987654321}}, monkeypatch)
    assert await adapter.send_message("12345", "hello") == "987654321"


@pytest.mark.asyncio
async def test_qqbot_send_message_falls_back_without_message_id(monkeypatch):
    adapter = _qqbot_adapter_with({"retcode": 0, "data": {}}, monkeypatch)
    msg_id = await adapter.send_message("12345", "hello")
    assert isinstance(msg_id, str) and msg_id


@pytest.mark.asyncio
async def test_qqbot_send_message_failure_returns_none(monkeypatch):
    adapter = _qqbot_adapter_with({"retcode": 1, "data": {}}, monkeypatch)
    assert await adapter.send_message("12345", "hello") is None


@pytest.mark.asyncio
async def test_qqbot_send_unified_bool_semantics_compatible(monkeypatch):
    """既有调用方布尔语义锁存：成功=非空 str（真）、失败=None（假）——
    `if result:` 契约不回退（_send_typing 等调用方无需改动）"""
    ok_adapter = _qqbot_adapter_with({"retcode": 0, "data": {"message_id": 42}}, monkeypatch)
    result = ok_adapter._send_unified(_qqbot_unified_msg())
    assert isinstance(result, str) and bool(result) is True

    fail_adapter = _qqbot_adapter_with({"retcode": 1}, monkeypatch)
    assert bool(fail_adapter._send_unified(_qqbot_unified_msg())) is False


# ============================================================
# QQ 开放平台（响应 JSON id）
# ============================================================


def _qq_adapter_with(resp, monkeypatch):
    adapter = QQAdapter()
    adapter.access_token = "t"
    adapter.token_expire_time = time.time() + 9999
    monkeypatch.setattr(qq_mod.requests, "post", lambda url, **kw: resp)
    return adapter


@pytest.mark.asyncio
async def test_qq_send_message_returns_platform_id(monkeypatch):
    adapter = _qq_adapter_with(_Resp({"id": PLATFORM_ID}), monkeypatch)
    assert await adapter.send_message("chan1", "hello") == PLATFORM_ID


@pytest.mark.asyncio
async def test_qq_send_message_falls_back_without_id(monkeypatch):
    adapter = _qq_adapter_with(_Resp({}), monkeypatch)
    msg_id = await adapter.send_message("chan1", "hello")
    assert isinstance(msg_id, str) and msg_id


@pytest.mark.asyncio
async def test_qq_204_empty_body_falls_back_to_local_id(monkeypatch):
    """官方 204 成功无包体：json() 抛错 → 回落本地 id，仍为真值 str"""

    class _NoBodyResp:
        status_code = 204
        text = ""

        def json(self):
            raise ValueError("no body")

    adapter = _qq_adapter_with(_NoBodyResp(), monkeypatch)
    msg_id = await adapter.send_message("chan1", "hello")
    assert isinstance(msg_id, str) and msg_id


@pytest.mark.asyncio
async def test_qq_send_message_failure_returns_none(monkeypatch):
    adapter = _qq_adapter_with(_Resp({"error": "denied"}, status=403), monkeypatch)
    assert await adapter.send_message("chan1", "hello") is None
