# WorkflowEngine 设计文档

**模块名称**: WorkflowEngine (工作流引擎)  
**版本**: 2.0  
**作者**: workflow-dev  
**审查者**: monitor-dev  
**日期**: 2026-05-13  

---

## 1. 概述

### 1.1 模块功能
WorkflowEngine 是 Neurova 项目的工作流引擎核心模块，负责：
- 工作流的创建、执行和管理
- 支持完整的状态机（PENDING → RUNNING → PAUSED/COMPLETED/FAILED）
- 暂停/恢复、回滚功能
- 条件分支和并行执行
- 执行监控和日志记录

### 1.2 设计目标
- **可靠性**: 支持检查点和回滚，确保工作流可恢复
- **灵活性**: 支持多种动作类型和条件表达式
- **可监控性**: 集成 ExecutionMonitor，实时记录执行状态
- **可扩展性**: 易于添加新的动作处理器

### 1.3 技术栈
- Python 3.8+
- asyncio（异步执行）
- JSON 文件存储（初期）/ 数据库（未来）
- FastAPI（API 接口）

---

## 2. 架构设计

### 2.1 模块结构
```
neurova/projects/
├── workflow_engine.py       # 核心引擎实现
├── models.py               # 数据模型（Workflow, WorkflowStep等）
└── __init__.py            # 模块导出

neurova/api/endpoints/
└── workflows_api.py        # FastAPI 路由接口
```

### 2.2 核心类设计

#### WorkflowEngine
```python
class WorkflowEngine:
    """
    工作流引擎 - 增强版
    
    支持完整的状态机、暂停/恢复、回滚、条件分支、并行执行、执行监控
    """
    
    # 有效的状态转换矩阵
    VALID_TRANSITIONS = {...}
    
    def __init__(self, base_path: str = None, project_manager=None, 
                 enable_monitor: bool = True):
        # 初始化存储路径、动作处理器、ExecutionMonitor等
        ...
    
    # 核心功能方法
    def create_workflow(...) -> Workflow: ...
    async def execute_workflow(...) -> WorkflowExecution: ...
    def pause_workflow(...) -> bool: ...
    def resume_workflow(...) -> bool: ...
    def rollback(...) -> bool: ...
```

#### 关键数据结构
- `Workflow`: 工作流定义（workflow_id, steps, trigger_type等）
- `WorkflowStep`: 步骤定义（step_id, action_type, conditions等）
- `WorkflowExecution`: 执行实例（execution_id, status, context等）
- `WorkflowCondition`: 条件表达式（field, operator, value）

### 2.3 状态机设计

```
PENDING ──→ RUNNING ──→ COMPLETED
              │              ↑
              ├──→ PAUSED ─┤
              │              │
              ├──→ FAILED ─┤
              │              │
              └──→ CANCELLED ┘
              
RUNNING/PAUSED ──→ ROLLED_BACK ──→ RUNNING (重新执行)
```

**状态转换规则** (见 `VALID_TRANSITIONS`):
- PENDING → RUNNING, CANCELLED
- RUNNING → PAUSED, COMPLETED, FAILED, CANCELLED, ROLLED_BACK
- PAUSED → RUNNING, CANCELLED, ROLLED_BACK
- COMPLETED → ROLLED_BACK
- FAILED → ROLLED_BACK, CANCELLED

---

## 3. 数据模型

### 3.1 Workflow（工作流）
```python
@dataclass
class Workflow:
    workflow_id: str
    project_id: str
    name: str
    description: str
    trigger_type: TriggerType
    trigger_config: Dict[str, Any]
    steps: List[WorkflowStep]
    is_active: bool = True
    created_at: datetime
    updated_at: datetime
```

### 3.2 WorkflowStep（工作流步骤）
```python
@dataclass
class WorkflowStep:
    step_id: str
    name: str
    description: str
    action_type: ActionType
    action_config: Dict[str, Any]
    conditions: List[WorkflowCondition]
    on_success: Optional[str] = None  # 成功后跳转的步骤ID
    on_failure: Optional[str] = None  # 失败后跳转的步骤ID
    timeout: int = 300  # 超时时间（秒）
    retry_count: int = 0  # 重试次数
    retry_delay: int = 60  # 重试延迟（秒）
```

### 3.3 WorkflowExecution（执行实例）
```python
@dataclass
class WorkflowExecution:
    execution_id: str
    workflow_id: str
    project_id: str
    status: ExecutionStatus
    context: Dict[str, Any]  # 执行上下文
    current_step: Optional[str]
    step_results: Dict[str, Any]  # 各步骤执行结果
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    error_message: Optional[str]
```

