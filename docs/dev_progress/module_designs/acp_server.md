# ACP Server 设计文档

> **模块ID**: Task6-ACPServer  
> **创建时间**: 2026-05-13 00:00  
> **最后更新**: 2026-05-13 00:05  
> **负责人**: acp-dev  
> **状态**: ✅ 已完成

---

## 1. 模块概述

### 1.1 功能描述

ACP Server（Agent Control Protocol Server）是 Neurova CogArch 2.0 架构中的标准化 Agent 控制协议实现，负责：

- 实现标准的 Agent 控制协议（ACP）
- 提供会话管理功能（新建/加载/恢复/关闭）
- 支持 Server-Sent Events (SSE) 流式输出
- 实现增量更新格式（delta）
- 支持思考过程和工具调用的可视化
- 提供工具调用请求/响应格式和结果回传
- 支持运行时模型切换
- 提供会话配置管理和动态更新

### 1.2 设计依据

- **NEUROVA_CogArch_2.0.md 第2593-2630行**：8.5.2 ACP 说明
- **QwenPaw 的 ACP 实现**：借鉴其 `QwenPawACPAgent` 设计

### 1.3 与其他模块的关系

- **依赖模块**: 
  - `neurova.core.api_standard`：提供 APIResponse、APIError 等标准接口
  - `neurova.api.middleware`：提供 get_current_user 认证依赖
  - FastAPI：Web 框架

- **被依赖模块**: 
  - `neurova.api.app`：需要注册 ACP 路由器
  - `console-api-dev`：将来可能基于 ACP Server 构建 Web Console API

---

## 2. 架构设计

### 2.1 类/函数设计

#### 2.1.1 ACPMessage (dataclass)

```python
@dataclass
class ACPMessage:
    """
    ACP 消息
    
    表示 ACP 协议中的一条消息，支持多轮对话。
    """
    role: ACPMessageRole
    content: str
    message_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = field(default_factory=lambda: time.time())
    metadata: Dict[str, Any] = field(default_factory=dict)
```

**属性说明**:
- `role`: 消息角色（USER/ASSISTANT/SYSTEM/TOOL）
- `content`: 消息内容
- `message_id`: 消息唯一标识符
- `timestamp`: 时间戳
- `metadata`: 元数据字典

**方法**:
- `to_dict() -> Dict[str, Any]`: 转换为字典
- `from_dict(data: Dict[str, Any]) -> ACPMessage`: 从字典创建

#### 2.1.2 ACPStreamChunk (dataclass)

```python
@dataclass
class ACPStreamChunk:
    """
    ACP 流式数据块
    
    用于 Server-Sent Events (SSE) 流式输出，支持增量更新。
    """
    event_type: ACPStreamEventType
    data: Dict[str, Any]
    session_id: str = ""
    chunk_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = field(default_factory=lambda: time.time())
```

**属性说明**:
- `event_type`: 事件类型（MESSAGE/DELTA/THINKING/TOOL_CALL/TOOL_RESULT/DONE/ERROR/HEARTBEAT）
- `data`: 事件数据
- `session_id`: 会话 ID
- `chunk_id`: 数据块唯一标识符

**方法**:
- `to_sse_format() -> str`: 转换为 SSE 格式字符串
- `to_dict() -> Dict[str, Any]`: 转换为字典

#### 2.1.3 ACPToolCall (dataclass)

```python
@dataclass
class ACPToolCall:
    """ACP 工具调用"""
    tool_name: str
    tool_input: Dict[str, Any]
    call_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = field(default_factory=lambda: time.time())
```

#### 2.1.4 ACPToolResult (dataclass)

```python
@dataclass
class ACPToolResult:
    """ACP 工具调用结果"""
    call_id: str
    success: bool
    result: Any = None
    error: Optional[str] = None
    timestamp: float = field(default_factory=lambda: time.time())
```

#### 2.1.5 ACPThinkingStep (dataclass)

```python
@dataclass
class ACPThinkingStep:
    """ACP 思考步骤"""
    step: int
    content: str
    timestamp: float = field(default_factory=lambda: time.time())
```

