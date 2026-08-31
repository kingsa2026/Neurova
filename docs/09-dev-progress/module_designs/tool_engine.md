# ToolEngine 设计文档

> **模块ID**: Task2-ToolEngine  
> **创建时间**: 2026-05-12 23:50  
> **最后更新**: 2026-05-13 00:30  
> **负责人**: tool-engine-dev  
> **状态**: ✅ 已完成

---

## 1. 模块概述

### 1.1 功能描述

ToolEngine 是 Neurova CogArch 2.0 执行引擎（手脚）的核心组件之一，负责：
- 智能工具选择与发现（基于上下文和意图）
- 自动参数填充（结合记忆与上下文）
- 安全执行（集成 ToolGuard 和 SkillScanner）
- 工具链执行（按顺序执行多个工具）
- 工具注册与版本管理
- 调用记录与审计

### 1.2 设计依据

- **NEUROVA_CogArch_2.0.md 第3.3节**：执行引擎（手脚）设计
- **QwenPaw 设计**：借鉴其工具管理、安全守卫设计
- **任务分配**：team-lead 分配的具体要求

### 1.3 与其他模块的关系

- **依赖模块**: 
  - `neurova.security.tool_guard`：提供 ToolGuardEngine（工具守卫）
  - `neurova.skills.security_scanner`：提供 SkillScanner（技能扫描器）
  - `neurova.core.event_bus`：提供 EventBus（事件总线，可选）
  - `neurova.core.service_manager`：提供 ServiceManager（服务管理器，可选）

- **被依赖模块**: 
  - `neurova.execution_engine.__init__`：导出 ToolEngine 相关接口
  - 未来可能作为 PlanOrchestrator、WorkflowEngine 的底层依赖

---

## 2. 架构设计

### 2.1 整体架构

```
┌─────────────────────────────────────────────────────────┐
│                   ToolEngine                        │
├─────────────────────────────────────────────────────────┤
│                                                  │
│  ┌──────────────────────────────────────────────┐   │
│  │  工具注册与管理                              │   │
│  │  • register_tool() • unregister_tool()    │   │
│  │  • get_tool() • list_tools()             │   │
│  │  • 版本管理（get_tool_versions() 等）    │   │
│  └──────────────────────────────────────────────┘   │
│                  ↓                               │
│  ┌──────────────────────────────────────────────┐   │
│  │  智能工具选择                                │   │
│  │  • discover_tools()（基于上下文发现）      │   │
│  │  • select_tools()（智能选择）             │   │
│  └──────────────────────────────────────────────┘   │
│                  ↓                               │
│  ┌──────────────────────────────────────────────┐   │
│  │  参数自动填充                                │   │
│  │  • prepare_arguments()（结合上下文）       │   │
│  └──────────────────────────────────────────────┘   │
│                  ↓                               │
│  ┌──────────────────────────────────────────────┐   │
│  │  安全执行                                    │   │
│  │  • execute_with_safeguards()                │   │
│  │  • 集成 ToolGuard（执行前检查）            │   │
│  │  • 集成 SkillScanner（技能扫描）           │   │
│  │  • 结果验证（执行后检查）                  │   │
│  └──────────────────────────────────────────────┘   │
│                  ↓                               │
│  ┌──────────────────────────────────────────────┐   │
│  │  工具链执行                                  │   │
│  │  • chain_tools()（顺序执行）               │   │
│  └──────────────────────────────────────────────┘   │
│                  ↓                               │
│  ┌──────────────────────────────────────────────┐   │
│  │  调用记录与审计                            │   │
│  │  • get_invocation() • get_tool_history()   │   │
│  │  • clear_history()                         │   │
│  └──────────────────────────────────────────────┘   │
│                                                  │
└─────────────────────────────────────────────────────────┘
```

### 2.2 安全集成架构