### 3.4 存储格式
- **工作流定义**: `data/workflow_{workflow_id}.json`
- **工作流索引**: `data/workflows.json`
- **执行记录**: `data/workflow_executions.json`
- **检查点**: 内存存储（`self._checkpoints`）

---

## 4. API 设计

### 4.1 接口列表

| 方法 | 路径 | 功能 | 请求体 | 响应 |
|------|------|------|--------|------|
| POST | `/api/v1/projects/{project_id}/workflows` | 创建工作流 | WorkflowCreate | 工作流ID |
| GET | `/api/v1/projects/{project_id}/workflows` | 列出工作流 | - | 工作流列表 |
| GET | `/api/v1/projects/{project_id}/workflows/{workflow_id}` | 获取工作流详情 | - | 工作流详情 |
| POST | `/api/v1/projects/{project_id}/workflows/{workflow_id}/execute` | 执行工作流 | WorkflowExecute | 执行ID |
| GET | `/api/v1/projects/{project_id}/workflows/{workflow_id}/executions` | 列出执行记录 | - | 执行记录列表 |
| GET | `/api/v1/projects/{project_id}/workflows/{workflow_id}/executions/{execution_id}` | 获取执行详情 | - | 执行详情 |
| POST | `/api/v1/projects/{project_id}/workflows/{workflow_id}/executions/{execution_id}/pause` | 暂停执行 | - | 成功消息 |
| POST | `/api/v1/projects/{project_id}/workflows/{workflow_id}/executions/{execution_id}/resume` | 恢复执行 | - | 成功消息 |
| POST | `/api/v1/projects/{project_id}/workflows/{workflow_id}/executions/{execution_id}/cancel` | 取消执行 | - | 成功消息 |
| DELETE | `/api/v1/projects/{project_id}/workflows/{workflow_id}` | 删除工作流 | - | 成功消息 |

### 4.2 请求/响应示例

**创建工flow**:
```json
// 请求
POST /api/v1/projects/{project_id}/workflows
{
  "workflow_id": "wf_001",
  "name": "数据处理工作流",
  "description": "处理用户数据并生成报告",
  "trigger_type": "manual",
  "steps": [
    {
      "step_id": "step_1",
      "name": "数据提取",
      "action_type": "agent_task",
      "action_config": {"agent_id": "agent_001", "prompt": "提取数据"},
      "timeout": 300,
      "retry_count": 2
    }
  ]
}

// 响应
{
  "success": true,
  "data": {
    "workflow_id": "wf_001",
    "name": "数据处理工作流",
    "steps_count": 1
  }
}
```

---

## 5. 核心功能实现

### 5.1 工作流执行流程

```
用户调用 execute_workflow()
    ↓
创建 WorkflowExecution 记录
    ↓
asyncio.create_task(_run_workflow())
    ↓
遍历所有步骤 (for step in workflow.steps):
    ↓
检查是否暂停 (if status == PAUSED)
    ↓
创建检查点 (create_checkpoint())
    ↓
评估条件 (_evaluate_conditions())
    ↓
执行步骤 (_execute_step())
    ↓
记录结果并更新状态
    ↓
工作流完成/失败
```

### 5.2 条件评估

支持多种条件操作符：
- 比较: `==`, `!=`, `>`, `<`, `>=`, `<=`
- 成员: `in`, `not in`
- 字符串: `contains`, `startswith`, `endswith`
- 正则: `matches`
- 表达式: 支持复杂逻辑表达式（待增强）

**实现逻辑**:
```python
def _evaluate_conditions(step, context):
    # 1. 检查是否有 condition_expression（复杂表达式）
    if step.condition_expression:
        return _evaluate_expression(step.condition_expression, context)
    
    # 2. 检查条件逻辑 (AND/OR)
    if step.condition_logic:
        return _evaluate_condition_logic(conditions, context, logic)
    
    # 3. 默认：所有条件必须满足 (AND)
    for cond in step.conditions:
        if not _evaluate_single_condition(cond, context):
            return False
    return True
```

### 5.3 并行执行

使用 `asyncio.gather()` 实现并行步骤执行：
```python
async def _handle_parallel(step, context):
    # 创建多个任务
    tasks = [asyncio.create_task(handler(s, context)) for s in parallel_steps]
    
    # 等待所有任务完成
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # 处理结果（区分成功/失败）
    return {"status": overall_status, "results": results}
```

### 5.4 检查点与回滚

