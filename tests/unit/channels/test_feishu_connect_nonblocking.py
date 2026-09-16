# -*- coding: utf-8 -*-
"""飞书 connect 不得饿死主事件循环——启动慢根修回归。

2026-09-16 实测：spawn→/health 200 共 14.5s，其中 6.7s 零日志窗口。
根因：bootstrap 的"后台化"只是 create_task（app.py _schedule_channel_bootstrap），
而 _connect_stream 在协程体内同步执行 `import lark_oapi`（全套 protobuf 生成代码，
实测 3.5s+）+ EventDispatcherHandler/ws.Client 构造——协程在 main loop 线程上没有
让出点，期间 uvicorn 无法接受任何连接，/health 就绪被拖到飞书连上之后。

修复契约（本测试钉死两件事，防"只挪位置不解决阻塞"或"异步化吞错误"回退）：
(a) lark 的重活（import/构造）不在 main loop 线程执行；
(b) 其耗时窗口内主循环心跳不饿死（/health 可服务）。
假件惯用法沿用 test_feishu_ws_thread_loop.py。
"""
from __future__ import annotations

import asyncio
import threading
import time

import pytest

from neurova.channels.base import ChannelConfig
from neurova.channels.feishu import FeishuAdapter


def _adapter() -> FeishuAdapter:
    return FeishuAdapter(ChannelConfig(
        channel_type="feishu", app_id="x", app_secret="y",
        use_stream=True, extra={"domain": "feishu"},
    ))


class _FakeBuilder:
    def __init__(self, on_build=None):
        self._on_build = on_build

    def register_p2_im_message_receive_v1(self, f):
        return self

    def register_p2_im_chat_member_bot_deleted_v1(self, f):
        return self

    def build(self):
        return object()


class _FakeWsClient:
    def __init__(self, *a, **k):
        pass

    def start(self):
        threading.Event().wait(timeout=3)


@pytest.mark.asyncio
async def test_connect_stream_setup_off_event_loop_thread(monkeypatch):
    """lark 构造在独立线程执行，且其 1s 耗时窗口内主循环心跳不饿死。"""
    import lark_oapi as lark

    main_tid = threading.get_ident()
    rec = {}
    release = threading.Event()

    def slow_builder(*a, **k):
        rec["builder_thread"] = threading.get_ident()
        # 模拟 lark 全家桶 import + handler 构造的实测耗时（阻塞调用线程）
        time.sleep(1.0)
        return _FakeBuilder()

    class ClientBlockingStart(_FakeWsClient):
        def start(self):
            release.wait(timeout=5)

    monkeypatch.setattr(lark.ws, "Client", ClientBlockingStart)
    monkeypatch.setattr(
        lark.EventDispatcherHandler, "builder", slow_builder, raising=False)

    ticks = 0
    hb_stop = asyncio.Event()

    async def heartbeat():
        nonlocal ticks
        while not hb_stop.is_set():
            ticks += 1
            await asyncio.sleep(0.02)

    hb_task = asyncio.ensure_future(heartbeat())
    try:
        ad = _adapter()
        ok = await asyncio.wait_for(ad.connect(), timeout=10)
    finally:
        hb_stop.set()
        release.set()
        await hb_task

    assert ok is True
    assert rec.get("builder_thread"), "EventDispatcherHandler.builder 未被调用"
    assert rec["builder_thread"] != main_tid, (
        "lark import/构造跑在事件循环线程 → 启动期 /health 被饿死（根因未修）")
    assert ticks >= 20, f"setup 1s 窗口内主循环心跳仅 {ticks} 次（<20）：loop 被 connect 阻塞"


@pytest.mark.asyncio
async def test_disconnect_during_setup_cancels_start(monkeypatch):
    """构造窗口内 disconnect 必须让线程放弃 start()，否则僵尸长连接。

    线程化修复引入的真实竞态：_connect_stream 现在把 import/构造放子线程（秒级），
    期间若 disconnect（restart_channel / shutdown 触发）置空 _ws_client，
    子线程若继续 start() 就会拉起一个无人引用的飞书长连接。取消位契约防这个。
    """
    import lark_oapi as lark

    started = threading.Event()
    release_setup = threading.Event()

    class HangingBuilder:
        def register_p2_im_message_receive_v1(self, f):
            return self

        def register_p2_im_chat_member_bot_deleted_v1(self, f):
            return self

        def build(self):
            return object()

    def slow_builder(*a, **k):
        release_setup.wait(timeout=5)  # 卡在构造期，等待被 disconnect 取消
        return HangingBuilder()

    class FakeWsClient:
        def __init__(self, *a, **k):
            pass

        def start(self):
            started.set()

    monkeypatch.setattr(lark.ws, "Client", FakeWsClient)
    monkeypatch.setattr(
        lark.EventDispatcherHandler, "builder", slow_builder, raising=False)

    ad = _adapter()
    connect_task = asyncio.ensure_future(ad.connect())
    await asyncio.sleep(0.05)      # 确保子线程已进入构造期
    await ad.disconnect()          # 构造期间断开
    release_setup.set()            # 放行构造，线程会去检查取消位

    await asyncio.wait_for(connect_task, timeout=10)
    await asyncio.sleep(0.1)
    assert not started.is_set(), "disconnect 后线程仍 start() → 僵尸长连接（取消位失效）"


@pytest.mark.asyncio
async def test_connect_stream_setup_error_still_returns_false(monkeypatch):
    """异步化不得吞错：构造期异常仍须让 connect() 诚实返回 False。"""
    import lark_oapi as lark

    def boom_builder(*a, **k):
        raise RuntimeError("simulated lark build failure")

    monkeypatch.setattr(lark.ws, "Client", _FakeWsClient)
    monkeypatch.setattr(
        lark.EventDispatcherHandler, "builder", boom_builder, raising=False)

    ad = _adapter()
    ok = await asyncio.wait_for(ad.connect(), timeout=10)
    assert ok is False