#### 2.1.6 ACPModelConfig (dataclass)

```python
@dataclass
class ACPModelConfig:
    """ACP 模型配置"""
    model_id: str
    provider: str
    model_name: str
    capabilities: List[str] = field(default_factory=list)
    config: Dict[str, Any] = field(default_factory=dict)
```

#### 2.1.7 ACPSessionConfig (dataclass)

```python
@dataclass
class ACPSessionConfig:
    """ACP 会话配置"""
    model_id: str = "default"
    temperature: float = 0.7
    max_tokens: int = 2048
    top_p: float = 1.0
    stream: bool = True
    enable_thinking: bool = True
    enable_tool_calls: bool = True
    custom_settings: Dict[str, Any] = field(default_factory=dict)
```

**方法**:
- `to_dict() -> Dict[str, Any]`: 转换为字典
- `from_dict(data: Dict[str, Any]) -> ACPSessionConfig`: 从字典创建

#### 2.1.8 ACPSession (dataclass)

```python
@dataclass
class ACPSession:
    """
    ACP 会话
    
    ACP 协议中的核心会话对象，管理会话的生命周期。
    """
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    agent_id: str = "default"
    status: ACPSessionStatus = ACPSessionStatus.CREATED
    config: ACPSessionConfig = field(default_factory=ACPSessionConfig)
    messages: List[ACPMessage] = field(default_factory=list)
    created_at: float = field(default_factory=lambda: time.time())
    updated_at: float = field(default_factory=lambda: time.time())
    metadata: Dict[str, Any] = field(default_factory=dict)
```

**属性说明**:
- `session_id`: 会话唯一标识符
- `agent_id`: Agent ID
- `status`: 会话状态（CREATED/ACTIVE/PAUSED/CLOSED/ERROR）
- `config`: 会话配置
- `messages`: 消息历史列表
- `created_at`: 创建时间戳
- `updated_at`: 最后更新时间戳
- `metadata`: 元数据字典

**方法**:
- `add_message(message: ACPMessage) -> None`: 添加消息到会话历史
- `get_history(max_turns: int = 10) -> List[Dict[str, Any]]`: 获取会话历史
- `to_dict() -> Dict[str, Any]`: 转换为字典
- `from_dict(data: Dict[str, Any]) -> ACPSession`: 从字典创建

#### 2.1.9 ACPServer

```python
class ACPServer:
    """
    ACP Server - Agent Control Protocol 服务器
    
    实现标准的 Agent 控制协议，作为接口层与内部核心（Cognition Orchestrator）之间的桥梁。
    
    架构位置：接口层 - API/协议适配层
    """
    
    def __init__(self):
        """初始化 ACP Server"""
        self._sessions: Dict[str, ACPSession] = {}
        self._models: Dict[str, ACPModelConfig] = {}
        self._lock = asyncio.Lock()
```

**属性/参数说明**:
- `_sessions`: 会话字典，键为 session_id，值为 ACPSession 实例
- `_models`: 模型配置字典，键为 model_id，值为 ACPModelConfig 实例
- `_lock`: asyncio.Lock，用于并发控制

#### 2.1.10 ACPServer.create_session()

```python
async def create_session(
    self,
    agent_id: str = "default",
    config: Optional[ACPSessionConfig] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> ACPSession:
    """
    创建新会话
    
    Args:
        agent_id: Agent ID
        config: 会话配置
        metadata: 元数据
        
    Returns:
        ACPSession: 新创建的会话
    """
```

#### 2.1.11 ACPServer.load_session()

```python
async def load_session(self, session_id: str) -> Optional[ACPSession]:
    """
    加载已有会话
    
    Args:
        session_id: 会话 ID
        
    Returns:
        Optional[ACPSession]: 会话对象，如果不存在则返回 None
    """
```

#### 2.1.12 ACPServer.resume_session()

