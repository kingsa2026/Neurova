"""临时探针：启动后端并探测 /api/v1/agents 与 /api/agents 路由。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import uvicorn, threading, time, requests
from neurova.api.app import create_app

app = create_app()

def run():
    uvicorn.run(app, host='127.0.0.1', port=8099, log_level='error')

t = threading.Thread(target=run, daemon=True)
t.start()
time.sleep(12)

# 测试 /api/v1/agents
try:
    r = requests.get('http://127.0.0.1:8099/api/v1/agents', timeout=5)
    print('/api/v1/agents status:', r.status_code)
    print('body:', r.text[:400])
except Exception as e:
    print('ERR /api/v1/agents:', e)

# 测试 /api/agents
try:
    r2 = requests.get('http://127.0.0.1:8099/api/agents', timeout=5)
    print('/api/agents status:', r2.status_code)
except Exception as e:
    print('ERR /api/agents:', e)
