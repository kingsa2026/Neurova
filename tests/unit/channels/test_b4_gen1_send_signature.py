"""B-4: Gen1 send_message 签名统一（红→绿 TDD）

缺陷: 基类 ChannelAdapter.send_message 契约为
    async send_message(chat_id, content, message_type="text", **kwargs) -> Optional[str]
而 discord/qqbot/qq/websocket 四个 Gen1 适配器以 (self, message: UnifiedMessage) 覆写，
manager.send_message（manager.py:177/226）按基类签名直连 → TypeError（签名错位）。

修复（qclaw 先例）: 四适配器补齐基类签名实现（内部委托既有 UnifiedMessage 逻辑），
旧 UnifiedMessage 路径保留为内部 _send_unified。全测试 mock/fake，不触真实网络。
"""

import inspect
import time

import pytest

import neurova.channels.qq as qq_mod
import neurova.channels.websocket as websocket_module
from neurova.channels.base import ChannelAdapter
from neurova.channels.discord import DiscordAdapter
from neurova.channels.models import ContentType, MessageChannel, UnifiedMessage
from neurova.channels.qq import QQAdapter
from neurova.channels.qqbot import QQBotAdapter
from neurova.channels.websocket import WebSocketAdapter

GEN1_ADAPTERS = [DiscordAdapter, QQBotAdapter, QQAdapter, WebSocketAdapter]


# ============================================================
# 签名契约：与基类抽象签名逐参一致
# ============================================================


@pytest.mark.parametrize("adapter_cls", GEN1_ADAPTERS)
def test_send_message_matches_base_signature(adapter_cls):
    assert issubclass(adapter_cls, ChannelAdapter)
    assert isinstance(adapter_cls(), ChannelAdapter), "isinstance 契约"

    sig = inspect.signature(adapter_cls.send_message)
    base_sig = inspect.signature(ChannelAdapter.send_message)
    assert list(sig.parameters) == list(base_sig.parameters), "参数名/顺序必须与基类一致"
    assert sig.parameters["message_type"].default == "text"
    assert sig.parameters["kwargs"].kind is inspect.Parameter.VAR_KEYWORD
    assert inspect.iscoroutinefunction(adapter_cls.send_message), "基类契约为 async"


@pytest.mark.parametrize("adapter_cls", GEN1_ADAPTERS)
def test_legacy_unified_path_preserved(adapter_cls):
    """旧 UnifiedMessage 路径保留为内部 _send_unified（qclaw 先例）"""
    assert hasattr(adapter_cls, "_send_unified")


# ============================================================
# 基类签名直调（mock 层面发送成功）— manager 直连场景
# ============================================================


@pytest.mark.asyncio
async def test_discord_base_signature_direct_call_success():
    adapter = DiscordAdapter()
    adapter._initialized = True

    captured = {}

    class _Resp:
        status_code = 200

        @staticmethod
        def json():
            return {"id": "M1"}

    class _Session:
        def post(self, url, headers=None, json=None, timeout=None):
            captured.update(url=url, payload=json)
            return _Resp()

    adapter.session = _Session()

    msg_id = await adapter.send_message("chan1", "hello")
    assert isinstance(msg_id, str) and msg_id, "成功必须返回 message_id"
    assert captured["url"].endswith("/channels/chan1/messages")
    assert captured["payload"]["content"] == "hello"


@pytest.mark.asyncio
async def test_discord_base_signature_direct_call_failure_returns_none():
    adapter = DiscordAdapter()
    adapter._initialized = True

    class _Resp:
        status_code = 500

        @staticmethod
        def json():
            return {"message": "boom"}

    class _Session:
        def post(self, url, headers=None, json=None, timeout=None):
            return _Resp()

    adapter.session = _Session()
    assert await adapter.send_message("chan1", "hello") is None


@pytest.mark.asyncio
async def test_qqbot_base_signature_direct_call_success(monkeypatch):
    adapter = QQBotAdapter()
    adapter._initialized = True

    captured = {}

    def fake_api_request(method, endpoint, **kwargs):
        captured.update(endpoint=endpoint, payload=kwargs.get("json"))
        return {"retcode": 0, "data": {"message_id": 123}}

    monkeypatch.setattr(adapter, "_api_request", fake_api_request)

    msg_id = await adapter.send_message("12345", "hello")
    assert isinstance(msg_id, str) and msg_id
    assert captured["endpoint"] == "/send_group_msg"
    assert captured["payload"]["message"] == "hello"


@pytest.mark.asyncio
async def test_qqbot_base_signature_direct_call_failure_returns_none(monkeypatch):
    adapter = QQBotAdapter()
    adapter._initialized = True
    monkeypatch.setattr(adapter, "_api_request", lambda *a, **k: {"retcode": 1})
    assert await adapter.send_message("12345", "hello") is None


class _QQResp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload

    @property
    def text(self):
        return str(self._payload)


@pytest.mark.asyncio
async def test_qq_base_signature_direct_call_with_kwargs_metadata(monkeypatch):
    """kwargs 进入 metadata：chat_type/msg_seq 等平台特有参数与旧 UnifiedMessage 路径等价"""
    adapter = QQAdapter()
    adapter.access_token = "t"
    adapter.token_expire_time = time.time() + 9999

    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured.update(url=url, payload=json)
        return _QQResp({"id": "M1"})

    monkeypatch.setattr(qq_mod.requests, "post", fake_post)

    msg_id = await adapter.send_message("gopenid", "hello", chat_type="group", msg_seq=2, message_id="MSGID1")
    assert isinstance(msg_id, str) and msg_id
    assert captured["url"].endswith("/v2/groups/gopenid/messages")
    assert captured["payload"]["content"] == "hello"
    assert captured["payload"]["msg_seq"] == 2
    assert captured["payload"]["msg_id"] == "MSGID1", "kwargs.message_id 必须落到被动回复 msg_id"


@pytest.mark.asyncio
async def test_qq_base_signature_direct_call_failure_returns_none(monkeypatch):
    adapter = QQAdapter()
    adapter.access_token = "t"
    adapter.token_expire_time = time.time() + 9999
    monkeypatch.setattr(qq_mod.requests, "post", lambda *a, **k: _QQResp({}, status=500))
    assert await adapter.send_message("chan1", "hello") is None


@pytest.mark.asyncio
async def test_websocket_base_signature_direct_call(monkeypatch):
    monkeypatch.setattr(websocket_module, "WEBSOCKETS_AVAILABLE", True)

    adapter = WebSocketAdapter()
    adapter._initialized = True
    adapter._connected = True

    sent = []

    class _Conn:
        async def send(self, payload):
            sent.append(payload)

    adapter._ws_connection = _Conn()

    msg_id = await adapter.send_message("u1", "hello")
    assert isinstance(msg_id, str) and msg_id
    assert "hello" in "".join(sent), "必须经真实 ws 连接 await 发送"


@pytest.mark.asyncio
async def test_websocket_base_signature_not_connected_returns_none():
    adapter = WebSocketAdapter()
    adapter._initialized = True
    adapter._connected = False
    assert await adapter.send_message("u1", "hello") is None
