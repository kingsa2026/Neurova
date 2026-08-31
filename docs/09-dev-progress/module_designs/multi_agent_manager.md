# MultiAgentManager 设计文档

> **模块ID**: Task1-MultiAgentManager  
> **创建时间**: 2026-05-12 21:00  
> **最后更新**: 2026-05-12 23:45  
> **负责人**: multi-agent-dev  
> **状态**: ✅ 已完成

---

## 1. 模块概述

### 1.1 功能描述

MultiAgentManager 是 Neurova CogArch 2.0 多 Agent 架构的核心管理模块，负责：
- 管理多个 Agent 的生命周期（启动、停止、重载）
- 实现 Lazy Loading（懒加载）机制，Agent 只在第一次请求时创建
- 提供并行启动能力，多个 Agent 通过细粒度锁并行初始化
- 支持 Hot Reload（热重载），单个 Agent 重载不影响其他 Agent
- 实现认知-执行闭环：每个 Agent 有独立的大脑（Memory DB）和办公室（Workspace），但共用小脑（PlanOrchestrator）、脑干（ExecutionEngine）和脊髓（Infrastructure）

### 1.2 设计依据

- **NEUROVA_CogArch_2.0.md 第2章**：多 Agent 架构设计（大脑/办公室 + 共用小脑/脑干/脊髓）
- **QwenPaw 设计**：借鉴其 MultiAgentManager 的 Lazy Loading、细粒度锁、Hot Reload 设计

### 1.3 与其他模块的关系

- **依赖模块**: 
  - `neurova.core.workspace`：提供 Workspace 类（Agent 办公室）
  - `neurova.core.plan_orchestrator`：提供 PlanOrchestrator 类（共用小脑）
  - `neurova.shared_core.execution_engine`：提供 ExecutionEngine 类（共用脑干）
  - `neurova.core.event_bus`：提供 EventBus（共用脊髓基础设施）
  - `neurova.core.service_manager`：提供 ServiceManager（共用脊髓基础设施）

- **被依赖模块**: 
  - `neurova.core.__init__`：导出 MultiAgentManager 相关接口
  - 未来可能作为 API 层、CLI 层的底层依赖

---

## 2. 架构设计

### 2.1 类/函数设计

#### 2.1.1 NeurovaAgent (dataclass)

```python
@dataclass
class NeurovaAgent:
    """
    Neurova Agent 数据类
    
    每个 Agent 有自己的大脑（Memory DB）和办公室（Workspace），
    但共用小脑（PlanOrchestrator）、脑干（ExecutionEngine）和脊髓（Infrastructure）。
    """
    agent_id: str                                    # Agent 唯一标识符
    persona: str = ""                               # Agent 人格设定
    constitution: str = ""                           # Agent 宪法（行为准则）
    workspace: Optional[Workspace] = None            # Agent 的工作区实例
    memory_db_path: str = ""                        # Agent 记忆数据库路径
    workspace_dir: str = ""                         # Agent 工作目录
    created_at: float = field(default_factory=lambda: time.time())  # 创建时间
    last_active: float = field(default_factory=lambda: time.time()) # 最后活跃时间
    
    @property
    def is_initialized(self) -> bool:
        """检查 Agent 是否已初始化"""
        return self.workspace is not None and self.workspace.started
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "agent_id": self.agent_id,
            "persona": self.persona,
            "constitution": self.constitution,
            "memory_db_path": self.memory_db_path,
            "workspace_dir": self.workspace_dir,
            "is_initialized": self.is_initialized,
            "created_at": self.created_at,
            "last_active": self.last_active,
        }
```

**属性说明**:
- `agent_id`: Agent 唯一标识符
- `persona`: Agent 人格设定（如"热情友好，善于沟通"）
- `constitution`: Agent 宪法/行为准则（如"永远不说谎"）
- `workspace`: Agent 的 Workspace 实例（办公室）
- `memory_db_path`: Agent 记忆数据库路径（大脑）
- `workspace_dir`: Agent 工作目录
- `created_at`: 创建时间（时间戳）
- `last_active`: 最后活跃时间（时间戳）

