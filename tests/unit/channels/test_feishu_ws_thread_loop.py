# -*- coding: utf-8 -*-
"""飞书 Stream 线程必须跑在独立事件循环（lark 模块全局 loop 重绑）——根因回归。

lark_oapi.ws.client 在导入期把 `loop` 绑成 asyncio.get_event_loop()；NV 在主运行循环
里 import lark → 该全局即主循环。client.start() 用 `loop.run_until_complete(_connect())`
落到主循环 → "This event loop is already running" → ws 线程秒崩、飞书永不收消息。
_fix_：_connect_stream 的线程内 new_event_loop + 重绑 lark 模块 loop 到它。
本测试用假 ws.Client 捕获 start() 实际运行所在的循环，断言非主循环且未运行。
"""
from __future__ import annotations

import asyncio
import threading

import pytest

from neurova.channels.base import ChannelConfig
from neurova.channels.feishu import FeishuAdapter


@pytest.mark.asyncio
async def test_ws_client_start_runs_on_fresh_non_main_loop(monkeypatch):
    import lark_oapi as lark

    main_loop = asyncio.get_running_loop()
    captured = {}
    release = threading.Event()

    class FakeWsClient:
        def __init__(self, *a, **k):
            pass

        def start(self):
            loop = asyncio.get_event_loop()
            captured["loop"] = loop
            captured["is_main"] = loop is main_loop
            captured["running"] = loop.is_running()
            # 模拟阻塞长连接：释放后立即返回，避免线程悬挂
            release.wait(timeout=3)

    class FakeBuilder:
        def register_p2_im_message_receive_v1(self, f):
            return self

        def build(self):
            return object()

    monkeypatch.setattr(lark.ws, "Client", FakeWsClient)
    monkeypatch.setattr(lark.EventDispatcherHandler, "builder", lambda *a, **k: FakeBuilder())

    ad = FeishuAdapter(ChannelConfig(channel_type="feishu", app_id="x", app_secret="y",
                                     use_stream=True, extra={"domain": "feishu"}))
    ok = await ad.connect()
    assert ok is True

    # 等 start() 在后台线程记录循环
    for _ in range(100):
        if captured:
            break
        await asyncio.sleep(0.02)
    release.set()

    assert captured, "ws.Client.start() 未被调用"
    assert captured["is_main"] is False, "start() 跑在主循环上（lark 模块 loop 未重绑）"
    assert captured["running"] is False, "start() 所在循环已在运行 → run_until_complete 必崩"
    await ad.disconnect()
