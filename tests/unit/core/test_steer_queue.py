# -*- coding: utf-8 -*-
"""P1-9 steer 插话：队列语义 + agent loop 排空接线 + API 契约。"""
import pytest


@pytest.fixture()
def queue():
    from neurova.core.steer_queue import SteerQueue, reset_steer_queue

    q = SteerQueue()
    yield q
    from neurova.core import steer_queue as sq

    sq.reset_steer_queue()


class TestSteerQueue:
    def test_push_drain_fifo(self, queue):
        assert queue.push("s1", "先看配置") is True
        assert queue.push("s1", "再看日志") is True
        assert queue.drain("s1") == ["先看配置", "再看日志"]
        assert queue.drain("s1") == []

    def test_empty_and_missing(self, queue):
        assert queue.push("s1", "  ") is False
        assert queue.push("", "x") is False
        assert queue.drain("nope") == []
        assert queue.pending("s1") == 0

    def test_session_isolation(self, queue):
        queue.push("s1", "a")
        queue.push("s2", "b")
        assert queue.drain("s1") == ["a"]
        assert queue.drain("s2") == ["b"]

    def test_ttl_expiry(self, queue):
        queue.ttl_seconds = 0.01
        queue.push("s1", "old")
        import time

        time.sleep(0.05)
        assert queue.drain("s1") == []

    def test_max_per_session(self, queue):
        queue.max_per_session = 2
        assert queue.push("s1", "a") is True
        assert queue.push("s1", "b") is True
        assert queue.push("s1", "c") is False


class TestLoopDrainIntegration:
    @pytest.mark.asyncio
    async def test_handle_tool_calls_appends_steer(self, queue, monkeypatch):
        """工具轮间隙排空插话：以 user 角色并入回传消息。"""
        from unittest.mock import MagicMock

        from neurova.agent.loops.base import BaseAgentLoop
        from neurova.core import steer_queue as sq

        # loop 走单例工厂 → 把夹具实例注入模块级单例
        monkeypatch.setattr(sq, "_QUEUE", queue)

        class DummyLoop(BaseAgentLoop):
            async def predict_step(self, messages, tools=None, **kwargs):
                return None

            async def _execute_tool_call_worker(self, tool_call):
                msg = {"role": "tool", "tool_call_id": "c1", "name": "t", "content": "ok"}
                return msg, []

        agent = MagicMock()
        agent.current_session_id = "s-steer"
        loop = DummyLoop(agent)
        queue.push("s-steer", "补充：顺便看下超时设置")

        tool_call = {"id": "c1", "function": {"name": "t", "arguments": "{}"}}
        new_messages = await loop.handle_tool_calls([tool_call], [])
        steer_msgs = [m for m in new_messages if m.get("role") == "user"]
        assert steer_msgs and "补充：顺便看下超时设置" in steer_msgs[0]["content"]
        assert queue.pending("s-steer") == 0


class TestSteerEndpoint:
    def test_steer_endpoint_registered(self):
        from neurova.api.app import create_app

        app = create_app(enable_memory=False, enable_channels=False)
        paths = {getattr(r, "path", "") for r in app.routes}
        assert "/api/v1/console/chat/steer" in paths


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
