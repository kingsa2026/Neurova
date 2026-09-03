import requests
import json

BASE = "http://localhost:9527/api/v1"
agent_id = "agent_001"

endpoints = [
    f"/agents/{agent_id}/metacognition",
    f"/agents/{agent_id}/metacognition/stats",
    f"/agents/{agent_id}/reflection?limit=2",
    f"/agents/{agent_id}/reflection/stats",
    f"/agents/{agent_id}/knowledge-graph",
    f"/agents/{agent_id}/growth",
]

print("=== 测试新端点 ===")
for path in endpoints:
    try:
        r = requests.get(BASE + path, timeout=8)
        d = r.json()
        code = d.get("code", "?")
        msg = d.get("message", "")
        data_keys = list(d.get("data", {}).keys())[:4] if d.get("data") else []
        print(f"[{r.status_code}] {path}")
        print(f"    code={code}, keys={data_keys}, msg={msg[:50]}")
    except Exception as e:
        print(f"[FAIL] {path}: {e}")

print("\n=== 测试 POST 端点 ===")
# 测试创建元认知记录
try:
    r = requests.post(
        f"{BASE}/agents/{agent_id}/metacognition",
        json={"thought_type": "analysis", "content": "测试分析"},
        timeout=8
    )
    print(f"POST metacognition: [{r.status_code}] {r.json().get('message', '')[:50]}")
except Exception as e:
    print(f"POST metacognition FAIL: {e}")
