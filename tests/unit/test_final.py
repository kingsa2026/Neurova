import requests
import os

BASE = "http://localhost:9527/api/v1"

# 找一个存在的 agent
agent_dir = r"e:\项目\Neurova\neurova\data"
agents = []
if os.path.exists(agent_dir):
    agents = [d for d in os.listdir(agent_dir) if os.path.isdir(os.path.join(agent_dir, d))]
print("可用 agents:", agents[:3])

if agents:
    aid = agents[0]
    print(f"\n使用 agent: {aid}")
    for path in [
        f"/agents/{aid}/metacognition",
        f"/agents/{aid}/metacognition/stats",
        f"/agents/{aid}/reflection",
        f"/agents/{aid}/reflection/stats",
        f"/memories/meta/health",
        f"/memories/reflection/logs",
    ]:
        try:
            r = requests.get(BASE + path, timeout=8)
            d = r.json()
            print(f"[{r.status_code}] {path}")
            print(f"    code={d.get('code')}, msg={d.get('message', '')[:40]}")
        except Exception as e:
            print(f"[FAIL] {path}: {e}")
else:
    print("没有可用 agent，测试 /memories 端点")
    for path in ["/memories/meta/health", "/memories/reflection/logs"]:
        try:
            r = requests.get(BASE + path, timeout=8)
            d = r.json()
            print(f"[{r.status_code}] {path}: code={d.get('code')}")
        except Exception as e:
            print(f"[FAIL] {path}: {e}")
