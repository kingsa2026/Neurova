# -*- coding: utf-8 -*-
"""测试内假 ACP agent：真 stdio 子进程，按 FAKE_ACP_MODE 模拟不同行为。

模式：
  ok               正常握手（protocolVersion "1"），支持 ping 回显
  bad_version      握手返回 protocolVersion "9"
  no_version       握手返回缺 protocolVersion
  crash_after_init 握手后立即退出（模拟进程崩溃/EOF）
  oversize         握手后推送一行超过 1MB 的帧
  push_notify      握手后主动推送一条 session/update 通知
  acp_flow         完整会话流：session/new → prompt 期推 content/thought chunk → end_of_turn
  acp_cancelled    prompt 直接回 cancelled
  acp_permission   prompt 期发 session/request_permission，按客户端裁决继续/中止
"""
import json
import os
import sys


def send(out, obj):
    out.write((json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))
    out.flush()


def main():
    mode = os.environ.get("FAKE_ACP_MODE", "ok")
    out = sys.stdout.buffer
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line.decode("utf-8"))
        except Exception:
            continue
        msg_id = msg.get("id")
        method = msg.get("method", "")
        params = msg.get("params") or {}

        if method == "initialize":
            if mode == "bad_version":
                result = {"protocolVersion": "9", "serverCapabilities": {}}
            elif mode == "no_version":
                result = {"serverCapabilities": {}}
            else:
                result = {"protocolVersion": "1", "serverCapabilities": {"tools": {}}}
            send(out, {"jsonrpc": "2.0", "id": msg_id, "result": result})
            if mode == "crash_after_init":
                sys.exit(3)
            if mode == "oversize":
                out.write(b"x" * 1_050_000 + b"\n")
                out.flush()
            if mode == "push_notify":
                send(out, {"jsonrpc": "2.0", "method": "session/update", "params": {"update": {"sessionUpdate": "agent_message_chunk", "content": {"text": "你好 Neuacp"}}}})
            continue

        if method == "ping":
            send(out, {"jsonrpc": "2.0", "id": msg_id, "result": {"pong": True, "echo": params}})
            continue

        if method == "session/new":
            send(out, {"jsonrpc": "2.0", "id": msg_id, "result": {"sessionId": "sess-1"}})
            continue

        if method == "session/prompt":
            if mode in ("acp_flow", "acp_permission"):
                send(out, {"jsonrpc": "2.0", "method": "session/update", "params": {"sessionId": "sess-1", "update": {"sessionUpdate": "agent_message_chunk", "content": {"text": "你好 Neuacp"}}}})
                send(out, {"jsonrpc": "2.0", "method": "session/update", "params": {"sessionId": "sess-1", "update": {"sessionUpdate": "agent_thought_chunk", "content": {"text": "思考中"}}}})
                if mode == "acp_permission":
                    send(out, {"jsonrpc": "2.0", "id": 9001, "method": "session/request_permission", "params": {"toolCall": {"title": "写入 src/app.py"}, "options": [{"kind": "allow"}]}})
                    resp_line = sys.stdin.buffer.readline()
                    try:
                        resp = json.loads(resp_line.decode("utf-8"))
                    except Exception:
                        resp = {}
                    choice = ((resp.get("result") or {}).get("outcome") or {}).get("choice")
                    if choice != "allow":
                        send(out, {"jsonrpc": "2.0", "method": "session/update", "params": {"sessionId": "sess-1", "update": {"sessionUpdate": "agent_message_chunk", "content": {"text": "权限被拒，任务中止"}}}})
                        send(out, {"jsonrpc": "2.0", "id": msg_id, "result": {"stopReason": "end_of_turn"}})
                        continue
                send(out, {"jsonrpc": "2.0", "id": msg_id, "result": {"stopReason": "end_of_turn"}})
                continue
            if mode == "acp_cancelled":
                send(out, {"jsonrpc": "2.0", "id": msg_id, "result": {"stopReason": "cancelled"}})
                continue
            send(out, {"jsonrpc": "2.0", "id": msg_id, "result": {"stopReason": "end_of_turn"}})
            continue

        send(out, {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601, "message": "method not found"}})
        out.flush()


if __name__ == "__main__":
    main()
