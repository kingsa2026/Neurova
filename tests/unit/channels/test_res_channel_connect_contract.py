"""
资源型修复台账 2026-09-11 渠道域 #1/#8/#9/#13/#14 防回归测试

- #1/#8 Gen2 实例化打通：Discord/QQBot/WebSocket/MQTT/SIP 五个适配器此前缺
  connect/disconnect 抽象实现 → TypeError: Can't instantiate abstract class，
  渠道保存/测试端点（channel_config.py test_connection: connect→health_check→disconnect）
  对它们即 400。修复后必须可直接实例化，且 connect 接线真实路径、禁止假成功。
- #8 websocket.py Gen1 sync 残留：_init_connection / send_message 曾在捕获 loop 上
  run_until_complete（运行中循环上调用即 RuntimeError）——全模块不得再出现。
- #9 sip.py 诚实实现：SIP 协议栈未落地，connect/send_message 必须如实报未实现，
  绝不虚构 SIP 能力、绝不假成功。
- #13 receive_message 死 stub 清理：qq/qqbot/discord/sip/qclaw 的零消费口不得复活。
- #14 feishu.py _download_media_bytes 的 requests 调用必须带 timeout（防御性钉住）。

隔离纪律：无真实网络/文件/SQLite。discord/qqbot 的真实校验方法打桩；
websockets/paho-mqtt 用 fake 模块注入；feishu tenant token 与 requests.get 打桩。
"""

import asyncio
import inspect
import threading
import types
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import neurova.channels.discord as discord_module
import neurova.channels.mqtt as mqtt_module
import neurova.channels.websocket as websocket_module
from neurova.channels.base import ChannelConfig, ChannelEventType
from neurova.channels.discord import DiscordAdapter
from neurova.channels.mqtt import MQTTAdapter
from neurova.channels.models import ContentType, MessageChannel, UnifiedMessage
from neurova.channels.qclaw import QClawAdapter
from neurova.channels.qq import QQAdapter
from neurova.channels.qqbot import QQBotAdapter
from neurova.channels.sip import SIPAdapter
from neurova.channels.websocket import WebSocketAdapter


# ============================================================
# #1/#8 五适配器可直接实例化（Gen2 抽象契约补齐）
# ============================================================


@pytest.mark.parametrize(
    "adapter_cls,expected_type",
    [
        (DiscordAdapter, "discord"),
        (QQBotAdapter, "qqbot"),
        (WebSocketAdapter, "websocket"),
        (MQTTAdapter, "mqtt"),
        (SIPAdapter, "sip"),
    ],
)
def test_gen2_adapter_instantiable_and_contract(adapter_cls, expected_type):
    """修复前: TypeError: Can't instantiate abstract class（渠道保存/测试端点即 400）"""
    adapter = adapter_cls()
    assert isinstance(adapter.config, ChannelConfig), f"{adapter_cls.__name__} 缺基类契约三件"
    assert adapter.config.channel_type == expected_type
    assert adapter._connected is False
    assert adapter._event_callback is None
    # 基类抽象契约必须是 async 实现（base.py:151/:161）
    assert inspect.iscoroutinefunction(adapter_cls.connect), f"{adapter_cls.__name__}.connect 必须是 async"
    assert inspect.iscoroutinefunction(adapter_cls.disconnect), f"{adapter_cls.__name__}.disconnect 必须是 async"


# ============================================================
# #1 DiscordAdapter connect/disconnect（接线真实 _verify_token 路径）
# ============================================================


@pytest.mark.asyncio
async def test_discord_connect_without_token_honest_fail():
    """bot_token 未配置（authenticate 未通过）→ 诚实失败，不做任何网络调用"""
    adapter = DiscordAdapter()
    assert await adapter.connect() is False
    assert adapter._connected is False


