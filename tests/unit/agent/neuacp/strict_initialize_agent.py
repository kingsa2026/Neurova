# -*- coding: utf-8 -*-
"""严格 initialize 校验 agent：按 ACP 规范校验 protocolVersion 必须是整数
（uint16），类型不符回 -32602 Invalid params——复刻真实 CLI 的校验行为
（假 agent 不校验类型，导致本仓客户端发字符串 "1" 从未暴露互操作缺陷）。
"""
import json
import sys


def send(out, obj):
    out.write((json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))
    out.flush()


def main():
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
            pv = params.get("protocolVersion")
            # ACP schema：ProtocolVersion = integer (uint16)。字符串一律 -32602。
            if not isinstance(pv, int) or isinstance(pv, bool):
                send(out, {"jsonrpc": "2.0", "id": msg_id, "error": {
                    "code": -32602, "message": "Invalid params: protocolVersion must be integer"}})
                continue
            send(out, {"jsonrpc": "2.0", "id": msg_id, "result": {
                "protocolVersion": pv, "serverCapabilities": {}}})
        elif msg_id is not None:
            send(out, {"jsonrpc": "2.0", "id": msg_id, "result": {}})


if __name__ == "__main__":
    main()
