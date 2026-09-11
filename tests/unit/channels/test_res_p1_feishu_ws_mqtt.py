"""
RES-P1-6 / RES-P1-7 / RES-P1-8 防回归测试（资源型Bug扫描报告 2026-09-11 渠道域）

- P1-6 feishu.py: send_message 内的同步 lark Client 调用必须经 asyncio.to_thread
  下沉到工作线程，不得阻塞事件循环线程。
- P1-7 websocket.py/mqtt.py: 入站消息必须经 _emit_event 走统一事件分发
  （对照 feishu/dingtalk 模式）；死队列 _message_queue 与死方法 receive_message
  必须删除（全仓零消费口，曾造成无界堆积+功能黑洞）。
- P1-8 websocket.py/mqtt.py: disconnect 必须是 async（基类 base.py:161 抽象契约），
  websocket 需 cancel _receive_task/_reconnect_task 并收尸；
  原同步实现 + run_until_complete 在运行中事件循环上必抛 RuntimeError。

隔离纪律：无真实网络/文件/SQLite。lark_oapi 与 paho-mqtt 在测试环境未安装，
以 fake 模块/对象注入；paho 线程回调语义用 asyncio.to_thread 复现。
"""

import asyncio
import sys
import threading
import types
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from neurova.channels.base import ChannelConfig, ChannelEventType
from neurova.channels.feishu import FeishuAdapter
from neurova.channels.mqtt import MQTTAdapter
from neurova.channels.websocket import WebSocketAdapter


# ============================================================
# 测试夹具（生产侧 connect 缺口已由台账 #1 补齐，直接用生产类实例化）
# ============================================================


class _FakeWsConnection:
    """async-iterable 的 WebSocket 连接替身"""

    def __init__(self, messages):
        self._messages = list(messages)
        self.closed = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._messages:
            raise StopAsyncIteration
        return self._messages.pop(0)

    async def close(self):
        self.closed = True


# ============================================================
# P1-6 feishu：同步 lark 调用不得阻塞事件循环
# ============================================================


class _FakeLarkBuilder:
    @classmethod
    def builder(cls):
        return cls()

    def receive_id_type(self, v):
        return self

    def request_body(self, b):
        return self

    def receive_id(self, v):
        return self

    def msg_type(self, v):
        return self

    def content(self, v):
        return self

    def build(self):
        return SimpleNamespace()


def _install_fake_lark(monkeypatch, record):
    """注入 fake lark_oapi 模块树，返回挂在 im.v1.message 上的 API 实例"""
    record.setdefault("called", False)

    class _FakeResponse:
        def __init__(self):
            self.data = SimpleNamespace(message_id="om_fake_1")
            self.code = 0
            self.msg = "ok"

        def success(self):
            return True

    class _FakeMessageApi:
        def create(self, request):
            record["called"] = True
            record["thread"] = threading.current_thread()
            return _FakeResponse()

    mod_lark = types.ModuleType("lark_oapi")
    mod_api = types.ModuleType("lark_oapi.api")
    mod_im = types.ModuleType("lark_oapi.api.im")
    mod_v1 = types.ModuleType("lark_oapi.api.im.v1")
    mod_v1.CreateMessageRequest = _FakeLarkBuilder
    mod_v1.CreateMessageRequestBody = _FakeLarkBuilder
    mod_lark.api = mod_api
    mod_api.im = mod_im
    mod_im.v1 = mod_v1
    monkeypatch.setitem(sys.modules, "lark_oapi", mod_lark)
    monkeypatch.setitem(sys.modules, "lark_oapi.api", mod_api)
    monkeypatch.setitem(sys.modules, "lark_oapi.api.im", mod_im)
    monkeypatch.setitem(sys.modules, "lark_oapi.api.im.v1", mod_v1)
    return _FakeMessageApi()


@pytest.mark.asyncio
async def test_p1_6_feishu_send_message_offloads_sync_lark_call(monkeypatch):
    """P1-6: send_message 中的 lark 同步 HTTP 调用必须在工作线程上执行"""
    record = {}
    msg_api = _install_fake_lark(monkeypatch, record)
    adapter = FeishuAdapter(ChannelConfig(channel_type="feishu", app_id="cli_x", app_secret="s"))
    adapter._client = SimpleNamespace(im=SimpleNamespace(v1=SimpleNamespace(message=msg_api)))

    loop_thread = threading.current_thread()
    msg_id = await adapter.send_message("chat_x", "hello")

    assert msg_id == "om_fake_1"
    assert record["called"]
    assert record["thread"] is not loop_thread, (
        "P1-6 未修复：同步 lark 调用直接跑在事件循环线程上，每条消息阻塞一次 HTTPS 往返"
    )


# ============================================================
# P1-7 websocket：入站消息走 _emit_event，死队列/死方法删除
# ============================================================