**返回值**: 
- `is_initialized`: 返回 Agent 是否已初始化（workspace 非空且已启动）
- `to_dict()`: 返回 Agent 信息的字典表示

**异常**: 无

#### 2.1.2 MultiAgentManager

```python
class MultiAgentManager:
    """
    多 Agent 管理器
    
    架构设计（Neurova CogArch 2.0）：
    - 每个 Agent 有自己的大脑（Memory DB）和办公室（Workspace）
    - 所有 Agent 共用 PlanOrchestrator（小脑）、ExecutionEngine（脑干）和 Infrastructure（脊髓）
    """
    
    def __init__(self):
        """初始化多 Agent 管理器"""
        # 大脑 + 办公室（每个 Agent 独立）
        self.agents: Dict[str, NeurovaAgent] = {}
        
        # 小脑（共用）
        self.shared_cerebellum: Optional[PlanOrchestrator] = None
        
        # 脑干（共用）
        self.shared_brainstem: Optional[ExecutionEngine] = None
        
        # 脊髓（共用基础设施）
        self.service_manager = None
        self.provider_manager = None
        self.event_bus = None
        
        # 并发控制
        self._lock = asyncio.Lock()
        self._pending_starts: Dict[str, asyncio.Event] = {}
        self._cleanup_tasks: Set[asyncio.Task] = set()
        
        # 基础配置
        self._base_workspace_dir = Path("neurova/agents")
        self._initialized = False
```

**属性/参数说明**:
- `agents`: Agent 字典，键为 agent_id，值为 NeurovaAgent 实例
- `shared_cerebellum`: 共用的 PlanOrchestrator 实例（小脑）
- `shared_brainstem`: 共用的 ExecutionEngine 实例（脑干）
- `service_manager`: 共用的 ServiceManager 实例（脊髓）
- `provider_manager`: 共用的 LLMProviderManager 实例（脊髓）
- `event_bus`: 共用的 EventBus 实例（脊髓）
- `_lock`: asyncio.Lock，用于并发控制
- `_pending_starts`: 待处理的启动事件字典，用于细粒度锁协调
- `_cleanup_tasks`: 清理任务集合
- `_base_workspace_dir`: Agent 工作区基础目录
- `_initialized`: 是否已初始化共享组件

#### 2.1.3 initialize_shared_components()

```python
async def initialize_shared_components(
    self,
    event_bus=None,
    service_manager=None,
    provider_manager=None,
) -> None:
    """
    初始化共用组件（小脑、脑干、脊髓）
    
    Args:
        event_bus: 事件总线实例（可选）
        service_manager: 服务管理器实例（可选）
        provider_manager: LLM 提供商管理器实例（可选）
    """
```

**参数说明**:
- `event_bus`: EventBus 实例，用于事件发布/订阅
- `service_manager`: ServiceManager 实例，用于服务管理
- `provider_manager`: LLMProviderManager 实例，用于 LLM 提供商管理

**返回值**: 无

**异常**: 无（如果已初始化则直接返回）

#### 2.1.4 get_agent()

```python
async def get_agent(self, agent_id: str) -> NeurovaAgent:
    """
    获取 Agent（Lazy Loading，借鉴 QwenPaw）
    
    如果 Agent 不存在，创建它的大脑（Memory DB）和办公室（Workspace），
    但小脑、脑干、脊髓是共用的，不需要重复创建。
    
    多个并发调用者会被协调：第一个调用者创建 Agent，其他调用者等待。
    
    Args:
        agent_id: Agent ID
        
    Returns:
        NeurovaAgent: 请求的 Agent 实例
        
    Raises:
        Exception: 如果 Agent 初始化失败
    """
```

