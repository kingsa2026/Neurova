"""
Shared Core - Neurova 多Agent 共用核心组件

在役两件：
- ExecutionEngine: 执行引擎（脑干）
- InfrastructureManager: 基础设施管理器（脊髓）

架构设计：
- 所有 Agent 共用一套脑干与脊髓
- 每个 Agent 有独立的大脑（Memory Layer）和办公室（Workspace）
- 任务编排不在本包：agent 侧规划走 `neurova/planning/planning_tool.py`，
  HTTP 规划走 `neurova/plan_mode/`（挂在 `/v1/plans`）
"""

# shared_core imports

