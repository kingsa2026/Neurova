"""
Neurova CogArch 1.0.0 - 执行引擎（手脚）

核心模块：
- tool_engine: 工具引擎 - 智能工具选择与执行
- agent_colab: 多Agent协作引擎
- execution_monitor: 执行监控器
- mcp_manager: MCP 协议管理器

（本门面原先还列着 `workflow_engine`（CogArch 1.0 任务型线性链）。它自己那份 docstring 早已声明
deprecated 与"迁移完成后整体删除"，而它的唯一生产引用是 `shared_core.ExecutionEngine._init_components`
里那份从不被读取的组件实例——那条孤儿装配随台账 §6-303 的档案退役后，本模块再无来路，遂整体删除。
真工作流引擎是 `collaboration/neurflow/`（拓扑分层＋层内并发＋`safe_eval_condition` 真分支＋检查点）。）

（原列在此处的 `plan_orchestrator`（计划编排器/小脑）从未被本门面导入或再导出，且生产侧
零消费者——它自称的步骤状态机与真重试从未可达（执行表零注册方），那两格能力现已落在
服务路上的 `collaboration/neurflow/execution_engine.py`（层内并发上限 + 幂等声明门的
节点级重试）。台账 §6-157 比对、§6-166 退役。）

本门面原先把这条再导出包在 `try/except ImportError` 里，handler 里定义九个**同名空类**顶替
真身（八枚只有 docstring，`ToolStatus` 那枚另抄四份状态常量）。按批 43 已裁口径，被包的
`tool_engine` 其模块级闭包只碰 stdlib 与本仓（`neurova.core.logger`），这条兜底**永不可达**；
而它一旦真触发（循环导入、路径没装好），调用方拿到的是"看着像"的空类——比拿到 `None` 更坏，
`None` 下一行就炸，空类能一路走下去。故直接导入，不再兜。台账 §6-224。
"""

from .tool_engine import (
    ToolCallingContext,
    ToolDefinition,
    ToolDiscoveryResult,
    ToolEngine,
    ToolInvocation,
    ToolParameter,
    ToolSelection,
    ToolStatus,
    ToolVersion,
)

# 本门面给出去的公开面（§6-224）：这九名是包外真在经包路径取用的那一圈，
# 由 tests/unit/core/test_packageDeclaredSurfaceCoversWhatIsTaken.py 逐名复核「在 __all__ 里 ∧
# 取得到 ∧ 真身来自 tool_engine」。
__all__ = [
    "ToolCallingContext",
    "ToolDefinition",
    "ToolDiscoveryResult",
    "ToolEngine",
    "ToolInvocation",
    "ToolParameter",
    "ToolSelection",
    "ToolStatus",
    "ToolVersion",
]
