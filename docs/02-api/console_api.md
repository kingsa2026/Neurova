# Web Console 后端 API 文档

> **版本**: 1.0.0  
> **最后更新**: 2026-05-12  
> **负责人**: console-api-dev

---

## 概述

Web Console 后端 API 提供以下功能区：

1. **聊天接口** - 支持流式输出的对话接口
2. **文件上传** - 文件上传、下载、删除和管理
3. **调试接口** - 后端日志查看、系统状态、命令执行
4. **WebSocket 推送** - 实时消息推送和任务状态更新
5. **任务追踪** - 任务生命周期管理和进度追踪

---

## 1. 聊天接口

### 1.1 POST /console/chat

流式聊天接口（SSE - Server-Sent Events）

**请求体**:
```json
{
  "message": "用户消息",
  "session_id": "会话ID（可选）",
  "stream": true,
  "metadata": {}
}
```

**响应**: SSE (text/event-stream)

**SSE 事件格式**:
```json
// 认知过程更新
data: {"state": "reasoning", "progress": 0.3, "message": "推理中", "data": {}}

// 文本流（逐个单词）
data: {"text": "你好 ", "task_id": "uuid"}

// 完成事件
data: {"event": "done", "task_id": "uuid", "response": "完整响应"}

// 错误事件
data: {"event": "error", "error": "错误信息", "task_id": "uuid"}

// 停止事件
data: {"event": "stopped", "task_id": "uuid"}
```

**集成**: 使用 `CognitionOrchestrator` 进行认知处理，支持完整的认知周期（OBSERVING → REASONING → RECALLING → REFLECTING → ACTING → LEARNING）

---

### 1.2 POST /console/chat/stop

停止运行中的对话

**请求参数**:
- `task_id` (query, required): 要停止的任务ID

**响应**:
```json
{
  "stopped": true,
  "task_id": "uuid"
}
```

---

### 1.3 GET /console/chat/history

获取聊天历史

**请求参数**:
- `session_id` (query, optional): 会话ID
- `limit` (query, optional): 返回消息数量（默认50，最大100）

**响应**:
```json
{
  "session_id": "session_id",
  "messages": [],
  "total": 0
}
```

**TODO**: 集成 MemoryManager 获取真实历史记录

---

### 1.4 POST /console/chat/new

创建新会话

**请求体**:
```json
{
  "metadata": {
    "user_id": "user123",
    "source": "web"
  }
}
```

**响应**:
```json
{
  "session_id": "uuid",
  "created_at": "2026-05-12T23:54:00Z",
  "metadata": {}
}
```

---

### 1.5 GET /console/chat/sessions

列出所有会话

**请求参数**:
- `user_id` (query, optional): 用户ID

**响应**:
```json
{
  "sessions": [],
  "total": 0
}
```

**TODO**: 集成 SessionManager 获取真实会话列表

---

## 2. 文件上传接口

### 2.1 POST /console/upload

上传文件

**请求**: `multipart/form-data`
- `file` (form, required): 要上传的文件

**限制**:
- 最大文件大小: 50 MB
- 支持任意文件类型

**响应**:
```json
{
  "file_id": "uuid_filename.txt",
  "file_name": "filename.txt",
  "size": 12345,
  "path": "data/uploads/uuid_filename.txt",
  "url": "/console/upload/uuid_filename.txt"
}
```

**安全**: 文件名会经过安全处理（只允许字母数字、`.`、`-`、`_`，最大200字符）

---

### 2.2 GET /console/upload/{file_id}

下载文件

**路径参数**:
- `file_id`: 文件ID

**响应**: 文件内容（TODO: 实现文件下载功能）

---

### 2.3 DELETE /console/upload/{file_id}

删除文件

**路径参数**:
- `file_id`: 文件ID

**响应**:
```json
{
  "deleted": true,
  "file_id": "uuid_filename.txt"
}
```

---

### 2.4 GET /console/upload/list

列出已上传文件

**请求参数**:
- `limit` (query, optional): 返回数量（默认50，最大100）
- `offset` (query, optional): 偏移量（默认0）

**响应**:
```json
{
  "files": [
    {
      "file_id": "uuid_filename.txt",
      "size": 12345,
      "created_at": "2026-05-12T23:54:00Z"
    }
  ],
  "total": 1,
  "limit": 50,
  "offset": 0
}
```

