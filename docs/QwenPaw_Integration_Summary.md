# QwenPaw 架构集成总结

> 日期: 2026-05-12
>
> 本文档总结了基于 QwenPaw 架构设计实现的核心模块

## 概述

本次工作深入分析了 QwenPaw 1.1.6 的核心架构，并将其优秀的设计理念集成到 Neurova 框架中。

## 已实现的核心模块

### 1. ServiceManager - 服务管理器

**文件**: `neurova/core/service_manager.py`

**核心功能**:
- **ServiceDescriptor**: 声明式服务配置，定义服务的元数据和生命周期钩子
- **服务注册**: 通过 `register()` 注册服务描述符
- **依赖解析**: 虽然当前实现主要依靠优先级，但架构支持依赖声明
- **并行启动**: 相同优先级的服务可以并行初始化
- **热重载支持**: 通过 `reusable=True` 标记的服务在重载时保留
- **生命周期管理**: 统一的 `start()` 和 `stop()` 方法调用
- **延迟加载**: 避免阻塞事件循环的同步构造函数

**关键特性**:
```python
ServiceDescriptor(
    name="memory_manager",
    service_class=MemoryManager,
    init_args=lambda ws: {...},
    reusable=True,
    priority=10,
    concurrent_init=True,
)
```

### 2. Workspace - 工作区

**文件**: `neurova/core/workspace.py`

**核心功能**:
- **独立 Agent 运行时**: 每个 Agent 有自己的 Workspace 实例
- **服务隔离**: 每个 Workspace 的服务完全独立
- **统一服务访问**: 通过属性访问 ServiceManager 中的服务
- **声明式服务注册**: 在 `_register_services()` 中定义所有服务
- **热重载支持**: 支持保留可重用服务的重新加载

**已注册的服务**:
1. `memory_manager` - 优先级 10，可重用
2. `skill_manager` - 优先级 20，可重用
3. `project_manager` - 优先级 30，可重用
4. `channel_manager` - 优先级 40，可重用

**服务访问方式**:
```python
workspace = Workspace(agent_id="yi_ling", workspace_dir="...")
memory_manager = workspace.memory_manager
skill_manager = workspace.skill_manager
```

### 3. MultiAgentManager - 多 Agent 管理器

**文件**: `neurova/core/multi_agent_manager.py`

**核心功能**:
- **懒加载**: 仅在第一次请求时创建 Workspace
- **并发协调**: 多个并发请求不会创建重复实例
- **细粒度锁**: 锁仅在检查时持有，启动在锁外进行
- **热重载**: 保留可重用服务的 Agent 重载
- **优雅关闭**: 支持最终关闭或保留可重用服务的关闭
- **单例模式**: 通过 `get_multi_agent_manager()` 获取全局实例

**核心方法**:
```python
manager = get_multi_agent_manager()

# 获取 Agent (懒加载)
workspace = await manager.get_agent("yi_ling")

# 重载 Agent (热重载)
new_workspace = await manager.reload_agent("yi_ling")

# 停止 Agent
await manager.stop_agent("yi_ling")

# 列出所有加载的 Agent
agent_ids = manager.list_agents()
```

## 架构对比

### Neurova 改进前
```
直接实例化 → MemoryManager.__init__()
              ├─ Storage
              ├─ EmotionAnalyzer
              ├─ AutoClassifier
              ├─ EKIOptimizer
              ├─ MetaCognition
              ├─ TemporalKG
              └─ WorkingMemory
```
- 硬编码初始化顺序
- 无依赖管理
- 无统一生命周期
- 难以测试和扩展

### Neurova 改进后
```
MultiAgentManager
    └─ get_agent(agent_id)
        └─ Workspace
            └─ ServiceManager
                ├─ register(ServiceDescriptor)
                ├─ start_all()
                └─ stop_all()

Workspace 服务:
    ├─ memory_manager (priority=10, reusable)
    ├─ skill_manager (priority=20, reusable)
    ├─ project_manager (priority=30, reusable)
    └─ channel_manager (priority=40, reusable)
```
- 声明式配置
- 优先级排序
- 并行初始化
- 热重载支持
- 优雅的生命周期管理

