"""记忆世代链读取（T1 supersedes 链读路径化）。

记忆双过程研究（arXiv:2606.09483）的 supersedes 双向链证明：隐式个性化查询大量依赖
"沿链恢复信念演化弧线"（其 LongMemEval 知识更新子集上，答对查询 78% 触碰
supersedes 指针，答错仅 31%）。本仓的取代语义此前**只写不读**——三处写点
各自落了指针，但 recall 排除 FORGOTTEN 行后，链永远沉在 metadata 审计里：

- S16 世代失效：旧行 ``metadata.memoryDiscipline = {status: "superseded",
  supersededBy, supersededAt, supersededBasis}``（memory_discipline.py）；
- 导入声明取代：旧行 ``metadata.superseded_by_ingest = <新行 id>``
  （manager._retireSuperseded）；
- 睡眠合并：产物行 ``metadata.merged_from = [源 id...]``（sleep_writeback）。

本模块是这三类指针的**唯一读取口**（教义第 6 条：不另立第四种取代语义，
也不在消费方各写一遍解析）。方向约定：边一律从旧代指向新代——

- ``superseded_by``：旧代 --被谁修订--> 新代（带 basis/at 依据）；
- ``merged_into``：源 --被合并进--> 产物。

读取是纯只读遍历：正向沿行自身指针、反向靠一次有界全量扫描建反向索引；
所有行都来自请求作用域（``get_all_memories(scoped=True)`` / ``get_memory``），
跨作用域指针（悬空/越权）不产出幽灵节点——fail-closed。
"""

from __future__ import annotations

from collections import deque
from typing import Any, Dict, List, Optional, Tuple

from neurova.core.logger import get_logger

logger = get_logger(__name__)

#: 链遍历深度上限（跳数；端点查询参 ge=1，模块侧再夹一遍）
LINEAGE_MAX_DEPTH = 5

#: 节点内容预览长度（链读面是审计视图，不整段吐原文）
LINEAGE_CONTENT_PREVIEW_CHARS = 200

#: 边关系闭集
REL_SUPERSEDED_BY = "superseded_by"  # 旧代 --被修订--> 新代
REL_MERGED_INTO = "merged_into"      # 源 --被合并进--> 产物


def _supersedeTargetOf(row: Dict[str, Any]) -> Optional[str]:
    """旧行自身携带的"被谁取代"指针（S16 与导入两个写点，取法单点）。"""
    meta = row.get("metadata") or {}
    disc = meta.get("memoryDiscipline")
    target = ""
    if isinstance(disc, dict):
        target = str(disc.get("supersededBy") or "")
    if not target:
        target = str(meta.get("superseded_by_ingest") or "")
    target = target.strip()
    return target or None


def _supersedeBasisOf(row: Dict[str, Any]) -> Tuple[str, str]:
    """旧行的修订依据与时刻（仅 S16 写点携带；导入取代无依据，如实为空）。"""
    meta = row.get("metadata") or {}
    disc = meta.get("memoryDiscipline")
    if isinstance(disc, dict):
        return (
            str(disc.get("supersededBasis") or ""),
            str(disc.get("supersededAt") or ""),
        )
    return "", ""


def _mergedSourcesOf(row: Dict[str, Any]) -> List[str]:
    """产物行合并吸收的源 id 列表（睡眠写回写点）。"""
    meta = row.get("metadata") or {}
    sources = meta.get("merged_from") or []
    if not isinstance(sources, (list, tuple)):
        return []
    out: List[str] = []
    for sid in sources:
        sid = str(sid or "").strip()
        if sid and sid not in out:
            out.append(sid)
    return out


def _preview(text: Any) -> str:
    content = str(text or "")
    if len(content) <= LINEAGE_CONTENT_PREVIEW_CHARS:
        return content
    return content[:LINEAGE_CONTENT_PREVIEW_CHARS] + "…"


def _nodeFromRow(row: Optional[Dict[str, Any]], rowId: str, isRoot: bool) -> Dict[str, Any]:
    """行 → 链节点（行缺席＝指针悬空，不产出节点，见 memoryLineage 主流程）。"""
    return {
        "id": rowId,
        "content": _preview((row or {}).get("content")),
        "lifecycle_stage": str((row or {}).get("lifecycle_stage") or ""),
        "created_at": str((row or {}).get("created_at") or ""),
        "is_root": isRoot,
    }