---

## 3. 调试接口

### 3.1 GET /console/debug/backend-logs

查看后端日志

**请求参数**:
- `lines` (query, optional): 返回行数（默认200，最大1000）

**响应**:
```json
{
  "path": "logs/neurova.log",
  "exists": true,
  "lines": 200,
  "content": "...日志内容...",
  "updated_at": 1620854400.123,
  "size": 123456
}
```

**实现**: 读取日志文件的最后 N 行（限制内存使用）

---

### 3.2 GET /console/debug/system-status

获取系统状态

**响应**:
```json
{
  "status": "running",
  "version": "1.0.0",
  "uptime": "2:30:00",
  "agents_loaded": 1,
  "default_agent": "Yiling",
  "memory_enabled": true,
  "channels_enabled": true,
  "tasks": {
    "total": 10,
    "running": 2,
    "completed": 7,
    "failed": 1
  },
  "websocket_connections": 3
}
```

---

### 3.3 POST /console/debug/run-command

运行调试命令

**请求体**:
```json
{
  "command": "dir",
  "timeout": 30
}
```

**响应**:
```json
{
  "command": "dir",
  "returncode": 0,
  "stdout": "...",
  "stderr": "",
  "timeout": 30
}
```

**错误响应** (408 Request Timeout):
```json
{
  "error": "命令执行超时（30 秒）",
  "command": "dir"
}
```

**安全警告**: 此接口仅用于开发/测试环境，生产环境应禁用或严格限制可用命令。

---

## 4. WebSocket 推送消息

### 4.1 WS /console/ws

WebSocket 连接端点

**支持的消息类型**:

#### 客户端 → 服务器

1. **订阅任务更新**
```json
{
  "type": "subscribe",
  "task_id": "uuid"
}
```

2. **取消订阅**
```json
{
  "type": "unsubscribe",
  "task_id": "uuid"
}
```

3. **心跳检测**
```json
{
  "type": "ping",
  "timestamp": "2026-05-12T23:54:00Z"
}
```

#### 服务器 → 客户端

1. **订阅成功**
```json
{
  "event": "subscribed",
  "task_id": "uuid"
}
```

2. **取消订阅成功**
```json
{
  "event": "unsubscribed",
  "task_id": "uuid"
}
```

3. **心跳响应**
```json
{
  "event": "pong",
  "timestamp": "2026-05-12T23:54:00Z"
}
```

4. **任务更新**（通过 TaskTracker.subscribe）
```json
{
  "event": "progress_update",
  "task_id": "uuid",
  "progress": 0.5,
  "message": "处理中...",
  "status": "running"
}
```

5. **错误**
```json
{
  "event": "error",
  "message": "错误信息"
}
```

---

## 5. 推送消息 API

### 5.1 GET /console/push-messages

获取推送消息（用于轮询方式）

**请求参数**:
- `session_id` (query, optional): 会话ID
- `after` (query, optional): 只获取此时间之后的消息

**响应**:
```json
{
  "messages": [],
  "session_id": "session_id",
  "after": "2026-05-12T23:00:00Z"
}
```

**TODO**: 实现消息存储和检索

---

### 5.2 POST /console/push-messages

发送推送消息（广播给所有 WebSocket 连接）

**请求体**:
```json
{
  "event": "custom_event",
  "data": {
    "key": "value"
  }
}
```

**响应**:
```json
{
  "broadcast": true,
  "connections": 3
}
```

---

## 6. 任务追踪器 (TaskTracker)

`TaskTracker` 类提供任务生命周期管理，支持以下状态转换：

```
PENDING → RUNNING → COMPLETED
                 ↓
              FAILED
                 ↓
             CANCELLED
```

### 6.1 任务状态

| 状态 | 说明 |
|------|------|
| `pending` | 等待执行 |
| `running` | 执行中 |
| `paused` | 已暂停 |
| `completed` | 已完成 |
| `failed` | 失败 |
| `cancelled` | 已取消 |

### 6.2 核心方法

