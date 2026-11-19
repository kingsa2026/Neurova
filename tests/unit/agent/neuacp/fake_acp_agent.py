# -*- coding: utf-8 -*-
"""测试内假 ACP agent：真 stdio 子进程，按 FAKE_ACP_MODE 模拟不同行为。

模式：
  ok               正常握手（protocolVersion "1"），支持 ping 回显
  bad_version      握手返回 protocolVersion "9"
  no_version       握手返回缺 protocolVersion
  crash_after_init 握手后立即退出（模拟进程崩溃/EOF）
  oversize         握手后推送一行超过 1MB 的帧
  push_notify      握手后主动推送一条 session/update 通知
"""
import json
import os
import sys


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
            out.write((json.dumps({"jsonrpc": "2.0", "id": msg_id, "result": result}, ensure_ascii=False) + "\n").encode("utf-8"))
            out.flush()
            if mode == "crash_after_init":
                sys.exit(3)
            if mode == "oversize":
                out.write(b"x" * 1_050_000 + b"\n")
                out.flush()
            if mode == "push_notify":
                note = {"jsonrpc": "2.0", "method": "session/update", "params": {"update": {"sessionUpdate": "agent_message_chunk", "content": {"text": "你好 Neuacp"}}}}
                out.write((json.dumps(note, ensure_ascii=False) + "\n").encode("utf-8"))
                out.flush()
            continue

        if method == "ping":
            out.write((json.dumps({"jsonrpc": "2.0", "id": msg_id, "result": {"pong": True, "echo": params}}, ensure_ascii=False) + "\n").encode("utf-8"))
            out.flush()
            continue

        out.write((json.dumps({"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601, "message": "method not found"}}, ensure_ascii=False) + "\n").encode("utf-8"))
        out.flush()


if __name__ == "__main__":
    main()
