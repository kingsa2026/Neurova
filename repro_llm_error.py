"""通过 console chat 端点复现错误 (无需认证)"""
import sys
import os
import json
import urllib.request
import urllib.error

sys.path.insert(0, os.path.abspath('.'))

def call_api(path, method="GET", body=None):
    url = f"http://localhost:9527{path}"
    headers = {}
    if body:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    else:
        data = None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()
    except Exception as e:
        return -1, str(e)

# 调用 console chat API (无需认证)
print("[REPRO] === Calling console chat (no auth) ===")
status, body = call_api("/api/console/chat", method="POST", body={
    "message": "你好测试",
    "agent_id": "default",
    "session_id": "test_repro_2",
    "stream": False
})
print(f"[REPRO] status={status}")
print(f"[REPRO] body={body[:800] if body else ''}")
