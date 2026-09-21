"""原生 function-calling 链到执行咽喉的改道（工单 003）。

`agent/loops/base.py` 的两条出口（`SkillRegistry.execute_skill` / `ToolRouter.execute`）
此前各自为政，不经 `ToolExecutor._execute_single_tool_inner`，于是同一次工具执行拿不到
客观票据（`creation_governance.record_tool_execution`）、`on_tool_executed`（肌肉记忆/
生命周期）、统一治理预检、Pre/PostToolUse hooks 与 per-tool 超时。更糟的是两条链对
同一个失败工具会给出**不同的 success 值**：router 把 `{"error": …}` 包成
`ToolResult(success=True)`，`base.py` 于是恒真 ⇒ 假成功票。

本模块把改道收在一处：原生链只解析参数、落展示记录，执行一律委托咽喉。成败判据复用
咽喉的 `_result_is_success`（**单源**，此处不再写第二份内容判据）。

身份与沙箱根**不**回退成 LLM 可伪造的参数：`_caller_user_id` 由
`ToolExecutor.execute_skill_tool` 注入、`file_operation._base_dir` 由
`ToolExecutor._workspace_base` 赋值，两者都留在咽喉内。
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)


async def execute_native_tool(agent: Any, tool_name: str,
                              params: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """经执行咽喉跑一条原生工具调用，返回归一后的成败与结果。

    Returns:
        `{"success": bool, "result": Any, "error": Optional[str]}`——成败取自咽喉的
        `_result_is_success`，不再由调用侧按"有没有抛异常"猜。
    """
    executor = getattr(agent, "tool_executor", None)
    if executor is None:
        return {"success": False, "result": None, "error": "工具执行器未装配，原生工具调用无法执行"}

    try:
        raw = await executor.execute_tool(tool_name, dict(params or {}))
    except Exception as err:  # noqa: BLE001 - 咽喉异常即该工具失败，不许静默成功
        logger.warning("原生工具调用经咽喉执行异常: %s, %s", tool_name, err)
        return {"success": False, "result": None, "error": f"工具执行异常: {err}"}

    if not isinstance(raw, dict):
        raw = {"result": raw}
    success = executor._result_is_success(raw)
    error = None if success else (raw.get("error") or f"工具执行失败: {tool_name}")
    return {"success": success, "result": raw, "error": error}
