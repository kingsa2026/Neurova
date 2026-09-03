"""
P0-4/5/6 修复测试：feishu/dingtalk/wecom 跨线程事件循环安全（C3/C4/C5）

测试目标（来自 fix-all-bugs-plan-v2.md）：
- RED：从子线程触发同步回调，断言事件被调度到主 loop（而非创建新 loop）
- GREEN：修复后 _main_loop 引用确保事件正确调度

设计依据：
- neurova/channels/feishu.py:148-162 _handle_message_event 的跨线程事件循环反模式
- neurova/channels/dingtalk.py:181-195 _handle_bot_message 同一反模式
- neurova/channels/wecom.py:177-191 handle_callback 同一反模式
- 三处都用 asyncio.get_event_loop() + run_until_complete + except RuntimeError: new_event_loop
- 子线程中 asyncio.get_event_loop() 在 Python 3.12+ 抛 RuntimeError，进入错误兜底分支
- 修复方案：捕获主 loop 引用到 self._main_loop，用 run_coroutine_threadsafe 调度
"""

import asyncio
import threading
import time
from typing import List, Tuple
from unittest.mock import MagicMock

import pytest

from neurova.channels.base import ChannelConfig
from neurova.channels.feishu import FeishuAdapter
from neurova.channels.dingtalk import DingTalkAdapter
from neurova.channels.wecom import WeComAdapter


def _start_main_loop() -> Tuple[asyncio.AbstractEventLoop, threading.Thread]:
    """启动主事件循环在后台线程，返回 (loop, thread)"""
    loop = asyncio.new_event_loop()

    def run():
        asyncio.set_event_loop(loop)
        loop.run_forever()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return loop, thread


def _stop_main_loop(loop: asyncio.AbstractEventLoop, thread: threading.Thread) -> None:
    """停止主事件循环"""
    loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=2)
    loop.close()


def _make_callback_tracker() -> Tuple[threading.Event, List[asyncio.AbstractEventLoop]]:
    """构造 callback 追踪器，返回 (event, loop_list)"""
    called = threading.Event()
    loops: List[asyncio.AbstractEventLoop] = []

    async def callback(event_type, message):
        loops.append(asyncio.get_running_loop())
        called.set()

    return called, loops


class TestFeishuEventLoopSafety:
    """P0-4: FeishuAdapter 跨线程事件循环安全"""

    def test_callback_schedules_to_main_loop(self):
        """RED: feishu 同步回调应将事件调度到主 loop（而非创建新 loop）

        修复前：子线程 asyncio.get_event_loop() 抛 RuntimeError → except 分支创建新 loop
                callback 在新 loop 上运行，不是主 loop
        修复后：用 self._main_loop + run_coroutine_threadsafe 调度到主 loop
                callback 在主 loop 上运行
        """
        adapter = FeishuAdapter(ChannelConfig(channel_type="feishu"))
        called = threading.Event()
        loops: List[asyncio.AbstractEventLoop] = []
        adapter.set_event_callback(_make_callback_func(called, loops))

        main_loop, loop_thread = _start_main_loop()
        # 修复后：adapter._main_loop 在 connect() 中设置
        # RED 阶段手动设置以隔离测试（修复前代码不读 _main_loop，所以无影响）
        adapter._main_loop = main_loop

        try:
            time.sleep(0.15)  # 等待 loop 启动

            # 构造 mock event（飞书 SDK 的 event 结构）
            mock_event = MagicMock()
            mock_event.event.message.message_type = "text"
            mock_event.event.message.content = '{"text":"hello"}'
            mock_event.event.message.message_id = "msg_123"
            mock_event.event.message.chat_id = "chat_1"
            mock_event.event.message.chat_type = "p2p"
            mock_event.event.sender.sender_id.user_id = "user_1"
            mock_ctx = MagicMock()

            # 从子线程触发同步回调（模拟 lark SDK 在其回调线程中调用）
            errors: List[Exception] = []

            def trigger():
                try:
                    adapter._handle_message_event(mock_ctx, mock_event)
                except Exception as e:
                    errors.append(e)

            t = threading.Thread(target=trigger)
            t.start()
            t.join(timeout=5)

            assert not errors, f"回调抛异常: {errors}"
            assert called.wait(timeout=3), "callback 未被调用"
            assert len(loops) > 0, "callback 未记录 loop"
            assert loops[0] is main_loop, (
                "callback 未在主 loop 上运行（事件被调度到错误 loop）- "
                "跨线程事件循环 bug 未修复"
            )
        finally:
            _stop_main_loop(main_loop, loop_thread)

    def test_has_main_loop_attribute(self):
        """RED: 修复后 FeishuAdapter 应有 _main_loop 属性（在 __init__ 中初始化为 None）"""
        adapter = FeishuAdapter(ChannelConfig(channel_type="feishu"))
        assert hasattr(adapter, "_main_loop"), (
            "FeishuAdapter 缺少 _main_loop 属性 - "
            "应在 __init__ 中初始化 self._main_loop = None"
        )
        assert adapter._main_loop is None, (
            "_main_loop 初始值应为 None（在 connect() 中才捕获主 loop 引用）"
        )


