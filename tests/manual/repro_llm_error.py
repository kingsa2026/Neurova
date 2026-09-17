"""通过 console chat 端点复现错误 (无需认证)"""
import sys
import os
import json
import urllib.request

if os.path.abspath('.') not in sys.path:
    sys.path.insert(0, os.path.abspath('.'))


def call_api(method="POST", body=None):
    headers = {}
    data = None
    if body:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    try:
        with urllib.request.urlopen(
            "http://localhost:9527/api/console/chat", data=data, headers=headers, method=method, timeout=60
        ) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()
    except Exception as e:
        return -1, str(e)

# 调用 console chat API (无需认证)
print("[REPRO] === Calling console chat (no auth) ===")
status, body = call_api(method="POST", body={
    "message": "你好测试",
    "agent_id": "default",
    "session_id": "test_repro_2",
    "stream": False
})
print(f"[REPRO] status={status}")
print(f"[REPRO] body={body[:800] if body else ''}")