@pytest.mark.asyncio
async def test_discord_connect_verifies_token_off_event_loop(monkeypatch):
    """connect 走真实 _verify_token 校验路径，且 HTTP 往返必须下沉工作线程"""
    adapter = DiscordAdapter()
    adapter.bot_token = "fake.token.signature"
    loop_thread = threading.current_thread()
    seen = {}

    def fake_verify():
        seen["thread"] = threading.current_thread()
        adapter._initialized = True
        return True

    monkeypatch.setattr(adapter, "_verify_token", fake_verify)

    assert await adapter.connect() is True
    assert adapter._connected is True
    assert seen["thread"] is not loop_thread, "Discord connect 的真实校验阻塞了事件循环线程"


@pytest.mark.asyncio
async def test_discord_connect_false_when_token_invalid(monkeypatch):
    adapter = DiscordAdapter()
    adapter.bot_token = "bad"
    monkeypatch.setattr(adapter, "_verify_token", lambda: False)
    assert await adapter.connect() is False
    assert adapter._connected is False, "校验失败不得假成功置 _connected"


@pytest.mark.asyncio
async def test_discord_disconnect_closes_session():
    adapter = DiscordAdapter()
    closed = []
    adapter.session = SimpleNamespace(close=lambda: closed.append(1))
    adapter._connected = True
    adapter._initialized = True

    await adapter.disconnect()

    assert closed == [1], "disconnect 必须真实关闭 requests.Session"
    assert adapter.session is None
    assert adapter._connected is False
    assert adapter._initialized is False


# ============================================================
# #1 QQBotAdapter connect/disconnect（接线真实 _verify_connection 路径）
# ============================================================


@pytest.mark.asyncio
async def test_qqbot_connect_without_token_honest_fail():
    adapter = QQBotAdapter()
    assert await adapter.connect() is False
    assert adapter._connected is False


@pytest.mark.asyncio
async def test_qqbot_connect_verifies_off_event_loop(monkeypatch):
    adapter = QQBotAdapter()
    adapter.access_token = "tok"
    loop_thread = threading.current_thread()
    seen = {}

    def fake_verify():
        seen["thread"] = threading.current_thread()
        adapter._initialized = True
        return True

    monkeypatch.setattr(adapter, "_verify_connection", fake_verify)

    assert await adapter.connect() is True
    assert adapter._connected is True
    assert seen["thread"] is not loop_thread, "QQBot connect 的真实校验阻塞了事件循环线程"


@pytest.mark.asyncio
async def test_qqbot_disconnect_clears_state():
    adapter = QQBotAdapter()
    adapter._connected = True
    adapter._initialized = True
    adapter._ws_connection = object()

    await adapter.disconnect()

    assert adapter._connected is False
    assert adapter._initialized is False
    assert adapter._ws_connection is None


# ============================================================
# #1/#8 WebSocketAdapter connect（真实 websockets 路径，禁假成功）
# ============================================================


class _FakeWsConn:
    """长连接替身：无消息时挂起（保持 _receive_loop 存活），可发可关"""

    def __init__(self):
        self.sent = []
        self.closed = False
        self._idle = asyncio.Event()

    def __aiter__(self):
        return self

    async def __anext__(self):
        await self._idle.wait()
        raise StopAsyncIteration

    async def send(self, payload):
        self.sent.append(payload)

    async def close(self):
        self.closed = True
        self._idle.set()


class _FakeWebsocketsModule:
    def __init__(self, fail=False):
        self.fail = fail
        self.connect_kwargs = {}

    async def connect(self, url, **kwargs):
        self.connect_kwargs = {"url": url, **kwargs}
        if self.fail:
            raise OSError("connection refused")
        return _FakeWsConn()


@pytest.mark.asyncio
async def test_websocket_connect_without_url_honest_fail():
    adapter = WebSocketAdapter()
    assert await adapter.connect() is False
    assert adapter._connected is False


@pytest.mark.asyncio
async def test_websocket_connect_honest_fail_when_lib_missing(monkeypatch):
    """websockets 未安装 → 诚实失败。修复前 _init_connection '模拟初始化' return True 假成功"""
    monkeypatch.setattr(websocket_module, "WEBSOCKETS_AVAILABLE", False)
    adapter = WebSocketAdapter()
    adapter.ws_url = "ws://unit.test/x"
    assert await adapter.connect() is False
    assert adapter._connected is False