class TestDingTalkEventLoopSafety:
    """P0-5: DingTalkAdapter 跨线程事件循环安全"""

    def test_callback_schedules_to_main_loop(self):
        """RED: dingtalk 同步回调应将事件调度到主 loop"""
        adapter = DingTalkAdapter(ChannelConfig(channel_type="dingtalk"))
        called = threading.Event()
        loops: List[asyncio.AbstractEventLoop] = []
        adapter.set_event_callback(_make_callback_func(called, loops))

        main_loop, loop_thread = _start_main_loop()
        adapter._main_loop = main_loop

        try:
            time.sleep(0.15)

            # 构造 mock data（钉钉 SDK 的回调数据结构）
            mock_data = {
                "msgId": "msg_123",
                "senderId": "user_1",
                "senderNick": "TestUser",
                "conversationId": "chat_1",
                "msgtype": "text",
                "conversationType": "1",
                "text": {"content": "hello"},
                "sessionWebhook": "https://oapi.dingtalk.com/robot/sendBySession?session=xxx",
            }

            errors: List[Exception] = []

            def trigger():
                try:
                    adapter._handle_bot_message(mock_data)
                except Exception as e:
                    errors.append(e)

            t = threading.Thread(target=trigger)
            t.start()
            t.join(timeout=5)

            assert not errors, f"回调抛异常: {errors}"
            assert called.wait(timeout=3), "callback 未被调用"
            assert len(loops) > 0, "callback 未记录 loop"
            assert loops[0] is main_loop, (
                "callback 未在主 loop 上运行 - 跨线程事件循环 bug 未修复"
            )
        finally:
            _stop_main_loop(main_loop, loop_thread)

    def test_has_main_loop_attribute(self):
        """RED: 修复后 DingTalkAdapter 应有 _main_loop 属性"""
        adapter = DingTalkAdapter(ChannelConfig(channel_type="dingtalk"))
        assert hasattr(adapter, "_main_loop"), (
            "DingTalkAdapter 缺少 _main_loop 属性"
        )
        assert adapter._main_loop is None


class TestWeComEventLoopSafety:
    """P0-6: WeComAdapter 跨线程事件循环安全"""

    def test_callback_schedules_to_main_loop(self):
        """RED: wecom 同步回调应将事件调度到主 loop"""
        # 不设置 callback_token，跳过签名验证
        adapter = WeComAdapter(
            ChannelConfig(channel_type="wecom", webhook_token="")
        )
        called = threading.Event()
        loops: List[asyncio.AbstractEventLoop] = []
        adapter.set_event_callback(_make_callback_func(called, loops))

        main_loop, loop_thread = _start_main_loop()
        adapter._main_loop = main_loop

        try:
            time.sleep(0.15)

            # 构造 XML 数据（企业微信回调格式）
            xml_data = (
                "<xml>"
                "<ToUserName><![CDATA[corp]]></ToUserName>"
                "<FromUserName><![CDATA[user_1]]></FromUserName>"
                "<CreateTime>1234567890</CreateTime>"
                "<MsgType><![CDATA[text]]></MsgType>"
                "<Content><![CDATA[hello]]></Content>"
                "<MsgId>msg_123</MsgId>"
                "</xml>"
            )

            errors: List[Exception] = []

            def trigger():
                try:
                    adapter.handle_callback("", "1234567890", "nonce", xml_data)
                except Exception as e:
                    errors.append(e)

            t = threading.Thread(target=trigger)
            t.start()
            t.join(timeout=5)

            assert not errors, f"回调抛异常: {errors}"
            assert called.wait(timeout=3), "callback 未被调用"
            assert len(loops) > 0, "callback 未记录 loop"
            assert loops[0] is main_loop, (
                "callback 未在主 loop 上运行 - 跨线程事件循环 bug 未修复"
            )
        finally:
            _stop_main_loop(main_loop, loop_thread)

    def test_has_main_loop_attribute(self):
        """RED: 修复后 WeComAdapter 应有 _main_loop 属性"""
        adapter = WeComAdapter(
            ChannelConfig(channel_type="wecom", webhook_token="")
        )
        assert hasattr(adapter, "_main_loop"), (
            "WeComAdapter 缺少 _main_loop 属性"
        )
        assert adapter._main_loop is None


# ============================================================
# 辅助函数
# ============================================================


def _make_callback_func(
    called: threading.Event, loops: List[asyncio.AbstractEventLoop]
):
    """构造 callback 函数，记录运行的 loop 并 set event"""

    async def callback(event_type, message):
        loops.append(asyncio.get_running_loop())
        called.set()

    return callback
