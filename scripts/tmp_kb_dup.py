# -*- coding: utf-8 -*-
import sys, io, json, urllib.request, uuid, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
BASE = 'http://localhost:9527/api/v1'
def req(method, path, token=None, data=None, headers=None):
    r = urllib.request.Request(BASE+path, data=data, headers=dict(headers or {}), method=method)
    if token: r.add_header('Authorization', 'Bearer '+token)
    with urllib.request.urlopen(r, timeout=60) as resp: return json.loads(resp.read())
r = req('POST', '/auth/login', headers={'Content-Type':'application/json'},
        data=json.dumps({'username':'admin','password':'Admin23@'}).encode())
token = r['access_token']
def imp(filename, content):
    b = '----kb' + uuid.uuid4().hex[:8]
    part = (f'--{b}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            f'Content-Type: application/octet-stream\r\n\r\n').encode() + content + f'\r\n--{b}--\r\n'.encode()
    return req('POST', '/knowledge/import?agent_id=default', token=token, data=part,
               headers={'Content-Type': f'multipart/form-data; boundary={b}'})
tag = uuid.uuid4().hex[:6]
for name in (f'd1_{tag}.md', f'd2_{tag}.md'):
    rr = imp(name, f'dup check {name}'.encode())
    print(name, '-> code:', rr['code'], 'items:', len(rr['data']['items']), 'id:', rr['data']['items'][0].get('knowledge_id') if rr['data']['items'] else None)
r = req('GET', '/knowledge?agent_id=default&scope=all&page=1&page_size=60', token=token)
items = r if isinstance(r, list) else (r.get('data') or [])
hits = [it for it in items if tag in (it.get('source') or '')]
print('found in list:', len(hits), [h.get('source') for h in hits])
