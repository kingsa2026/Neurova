# Web Console 后端 API 文档

> **版本**: 1.1.0  
> **最后更新**: 2026-11-19  
> **负责人**: console-api-dev  
> **核对基准**: 2026-11-19，来源 `neurova/api/endpoints/console.py`、`console_files.py`、`console_system.py`（路由挂载见 `neurova/api/endpoints/__init__.py`）

---

## 概述

Console 路由挂载于 **`/api/v1/console/*`**（注册表项 `("neurova.api.endpoints.console", "/v1/console")`，
装配时统一加 `/api` 前缀）。本文所有路径均含完整前缀，直接请求 `/console/*` 会 404。

Web Console 后端 API 提供以下功能区：

1. **聊天接口** - 流式（SSE）与非流式对话，以及会话/回合/反馈等操作面
2. **文件上传** - 文件上传、下载、删除和列表（按用户域隔离）
3. **调试接口** - 后端日志查看、系统状态、白名单命令执行（仅管理员）
4. **WebSocket 推送** - 实时消息推送与双向通信
5. **任务追踪** - 运行中 asyncio 任务的注册、查询与取消

**鉴权**: 除特别说明外，所有端点均要求 JWT（`Authorization: Bearer <token>`）；
调试面与推送广播面额外要求管理员角色。

---

## 1. 聊天接口

### 1.1 POST /api/v1/console/chat

聊天接口，`stream=true`（默认）时为 SSE（Server-Sent Events）流。

**请求体**:
```json
{
  "message": "用户消息",
  "session_id": "会话ID（可选，缺省新建）",
  "agent_id": "智能体ID（可选，缺省默认智能体）",
  "stream": true,
  "model": "模型名（可选）",
  "thinking_effort": "light | standard | deep（可选）",
  "thinking_enabled": true,
  "thinking_budget": 4096,
  "file_ids": ["附件文件ID（可选）"],
  "client_timestamp": "前端发送时刻 ISO（可选）",
  "replay_from": null,
  "build_session_id": null
}
```

**流式响应**: SSE（`text/event-stream`），事件为 `data: <JSON>\n\n` 帧。

**SSE 事件格式**（按 `type` 区分）:
```json
// 会话归属声明（客户端未带 session_id 时当场告知，不进重放缓冲）
data: {"type": "session", "session_id": "uuid"}

// 文本增量（60ms 合并窗口）
data: {"type": "chunk", "content": "你好 "}

// 思考/推理增量
data: {"type": "reasoning", "content": "推理内容..."}

// 工具调用与结果（收尾 flush 与流式侧按 key 去重）
data: {"type": "tool_call", "name": "tool_name", "arguments": "{}"}
data: {"type": "tool_result", "name": "tool_name", "result": "...（截断至 2000 字符）"}

// 完成事件
data: {"type": "done", "session_id": "uuid"}

// 错误事件（附 error_kind / retryable 分型）
data: {"type": "error", "message": "错误信息", "error_kind": "...", "retryable": false}

// 停止事件（/chat/stop 真取消后以此收尾）
data: {"type": "stopped", "session_id": "uuid"}
```

其余控制事件：`item_started` / `item_delta` / `item_completed`（item 化旁路，携带
`thread_id`/`turn_id`/`item_id`/`item_type`）、`memory_progress`（实时检索进度）、
`retry`（429 重试倒计时）、`upstream_status`（上游静默）、`usage`（本调用真实用量）、
`quota_limited`（配额受限）、`parked`（回合挂起待续跑，附 `run_id`/`reason`/模型冲突双方）、
`plan_update`、`approval_required`、`build_interaction_required`、`artifact`（产物预览）。
空闲 15s 发 SSE 注释心跳 `: ping`。

**非流式响应**（`stream=false`）:
```json
{
  "code": 0,
  "message": "success",
  "data": {"reply": "完整响应", "response": "完整响应", "session_id": "uuid"}
}
```

**错误**: agent 未装配时返回 503（不再以回声/空回复假成功）。

---

### 1.2 POST /api/v1/console/chat/stop

停止运行中的对话（真取消：cancel 会话注册的 asyncio 任务）

