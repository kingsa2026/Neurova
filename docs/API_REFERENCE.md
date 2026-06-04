# Neurova API 接口文档

> **版本**: v1.0.0  
> **基础路径**: `/api/v1`  
> **协议**: HTTP/HTTPS  
> **数据格式**: JSON  
> **最后更新**: 2026-05-08

---

## 目录

1. [认证接口](#1-认证接口)
2. [对话接口](#2-对话接口)
3. [记忆管理接口](#3-记忆管理接口)
4. [配置接口](#4-配置接口)
5. [Agent 接口](#5-agent-接口)
6. [技能接口](#6-技能接口)
7. [渠道接口](#7-渠道接口)
8. [心愿接口](#8-心愿接口)
9. [协作接口](#9-协作接口)
10. [任务调度接口](#10-任务调度接口)
11. [日志接口](#11-日志接口)
12. [系统接口](#12-系统接口)

---

## 通用说明

### 响应格式

所有接口统一返回以下 JSON 格式：

```json
{
  "success": true,
  "data": {},
  "error": null,
  "message": "操作成功"
}
```

**字段说明**:
- `success` (boolean): 请求是否成功
- `data` (any): 成功时返回的数据
- `error` (string): 失败时的错误信息
- `message` (string): 附加说明信息

### HTTP 状态码

| 状态码 | 说明 |
|--------|------|
| 200 | 请求成功 |
| 400 | 请求参数错误 |
| 401 | 未授权 |
| 404 | 资源不存在 |
| 500 | 服务器内部错误 |

### 认证

需要在请求头中添加 Token：

```
Authorization: Bearer <your_token>
```

---

## 1. 认证接口

### 1.1 用户登录

**POST** `/api/v1/auth/login`

**请求体**:
```json
{
  "username": "string",
  "password": "string"
}
```

**响应**:
```json
{
  "success": true,
  "data": {
    "token": "string",
    "refresh_token": "string",
    "expires_in": 3600
  }
}
```

### 1.2 刷新 Token

**POST** `/api/v1/auth/refresh`

**请求体**:
```json
{
  "refresh_token": "string"
}
```

---

## 2. 对话接口

### 2.1 发送消息

**POST** `/api/chat`

**请求体**:
```json
{
  "message": "string",
  "agent_name": "string (可选)",
  "agent_id": "string (可选)"
}
```

**响应**:
```json
{
  "success": true,
  "response": "string",
  "agent_name": "string",
  "timestamp": "2026-05-08T10:00:00"
}
```

### 2.2 获取对话历史

**GET** `/api/chat/history?agent_id=xxx`

**响应**:
```json
{
  "success": true,
  "messages": [
    {
      "role": "user|assistant",
      "content": "string",
      "timestamp": "2026-05-08T10:00:00"
    }
  ]
}
```

### 2.3 流式对话 (SSE)

**POST** `/api/chat/stream`

**请求体**:
```json
{
  "message": "string",
  "agent_id": "string (可选)"
}
```

**响应**: Server-Sent Events 流

---

## 3. 记忆管理接口

### 3.1 获取记忆列表

**GET** `/api/v1/memories`

**查询参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| query | string | 否 | 搜索关键词 |
| category | string | 否 | 分类筛选 |
| min_temperature | int | 否 | 最低温度 |
| limit | int | 否 | 返回数量 (默认 50) |
| offset | int | 否 | 偏移量 (默认 0) |

**响应**:
```json
{
  "success": true,
  "count": 10,
  "total": 128,
  "memories": [
    {
      "id": "mem_xxx",
      "content": "string",
      "category": "conversation|fact|profile|...",
      "temperature": 85,
      "source": "用户陈述|AI 推断|系统记录",
      "created_at": "2026-05-08T10:00:00",
      "updated_at": "2026-05-08T10:00:00"
    }
  ]
}
```

### 3.2 获取单个记忆

**GET** `/api/v1/memories/{memory_id}`

**响应**:
```json
{
  "success": true,
  "memory": {
    "id": "mem_xxx",
    "content": "string",
    "category": "conversation",
    "temperature": 85,
    "created_at": "2026-05-08T10:00:00"
  }
}
```

### 3.3 创建记忆

**POST** `/api/v1/memories`

**请求体**:
```json
{
  "content": "string",
  "category": "conversation (可选，默认 conversation)",
  "source": "string (可选)",
  "temperature": 50 (可选)
}
```

**响应**:
```json
{
  "success": true,
  "memory_id": "mem_xxx",
  "timestamp": "2026-05-08T10:00:00"
}
```

### 3.4 删除记忆

**DELETE** `/api/v1/memories/{memory_id}`

**响应**:
```json
{
  "success": true,
  "message": "记忆已删除",
  "memory_id": "mem_xxx"
}
```

### 3.5 搜索记忆

**GET** `/api/v1/memories/search?query=xxx&limit=10`

**查询参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| query | string | 是 | 搜索关键词 |
| limit | int | 否 | 返回数量 (默认 10) |

**响应**:
```json
{
  "success": true,
  "count": 5,
  "query": "xxx",
  "memories": [...]
}
```

### 3.6 获取记忆统计

**GET** `/api/v1/memories/stats`

**响应**:
```json
{
  "success": true,
  "stats": {
    "total": 128,
    "by_category": {
      "conversation": 50,
      "fact": 30,
      "profile": 20
    },
    "by_temperature": {
      "hot": 15,
      "warm": 45,
      "cold": 68
    }
  }
}
```

### 3.7 获取记忆配置

**GET** `/api/v1/memory/config`

**响应**:
```json
{
  "success": true,
  "config": {
    "decay_rate": 0.1,
    "max_temperature": 100,
    "consolidation_threshold": 80,
    "hot_threshold": 50
  }
}
```

### 3.8 更新记忆配置

**PUT** `/api/v1/memory/config`

**请求体**:
```json
{
  "decay_rate": 0.1,
  "max_temperature": 100
}
```

### 3.9 获取温度配置

**GET** `/api/v1/memory/config/temperature`

**响应**:
```json
{
  "success": true,
  "config": {
    "decay_rate": 0.1,
    "max_temperature": 100,
    "consolidation_threshold": 80,
    "hot_threshold": 50
  }
}
```

### 3.10 更新温度配置

**POST** `/api/v1/memory/config/temperature`

**请求体**:
```json
{
  "decay_rate": 0.15,
  "hot_threshold": 60
}
```

### 3.11 获取记忆关联

**GET** `/api/v1/memory/associations`

**响应**:
```json
{
  "success": true,
  "associations": [
    {
      "memory_id": "mem_xxx",
      "related_ids": ["mem_yyy", "mem_zzz"]
    }
  ]
}
```

### 3.12 获取记忆版本

**GET** `/api/v1/memory/versions/{memory_id}`

**响应**:
```json
{
  "success": true,
  "memory_id": "mem_xxx",
  "versions": [
    {
      "version": 1,
      "content": "string",
      "created_at": "2026-05-01T10:00:00",
      "updated_at": "2026-05-01T10:00:00"
    }
  ]
}
```

### 3.13 获取记忆流

**GET** `/api/v1/memory/stream?limit=50&type=xxx`

**查询参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| limit | int | 否 | 返回数量 (默认 50) |
| type | string | 否 | 记忆类型 |

### 3.14 获取记忆流统计

**GET** `/api/v1/memory/stream/stats`

### 3.15 元认知监控

**GET** `/api/v1/memory/meta-cognition/monitor`

### 3.16 元认知反思

**POST** `/api/v1/memory/meta-cognition/reflect`

### 3.17 元认知优化

**POST** `/api/v1/memory/meta-cognition/optimize`

### 3.18 元认知健康检查

**GET** `/api/v1/memory/meta-cognition/health`

### 3.19 旧版接口（向后兼容）

**POST** `/api/remember` - 添加记忆  
**GET** `/api/memories?query=xxx` - 搜索记忆

---

## 4. 配置接口

### 4.1 获取系统配置

**GET** `/api/v1/config/system`

**响应**:
```json
{
  "success": true,
  "data": {
    "host": "0.0.0.0",
    "port": 9527,
    "debug": true,
    "cors_origins": "*",
    "log_level": "INFO"
  }
}
```

### 4.2 更新系统配置

**PUT** `/api/v1/config/system`

**请求体**:
```json
{
  "host": "0.0.0.0",
  "port": 9527,
  "debug": true,
  "cors_origins": "*",
  "log_level": "DEBUG"
}
```

### 4.3 获取 LLM 配置

**GET** `/api/v1/config/llm`

**响应**:
```json
{
  "success": true,
  "data": {
    "provider": "OpenAI",
    "model": "gpt-4",
    "api_key": "***",
    "temperature": 0.7,
    "max_tokens": 4000
  }
}
```

### 4.4 更新 LLM 配置

**POST** `/api/v1/config/llm`

**请求体**:
```json
{
  "provider": "OpenAI",
  "model": "gpt-4",
  "temperature": 0.7,
  "max_tokens": 4000
}
```

### 4.5 测试 LLM 配置

**POST** `/api/v1/config/llm/test`

**请求体**:
```json
{
  "provider": "OpenAI",
  "model": "gpt-4",
  "api_key": "sk-xxx"
}
```

**响应**:
```json
{
  "success": true,
  "message": "LLM 连接测试成功",
  "response_time": 1.2
}
```

### 4.6 获取心跳配置

**GET** `/api/v1/config/heartbeat`

### 4.7 保存心跳配置

**POST** `/api/v1/config/heartbeat`

### 4.8 获取睡眠配置

**GET** `/api/v1/sleep/config`

**响应**:
```json
{
  "success": true,
  "config": {
    "auto_sleep": true,
    "sleep_threshold": 30,
    "wake_threshold": 70,
    "sleep_interval": 3600
  }
}
```

### 4.9 保存睡眠配置

**POST** `/api/v1/sleep/config`

---

## 5. Agent 接口

### 5.1 获取 Agent 列表

**GET** `/api/v1/agents`

**响应**:
```json
{
  "success": true,
  "agents": [
    {
      "id": "Yiling",
      "name": "一号",
      "status": "active",
      "description": "Neurova 核心 Agent",
      "created_at": "2026-05-01"
    }
  ]
}
```

### 5.2 获取单个 Agent

**GET** `/api/v1/agents/{agent_id}`

### 5.3 创建 Agent

**POST** `/api/v1/agents`

**请求体**:
```json
{
  "id": "string",
  "name": "string",
  "description": "string (可选)",
  "config": {} (可选)
}
```

### 5.4 更新 Agent

**PUT** `/api/v1/agents/{agent_id}`

### 5.5 删除 Agent

**DELETE** `/api/v1/agents/{agent_id}`

---

## 6. 技能接口

### 6.1 获取技能列表

**GET** `/api/v1/skills`

**响应**:
```json
{
  "success": true,
  "skills": [
    {
      "id": "skill-1",
      "name": "记忆检索",
      "description": "从记忆库中检索相关信息"
    }
  ]
}
```

### 6.2 获取单个技能

**GET** `/api/v1/skills/{skill_id}`

### 6.3 执行技能

**POST** `/api/v1/skills/{skill_id}/execute`

**请求体**:
```json
{
  "params": {}
}
```

**响应**:
```json
{
  "success": true,
  "result": "string"
}
```

### 6.4 导入技能

**POST** `/api/v1/skills/import`

---

## 7. 渠道接口

### 7.1 获取渠道列表

**GET** `/api/v1/channels`

### 7.2 获取单个渠道

**GET** `/api/v1/channels/{channel_id}`

### 7.3 创建渠道

**POST** `/api/v1/channels`

### 7.4 更新渠道

**PUT** `/api/v1/channels/{channel_id}`

### 7.5 删除渠道

**DELETE** `/api/v1/channels/{channel_id}`

### 7.6 切换渠道状态

**POST** `/api/v1/channels/{channel_id}/toggle`

---

## 8. 心愿接口

### 8.1 获取心愿列表

**GET** `/api/v1/wishes`

**响应**:
```json
{
  "success": true,
  "wishes": [
    {
      "id": "wish-1",
      "title": "string",
      "status": "pending|in_progress|completed",
      "created_at": "2026-05-08",
      "completed_at": "2026-05-08 (可选)",
      "progress": 0 (可选)
    }
  ]
}
```

### 8.2 创建心愿

**POST** `/api/v1/wishes`

**请求体**:
```json
{
  "title": "string",
  "description": "string (可选)"
}
```

### 8.3 更新心愿

**PUT** `/api/v1/wishes/{wish_id}`

### 8.4 删除心愿

**DELETE** `/api/v1/wishes/{wish_id}`

### 8.5 完成心愿

**POST** `/api/v1/wishes/{wish_id}/complete`

---

## 9. 协作接口

### 9.1 获取任务列表

**GET** `/api/v1/collaboration/tasks`

**响应**:
```json
{
  "success": true,
  "tasks": [
    {
      "id": "task-1",
      "title": "string",
      "assignee": "string",
      "status": "todo|doing|done",
      "priority": "low|medium|high"
    }
  ]
}
```

### 9.2 创建任务

**POST** `/api/v1/collaboration/tasks`

### 9.3 更新任务

**PUT** `/api/v1/collaboration/tasks/{task_id}`

### 9.4 删除任务

**DELETE** `/api/v1/collaboration/tasks/{task_id}`

### 9.5 获取工作流

**GET** `/api/v1/collaboration/workflows`

### 9.6 创建工作流

**POST** `/api/v1/collaboration/workflows`

### 9.7 获取团队信息

**GET** `/api/v1/collaboration/team`

### 9.8 获取讨论

**GET** `/api/v1/collaboration/discussions`

### 9.9 创建讨论

**POST** `/api/v1/collaboration/discussions`

### 9.10 获取协作记录

**GET** `/api/v1/collaboration/records`

---

## 10. 任务调度接口

### 10.1 获取任务列表

**GET** `/api/v1/scheduler/tasks`

### 10.2 创建任务

**POST** `/api/v1/scheduler/tasks`

### 10.3 更新任务

**PUT** `/api/v1/scheduler/tasks/{task_id}`

### 10.4 删除任务

**DELETE** `/api/v1/scheduler/tasks/{task_id}`

### 10.5 切换任务状态

**POST** `/api/v1/scheduler/tasks/{task_id}/toggle`

---

## 11. 日志接口

### 11.1 获取系统日志

**GET** `/api/v1/logs?level=INFO&limit=50`

**查询参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| level | string | 否 | 日志级别 (DEBUG/INFO/WARN/ERROR) |
| limit | int | 否 | 返回数量 (默认 50) |

**响应**:
```json
{
  "success": true,
  "logs": [
    {
      "level": "INFO",
      "timestamp": "2026-05-08T10:00:00",
      "message": "string"
    }
  ]
}
```

---

## 12. 系统接口

### 12.1 健康检查

**GET** `/health`

**响应**:
```json
{
  "status": "healthy",
  "timestamp": "2026-05-08T10:00:00",
  "version": "1.0.0",
  "uptime": 3600,
  "memory_mb": 150.5
}
```

### 12.2 系统统计

**GET** `/api/v1/stats`

---

## 附录

### 记忆分类枚举

| 值 | 说明 |
|----|------|
| conversation | 对话 |
| fact | 事实 |
| profile | 画像 |
| relationship | 关系 |
| skill | 技能 |
| task | 任务 |
| instruction | 指令 |

### 记忆来源枚举

| 值 | 说明 |
|----|------|
| 用户陈述 | 用户直接提供 |
| AI 推断 | AI 分析推断 |
| 系统记录 | 系统自动生成 |

### 错误码说明

| 错误码 | 说明 |
|--------|------|
| 400 | 请求参数错误 |
| 401 | 未授权访问 |
| 403 | 权限不足 |
| 404 | 资源不存在 |
| 500 | 服务器内部错误 |

---

## 更新日志

### v1.0.0 (2026-05-08)
- 初始版本
- 统一 RESTful API 规范
- 添加所有核心模块接口
- 添加 Mock 接口支持前端开发
- 保持向后兼容旧版接口