```python
async def resume_session(self, session_id: str) -> Optional[ACPSession]:
    """
    恢复会话（从持久化存储）
    
    Args:
        session_id: 会话 ID
        
    Returns:
        Optional[ACPSession]: 恢复的会话对象
    """
```

#### 2.1.13 ACPServer.close_session()

```python
async def close_session(self, session_id: str) -> bool:
    """
    关闭会话
    
    Args:
        session_id: 会话 ID
        
    Returns:
        bool: 是否成功关闭
    """
```

#### 2.1.14 ACPServer.get_session_status()

```python
async def get_session_status(self, session_id: str) -> Optional[Dict[str, Any]]:
    """
    获取会话状态
    
    Args:
        session_id: 会话 ID
        
    Returns:
        Optional[Dict[str, Any]]: 会话状态字典
    """
```

#### 2.1.15 ACPServer.chat_stream()

```python
async def chat_stream(
    self,
    session_id: str,
    message: str,
    tools: Optional[List[str]] = None,
) -> AsyncGenerator[str, None]:
    """
    流式对话
    
    Args:
        session_id: 会话 ID
        message: 用户消息
        tools: 可用工具列表
        
    Yields:
        str: SSE 格式的数据块
    """
```

**流式输出格式**:
- `event: heartbeat` - 心跳事件（保持连接）
- `event: thinking` - 思考过程可视化
- `event: tool_call` - 工具调用可视化
- `event: delta` - 增量更新
- `event: done` - 完成事件
- `event: error` - 错误事件

#### 2.1.16 ACPServer.switch_model()

```python
async def switch_model(
    self,
    session_id: str,
    model_id: str,
    config: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    切换模型
    
    Args:
        session_id: 会话 ID
        model_id: 目标模型 ID
        config: 模型配置
        
    Returns:
        bool: 是否成功切换
    """
```

#### 2.1.17 ACPServer.get_available_models()

```python
async def get_available_models(self) -> List[Dict[str, Any]]:
    """
    获取可用模型列表
    
    Returns:
        List[Dict[str, Any]]: 模型配置列表
    """
```

#### 2.1.18 ACPServer.detect_model_capabilities()

```python
async def detect_model_capabilities(self, model_id: str) -> List[str]:
    """
    探测模型能力
    
    Args:
        model_id: 模型 ID
        
    Returns:
        List[str]: 能力列表
    """
```

#### 2.1.19 ACPServer.update_session_config()

```python
async def update_session_config(
    self,
    session_id: str,
    new_config: Dict[str, Any],
) -> bool:
    """
    更新会话配置
    
    Args:
        session_id: 会话 ID
        new_config: 新配置
        
    Returns:
        bool: 是否成功更新
    """
```

#### 2.1.20 ACPServer.get_session_config()

```python
async def get_session_config(self, session_id: str) -> Optional[Dict[str, Any]]:
    """
    获取会话配置
    
    Args:
        session_id: 会话 ID
        
    Returns:
        Optional[Dict[str, Any]]: 会话配置字典
    """
```

#### 2.1.21 ACPServer.list_sessions()

```python
async def list_sessions(self) -> List[Dict[str, Any]]:
    """
    列出所有会话
    
    Returns:
        List[Dict[str, Any]]: 会话信息列表
    """
```

#### 2.1.22 get_acp_server()

```python
def get_acp_server() -> ACPServer:
    """
    获取 ACP Server 单例
    
    Returns:
        ACPServer: ACP Server 实例
    """
```

