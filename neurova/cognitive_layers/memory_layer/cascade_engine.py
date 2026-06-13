"""级联推理引擎 - 实现 A→B→C 链式推理

基于依赖图谱实现正向/反向级联推理:
- 正向级联: A变化 → 影响B → 影响C
- 反向级联: C变化 ← 受B影响 ← 受A影响

对应 MEEM 基准测试中的 Cascade (Cas) 任务。
"""

import logging
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class CascadeDirection(Enum):
    """级联方向"""
    FORWARD = "forward"   # 正向: A→B→C
    BACKWARD = "backward"  # 反向: A←B←C


@dataclass
class CascadeEffect:
    """级联影响"""
    entity_id: str
    effect_type: str       # "direct" | "indirect"
    confidence: float
    path: List[str]
    evidence: List[str] = field(default_factory=list)


@dataclass
class CascadeResult:
    """级联推理结果"""
    source_entity: str
    direction: CascadeDirection
    effects: List[CascadeEffect]
    total_affected: int
    confidence: float
    reasoning_chain: List[str]


class CascadeEngine:
    """
    级联推理引擎

    核心算法:
        forward_cascade: BFS 正向遍历，追踪变化传播链
        backward_cascade: BFS 反向遍历，追溯影响源
        would_affect: 判断 source 变化是否影响 target

    置信度衰减:
        confidence = 1.0 / (1.0 + depth * decay)
        depth=1 → 0.83, depth=2 → 0.71, depth=3 → 0.63
    """

    def __init__(self, dependency_graph: Any):
        self.graph = dependency_graph
        self._confidence_decay: float = 0.2

    def forward_cascade(
        self, changed_entity: str, max_depth: int = 5
    ) -> CascadeResult:
        """
        正向级联: A变化 → 影响哪些实体

        Args:
            changed_entity: 变化的实体 ID
            max_depth: 最大级联深度

        Returns:
            CascadeResult 包含所有受影响实体及置信度
        """
        if changed_entity not in self.graph.entities:
            return CascadeResult(
                source_entity=changed_entity,
                direction=CascadeDirection.FORWARD,
                effects=[], total_affected=0, confidence=0.0,
                reasoning_chain=[f"实体 '{changed_entity}' 不存在"],
            )

        effects: List[CascadeEffect] = []
        visited: set = {changed_entity}
        queue: deque = deque([(changed_entity, 0, [changed_entity])])
        reasoning_chain: List[str] = [f"正向级联: {changed_entity} 变化"]

        while queue:
            current_id, depth, path = queue.popleft()
            if depth > max_depth:
                continue

            if depth > 0:
                confidence = 1.0 / (1.0 + depth * self._confidence_decay)
                effect_type = "direct" if depth == 1 else "indirect"
                effects.append(CascadeEffect(
                    entity_id=current_id,
                    effect_type=effect_type,
                    confidence=confidence,
                    path=path.copy(),
                ))

                entity = self.graph.entities.get(current_id)
                entity_name = entity.name if entity else current_id
                reasoning_chain.append(
                    f"  {'→' * depth} {entity_name} "
                    f"({effect_type}, 置信度={confidence:.2f})"
                )

            for edge in self.graph.adjacency.get(current_id, []):
                if edge.target_id not in visited:
                    visited.add(edge.target_id)
                    queue.append((edge.target_id, depth + 1, path + [edge.target_id]))

        total_confidence = (
            sum(e.confidence for e in effects) / len(effects) if effects else 0.0
        )
        reasoning_chain.append(
            f"总计影响 {len(effects)} 个实体，平均置信度 {total_confidence:.2f}"
        )

        return CascadeResult(
            source_entity=changed_entity,
            direction=CascadeDirection.FORWARD,
            effects=effects,
            total_affected=len(effects),
            confidence=total_confidence,
            reasoning_chain=reasoning_chain,
        )

    def backward_cascade(
        self, target_entity: str, max_depth: int = 5
    ) -> CascadeResult:
        """
        反向级联: B变化 ← 受哪些实体影响

        Args:
            target_entity: 目标实体 ID
            max_depth: 最大追溯深度

        Returns:
            CascadeResult 包含所有影响源及置信度
        """
        if target_entity not in self.graph.entities:
            return CascadeResult(
                source_entity=target_entity,
                direction=CascadeDirection.BACKWARD,
                effects=[], total_affected=0, confidence=0.0,
                reasoning_chain=[f"实体 '{target_entity}' 不存在"],
            )

        effects: List[CascadeEffect] = []
        visited: set = {target_entity}
        queue: deque = deque([(target_entity, 0, [target_entity])])
        reasoning_chain: List[str] = [f"反向级联: {target_entity} ← 受影响源"]

        while queue:
            current_id, depth, path = queue.popleft()
            if depth > max_depth:
                continue

            if depth > 0:
                confidence = 1.0 / (1.0 + depth * self._confidence_decay)
                effect_type = "direct" if depth == 1 else "indirect"
                effects.append(CascadeEffect(
                    entity_id=current_id,
                    effect_type=effect_type,
                    confidence=confidence,
                    path=list(reversed(path)),
                ))

                entity = self.graph.entities.get(current_id)
                entity_name = entity.name if entity else current_id
                reasoning_chain.append(
                    f"  {'←' * depth} {entity_name} "
                    f"({effect_type}, 置信度={confidence:.2f})"
                )

            for edge in self.graph.reverse_adjacency.get(current_id, []):
                if edge.source_id not in visited:
                    visited.add(edge.source_id)
                    queue.append(
                        (edge.source_id, depth + 1, [edge.source_id] + path)
                    )

        total_confidence = (
            sum(e.confidence for e in effects) / len(effects) if effects else 0.0
        )
        reasoning_chain.append(
            f"总计 {len(effects)} 个影响源，平均置信度 {total_confidence:.2f}"
        )

        return CascadeResult(
            source_entity=target_entity,
            direction=CascadeDirection.BACKWARD,
            effects=effects,
            total_affected=len(effects),
            confidence=total_confidence,
            reasoning_chain=reasoning_chain,
        )

    def would_affect(
        self, source_id: str, target_id: str, threshold: float = 0.5
    ) -> Dict[str, Any]:
        """
        判断 source 变化是否会影响 target

        Returns:
            {"would_affect": bool, "confidence": float, "paths": list}
        """
        paths = self.graph.find_cascade_paths(source_id, target_id)
        if not paths:
            return {"would_affect": False, "confidence": 0.0, "paths": []}

        min_confidence = min(
            1.0 / (1.0 + (len(p) - 1) * self._confidence_decay)
            for p in paths
        )

        return {
            "would_affect": min_confidence >= threshold,
            "confidence": min_confidence,
            "paths": paths,
        }
