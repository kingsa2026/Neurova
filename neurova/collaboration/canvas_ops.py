"""
Canvas Op 层 — Agent 交互式操作画布的唯一写入口（Phase 1）

设计（见 docs 方案讨论）：
1. 语义操作而非像素操作：create / add_node / connect / set_config /
   move_node / remove_node / remove_edge / layout 等 op。agent 工具
   （tool_executor 的 canvas_* 工具）与 HTTP 端点（collaboration_api
   的 /canvas/{id}/ops）共用本层，用户手动保存与 agent 编辑走同一套
   版本语义，天然一致。
2. 乐观锁（实时抢占）：画布记录带单调递增 version；op 可携带
   base_version，落后即抛 CanvasVersionConflict —— 用户随时可以抢占
   编辑，agent 的过期 op 被拒绝后重读重试，而不是静默覆盖。
3. 事件直播：每个成功 op 经 broadcaster 推送 {canvas_id, op, version,
   data, actor}；生产默认走 SessionSyncManager 的 canvas_op 事件，
   画布页订阅后增量应用，用户看着 agent 一步步搭工作流。

深模块约束（AGENTS.md）：
- 通过注入的 CanvasStore 访问持久化，不反向依赖 API 层
- broadcaster 为 async callable(session_id, payload) 协议，可测试替换
- 单例生命周期：get_canvas_op_service() / reset_canvas_op_service()
"""

from __future__ import annotations

import difflib
import threading
import uuid
from typing import Any, Awaitable, Callable, Dict, List, Optional

from neurova.core.logger import get_logger

from .canvas_store import CanvasStore, CanvasVersionConflict, get_canvas_store

logger = get_logger(__name__)

# broadcaster 协议：async (session_id, payload) -> None
Broadcaster = Callable[[str, Dict[str, Any]], Awaitable[None]]

# 自动布局参数（与前端节点卡片尺寸匹配：宽 ~240、高 ~120）
_LAYOUT_X_GAP = 300
_LAYOUT_Y_GAP = 180
_LAYOUT_ORIGIN_X = 80
_LAYOUT_ORIGIN_Y = 100
_ADD_NODE_X_STEP = 300


class CanvasOpError(ValueError):
    """画布 op 业务错误，携带机器可读 code 供 agent/前端分支处理。"""

    def __init__(self, message: str, code: str = "canvas_error"):
        super().__init__(message)
        self.code = code


def compute_layout(
    nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]]
) -> Dict[str, Dict[str, float]]:
    """拓扑分层自动布局（纯函数）：返回 {node_id: {"x", "y"}}。

    最长路径分层（Kahn）：入度为 0 的节点在第 0 层，
    下游节点层号 = max(上游层号)+1；同层按原节点顺序纵向排布。
    环上的节点无法拓扑到达，兜底放到最右层之后，不挂死。
    """
    node_ids = [str(n.get("id", "")) for n in nodes if n.get("id")]
    if not node_ids:
        return {}

    successors: Dict[str, List[str]] = {nid: [] for nid in node_ids}
    in_degree: Dict[str, int] = {nid: 0 for nid in node_ids}
    for e in edges or []:
        src = e.get("source")
        tgt = e.get("target")
        src_id = str(src.get("nodeId", "")) if isinstance(src, dict) else str(src or "")
        tgt_id = str(tgt.get("nodeId", "")) if isinstance(tgt, dict) else str(tgt or "")
        if src_id in in_degree and tgt_id in in_degree and src_id != tgt_id:
            successors[src_id].append(tgt_id)
            in_degree[tgt_id] += 1

    depth: Dict[str, int] = {}
    queue = [nid for nid in node_ids if in_degree[nid] == 0]
    for nid in queue:
        depth[nid] = 0
    head = 0
    while head < len(queue):
        cur = queue[head]
        head += 1
        for nxt in successors[cur]:
            candidate = depth[cur] + 1
            if nxt not in depth or candidate > depth[nxt]:
                depth[nxt] = candidate
            in_degree[nxt] -= 1
            if in_degree[nxt] == 0:
                queue.append(nxt)

    # 环上未到达的节点：兜底放到最深层之后
    max_depth = max(depth.values(), default=-1)
    for nid in node_ids:
        if nid not in depth:
            max_depth += 1
            depth[nid] = max_depth

    # 同层按节点原顺序纵向排布
    layer_index: Dict[str, int] = {}
    positions: Dict[str, Dict[str, float]] = {}
    for nid in node_ids:
        d = depth[nid]
        idx = layer_index.get(str(d), 0)
        layer_index[str(d)] = idx + 1
        positions[nid] = {
            "x": _LAYOUT_ORIGIN_X + d * _LAYOUT_X_GAP,
            "y": _LAYOUT_ORIGIN_Y + idx * _LAYOUT_Y_GAP,
        }
    return positions


