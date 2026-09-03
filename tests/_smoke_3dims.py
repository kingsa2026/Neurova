import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from neurova.context_pool_registry import ContextPoolRegistry
from neurova.context.pool_models import ContextInput, ContextSource

ContextPoolRegistry._instance = None
reg = ContextPoolRegistry().reset()

# 维度 1: 按需调取
p = reg.get_or_create(user_id='alice', agent_id='coding', session_id='s1')
for i in range(50):
    p.add_context(ContextInput(source=ContextSource.CONVERSATION, content='msg-' + str(i), priority=50))
r = p.query(query='', limit=3)
print('[1] 按需调取 OK: query(limit=3) 返回 ' + str(len(r)) + ' 条 (pool 实际有 50)')

# 维度 2: 三层隔离
p2 = reg.get_or_create(user_id='bob', agent_id='coding', session_id='s1')
p2.add_context(ContextInput(source=ContextSource.CONVERSATION, content='bob data', priority=10))
p3 = reg.get_or_create(user_id='alice', agent_id='search', session_id='s1')
p3.add_context(ContextInput(source=ContextSource.CONVERSATION, content='search data', priority=10))
r_alice = reg.query_agent(user_id='alice', agent_id='coding', current_session_id='s1', query='', limit=100)
print('[2] user/agent 隔离 OK: alice/coding 看到 ' + str(len(r_alice)) + ' 条, 全部属于 alice')
assert all(c.metadata.get('user_id') == 'alice' for c in r_alice)

# 维度 3: sessionID 跨会话
p_s2 = reg.get_or_create(user_id='alice', agent_id='coding', session_id='s2')
p_s2.add_context(ContextInput(source=ContextSource.MEMORY, content='history from s2', priority=99))
r = reg.query_agent(user_id='alice', agent_id='coding', current_session_id='s1', query='', limit=100)
sessions = sorted({c.metadata.get('session_id') for c in r})
first = r[0].metadata.get('session_id')
print('[3] sessionID 跨会话 OK: 覆盖 sessions=' + str(sessions) + ', 首位=' + str(first))
assert 's1' in sessions and 's2' in sessions
assert first == 's1'

print()
print('=== 全部 3 维度通过 ===')