**请求参数**:
- `session_id` (query, required): 要停止的会话ID

**响应**:
```json
{
  "code": 0,
  "message": "Chat stopped",
  "data": {"session_id": "uuid", "stopped": true}
}
```

无运行中任务时 `stopped` 为 `false`（message 为 "No running task"）。

---

### 1.3 GET /api/v1/console/chat/history

获取聊天历史

**请求参数**:
- `session_id` (query, required): 会话ID

**响应**:
```json
{
  "code": 0,
  "message": "success",
  "data": {"messages": [], "session_id": "uuid"}
}
```

会话不存在时返回 404；他人会话返回 403。

---

### 1.4 POST /api/v1/console/chat/new

创建新会话

**请求体**（可选）:
```json
{
  "agent_id": "智能体ID（可选）",
  "title": "会话标题（可选，缺省「新对话」）"
}
```

**响应**:
```json
{
  "code": 0,
  "message": "Session created",
  "data": {"session_id": "uuid"}
}
```

---

### 1.5 GET /api/v1/console/chat/sessions

列出当前用户的会话（过滤协作房间会话）

**请求参数**:
- `agent_id` (query, optional): 按智能体过滤

**响应**:
```json
{
  "code": 0,
  "message": "success",
  "data": {
    "sessions": [
      {
        "id": "uuid",
        "title": "新对话",
        "agent_id": "agent_id",
        "created_at": "2026-11-19T00:00:00",
        "updated_at": "2026-11-19T00:00:00",
        "pinned": false,
        "sort_order": 0,
        "source_channel": "",
        "channel_name": ""
      }
    ],
    "total": 1
  }
}
```

---

### 1.6 其余会话 / 回合 / 反馈端点

| 方法 | 路径 | 说明 | 关键参数 |
|------|------|------|----------|
| POST | `/api/v1/console/chat/review` | 代码评审受限子会话（禁工具/禁网，强制 JSON findings） | body: `content`(必填)、`focus`、`agent_id` |
| POST | `/api/v1/console/chat/steer` | 回合进行中插话（进会话级 steer 邮箱，TTL 300s） | body: `session_id`、`message` |
| POST | `/api/v1/console/chat/resume` | 人工续跑一条 parked 回合（按原入口重跑，返回 SSE 流） | query: `run_id` |
| GET | `/api/v1/console/chat/runs` | 回合台账读面（状态/挂起原因，不含消息原文） | query: `session_id`(必填)、`limit`(1-200,默认20)、`scope`=`turns`\|`subagents`；run 闸关闭时 503 |
| GET | `/api/v1/console/chat/tools/{task_id}/result` | 后台工具完成结果的限时查询面 | query: `session_id`、`agent_id` |
| GET | `/api/v1/console/chat/subagents/{subagent_id}/events` | 子任务事件账本读面（全程事件 + 因果链） | 路径: `subagent_id` |
| GET | `/api/v1/console/chat/sessions/{session_id}/timeline` | 会话时间线（SSE 事件 JSONL 只读重放） | query: `limit`(0-5000,默认0=全部) |
| POST | `/api/v1/console/chat/sessions/reorder` | 按拖拽顺序持久化会话排序 | body: `agent_id`、`ordered_ids`(必填) |
| DELETE | `/api/v1/console/chat/sessions/{session_id}` | 删除指定会话 | 路径: `session_id` |
| POST | `/api/v1/console/chat/sessions/{session_id}/auto-title` | LLM 概括首轮对话生成会话标题（幂等） | 路径: `session_id` |
| GET | `/api/v1/console/chat/sessions/archived` | 列出存档会话 | query: `agent_id` |
| POST | `/api/v1/console/chat/sessions/{session_id}/pin` | 置顶/取消置顶 | body: `pinned`(bool) |
| POST | `/api/v1/console/chat/sessions/{session_id}/archive` | 存档会话（历史列表隐藏，可恢复） | 路径: `session_id` |
| POST | `/api/v1/console/chat/sessions/{session_id}/unarchive` | 恢复存档会话 | 路径: `session_id` |
| PUT | `/api/v1/console/chat/sessions/{session_id}` | 重命名会话 | body: `title`(必填) |
| DELETE | `/api/v1/console/chat/rounds` | 删除一轮对话（user+相邻 assistant，含记忆清除） | query: `session_id`、`timestamp` |
| POST | `/api/v1/console/chat/feedback` | 点赞/点踩回复（作用于记忆温度等六面扇出） | body: `session_id`、`timestamp`、`feedback`=`like`\|`dislike`\|null、`corrected_answer` |
| GET | `/api/v1/console/chat/feedback/stats` | 点赞/点踩统计（按 agent 聚合） | query: `agent_id`、`limit`(1-200,默认50) |
| POST | `/api/v1/console/chat/sessions/{session_id}/fork` | 会话分叉（按时间戳截取历史复制为新会话） | body: `until_timestamp`、`title`（均可选） |
| POST | `/api/v1/console/chat/checkpoint` | 消息钩子/检查点（写 metadata.checkpoint） | body: `session_id`、`timestamp`、`active`(bool) |