**参数说明**:
- `agent_id`: Agent ID

**返回值**: NeurovaAgent 实例

**异常**: 
- `Exception`: 如果 Agent 初始化失败

#### 2.1.5 execute_with_shared_cerebellum()

```python
async def execute_with_shared_cerebellum(
    self,
    agent_id: str,
    input_context: Dict[str, Any],
) -> Dict[str, Any]:
    """
    共用小脑 + 脑干执行任务
    
    实现认知-执行闭环：
    1. 用 Agent 自己的大脑（Memory Layer）做认知
    2. 用共用的小脑（PlanOrchestrator）来编排任务
    3. 用共用的脑干（ExecutionEngine）来执行任务
    4. 结果反馈到 Agent 自己的大脑（记忆巩固）
    
    Args:
        agent_id: Agent ID
        input_context: 输入上下文（包含用户请求、环境信息等）
        
    Returns:
        Dict[str, Any]: 执行结果
        
    Raises:
        RuntimeError: 如果共享组件未初始化
        Exception: 如果执行失败
    """
```

**参数说明**:
- `agent_id`: Agent ID
- `input_context`: 输入上下文字典，包含用户请求、环境信息等

**返回值**: 执行结果字典，包含：
- `agent_id`: Agent ID
- `cognition`: 认知结果
- `plan`: 任务计划信息
- `execution`: 执行结果
- `success`: 是否成功

**异常**: 
- `RuntimeError`: 如果共享组件未初始化
- `Exception`: 如果执行失败

#### 2.1.6 start_agent()

```python
async def start_agent(
    self, 
    agent_id: str, 
    persona: str = "", 
    constitution: str = "",
) -> NeurovaAgent:
    """
    启动 Agent（如果未启动则创建）
    
    Args:
        agent_id: Agent ID
        persona: Agent 人格设定（可选）
        constitution: Agent 宪法/行为准则（可选）
        
    Returns:
        NeurovaAgent: 启动后的 Agent 实例
    """
```

**参数说明**:
- `agent_id`: Agent ID
- `persona`: Agent 人格设定（可选）
- `constitution`: Agent 宪法/行为准则（可选）

**返回值**: NeurovaAgent 实例

**异常**: 无

#### 2.1.7 reload_agent()

```python
async def reload_agent(self, agent_id: str) -> NeurovaAgent:
    """
    热重载 Agent
    
    保留可复用服务（标记为 reusable=True），同时重新创建其他服务。
    
    Args:
        agent_id: 要重载的 Agent ID
        
    Returns:
        NeurovaAgent: 重载后的 Agent 实例
        
    Raises:
        ValueError: 如果 Agent 未找到
    """
```

**参数说明**:
- `agent_id`: 要重载的 Agent ID

**返回值**: NeurovaAgent 实例

**异常**: 
- `ValueError`: 如果 Agent 未找到
- `ValueError`: 如果 Agent 的 Workspace 未初始化

#### 2.1.8 stop_agent()

```python
async def stop_agent(self, agent_id: str, final: bool = True) -> None:
    """
    停止 Agent
    
    Args:
        agent_id: 要停止的 Agent ID
        final: 如果为 True，停止所有服务（包括可复用服务）
    """
```

**参数说明**:
- `agent_id`: 要停止的 Agent ID
- `final`: 如果为 True，停止所有服务（包括可复用服务）；如果为 False，保留可复用服务（用于热重载）

**返回值**: 无

**异常**: 无

#### 2.1.9 stop_all()

```python
async def stop_all(self, final: bool = True) -> None:
    """
    停止所有 Agent
    
    Args:
        final: 如果为 True，停止所有服务（包括可复用服务）
    """
```

**参数说明**:
- `final`: 如果为 True，停止所有服务（包括可复用服务）

**返回值**: 无

**异常**: 无

#### 2.1.10 其他辅助方法

