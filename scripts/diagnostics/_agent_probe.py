"""临时探针：启动后端(9527)并探测 agents 路由。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import uvicorn, threading, time, requests
from neurova.api.app import create_app

app = create_app()
def run():
    uvicorn.run(app, host='127.0.0.1', port=9527, log_level='error')
t = threading.Thread(target=run, daemon=True)
t.start()
time.sleep(15)

try:
    r = requests.get('http://127.0.0.1:9527/api/v1/agents', timeout=5)
    print(f'GET /api/v1/agents: {r.status_code}')
    if r.status_code == 200:
        print('   body:', r.text[:300])
except Exception as e:
    print(f'ERR /api/v1/agents: {e}')

try:
    r = requests.get('http://127.0.0.1:9527/api/agents', timeout=5)
    print(f'GET /api/agents: {r.status_code}')
    if r.status_code == 200:
        print('   body:', r.text[:300])
except Exception as e:
    print(f'ERR /api/agents: {e}')