```
┌─────────────────────────────────────────────────────────┐
│          execute_with_safeguards() 执行流程           │
├─────────────────────────────────────────────────────────┤
│                                                  │
│  1. 执行前安全检查                                 │
│     ┌────────────────────────────────────────┐      │
│     │  ToolGuard 检查                          │      │
│     │  • RuleBasedToolGuardian（规则检查）    │      │
│     │  • FilePathGuardian（文件路径检查）      │      │
│     │  • ShellEvasionGuardian（Shell 绕过）  │      │
│     └────────────────────────────────────────┘      │
│     ↓ 通过                                        │
│     ┌────────────────────────────────────────┐      │
│     │  SkillScanner 检查                       │      │
│     │  • 如果是技能工具，扫描安全漏洞          │      │
│     │  • 静态代码分析                          │      │
│     └────────────────────────────────────────┘      │
│     ↓ 通过                                        │
│  2. 执行工具                                     │
│     • 创建调用记录（ToolInvocation）             │
│     • 执行处理器（同步/异步）                   │
│     • 超时控制                                   │
│     ↓                                            │
│  3. 执行后结果验证                               │
│     • _validate_result()（结果验证）             │
│     • 触发事件（EventBus）                      │
│                                                  │
└─────────────────────────────────────────────────────────┘
```

---

## 3. 数据结构设计

### 3.1 核心数据结构

#### 3.1.1 ToolStatus (Enum)
```python
class ToolStatus(str, Enum):
    """工具状态"""
    AVAILABLE = "available"   # 可用
    BUSY = "busy"             # 忙碌
    ERROR = "error"             # 错误
    DISABLED = "disabled"     # 禁用
```

#### 3.1.2 ToolParameter (dataclass)
```python
@dataclass
class ToolParameter:
    """工具参数定义"""
    name: str                  # 参数名称
    type: str = "string"      # 参数类型（integer, number, boolean, array, object）
    required: bool = True      # 是否必需
    description: str = ""      # 参数描述
    default: Any = None       # 默认值
    constraints: Dict[str, Any] = field(default_factory=dict)  # 约束（min, max, pattern）
```

#### 3.1.3 ToolDefinition (dataclass)
```python
@dataclass
class ToolDefinition:
    """工具定义"""
    id: str                           # 工具唯一标识符
    name: str                         # 工具名称
    description: str                  # 工具描述
    parameters: List[ToolParameter]   # 参数列表
    status: ToolStatus = ToolStatus.AVAILABLE  # 状态
    category: str = "general"        # 分类
    tags: List[str] = field(default_factory=list)  # 标签
    timeout: int = 300               # 超时时间（秒）
    version: str = "1.0.0"         # 版本号
    author: str = ""                # 作者
    metadata: Dict[str, Any] = field(default_factory=dict)  # 元数据
```

#### 3.1.4 ToolInvocation (dataclass)
```python
@dataclass
class ToolInvocation:
    """工具调用记录"""
    invocation_id: str               # 调用唯一标识符
    tool_id: str                    # 工具 ID
    tool_name: str                  # 工具名称
    parameters: Dict[str, Any]      # 调用参数
    status: str = "pending"         # 状态（pending, running, completed, failed）
    result: Any = None              # 执行结果
    error: Optional[str] = None     # 错误信息
    started_at: Optional[datetime] = None   # 开始时间
    completed_at: Optional[datetime] = None # 完成时间
    execution_time: Optional[float] = None # 执行耗时（秒）
    metadata: Dict[str, Any] = field(default_factory=dict)  # 元数据
```

#### 3.1.5 ToolSelection (dataclass)
```python
@dataclass
class ToolSelection:
    """工具选择结果"""
    tool_id: str                            # 工具 ID
    confidence: float                      # 置信度（0.0 ~ 1.0）
    reasoning: str                         # 选择原因
    suggested_parameters: Dict[str, Any] = field(default_factory=dict)  # 建议参数
```

