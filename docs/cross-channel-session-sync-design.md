# 跨渠道会话同步系统设计

## 1. 需求概述

用户期望实现手机、电脑、消息渠道之间的会话实时同步：

1. **双向同步**：任一渠道发送的消息和 Agent 响应在所有活跃渠道实时显示
2. **完整过程同步**：包括用户输入、Agent 思考、工具调用、命令执行、回复内容
3. **历史共享**：所有渠道都能查看当前会话的完整历史

## 2. 架构设计

### 2.1 核心组件

```
┌─────────────────────────────────────────────────────────────────┐
│                      SessionSyncManager                         │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                   UnifiedSession                         │  │
│  │  - session_id: str                                       │  │
│  │  - conversation_id: str                                  │  │
│  │  - user_id: str                                          │  │
│  │  - agent_id: str                                         │  │
│  │  - history: List[SessionEvent]                           │  │
│  │  - active_channels: Dict[str, ChannelConnection]         │  │
│  │  - created_at: datetime                                  │  │
│  │  - last_activity: datetime                               │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                   SessionEvent                           │  │
│  │  - event_id: str                                         │  │
│  │  - event_type: EventType                                 │  │
│  │  - source_channel: str                                   │  │
│  │  - timestamp: datetime                                   │  │
│  │  - payload: Dict[str, Any]                               │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                   ChannelConnection                      │  │
│  │  - channel_type: str                                     │  │
│  │  - connection_id: str                                    │  │
│  │  - connected_at: datetime                                │  │
│  │  - last_heartbeat: datetime                              │  │
│  │  - send_callback: Callable                               │  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 事件类型

```python
class EventType(str, Enum):
    # 用户输入
    USER_MESSAGE = "user_message"
    
    # Agent 状态
    AGENT_THINKING = "agent_thinking"
    AGENT_TOOL_CALL = "agent_tool_call"
    AGENT_TOOL_RESULT = "agent_tool_result"
    AGENT_COMMAND = "agent_command"
    AGENT_REPLY = "agent_reply"
    AGENT_ERROR = "agent_error"
    
    # 会话状态
    SESSION_CREATED = "session_created"
    SESSION_RESUMED = "session_resumed"
    SESSION_PAUSED = "session_paused"
    SESSION_ENDED = "session_ended"
    
    # 渠道状态
    CHANNEL_CONNECTED = "channel_connected"
    CHANNEL_DISCONNECTED = "channel_disconnected"
```

### 2.3 数据流

```
用户输入 → 渠道适配器 → SessionSyncManager
                              │
                              ├─→ 保存到历史
                              ├─→ 广播到所有活跃渠道
                              └─→ 触发 Agent 处理
                                      │
                                      ├─→ AGENT_THINKING 事件
                                      ├─→ AGENT_TOOL_CALL 事件
                                      ├─→ AGENT_TOOL_RESULT 事件
                                      └─→ AGENT_REPLY 事件
                                              │
                                              └─→ 广播到所有活跃渠道
```

## 3. API 设计

### 3.1 WebSocket 端点

```
WS /api/v1/sessions/{session_id}/sync
```

**连接流程**：
1. 客户端发起 WebSocket 连接，携带 `session_id` 和认证 token
2. 服务端验证后注册连接到 `SessionSyncManager`
3. 服务端发送历史事件（可配置数量）
4. 双向实时通信

**消息格式**：
```json
// 客户端 → 服务端
{
    "type": "user_message",
    "payload": {
        "content": "用户消息内容",
        "metadata": {}
    }
}

// 服务端 → 客户端
{
    "type": "agent_reply",
    "event_id": "evt_xxx",
    "source_channel": "web",
    "timestamp": "2026-06-07T10:00:00Z",
    "payload": {
        "content": "Agent 回复内容",
        "tool_calls": [],
        "metadata": {}
    }
}
```

### 3.2 REST API

```
# 会话管理
POST   /api/v1/sync/sessions              # 创建同步会话
GET    /api/v1/sync/sessions/{id}          # 获取会话信息
GET    /api/v1/sync/sessions/{id}/history  # 获取会话历史
DELETE /api/v1/sync/sessions/{id}          # 结束会话

# 渠道注册
POST   /api/v1/sync/sessions/{id}/channels    # 注册渠道
DELETE /api/v1/sync/sessions/{id}/channels/{type}  # 注销渠道