### 2.2 数据流图

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                           ACP Server 数据流                                 │
├─────────────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  客户端 (Zed/OpenCode/Web Console)                                         │
│           │                                                                 │
│           │ HTTP/WebSocket                                                  │
│           ▼                                                                 │
│  ┌─────────────────────────────────────────────────────────────────────┐      │
│  │  ACP Router (FastAPI)                                           │      │
│  │  /acp/session/new                                                │      │
│  │  /acp/session/load                                               │      │
│  │  /acp/session/resume                                             │      │
│  │  /acp/session/{session_id} (DELETE)                              │      │
│  │  /acp/session/{session_id}/status                                │      │
│  │  /acp/chat (SSE)                                                │      │
│  │  /acp/model/switch                                               │      │
│  │  /acp/sessions                                                   │      │
│  └─────────────────────────────────────────────────────────────────────┘      │
│           │                                                                 │
│           │ 调用                                                            │
│           ▼                                                                 │
│  ┌─────────────────────────────────────────────────────────────────────┐      │
│  │  ACPServer                                                      │      │
│  │  • create_session()                                              │      │
│  │  • load_session()                                                │      │
│  │  • resume_session()                                              │      │
│  │  • close_session()                                               │      │
│  │  • chat_stream()                                                 │      │
│  │  • switch_model()                                                │      │
│  │  • update_session_config()                                        │      │
│  └─────────────────────────────────────────────────────────────────────┘      │
│           │                                                                 │
│           │ 管理                                                            │
│           ▼                                                                 │
│  ┌─────────────────────────────────────────────────────────────────────┐      │
│  │  ACPSession (内存/持久化)                                      │      │
│  │  • session_id                                                    │      │
│  │  • agent_id                                                      │      │
│  │  • status                                                        │      │
│  │  • config (ACPSessionConfig)                                     │      │
│  │  • messages (List[ACPMessage])                                   │      │
│  └─────────────────────────────────────────────────────────────────────┘      │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

### 2.3 状态机

```
                ┌─────────────┐
                │   Created   │
                └──────┬──────┘
                       │ create_session()
                ┌──────▼──────┐
                │   Active    │◄──────┐
                └──────┬──────┘       │
                       │ close_session()
                ┌──────▼──────┐       │
                │   Closed    │       │
                └─────────────┘       │
                                      │
                      ┌───────────────┘
                      │ load_session() / resume_session()
                      ▼
                ┌─────────────┐
                │   Active    │
                └─────────────┘
```

---

## 3. 接口设计

### 3.1 API接口

| 接口路径 | 方法 | 说明 | 请求参数 | 返回格式 |
|---------|------|------|---------|----------|
| `/acp/session/new` | POST | 创建新会话 | `agent_id`, `config`, `metadata` | `session_id`, `status` |
| `/acp/session/load` | POST | 加载已有会话 | `session_id` | `session_id`, `status`, `config` |
| `/acp/session/resume` | POST | 恢复会话 | `session_id` | `session_id`, `status`, `config` |
| `/acp/session/{session_id}` | DELETE | 关闭会话 | 无 | `session_id` |
| `/acp/session/{session_id}/status` | GET | 获取会话状态 | 无 | `session_id`, `status`, `config`, `message_count` |
| `/acp/chat` | POST | 流式对话 (SSE) | `session_id`, `message`, `tools` | SSE 流 |
| `/acp/tool/call/result` | POST | 提交工具调用结果 | `call_id`, `result`, `success` | `call_id`, `received` |
| `/acp/model/switch` | POST | 切换模型 | `model_id`, `config` | `session_id`, `model_id` |
| `/acp/models` | GET | 获取可用模型列表 | 无 | `models`, `total` |
| `/acp/model/{model_id}/capabilities` | GET | 探测模型能力 | 无 | `model_id`, `capabilities` |
| `/acp/session/{session_id}/config` | PUT | 更新会话配置 | `config` | `session_id` |
| `/acp/session/{session_id}/config` | GET | 获取会话配置 | 无 | `config` |
| `/acp/sessions` | GET | 列出所有会话 | 无 | `sessions`, `total` |

### 3.2 SSE 流式输出格式

**1. 心跳事件**
```
event: heartbeat
data: {"status": "processing"}
```

**2. 思考过程事件**
```
event: thinking
data: {"step": 1, "content": "分析用户意图...", "total_steps": 4}
```

**3. 工具调用事件**
```
event: tool_call
data: {"tool_name": "search_tool", "tool_input": {...}, "call_id": "..."}
```

**4. 增量更新事件**
```
event: delta
data: {"content": "你", "done": false}
```