统一响应外层为 `{"code": 0, "message": "...", "data": {...}}`；资源不存在 404，
越权访问他人会话 403，参数缺失 400。

---

## 2. 文件上传接口

附件按上传者 `user_id` 分域落盘，列表/下载/删除只在自己的域内活动。

### 2.1 POST /api/v1/console/upload

上传文件（需登录）

**请求**: `multipart/form-data`
- `file` (form, required): 要上传的文件

**限制**:
- 最大文件大小: 100 MB（超限返回 413）
- 支持任意文件类型

**响应**:
```json
{
  "code": 0,
  "message": "File uploaded",
  "data": {
    "file_id": "1a2b3c4d",
    "filename": "filename.txt",
    "size": 12345,
    "content_type": "text/plain",
    "path": "<数据根>/uploads/console/<user_id>/1a2b3c4d_filename.txt",
    "uploaded_at": "2026-11-19T00:00:00+00:00"
  }
}
```

**安全**: 文件名会经过安全处理（`_safe_filename`：非法字符替换为 `_`，最大200字符）；
落盘名为 `{file_id}_{safe_name}`（file_id 为 8 位 uuid 前缀）。

---

### 2.2 GET /api/v1/console/uploads

列出**本人**已上传文件

**响应**:
```json
{
  "code": 0,
  "message": "success",
  "data": {
    "files": [
      {"filename": "1a2b3c4d_filename.txt", "size": 12345, "modified": "2026-11-19T00:00:00"}
    ],
    "total": 1
  }
}
```

---

### 2.3 GET /api/v1/console/uploads/{filename}

下载文件（仅本人域内；`filename` 为列表返回的落盘名）

**路径参数**:
- `filename`: 文件名（含 file_id 前缀）

**响应**: 文件内容（`FileResponse`）；不存在返回 404。

---

### 2.4 DELETE /api/v1/console/uploads/{filename}

删除文件（仅本人域内）

**路径参数**:
- `filename`: 文件名（含 file_id 前缀）

**响应**:
```json
{"code": 0, "message": "File deleted"}
```

---

## 3. 调试接口（仅管理员）

### 3.1 GET /api/v1/console/debug/logs

查看后端日志

**请求参数**:
- `lines` (query, optional): 返回行数（默认100）

**响应**:
```json
{
  "code": 0,
  "message": "success",
  "data": {"content": "...日志末 N 行...", "lines": 100}
}
```

日志文件路径取 `NEUROVA_LOG_FILE` 配置（缺省 `logs/neurova.log`）；文件不存在时
`content` 返回提示文案。

---

### 3.2 GET /api/v1/console/debug/status

获取系统状态（psutil 指标）

**响应**:
```json
{
  "code": 0,
  "message": "success",
  "data": {
    "cpu_percent": 12.3,
    "memory_percent": 45.6,
    "memory_used_mb": 8192,
    "memory_total_mb": 16384,
    "disk_percent": 33.3,
    "uptime_seconds": 9000
  }
}
```

psutil 不可用时 `data` 降级为 `{"note": "...", "timestamp": "..."}`。

---

### 3.3 POST /api/v1/console/debug/command