**检查点创建**:
```python
def create_checkpoint(execution_id, step_id, additional_data):
    checkpoint_data = {
        "step_id": step_id,
        "context": execution.context.copy(),
        "step_results": execution.step_results.copy(),
        "timestamp": datetime.now().isoformat()
    }
    self._checkpoints[execution_id][step_id] = checkpoint_data
```

**回滚实现**:
```python
def rollback(execution_id, to_step=None):
    # 1. 验证状态转换
    # 2. 确定回滚目标步骤（默认最后一个检查点）
    # 3. 恢复 context 和 step_results
    # 4. 更新执行状态为 ROLLED_BACK
```

### 5.5 暂停/恢复

**暂停**:
```python
def pause_workflow(execution_id, reason):
    execution.status = ExecutionStatus.PAUSED
    self._set_pause_reason(execution_id, reason)
    self._running_executions[execution_id].cancel()
```

**恢复**:
```python
def resume_workflow(execution_id):
    execution.status = ExecutionStatus.RUNNING
    self._clear_pause_reason(execution_id)
    asyncio.create_task(_resume_from_step(execution, workflow))
```

---

## 6. 错误处理

### 6.1 异常类型

| 异常 | 触发条件 | 处理方式 |
|------|----------|----------|
| `ValueError` | 工作流已存在、不存在 | 抛出给API层，返回400错误 |
| `asyncio.TimeoutError` | 步骤执行超时 | 重试或标记为失败 |
| `asyncio.CancelledError` | 工作流被暂停/取消 | 清理资源，更新状态 |
| 通用 `Exception` | 未预期的错误 | 记录日志，标记工作流为FAILED |

### 6.2 重试机制

每个步骤支持配置：
- `retry_count`: 最大重试次数
- `retry_delay`: 重试延迟（秒）

**实现**:
```python
for retry in range(step.retry_count + 1):
    try:
        result = await handler(step, context)
        if result.get("status") != "failed":
            return result
    except Exception as e:
        if retry < step.retry_count:
            await asyncio.sleep(step.retry_delay)
            continue
        return {"status": "failed", "error": str(e)}
```

### 6.3 日志记录

使用 Python `logging` 模块：
- 记录关键操作（创建、执行、暂停、恢复、回滚）
- 记录错误和异常
- 记录性能指标（步骤执行时间等）

---

## 7. 测试计划

### 7.1 单元测试

| 测试项 | 覆盖内容 | 优先级 |
|--------|----------|--------|
| 工作流创建 | 正常创建、重复创建、参数验证 | 高 |
| 工作流执行 | 正常执行、条件分支、并行执行 | 高 |
| 状态转换 | 所有状态转换路径 | 高 |
| 暂停/恢复 | 暂停、恢复、重复暂停 | 中 |
| 回滚 | 回滚到检查点、无效回滚 | 中 |
| 错误处理 | 超时、重试、异常处理 | 高 |
| 条件评估 | 各种操作符、复杂表达式 | 中 |

### 7.2 集成测试

- WorkflowEngine + ExecutionMonitor 集成
- API + WorkflowEngine 集成
- 多工作流并发执行

### 7.3 性能测试

- 大量步骤的工作流执行时间
- 并行执行的并发能力
- 检查点创建和回滚的性能

---

## 8. 安全和性能考虑

### 8.1 安全问题

⚠️ **高危**: 表达式评估使用 `eval()` (Line 791-795)
- **风险**: 远程代码执行
- **建议**: 实现安全的表达式解析器，禁用 `eval()`

⚠️ **中危**: JSON 文件存储
- **风险**: 数据篡改、并发写入冲突
- **建议**: 未来迁移到数据库，增加数据校验

### 8.2 性能优化

- **检查点清理**: 定期清理过期检查点，避免内存泄漏
- **异步优化**: 确保所有的 I/O 操作都是异步的
- **并发控制**: 限制同时运行的工作流数量

### 8.3 可扩展性

- **插件化**: 动作处理器支持动态注册
- **配置化**: 超时、重试等参数可配置
- **监控**: 集成更多监控指标（执行时间、成功率等）

---

## 9. 附录

### 9.1 参考资料
- [Neurova CogArch 2.0 设计文档](../../../01-architecture/NEUROVA_CogArch_2.0.md)
- [ExecutionMonitor 设计](../execution_engine/execution_monitor.py)

### 9.2 变更日志

| 版本 | 日期 | 变更内容 | 作者 |
|------|------|----------|------|
| 1.0 | 2026-05-13 | 初始设计 | workflow-dev |
| 2.0 | 2026-05-13 | 增强版：状态机、回滚、并行执行 | workflow-dev |

---

**审查状态**: 🟡 待审查  
**审查者**: monitor-dev  
**审查日期**: 待定
