# -*- coding: utf-8 -*-
"""外部编码代理只读 MCP 工具面（ACP 编码代理团队接入 P2 卡 C2，2026-11-19；
P2-2 车道D 增只读问数，2026-11-21）。

把本仓只读能力以 MCP tools 开放给 Claude Code / OpenCode 等外部编码代理
（外部代理以 MCP client 身份调用，即"反向 MCP"）。只读四件套：

- team_list：当前凭据可见团队——**转交 teams 单源** `teams_api.list_teams`
  （与 GET /v1/teams 同一租户过滤口径，本壳不复制租户比较式）；
- knowledge_search：知识检索——转交知识仓库单源
  `KnowledgeRepository.search_visible_items`（租户/可见性/部门白名单过滤
  全在单源内完成）；
- memory_search：记忆检索——转交运行 agent 注册表里各 agent 的
  NeurovaRecallEngine.recall_flat（与 /v1/enhanced-memory-search 同一取数链），
  逐 agent 过平台唯一属主门 `can_access_agent`（admin 全量 / 属主本人 / 其余拒）；
- data_query：企业数据只读问数（P2-2 车道D）——转交 nl2sql 可复用入口
  `runReadonlyDataQuestion`（目录 grounding → 生成 → 只读校验 → 连接器
  只读执行），数据源按发起者租户段过滤，总闸 `NEUROVA_NL2SQL_ENABLED`
  关闭时结构化拒绝。

**只读红线**：本面不注册任何写工具；四件工具全零副作用（列表/检索/读数），
并以 ToolAnnotations(readOnlyHint=True) 向客户端声明。
**鉴权**：照 mcp_ontology_server.py M0 先例——X-Service-Token / X-API-Key /
Bearer JWT 任一成立；全不成立 fail-closed 401。身份解析直接复用该模块的
同一份实现（双鉴权不造第二份，教义第 6/7 条）。
**输出有界**：结果条数、单文本字段、整体 JSON 体三层截断（截断必留痕），
防外部代理拉走超大载荷。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.types import ToolAnnotations
from starlette.responses import JSONResponse

from neurova.core.identity_context import set_request_user_id
from neurova.core.logger import get_logger
from neurova.mcp_ontology_server import _currentUserFromContext, _resolveIdentity

logger = get_logger(__name__)

_MCP_INSTRUCTIONS = (
    "Neurova 面向外部编码代理的只读工具面：查团队名册（team_list）、"
    "检索知识库（knowledge_search）、检索记忆（memory_search）、"
    "企业数据只读问数（data_query）。"
    "全部工具只读无副作用；数据范围按调用凭据的租户/属主隔离。"
)

_SERVER = MCPServer(name="neurova-agent-tools", instructions=_MCP_INSTRUCTIONS,
                    version="1.0.0")

# 输出有界三层：单文本字段 / 单工具结果条数 / 整体 JSON 体。超限一律留痕
# （truncated 标记或截断后缀），不静默丢字。
MAX_TEXT_CHARS = 2000
MAX_RESULTS_PER_TOOL = 20
MAX_QUERY_CHARS = 8000
_MAX_PAYLOAD_CHARS = 200_000

_READ_ONLY = ToolAnnotations(readOnlyHint=True)


# ── 输出有界 helpers ─────────────────────────────────────────────────────────

def _clipText(value: Any, limit: int = MAX_TEXT_CHARS) -> str:
    text = "" if value is None else str(value)
    if len(text) <= limit:
        return text
    return text[:limit] + "…[已截断，原文 %d 字符]" % len(text)


def _clipTexts(obj: Any) -> Any:
    """递归裁剪所有字符串字段（结构不变，超长字段留截断后缀）。"""
    if isinstance(obj, str):
        return _clipText(obj)
    if isinstance(obj, dict):
        return {k: _clipTexts(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clipTexts(v) for v in obj]
    return obj


def _boundedPayload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """整体 JSON 体兜底上限：超限逐条丢弃行集直至入界并置 truncated。"""
    try:
        text = json.dumps(payload, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return {"truncated": True, "detail": "结果含不可序列化对象，已整体降级",
                "count": payload.get("count")}
    if len(text) <= _MAX_PAYLOAD_CHARS:
        return payload
    trimmed = dict(payload)
    for key in ("teams", "results", "rows"):
        rows = trimmed.get(key)
        if isinstance(rows, list) and rows:
            while len(rows) > 1 and len(
                    json.dumps(trimmed, ensure_ascii=False, default=str)) > _MAX_PAYLOAD_CHARS:
                rows.pop()
            trimmed["truncated"] = True
            break
    return trimmed


def _clampLimit(value: Any) -> int:
    try:
        limit = int(value)
    except (TypeError, ValueError):
        return 10
    return max(1, min(limit, MAX_RESULTS_PER_TOOL))


def _queryRejection(query: Any) -> Optional[Dict[str, Any]]:
    """查询词入参校验：空/超长一律结构化拒绝（诚实错误，不静默降级）。"""
    raw = "" if query is None else str(query)
    if not raw.strip():
        return {"rejected": True, "detail": "query 不能为空"}
    if len(raw) > MAX_QUERY_CHARS:
        return {"rejected": True,
                "detail": "query 过长（%d 字符，上限 %d）" % (len(raw), MAX_QUERY_CHARS)}
    return None


# ── team_list（只读）─────────────────────────────────────────────────────────

@_SERVER.tool(
    name="team_list",
    description="列出当前凭据可见的固定团队（只读；按调用身份租户过滤，"
                "与 GET /v1/teams 同一单源口径）。",
    annotations=_READ_ONLY,
)
async def teamList(ctx: Context, limit: int = MAX_RESULTS_PER_TOOL) -> dict:
    from neurova.api.endpoints.teams_api import list_teams

    user = _currentUserFromContext(ctx)
    # 转交 teams 单源端点函数：租户过滤口径与 REST 面逐字同一份（不新写比较式）。
    teams = await list_teams(current_user=user)
    rows = [_clipTexts(t.model_dump()) for t in teams][:_clampLimit(limit)]
    return _boundedPayload({
        "tenant_id": str(user.get("tenant_id") or "default"),
        "teams": rows,
        "count": len(rows),
    })


# ── knowledge_search（只读）──────────────────────────────────────────────────

def _knowledgeView(item: Dict[str, Any]) -> Dict[str, Any]:
    """条目 → 有界投影：不带 revisions/chunks 等大件，检索明细只留 chunk_hits。"""
    keys = ("knowledge_id", "title", "content", "category", "tags", "source",
            "confidence", "created_at", "updated_at", "visibility",
            "owner_user_id", "tenant_id", "lifecycle_status", "chunk_hits")
    view = {k: item.get(k) for k in keys if k in item}
    view["chunk_count"] = len(item.get("chunks") or [])
    return view


@_SERVER.tool(
    name="knowledge_search",
    description="在当前凭据可见范围内检索知识库（只读；标题/内容/分片相关性"
                "检索，租户与可见性过滤走知识仓库单源）。",
    annotations=_READ_ONLY,
)
async def knowledgeSearch(ctx: Context, query: str, limit: int = 10,
                          category: str = "", agent_id: str = "") -> dict:
    from neurova.knowledge.repository import get_knowledge_repository

    rejection = _queryRejection(query)
    if rejection is not None:
        return rejection
    user = _currentUserFromContext(ctx)
    needle = str(query).strip()
    items = get_knowledge_repository().search_visible_items(
        user, needle, limit=_clampLimit(limit),
        category=str(category or "").strip() or None,
        agent_id=str(agent_id or "").strip() or None)
    rows = [_clipTexts(_knowledgeView(dict(item))) for item in items]
    return _boundedPayload({"query": needle, "results": rows, "count": len(rows)})


# ── memory_search（只读）─────────────────────────────────────────────────────

@_SERVER.tool(
    name="memory_search",
    description="检索当前凭据可见 agent 的记忆（只读；多通道融合召回 "
                "recall_flat 单源，逐 agent 过属主门，他人 agent 记忆不可见）。",
    annotations=_READ_ONLY,
)
async def memorySearch(ctx: Context, query: str, limit: int = 10,
                       agent_id: str = "") -> dict:
    from neurova.api.agent_access import can_access_agent, resolve_agent_owner
    from neurova.api.endpoints import get_app_state

    rejection = _queryRejection(query)
    if rejection is not None:
        return rejection
    user = _currentUserFromContext(ctx)
    userId = str(user.get("user_id") or "")
    role = str(user.get("role") or "user")
    wanted = str(agent_id or "").strip()
    needle = str(query).strip()
    agents = (get_app_state() or {}).get("agents") or {}
    limit = _clampLimit(limit)

    results: List[Dict[str, Any]] = []
    engineErrors: List[str] = []
    enginesQueried = 0
    for aid, agent in list(agents.items()):
        if wanted and aid != wanted:
            continue
        # 平台唯一属主门（admin 全量 / 属主本人 / 其余拒）——不另写第二份判定。
        if not can_access_agent(userId, role, resolve_agent_owner(aid, state_agent=agent)):
            continue
        engine = getattr(getattr(agent, "memory_agent", None), "recall_engine", None)
        if engine is None:
            continue
        enginesQueried += 1
        try:
            recalled = engine.recall_flat(query=needle, limit=limit)
        except Exception as exc:  # noqa: BLE001 - 单引擎故障不拖垮其余 agent，如实留痕
            engineErrors.append("%s: %s" % (aid, exc))
            continue
        for rm in recalled or []:
            row = rm.to_dict() if hasattr(rm, "to_dict") else dict(rm)
            row["agent_id"] = aid
            results.append(_clipTexts(row))

    payload: Dict[str, Any] = {
        "query": needle,
        "results": results[:limit],
        "count": min(len(results), limit),
        "engines_queried": enginesQueried,
    }
    if engineErrors:
        payload["engine_errors"] = engineErrors
    if wanted and enginesQueried == 0 and not engineErrors:
        payload["detail"] = "未查询到可见召回引擎（agent 未注册、无记忆面或不可见）"
    return _boundedPayload(payload)


# ── data_query（只读，P2-2 车道D）────────────────────────────────────────────

@_SERVER.tool(
    name="data_query",
    description="企业数据只读问数（NL2SQL）：自然语言 → 只读 SELECT → 本凭据租户"
                "可见的企业数据源执行。只读无副作用；写意图（INSERT/UPDATE/DELETE/"
                "DROP 等）被连接器只读断言拒绝；总闸 NEUROVA_NL2SQL_ENABLED 关闭时"
                "结构化拒绝（capability_disabled）；数据源按调用凭据租户隔离，"
                "他租户源不可见。",
    annotations=_READ_ONLY,
)
async def dataQuery(ctx: Context, question: str, source_id: str = "",
                    max_rows: int = 50) -> dict:
    from neurova.api.endpoints.knowledge_common import resolveAgentLlmClients
    from neurova.api.endpoints.knowledge_nl2sql import (
        llmCallFromClients,
        runReadonlyDataQuestion,
    )

    rejection = _queryRejection(question)
    if rejection is not None:
        return rejection
    user = _currentUserFromContext(ctx)
    tenant = str(user.get("tenant_id") or "default")
    # LLM 候选 = 运行时 agent 注册表（与 REST 面同一解析单源）；生成走本仓
    # 管线，usage 由既有 cost 链自动记账。
    llmCall = llmCallFromClients(resolveAgentLlmClients(None))
    try:
        maxRows = int(max_rows)
    except (TypeError, ValueError):
        maxRows = 50
    maxRows = max(1, min(maxRows, 200))

    result = await asyncio.to_thread(
        runReadonlyDataQuestion, tenant, str(source_id or "").strip(),
        str(question).strip(), llmCall, str(user.get("username") or ""), maxRows)

    status = str(result.get("status") or "")
    if status == "capability_disabled":
        return {"rejected": True, "code": "capability_disabled",
                "detail": str(result.get("error") or "NL2SQL 能力未开启")}
    if status == "source_not_found":
        return {"rejected": True, "code": "source_not_found",
                "detail": str(result.get("error") or "企业源不可见或未提交")}

    # 输出三层截断纪律与既有三工具同款：行数钳位 + 单字段裁剪 + 整体兜底。
    rows = result.get("rows") or []
    limit = _clampLimit(maxRows)
    shown = rows[:limit]
    payload: Dict[str, Any] = {
        "question": str(question).strip(),
        "source_id": result.get("source_id") or "",
        "status": status,
        "answerable": result.get("answerable"),
        "sql": result.get("sql") or "",
        "explanation": result.get("explanation") or "",
        "rows": [_clipTexts(dict(row)) if isinstance(row, dict) else _clipText(row)
                 for row in shown],
        "row_count": len(rows),
        "count": len(shown),
        "truncated": bool(result.get("truncated")) or len(rows) > len(shown),
    }
    if status == "refused":
        payload["reason"] = str(result.get("reason") or "")
    if result.get("error"):
        payload["error"] = str(result.get("error"))
    return _boundedPayload(payload)


# ── ASGI 挂载 ────────────────────────────────────────────────────────────────

def build_agent_tools_mcp_asgi():
    """构造外部代理只读工具 MCP 面的裸 ASGI app（双鉴权 + 每请求独立运输）。

    运输采用 `mcp_server_api._McpFaceAsgi` 的同构接法：StreamableHTTPSessionManager
    **每请求新建**（stateless + json_response，一发请求一条运输，进出同一任务）。
    不采用"app 级 lifespan 常驻 task group"的形态——`create_app()` 是缓存单例，会被
    多个 TestClient portal 反复进出，而 anyio cancel scope 的进出必须同任务，app 级
    常驻在第二轮启停即炸（mcp_server_api 模块注释有完整实测记录）；本面若照
    mcp_ontology_server 的 lifespan 驱动形态挂第二个常驻面，实测会把宿主 app 的
    关停链炸成 CancelledError（tests/unit/api/test_mcp_session_shutdown_wiring.py）。

    鉴权fail-closed：X-Service-Token / X-API-Key / Bearer JWT 任一成立；全不成立 401。
    身份经 scope.state 传给 tool handler，并在请求边界写一次身份通道（§3）。
    """
    lowlevel = _SERVER._lowlevel_server

    async def asgi_entry(scope, receive, send):
        if scope["type"] != "http":
            return
        if scope.get("method") not in ("POST", "DELETE"):
            # 与 mcp_server_api 同一款动词闸：stateless + json_response 下 GET 会
            # 开一条不结束的流（挂起面从无到有就是新缺陷），必须显式 405。
            resp = JSONResponse(
                {"jsonrpc": "2.0", "id": None,
                 "error": {"code": -32600, "message": "Method Not Allowed"}},
                status_code=405)
            await resp(scope, receive, send)
            return
        user = await _resolveIdentity(scope)
        if user is None:
            resp = JSONResponse({"detail": "MCP 端点需要服务令牌、API key 或 JWT"},
                                status_code=401)
            await resp(scope, receive, send)
            return
        set_request_user_id(user.get("user_id") or None)
        scope.setdefault("state", {})["neurova_user"] = user
        manager = StreamableHTTPSessionManager(app=lowlevel, stateless=True,
                                               json_response=True)
        async with manager.run():
            await manager.handle_request(scope, receive, send)

    return asgi_entry


def create_agent_tools_mcp_server() -> MCPServer:
    """测试/工具面获取 server 实例（工具注册态同一份）。"""
    return _SERVER