运行调试命令（仅限管理员；白名单精确匹配 + exec 数组执行）

**请求体**:
```json
{"command": "python --version", "args": null}
```

**白名单**: `ls`、`pwd`、`whoami`、`date`、`python --version`、`node --version`；
执行超时 10 秒。

**响应**:
```json
{
  "code": 0,
  "message": "success",
  "data": {"stdout": "...", "stderr": "", "returncode": 0}
}
```

**错误响应**:
- 403：命令不在白名单（`Command '...' not allowed. Allowed: [...]`）
- 408：命令执行超时
- 500：执行异常

**安全警告**: 此接口仅用于开发/测试环境，生产环境应禁用或严格限制。

---

## 4. WebSocket 推送消息

### 4.1 WS /api/v1/console/ws/{client_id}

WebSocket 连接端点。**必须携带鉴权**：`?token=<JWT>`（或 `Authorization: Bearer` 头），
校验失败以 4401 关闭。`client_id` 路径参数仅保留路由形状（前端兼容），服务端连接键
实际为 `f"{user}:{uuid4().hex[:8]}"` 派生，不作为身份。

**支持的消息类型**:

#### 客户端 → 服务器

1. **心跳检测**
```json
{"type": "ping"}
```

2. **对话**（走当前默认智能体，受属主门校验）
```json
{"type": "chat", "message": "用户消息", "session_id": "可选会话ID"}
```

#### 服务器 → 客户端

1. **心跳响应**
```json
{"type": "pong", "timestamp": 1620854400.123}
```

2. **对话回复**
```json
{"type": "chat_reply", "content": "回复内容"}
```

3. **错误**
```json
{"type": "error", "message": "错误信息"}
```

4. **未识别消息的确认**
```json
{"type": "ack", "data": {}}
```

5. **推送广播**（由 `POST /push/message` 广播给所有连接）
```json
{"type": "push", "content": "广播内容", "sender": "admin", "timestamp": 1620854400.123}
```

---

## 5. 推送消息 API

### 5.1 GET /api/v1/console/push/messages

获取推送消息（轮询方式；取当前用户离线缓冲中 `stored_at > since` 的消息，缓冲上限 100 条）

**请求参数**:
- `since` (query, optional, float): 只取此时间戳之后的消息（默认 0）

**响应**:
```json
{
  "code": 0,
  "message": "success",
  "data": {"messages": [], "total": 0}
}
```

---

### 5.2 POST /api/v1/console/push/message

发送推送消息（广播给所有 WebSocket 连接；**仅管理员**）

**请求体**:
```json
{"content": "广播内容"}
```

**响应**:
```json
{"code": 0, "message": "Push sent"}
```

---

## 6. 任务追踪器 (TaskTracker)

`neurova/core/task_tracker.py` 的 `TaskTracker` 是**运行中 asyncio 任务注册表**
（`/console/chat/stop` 真取消的根基），不再是同步状态机。历史注记（B-11/B-12 清理，
2026-09-11）：旧同步任务路径（`start_tracking`/`update_progress`/`complete_task`/
`fail_task`/`pause`/`resume`/`stop`/`get_task_status`/`subscribe`/`get_statistics` 及
`TaskInfo`/`TaskStatus` 状态机）已随 `start_tracking`（全仓零运行时调用方）一并删除。

### 6.1 核心方法

- `register_async_task(session_id, task, kind="chat")` - 注册运行中的 asyncio 任务（done 回调自动移除）
- `lookup_async_tasks(session_id)` - 列出会话的运行中任务（不含 task 对象）
- `request_session_stop(session_id)` - 取消会话全部运行中任务（`Task.cancel()`），返回取消数量
- `snapshot_async_tasks()` - 全部运行中任务快照（后台任务面板数据源）
- `get_task_tracker()` - 全局单例获取

### 6.2 消费方

- `GET /api/v1/console/tasks` - 任务快照 + 持久台账四档计数（running/queued/parked/terminal）
- `POST /api/v1/console/chat/stop` - 会话级真取消

### 6.3 使用示例

