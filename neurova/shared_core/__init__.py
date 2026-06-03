"""
Shared Core - Neurova 多Agent 共用核心组件

实现多Agent架构中的共用部分：
- SharedPlanOrchestrator: 共用任务编排器（小脑）
- ExecutionEngine: 执行引擎（脑干）
- InfrastructureManager: 基础设施管理器（脊髓）

架构设计：
- 所有 Agent 共用一套小脑、脑干和脊髓
- 每个 Agent 有独立的大脑（Memory Layer）和办公室（Workspace）
"""

# shared_core imports
import neurova.shared_core.execution_engine
import neurova.shared_core.infrastructure
import neurova.shared_core.plan_orchestrator

pass