# 实现计划和 API 规范

## 1. 项目结构

### 1.1 目录结构

```
neurova/
├── README.md
├── LICENSE
├── setup.py
├── requirements.txt
├── requirements-dev.txt
├── Dockerfile
├── docker-compose.yml
├── .trae/
│   └── project_rules.md
├── docs/
│   ├── architecture/
│   │   ├── 01-core-architecture.md
│   │   ├── 02-memory-system.md
│   │   ├── 03-message-routing.md
│   │   ├── 04-multi-agent-collaboration.md
│   │   ├── 05-skill-system.md
│   │   ├── 06-plugin-cli-system.md
│   │   └── 07-implementation-plan.md
│   ├── api/
│   │   └── api-reference.md
│   └── guides/
│       ├── quickstart.md
│       ├── user-guide.md
│       └── developer-guide.md
├── src/
│   └── neurova/
│       ├── __init__.py
│       ├── core/
│       │   ├── __init__.py
│       │   ├── agent.py
│       │   ├── orchestrator.py
│       │   ├── config.py
│       │   └── events.py
│       ├── memory/
│       │   ├── __init__.py
│       │   ├── manager.py
│       │   ├── models.py
│       │   ├── storage.py
│       │   └── emotion.py
│       ├── messaging/
│       │   ├── __init__.py
│       │   ├── router.py
│       │   ├── message.py
│       │   ├── event_bus.py
│       │   └── channels/
│       │       ├── __init__.py
│       │       ├── base.py
│       │       ├── wechat.py
│       │       ├── telegram.py
│       │       └── webhook.py
│       ├── llm/
│       │   ├── __init__.py
│       │   ├── base.py
│       │   ├── openai_provider.py
│       │   └── anthropic_provider.py
│       ├── skills/
│       │   ├── __init__.py
│       │   ├── manager.py
│       │   ├── base.py
│       │   ├── context.py
│       │   └── builtin/
│       │       ├── __init__.py
│       │       ├── search.py
│       │       ├── calculator.py
│       │       └── file_ops.py
│       ├── plugins/
│       │   ├── __init__.py
│       │   ├── manager.py
│       │   ├── models.py
│       │   └── loader.py
│       ├── cli/
│       │   ├── __init__.py
│       │   └── commands.py
│       ├── api/
│       │   ├── __init__.py
│       │   ├── server.py
│       │   └── routes/
│       │       ├── __init__.py
│       │       ├── agents.py
│       │       ├── skills.py
│       │       └── plugins.py
│       └── utils/
│           ├── __init__.py
│           ├── logging.py
│           ├── helpers.py
│           └── security.py
├── tests/
│   ├── __init__.py
│   ├── unit/
│   │   ├── test_agent.py
│   │   ├── test_memory.py
│   │   ├── test_skills.py
│   │   └── test_plugins.py
│   ├── integration/
│   │   ├── test_orchestrator.py
│   │   └── test_messaging.py
│   └── fixtures/
│       ├── config.yaml
│       └── skills/
├── examples/
│   ├── basic_agent.py
│   ├── multi_agent.py
│   ├── custom_skill.py
│   └── custom_plugin/
├── config/
│   ├── default.yaml
│   ├── development.yaml
│   └── production.yaml
├── data/
│   └── .gitkeep
└── logs/
    └── .gitkeep
```

## 2. 实现阶段

### 阶段 1: 核心框架 (MVP) - 2 周

#### 第一周：基础架构
- [ ] 项目结构搭建
- [ ] 配置系统实现
- [ ] 日志系统实现
- [ ] 事件总线实现
- [ ] 基础数据模型定义

#### 第二周：Agent 核心
- [ ] Agent 基类实现
- [ ] LLM 提供商抽象 (OpenAI, Anthropic)
- [ ] Agent 编排器实现
- [ ] 基础 CLI 命令
- [ ] 单元测试

**交付物:**
- 可运行的基础框架
- 支持单个 Agent 与 LLM 通信
- 基础 CLI 命令可用

### 阶段 2: 记忆系统 - 2 周

#### 第三周：记忆存储
- [ ] SQLite 存储层实现
- [ ] 记忆数据模型实现
- [ ] 记忆管理器实现
- [ ] 记忆索引和搜索

