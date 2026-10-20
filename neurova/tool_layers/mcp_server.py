"""Neurova MCP server 面。

平台自身作为 MCP server 对外暴露能力：已发布工作流 + 技能聚合为
MCP tools。协议无关核心（list_tools/call_tool），传输层（stdio/SSE
server 核心与传输分离

复用既有契约，不另起炉灶：
- 工作流工具：workflow_as_tool.build_workflow_tool_schema（P1-3，
  DAG 输入校验天然生效——MCP 面不绕过必填校验）
- 技能工具：清单取 skill_registry（skill:{name} 命名空间归一），
  执行一律经 ToolExecutor.execute_skill_tool 咽喉，本面不自建第二条技能通路
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

_SKILL_PREFIX = "skill:"

_CUA_EXPORT_ENV = "NEUROVA_CUA_MCP_EXPORT"
_RUN_COMPUTER_TASK = "run_computer_task"

#: 失败文案的取值顺序：`error` 是三条腿共同的拒因位，后三个是"没写成 error 但体里有话"
#: 的兜底（技能 output / 工具 result / agent 回合 reply）——统一信封不许顺手把内容丢掉。
_FAILURE_TEXT_KEYS = ("error", "output", "result", "reply")


def _mcpEnvelope(raw: Any) -> Dict[str, Any]:
    """把任意一条腿的返回值收成**一种**失败形状（§6-334 的 B 票裁甲）。

    判"失败"只看两条：显式 `success=False`，或**根本没有 success 键却带 error**
    （技能咽喉的拒绝体与安全钩子拦截之外的裸错误体都属这一形）。
    成功侧逐字段原样透传——工具面"与内部执行结果等价、不加工"那条承诺由这一句守着，
    B 票不许把它顺带削掉。
    """
    if not isinstance(raw, dict):
        return {"success": True, "result": raw}
    if raw.get("isError"):
        return raw
    failed = raw.get("success") is False or ("success" not in raw and raw.get("error"))
    if not failed:
        return raw
    for key in _FAILURE_TEXT_KEYS:
        value = raw.get(key)
        if value:
            text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
            return {"isError": True, "error": text}
    return {"isError": True, "error": "工具执行失败"}


class NeurovaMCPServer:
    """协议无关 MCP server 核心。

    Args:
        storage: neurflow WorkflowStorage（工作流工具源；None=不暴露工作流）
        skill_registry: SkillRegistry（技能清单源；None=不暴露技能）
        agent_ref / agent_provider: 执行侧的 agent（技能腿与 computer 腿都要它
            才能过 ToolExecutor；两者都给时优先 agent_ref）
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
        """按命名空间分派调用，**出口只归一次形**（`_mcpEnvelope`）。

        分派与信封解耦是这一格的根修处：三条腿各有各的失败写法（工作流回
        `success=False` 业务体、技能咽喉回只带 `error` 的拒绝体、CUA 工具面回执行器
        原始 dict），若在每条腿里各转一次，第四条腿加进来时必然漏转——那正是
        §6-334 的 B 票登记的"同一失败两种信封"的成因。
        """
        arguments = arguments or {}
        try:
            return _mcpEnvelope(await self._dispatch(name, arguments))
        except Exception as e:  # noqa: BLE001 — MCP 语义：错误也是响应
            logger.warning("MCP call_tool %s 失败: %s", name, e)
            return {"isError": True, "error": str(e)}

    async def _dispatch(self, name: str, arguments: Dict[str, Any]) -> Any:
        """命名空间分派——只管"交给谁执行"，不管"回什么形状"。"""
        if name.startswith("workflow:"):
            from neurova.collaboration.neurflow.workflow_as_tool import execute_workflow_as_tool

            wf_id = name[len("workflow:"):]
            return await execute_workflow_as_tool(
                wf_id, arguments,
                storage=self._storage,
                user_id=self._current_user_id(),
            )

        if name.startswith(_SKILL_PREFIX):
            return await self._call_skill(name[len(_SKILL_PREFIX):], arguments)

        if name.startswith("computer_") or name == _RUN_COMPUTER_TASK:
            return await self._call_computer(name, arguments)

        # 无前缀：按注册表技能名归一尝试（宽容匹配存量调用习惯）
        if self._skill_registry is not None and name in (getattr(self._skill_registry, "_skills", {}) or {}):
            return await self._call_skill(name, arguments)

        return {"isError": True, "error": f"未知 MCP 工具: {name}"}

    async def _call_computer(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """默认关时按名调用也拒（导出面与清单同源开关）

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
        """技能腿一律走 `ToolExecutor.execute_skill_tool` 那道咽喉，无 agent 即拒。

        咽喉上挂着四件本面补不出的事：轮级可见门（Wave H-W2）、声明式权限作用域
        （P0-4）、沙箱根注入、P0-1 质量漏斗记账。直调 `skill.execute` 等于把这四件
        一起绕掉——所以这里没有"拿不到 agent 就退回直调"的兜底，只有 fail-closed。

        清单源与执行源**不是同一份注册表**（这条是实测，不是推理）：清单读构造期注入的
        那一份（生产里是 `get_skill_registry()` 全局单例），执行读 `agent._skill_registry`
        ——后者由 `create_default_skills()` 每 agent 现造，两份从来没有同源过。于是两个
        方向都会出现：advertised 而调用判「不存在」，以及**清单从未列出而点名仍能执行**。
        更重的一条：这道咽喉的轮级可见门（Wave H-W2）在本面这条路上读到的视图恒为 `None`
        ——全仓 `set_turn_skill_view` 只有一个写点（`neurova/agent/chat_pipeline.py` 的
        回合装配段），MCP 请求边界不经过它。所以"接进咽喉"实际只带来权限作用域、沙箱根
        注入与漏斗记账三件，可见集那一件在这条路上是空转的。
        缺陷档案与三态票见台账 §6-352；本段不写"这是正确行为"。
        """
        agent = self._resolve_agent()
        if agent is None:
            return {
                "isError": True,
                "error": f"技能 {skill_name} 需要 agent 才能过治理咽喉（可见门/权限作用域/沙箱根/漏斗记账），当前无 agent",
            }

        from neurova.tool_executor import ToolExecutor

        outcome = await ToolExecutor(agent).execute_skill_tool(skill_name, dict(arguments or {}), None)
        # 成功侧只做一件事：把咽喉的 `output` 归到 MCP 的 `result` 位。
        # 失败侧一律原样交给 `call_tool` 出口那一次归形——这里不再攒第二种判断。
        if outcome.get("success") is True:
            return {"success": True, "result": outcome.get("output")}
        return outcome

    @staticmethod
    def _current_user_id() -> Optional[str]:
        try:
            from neurova.core.identity_context import get_request_user_id

            return get_request_user_id() or None
        except Exception:  # noqa: BLE001
            return None


__all__ = ["NeurovaMCPServer"]
