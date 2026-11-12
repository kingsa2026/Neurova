"""
Shared Core - Neurova 多Agent 共用核心组件

在役一件：
- ExecutionEngine: 执行引擎（脑干）

架构设计：
- 所有 Agent 共用一套脑干
- 每个 Agent 有独立的大脑（Memory Layer）和办公室（Workspace）
- 任务编排不在本包：agent 侧规划走 `neurova/planning/planning_tool.py`，
  HTTP 规划走 `neurova/plan_mode/`（挂在 `/v1/plans`）

P1-14（全库断点审计 2026-11-12，拍板：退役）：InfrastructureManager（原
"脊髓"）全仓零生产消费方，且按其 docstring 接线会经 get_event_bus() 造出
第二个 EventBus（core/event_bus.py 已有全局单例，撞教义第 6 条）——已随
本批退役。
"""

# shared_core imports