@pytest.mark.asyncio
async def test_websocket_connect_success_keeps_task_reference(monkeypatch):
    fake_ws = _FakeWebsocketsModule()
    monkeypatch.setattr(websocket_module, "WEBSOCKETS_AVAILABLE", True)
    # websockets 未安装的环境里模块级 `websockets` 名未被绑定，raising=False 兜住
    monkeypatch.setattr(websocket_module, "websockets", fake_ws, raising=False)

    adapter = WebSocketAdapter()
    adapter.ws_url = "ws://unit.test/ok"

    assert await adapter.connect() is True
    assert adapter._connected is True
    # connect 里起的 _receive_task 必须存引用（disconnect cancel 之）
    assert adapter._receive_task is not None
    assert not adapter._receive_task.done()

    await adapter.disconnect()
    assert adapter._receive_task is None
    assert adapter._connected is False


@pytest.mark.asyncio
async def test_websocket_connect_failure_honest_fail(monkeypatch):
    """连接异常必须如实返回 False。修复前 _init_connection 捕获异常仍 return True 假成功"""
    fake_ws = _FakeWebsocketsModule(fail=True)
    monkeypatch.setattr(websocket_module, "WEBSOCKETS_AVAILABLE", True)
    monkeypatch.setattr(websocket_module, "websockets", fake_ws, raising=False)

    adapter = WebSocketAdapter()
    adapter.ws_url = "ws://unit.test/fail"

    assert await adapter.connect() is False
    assert adapter._connected is False
    assert adapter._receive_task is None


def test_websocket_authenticate_is_config_only():
    """连接职责移交 connect：authenticate 只解析/校验配置，不再建连"""
    adapter = WebSocketAdapter()
    assert adapter.authenticate({"ws_url": "ws://unit.test/x"}) is True
    assert adapter.ws_url == "ws://unit.test/x"
    assert adapter._connected is False
    assert WebSocketAdapter().authenticate({}) is False, "缺 ws_url 必须诚实失败"


@pytest.mark.asyncio
async def test_websocket_send_message_is_async_and_awaits_connection(monkeypatch):
    fake_ws = _FakeWebsocketsModule()
    monkeypatch.setattr(websocket_module, "WEBSOCKETS_AVAILABLE", True)
    monkeypatch.setattr(websocket_module, "websockets", fake_ws)

    adapter = WebSocketAdapter()
    adapter.ws_url = "ws://unit.test/ok"
    await adapter.connect()
    conn = adapter._ws_connection

    msg = UnifiedMessage(
        message_id="m1",
        channel=MessageChannel.WEBSOCKET,
        content_type=ContentType.TEXT,
        content="hello",
        user_id="u1",
        chat_id="c1",
    )
    # B-4: 旧 UnifiedMessage 路径更名为内部 _send_unified（基类签名由 test_b4 覆盖）
    assert await adapter._send_unified(msg) is True
    assert "hello" in "".join(conn.sent), "send_message 必须 await 真实 ws 连接发送"

    await adapter.disconnect()


def test_websocket_no_run_until_complete_residual():
    """#8: Gen1 sync 残留必须清零——全模块不得再出现 run_until_complete 调用 / 捕获 loop 引用"""
    import re

    src = inspect.getsource(websocket_module)
    assert not re.search(r"run_until_complete\s*\(", src), (
        "websocket.py 仍残留 run_until_complete 调用（运行中循环上必抛 RuntimeError）"
    )
    adapter = WebSocketAdapter()
    assert not hasattr(adapter, "_event_loop"), "_event_loop 捕获 loop 引用应随 Gen1 sync 路径一并删除"


# ============================================================
# #1 MQTTAdapter connect（真实 paho 路径 + P1-7 主 loop 补捕获）
# ============================================================