# 消息发送（REST 降级方案）
POST   /api/v1/sync/sessions/{id}/messages    # 发送消息
```

## 4. 实现计划

### Phase 1: 核心同步引擎 (2天)

**文件**：`neurova/sync/session_sync_manager.py`

- [ ] `UnifiedSession` 数据类
- [ ] `SessionEvent` 数据类
- [ ] `ChannelConnection` 数据类
- [ ] `SessionSyncManager` 单例类
  - 创建/销毁会话
  - 注册/注销渠道连接
  - 广播事件到所有活跃渠道
  - 保存/查询历史

### Phase 2: WebSocket 端点 (1天)

**文件**：`neurova/api/endpoints/session_sync.py`

- [ ] WebSocket 连接处理
- [ ] 认证和权限验证
- [ ] 历史事件推送
- [ ] 心跳检测

### Phase 3: 渠道适配器集成 (2天)

**文件**：修改 `neurova/channels/manager.py`

- [ ] 在消息接收时调用 `SessionSyncManager`
- [ ] 在消息发送时调用 `SessionSyncManager`
- [ ] 支持从同步会话发送消息到指定渠道

### Phase 4: Agent 集成 (1天)

**文件**：修改 `neurova/agent_core.py`

- [ ] 在 `chat()` 方法中发送 `AGENT_THINKING` 事件
- [ ] 在工具调用时发送 `AGENT_TOOL_CALL` 事件
- [ ] 在回复时发送 `AGENT_REPLY` 事件

### Phase 5: 前端实现 (2天)

**文件**：
- `neuUI/src/api/modules/session-sync.ts`
- `neuUI/src/composables/useSessionSync.ts`
- `neuUI/src/components/SessionSyncPanel.vue`

- [ ] WebSocket 连接管理
- [ ] 实时消息显示
- [ ] 历史消息加载
- [ ] 多渠道状态指示

## 5. 技术细节

### 5.1 会话 ID 映射

```python
class SessionMapping:
    """会话 ID 映射管理"""
    
    # user_id + agent_id → session_id
    _user_sessions: Dict[Tuple[str, str], str] = {}
    
    # external_id (渠道特定) → session_id
    _external_mapping: Dict[str, str] = {}
    
    def get_or_create_session(self, user_id: str, agent_id: str, 
                              external_id: str = None) -> str:
        """获取或创建会话"""
        key = (user_id, agent_id)
        
        if key in self._user_sessions:
            session_id = self._user_sessions[key]
        else:
            session_id = f"session_{uuid.uuid4().hex[:12]}"
            self._user_sessions[key] = session_id
        
        if external_id:
            self._external_mapping[external_id] = session_id
        
        return session_id
```

### 5.2 事件广播

```python
async def broadcast_event(self, session_id: str, event: SessionEvent):
    """广播事件到所有活跃渠道"""
    session = self._sessions.get(session_id)
    if not session:
        return
    
    # 保存到历史
    session.history.append(event)
    
    # 并发发送到所有渠道
    tasks = []
    for channel_type, conn in session.active_channels.items():
        if conn.send_callback:
            tasks.append(conn.send_callback(event))
    
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
```

### 5.3 历史压缩

```python
def compress_history(self, session: UnifiedSession, max_events: int = 1000):
    """压缩历史事件"""
    if len(session.history) <= max_events:
        return
    
    # 保留最近的事件
    session.history = session.history[-max_events:]
    
    # 可选：生成摘要保存到数据库
    self._archive_old_events(session)
```

## 6. 数据库设计

### 6.1 会话表

```sql
CREATE TABLE sync_sessions (
    session_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status TEXT DEFAULT 'active',
    metadata JSONB DEFAULT '{}'
);

CREATE INDEX idx_sessions_user ON sync_sessions(user_id);
CREATE INDEX idx_sessions_agent ON sync_sessions(agent_id);
CREATE INDEX idx_sessions_status ON sync_sessions(status);
```

### 6.2 事件表

```sql
CREATE TABLE session_events (
    event_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    source_channel TEXT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    payload JSONB NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sync_sessions(session_id)
);

CREATE INDEX idx_events_session ON session_events(session_id);
CREATE INDEX idx_events_timestamp ON session_events(timestamp);
```

## 7. 性能考虑

### 7.1 内存优化
- 使用环形缓冲区限制内存中的历史事件数量
- 定期将旧事件持久化到数据库
- 使用 LRU 缓存热点会话

### 7.2 并发处理
- 使用 `asyncio.Lock` 保护会话状态
- 使用 `asyncio.gather` 并发广播
- 使用连接池管理 WebSocket 连接

### 7.3 网络优化
- 支持消息压缩（gzip）
- 批量发送小消息
- 心跳检测和自动重连

## 8. 安全考虑

### 8.1 认证
- WebSocket 连接需要 JWT token
- REST API 需要用户认证
- 渠道注册需要渠道权限验证

### 8.2 隔离
- 会话按 user_id + agent_id 隔离
- 渠道只能访问已注册的会话
- 历史消息按权限过滤

## 9. 测试计划

### 9.1 单元测试
- SessionSyncManager 核心逻辑
- 事件序列化/反序列化
- 会话 ID 映射

### 9.2 集成测试
- WebSocket 连接和断开
- 多渠道同步
- 历史消息查询

### 9.3 E2E 测试
- Web + Mobile 同步对话
- 渠道切换后恢复历史
- 断线重连

## 10. 迁移计划

### 10.1 现有会话迁移
- 将现有的 `_CHAT_SESSIONS` 迁移到新的 `UnifiedSession`
- 保持向后兼容的 API

### 10.2 渠道适配器更新
- 逐步更新各渠道适配器支持同步
- 优先支持 Web、Mobile、Feishu

## 11. 监控和日志

### 11.1 指标
- 活跃会话数
- 消息吞吐量
- 平均延迟
- 错误率

### 11.2 日志
- 会话创建/销毁
- 渠道连接/断开
- 消息广播
- 错误和异常

## 12. 未来扩展

### 12.1 多人协作
- 支持多个用户同时参与同一会话
- 用户权限管理

### 12.2 消息队列集成
- 使用 Redis Pub/Sub 替代内存广播
- 支持分布式部署

### 12.3 端到端加密
- 会话内容加密存储
- 传输层加密