#### 第四周：记忆架构
- [ ] 短期/长期记忆管理
- [ ] 情感引擎实现
- [ ] 记忆巩固机制
- [ ] 记忆遗忘机制
- [ ] 集成测试

**交付物:**
- 完整的记忆系统
- 情感架构
- 记忆可视化 API

### 阶段 3: 消息路由 - 2 周

#### 第五周：消息系统
- [ ] 消息模型实现
- [ ] 消息路由器实现
- [ ] 路由规则引擎
- [ ] 限流器实现

#### 第六周：渠道适配
- [ ] 渠道适配器基类
- [ ] Webhook 适配器
- [ ] WebSocket 适配器
- [ ] 消息重试机制
- [ ] 性能优化

**交付物:**
- 完整的消息路由系统
- 支持 Webhook 和 WebSocket
- 限流和重试机制

### 阶段 4: Skill 系统 - 2 周

#### 第七周：Skill 核心
- [ ] Skill 抽象基类
- [ ] Skill 管理器
- [ ] Skill 上下文
- [ ] 参数验证

#### 第八周：内置 Skill
- [ ] 搜索 Skill
- [ ] 计算器 Skill
- [ ] 文件操作 Skill
- [ ] OpenClaw 兼容层
- [ ] Qwenpaw 兼容层

**交付物:**
- Skill 系统
- 3 个内置 Skill
- 协议兼容层

### 阶段 5: 多 Agent 协作 - 2 周

#### 第九周：协作机制
- [ ] Agent 间通信
- [ ] 任务管理器
- [ ] 任务分配算法
- [ ] 协调 Agent

#### 第十周：高级功能
- [ ] 任务分解
- [ ] 工作流引擎
- [ ] Agent 群组
- [ ] 信息风暴防护
- [ ] 集成测试

**交付物:**
- 多 Agent 协作系统
- 工作流引擎
- 群组讨论功能

### 阶段 6: 插件系统 - 2 周

#### 第十一周：插件核心
- [ ] 插件管理器
- [ ] 插件加载器
- [ ] 插件生命周期
- [ ] 钩子系统

#### 第十二周：CLI 和 API
- [ ] 完整 CLI 实现
- [ ] RESTful API
- [ ] API 文档
- [ ] 插件仓库
- [ ] 文档完善

**交付物:**
- 完整的插件系统
- CLI 工具
- RESTful API
- 完整文档

## 3. API 规范

### 3.1 RESTful API

#### 基础信息
- Base URL: `http://localhost:8081/api/v1`
- 认证：Bearer Token
- 内容类型：application/json

#### 端点

##### Agent 管理

```http
GET /agents
```
列出所有 Agent

**响应:**
```json
{
  "success": true,
  "data": {
    "agents": [
      {
        "id": "agent_123",
        "name": "Assistant",
        "status": "idle",
        "role": "worker"
      }
    ],
    "total": 1
  }
}
```

```http
POST /agents
```
创建 Agent

**请求:**
```json
{
  "name": "New Agent",
  "config": {
    "llm_provider": "openai",
    "llm_model": "gpt-4",
    "skills": ["search", "calculator"]
  }
}
```

```http
GET /agents/{agent_id}
```
获取 Agent 详情

```http
DELETE /agents/{agent_id}
```
删除 Agent

```http
POST /agents/{agent_id}/tasks
```
创建任务

**请求:**
```json
{
  "title": "Analyze data",
  "description": "Analyze the sales data",
  "content": "Please analyze Q4 sales data",
  "priority": 3
}
```

```http
GET /agents/{agent_id}/tasks
```
获取任务列表

```http
GET /agents/{agent_id}/status
```
获取 Agent 状态

##### Skill 管理

```http
GET /skills
```
列出所有 Skill

**查询参数:**
- `category`: 分类过滤
- `tag`: 标签过滤

**响应:**
```json
{
  "success": true,
  "data": {
    "skills": [
      {
        "id": "search",
        "name": "Web Search",
        "description": "Search the web",
        "category": "search",
        "tags": ["search", "web"]
      }
    ],
    "total": 10
  }
}
```

```http
GET /skills/{skill_id}
```
获取 Skill 详情

```http
POST /skills/{skill_id}/execute
```
执行 Skill

**请求:**
```json
{
  "agent_id": "agent_123",
  "params": {
    "query": "Python tutorial",
    "num_results": 5
  }
}
```