#### 3.1.6 ToolCallingContext (dataclass)
```python
@dataclass
class ToolCallingContext:
    """工具调用上下文"""
    intent: str                           # 用户意图
    context: Dict[str, Any] = field(default_factory=dict)  # 上下文信息
    agent_id: Optional[str] = None        # Agent ID
    conversation_id: Optional[str] = None # 会话 ID
    constraints: List[str] = field(default_factory=list)  # 约束条件
```

#### 3.1.7 ToolVersion (dataclass)
```python
@dataclass
class ToolVersion:
    """工具版本信息"""
    version: str                         # 版本号
    tool_definition: ToolDefinition      # 工具定义
    created_at: datetime = field(default_factory=datetime.now)  # 创建时间
    changelog: str = ""                 # 变更日志
    is_active: bool = True             # 是否活跃版本
```

#### 3.1.8 ToolDiscoveryResult (dataclass)
```python
@dataclass
class ToolDiscoveryResult:
    """工具发现结果"""
    tool_id: str                       # 工具 ID
    match_score: float                 # 匹配分数
    match_reasons: List[str] = field(default_factory=list)  # 匹配原因
```

---

## 4. 类设计

### 4.1 ToolEngine 类

```python
class ToolEngine:
    """
    工具引擎
    
    核心功能：
    - 工具注册与管理（含版本管理）
    - 智能工具选择（基于上下文）
    - 参数自动填充（结合记忆与上下文）
    - 安全执行（集成 ToolGuard 和 SkillScanner）
    - 工具链执行
    - 调用记录与审计
    """
    
    def __init__(self, event_bus=None, service_manager=None, tool_guard=None):
        """
        初始化工具引擎
        
        参数:
            event_bus: 事件总线（用于触发事件）
            service_manager: 服务管理器
            tool_guard: 工具守卫实例（可选，会自动创建默认守卫）
        """
        self.event_bus = event_bus
        self.service_manager = service_manager
        
        # 工具注册表（工具ID -> 工具定义）
        self.tools: Dict[str, ToolDefinition] = {}
        
        # 工具处理器（工具ID -> 处理函数）
        self.tool_handlers: Dict[str, Callable] = {}
        
        # 工具版本管理（工具ID -> 版本列表）
        self.tool_versions: Dict[str, List[ToolVersion]] = {}
        
        # 工具调用记录（调用ID -> 调用记录）
        self.invocations: Dict[str, ToolInvocation] = {}
        
        # 初始化工具守卫
        if tool_guard is None:
            from neurova.security.tool_guard import ToolGuardEngine
            self.tool_guard = ToolGuardEngine()
        else:
            self.tool_guard = tool_guard
        
        # 初始化技能扫描器（延迟加载）
        self._skill_scanner = None
    
    # ============ 工具注册与管理 ============
    
    def register_tool(
        self,
        definition: ToolDefinition,
        handler: Callable,
        version: str = "1.0.0",
        changelog: str = ""
    ) -> bool:
        """
        注册工具
        
        参数:
            definition: 工具定义
            handler: 工具处理函数
            version: 工具版本
            changelog: 版本变更日志
            
        返回:
            bool: 注册是否成功
        """
        # ... 实现 ...
    
    def unregister_tool(self, tool_id: str) -> bool:
        """注销工具"""
        # ... 实现 ...
    
    def get_tool(self, tool_id: str) -> Optional[ToolDefinition]:
        """获取工具定义"""
        # ... 实现 ...
    
    def list_tools(
        self,
        category: Optional[str] = None,
        status: Optional[ToolStatus] = None
    ) -> List[ToolDefinition]:
        """列出工具（支持过滤）"""
        # ... 实现 ...
    
    # ============ 工具版本管理 ============
    
    def get_tool_versions(self, tool_id: str) -> List[ToolVersion]:
        """获取工具的所有版本"""
        # ... 实现 ...
    
    def get_tool_version(self, tool_id: str, version: str) -> Optional[ToolVersion]:
        """获取工具的指定版本"""
        # ... 实现 ...
    
    def set_active_version(self, tool_id: str, version: str) -> bool:
        """设置工具的活跃版本"""
        # ... 实现 ...
    
    # ============ 工具发现机制 ============
    
    def discover_tools(self, context: ToolCallingContext) -> List[ToolDiscoveryResult]:
        """
        发现适合的工具（基于上下文）
        
        参数:
            context: 工具调用上下文
            
        返回:
            List[ToolDiscoveryResult]: 发现的工具列表（按匹配分数排序）
        """
        # ... 实现（基于标签、名称、描述、上下文匹配）...
    
    # ============ 智能工具选择 ============
    
    async def select_tools(self, context: ToolCallingContext) -> List[ToolSelection]:
        """
        智能工具选择
        
        参数:
            context: 工具调用上下文
            
        返回:
            List[ToolSelection]: 选择的工具列表（按置信度排序）
        """
        # ... 实现（调用 discover_tools，转换为 ToolSelection）...
    
    # ============ 参数自动填充 ============
    
    async def prepare_arguments(
        self,
        tool: ToolDefinition,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        自动参数填充
        
        参数:
            tool: 工具定义
            context: 上下文信息
            
        返回:
            Dict[str, Any]: 完整参数
        """
        # ... 实现（从上下文获取参数、使用默认值、验证参数）...
    
    # ============ 安全执行 ============
    
    async def execute_with_safeguards(
        self,
        tool: ToolDefinition,
        args: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None
    ) -> Any:
        """
        安全执行工具
        
        集成 ToolGuard 进行执行前安全检查
        集成 SkillScanner 进行技能安全扫描（如果是技能工具）
        
        参数:
            tool: 工具定义
            args: 工具参数
            context: 上下文信息（可选）
            
        返回:
            Any: 执行结果
        """
        # ... 实现（ToolGuard 检查、SkillScanner 检查、执行、结果验证）...
    
    # ============ 工具链执行 ============
    
    async def chain_tools(self, tool_calls: List[ToolInvocation]) -> Any:
        """
        工具链执行
        
        按顺序执行多个工具，前一个工具的输出作为后一个工具的输入
        
        参数:
            tool_calls: 工具调用列表（按执行顺序）
            
        返回:
            Any: 最后一个工具的执行结果
        """
        # ... 实现（顺序执行、传递上下文）...
    
    # ============ 辅助方法 ============
    
    def _is_skill_tool(self, tool: ToolDefinition) -> bool:
        """判断是否为技能工具"""
        # ... 实现 ...
    
    async def _scan_skill_tool(
        self,
        tool: ToolDefinition,
        context: Dict[str, Any]
    ) -> Optional[Any]:
        """扫描技能工具"""
        # ... 实现（延迟加载 SkillScanner、执行扫描）...
    
    async def _validate_parameters(
        self,
        tool: ToolDefinition,
        parameters: Dict[str, Any]
    ) -> None:
        """验证参数（类型检查、约束检查）"""
        # ... 实现 ...
    
    async def _validate_result(self, tool: ToolDefinition, result: Any) -> None:
        """验证执行结果"""
        # ... 实现 ...
    
    # ============ 调用记录与审计 ============
    
    def get_invocation(self, invocation_id: str) -> Optional[ToolInvocation]:
        """获取调用记录"""
        # ... 实现 ...
    
    def get_tool_history(self, tool_id: str, limit: int = 100) -> List[ToolInvocation]:
        """获取工具的历史调用记录"""
        # ... 实现 ...
    
    def clear_history(self, tool_id: Optional[str] = None) -> int:
        """清理调用记录"""
        # ... 实现 ...
```