```python
from neurova.core.task_tracker import get_task_tracker

tracker = get_task_tracker()
tracker.register_async_task(session_id, asyncio_task, kind="chat")
running = tracker.snapshot_async_tasks()   # [{session_id, kind, started_at, duration}]
stopped = tracker.request_session_stop(session_id)
```

---

## 7. 错误代码说明

| HTTP 状态码 | 说明 |
|------------|------|
| 200 | 成功 |
| 400 | 请求参数错误（如 ordered_ids 缺失、content 为空） |
| 401 | 未认证（JWT 缺失/无效；WS 以 4401 关闭） |
| 403 | 禁止访问（会话/智能体越权、调试命令不在白名单） |
| 404 | 资源不存在（会话、文件、轮次、消息） |
| 408 | 请求超时（如调试命令执行超时） |
| 409 | 状态冲突（如续跑目标不是 parked、run 已被取走） |
| 413 | 文件过大（上传超过 100 MB） |
| 429 | 请求过于频繁（速率限制） |
| 500 | 服务器内部错误 |
| 503 | 服务不可用（如 agent 未装配、run 台账已关闭） |

---

## 8. 集成说明

### 8.1 认知处理走的是哪条路

> **2026-10-12 更正**（台账 §6-166）：本节原先写"聊天接口使用 `CognitionOrchestrator` 进行认知处理"
> 并给了一段 `from neurova.core.cognition_orchestrator import ...` ＋
> `async for output in orchestrator.process_thought_cycle(context)` 的示例。两处都不成立：
> ① `console.py` 从未 import 该模块（复算口径含相对导入与门面再导出）；② 该函数返回
> `CognitiveCycleResult` 对象，不是异步生成器，`async for` 这个形状从来没跑通过。
> 那只编排器与另两套同批退役——它的"周期"实测按字符串长度编观察与反思内容并把 `success` 写 True。

聊天接口 (`POST /api/v1/console/chat`) 的实际链路：

```text
console.py: get_agent_instance(...) → neurova/agent_core.py
    ├─ 回合内召回：neurova/agent/chat_pipeline.py（_retrieve_memories 等）
    ├─ 回合后反思与改进：neurova/agent/post_chat_pipeline.py
    ├─ 记忆巩固：SleepConsolidation（空闲触发 + 关机 run_sleep_cycle）
    └─ 后台任务句柄与停止：neurova/core/task_tracker.py
```

规划类能力不在这条链上，现役三处：`neurova/planning/planning_tool.py`（agent 工具面）、
`neurova/plan_mode/` → `/api/v1/plans`（审批后产出 `execute_prompt` 交回聊天链路执行）、
`neurova/collaboration/neurflow/nl_designer.py`（自然语言生成工作流图）。

### 8.2 与 WebSocket 集成

消息通过 WebSocket 实时推送给客户端：

```javascript
const ws = new WebSocket('ws://localhost:9527/api/v1/console/ws/client-1?token=<JWT>');

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  if (data.type === 'chat_reply') {
    console.log(`回复: ${data.content}`);
  } else if (data.type === 'push') {
    console.log(`广播: ${data.content}`);
  }
};
```

---

## 9. 测试覆盖

Console API 测试现分布于以下文件（用例数按 `def test*` 现场清点，2026-11-19；
未附通过/失败读数——以当次实跑为准）：

| 文件 | 用例数 | 覆盖类 |
|------|--------|--------|
| `tests/test_api/test_console_api.py` | 15 | `TestTaskTrackerSingleton`、`TestConsoleAPI`、`TestIntegration` |
| `tests/test_api/test_console_api_extended.py` | 28 | 文件上传/下载/删除、推送、历史、会话、调试、WebSocket、集成（`TestFileDownload`、`TestFileDelete`、`TestPushMessages`、`TestChatHistoryExtended`、`TestChatSessionsExtended`、`TestDebugEndpointsExtended`、`TestWebSocketExtended`、`TestIntegrationExtended`） |
| `tests/test_api/test_console_timeline_api.py` | 4 | `TestTimelineEndpoint`（会话时间线重放） |
| `tests/unit/api/test_consoleRunLedgerReadout.py` | 2 | `TestRunLedgerReadout`（回合台账读面） |

