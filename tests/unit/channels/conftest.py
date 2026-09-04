"""channels 域测试隔离夹具

P0-5 入站持久化队列接进 ChannelManager 后，走 _get_ingress_queue() 的测试
若不隔离会读写真实 data/channel_ingress.db——跨测试/跨运行的 tombstone
（channel_type:message_id 去重）让 claim() 捞到上次运行的遗留消息，
handler 收到陈旧对象导致旧契约测试（如 test_message_handler_called 的
消息身份断言）随机失败。此夹具把队列 DB 重定向到每测试独立的临时路径，
与环境变量 NEUROVA_CHANNEL_INGRESS_DB 的生产覆盖通道同源。
"""

import pytest


@pytest.fixture(autouse=True)
def _isolate_channel_ingress_db(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_CHANNEL_INGRESS_DB", str(tmp_path / "channel_ingress.db"))
    yield
