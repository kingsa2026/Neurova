"""
知识条目 → 图谱节点自动抽取（批次 3 / RAG 演进 B2）

打通 KnowledgeRepository → KnowledgeGraphManager 的写入链路：
LLM 从条目标题+正文抽取实体与关系，建立图谱节点/边，
并把节点 id 回写 KnowledgeItem.graph_node_ids。

设计要点：
- llm_call(prompt) -> str 可注入（测试零网络/零 LLM）；None 表示未配置，跳过
- 类型对齐 manager 的 NodeType/RelationType 枚举，越界一律落 custom
- 按 (label, type) 去重：search_nodes 精确匹配既有节点，命中即复用
- 任何异常不向上传播（导入链路的钩子调用，失败不阻断导入）
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable, Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

_PROMPT_TEMPLATE = """从下面的知识条目中抽取实体与关系，输出严格的 JSON（不要解释）：
{{"entities": [{{"label": "...", "type": "concept|entity|event|memory|skill|tool|person|location|time|custom"}}], "relations": [{{"source": "实体标签", "target": "实体标签", "type": "is_a|has_a|part_of|related_to|causes|similar_to|opposite_of|temporal|spatial|causal|depends_on|used_by|contains|custom"}}]}}
约束：type 必须从给定枚举中选；实体 2-6 个；关系基于实体标签。

标题：{title}
正文：{content}"""

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.S)


def _parse_llm_json(text: str) -> Optional[Dict[str, Any]]:
    """解析 LLM 输出中的 JSON 对象（容忍 markdown 代码围栏）。"""
    if not text:
        return None
    match = _FENCE_RE.search(text)
    raw = match.group(1) if match else text
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        data = json.loads(raw[start : end + 1])
    except Exception:  # noqa: BLE001 - LLM 输出不可信
        return None
    return data if isinstance(data, dict) else None


def _find_existing_node(graph, label: str, node_type):
    """按 (label, type) 精确查找既有节点；命中则复用（去重）。"""
    try:
        for node in graph.search_nodes(label, node_type=node_type, limit=20):
            if node.label == label and node.node_type == node_type:
                return node
    except Exception:  # noqa: BLE001
        pass
    return None


def extract_knowledge_to_graph(
    item: Dict[str, Any],
    repo: Any = None,
    llm_call: Optional[Callable[[str], str]] = None,
    graph_manager: Any = None,
) -> List[str]:
    """抽取一条知识条目的实体/关系写入图谱，返回回写后的 graph_node_ids。

    Args:
        item: 知识条目 dict（含 knowledge_id/title/content）
        repo: KnowledgeRepository（回写 graph_node_ids；None 则跳过回写）
        llm_call: prompt -> 文本 的调用器；None/异常/畸形输出 → 跳过（返回 []）
        graph_manager: KnowledgeGraphManager；None 时用全局单例

    Returns:
        条目关联的图谱节点 id 列表（失败为 []）
    """
    if llm_call is None:
        logger.info("graph_bridge: 未配置 LLM 调用器，跳过图谱抽取")
        return []

    title = str(item.get("title", ""))
    content = str(item.get("content", ""))
    if not (title or content):
        return []

    try:
        raw = llm_call(_PROMPT_TEMPLATE.format(title=title, content=content[:4000]))
        data = _parse_llm_json(raw)
    except Exception as exc:  # noqa: BLE001 - LLM 不可用不阻断调用方
        logger.warning("graph_bridge: LLM 抽取失败: %s", exc)
        return []
    if not data:
        logger.warning("graph_bridge: LLM 输出无法解析为 JSON，跳过")
        return []

    if graph_manager is None:
        from neurova.cognitive_layers.knowledge_graph.manager import (
            get_knowledge_graph_manager,
        )

        graph_manager = get_knowledge_graph_manager()

    from neurova.cognitive_layers.knowledge_graph.manager import (
        NodeType,
        RelationType,
    )

    def _norm_type(value, enum_cls, default):
        try:
            return enum_cls(str(value))
        except Exception:  # noqa: BLE001 - 越界类型落 custom
            return default

    # 建实体节点（label+type 去重）
    node_ids: List[str] = []
    label_to_id: Dict[str, str] = {}
    for ent in data.get("entities") or []:
        if not isinstance(ent, dict):
            continue
        label = str(ent.get("label", "")).strip()
        if not label:
            continue
        node_type = _norm_type(ent.get("type"), NodeType, NodeType.CUSTOM)
        existing = _find_existing_node(graph_manager, label, node_type)
        if existing is not None:
            node_ids.append(existing.node_id)
            label_to_id.setdefault(label, existing.node_id)
            continue
        try:
            node = graph_manager.add_node(
                label=label,
                node_type=node_type,
                properties={"description": content[:200], "source_knowledge_id": str(item.get("knowledge_id", ""))},
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("graph_bridge: 建节点失败 %s: %s", label, exc)
            continue
        node_ids.append(node.node_id)
        label_to_id[label] = node.node_id

    # 建关系边
    for rel in data.get("relations") or []:
        if not isinstance(rel, dict):
            continue
        source_id = label_to_id.get(str(rel.get("source", "")).strip())
        target_id = label_to_id.get(str(rel.get("target", "")).strip())
        if not source_id or not target_id or source_id == target_id:
            continue
        relation = _norm_type(rel.get("type"), RelationType, RelationType.CUSTOM)
        try:
            graph_manager.add_edge(
                source_id=source_id, target_id=target_id, relation_type=relation
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("graph_bridge: 建边失败 %s->%s: %s", source_id, target_id, exc)

    # 回写条目（经 find_item 跨组定位，不依赖 item dict 携带 agent_id）
    if node_ids and repo is not None:
        try:
            found = repo.find_item(str(item.get("knowledge_id", "")))
            if found is not None:
                agent_id, _current = found
                repo.update_knowledge(
                    agent_id,
                    str(item.get("knowledge_id", "")),
                    {"graph_node_ids": node_ids},
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("graph_bridge: graph_node_ids 回写失败: %s", exc)

    return node_ids
