"""C-13 回归测试：feishu/dingtalk disconnect() 必须真正关闭长连接资源。

缺陷：原 disconnect() 仅 pass + 置标志，不调用 SDK stop/close、不 join
长连接线程 → 重复 connect 产生并存长连接。修复后：
- 探测 SDK 客户端的 stop()/close()（getattr，SDK 版本差异安全）并调用
  （awaitable 结果在主 loop 等待）
- join 长连接线程（daemon，timeout=5，超时不强杀）
- 保持幂等
"""

import threading

import pytest

from neurova.channels.dingtalk import create_dingtalk_adapter
from neurova.channels.feishu import create_feishu_adapter


class FakeLarkClientNoStop:
    """模拟当前 lark-oapi ws.Client（无公开 stop/close API）。"""


class FakeLarkClientWithStop:
    """模拟未来版本提供 stop() 的 lark ws Client。"""

    def __init__(self):
        self.stop_called = False

    async def stop(self):
        self.stop_called = True


class FakeDingtalkStreamClient:
    """模拟 dingtalk_stream.DingtalkStreamClient（async stop()）。"""

    def __init__(self):
        self.stop_called = False

    async def stop(self):
        self.stop_called = True


def _short_lived_thread():
    """一个 0.2 秒内自然退活的 daemon 线程，模拟长连接线程。"""
    evt = threading.Event()
    t = threading.Thread(target=lambda: evt.wait(0.2), daemon=True)
    t.start()
    return t


@pytest.mark.asyncio
async def test_feishu_disconnect_joins_thread_and_clears_state():
    adapter = create_feishu_adapter(app_id="cli_x", app_secret="s")
    adapter._ws_client = FakeLarkClientNoStop()
    thread = _short_lived_thread()
    adapter._ws_thread = thread
    adapter._connected = True

    await adapter.disconnect()

    assert adapter._ws_client is None
    assert adapter._ws_thread is None  # C-13: join 后清引用
    assert adapter.is_connected is False


@pytest.mark.asyncio
async def test_feishu_disconnect_calls_stop_when_sdk_provides():
    adapter = create_feishu_adapter(app_id="cli_x", app_secret="s")
    client = FakeLarkClientWithStop()
    adapter._ws_client = client
    adapter._ws_thread = _short_lived_thread()

    await adapter.disconnect()

    assert client.stop_called is True


@pytest.mark.asyncio
async def test_dingtalk_disconnect_calls_async_stop_and_joins_thread():
    adapter = create_dingtalk_adapter(app_id="app_x", app_secret="s")
    client = FakeDingtalkStreamClient()
    adapter._stream_client = client
    thread = _short_lived_thread()
    adapter._ws_thread = thread
    adapter._connected = True

    await adapter.disconnect()

    assert client.stop_called is True  # 旧实现为 pass，此断言必红
    assert adapter._ws_thread is None
    assert adapter._stream_client is None
    assert adapter.is_connected is False


@pytest.mark.asyncio
async def test_disconnect_idempotent():
    feishu = create_feishu_adapter(app_id="cli_x", app_secret="s")
    feishu._ws_client = FakeLarkClientWithStop()
    feishu._ws_thread = _short_lived_thread()
    ding = create_dingtalk_adapter(app_id="app_x", app_secret="s")
    ding._stream_client = FakeDingtalkStreamClient()
    ding._ws_thread = _short_lived_thread()

    await feishu.disconnect()
    await feishu.disconnect()  # 第二次不得抛错
    await ding.disconnect()
    await ding.disconnect()

    assert feishu.is_connected is False
    assert ding.is_connected is False