**响应:**
```json
{
  "success": true,
  "data": {
    "results": [
      {
        "title": "Python Tutorial",
        "url": "https://...",
        "snippet": "..."
      }
    ]
  },
  "metadata": {
    "execution_time": 1.23,
    "tokens_used": 100
  }
}
```

##### 插件管理

```http
GET /plugins
```
列出所有插件

```http
POST /plugins/install
```
安装插件

**请求:**
```json
{
  "source": "plugin-name",
  "version": "1.0.0"
}
```

```http
POST /plugins/{plugin_id}/enable
```
启用插件

```http
POST /plugins/{plugin_id}/disable
```
禁用插件

```http
DELETE /plugins/{plugin_id}
```
卸载插件

##### 消息

```http
POST /messages
```
发送消息

**请求:**
```json
{
  "agent_id": "agent_123",
  "content": "Hello",
  "type": "text"
}
```

```http
GET /messages
```
获取消息历史

**查询参数:**
- `agent_id`: Agent ID
- `limit`: 数量限制
- `offset`: 偏移量

##### 系统

```http
GET /status
```
获取系统状态

**响应:**
```json
{
  "success": true,
  "data": {
    "version": "1.0.0",
    "uptime": 3600,
    "agents": {
      "total": 5,
      "online": 3
    },
    "skills": {
      "total": 10
    },
    "plugins": {
      "enabled": 5
    },
    "memory": {
      "usage_mb": 256.5
    }
  }
}
```

```http
GET /health
```
健康检查

**响应:**
```json
{
  "status": "healthy",
  "timestamp": "2026-05-05T10:00:00Z"
}
```

### 3.2 WebSocket API

#### 连接
```
ws://localhost:8081/ws/v1
```

#### 消息格式

**客户端 → 服务端:**
```json
{
  "type": "subscribe",
  "data": {
    "channel": "agent.agent_123"
  }
}
```

**服务端 → 客户端:**
```json
{
  "type": "message",
  "data": {
    "agent_id": "agent_123",
    "content": "Hello",
    "timestamp": "2026-05-05T10:00:00Z"
  }
}
```

#### 事件类型

- `subscribe`: 订阅频道
- `unsubscribe`: 取消订阅
- `message`: 发送消息
- `agent_status`: Agent 状态变更
- `task_update`: 任务更新

### 3.3 Python SDK

#### 初始化

```python
from neurova import neurovaClient

client = neurovaClient(
    base_url="http://localhost:8081",
    api_key="your-api-key"
)
```

#### Agent 操作

```python
# 列出 Agent
agents = client.agents.list()

# 创建 Agent
agent = client.agents.create(
    name="Assistant",
    config={
        "llm_provider": "openai",
        "llm_model": "gpt-4"
    }
)

# 获取 Agent
agent = client.agents.get("agent_123")

# 发送消息
response = client.agents.send_message(
    agent_id="agent_123",
    content="Hello"
)

# 创建任务
task = client.agents.create_task(
    agent_id="agent_123",
    title="Analyze data",
    description="Analyze sales data"
)

# 等待任务完成
result = task.wait(timeout=60)
```

#### Skill 操作

```python
# 列出 Skill
skills = client.skills.list()

# 获取 Skill 详情
skill = client.skills.get("search")

# 执行 Skill
result = client.skills.execute(
    skill_id="search",
    agent_id="agent_123",
    params={
        "query": "Python tutorial"
    }
)

print(result.data)
```

#### 插件操作

```python
# 列出插件
plugins = client.plugins.list()

# 安装插件
plugin = client.plugins.install("plugin-name")

# 启用插件
client.plugins.enable("plugin-name")

# 禁用插件
client.plugins.disable("plugin-name")
```

#### WebSocket 订阅

```python
from neurova import WebSocketClient

ws = WebSocketClient("ws://localhost:8081/ws/v1")

@ws.on('message')
def handle_message(data):
    print(f"Received: {data}")

@ws.on('agent_status')
def handle_status(data):
    print(f"Agent status: {data}")

ws.subscribe("agent.agent_123")
ws.connect()
```

## 4. 数据库设计

### 4.1 SQLite 表结构