> **历史读数**：旧版本文档所记「单元测试文件 `tests/test_console_api.py`，总用例 30、
> 通过 20（TaskTracker 相关）、失败 10（API 端点，速率限制问题）」为 2026-05 快照——
> 该路径与用例分布均已不反映现状（文件已迁至 `tests/test_api/` 并拆分扩展）。

---

## 10. TODO 和后续工作

旧版本文档的 TODO 清单（集成 MemoryManager/SessionManager、实现文件下载、
实现消息存储、完善 CognitionOrchestrator 等）所涉能力均已落地或随退役清理，不再列示。
当前遗留的工程化事项以仓库台账为准（如生产环境速率限制与认证强化策略）。

---

## 11. 附录：完整 API 端点列表

核对基准 2026-11-19，来源 `neurova/api/endpoints/console*.py`（console.py、console_files.py、
console_system.py 的 `@router` 装饰器逐一核对；文件/调试路由经 `router.include_router`
并入同一前缀）。

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/console/chat` | 聊天接口（默认 SSE 流式） |
| POST | `/api/v1/console/chat/review` | 代码评审受限子会话 |
| POST | `/api/v1/console/chat/steer` | 回合进行中插话 |
| POST | `/api/v1/console/chat/stop` | 停止会话运行中对话 |
| POST | `/api/v1/console/chat/resume` | 续跑 parked 回合 |
| GET | `/api/v1/console/chat/runs` | 回合台账读面 |
| GET | `/api/v1/console/chat/tools/{task_id}/result` | 后台工具结果查询 |
| GET | `/api/v1/console/chat/subagents/{subagent_id}/events` | 子任务事件账本 |
| GET | `/api/v1/console/chat/history` | 获取聊天历史 |
| GET | `/api/v1/console/chat/sessions/{session_id}/timeline` | 会话时间线重放 |
| POST | `/api/v1/console/chat/new` | 创建新会话 |
| GET | `/api/v1/console/chat/sessions` | 列出会话 |
| POST | `/api/v1/console/chat/sessions/reorder` | 会话排序持久化 |
| DELETE | `/api/v1/console/chat/sessions/{session_id}` | 删除会话 |
| POST | `/api/v1/console/chat/sessions/{session_id}/auto-title` | 自动生成会话标题 |
| GET | `/api/v1/console/chat/sessions/archived` | 列出存档会话 |
| POST | `/api/v1/console/chat/sessions/{session_id}/pin` | 置顶/取消置顶 |
| POST | `/api/v1/console/chat/sessions/{session_id}/archive` | 存档会话 |
| POST | `/api/v1/console/chat/sessions/{session_id}/unarchive` | 恢复存档会话 |
| PUT | `/api/v1/console/chat/sessions/{session_id}` | 重命名会话 |
| DELETE | `/api/v1/console/chat/rounds` | 删除一轮对话 |
| POST | `/api/v1/console/chat/feedback` | 点赞/点踩反馈 |
| GET | `/api/v1/console/chat/feedback/stats` | 反馈统计 |
| POST | `/api/v1/console/chat/sessions/{session_id}/fork` | 会话分叉 |
| POST | `/api/v1/console/chat/checkpoint` | 消息钩子/检查点 |
| GET | `/api/v1/console/tasks` | 运行中任务快照 + 台账计数 |
| POST | `/api/v1/console/upload` | 文件上传 |
| GET | `/api/v1/console/uploads` | 列出本人已上传文件 |
| GET | `/api/v1/console/uploads/{filename}` | 下载文件 |
| DELETE | `/api/v1/console/uploads/{filename}` | 删除文件 |
| GET | `/api/v1/console/debug/logs` | 查看后端日志（管理员） |
| GET | `/api/v1/console/debug/status` | 系统状态（管理员） |
| POST | `/api/v1/console/debug/command` | 运行白名单调试命令（管理员） |
| WS | `/api/v1/console/ws/{client_id}` | WebSocket 连接（需 token） |
| GET | `/api/v1/console/push/messages` | 获取推送消息（轮询） |
| POST | `/api/v1/console/push/message` | 发送推送消息（管理员） |

---

**文档结束**
