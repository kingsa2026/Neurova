# -*- coding: utf-8 -*-
"""企微回调群聊 chatid/chat_type 解析（阶段3.3）——真走 handle_callback。"""
from __future__ import annotations
import asyncio
from neurova.channels.base import ChannelConfig
from neurova.channels.wechat_kf_crypto import callbackSignature
from neurova.channels.wecom import WeComAdapter


def _ad():
    return WeComAdapter(ChannelConfig(channel_type="wecom", app_id="corp", app_secret="sec",
                                      webhook_token="tok", extra={"encoding_aes_key": ""}))


def test_group_callback_sets_group_chat_type(monkeypatch):
    ad = _ad()
    captured = {}
    async def cap(et, m): captured["m"] = m
    ad._emit_event = cap
    ad._main_loop = asyncio.new_event_loop()
    xml = ("<xml><ToUserName>corp</ToUserName><FromUserName>u1</FromUserName>"
           "<CreateTime>1</CreateTime><MsgType>text</MsgType><Content>hi</Content>"
           "<MsgId>m1</MsgId><ChatId>wr_group_1</ChatId></xml>")
    # 明文模式（无 Encrypt）：签名第 4 元为空串，真签名（协议单源）
    sig = callbackSignature("tok", "ts", "nc", "")
    ad.handle_callback(sig, "ts", "nc", xml)
    # emit 经 run_coroutine_threadsafe 到未运行的 loop → 不即时执行；改为直接同步断言：
    # 用运行中的 loop 捕获
    async def run():
        ad._main_loop = asyncio.get_running_loop()
        ad.handle_callback(sig, "ts", "nc", xml)
        for _ in range(50):
            if captured: break
            await asyncio.sleep(0.01)
        return captured["m"]
    m = asyncio.run(run())
    assert m.chat_type == "group" and m.chat_id == "wr_group_1"
