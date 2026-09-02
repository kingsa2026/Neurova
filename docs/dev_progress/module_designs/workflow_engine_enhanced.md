# Workflow Engine 增强 - 模块设计文档

> **版本**: 1.0  
> **日期**: 2026-05-13  
> **作者**: workflow-dev  
> **状态**: 设计完成，实现中  

---

## 一、模块概述

### 1.1 模块名称
Workflow Engine 增强（Workflow Engine Enhancement）

### 1.2 模块定位
本模块属于 Neurova CogArch 2.0 架构中的**工作流编排层**，负责统一管理复杂任务的自动化执行流程。

### 1.3 设计目标
1. 提供完整的工作流状态机管理
2. 支持工作流的暂停、恢复和回滚
3. 实现条件分支和并行执行
4. 提供执行监控和错误处理
5. 支持多种动作类型和触发器

---

## 二、架构设计

### 2.1 整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                    Workflow Engine 增强                         │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │               工作流管理层                                │ │
│  │  ┌────────────┐  ┌────────────┐  ┌─────────────────┐│ │
│  │  │  Workflow │  │  Workflow  │  │  Workflow       ││ │
│  │  │  Engine    │  │  Execution │  │  Scheduler     ││ │
│  │  └────────────┘  └────────────┘  └─────────────────┘│ │
│  └──────────────────────────────────────────────────────────┘ │
│                           ↓                                  │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │               执行引擎层                                  │ │
│  │  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐   │ │
│  │  │Step  │ │Cond- │ │Paral-│ │Pause/│ │Roll- │...│ │
│  │  │Exec  │ │ition │ │lel   │ │Resume│ │back  │   │ │
│  │  └──────┘ └──────┘ └──────┘ └──────┘ └──────┘   │ │
│  └──────────────────────────────────────────────────────────┘ │
│                           ↓                                  │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │               监控与集成层                                │ │
│  │  ┌────────────┐  ┌─────────────┐  ┌──────────────┐ │ │
│  │  │Execution  │  │  Checkpoint │  │  Event        │ │ │
│  │  │Monitor     │  │  & Rollback │  │  Bus          │ │ │
│  │  └────────────┘  └─────────────┘  └──────────────┘ │ │
│  └──────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 目录结构

```
neurova/projects/
├── models.py                   # 数据模型（Workflow, WorkflowStep等）
├── workflow_engine.py          # 工作流引擎核心实现
├── test_workflow_engine.py    # 单元测试
└── data/
    ├── workflows.json         # 工作流定义存储
    └── workflow_executions.json  # 执行记录存储

neurova/api/endpoints/
└── workflows_api.py          # Workflow API 端点
```

---

## 三、详细设计

### 3.1 核心数据模型（models.py）

#### 3.1.1 枚举类型

**ActionType（动作类型）**
- AGENT_TASK: Agent任务
- APPROVAL: 审批
- NOTIFICATION: 通知
- CONDITION: 条件判断
- PARALLEL: 并行执行
- WAIT: 等待
- HTTP_REQUEST: HTTP请求

**TriggerType（触发器类型）**
- MANUAL: 手动触发
- SCHEDULED: 定时触发
- EVENT: 事件触发
- WEBHOOK: Webhook触发

**ExecutionStatus（执行状态）**
- PENDING: 待执行
- RUNNING: 执行中
- PAUSED: 已暂停
- COMPLETED: 已完成
- FAILED: 失败
- CANCELLED: 已取消
- ROLLED_BACK: 已回滚

#### 3.1.2 数据类

**WorkflowCondition**
- field: 条件字段
- operator: 操作符（==, !=, >, <, >=, <=, in, not in, contains, startswith, endswith, matches）
- value: 比较值

**WorkflowStep**
- step_id: 步骤ID
- name: 步骤名称
- description: 步骤描述
- action_type: 动作类型
- action_config: 动作配置
- conditions: 条件列表
- on_success: 成功跳转
- on_failure: 失败跳转
- timeout: 超时时间（秒）
- retry_count: 重试次数
- retry_delay: 重试延迟（秒）