---

## 5. API 设计

### 5.1 公共方法列表

| 方法名 | 参数 | 返回值 | 说明 |
|--------|------|--------|------|
| `register_tool()` | `definition, handler, version, changelog` | `bool` | 注册工具 |
| `unregister_tool()` | `tool_id` | `bool` | 注销工具 |
| `get_tool()` | `tool_id` | `Optional[ToolDefinition]` | 获取工具定义 |
| `list_tools()` | `category, status` | `List[ToolDefinition]` | 列出工具 |
| `get_tool_versions()` | `tool_id` | `List[ToolVersion]` | 获取工具版本列表 |
| `get_tool_version()` | `tool_id, version` | `Optional[ToolVersion]` | 获取指定版本 |
| `set_active_version()` | `tool_id, version` | `bool` | 设置活跃版本 |
| `discover_tools()` | `context` | `List[ToolDiscoveryResult]` | 发现工具 |
| `select_tools()` | `context` | `List[ToolSelection]` | 智能选择工具 |
| `prepare_arguments()` | `tool, context` | `Dict[str, Any]` | 自动填充参数 |
| `execute_with_safeguards()` | `tool, args, context` | `Any` | 安全执行工具 |
| `chain_tools()` | `tool_calls` | `Any` | 工具链执行 |
| `get_invocation()` | `invocation_id` | `Optional[ToolInvocation]` | 获取调用记录 |
| `get_tool_history()` | `tool_id, limit` | `List[ToolInvocation]` | 获取调用历史 |
| `clear_history()` | `tool_id` | `int` | 清理调用记录 |

