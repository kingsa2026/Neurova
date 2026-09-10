"""C-24 回归测试：ChannelManager._message_handlers 构造期建表 + 快照遍历。

缺陷：惰性 hasattr 建表存在竞态（并发 add 双建表）；dispatch 遍历活列表，
回调中增删会跳过处理器。
"""

from types import SimpleNamespace

import pytest

from neurova.channels.manager import ChannelManager


@pytest.fixture
def manager():
    ChannelManager._instance = None
    m = ChannelManager()
    yield m
    ChannelManager._instance = None


def test_handlers_table_initialized_in_ctor(manager):
    assert manager._message_handlers == []


def test_add_remove_without_lazy_branch(manager):
    calls = []

    def handler(msg):
        return None

    hid = manager.add_message_handler(handler)
    assert len(manager._message_handlers) == 1
    assert manager.remove_message_handler(hid) is True
    assert calls == []


@pytest.mark.asyncio
async def test_dispatch_iterates_snapshot(manager):
    calls = []

    async def h1(msg):
        calls.append("h1")
        manager.remove_message_handler(h2_id)

    async def h2(msg):
        calls.append("h2")

    manager.add_message_handler(h1)
    h2_id = manager.add_message_handler(h2)

    message = SimpleNamespace(channel_type="feishu", chat_id="c1")
    await manager._dispatch_message(message)

    # 快照遍历：h1 内移除 h2 不影响本轮分发（旧实现遍历活列表会跳过 h2）
    assert calls == ["h1", "h2"]


@pytest.mark.asyncio
async def test_dispatch_after_removal_does_not_call_removed_handler(manager):
    calls = []

    async def h1(msg):
        calls.append("h1")

    hid = manager.add_message_handler(h1)
    manager.remove_message_handler(hid)

    message = SimpleNamespace(channel_type="feishu", chat_id="c1")
    await manager._dispatch_message(message)
    assert calls == []