**Workflow**
- workflow_id: 工作流ID
- project_id: 项目ID
- name: 工作流名称
- description: 工作流描述
- trigger_type: 触发器类型
- trigger_config: 触发器配置
- steps: 步骤列表
- is_active: 是否激活
- created_at: 创建时间
- updated_at: 更新时间

**WorkflowExecution**
- execution_id: 执行ID
- workflow_id: 工作流ID
- project_id: 项目ID
- status: 执行状态
- context: 执行上下文
- current_step: 当前步骤
- step_results: 步骤结果
- started_at: 开始时间
- completed_at: 完成时间
- error_message: 错误信息

### 3.2 工作流引擎核心（workflow_engine.py）

#### 3.2.1 WorkflowEngine 类

**核心属性**：
- base_path: 数据存储路径
- workflows_file: 工作流定义文件
- executions_file: 执行记录文件
- _action_handlers: 动作处理器字典
- _running_executions: 运行中的执行任务
- _pause_reasons: 暂停原因跟踪
- _checkpoints: 检查点跟踪
- _rollback_points: 回滚点跟踪
- _monitor: ExecutionMonitor 集成

**核心方法**：

1. **工作流管理**
   - `create_workflow()`: 创建工作流
   - `get_workflow()`: 获取工作流
   - `update_workflow()`: 更新工作流
   - `delete_workflow()`: 删除工作流
   - `get_workflows_by_project()`: 获取项目下的工作流

2. **执行管理**
   - `execute_workflow()`: 执行工作流
   - `_run_workflow()`: 运行工作流（增强版）
   - `_execute_step()`: 执行单个步骤（增强版）
   - `pause_workflow()`: 暂停工作流
   - `resume_workflow()`: 恢复工作流
   - `cancel_execution()`: 取消执行

3. **检查点与回滚**
   - `create_checkpoint()`: 创建检查点
   - `get_rollback_points()`: 获取可回滚点列表
   - `rollback()`: 回滚工作流到指定步骤

4. **条件评估**
   - `_evaluate_conditions()`: 增强的条件评估
   - `_evaluate_single_condition()`: 评估单个条件
   - `_evaluate_condition_logic()`: 评估带逻辑的条件
   - `_evaluate_expression()`: 评估条件表达式

5. **动作处理器**
   - `_handle_agent_task()`: 处理Agent任务
   - `_handle_approval()`: 处理审批
   - `_handle_notification()`: 处理通知
   - `_handle_condition()`: 处理条件判断
   - `_handle_parallel()`: 处理并行执行（增强版）
   - `_handle_wait()`: 处理等待
   - `_handle_http_request()`: 处理HTTP请求

6. **状态管理**
   - `_validate_status_transition()`: 验证状态转换
   - VALID_TRANSITIONS: 有效的状态转换映射

#### 3.2.2 状态机设计

**状态转换规则**：
```
PENDING → RUNNING, CANCELLED
RUNNING → PAUSED, COMPLETED, FAILED, CANCELLED, ROLLED_BACK
PAUSED → RUNNING, CANCELLED, ROLLED_BACK
COMPLETED → ROLLED_BACK
FAILED → ROLLED_BACK, CANCELLED
CANCELLED → []
ROLLED_BACK → RUNNING (回滚后可以重新运行)
```

#### 3.2.3 条件评估增强

**支持的操作符**：
- 基本比较：==, !=, >, <, >=, <=
- 集合操作：in, not in
- 字符串操作：contains, startswith, endswith
- 正则匹配：matches

**条件逻辑**：
- AND逻辑：所有条件必须满足（默认）
- OR逻辑：任一条件满足即可

**表达式支持**：
- 支持点号访问嵌套字段（e.g., "user.profile.age"）
- 支持条件表达式（e.g., "user.age > 18 AND user.status == 'active'"）

#### 3.2.4 并行执行增强

**功能特性**：
- 支持多个步骤并行执行
- 使用 asyncio.gather 收集结果
- 支持 fail_fast 配置
- 错误处理和结果收集

**返回结果**：
- status: 整体状态（completed, failed, partial_success）
- total: 总步骤数
- success_count: 成功步骤数
- error_count: 错误步骤数
- results: 详细结果列表
- errors: 错误列表