@pytest.mark.asyncio
async def test_p1_7_websocket_inbound_dispatches_via_event_callback():
    adapter = WebSocketAdapter()
    received = []

    async def cb(event_type, message):
        received.append((event_type, message))

    adapter.set_event_callback(cb)
    adapter._ws_connection = _FakeWsConnection(
        [
            '{"content":"hello","user_id":"u1","message_id":"m1"}',
            "plain-text-not-json",
        ]
    )

    await adapter._receive_loop()

    assert [m.content for _, m in received] == ["hello", "plain-text-not-json"], (
        "P1-7 未修复：入站消息仍进死队列 _message_queue，未走 _emit_event 统一分发"
    )
    assert all(et == ChannelEventType.MESSAGE_RECEIVED for et, _ in received)
    # 死队列与死方法必须删除（全仓 receive_message 零调用方）
    assert not hasattr(adapter, "_message_queue")
    assert not hasattr(adapter, "receive_message")


def test_p1_7_websocket_gen2_contract_present():
    """P1-7 的 _emit_event 依赖基类三件契约（websocket 经 super().__init__ 获得）"""
    adapter = WebSocketAdapter()
    assert isinstance(adapter.config, ChannelConfig)
    assert adapter.config.channel_type == "websocket"
    assert adapter._connected is False
    assert adapter._event_callback is None
    assert adapter.channel_type == "websocket"


# ============================================================
# P1-7 mqtt：paho 线程回调经 run_coroutine_threadsafe 分发
# ============================================================


def _fake_mqtt_msg(payload: bytes, topic: str = "server/u1/up") -> SimpleNamespace:
    return SimpleNamespace(topic=topic, payload=payload, qos=1, retain=False)


@pytest.mark.asyncio
async def test_p1_7_mqtt_inbound_dispatches_via_event_callback():
    adapter = MQTTAdapter()
    received = []
    done = asyncio.Event()

    async def cb(event_type, message):
        received.append((event_type, message))
        done.set()

    adapter.set_event_callback(cb)
    adapter._main_loop = asyncio.get_running_loop()

    # paho loop_start 的网络线程在独立线程上回调 _on_message，用 to_thread 复现
    await asyncio.to_thread(adapter._on_message, None, None, _fake_mqtt_msg(b'{"content":"hi","user_id":"u1"}'))

    await asyncio.wait_for(done.wait(), timeout=2)
    event_type, message = received[0]
    assert event_type == ChannelEventType.MESSAGE_RECEIVED
    assert message.content == "hi"
    # 死队列与死方法必须删除
    assert not hasattr(adapter, "_message_queue")
    assert not hasattr(adapter, "receive_message")
    # Gen2 契约：mqtt 走基类构造（此前 __init__ 完全未调 super，config/_event_callback 缺失）
    assert isinstance(adapter.config, ChannelConfig)
    assert adapter.config.channel_type == "mqtt"


@pytest.mark.asyncio
async def test_p1_7_mqtt_drops_message_when_no_loop_available():
    """无可用事件循环时必须丢弃并告警，而不是退回无界堆积"""
    adapter = MQTTAdapter()
    received = []

    async def cb(event_type, message):
        received.append(message)

    adapter.set_event_callback(cb)
    adapter._main_loop = None

    await asyncio.to_thread(adapter._on_message, None, None, _fake_mqtt_msg(b'{"content":"x"}'))
    await asyncio.sleep(0.05)

    assert received == []
    assert not hasattr(adapter, "_message_queue")


# ============================================================
# P1-8 websocket：async disconnect + cancel 后台任务
# ============================================================


@pytest.mark.asyncio
async def test_p1_8_websocket_disconnect_is_async_and_cancels_tasks():
    adapter = WebSocketAdapter()
    conn = _FakeWsConnection([])
    adapter._ws_connection = conn
    receive_task = asyncio.create_task(asyncio.sleep(3600))
    reconnect_task = asyncio.create_task(asyncio.sleep(3600))
    adapter._receive_task = receive_task
    adapter._reconnect_task = reconnect_task
    adapter._connected = True

    # 修复前：sync def disconnect + run_until_complete 在运行中循环上必抛
    # RuntimeError（或 await None 的 TypeError），manager.stop/restart 中断
    await adapter.disconnect()

    assert conn.closed is True
    assert adapter._ws_connection is None
    assert receive_task.cancelled(), "_receive_task 未被 cancel（僵尸重连任务泄漏）"
    assert reconnect_task.cancelled(), "_reconnect_task 未被 cancel（僵尸重连任务泄漏）"
    assert adapter._receive_task is None
    assert adapter._reconnect_task is None
    assert adapter._connected is False


# ============================================================
# P1-8 mqtt：async disconnect（基类抽象契约）
# ============================================================


@pytest.mark.asyncio
async def test_p1_8_mqtt_disconnect_is_async_and_releases_client():
    adapter = MQTTAdapter()
    client = SimpleNamespace(loop_stop=Mock(), disconnect=Mock())
    adapter._client = client
    adapter._connected = True

    # 修复前：sync def → await None → TypeError，manager.stop 的 gather 中断
    await adapter.disconnect()

    client.loop_stop.assert_called_once()
    client.disconnect.assert_called_once()
    assert adapter._client is None
    assert adapter._connected is False


@pytest.mark.asyncio
async def test_p1_8_mqtt_disconnect_idempotent_without_client():
    adapter = MQTTAdapter()
    adapter._client = None
    await adapter.disconnect()  # 不抛即通过
