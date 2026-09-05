# -*- coding: utf-8 -*-
import sys, io, json, urllib.request
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
BASE = 'http://localhost:9527/api/v1'
def req(method, path, token=None, data=None, headers=None):
    r = urllib.request.Request(BASE+path, data=data, headers=dict(headers or {}), method=method)
    if token: r.add_header('Authorization', 'Bearer '+token)
    with urllib.request.urlopen(r, timeout=60) as resp: return json.loads(resp.read())
r = req('POST', '/auth/login', headers={'Content-Type':'application/json'},
        data=json.dumps({'username':'admin','password':'Admin23@'}).encode())
token = r['access_token']
r = req('GET', '/knowledge?agent_id=default&scope=all&page=1&page_size=60', token=token)
items = r if isinstance(r, list) else (r.get('data') or [])
print('total in list:', len(items))
for it in items:
    print(' -', it.get('title'), '|', it.get('source'), '| created:', it.get('created_at'))