def _install_fake_paho(monkeypatch, fail=False):
    created = {}

    class _FakeClient:
        def __init__(self, client_id=None, clean_session=None, transport=None):
            created["client"] = self
            self.connected = False
            self.loop_started = False
            self.loop_stopped = False
            self.disconnected = False
            self.connect_args = None

        def username_pw_set(self, username, password):
            self.credentials = (username, password)

        def connect(self, host, port, keepalive=None):
            if fail:
                raise OSError("connection refused")
            self.connect_args = (host, port, keepalive)
            self.connected = True

        def loop_start(self):
            self.loop_started = True

        def loop_stop(self):
            self.loop_stopped = True

        def is_connected(self):
            return self.connected

        def disconnect(self):
            self.disconnected = True
            self.connected = False

        def subscribe(self, topic, qos=0):
            return (0, 1)

    fake_mqtt = types.SimpleNamespace(Client=_FakeClient, MQTT_ERR_SUCCESS=0)
    monkeypatch.setattr(mqtt_module, "MQTT_AVAILABLE", True)
    # paho-mqtt 未安装的环境里模块级 `mqtt` 名未被绑定（try/except ImportError），raising=False 兜住
    monkeypatch.setattr(mqtt_module, "mqtt", fake_mqtt, raising=False)
    return created


@pytest.mark.asyncio
async def test_mqtt_connect_honest_fail_when_lib_missing(monkeypatch):
    monkeypatch.setattr(mqtt_module, "MQTT_AVAILABLE", False)
    adapter = MQTTAdapter()
    assert await adapter.connect() is False, "paho 未安装必须诚实失败（不得假成功）"
    assert adapter._connected is False


@pytest.mark.asyncio
async def test_mqtt_connect_success_captures_running_loop(monkeypatch):
    """P1-7: _init_connection 在 to_thread 工作线程上无法捕获主 loop，connect 成功后必须补捕获"""
    created = _install_fake_paho(monkeypatch)
    adapter = MQTTAdapter()
    adapter.host = "unit.test"
    adapter.port = 1883

    assert await adapter.connect() is True

    client = created["client"]
    assert client.connect_args == ("unit.test", 1883, 60)
    assert client.loop_started is True
    # paho 网络线程回调语义复现（对照 test_res_p1_feishu_ws_mqtt 的 _on_message 打法）
    adapter._on_connect(client, None, None, 0)
    assert adapter._connected is True
    assert adapter._main_loop is asyncio.get_running_loop(), (
        "connect 未捕获运行中事件循环——paho 线程回调将因 _main_loop=None 丢弃入站消息（P1-7 回归）"
    )

    await adapter.disconnect()
    assert client.loop_stopped is True
    assert client.disconnected is True
    assert adapter._client is None
    assert adapter._connected is False


@pytest.mark.asyncio
async def test_mqtt_connect_failure_honest_fail(monkeypatch):
    _install_fake_paho(monkeypatch, fail=True)
    adapter = MQTTAdapter()
    assert await adapter.connect() is False
    assert adapter._connected is False


# ============================================================
# #9 SIPAdapter 诚实实现（协议栈未落地 → 如实失败，绝不假成功）
# ============================================================


def test_sip_contract_trio():
    adapter = SIPAdapter()
    assert isinstance(adapter.config, ChannelConfig)
    assert adapter.config.channel_type == "sip"
    assert adapter._connected is False
    assert adapter._event_callback is None


@pytest.mark.asyncio
async def test_sip_connect_honest_fail_without_credentials():
    adapter = SIPAdapter()
    assert await adapter.connect() is False
    assert adapter._connected is False


@pytest.mark.asyncio
async def test_sip_connect_honest_fail_even_with_valid_config(monkeypatch, caplog):
    """配置齐全也必须诚实失败——SIP 协议栈未实现，绝不虚构能力"""
    import neurova.channels.sip as sip_module

    monkeypatch.setattr(sip_module, "PYVOIP_AVAILABLE", False)
    adapter = SIPAdapter()
    # B-3: pyVoIP 缺失时 dev 初始化不再"模拟成功"——authenticate 诚实返回 False，
    # 但凭据已写入，connect 仍越过凭据检查走到"未实现"诚实警告
    assert adapter.authenticate({"sip_username": "u", "sip_password": "p"}) is False
    assert adapter._initialized is False

    with caplog.at_level("WARNING"):
        assert await adapter.connect() is False
    assert adapter._connected is False
    assert any("SIP 通道未实现" in r.message for r in caplog.records), "connect 必须明示 SIP 通道未实现"