#### 3.2.5 检查点与回滚

**检查点功能**：
- 在每个步骤执行前创建检查点
- 保存上下文和步骤结果
- 支持回滚到任意检查点

**回滚功能**：
- 验证状态转换
- 恢复上下文和步骤结果
- 取消正在运行的任务
- 记录回滚操作到 ExecutionMonitor

### 3.3 ExecutionMonitor 集成

#### 3.3.1 集成点

**工作流级别**：
- `start_workflow_execution()`: 记录工作流执行开始
- `finish_workflow_execution()`: 记录工作流执行完成
- `fail_workflow_execution()`: 记录工作流执行失败
- `record_workflow_pause()`: 记录工作流暂停
- `record_workflow_resume()`: 记录工作流恢复
- `record_rollback()`: 记录回滚操作

**步骤级别**：
- `start_step()`: 记录步骤开始
- `finish_step()`: 记录步骤完成
- `skip_step()`: 记录步骤跳过

#### 3.3.2 集成方式

- 使用 try-except 导入 ExecutionMonitor
- 如果导入失败，禁用监控功能
- 使用 asyncio.create_task 异步记录，不阻塞主流程
- 记录失败不影响主流程执行

### 3.4 API 设计（workflows_api.py）

#### 3.4.1 端点列表

| 方法 | 路径 | 功能 |
|------|------|------|
| POST | /api/v1/projects/{project_id}/workflows | 创建工作流 |
| GET | /api/v1/projects/{project_id}/workflows | 列出项目工作流 |
| GET | /api/v1/projects/{project_id}/workflows/{workflow_id} | 获取工作流详情 |
| POST | /api/v1/projects/{project_id}/workflows/{workflow_id}/execute | 执行工作流 |
| GET | /api/v1/projects/{project_id}/workflows/{workflow_id}/executions | 列出执行记录 |
| GET | /api/v1/projects/{project_id}/workflows/{workflow_id}/executions/{execution_id} | 获取执行详情 |
| POST | /api/v1/projects/{project_id}/workflows/{workflow_id}/executions/{execution_id}/pause | 暂停执行 |
| POST | /api/v1/projects/{project_id}/workflows/{workflow_id}/executions/{execution_id}/resume | 恢复执行 |
| POST | /api/v1/projects/{project_id}/workflows/{workflow_id}/executions/{execution_id}/cancel | 取消执行 |
| DELETE | /api/v1/projects/{project_id}/workflows/{workflow_id} | 删除工作流 |

#### 3.4.2 请求/响应格式

**创建工作流**：
```json
POST /api/v1/projects/{project_id}/workflows
{
  "workflow_id": "workflow_001",
  "name": "测试工作流",
  "description": "这是一个测试工作流",
  "trigger_type": "manual",
  "trigger_config": {},
  "steps": [
    {
      "step_id": "step_1",
      "name": "步骤1",
      "action_type": "agent_task",
      "action_config": {
        "agent_id": "agent_001",
        "prompt": "执行任务"
      }
    }
  ]
}
```

**执行工作流**：
```json
POST /api/v1/projects/{project_id}/workflows/{workflow_id}/execute
{
  "context": {
    "user": "test_user",
    "priority": "high"
  }
}
```

---

## 四、测试计划

### 4.1 单元测试（test_workflow_engine.py）

| 测试类 | 测试方法 | 测试内容 |
|--------|----------|----------|
| TestWorkflowEngine | test_create_workflow | 创建工作流 |
| | test_get_workflow | 获取工作流 |
| | test_update_workflow | 更新工作流 |
| | test_get_workflows_by_project | 获取项目下的工作流 |
| | test_execute_workflow | 执行工作流 |
| | test_condition_workflow | 条件工作流 |
| | test_parallel_workflow | 并行工作流 |
| | test_pause_workflow | 暂停工作流 |
| | test_cancel_execution | 取消执行 |
| | test_delete_workflow | 删除工作流 |
| | test_rollback_workflow | 回滚工作流 |
| | test_checkpoint_creation | 创建检查点 |
| | test_condition_evaluation | 条件评估 |
| | test_parallel_execution | 并行执行 |
| | test_status_transition | 状态转换 |