---

## 6. 集成设计

### 6.1 与 ToolGuard 集成

```python
# 在 ToolEngine.__init__() 中初始化 ToolGuard
if tool_guard is None:
    from neurova.security.tool_guard import ToolGuardEngine
    self.tool_guard = ToolGuardEngine()
else:
    self.tool_guard = tool_guard

# 在 execute_with_safeguards() 中使用 ToolGuard
if self.tool_guard:
    guard_result = self.tool_guard.guard(tool.name, args)
    
    if not guard_result.is_safe:
        error_msg = f"工具守卫检测到安全问题: {tool.name}"
        for finding in guard_result.findings:
            error_msg += f"\n  - [{finding.severity}] {finding.title}: {finding.description}"
        
        logger.error(error_msg)
        raise PermissionError(error_msg)
    
    logger.info(f"✅ ToolGuard 检查通过: {tool.name}")
```

### 6.2 与 SkillScanner 集成

```python
# 延迟加载 SkillScanner
if self._skill_scanner is None:
    try:
        from neurova.skills.security_scanner import SkillScanner
        self._skill_scanner = SkillScanner()
    except ImportError:
        logger.warning("SkillScanner 未安装，跳过技能扫描")
        return None

# 在 execute_with_safeguards() 中使用 SkillScanner
if self._is_skill_tool(tool):
    scanner_result = await self._scan_skill_tool(tool, context)
    if scanner_result and not scanner_result.safe:
        error_msg = f"技能扫描检测到安全问题: {tool.name}"
        for issue in scanner_result.issues:
            error_msg += f"\n  - [{issue.severity}] {issue.issue_type}: {issue.detail}"
        
        logger.error(error_msg)
        raise PermissionError(error_msg)
    
    logger.info(f"✅ SkillScanner 检查通过: {tool.name}")
```

---

## 7. 使用示例

### 7.1 基本使用

```python
from neurova.execution_engine import ToolEngine, ToolDefinition, ToolParameter

# 创建工具引擎
engine = ToolEngine()

# 定义工具
async def my_tool_handler(**kwargs):
    return f"Hello, {kwargs.get('name', 'World')}!"

tool = ToolDefinition(
    id="greet",
    name="greet",
    description="Greet someone",
    parameters=[
        ToolParameter(name="name", type="string", required=False, default="World"),
    ]
)

# 注册工具
engine.register_tool(tool, my_tool_handler)

# 执行工具
result = await engine.execute_with_safeguards(
    tool=tool,
    args={"name": "Alice"}
)
print(result)  # 输出: Hello, Alice!
```

