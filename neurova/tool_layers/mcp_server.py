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

# R3-3 CUA 双层 MCP 导出（docs/Neurova_CUA_Phase3立项_2026-09-12.md §2）
_CUA_EXPORT_ENV = "NEUROVA_CUA_MCP_EXPORT"
_RUN_COMPUTER_TASK = "run_computer_task"


class NeurovaMCPServer:
    """协议无关 MCP server 核心。

    Args:
        storage: neurflow WorkflowStorage（工作流工具源；None=不暴露工作流）
        skill_registry: SkillRegistry（技能工具源；None=不暴露技能）
        agent_ref: Agent（R3-3 CUA 导出源；None=不暴露 computer_*/run_computer_task）
    """

    def __init__(self, storage=None, skill_registry=None, agent_ref=None, agent_provider=None):
        self._storage = storage
        self._skill_registry = skill_registry
        self._agent_ref = agent_ref
        self._agent_provider = agent_provider

    def _resolve_agent(self):
        """惰性解析 agent：优先构造注入，其次 provider（生产单例在首次 MCP
        调用时 agent 可能尚未就绪，provider 每次现取）。"""
        if self._agent_ref is not None:
            return self._agent_ref
        if self._agent_provider is not None:
            try:
                return self._agent_provider()
            except Exception:  # noqa: BLE001
                return None
        return None

    # ── R3-3 CUA 导出 ─────────────────────────────────────────

    @staticmethod
    def _computer_export_enabled() -> bool:
        """默认关：仅 env NEUROVA_CUA_MCP_EXPORT ∈ {1,true,yes} 时导出。"""
        import os

        return os.environ.get(_CUA_EXPORT_ENV, "").strip().lower() in ("1", "true", "yes")

    @staticmethod
    def _computer_tool_names() -> list:
        from neurova.builtin_tools import _BUILTIN_SCHEMAS

        return [k for k in _BUILTIN_SCHEMAS if k.startswith("computer_")]

    def _cua_export_active(self) -> bool:
        return self._computer_export_enabled() and self._resolve_agent() is not None


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

        # R3-3 工具面：computer_* 全量（schema 复用 builtin_tools 单一来源，不复制）
        if self._cua_export_active():
            try:
                from neurova.builtin_tools import _BUILTIN_SCHEMAS

                for name in self._computer_tool_names():
                    spec = _BUILTIN_SCHEMAS.get(name) or {}
                    tools.append({
                        "name": name,
                        "description": spec.get("description", name),
                        "inputSchema": spec.get("parameters", {"type": "object", "properties": {}}),
                    })
                tools.append({
                    "name": _RUN_COMPUTER_TASK,
                    "description": "【Agent 面】把一个桌面目标交给 Neurova agent 跑一整轮（内部自行观察→语义→动作），返回最终回复",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"goal": {"type": "string", "description": "桌面任务目标"}},
                        "required": ["goal"],
                    },
                })
            except Exception as e:  # noqa: BLE001
                logger.warning("MCP server: CUA 清单失败: %s", e)

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

            # R3-3 CUA 导出面（工具面 computer_* + agent 面 run_computer_task）
            if name.startswith("computer_") or name == _RUN_COMPUTER_TASK:
                return await self._call_computer(name, arguments)

            # 无前缀：按注册表技能名归一尝试（宽容匹配存量调用习惯）
            if self._skill_registry is not None and name in (getattr(self._skill_registry, "_skills", {}) or {}):
                return await self._call_skill(name, arguments)

            return {"isError": True, "error": f"未知 MCP 工具: {name}"}
        except Exception as e:  # noqa: BLE001 — MCP 语义：错误也是响应
            logger.warning("MCP call_tool %s 失败: %s", name, e)
            return {"isError": True, "error": str(e)}

    async def _call_computer(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """R3-3 CUA 导出路由。默认关时按名调用也拒（导出面与清单同源开关）。

        工具面：路由到 ToolExecutor._execute_single_tool（单一实现源，走同一
        governance 预检/桌面审计/ActionResult，与内部直调逐字段等价，不复制实现、
        不绕治理）。agent 面：agent.chat(goal) 跑一整轮。
        """
        if not self._cua_export_active():
            return {"isError": True, "error": "CUA MCP 导出未启用（设 NEUROVA_CUA_MCP_EXPORT=1 且提供 agent）"}
        agent = self._resolve_agent()
        if agent is None:
            return {"isError": True, "error": "CUA 导出需要 agent"}

        # 身份透传：MCP 调用方 user 经 ContextVar 落到执行链（三层隔离）
        uid = self._current_user_id()
        if uid:
            try:
                from neurova.core.identity_context import set_request_user_id

                set_request_user_id(uid)
            except Exception:  # noqa: BLE001
                pass

        if name == _RUN_COMPUTER_TASK:
            goal = str((arguments or {}).get("goal", "")).strip()
            if not goal:
                return {"isError": True, "error": "run_computer_task 需要 goal"}
            reply = await agent.chat(goal)
            if isinstance(reply, dict):
                return {"success": bool(reply.get("success", True)), "result": reply.get("reply", reply)}
            return {"success": True, "result": reply}

        from neurova.tool_executor import ToolExecutor

        executor = ToolExecutor(agent)
        return await executor._execute_single_tool(name, dict(arguments or {}), skip_governance=False)

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