def memoryLineage(
    manager: Any,
    memory_id: str,
    *,
    max_depth: int = LINEAGE_MAX_DEPTH,
) -> Optional[Dict[str, Any]]:
    """从任一代出发读出完整世代链（双向 BFS，深度有界）。

    Args:
        manager: MemoryManager（作用域由请求上下文决定；跨作用域行读不到）。
        memory_id: 起点记忆 id（可为链上任意一代，不要求活跃）。
        max_depth: 跳数上限（>=1；1＝只看相邻一代）。

    Returns:
        ``{"root_id", "max_depth", "nodes", "edges"}``；起点不存在/越权
        （get_memory 视同不存在）返回 None。边方向一律旧代 → 新代。

    纯只读：不写行、不改温度（行数据来自 get_all_memories 快照，
    不走 get_memory 的 touch 语义）。
    """
    if manager is None or not memory_id:
        return None
    hops = max(1, int(max_depth))
    root = manager.get_memory(str(memory_id))
    if not isinstance(root, dict) or not root.get("id"):
        return None
    root_id = str(root["id"])

    # 一次有界全量扫描（请求作用域内，含 FORGOTTEN——链上旧代多已退役），
    # 同时建出正向/反向邻接：newerOf[旧] = [边]、olderOf[新] = [边]。
    byId: Dict[str, Dict[str, Any]] = {}
    newerOf: Dict[str, List[Tuple[str, str, str, str]]] = {}
    olderOf: Dict[str, List[Tuple[str, str, str, str]]] = {}
    for row in manager.get_all_memories(scoped=True) or []:
        if not isinstance(row, dict):
            continue
        rowId = str(row.get("id") or "")
        if not rowId:
            continue
        byId[rowId] = row
        target = _supersedeTargetOf(row)
        if target and target != rowId:
            basis, at = _supersedeBasisOf(row)
            newerOf.setdefault(rowId, []).append((target, REL_SUPERSEDED_BY, basis, at))
            olderOf.setdefault(target, []).append((rowId, REL_SUPERSEDED_BY, basis, at))
        for sid in _mergedSourcesOf(row):
            newerOf.setdefault(sid, []).append((rowId, REL_MERGED_INTO, "", ""))
            olderOf.setdefault(rowId, []).append((sid, REL_MERGED_INTO, "", ""))

    nodes: Dict[str, Dict[str, Any]] = {
        root_id: _nodeFromRow(byId.get(root_id), root_id, isRoot=True)
    }
    edges: List[Dict[str, Any]] = []
    seenEdges: set = set()
    visited = {root_id}
    queue: deque = deque([(root_id, 0)])
    while queue:
        rowId, depth = queue.popleft()
        if depth >= hops:
            continue
        # 出边（我是旧代，指向新代）+ 入边（我是新代，来自旧代）——同一条边
        # 从两端各看一次时用 seenEdges 去重。
        halfEdges: List[Tuple[str, str, str, str, str]] = []
        for target, relation, basis, at in newerOf.get(rowId, []):
            halfEdges.append((rowId, target, relation, basis, at))
        for older, relation, basis, at in olderOf.get(rowId, []):
            halfEdges.append((older, rowId, relation, basis, at))
        for src, dst, relation, basis, at in halfEdges:
            # 悬空/越权指针：目标不在本作用域快照里 → 不产幽灵节点与半截边
            if src not in byId or dst not in byId:
                continue
            key = (src, dst, relation)
            if key in seenEdges:
                continue
            seenEdges.add(key)
            edges.append(
                {
                    "from": src,
                    "to": dst,
                    "relation": relation,
                    "basis": basis,
                    "at": at,
                }
            )
            for neighbor in (src, dst):
                if neighbor not in visited:
                    visited.add(neighbor)
                    nodes[neighbor] = _nodeFromRow(
                        byId.get(neighbor), neighbor, isRoot=False
                    )
                    queue.append((neighbor, depth + 1))

    logger.debug(
        "世代链读取: root=%s nodes=%s edges=%s hops<=%s", root_id, len(nodes), len(edges), hops
    )
    return {
        "root_id": root_id,
        "max_depth": hops,
        "nodes": list(nodes.values()),
        "edges": edges,
    }
