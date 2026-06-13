"""缺失推理器 - 检测"应该存在但没有"的记忆

对应 MEEM 基准测试中的 Absence (Abs) 任务。
检测三层缺失: 实体缺失、关系缺失、上下文依赖缺失。
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class AbsenceResult:
    """缺失检测结果"""
    is_absent: bool
    entity_exists: bool
    relation_exists: bool
    context_has_dependency: bool
    confidence: float
    explanation: List[str]
    suggestions: List[str] = field(default_factory=list)


class AbsenceReasoner:
    """
    缺失推理器

    三层检测:
        1. 实体是否存在
        2. 期望的关系是否存在
        3. 上下文中是否有指向目标的依赖

    置信度计算:
        is_absent = not (entity_exists and relation_exists and context_has_dependency)
        confidence = 0.3 + missing_count * 0.2 (上限 0.9)
    """

    def __init__(self, dependency_graph: Any):
        self.graph = dependency_graph

    def detect_absence(
        self,
        expected_entity: str,
        expected_relation: Any,
        context_entities: List[str],
    ) -> AbsenceResult:
        """
        检测缺失

        Args:
            expected_entity: 期望存在的实体
            expected_relation: 期望存在的关系类型
            context_entities: 上下文中的实体列表

        Returns:
            AbsenceResult 包含缺失检测结果和建议
        """
        explanation: List[str] = []
        suggestions: List[str] = []

        # 检查 1: 实体是否存在
        entity_exists = expected_entity in self.graph.entities
        if not entity_exists:
            explanation.append(f"实体 '{expected_entity}' 不存在于依赖图谱中")
            suggestions.append(f"需要添加实体 '{expected_entity}'")

        # 检查 2: 期望的关系是否存在
        relation_exists = False
        if entity_exists:
            for edge in self.graph.adjacency.get(expected_entity, []):
                if edge.dep_type == expected_relation:
                    relation_exists = True
                    break

            if not relation_exists:
                explanation.append(
                    f"实体 '{expected_entity}' 没有 {expected_relation.value} 类型的关系"
                )
                suggestions.append(
                    f"需要为 '{expected_entity}' 添加 {expected_relation.value} 关系"
                )

        # 检查 3: 上下文是否有依赖（双向检测）
        context_has_dependency = False
        for ctx_entity in context_entities:
            # 方向 1: context → expected (上下文指向目标)
            for edge in self.graph.adjacency.get(ctx_entity, []):
                if edge.target_id == expected_entity:
                    context_has_dependency = True
                    break
            # 方向 2: expected → context (目标指向上文上下文)
            if not context_has_dependency:
                for edge in self.graph.adjacency.get(expected_entity, []):
                    if edge.target_id == ctx_entity:
                        context_has_dependency = True
                        break
            if context_has_dependency:
                break

        if not context_has_dependency and context_entities:
            explanation.append(
                f"上下文实体中没有指向 '{expected_entity}' 的依赖"
            )
            suggestions.append("需要建立上下文实体与目标实体的关联")

        # 综合判断
        is_absent = not (entity_exists and relation_exists and context_has_dependency)

        if is_absent:
            missing_count = sum([
                not entity_exists,
                not relation_exists,
                not context_has_dependency,
            ])
            confidence = min(0.9, 0.3 + missing_count * 0.2)
        else:
            confidence = 0.1

        return AbsenceResult(
            is_absent=is_absent,
            entity_exists=entity_exists,
            relation_exists=relation_exists,
            context_has_dependency=context_has_dependency,
            confidence=confidence,
            explanation=explanation,
            suggestions=suggestions,
        )

    def detect_batch(
        self,
        expected_entities: List[str],
        expected_relation: Any,
        context_entities: List[str],
    ) -> List[AbsenceResult]:
        """批量缺失检测"""
        results = []
        for entity in expected_entities:
            results.append(self.detect_absence(
                expected_entity=entity,
                expected_relation=expected_relation,
                context_entities=context_entities,
            ))
        return results