def _port_ref(port: Any) -> Dict[str, str]:
    """NodePort 对象或 dict → 画布端口引用 {"id", "label"}（兼容两种形态）"""
    if isinstance(port, dict):
        pid = str(port.get("id", ""))
        return {"id": pid, "label": str(port.get("label") or pid)}
    pid = str(getattr(port, "id", "") or "")
    return {"id": pid, "label": str(getattr(port, "label", "") or pid)}


def _edge_endpoint(edge: Dict[str, Any], key: str) -> str:
    """边端点取 nodeId（兼容 {nodeId, portId} dict 与纯字符串）"""
    ref = edge.get(key)
    if isinstance(ref, dict):
        return str(ref.get("nodeId", ""))
    return str(ref or "")


class CanvasOpService:
    """画布语义操作服务（async；broadcaster 可注入以便测试）"""

    def __init__(
        self,
        store: Optional[CanvasStore] = None,
        broadcaster: Optional[Broadcaster] = None,
    ):
        self._store = store or get_canvas_store()
        # broadcaster 显式传入 None 时用默认 SessionSyncManager 广播
        self._broadcaster: Broadcaster = broadcaster if broadcaster is not None else _default_broadcast

    # ── 内部工具 ────────────────────────────────────────────────

    def _registry(self):
        from .neurflow.node_registry import get_node_registry

        registry = get_node_registry()
        registry.ensure_builtin()
        return registry

    def _get_definition(self, node_type: str):
        """按类型取节点定义；未注册时抛错并给出模糊候选（供 agent 纠错）"""
        registry = self._registry()
        definition = registry.get(node_type)
        if definition is not None:
            return definition

        known = [d.type for d in registry.list_all()]
        candidates = difflib.get_close_matches(node_type, known, n=5, cutoff=0.6)
        hint = f"，相近节点: {', '.join(candidates)}" if candidates else ""
        raise CanvasOpError(
            f"未注册的节点类型: {node_type}{hint}（可用 canvas_list_nodes 查询节点库）",
            code="unknown_node_type",
        )

    async def _broadcast(
        self,
        session_id: Optional[str],
        op: str,
        canvas_id: str,
        version: int,
        data: Dict[str, Any],
        actor: str,
    ) -> None:
        """广播 op 事件；失败只告警不影响 op 结果（存储已落盘为准）"""
        if not session_id:
            return
        payload = {
            "canvas_id": canvas_id,
            "op": op,
            "version": version,
            "actor": actor,
            "data": data,
        }
        try:
            await self._broadcaster(session_id, payload)
        except Exception as e:  # noqa: BLE001 - 广播失败不回滚已落盘的 op
            logger.warning("画布 op 事件广播失败 (%s %s): %s", op, canvas_id, e)

    @staticmethod
    def _require_record(record: Optional[Dict[str, Any]], canvas_id: str) -> Dict[str, Any]:
        if record is None:
            raise CanvasOpError(f"画布不存在: {canvas_id}", code="not_found")
        return record

    @staticmethod
    def _auto_position(nodes: List[Dict[str, Any]]) -> Dict[str, float]:
        """新节点自动落位：最右列再往右一格，与最右节点同行"""
        if not nodes:
            return {"x": _LAYOUT_ORIGIN_X + 40, "y": _LAYOUT_ORIGIN_Y + 20}
        max_x = max(float((n.get("position") or {}).get("x", 0)) for n in nodes)
        rightmost_y = [
            float((n.get("position") or {}).get("y", 0))
            for n in nodes
            if float((n.get("position") or {}).get("x", 0)) == max_x
        ]
        return {"x": max_x + _ADD_NODE_X_STEP, "y": rightmost_y[0] if rightmost_y else _LAYOUT_ORIGIN_Y}

    # ── 查询 ────────────────────────────────────────────────────

    async def read_canvas(self, canvas_id: str) -> Dict[str, Any]:
        """读取画布快照（含 version）——agent 冲突重读用"""
        record = self._store.get(canvas_id)
        return self._require_record(record, canvas_id)

    async def list_nodes(
        self,
        *,
        query: Optional[str] = None,
        category: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """查询节点库（agent 按需找节点；找不到时触发自主建节点决策）"""
        registry = self._registry()
        if query:
            # 注册表 search 只匹配 label/description/tags，补上 type 子串匹配
            hits = {d.type: d for d in registry.search(query)}
            ql = query.lower()
            for d in registry.list_all():
                if ql in d.type.lower() or ql in d.label.lower():
                    hits[d.type] = d
            definitions = list(hits.values())
        else:
            definitions = registry.list_all()

        if category:
            definitions = [d for d in definitions if d.category == category]

        return [
            {
                "type": d.type,
                "label": d.label,
                "icon": d.icon,
                "category": d.category,
                "description": d.description,
                "source": d.source,
            }
            for d in definitions[: max(1, int(limit))]
        ]

    # ── 变更 op（每个 = 校验 → 原子 mutate → 广播） ─────────────

    async def create_canvas(
        self,
        *,
        name: str,
        description: str = "",
        project_id: Optional[str] = None,
        session_id: Optional[str] = None,
        actor: str = "agent",
    ) -> Dict[str, Any]:
        snapshot: Dict[str, Any] = {
            "name": name,
            "description": description,
            "nodes": [],
            "edges": [],
        }
        if project_id:
            snapshot["project_id"] = project_id
        record = self._store.create(snapshot)
        await self._broadcast(
            session_id, "create", record["id"], int(record.get("version", 1)),
            {"name": name, "description": description}, actor,
        )
        return record

    async def add_node(
        self,
        canvas_id: str,
        *,
        node_type: str,
        config: Optional[Dict[str, Any]] = None,
        position: Optional[Dict[str, float]] = None,
        label: Optional[str] = None,
        base_version: Optional[int] = None,
        session_id: Optional[str] = None,
        actor: str = "agent",
    ) -> Dict[str, Any]:
        definition = self._get_definition(node_type)
        inputs = [_port_ref(p) for p in definition.inputs]
        outputs = [_port_ref(p) for p in definition.outputs]
        # sub_block 默认值作为初始 config（表单字段有默认选中项）
        default_config: Dict[str, Any] = {}
        for sb in definition.sub_blocks or []:
            sb_id = sb.get("id") if isinstance(sb, dict) else getattr(sb, "id", None)
            sb_default = sb.get("default_value") if isinstance(sb, dict) else getattr(sb, "default_value", None)
            if sb_id and sb_default is not None:
                default_config[sb_id] = sb_default

        holder: Dict[str, Any] = {}

        def _mut(record: Dict[str, Any]) -> Dict[str, Any]:
            node = {
                "id": f"node_{uuid.uuid4().hex[:8]}",
                "type": node_type,
                "label": label or definition.label,
                "icon": definition.icon or "📦",
                "position": dict(position) if position else self._auto_position(record.get("nodes", [])),
                "inputs": inputs,
                "outputs": outputs,
                "config": {**default_config, **(config or {})},
            }
            record.setdefault("nodes", []).append(node)
            holder["node"] = node
            return record

        record = self._store.mutate(canvas_id, _mut, base_version=base_version)
        self._require_record(record, canvas_id)
        node = holder["node"]
        await self._broadcast(
            session_id, "add_node", canvas_id, int(record["version"]),
            {"node": node}, actor,
        )
        return node

    async def connect(
        self,
        canvas_id: str,
        *,
        source_node: str,
        target_node: str,
        source_port: Optional[str] = None,
        target_port: Optional[str] = None,
        base_version: Optional[int] = None,
        session_id: Optional[str] = None,
        actor: str = "agent",
    ) -> Dict[str, Any]:
        holder: Dict[str, Any] = {}

        def _mut(record: Dict[str, Any]) -> Dict[str, Any]:
            nodes = record.get("nodes", [])
            by_id = {str(n.get("id", "")): n for n in nodes}
            if source_node not in by_id:
                raise CanvasOpError(f"连线源节点不存在: {source_node}", code="unknown_node")
            if target_node not in by_id:
                raise CanvasOpError(f"连线目标节点不存在: {target_node}", code="unknown_node")

            # 端口校验（节点快照带端口列表时才校验，兼容旧数据）
            src_outputs = [p.get("id") for p in by_id[source_node].get("outputs", []) or []]
            tgt_inputs = [p.get("id") for p in by_id[target_node].get("inputs", []) or []]
            if source_port and src_outputs and source_port not in src_outputs:
                raise CanvasOpError(
                    f"节点 {source_node} 没有输出端口: {source_port}（可用: {', '.join(src_outputs)}）",
                    code="unknown_port",
                )
            if target_port and tgt_inputs and target_port not in tgt_inputs:
                raise CanvasOpError(
                    f"节点 {target_node} 没有输入端口: {target_port}（可用: {', '.join(tgt_inputs)}）",
                    code="unknown_port",
                )

            # 重复连线校验（端点四元组相同即重复）
            def _sig(e: Dict[str, Any]) -> tuple:
                s = e.get("source") or {}
                t = e.get("target") or {}
                return (
                    s.get("nodeId") if isinstance(s, dict) else s,
                    (s.get("portId") if isinstance(s, dict) else None) or None,
                    t.get("nodeId") if isinstance(t, dict) else t,
                    (t.get("portId") if isinstance(t, dict) else None) or None,
                )

            new_sig = (source_node, source_port, target_node, target_port)
            for e in record.get("edges", []):
                if _sig(e) == new_sig:
                    raise CanvasOpError(
                        f"重复连线: {source_node} → {target_node}", code="duplicate_edge"
                    )

            edge = {
                "id": f"edge_{uuid.uuid4().hex[:8]}",
                "source": {"nodeId": source_node, "portId": source_port},
                "target": {"nodeId": target_node, "portId": target_port},
            }
            record.setdefault("edges", []).append(edge)
            holder["edge"] = edge
            return record

        record = self._store.mutate(canvas_id, _mut, base_version=base_version)
        self._require_record(record, canvas_id)
        edge = holder["edge"]
        await self._broadcast(
            session_id, "connect", canvas_id, int(record["version"]),
            {"edge": edge}, actor,
        )
        return edge

    async def set_config(
        self,
        canvas_id: str,
        node_id: str,
        values: Dict[str, Any],
        *,
        base_version: Optional[int] = None,
        session_id: Optional[str] = None,
        actor: str = "agent",
    ) -> Dict[str, Any]:
        holder: Dict[str, Any] = {}

        def _mut(record: Dict[str, Any]) -> Dict[str, Any]:
            for n in record.get("nodes", []):
                if n.get("id") == node_id:
                    merged = {**(n.get("config") or {}), **(values or {})}
                    n["config"] = merged
                    holder["node"] = n
                    return record
            raise CanvasOpError(f"节点不存在: {node_id}", code="unknown_node")

        record = self._store.mutate(canvas_id, _mut, base_version=base_version)
        self._require_record(record, canvas_id)
        node = holder["node"]
        await self._broadcast(
            session_id, "set_config", canvas_id, int(record["version"]),
            {"node_id": node_id, "config": node["config"]}, actor,
        )
        return node

    async def move_node(
        self,
        canvas_id: str,
        node_id: str,
        x: float,
        y: float,
        *,
        base_version: Optional[int] = None,
        session_id: Optional[str] = None,
        actor: str = "agent",
    ) -> Dict[str, Any]:
        holder: Dict[str, Any] = {}

        def _mut(record: Dict[str, Any]) -> Dict[str, Any]:
            for n in record.get("nodes", []):
                if n.get("id") == node_id:
                    n["position"] = {"x": float(x), "y": float(y)}
                    holder["node"] = n
                    return record
            raise CanvasOpError(f"节点不存在: {node_id}", code="unknown_node")

        record = self._store.mutate(canvas_id, _mut, base_version=base_version)
        self._require_record(record, canvas_id)
        node = holder["node"]
        await self._broadcast(
            session_id, "move_node", canvas_id, int(record["version"]),
            {"node_id": node_id, "position": node["position"]}, actor,
        )
        return node

    async def remove_node(
        self,
        canvas_id: str,
        node_id: str,
        *,
        base_version: Optional[int] = None,
        session_id: Optional[str] = None,
        actor: str = "agent",
    ) -> Dict[str, Any]:
        holder: Dict[str, Any] = {}

        def _mut(record: Dict[str, Any]) -> Dict[str, Any]:
            nodes = record.get("nodes", [])
            if not any(n.get("id") == node_id for n in nodes):
                raise CanvasOpError(f"节点不存在: {node_id}", code="unknown_node")
            record["nodes"] = [n for n in nodes if n.get("id") != node_id]
            edges = record.get("edges", [])
            kept = [
                e for e in edges
                if _edge_endpoint(e, "source") != node_id and _edge_endpoint(e, "target") != node_id
            ]
            record["edges"] = kept
            holder["removed_edges"] = len(edges) - len(kept)
            return record

        record = self._store.mutate(canvas_id, _mut, base_version=base_version)
        self._require_record(record, canvas_id)
        result = {"node_id": node_id, "removed_edges": holder["removed_edges"]}
        await self._broadcast(
            session_id, "remove_node", canvas_id, int(record["version"]), result, actor
        )
        return result

    async def remove_edge(
        self,
        canvas_id: str,
        edge_id: str,
        *,
        base_version: Optional[int] = None,
        session_id: Optional[str] = None,
        actor: str = "agent",
    ) -> Dict[str, Any]:
        def _mut(record: Dict[str, Any]) -> Dict[str, Any]:
            edges = record.get("edges", [])
            kept = [e for e in edges if e.get("id") != edge_id]
            if len(kept) == len(edges):
                raise CanvasOpError(f"连线不存在: {edge_id}", code="unknown_edge")
            record["edges"] = kept
            return record

        record = self._store.mutate(canvas_id, _mut, base_version=base_version)
        self._require_record(record, canvas_id)
        result = {"edge_id": edge_id}
        await self._broadcast(
            session_id, "remove_edge", canvas_id, int(record["version"]), result, actor
        )
        return result

    async def apply_layout(
        self,
        canvas_id: str,
        *,
        base_version: Optional[int] = None,
        session_id: Optional[str] = None,
        actor: str = "agent",
    ) -> Dict[str, Dict[str, float]]:
        holder: Dict[str, Any] = {}

        def _mut(record: Dict[str, Any]) -> Dict[str, Any]:
            positions = compute_layout(record.get("nodes", []), record.get("edges", []))
            for n in record.get("nodes", []):
                pos = positions.get(str(n.get("id", "")))
                if pos:
                    n["position"] = dict(pos)
            holder["positions"] = positions
            return record

        record = self._store.mutate(canvas_id, _mut, base_version=base_version)
        self._require_record(record, canvas_id)
        positions = holder["positions"]
        await self._broadcast(
            session_id, "layout", canvas_id, int(record["version"]),
            {"positions": positions}, actor,
        )
        return positions


# ── 默认 broadcaster：SessionSyncManager 的 canvas_op 事件 ──────


async def _default_broadcast(session_id: str, payload: Dict[str, Any]) -> None:
    from neurova.sync.session_sync_manager import (
        EventType,
        SessionEvent,
        get_session_sync_manager,
    )

    event = SessionEvent(event_type=EventType.CANVAS_OP, payload=payload)
    await get_session_sync_manager().broadcast_event(session_id, event)


# ── 单例生命周期 ────────────────────────────────────────────────

_service_instance: Optional[CanvasOpService] = None
_service_lock = threading.RLock()


def get_canvas_op_service() -> CanvasOpService:
    global _service_instance
    if _service_instance is None:
        with _service_lock:
            if _service_instance is None:
                _service_instance = CanvasOpService()
    return _service_instance


def reset_canvas_op_service() -> None:
    global _service_instance
    with _service_lock:
        _service_instance = None


__all__ = [
    "CanvasOpError",
    "CanvasOpService",
    "CanvasVersionConflict",
    "compute_layout",
    "get_canvas_op_service",
    "reset_canvas_op_service",
]