**总计**: 15+ 个测试用例

### 4.2 集成测试

- 与 ExecutionMonitor 集成测试
- 与 ProjectManager 集成测试
- API 端点集成测试

---

## 五、依赖关系

### 5.1 外部依赖

| 依赖包 | 版本 | 用途 |
|--------|------|------|
| fastapi | >=0.100.0 | Web API 框架 |
| pydantic | >=2.0.0 | 数据验证 |
| aiohttp | >=3.8.0 | 异步 HTTP 请求 |

### 5.2 内部依赖

- `neurova.execution_engine.execution_monitor` - 执行监控
- `neurova.projects.models` - 数据模型

---

## 六、集成计划

### 6.1 与现有系统集成

1. **与 ProjectManager 集成**
   - 工作流绑定到项目
   - 项目删除时清理工作流

2. **与 ExecutionMonitor 集成**
   - 记录工作流执行过程
   - 监控性能和错误

3. **与前端集成**
   - 提供 Workflow API
   - 前端页面：Workflow Designer

---

## 七、时间安排

| 阶段 | 时间 | 内容 |
|------|------|------|
| 设计阶段 | 第1天 | 完成模块设计文档 |
| 实现阶段 | 第1-2天 | 实现工作流引擎核心功能 |
| 实现阶段 | 第2天 | 实现暂停/恢复/回滚功能 |
| 实现阶段 | 第2-3天 | 实现条件分支和并行执行 |
| 实现阶段 | 第3天 | 实现 ExecutionMonitor 集成 |
| 测试阶段 | 第3-4天 | 编写单元测试 |
| 文档阶段 | 第4天 | 编写 API 文档 |
| 集成阶段 | 第4-5天 | 与现有系统集成 |

---

## 八、风险评估

| 风险 | 影响 | 应对措施 |
|------|------|----------|
| 并行执行复杂度高 | 高 | 使用 asyncio.gather，充分测试 |
| 状态转换逻辑复杂 | 高 | 明确状态转换规则，编写单元测试 |
| 回滚功能实现复杂 | 中 | 使用检查点机制，分步实现 |
| 条件表达式解析安全风险 | 中 | 使用安全的表达式解析器 |

---

## 九、当前进度

### 9.1 已完成功能（60%）

✅ **核心功能**：
- 工作流创建、获取、更新、删除
- 工作流执行（基本流程）
- 动作处理器（7种类型）
- 状态机管理

✅ **增强功能**：
- 暂停/恢复功能
- 回滚功能（检查点机制）
- 条件分支（增强评估）
- 并行执行（增强版）
- ExecutionMonitor 集成

✅ **API 端点**：
- 完整的工作流 API（10个端点）

✅ **测试**：
- 基本单元测试（10个测试用例）

### 9.2 待完成功能（40%）

❌ **需要增强的功能**：
1. 定时触发器（SCHEDULED trigger）
2. 事件触发器（EVENT trigger）
3. Webhook触发器（WEBHOOK trigger）
4. 步骤跳转逻辑（on_success, on_failure）
5. 更完整的表达式解析器
6. 工作流可视化（DAG）
7. 工作流版本管理

❌ **需要完善的测试**：
1. 增加测试用例到 15+ 个
2. 测试覆盖率 > 80%
3. 集成测试

❌ **需要完善的文档**：
1. API 使用文档
2. 工作流设计指南
3. 示例代码

---

## 十、总结

本模块实现了增强的工作流引擎，支持完整的状态机、暂停/恢复、回滚、条件分支、并行执行、执行监控等功能。参考了业界最佳实践，同时保持了与 Neurova 现有架构的兼容性。

**核心优势**：
1. 完整的状态机管理
2. 灵活的暂停/恢复和回滚机制
3. 强大的条件评估和并行执行
4. 完善的执行监控和错误处理
5. 丰富的 API 接口

**下一步计划**：
1. 完成剩余40%功能（触发器、步骤跳转等）
2. 编写更多单元测试（覆盖率>80%）
3. 完善文档和示例代码
4. 与现有系统集成测试

---

**文档版本历史**：
- v1.0 (2026-05-13): 初始版本