- `start_tracking(task_id, metadata)` - 开始追踪任务
- `update_progress(task_id, progress, message)` - 更新任务进度
- `complete_task(task_id, result)` - 完成任务
- `fail_task(task_id, error)` - 任务失败
- `pause_task(task_id)` - 暂停任务
- `resume_task(task_id)` - 恢复任务
- `stop_task(task_id)` - 停止任务
- `get_task_status(task_id)` - 获取任务状态
- `subscribe(task_id)` - 订阅任务更新（用于 SSE）

### 6.3 使用示例

```python
from neurova.core.task_tracker import start_tracking, update_progress, complete_task

# 开始追踪
task_info = await start_tracking("task_1", {"type": "chat"})

# 更新进度
await update_progress("task_1", 0.5, "处理中...")

# 完成任务
await complete_task("task_1", {"result": "success"})
```

---

## 7. 错误代码说明

| HTTP 状态码 | 说明 |
|------------|------|
| 200 | 成功 |
| 400 | 请求参数错误（如文件太大） |
| 404 | 资源不存在（如文件不存在） |
| 408 | 请求超时（如命令执行超时） |
| 429 | 请求过于频繁（速率限制） |
| 500 | 服务器内部错误 |
| 503 | 服务不可用（如必需的组件未初始化） |

---

## 8. 集成说明

### 8.1 与 CognitionOrchestrator 集成

聊天接口 (`POST /console/chat`) 使用 `CognitionOrchestrator` 进行认知处理：

```python
from neurova.core.cognition_orchestrator import (
    CognitionOrchestrator,
    CognitiveContext,
    get_cognition_orchestrator,
)

orchestrator = get_cognition_orchestrator()
context = CognitiveContext(
    user_input="用户消息",
    session_id="session_id",
    metadata={},
)

async for output in orchestrator.process_thought_cycle(context):
    # 处理认知过程输出
    pass
```

### 8.2 与 WebSocket 集成

任务更新通过 WebSocket 实时推送给客户端：

```javascript
const ws = new WebSocket('ws://localhost:9527/console/ws');

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  if (data.event === 'progress_update') {
    console.log(`任务 ${data.task_id} 进度: ${data.progress * 100}%`);
  }
};
```

---

## 9. 测试覆盖

单元测试文件: `tests/test_console_api.py`

**测试统计**:
- 总测试用例: 30
- 通过: 20 (TaskTracker 相关)
- 失败: 10 (API 端点，由于中间件速率限制问题)

**核心测试类**:
1. `TestTaskTracker` - TaskTracker 功能测试（10 个测试）
2. `TestConvenienceFunctions` - 便捷函数测试（5 个测试）
3. `TestConsoleAPI` - Web Console API 端点测试（10 个测试）
4. `TestIntegration` - 集成测试（2 个测试）

---

## 10. TODO 和后续工作

1. **集成 MemoryManager** - 实现真实的聊天历史存储和检索
2. **集成 SessionManager** - 实现真实的会话管理
3. **实现文件下载** - `GET /console/upload/{file_id}` 返回文件内容
4. **实现消息存储** - `GET /console/push-messages` 返回真实消息
5. **完善 CognitionOrchestrator** - 当前是模拟实现，等待 cognition-dev 完成
6. **修复速率限制中间件** - 测试环境中的速率限制问题
7. **添加认证** - 生产环境需要添加适当的认证机制
8. **添加速率限制** - 对 API 端点添加合理的速率限制

---

## 11. 附录：完整 API 端点列表

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/console/chat` | 流式聊天接口 |
| POST | `/console/chat/stop` | 停止对话 |
| GET | `/console/chat/history` | 获取聊天历史 |
| POST | `/console/chat/new` | 创建新会话 |
| GET | `/console/chat/sessions` | 列出所有会话 |
| POST | `/console/upload` | 文件上传 |
| GET | `/console/upload/{file_id}` | 下载文件 |
| DELETE | `/console/upload/{file_id}` | 删除文件 |
| GET | `/console/upload/list` | 列出已上传文件 |
| GET | `/console/debug/backend-logs` | 查看后端日志 |
| GET | `/console/debug/system-status` | 系统状态 |
| POST | `/console/debug/run-command` | 运行调试命令 |
| WS | `/console/ws` | WebSocket 连接 |
| GET | `/console/push-messages` | 获取推送消息 |
| POST | `/console/push-messages` | 发送推送消息 |

---

**文档结束**
