# Bug Fix: GET /api/v1/chat/sessions?agent_id= 返回 404

## 问题

前端调用 `GET /api/v1/chat/sessions?agent_id=` 返回 404 Not Found。

前端 `ChatPage.vue` 的 `loadSessions()` 函数构造 URL：
```javascript
const res = await api.get(`/chat/sessions?agent_id=${agentId.value}`)
```

当 `agentId.value` 为空字符串时，发送请求 `?agent_id=`（空值）。

## 根因分析

### 第一层：endpoint 参数处理

`chat.py` 的 `get_chat_sessions` 端点：
```python
@router.get("/sessions")
async def get_chat_sessions(
    agent_id: str = Query(default="default"),  # 默认值仅在参数完全缺失时生效
    ...
):
```

当请求 `?agent_id=` 时，FastAPI 将 `agent_id` 设为空字符串 `""`（不是缺省值 `"default"`）。

### 第二层：Agent 实例查找

```python
agent = _get_agent(agent_id)  # agent_id = ""
# → get_agent_instance("")
# → agents.get("")  →  None  (没有空字符串 key)
```

`get_agent_instance("")` 返回 `None` → 404。

### 为什么 _app_state 中没有 "" key？

`app.py` 初始化 agents 字典时使用 agent 配置中的 `id` 作 key，这些 ID 都是非空字符串。
空字符串 `""` 永远不会成为 agents 字典的 key。

## 修复

### 文件：`neurova/api/endpoints/__init__.py` (第 65-73 行)

```python
def get_agent_instance(agent_id: str = "default"):
    """获取 Agent 实例"""
    if _app_state:
        agents = _app_state.get("agents", {})
        # 如果 agent_id 为空，使用默认 agent
        if not agent_id:
            agent_id = "default"
        return agents.get(agent_id)
    return None
```

**关键**：使用 `if not agent_id` 而不是 `if agent_id is None`，这样空字符串 `""`、`None`、`0` 等 falsy 值都会被映射到默认 agent。

## 测试

### 新建：`tests/unit/test_chat_sessions_empty_agent_id.py`

7 个测试，分 2 个测试类：

#### TestEmptyAgentId（端点集成测试）
| 测试 | 说明 |
|------|------|
| `test_get_sessions_with_empty_agent_id` | `?agent_id=` → 200 (使用默认 agent) |
| `test_get_sessions_with_no_agent_id` | 无参数 → 200 |
| `test_get_sessions_with_valid_agent_id` | `?agent_id=agent-1` → 200 |
| `test_get_sessions_with_invalid_agent_id` | `?agent_id=invalid` → 404 |

#### TestGetAgentInstance（单元测试）
| 测试 | 说明 |
|------|------|
| `test_get_agent_instance_with_empty_string` | `""` → 默认 agent |
| `test_get_agent_instance_with_none` | `None` → 默认 agent |
| `test_get_agent_instance_with_valid_id` | `"agent-1"` → 对应 agent |

### 测试技术要点

FastAPI `Depends(get_current_user)` 在 import 时绑定，必须用 `app.dependency_overrides` 覆盖，
不能用 `unittest.mock.patch`（patch 只替换模块属性，不会影响 FastAPI 内部的依赖注册表）。

```python
from neurova.api.auth import get_current_user

app.dependency_overrides[get_current_user] = _mock_get_current_user
```

## 验证结果

```
7 passed, 0 failed, 0 linter errors
```

## 影响范围

所有使用 `get_agent_instance()` 的端点都会受益于此修复，包括：
- `/chat/sessions`
- `/chat/history`
- `/memory/*`
- `/growth/*`
- `/sleep/*`
- `/context/*`
- 等 10+ 个端点模块