```python
# 列出所有已加载的 Agent ID
def list_agents(self) -> list: ...

# 检查 Agent 是否已加载
def is_agent_loaded(self, agent_id: str) -> bool: ...

# 获取 Agent 信息
def get_agent_info(self, agent_id: str) -> Optional[Dict[str, Any]]: ...

# 列出所有 Agent 的详细信息
def list_agents_info(self) -> List[Dict[str, Any]]: ...

# 设置所有 Agent 工作区的基础目录
def set_base_workspace_dir(self, base_dir: str) -> None: ...

# 获取 Agent 的工作区目录
def get_workspace_dir(self, agent_id: str) -> Path: ...
```

### 2.2 数据流图

```
┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
│                  SHARED CORE (多个 Agent 共用的部分)                    │
│  ┌───────────────────────────────────────────────────────────────────────────────────┐    │
│  │  SHARED CEREBELLUM (共用小脑) + BRAINSTEM (脑干) + SPINAL CORD (脊髓)  │    │
│  │  ┌───────────────────────────────────────────────────────────────────────┐    │    │
│  │  │  Plan Orchestrator (共用小脑) - 所有 Agent 的任务编排        │    │    │
│  │  ├───────────────────────────────────────────────────────────────────────┤    │    │
│  │  │  Execution Engine (共用脑干/脊髓)                                     │    │    │
│  │  │  • Tool Engine (共用) • MCP (共用) • Workflow Engine (共用)  │    │    │
│  │  ├───────────────────────────────────────────────────────────────────────┤    │    │
│  │  │  Infrastructure (共用脊髓)                                             │    │    │
│  │  │  • Service Manager • Provider Manager • Event Bus • Config  │    │    │
│  │  └───────────────────────────────────────────────────────────────────────┘    │    │
│  └───────────────────────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────────────────┘
                                             │
                      ┌──────────────────────┼──────────────────────┐
                      │                      │                      │
                      ▼                      ▼                      ▼
┌───────────────────────────┐  ┌───────────────────────────┐  ┌───────────────────────────┐
│   Agent "Alice"           │  │   Agent "Bob"             │  │   Agent "Charlie"         │
│  ┌─────────────────────┐  │  │  ┌─────────────────────┐  │  │  ┌─────────────────────┐  │
│  │  ALICE'S BRAIN      │  │  │  │  BOB'S BRAIN         │  │  │  │  CHARLIE'S BRAIN    │  │
│  │  (独立数据库)       │  │  │  │  (独立数据库)        │  │  │  │  (独立数据库)        │  │
│  │  • Memory Layer    │  │  │  │  • Memory Layer    │  │  │  │  • Memory Layer    │  │
│  │  • Meta Cog        │  │  │  │  • Meta Cog        │  │  │  │  • Meta Cog        │  │
│  │  • Persona         │  │  │  │  • Persona         │  │  │  │  • Persona         │  │
│  └─────────────────────┘  │  │  └─────────────────────┘  │  │  └─────────────────────┘  │
│  ┌─────────────────────┐  │  │  ┌─────────────────────┐  │  │  ┌─────────────────────┐  │
│  │  ALICE'S OFFICE    │  │  │  │  BOB'S OFFICE       │  │  │  │  CHARLIE'S OFFICE  │  │
│  │  (独立工作目录)     │  │  │  │  (独立工作目录)      │  │  │  │  (独立工作目录)     │  │
│  │  • Workspace       │  │  │  │  • Workspace       │  │  │  │  • Workspace       │  │
│  └─────────────────────┘  │  │  └─────────────────────┘  │  │  └─────────────────────┘  │
└───────────────────────────┘  └───────────────────────────┘  └───────────────────────────┘
```

### 2.3 状态机