@pytest.mark.asyncio
async def test_sip_send_message_honest_unimplemented(caplog):
    adapter = SIPAdapter()
    with caplog.at_level("WARNING"):
        assert await adapter.send_message("chat1", "hello") is None
    assert any("SIP 通道未实现" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_sip_disconnect_clears_state():
    adapter = SIPAdapter()
    adapter._call_session = object()
    adapter._voip_client = object()
    adapter._connected = True

    await adapter.disconnect()

    assert adapter._call_session is None
    assert adapter._voip_client is None
    assert adapter._connected is False


# ============================================================
# #13 receive_message 死 stub 不复活（含本轮删除的五个 + 已清理的两个）
# ============================================================


@pytest.mark.parametrize(
    "adapter_cls",
    [DiscordAdapter, QQBotAdapter, WebSocketAdapter, MQTTAdapter, SIPAdapter, QQAdapter, QClawAdapter],
)
def test_receive_message_dead_stub_not_revived(adapter_cls):
    """全仓零消费口（mq/ws 的 _message_queue 已随 P1-7 删除），基类亦无此方法"""
    # QClawAdapter 构造需要显式 config（其余五类无参构造）
    adapter = adapter_cls(ChannelConfig(channel_type="qclaw")) if adapter_cls is QClawAdapter else adapter_cls()
    assert not hasattr(adapter, "receive_message"), f"{adapter_cls.__name__}.receive_message 死 stub 复活"


# ============================================================
# #14 feishu _download_media_bytes 必须带 timeout（防回归钉住）
# ============================================================


def test_feishu_download_media_bytes_passes_timeout(monkeypatch):
    from neurova.channels.feishu import FeishuAdapter

    adapter = FeishuAdapter(ChannelConfig(channel_type="feishu", app_id="cli_x", app_secret="s"))
    monkeypatch.setattr(adapter, "_get_tenant_access_token", lambda: "tok")

    seen = {}

    class _Resp:
        status_code = 200
        headers = {}
        content = b"audio-bytes"

    def fake_get(url, headers=None, params=None, timeout=None):
        seen["timeout"] = timeout
        return _Resp()

    monkeypatch.setattr("requests.get", fake_get)

    data = adapter._download_media_bytes("msg1", "key1")
    assert data == b"audio-bytes"
    assert seen["timeout"] is not None, "#14: 媒体下载 requests 调用缺 timeout（无超时上限）"


# ============================================================
# 附带：channel_config test_connection 端点链路兼容性（mock 层面全链）
# ============================================================


@pytest.mark.asyncio
async def test_test_connection_chain_connect_health_disconnect(monkeypatch):
    """模拟端点链路 adapter.connect() → health_check() → disconnect() 五适配器全通过"""
    # discord
    a = DiscordAdapter()
    a.bot_token = "t"
    monkeypatch.setattr(a, "_verify_token", lambda: True)
    assert await a.connect() is True
    assert (await a.health_check())["channel_type"] == "discord"
    await a.disconnect()

    # qqbot
    a = QQBotAdapter()
    a.access_token = "t"
    monkeypatch.setattr(a, "_verify_connection", lambda: True)
    assert await a.connect() is True
    assert (await a.health_check())["channel_type"] == "qqbot"
    await a.disconnect()

    # mqtt
    _install_fake_paho(monkeypatch)
    a = MQTTAdapter()
    assert await a.connect() is True
    assert (await a.health_check())["channel_type"] == "mqtt"
    await a.disconnect()

    # websocket
    monkeypatch.setattr(websocket_module, "WEBSOCKETS_AVAILABLE", True)
    monkeypatch.setattr(websocket_module, "websockets", _FakeWebsocketsModule())
    a = WebSocketAdapter()
    a.ws_url = "ws://unit.test/ok"
    assert await a.connect() is True
    assert (await a.health_check())["channel_type"] == "websocket"
    await a.disconnect()

    # sip：connect 诚实失败，但链路本身必须可走完（端点返回"Failed to connect"而非 500/400）
    a = SIPAdapter()
    assert await a.connect() is False
    assert (await a.health_check())["channel_type"] == "sip"
    await a.disconnect()