**5. 完成事件**
```
event: done
data: {"reply": "完整回复", "message_id": "...", "total_tokens": 100}
```

**6. 错误事件**
```
event: error
data: {"error": "错误信息"}
```

### 3.3 类接口

| 方法名 | 参数 | 返回值 | 说明 |
|--------|------|--------|------|
| `ACPServer()` | 无 | 无 | 初始化 ACP Server |
| `create_session()` | `agent_id`, `config`, `metadata` | `ACPSession` | 创建新会话 |
| `load_session()` | `session_id` | `Optional[ACPSession]` | 加载已有会话 |
| `resume_session()` | `session_id` | `Optional[ACPSession]` | 恢复会话 |
| `close_session()` | `session_id` | `bool` | 关闭会话 |
| `get_session_status()` | `session_id` | `Optional[Dict]` | 获取会话状态 |
| `chat_stream()` | `session_id`, `message`, `tools` | `AsyncGenerator` | 流式对话 |
| `switch_model()` | `session_id`, `model_id`, `config` | `bool` | 切换模型 |
| `get_available_models()` | 无 | `List[Dict]` | 获取可用模型列表 |
| `detect_model_capabilities()` | `model_id` | `List[str]` | 探测模型能力 |
| `update_session_config()` | `session_id`, `new_config` | `bool` | 更新会话配置 |
| `get_session_config()` | `session_id` | `Optional[Dict]` | 获取会话配置 |
| `list_sessions()` | 无 | `List[Dict]` | 列出所有会话 |

---

## 4. 实现细节

### 4.1 已完成的子任务

- [x] 创建数据类（ACPSession, ACPMessage, ACPStreamChunk, ACPToolCall, ACPToolResult, ACPThinkingStep, ACPModelConfig, ACPSessionConfig）
- [x] 实现 ACPServer 核心类
- [x] 实现会话管理功能（create/load/resume/close/status）
- [x] 实现流式输出（SSE 格式）
- [x] 实现思考过程可视化（thinking 事件）
- [x] 实现工具调用可视化（tool_call 事件）
- [x] 实现增量更新（delta 事件）
- [x] 实现模型切换功能
- [x] 实现模型能力探测
- [x] 实现配置管理（更新/获取）
- [x] 创建 FastAPI 路由（acp_router）
- [x] 编写单元测试（56个测试全部通过）

### 4.2 进行中的子任务

- [ ] 注册 ACP 路由到 `neurova/api/app.py`
- [ ] 更新 `docs/dev_progress/progress_tracker.md`

### 4.3 待完成的子任务

- [ ] 实现会话持久化存储（当前仅内存存储）
- [ ] 与 Cognition Orchestrator 集成（当前使用模拟回复）
- [ ] 实现真实的工具调用执行
- [ ] 添加性能测试
- [ ] 添加集成测试

### 4.4 关键代码片段

```python
# SSE 流式输出实现
async def chat_stream(...) -> AsyncGenerator[str, None]:
    # 1. 发送心跳事件
    yield heartbeat_chunk.to_sse_format()
    
    # 2. 发送思考过程
    for step in thinking_steps:
        yield thinking_chunk.to_sse_format()
    
    # 3. 发送工具调用（如果有）
    if tools:
        yield tool_call_chunk.to_sse_format()
    
    # 4. 增量输出回复
    for char in reply_text:
        yield delta_chunk.to_sse_format()
    
    # 5. 发送完成事件
    yield done_chunk.to_sse_format()
```

---

## 5. 测试计划

### 5.1 单元测试