```
                    ┌─────────────┐
                    │   Created   │
                    └──────┬──────┘
                           │ initialize_shared_components()
                    ┌──────▼──────┐
            ┌───────│  Initialized │◄──────┐
            │        └──────┬──────┘       │
            │               │ get_agent()   │
            │        ┌──────▼──────┐       │
            │        │   Loading   │       │
            │        └──────┬──────┘       │
            │               │              │
            │        ┌──────▼──────┐       │
            └───────►│  Running   │───────┘
                     └──────┬──────┘
                            │ stop_agent()
                     ┌──────▼──────┐
                     │  Stopped    │
                     └─────────────┘
```

---

## 3. 接口设计

### 3.1 API接口（如有）

无（本模块为底层管理模块，不直接提供 HTTP API）

### 3.2 类接口

| 方法名 | 参数 | 返回值 | 说明 |
|--------|------|--------|------|
| `__init__()` | 无 | 无 | 初始化 MultiAgentManager |
| `initialize_shared_components()` | `event_bus`, `service_manager`, `provider_manager` | 无 | 初始化共用组件（小脑、脑干、脊髓） |
| `get_agent()` | `agent_id: str` | `NeurovaAgent` | 获取 Agent（Lazy Loading） |
| `execute_with_shared_cerebellum()` | `agent_id: str`, `input_context: Dict[str, Any]` | `Dict[str, Any]` | 共用小脑 + 脑干执行任务 |
| `start_agent()` | `agent_id: str`, `persona: str`, `constitution: str` | `NeurovaAgent` | 启动 Agent |
| `reload_agent()` | `agent_id: str` | `NeurovaAgent` | 热重载 Agent |
| `stop_agent()` | `agent_id: str`, `final: bool` | 无 | 停止 Agent |
| `stop_all()` | `final: bool` | 无 | 停止所有 Agent |
| `list_agents()` | 无 | `list` | 列出所有已加载的 Agent ID |
| `is_agent_loaded()` | `agent_id: str` | `bool` | 检查 Agent 是否已加载 |
| `get_agent_info()` | `agent_id: str` | `Optional[Dict[str, Any]]` | 获取 Agent 信息 |
| `list_agents_info()` | 无 | `List[Dict[str, Any]]` | 列出所有 Agent 的详细信息 |
| `set_base_workspace_dir()` | `base_dir: str` | 无 | 设置所有 Agent 工作区的基础目录 |
| `get_workspace_dir()` | `agent_id: str` | `Path` | 获取 Agent 的工作区目录 |

---

## 4. 实现细节

### 4.1 已完成的子任务

- [x] 创建 `NeurovaAgent` 数据类
- [x] 更新 `MultiAgentManager.__init__()` 添加共享组件属性
- [x] 实现 `initialize_shared_components()` 方法
- [x] 更新 `get_agent()` 方法以支持 `NeurovaAgent`
- [x] 实现 `execute_with_shared_cerebellum()` 方法
- [x] 实现 `_cognitive_processing()` 辅助方法
- [x] 实现 `_consolidate_memory()` 辅助方法
- [x] 更新 `start_agent()` 方法
- [x] 更新 `reload_agent()` 方法以支持 `NeurovaAgent`
- [x] 更新 `stop_agent()` 方法以支持 `NeurovaAgent`
- [x] 更新 `stop_all()` 方法
- [x] 添加 `get_agent_info()` 方法
- [x] 添加 `list_agents_info()` 方法

### 4.2 已完成的子任务

- [x] 编写单元测试 ✅ (28/28 测试通过)
- [x] 更新 `progress_tracker.md` ✅
- [x] 创建每日进度报告 ✅

### 4.3 待完成的子任务

- [ ] 性能测试 (可选)
- [ ] 集成测试 (可选)
- [ ] 文档审查 (可选)

### 4.4 关键代码片段