#### agents 表
```sql
CREATE TABLE agents (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    config TEXT NOT NULL,  -- JSON
    status TEXT NOT NULL,
    role TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### memories 表
```sql
CREATE TABLE memories (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    type TEXT NOT NULL,
    category TEXT NOT NULL,
    content TEXT NOT NULL,
    weight REAL DEFAULT 1.0,
    emotion_score REAL DEFAULT 0.0,
    access_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP,
    FOREIGN KEY (agent_id) REFERENCES agents(id)
);

CREATE INDEX idx_memories_agent ON memories(agent_id);
CREATE INDEX idx_memories_type ON memories(type);
```

#### tasks 表
```sql
CREATE TABLE tasks (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    content TEXT,
    status TEXT NOT NULL,
    priority INTEGER DEFAULT 1,
    result TEXT,
    error TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    FOREIGN KEY (agent_id) REFERENCES agents(id)
);
```

#### plugins 表
```sql
CREATE TABLE plugins (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    version TEXT NOT NULL,
    manifest TEXT NOT NULL,  -- JSON
    status TEXT NOT NULL,
    installed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

## 5. 测试策略

### 5.1 单元测试

```python
# tests/unit/test_agent.py
import pytest
from neurova.core import Agent, AgentConfig

def test_agent_creation():
    config = AgentConfig(
        name="Test Agent",
        llm_provider="openai",
        llm_model="gpt-4"
    )
    agent = Agent(config)
    
    assert agent.config.name == "Test Agent"
    assert agent.status == AgentStatus.OFFLINE

def test_agent_initialization():
    config = AgentConfig(name="Test")
    agent = Agent(config)
    agent.initialize()
    
    assert agent.status == AgentStatus.IDLE
```

### 5.2 集成测试

```python
# tests/integration/test_orchestrator.py
import pytest
from neurova import neurovaFramework

@pytest.fixture
def framework():
    config = load_test_config()
    framework = neurovaFramework(config)
    yield framework
    framework.stop()

def test_agent_lifecycle(framework):
    # 创建 Agent
    agent = framework.orchestrator.create_agent(
        AgentConfig(name="Test")
    )
    
    # 发送消息
    response = framework.send_message(
        agent_id=agent.config.id,
        content="Hello"
    )
    
    assert response is not None
    assert response.content != ""
    
    # 销毁 Agent
    framework.orchestrator.destroy_agent(agent.config.id)
```

### 5.3 性能测试

```python
# tests/performance/test_messaging.py
import pytest
import time

def test_message_throughput(framework):
    """测试消息吞吐量"""
    start = time.time()
    
    # 发送 1000 条消息
    for i in range(1000):
        framework.send_message(
            agent_id="agent_123",
            content=f"Message {i}"
        )
    
    elapsed = time.time() - start
    throughput = 1000 / elapsed
    
    assert throughput > 100  # 至少 100 条/秒
```

## 6. 部署方案

### 6.1 Docker 部署

```dockerfile
# Dockerfile
FROM python:3.11-slim

WORKDIR /app

# 安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制代码
COPY . .

# 创建数据目录
RUN mkdir -p /app/data /app/logs

# 暴露端口
EXPOSE 8080 8081

# 启动命令
CMD ["python", "-m", "neurova.cli", "start"]
```

```yaml
# docker-compose.yml
version: '3.8'

services:
  neurova:
    build: .
    ports:
      - "8080:8080"
      - "8081:8081"
    volumes:
      - ./config:/app/config
      - ./data:/app/data
      - ./logs:/app/logs
    environment:
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
    restart: unless-stopped
```

### 6.2 生产部署

```yaml
# Kubernetes 部署
apiVersion: apps/v1
kind: Deployment
metadata:
  name: neurova
spec:
  replicas: 3
  selector:
    matchLabels:
      app: neurova
  template:
    metadata:
      labels:
        app: neurova
    spec:
      containers:
      - name: neurova
        image: neurova/neurova:latest
        ports:
        - containerPort: 8080
        - containerPort: 8081
        env:
        - name: OPENAI_API_KEY
          valueFrom:
            secretKeyRef:
              name: api-secrets
              key: openai-key
        volumeMounts:
        - name: data
          mountPath: /app/data
      volumes:
      - name: data
        persistentVolumeClaim:
          claimName: neurova-data
```

## 7. 监控和日志

### 7.1 指标收集

```python
from prometheus_client import Counter, Histogram, Gauge

# 定义指标
AGENT_COUNT = Gauge('neurova_agents_total', 'Total number of agents')
MESSAGE_COUNT = Counter('neurova_messages_total', 'Total messages', ['type'])
SKILL_EXECUTION_TIME = Histogram('neurova_skill_execution_seconds', 'Skill execution time')
MEMORY_USAGE = Gauge('neurova_memory_usage_bytes', 'Memory usage in bytes')

# 记录指标
def record_message(type: str):
    MESSAGE_COUNT.labels(type=type).inc()

def record_skill_execution(duration: float):
    SKILL_EXECUTION_TIME.observe(duration)
```

### 7.2 日志配置

```yaml
# logging.yaml
version: 1
disable_existing_loggers: false

formatters:
  standard:
    format: '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
  json:
    format: '%(message)s'
    class: pythonjsonlogger.jsonlogger.JsonFormatter

handlers:
  console:
    class: logging.StreamHandler
    level: INFO
    formatter: standard
    stream: ext://sys.stdout
  
  file:
    class: logging.handlers.RotatingFileHandler
    level: DEBUG
    formatter: json
    filename: logs/neurova.log
    maxBytes: 10485760
    backupCount: 5

loggers:
  neurova:
    level: INFO
    handlers: [console, file]
    propagate: no
```

## 8. 安全考虑

### 8.1 认证和授权

```python
from functools import wraps
from flask import request, jsonify
import jwt

def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('Authorization')
        
        if not token:
            return jsonify({'error': 'Token missing'}), 401
        
        try:
            token = token.split(' ')[1]  # Bearer <token>
            data = jwt.decode(token, SECRET_KEY, algorithms=['HS256'])
            request.current_user = data
        except jwt.ExpiredSignatureError:
            return jsonify({'error': 'Token expired'}), 401
        except jwt.InvalidTokenError:
            return jsonify({'error': 'Invalid token'}), 401
        
        return f(*args, **kwargs)
    
    return decorated
```

### 8.2 输入验证

```python
from marshmallow import Schema, fields, validate

class MessageSchema(Schema):
    content = fields.Str(required=True, validate=validate.Length(max=4096))
    type = fields.Str(validate=validate.OneOf(['text', 'image', 'voice']))
    agent_id = fields.Str(required=True)

# 使用
schema = MessageSchema()
result = schema.load(request.json)
```

### 8.3 API 限流

```python
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(
    app,
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"]
)

@app.route("/api/v1/messages", methods=["POST"])
@limiter.limit("10 per minute")
def send_message():
    pass
```

## 9. 文档完善

### 9.1 文档清单

- [ ] README.md - 项目介绍
- [ ] INSTALL.md - 安装指南
- [ ] QUICKSTART.md - 快速开始
- [ ] CONFIGURATION.md - 配置说明
- [ ] API.md - API 文档
- [ ] SDK.md - SDK 使用指南
- [ ] PLUGIN_DEV.md - 插件开发指南
- [ ] SKILL_DEV.md - Skill 开发指南
- [ ] DEPLOYMENT.md - 部署指南
- [ ] TROUBLESHOOTING.md - 故障排除
- [ ] CHANGELOG.md - 变更日志
- [ ] CONTRIBUTING.md - 贡献指南

### 9.2 示例代码

- [ ] 基础 Agent 示例
- [ ] 多 Agent 协作示例
- [ ] 自定义 Skill 示例
- [ ] 自定义插件示例
- [ ] Webhook 集成示例
- [ ] WebSocket 集成示例

## 10. 发布计划

### v0.1.0 (Alpha) - 第 4 周
- 核心框架
- 基础记忆系统
- 单个 Agent 支持

### v0.2.0 (Beta) - 第 8 周
- 完整记忆系统
- 消息路由
- 基础 Skill 系统

### v0.3.0 (Beta) - 第 12 周
- 多 Agent 协作
- 完整插件系统
- CLI 和 API

### v1.0.0 (GA) - 第 14 周
- 生产就绪
- 完整文档
- 性能优化

### v1.1.0 - 后续
- 高级监控
- 性能优化
- 更多内置 Skill

### v2.0.0 - 规划
- 分布式支持
- 集群模式
- 更多渠道适配器