| 测试用例 | 测试内容 | 状态 | 通过率 |
|---------|---------|------|--------|
| test_session_status_values | 测试会话状态枚举 | ✅ 通过 | 100% |
| test_message_role_values | 测试消息角色枚举 | ✅ 通过 | 100% |
| test_stream_event_type_values | 测试流事件类型枚举 | ✅ 通过 | 100% |
| test_acp_message_creation | 测试 ACPMessage 创建 | ✅ 通过 | 100% |
| test_acp_message_to_dict | 测试 ACPMessage.to_dict() | ✅ 通过 | 100% |
| test_acp_message_from_dict | 测试 ACPMessage.from_dict() | ✅ 通过 | 100% |
| test_stream_chunk_to_sse_format | 测试 SSE 格式转换 | ✅ 通过 | 100% |
| test_tool_call_creation | 测试 ACPToolCall 创建 | ✅ 通过 | 100% |
| test_tool_result_success | 测试 ACPToolResult 成功 | ✅ 通过 | 100% |
| test_session_config_default | 测试默认会话配置 | ✅ 通过 | 100% |
| test_session_creation | 测试 ACPSession 创建 | ✅ 通过 | 100% |
| test_session_add_message | 测试添加消息 | ✅ 通过 | 100% |
| test_server_creation | 测试 ACPServer 创建 | ✅ 通过 | 100% |
| test_create_session_basic | 测试创建会话 | ✅ 通过 | 100% |
| test_load_existing_session | 测试加载会话 | ✅ 通过 | 100% |
| test_close_session_success | 测试关闭会话 | ✅ 通过 | 100% |
| test_chat_stream_output | 测试流式输出 | ✅ 通过 | 100% |
| test_switch_model_success | 测试模型切换 | ✅ 通过 | 100% |
| test_get_available_models | 测试获取模型列表 | ✅ 通过 | 100% |
| test_update_config_success | 测试更新配置 | ✅ 通过 | 100% |
| ... | ... | ✅ 通过 | 100% |

**总计**: 56 个测试用例，56 个通过，0 个失败，通过率 100%

### 5.2 集成测试

1. **与 FastAPI 应用集成测试**：
   - 测试 ACP 路由正确注册
   - 测试 API 端点返回正确格式
   - 测试认证依赖正确工作

2. **与 Cognition Orchestrator 集成测试**（待实现）：
   - 测试真实 LLM 调用
   - 测试思考过程可视化
   - 测试工具调用执行

### 5.3 性能测试（待实现）

1. **并发会话测试**：
   - 测试多个会话并发创建
   - 测试多个会话并发流式输出

2. **SSE 流式输出性能测试**：
   - 测试流式输出速度
   - 测试内存占用

---

## 6. 已知问题

| 问题描述 | 严重程度 | 发现时间 | 解决方案 | 状态 |
|---------|---------|----------|--------|------|
| 会话仅存储在内存中，重启后丢失 | 中 | 2026-05-13 | 实现持久化存储 | 待解决 |
| 使用模拟回复，未集成真实 LLM | 低 | 2026-05-13 | 与 Cognition Orchestrator 集成 | 待解决 |
| 工具调用未真实执行 | 低 | 2026-05-13 | 实现工具调用执行逻辑 | 待解决 |

---

## 7. 变更记录

| 时间 | 变更内容 | 变更原因 | 影响范围 |
|------|---------|---------|---------|
| 2026-05-13 00:00 | 初始创建 | - | - |
| 2026-05-13 00:03 | 修复 `ACPRole` -> `ACPMessageRole` | 类名错误 | acp_server.py |
| 2026-05-13 00:04 | 修复 `ACPRMessage` -> `ACPMessage` | 类名错误 | acp_server.py |
| 2026-05-13 00:05 | 所有 56 个测试通过 | 修复 bug | test_acp_server.py |

---

## 8. 附录

### 8.1 参考资料

- `docs/NEUROVA_CogArch_2.0.md` 第2593-2630行：8.5.2 ACP 说明
- QwenPaw 设计文档：QwenPawACPAgent 实现
- [Server-Sent Events (SSE) 规范](https://html.spec.whatwg.org/multipage/server-sent-events.html)

### 8.2 相关文件

- `neurova/core/acp_server.py`：ACP Server 实现
- `tests/test_acp_server.py`：单元测试
- `neurova/api/app.py`：需要注册 ACP 路由（待修改）
- `docs/dev_progress/progress_tracker.md`：需要更新进度（待修改）

---

**最后更新**: 2026-05-13 00:05 | **更新人**: acp-dev