```python
# 认知-执行闭环实现
async def execute_with_shared_cerebellum(
    self,
    agent_id: str,
    input_context: Dict[str, Any],
) -> Dict[str, Any]:
    """实现认知-执行闭环"""
    # 第 1 步：用 Agent 自己的大脑做认知
    cognition_result = await self._cognitive_processing(agent, input_context)
    
    # 第 2 步：用共用的小脑来编排任务
    plan = await self.shared_cerebellum.decompose_intent(...)
    
    # 第 3 步：用共用的脑干来执行任务
    execution_result = await self.shared_brainstem.execute_plan(plan)
    
    # 第 4 步：结果反馈到 Agent 自己的大脑（记忆巩固）
    await self._consolidate_memory(agent, input_context, execution_result)
    
    return {...}
```

---

## 5. 测试计划

### 5.1 单元测试

| 测试用例 | 测试内容 | 状态 | 通过率 |
|---------|---------|------|--------|
| test_initialize_shared_components | 测试共享组件初始化 | 未开始 | - |
| test_get_agent_lazy_loading | 测试 Lazy Loading | 未开始 | - |
| test_get_agent_parallel | 测试并行启动 | 未开始 | - |
| test_execute_with_shared_cerebellum | 测试认知-执行闭环 | 未开始 | - |
| test_start_agent | 测试启动 Agent | 未开始 | - |
| test_reload_agent | 测试热重载 | 未开始 | - |
| test_stop_agent | 测试停止 Agent | 未开始 | - |
| test_stop_all | 测试停止所有 Agent | 未开始 | - |
| test_list_agents | 测试列出 Agent | 未开始 | - |
| test_is_agent_loaded | 测试检查 Agent 是否已加载 | 未开始 | - |
| test_get_agent_info | 测试获取 Agent 信息 | 未开始 | - |
| test_list_agents_info | 测试列出所有 Agent 信息 | 未开始 | - |

### 5.2 集成测试

1. **与 Workspace 模块集成测试**：
   - 测试 MultiAgentManager 与 Workspace 的交互
   - 测试 Lazy Loading 机制
   - 测试 Hot Reload 机制

2. **与 PlanOrchestrator 模块集成测试**：
   - 测试共用小脑的任务编排功能
   - 测试认知-执行闭环

3. **与 ExecutionEngine 模块集成测试**：
   - 测试共用脑干的计划执行功能
   - 测试执行结果反馈

### 5.3 性能测试

1. **并行启动性能测试**：
   - 测试多个 Agent 并行启动的时间
   - 测试细粒度锁的性能优势

2. **内存占用测试**：
   - 测试多个 Agent 的内存占用
   - 测试共用组件的内存节省效果

---

## 6. 已知问题

| 问题描述 | 严重程度 | 发现时间 | 解决方案 | 状态 |
|---------|---------|----------|--------|------|
| 暂无 | - | - | - | - |

---

## 7. 变更记录

| 时间 | 变更内容 | 变更原因 | 影响范围 |
|------|---------|---------|---------|
| 2026-05-12 21:00 | 初始创建 | - | - |
| 2026-05-12 21:30 | 添加 NeurovaAgent 数据类 | 实现多 Agent 架构 | multi_agent_manager.py |
| 2026-05-12 21:45 | 实现 initialize_shared_components() | 初始化共用组件 | multi_agent_manager.py |
| 2026-05-12 22:00 | 实现 execute_with_shared_cerebellum() | 实现认知-执行闭环 | multi_agent_manager.py |

---

## 8. 附录

### 8.1 参考资料

- `docs/NEUROVA_CogArch_2.0.md` 第2章：多 Agent 架构设计
- QwenPaw 设计文档：MultiAgentManager 设计

### 8.2 相关文件

- `neurova/core/multi_agent_manager.py`：MultiAgentManager 实现
- `neurova/core/workspace.py`：Workspace 实现
- `neurova/core/plan_orchestrator.py`：PlanOrchestrator 实现
- `neurova/shared_core/execution_engine.py`：ExecutionEngine 实现
- `tests/test_multi_agent_manager.py`：（待创建）单元测试

---

**最后更新**: 2026-05-12 22:00 | **更新人**: multi-agent-dev
