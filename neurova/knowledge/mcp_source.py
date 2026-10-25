"""MCP 信息源（B 方案）：外部 MCP server 作为知识库信息源。

Neurova 作为 MCP **客户端**连外部 server（streamable-http + 可选 Bearer），
调用指定工具取文本，经 `create_knowledge` 入库——A1 去重、A0 租户、
source_type=mcp 溯源全链生效。配置落 `knowledge_mcp_sources` 表（v26）。

分层：
- `McpSourceStore`：配置存取（token 单条 get 才回、列表脱敏）；
- `fetchViaSession`：纯会话操作（call_tool → 文本拼装），与传输解耦可单测；
- `openSourceSession`：HTTP 传输薄壳（async contextmanager）；
- `pullFromSource`：拉取 → 入库（失败诚实上抛，不静默吞）；
- `probeTools`：列远端 server 的工具清单（登记前选 tool_name 用）。
"""

from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)


def _now() -> str:
    import datetime

    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class McpSourceStore:
    """`knowledge_mcp_sources` 的唯一读写面。"""

    def __init__(self, store: Any) -> None:
        self._store = store

    def register(self, spec: Dict[str, Any], created_by: str = "") -> Dict[str, Any]:
        sourceId = "mcp_%s" % uuid.uuid4().hex[:12]
        stamp = _now()
        with self._store._lock, self._store._conn:
            self._store._conn.execute(
                "INSERT INTO knowledge_mcp_sources (source_id, name, endpoint, auth_token,"
                " tool_name, tool_args, agent_id, tenant_id, created_by, created_at,"
                " updated_at, last_pull_at, last_status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (sourceId, str(spec.get("name") or ""), str(spec.get("endpoint") or ""),
                 str(spec.get("auth_token") or ""), str(spec.get("tool_name") or ""),
                 json.dumps(spec.get("tool_args") or {}, ensure_ascii=False),
                 str(spec.get("agent_id") or "default"), str(spec.get("tenant_id") or "default"),
                 str(created_by or ""), stamp, stamp, None, "never"))
        return self.get(sourceId) or {}

    def list(self) -> List[Dict[str, Any]]:
        with self._store._lock:
            rows = self._store._conn.execute(
                "SELECT * FROM knowledge_mcp_sources ORDER BY created_at").fetchall()
        return [self._redact(dict(r)) for r in rows]

    def get(self, sourceId: str) -> Optional[Dict[str, Any]]:
        with self._store._lock:
            row = self._store._conn.execute(
                "SELECT * FROM knowledge_mcp_sources WHERE source_id = ?", (sourceId,)).fetchone()
        if row is None:
            return None
        return self._withArgs(dict(row))

    def update(self, sourceId: str, spec: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        existing = self.get(sourceId)
        if existing is None:
            return None
        with self._store._lock, self._store._conn:
            self._store._conn.execute(
                "UPDATE knowledge_mcp_sources SET name=?, endpoint=?, auth_token=?,"
                " tool_name=?, tool_args=?, agent_id=?, tenant_id=?, updated_at=?"
                " WHERE source_id=?",
                (str(spec.get("name") or existing["name"]),
                 str(spec.get("endpoint") or existing["endpoint"]),
                 str(spec.get("auth_token") or existing["auth_token"]),
                 str(spec.get("tool_name") or existing["tool_name"]),
                 json.dumps(spec.get("tool_args") if spec.get("tool_args") is not None
                            else json.loads(existing["tool_args"]), ensure_ascii=False),
                 str(spec.get("agent_id") or existing["agent_id"]),
                 str(spec.get("tenant_id") or existing["tenant_id"]),
                 _now(), sourceId))
        return self.get(sourceId)

    def delete(self, sourceId: str) -> None:
        with self._store._lock, self._store._conn:
            self._store._conn.execute(
                "DELETE FROM knowledge_mcp_sources WHERE source_id = ?", (sourceId,))

    def markPulled(self, sourceId: str, status: str) -> None:
        with self._store._lock, self._store._conn:
            self._store._conn.execute(
                "UPDATE knowledge_mcp_sources SET last_pull_at=?, last_status=? WHERE source_id=?",
                (_now(), status, sourceId))

    @staticmethod
    def _withArgs(row: Dict[str, Any]) -> Dict[str, Any]:
        d = dict(row)
        d["tool_args"] = json.loads(d.get("tool_args") or "{}")
        return d

    @staticmethod
    def _redact(row: Dict[str, Any]) -> Dict[str, Any]:
        d = McpSourceStore._withArgs(row)
        d["auth_token"] = ""
        return d


async def fetchViaSession(session: Any, toolName: str, toolArgs: Dict[str, Any]) -> str:
    """会话内调用工具并拼装文本（与传输解耦：内存流/HTTP 同一入口）。"""
    result = await session.call_tool(toolName, toolArgs or {})
    parts: List[str] = []
    for block in getattr(result, "content", None) or []:
        text = getattr(block, "text", None)
        if text:
            parts.append(str(text))
    return "\n".join(parts)


@asynccontextmanager
async def openSourceSession(source: Dict[str, Any]):
    """HTTP 传输薄壳：streamable-http + Bearer 鉴权头 + ClientSession（已 initialize）。"""
    import httpx
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    endpoint = str(source.get("endpoint") or "")
    token = str(source.get("auth_token") or "")
    headers = {"Authorization": "Bearer %s" % token} if token else {}
    async with httpx.AsyncClient(headers=headers, timeout=30) as http:
        async with streamable_http_client(endpoint, http_client=http) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                yield session


async def probeTools(source: Dict[str, Any]) -> List[Dict[str, Any]]:
    """列远端 server 的工具清单（登记/编辑时选 tool_name）。"""
    async with openSourceSession(source) as session:
        listing = await session.list_tools()
    return [
        {"name": t.name, "description": getattr(t, "description", "") or ""}
        for t in (getattr(listing, "tools", None) or [])
    ]


async def pullFromSource(store: McpSourceStore, source: Dict[str, Any],
                         repo: Any, *, fetcher=None, sessionOpener=None) -> Dict[str, Any]:
    """拉取 → 入库。失败诚实上抛（调用方转 4xx/5xx），不静默吞。

    fetcher/sessionOpener：API 面显式注入本模块的名字引用——patch API 命名
    空间才能打穿；缺省用本模块实现。"""
    fetchFn = fetcher or fetchViaSession
    opener = sessionOpener or openSourceSession
    try:
        async with opener(source) as session:
            text = await fetchFn(
                session, str(source.get("tool_name") or ""), source.get("tool_args") or {})
    except Exception:
        store.markPulled(str(source.get("source_id")), "failed")
        raise
    if not text.strip():
        store.markPulled(str(source.get("source_id")), "empty")
        raise ValueError("MCP 工具返回空内容：%s" % source.get("tool_name"))

    name = str(source.get("name") or "mcp-source")
    title = text.strip().splitlines()[0][:60] or name
    item = repo.create_knowledge(
        str(source.get("agent_id") or "default"),
        title,
        text,
        source=f"mcp:{name}",
        source_type="mcp",
        author="mcp",
        owner_user_id=str(source.get("created_by") or "default"),
        tenant_id=str(source.get("tenant_id") or "default"),
        visibility="private",
        dedupe=True,
    )
    store.markPulled(str(source.get("source_id")), "ok")
    return {
        "knowledge_id": item.get("knowledge_id"),
        "duplicate": bool(item.get("duplicate")),
        "chars": len(text),
    }