### 7.2 智能工具选择

```python
from neurova.execution_engine import ToolCallingContext

# 创建上下文
context = ToolCallingContext(
    intent="I want to search for information",
    context={"user": "Alice"}
)

# 选择工具
selections = await engine.select_tools(context)
for selection in selections:
    print(f"Selected tool: {selection.tool_id}, confidence: {selection.confidence}")
    print(f"Reasoning: {selection.reasoning}")
```

### 7.3 工具链执行

```python
from neurova.execution_engine import ToolInvocation

# 创建工具调用列表
tool_calls = [
    ToolInvocation(
        invocation_id="1",
        tool_id="tool1",
        tool_name="add_one",
        parameters={"value": 1}
    ),
    ToolInvocation(
        invocation_id="2",
        tool_id="tool2",
        tool_name="multiply_two",
        parameters={"value": None}  # 将从上一个工具的结果获取
    ),
]

# 执行工具链
result = await engine.chain_tools(tool_calls)
print(result)  # 输出: 4 ( (1+1) * 2 )
```

---

## 8. 测试计划

### 8.1 单元测试覆盖

测试用例文件：`tests/test_tool_engine.py`

测试覆盖：
1. **工具注册与管理**（4 个测试）
2. **工具列表与过滤**（3 个测试）
3. **工具发现机制**（3 个测试）
4. **智能工具选择**（2 个测试）
5. **参数自动填充**（2 个测试）
6. **参数验证**（4 个测试）
7. **工具执行**（2 个测试）
8. **工具链执行**（1 个测试）
9. **工具版本管理**（2 个测试）
10. **调用记录与审计**（2 个测试）
11. **ToolGuard 集成**（1 个测试）
12. **边界条件**（3 个测试）

**总计：至少 29 个测试用例**

### 8.2 测试运行

```bash
# 运行所有测试
python -m pytest tests/test_tool_engine.py -v

# 运行特定测试类
python -m pytest tests/test_tool_engine.py::TestToolRegistration -v

# 查看覆盖率
python -m pytest tests/test_tool_engine.py --cov=neurova.execution_engine.tool_engine --cov-report=html
```

---

## 9. 部署与配置

### 9.1 配置示例

```yaml
# neurova_config.yaml
execution_engine:
  tool_engine:
    # ToolGuard 配置
    tool_guard:
      enabled: true
      approval_mode: "auto"  # strict, smart, auto, off
      denied_tools: []  # 禁止的工具列表
    
    # 技能扫描配置
    skill_scanner:
      enabled: true
      scan_timeout: 30  # 扫描超时（秒）
```

### 9.2 依赖安装

```bash
# ToolEngine 本身不需要额外依赖
# 但 ToolGuard 和 SkillScanner 可能需要：
# - neurova.security.tool_guard（内置）
# - neurova.skills.security_scanner（内置）
```

---

## 10. 未来改进方向

1. **更智能的工具选择**：使用 LLM 进行工具选择，而非简单的基于关键词匹配
2. **工具执行并行化**：支持工具链中的并行执行
3. **工具执行监控**：集成 ExecutionMonitor，监控工具执行状态
4. **工具执行回滚**：支持工具执行失败时的回滚操作
5. **工具权限管理**：更细粒度的工具权限控制

---

## 11. 总结

ToolEngine 是 Neurova CogArch 2.0 执行引擎的核心组件，负责任务的具体执行。通过集成 ToolGuard 和 SkillScanner，确保了工具执行的安全性。通过提供智能工具选择、参数自动填充、工具链执行等功能，大大提升了系统的智能化水平。

**完成状态**：✅ 已完成
- 代码实现：`neurova/execution_engine/tool_engine.py`
- 单元测试：`tests/test_tool_engine.py`（29+ 测试用例）
- 模块设计文档：`docs/dev_progress/module_designs/tool_engine.md`
