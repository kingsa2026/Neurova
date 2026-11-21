# -*- coding: utf-8 -*-
"""M9：ACP 客户端请求处理器契约——泵线程不阻塞、应答可稍后补发。

旧契约 handler(params)->dict 在泵线程同步执行：人审等待（默认 300s）期间
泵线程无法派发任何后续帧（流式 chunk/心跳/崩溃通知全部滞留）。新契约
handler(params, respond)->None：需要等待的处理器先返回，裁决完成后经
respond（线程安全）补发应答帧（JSON-RPC 按 id 配对，允许晚于其它帧）。
"""
import json
import threading

import pytest

from neurova.agent.neuacp.acp_client import NeuacpClient


def _client():
    """未启动子进程的最小 client（仅测 _dispatch 契约）。"""
    client = NeuacpClient.__new__(NeuacpClient)
    client._lock = threading.RLock()
    client._request_handlers = {}
    client._waiters = {}
    sent = []
    client._sendFrame = lambda message: sent.append(message)
    return client, sent


class TestDispatchDeferredResponse:
    def test_deferred_response_completes_after_handler_returns(self):
        client, sent = _client()
        entered = threading.Event()
        release = threading.Event()

        def handler(params, respond):
            entered.set()
            # 不阻塞派发线程：先返回，稍后由独立线程补发应答（同执行体工作线程形态）
            def later():
                release.wait(5)
                respond({"outcome": {"choice": "deny"}})
            threading.Thread(target=later, daemon=True).start()

        client.setRequestHandler("session/request_permission", handler)
        msg = {"jsonrpc": "2.0", "id": 7, "method": "session/request_permission", "params": {}}
        worker = threading.Thread(target=client._dispatch, args=(msg,))
        worker.start()
        assert entered.wait(5), "处理器未被调用"
        worker.join(timeout=2)
        assert not worker.is_alive(), "处理器返回后派发即完成（应答可稍后补发，M9）"
        assert not sent, "应答尚未补发不应出现帧"
        release.set()
        deadline = threading.Event()
        for _ in range(100):
            if sent:
                break
            deadline.wait(0.05)
        assert sent and sent[-1]["id"] == 7
        assert sent[-1]["result"] == {"outcome": {"choice": "deny"}}

    def test_handler_exception_sends_error_frame(self):
        client, sent = _client()

        def boom(params, respond):
            raise RuntimeError("裁决装配失败")

        client.setRequestHandler("session/request_permission", boom)
        client._dispatch({"jsonrpc": "2.0", "id": 9, "method": "session/request_permission", "params": {}})
        assert sent and sent[-1]["id"] == 9
        assert sent[-1]["error"]["code"] == -32000
        assert "裁决装配失败" in sent[-1]["error"]["message"]

    def test_response_frame_shape_is_jsonrpc(self):
        client, sent = _client()
        client.setRequestHandler("session/request_permission",
                                 lambda params, respond: respond({"outcome": {"choice": "allow"}}))
        client._dispatch({"jsonrpc": "2.0", "id": 11, "method": "session/request_permission", "params": {}})
        assert sent[-1] == {"jsonrpc": "2.0", "id": 11,
                            "result": {"outcome": {"choice": "allow"}}}
