"""Neurova MCP server 面（P1-5 — Dify `core/mcp/server` 对标）。

平台自身作为 MCP server 对外暴露能力：已发布工作流 + 技能聚合为
MCP tools。协议无关核心（list_tools/call_tool），传输层（stdio/SSE
SDK 适配器）另行包壳——Dify 同构：server 核心与传输分离。

复用既有契约，不另起炉灶：
- 工作流工具：workflow_as_tool.build_workflow_tool_schema（P1-3，
  DAG 输入校验天然生效——MCP 面不绕过必填校验）
- 技能工具：skill_registry 清单（skill:{name} 命名空间归一）
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

_SKILL_PREFIX = "skill:"


class NeurovaMCPServer:
    """协议无关 MCP server 核心。

    Args:
        storage: neurflow WorkflowStorage（工作流工具源；None=不暴露工作流）
        skill_registry: SkillRegistry（技能工具源；None=不暴露技能）
    """

    def __init__(self, storage=None, skill_registry=None):
        self._storage = storage
        self._skill_registry = skill_registry

    # ── tools/list ────────────────────────────────────────────

    def list_tools(self) -> List[Dict[str, Any]]:
        """聚合能力清单（MCP tools 形态：name/description/inputSchema）"""
        tools: List[Dict[str, Any]] = []

        if self._storage is not None:
            try:
                from neurova.collaboration.neurflow.workflow_as_tool import (
                    build_workflow_tool_schema,
                )

                for wf in self._storage.list_workflows() or []:
                    status = str(getattr(getattr(wf, "status", None), "value", ""))
                    if status != "published":
                        continue
                    schema = build_workflow_tool_schema(wf)
                    tools.append({
                        "name": schema["name"],
                        "description": schema["description"],
                        "inputSchema": schema["parameters"],
                    })
            except Exception as e:  # noqa: BLE001 — 单源失败不拖垮清单
                logger.warning("MCP server: 工作流清单失败: %s", e)

        if self._skill_registry is not None:
            try:
                skills = getattr(self._skill_registry, "_skills", {}) or {}
                for name, skill in skills.items():
                    tools.append({
                        "name": f"{_SKILL_PREFIX}{name}",
                        "description": getattr(skill, "description", "") or f"技能 {name}",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "task": {"type": "string", "description": "交给技能的任务/输入"},
                            },
                        },
                    })
            except Exception as e:  # noqa: BLE001
                logger.warning("MCP server: 技能清单失败: %s", e)

        return tools

    # ── tools/call ────────────────────────────────────────────

    async def call_tool(self, name: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """按命名空间分派调用（MCP 错误信封：isError=true 不抛异常）"""
        arguments = arguments or {}
        try:
            if name.startswith("workflow:"):
                from neurova.collaboration.neurflow.workflow_as_tool import execute_workflow_as_tool

                wf_id = name[len("workflow:"):]
                outcome = await execute_workflow_as_tool(
                    wf_id, arguments,
                    storage=self._storage,
                    user_id=self._current_user_id(),
                )
                return outcome

            if name.startswith(_SKILL_PREFIX):
                skill_name = name[len(_SKILL_PREFIX):]
                return await self._call_skill(skill_name, arguments)

            # 无前缀：按注册表技能名归一尝试（宽容匹配存量调用习惯）
            if self._skill_registry is not None and name in (getattr(self._skill_registry, "_skills", {}) or {}):
                return await self._call_skill(name, arguments)

            return {"isError": True, "error": f"未知 MCP 工具: {name}"}
        except Exception as e:  # noqa: BLE001 — MCP 语义：错误也是响应
            logger.warning("MCP call_tool %s 失败: %s", name, e)
            return {"isError": True, "error": str(e)}

    async def _call_skill(self, skill_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        skill = (getattr(self._skill_registry, "_skills", {}) or {}).get(skill_name)
        if skill is None:
            return {"isError": True, "error": f"技能未注册: {skill_name}"}
        result = await skill.execute(dict(arguments), None)
        success = bool(getattr(result, "success", False))
        data = getattr(result, "data", None) if success else None
        error = getattr(result, "error", None)
        if success:
            return {"success": True, "result": data}
        return {"success": False, "error": error or "技能执行失败"}

    @staticmethod
    def _current_user_id() -> Optional[str]:
        try:
            from neurova.core.identity_context import get_request_user_id

            return get_request_user_id() or None
        except Exception:  # noqa: BLE001
            return None


__all__ = ["NeurovaMCPServer"]
