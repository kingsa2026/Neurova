"""Neurova MCP server 面。

平台自身作为 MCP server 对外暴露能力：已发布工作流 + 技能聚合为
MCP tools。协议无关核心（list_tools/call_tool），传输层（stdio/SSE
server 核心与传输分离

复用既有契约，不另起炉灶：
- 工作流工具：workflow_as_tool.build_workflow_tool_schema（P1-3，
  DAG 输入校验天然生效——MCP 面不绕过必填校验）
- 技能工具：清单源与执行源**同一份**（agent 自带的注册表，skill:{name} 命名空间归一），
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


class McpCaller:
    """这一发的调用方是谁、能不能驱动这个 agent——**按请求传入**的凭据对。

    为什么是参数而不是 ContextVar 或单例字段：核心单例跨请求共享，把 per-request 的
    授权态挂在它上面就是把上一发的身份漏进下一发（同一族见 §6-163 与那条 cancel scope
    跨 task 的实测）。`mayDriveAgent` 由 API 层用**属主判定单源**算好交进来
    （`agent_access.can_access_agent`，chat 执行门同一口径），本核心不参与口径定义。
    """

    __slots__ = ("userId", "mayDriveAgent")

    def __init__(self, userId: str = "", mayDriveAgent: bool = False):
        self.userId = userId
        self.mayDriveAgent = mayDriveAgent


class NeurovaMCPServer:
    """协议无关 MCP server 核心。

    Args:
        storage: neurflow WorkflowStorage（工作流工具源；None=不暴露工作流）
        agent_ref / agent_provider: 执行侧的 agent。技能面的**清单源与执行源就是它
            自带的那一份注册表**（§6-334 的 B/C 之后是 §6-352 的乙）；无 agent ⇒ 技能面
            整条不 advertise 也不执行，不留半边。构造期不再有第二个 `skill_registry`
            入口——第二份池子就是那次双源的入口本身。
    """

    def __init__(self, storage=None, agent_ref=None, agent_provider=None):
        self._storage = storage
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

    def _skillPool(self):
        """技能面的唯一取池口——advertise 与执行都从这里取，两处不许各有来源。"""
        agent = self._resolve_agent()
        return getattr(agent, "_skill_registry", None) if agent is not None else None

    @staticmethod
    def _skillOpenTo(skill, caller) -> bool:
        """这条技能对**这一发的调用方**开不开——清单与执行读的就是这一个谓词。

        属主／admin（`caller.mayDriveAgent`）全开；其余只开**声明为只读**的技能
        （`skillIsReadOnlyFace`，声明面仍是 `permissions` 那一份，本面不另立名单）。
        `caller is None` ⇒ 按最窄那层走：无从判定就不给写侧能力，宁拒不错放。

        §6-352 那次的教训就在这条里：清单与执行必须读同一个谓词，否则又会分裂成
        「清单报了而调用被拒」与「清单没报而点名能跑」两个方向。
        """
        if caller is not None and caller.mayDriveAgent:
            return True
        from neurova.skills.permissions import skillIsReadOnlyFace

        return skillIsReadOnlyFace(skill)

    @staticmethod
    def _skillDeclaration(skill) -> Dict[str, Any]:
        """技能参数面的唯一取数口，与 LLM 工具面读的是同一个适配器。

        返回 `{"type","properties","required"}`；技能没声明时返回 {}——**此时本面不校参数**，
        因为在本面另列一张"哪些键算合法"的表就是第二个事实源（教义 第 6 条）。
        """
        if skill is None:
            return {}
        from neurova.skill_system.compat import OpenAISchemaAdapter

        try:
            return OpenAISchemaAdapter.skill_to_tool_schema(skill)["function"]["parameters"] or {}
        except Exception:  # noqa: BLE001 — 适配器坏掉时退成"不校"，不许退成"全拒"
            return {}

    def _gateSkillArguments(self, skill_name: str, skill, arguments: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """按**声明**校参数：未声明的键与缺失的必填都在进咽喉之前拒掉。

        这一格是被实测出来的（台账 §6-352 附问）：键名写错时本面原先不拒，调用静默落到
        该技能的缺省分支上——`{"action": "write"}` 打到 `file_operation` 上执行的是"读"。
        拒绝而不兜底，是把错误留在调用方那侧（教义 第 2 条的诚实形态）。
        """
        declared = self._skillDeclaration(skill)
        properties = declared.get("properties") or {}
        if not properties:
            return None
        unknown = sorted(set(arguments or {}) - set(properties))
        if unknown:
            return {
                "isError": True,
                "error": (
                    f"技能 {skill_name} 收到未声明的参数键 {unknown}；"
                    f"本面声明的可接受键={sorted(properties)}"
                ),
            }
        missing = sorted(k for k in (declared.get("required") or []) if k not in (arguments or {}))
        if missing:
            return {
                "isError": True,
                "error": f"技能 {skill_name} 缺必填参数 {missing}；声明位={sorted(properties)}",
            }
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

    def list_tools(self, caller=None) -> List[Dict[str, Any]]:
        """聚合能力清单（MCP tools 形态：name/description/inputSchema）。

        `caller` 决定技能面开到哪一层（见 `_skillOpenTo`）——清单与执行读同一谓词。"""
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

        pool = self._skillPool()
        if pool is not None:
            try:
                from neurova.skill_system.compat import unpack_skill

                for name, raw in (getattr(pool, "skills", {}) or {}).items():
                    skill = unpack_skill(raw)
                    if not self._skillOpenTo(skill, caller):
                        continue
                    tools.append({
                        "name": f"{_SKILL_PREFIX}{name}",
                        "description": getattr(skill, "description", "") or f"技能 {name}",
                        # 与咽喉那侧同一个适配器、同一次取数：报出去的参数面就是执行的参数面
                        "inputSchema": self._skillDeclaration(skill)
                        or {"type": "object", "properties": {}},
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

    async def call_tool(self, name: str, arguments: Optional[Dict[str, Any]] = None,
                        caller=None) -> Dict[str, Any]:
        """按命名空间分派调用，**出口只归一次形**（`_mcpEnvelope`）。

        分派与信封解耦是这一格的根修处：三条腿各有各的失败写法（工作流回
        `success=False` 业务体、技能咽喉回只带 `error` 的拒绝体、CUA 工具面回执行器
        原始 dict），若在每条腿里各转一次，第四条腿加进来时必然漏转——那正是
        §6-334 的 B 票登记的"同一失败两种信封"的成因。
        """
        arguments = arguments or {}
        try:
            return _mcpEnvelope(await self._dispatch(name, arguments, caller))
        except Exception as e:  # noqa: BLE001 — MCP 语义：错误也是响应
            logger.warning("MCP call_tool %s 失败: %s", name, e)
            return {"isError": True, "error": str(e)}

    async def _dispatch(self, name: str, arguments: Dict[str, Any], caller=None) -> Any:
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
            return await self._call_skill(name[len(_SKILL_PREFIX):], arguments, caller)

        if name.startswith("computer_") or name == _RUN_COMPUTER_TASK:
            return await self._call_computer(name, arguments)

        # 无前缀：按执行池里的技能名归一尝试（宽容匹配存量调用习惯）
        pool = self._skillPool()
        if pool is not None and name in (getattr(pool, "skills", {}) or {}):
            return await self._call_skill(name, arguments, caller)

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

    def _assembleTurnView(self, agent):
        """把这一发装成「有可见集的回合」——用的就是 chat 主链那**同一个构造口**。

        Wave H-W2 那道门的判据是"视图在场时，视图外执行体拒绝执行"；视图只由
        `neurova/agent/chat_pipeline.py` 的回合装配段挂过，MCP 的请求边界不经过它，
        所以本面此前接进咽喉也拿不到那层授权（台账 §6-352 的甲）。这里补的是**接线**，
        不新造第二套合并逻辑（教义 第 6 条）：身份键走 `resolve_user_key`，三库合并走
        `build_turn_view`，并把用户库/公共库的副本物化成可执行体——否则"看得见不能调"
        就是半装配（与 chat 主链同批动作）。

        **装配失败一律 fail-closed**（与 chat 主链的 fail-open 相反，这是有意的分叉）：
        那边是"装配失败不许拖垮对话"，这边这道视图**就是授权本身**，静默回退成无视图
        等于把刚补上的门再拆一次。拒执行是可算的代价，放行不是。
        """
        from neurova.core import turn_context
        from neurova.skills.skill_visibility import build_turn_view, resolve_user_key

        pool = self._skillPool()
        userKey = resolve_user_key(user_id=self._current_user_id())
        try:
            view = build_turn_view(
                str(getattr(getattr(agent, "config", None), "agent_id", "") or ""),
                userKey,
                registry_skills=dict(pool.skills) if pool is not None else None,
            )
        except Exception as e:  # noqa: BLE001 — 授权装配失败不许退成"没有授权"
            logger.warning("MCP 技能腿可见集装配失败，按 fail-closed 拒执行: %s", e)
            return None
        token = turn_context.set_turn_skill_view(view)
        if pool is not None:
            try:
                from neurova.skills.market_registry import restore_library_skills_for_turn

                restore_library_skills_for_turn(pool, view)
            except Exception:  # noqa: BLE001 — 物化失败不放大为整发失败，视图本身已成立
                logger.debug("MCP 技能腿库副本物化失败（视图仍在，越权面不受影响）", exc_info=True)
        return token

    async def _call_skill(self, skill_name: str, arguments: Dict[str, Any], caller=None) -> Dict[str, Any]:
        """技能腿一律走 `ToolExecutor.execute_skill_tool` 那道咽喉，无 agent 即拒。

        咽喉上挂着四件本面补不出的事：轮级可见门（Wave H-W2）、声明式权限作用域
        （P0-4）、沙箱根注入、P0-1 质量漏斗记账。直调 `skill.execute` 等于把这四件
        一起绕掉——所以这里没有"拿不到 agent 就退回直调"的兜底，只有 fail-closed。
        （可见门要视图在场才判得动，所以本腿在进咽喉之前先调 `_assembleTurnView`
        挂上本轮视图，出去再复位——装配走的是 chat 主链那同一个构造口。）

        沿革（台账 §6-352 的乙）：这里曾长期**两份池子并存**——清单读构造期注入的
        `get_skill_registry()` 全局单例，执行读 `agent._skill_registry`（由
        `create_default_skills()` 每 agent 现造）。实测到的后果是双向的：清单报了而咽喉判
        「不存在」，以及清单从未列出而点名**照样执行**（还连带把未知参数静默落到技能的缺省
        分支上）。现在两边的源都是执行池那一份，`__init__` 上第二个池子入口一并删掉。
        """
        agent = self._resolve_agent()
        if agent is None:
            return {
                "isError": True,
                "error": f"技能 {skill_name} 需要 agent 才能过治理咽喉（可见门/权限作用域/沙箱根/漏斗记账），当前无 agent",
            }

        from neurova.core import turn_context
        from neurova.tool_executor import ToolExecutor

        pool = self._skillPool()
        skill = pool.get_skill(skill_name) if pool is not None else None
        # 查无此技能名时**不做身份层判定**：那种场合的正确答案是"不存在"，由咽喉给，
        # 本层的话（"属写侧能力面"）会把调用方引向一个并不存在的技能上。
        if skill is not None and not self._skillOpenTo(skill, caller):
            return {
                "isError": True,
                "error": (
                    f"技能 {skill_name} 属写侧能力面，需该 agent 的属主或 admin 身份调用"
                    "（非属主只开放声明为只读的技能）"
                ),
            }
        gate = self._gateSkillArguments(skill_name, skill, arguments)
        if gate is not None:
            return gate

        token = self._assembleTurnView(agent)
        if token is None:
            return {
                "isError": True,
                "error": f"技能 {skill_name} 的轮级可见集未能装配，本面按 fail-closed 拒执行",
            }
        try:
            outcome = await ToolExecutor(agent).execute_skill_tool(skill_name, dict(arguments or {}), None)
        finally:
            turn_context.reset_turn_skill_view(token)
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