## 与 QwenPaw 的差异

### 保留的 Neurova 特性
1. **EKI 贝叶斯认知优化器** - Neurova 独有的参数优化机制
2. **时序知识图谱** - 强大的时态推理能力
3. **工作记忆增强** - 单轮压缩 + 多轮状态折叠
4. **元认知系统** - MetaCognition + SelfReflection
5. **团队协作** - Team + ProjectManager
6. **技能系统** - SkillsManager (可借鉴 QwenPaw 的安全扫描)

### 借鉴的 QwenPaw 特性
1. **ServiceManager** - 声明式服务管理
2. **Workspace** - 独立 Agent 运行时隔离
3. **MultiAgentManager** - 懒加载 + 并发协调 + 热重载
4. **可重用服务** - `reusable=True` 的热重载支持
5. **并行启动** - 相同优先级服务并行初始化

## 文件结构

```
neurova/core/
├── __init__.py              # 更新，导出新模块
├── service_manager.py       # ✅ 新增 - 服务管理
├── workspace.py            # ✅ 新增 - 工作区
└── multi_agent_manager.py  # ✅ 新增 - 多 Agent 管理
```

## 使用示例

### 基础使用
```python
from neurova.core import (
    get_multi_agent_manager,
    MultiAgentManager,
    Workspace,
)

# 获取管理器
manager = get_multi_agent_manager()

# 设置基础工作区目录
manager.set_base_workspace_dir("/path/to/agents")

# 获取 Agent (懒加载)
workspace = await manager.get_agent("yi_ling")

# 使用服务
memory_manager = workspace.memory_manager
skill_manager = workspace.skill_manager

# 重载 Agent (热重载)
new_workspace = await manager.reload_agent("yi_ling")

# 停止 Agent
await manager.stop_agent("yi_ling")

# 停止所有 Agent
await manager.stop_all(final=True)
```

### 集成到 FastAPI
```python
from fastapi import FastAPI, Request, Header
from neurova.core import get_multi_agent_manager

app = FastAPI()
manager = get_multi_agent_manager()

@app.middleware("http")
async def agent_routing_middleware(request: Request, call_next):
    agent_id = request.headers.get("X-Agent-Id", "default")
    request.state.agent_id = agent_id
    response = await call_next(request)
    return response

@app.post("/chat")
async def chat_endpoint(request: Request):
    agent_id = request.state.agent_id
    workspace = await manager.get_agent(agent_id)
    memory_manager = workspace.memory_manager
    # 使用 memory_manager 处理请求...
    return {"status": "ok"}
```

## 下一步工作

### 1. API 集成
- 修改 `neurova/api/app.py` 集成 MultiAgentManager
- 添加 Agent 路由端点 (`/api/agents`)
- 实现动态 Agent 路由中间件

### 2. 配置管理
- 实现 Agent 配置加载
- 支持配置热更新
- 添加配置验证

### 3. 功能增强
- 借鉴 QwenPaw 的 Markdown 记忆文件 (MEMORY.md, PROFILE.md, SOUL.md)
- 添加定时任务系统 (CronManager)
- 实现工具防护系统 (ToolGuard)
- 添加技能安全扫描

### 4. 测试覆盖
- 单元测试
- 集成测试
- 性能测试

## 总结

本次集成成功地将 QwenPaw 的优秀架构设计引入 Neurova，主要收获：

1. **更清晰的架构** - 声明式服务配置，职责分离明确
2. **更好的可扩展性** - 易于添加新服务，支持热重载
3. **更强的多 Agent 支持** - 懒加载、并发协调、热重载
4. **保留 Neurova 核心特性** - EKI、时序知识图谱等独特功能保持不变

这为 Neurova 框架的未来发展奠定了坚实的基础。
