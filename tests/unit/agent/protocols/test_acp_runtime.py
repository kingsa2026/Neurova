"""ACP 运行时（消息中枢）单元测试。

对齐升级方案 P1-2.1：基于已有的 AgentMessage 信封，落地运行时路由——
注册/注销 agent、消息派发、未知接收者进 DLQ、request/response 关联、trace_id 贯穿。
"""

import asyncio
import time
import unittest

from neurova.agent.protocols.acp_runtime import (
    ACPRuntime,
    DeliveryStatus,
    get_acp_runtime,
    reset_acp_runtime,
)
from neurova.agent.protocols.message_protocol import (
    AgentMessage,
    DeadLetterReason,
    MessageType,
)


def _make_msg(sender="a1", receiver="receiver", action="greet", trace_id=None, **kw):
    return AgentMessage(
        sender_id=sender,
        receiver_id=receiver,
        action=action,
        type=MessageType.REQUEST,
        trace_id=trace_id,
        **kw,
    )


class TestRegistration(unittest.TestCase):
    """agent 注册与注销。"""

    def setUp(self):
        self.rt = ACPRuntime()

    def test_register_and_list(self):
        self.rt.register_agent("agent-x", lambda m: None)
        self.assertIn("agent-x", self.rt.list_agents())

    def test_unregister(self):
        self.rt.register_agent("agent-x", lambda m: None)
        self.assertTrue(self.rt.unregister_agent("agent-x"))
        self.assertNotIn("agent-x", self.rt.list_agents())

    def test_unregister_unknown_returns_false(self):
        self.assertFalse(self.rt.unregister_agent("nobody"))

    def test_register_rejects_empty_id(self):
        with self.assertRaises(ValueError):
            self.rt.register_agent("", lambda m: None)

    def test_duplicate_registration_replaces_handler(self):
        calls = []
        self.rt.register_agent("x", lambda m: calls.append("old"))
        self.rt.register_agent("x", lambda m: calls.append("new"))
        self.rt.send(_make_msg(receiver="x"))
        self.assertEqual(calls, ["new"])


class TestDelivery(unittest.TestCase):
    """消息派发核心语义。"""

    def setUp(self):
        self.rt = ACPRuntime()
        self.received = []
        self.rt.register_agent("receiver", self.received.append)

    def test_send_to_registered_agent_invokes_handler(self):
        msg = _make_msg()
        result = self.rt.send(msg)
        self.assertEqual(result.status, DeliveryStatus.DELIVERED)
        self.assertEqual(len(self.received), 1)
        self.assertEqual(self.received[0].message_id, msg.message_id)

    def test_send_to_unknown_goes_to_dead_letter(self):
        result = self.rt.send(_make_msg(receiver="ghost"))
        self.assertEqual(result.status, DeliveryStatus.DEAD_LETTER)
        self.assertEqual(result.reason, DeadLetterReason.RECIPIENT_NOT_FOUND)

    def test_expired_message_not_delivered(self):
        msg = _make_msg(expires_at=time.time() - 10)
        result = self.rt.send(msg)
        self.assertEqual(result.status, DeliveryStatus.EXPIRED)
        self.assertEqual(len(self.received), 0)

    def test_handler_exception_reports_failed_not_crash(self):
        def bad_handler(m):
            raise RuntimeError("handler boom")

        self.rt.register_agent("bad", bad_handler)
        result = self.rt.send(_make_msg(receiver="bad"))
        self.assertEqual(result.status, DeliveryStatus.FAILED)
        self.assertIn("boom", result.error or "")

    def test_trace_id_preserved_through_delivery(self):
        seen = {}
        self.rt.register_agent("t", lambda m: seen.update(trace=m.trace_id))
        self.rt.send(_make_msg(receiver="t", trace_id="trace-123"))
        self.assertEqual(seen["trace"], "trace-123")


class TestRequestResponse(unittest.IsolatedAsyncioTestCase):
    """关联请求-响应。"""

    async def asyncSetUp(self):
        self.rt = ACPRuntime()

    async def test_request_gets_correlated_response(self):
        """约定：handler 返回 AgentMessage 即视为响应，按 correlation_id 回路由。"""

        async def responder(msg: AgentMessage) -> AgentMessage:
            return msg.create_response(success=True, result={"answer": 42})

        self.rt.register_agent("calc", responder)

        req = _make_msg(sender="caller", receiver="calc")
        reply = await self.rt.request(req, timeout=2.0)
        self.assertIsNotNone(reply)
        self.assertEqual(reply.type, MessageType.RESPONSE)
        # create_response 约定: result 直接放入 data
        self.assertEqual(reply.data.get("answer"), 42)
        # 响应必须通过 correlation_id 关联回原请求
        self.assertEqual(reply.correlation_id, req.message_id)

    async def test_request_timeout_returns_none(self):
        self.rt.register_agent("silent", lambda m: None)  # 从不回复
        reply = await self.rt.request(_make_msg(receiver="silent"), timeout=0.2)
        self.assertIsNone(reply)

    async def test_request_to_unknown_is_none(self):
        reply = await self.rt.request(_make_msg(receiver="ghost"), timeout=0.2)
        self.assertIsNone(reply)


class TestStatsAndSingleton(unittest.TestCase):
    """统计与单例生命周期（AGENTS.md 规范）。"""

    def setUp(self):
        reset_acp_runtime()

    def tearDown(self):
        reset_acp_runtime()

    def test_stats_counts(self):
        rt = get_acp_runtime()
        rt.register_agent("a", lambda m: None)
        rt.send(AgentMessage(sender_id="sys", receiver_id="a", action="hi"))
        rt.send(AgentMessage(sender_id="sys", receiver_id="void", action="hi"))
        stats = rt.get_stats()
        self.assertGreaterEqual(stats["sent"], 2)
        self.assertGreaterEqual(stats["delivered"], 1)
        self.assertGreaterEqual(stats["dead_letter"], 1)

    def test_singleton_identity_and_reset(self):
        first = get_acp_runtime()
        again = get_acp_runtime()
        self.assertIs(first, again)
        reset_acp_runtime()
        self.assertIsNot(first, get_acp_runtime())


if __name__ == "__main__":
    unittest.main()
