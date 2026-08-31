# Bug 修复：Agent 核心不感知 Neurflow

## 问题描述

`agent_core.py` 中没有任何 Neurflow 的引用。Agent 核心完全不知道 Neurflow 的存在，工作流执行结果不会自动反馈到 Agent 的记忆系统或进化系统。

## 根因分析

Neurflow 执行引擎是自包含的：
1. `WorkflowExecutor.execute()` 返回 `ExecutionInstance`，包含 `node_results`、`outputs`、`status`、`duration`
2. `neurflow_api.py` 端点只调用 `storage.save_execution(instance)` 保存到本地存储
3. 没有将执行结果反馈给 Agent 的记忆系统或进化系统
4. `agent_core.py` 无任何 `neurflow`/`workflow` 引用

## 修复内容

### 1. WorkflowExecutor — 添加 `get_recent_executions()` 方法

**文件**: `neurova/collaboration/neurflow/execution_engine.py`

新增 `get_recent_executions(agent_id, user_id, limit, since_timestamp)` 方法：
- 按 Agent ID、用户 ID 过滤
- 按时间戳过滤（默认 5 分钟内）
- 只返回已完成/已失败/已取消的执行
- 按开始时间降序排列
- 支持限制返回数量

### 2. PostChatPipeline — 添加 `_step_record_workflow_experience()` 步骤

**文件**: `neurova/post_chat_pipeline.py`

新增步骤 9.05：
- 从 WorkflowExecutor 获取最近的执行记录（5 分钟内）
- 只记录状态为 `completed` 的成功执行
- 构建经验内容：工作流 ID、节点数、成功节点数、耗时、输出摘要
- 调用 `memory_manager.remember()` 存储为 `workflow_experience` 类型记忆
- 记录元数据：workflow_id、execution_id、duration、node_count、successful_nodes、session_id、source

### 3. Agent — 绑定 Neurflow 执行引擎

**文件**: `neurova/agent_core.py`

在 Agent 初始化时：
- 导入 `get_workflow_executor` 单例
- 设置 `self.neurflow_executor` 属性
- PostChatPipeline 通过 `_get_dependency("neurflow_executor")` 自动获取

### 4. 数据流

```
用户对话完成
  → PostChatPipeline.process()
    → 步骤 9: _step_record_experience()  [现有]
    → 步骤 9.05: _step_record_workflow_experience()  [新增]
      → neurflow_executor.get_recent_executions(agent_id, limit=5)
      → 过滤 completed 状态的执行
      → memory_manager.remember(content=经验内容, memory_type="workflow_experience")
    → 步骤 9.1: _step_evocate_generation()  [现有]
```

下次对话时：
```
用户输入
  → memory_manager.recall(查询) → 包含 workflow_experience 类型记忆
  → 注入上下文 → LLM 可利用工作流经验
```

## 修改文件清单

1. `neurova/collaboration/neurflow/execution_engine.py` — 新增 `get_recent_executions()` 方法
2. `neurova/post_chat_pipeline.py` — 新增 `_step_record_workflow_experience()` 步骤 + 配置项
3. `neurova/agent_core.py` — 初始化时绑定 `neurflow_executor`
4. `tests/unit/test_agent_neurflow_integration.py` — 新增 10 个测试

## 测试结果

- 10/10 测试通过
- 0 个 linter 错误
