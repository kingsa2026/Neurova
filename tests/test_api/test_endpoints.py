"""验证新端点的测试脚本"""
import requests
import json

base = "http://localhost:9527/api/v1"
endpoints = [
    "/agents/agent_001/metacognition?limit=2",
    "/agents/agent_001/reflection?limit=2",
    "/agents/agent_001/knowledge-graph",
    "/agents/agent_001/growth",
]

print("=" * 60)
print("验证记忆与认知模块 API 端点")
print("=" * 60)

for path in endpoints:
    url = base + path
    try:
        r = requests.get(url, timeout=8)
        d = r.json()
        code = d.get("code", "?")
        data_keys = list(d.get("data", {}).keys())[:4]
        print(f"[OK] {path.split('?')[0]}")
        print(f"      code={code}, data_keys={data_keys}")
    except requests.exceptions.ConnectionError:
        print(f"[FAIL] {path.split('?')[0]} - 连接被拒绝（后端未启动？）")
    except Exception as e:
        print(f"[FAIL] {path.split('?')[0]} - {e}")

print("=" * 60)
print("验证完成")
