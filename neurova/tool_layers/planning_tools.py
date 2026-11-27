# -*- coding: utf-8 -*-
"""planning 工具族——从 neurova.tool_executor 拆出。

`_builtin_dispatch["planning"]="_execute_planning"` 不变。
三层隔离：调用者身份 `(user_id, agent_id)` 经 `_agent_identity()` 注入归属，
计划按归属隔离；`_agent_identity` 由 ToolExecutor 提供。
`PlanningTool(store=get_planning_store())` 单一装配；不顶层 import
`neurova.tool_executor`。
"""
from typing import Dict

from neurova.core.logger import get_logger

__all__ = ["PlanningToolsMixin"]

logger = get_logger(__name__)


class PlanningToolsMixin:
    """planning built-in."""

    async def _execute_planning(self, params: Dict) -> Dict:
        """任务计划工具：7 个子命令（create/update/list/get/set_active/mark_step/delete）。

        三层隔离：调用者身份 (user_id, agent_id) 注入归属，计划按归属隔离。
        """
        command = str(params.get("command") or "").strip()
        if not command:
            return {"error": "缺少 command 参数"}
        try:
            from neurova.planning import PlanningTool, get_planning_store

            tool = PlanningTool(store=get_planning_store())
            try:
                caller_user_id, caller_agent_id = self._agent_identity()
            except Exception:
                caller_user_id, caller_agent_id = "default", "default"
            kwargs = {
                k: v for k, v in params.items() if k != "command" and v is not None
            }
            return await tool.run_command(
                command=command,
                owner_agent_id=caller_agent_id or "default",
                owner_user_id=caller_user_id or "default",
                **kwargs,
            )
        except Exception as e:
            logger.error("planning 工具执行失败: %s", e)
            return {"error": f"planning 工具执行失败: {str(e)}"}
