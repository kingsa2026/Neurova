"""基于 MOE 架构的无 LLM 依赖关系提取器

运行时成本: $0（纯规则 + 向量相似度，无 LLM 调用）
利用 Neurova 已有的 MOE 向量门控网络进行语义路由。
"""

from neurova.core.logger import get_logger
import re
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = get_logger(__name__)


# ────── Entity Extractor ──────


class EntityExtractor:
    """
    规则 + 正则 实体提取器

    提取类型: date, time, number, url, person, event, concept, object, task
    """

    PATTERNS = {
        "date": r"\d{4}[-/]\d{1,2}[-/]\d{1,2}",
        "time": r"\d{1,2}:\d{2}(:\d{2})?",
        "number": r"\b\d+(\.\d+)?\b",
        "url": r"https?://\S+",
    }

    ENTITY_KEYWORDS = {
        "person": ["张三", "李四", "Alice", "Bob", "用户", "开发者", "工程师", "管理员"],
        "event": ["会议", "部署", "发布", "上线", "测试", "调试", "回顾", "评审"],
        "concept": ["架构", "设计", "模式", "策略", "算法", "协议", "标准", "规范"],
        "object": ["数据库", "服务器", "API", "接口", "模块", "组件", "容器", "集群",
                    "缓存", "队列", "消息", "日志", "监控"],
        "task": ["任务", "需求", "功能", "优化", "修复", "重构", "迁移", "升级",
                 "安装", "配置", "备份", "恢复"],
    }

    def extract(self, text: str) -> List[Dict[str, Any]]:
        """从文本中提取实体"""
        entities: List[Dict[str, Any]] = []
        seen: set = set()

        # 正则提取 (date, time, number, url)
        for entity_type, pattern in self.PATTERNS.items():
            for match in re.finditer(pattern, text):
                name = match.group()
                if name not in seen and len(name) > 1:
                    seen.add(name)
                    entities.append({
                        "id": f"{entity_type}_{hash(name) % 100000}",
                        "name": name,
                        "type": entity_type,
                        "confidence": 0.9,
                        "start": match.start(),
                        "end": match.end(),
                    })

        # 关键词提取 (person, event, concept, object, task)
        text_lower = text.lower()
        for entity_type, keywords in self.ENTITY_KEYWORDS.items():
            for keyword in keywords:
                if keyword.lower() in text_lower and keyword not in seen:
                    seen.add(keyword)
                    idx = text_lower.find(keyword.lower())
                    entities.append({
                        "id": f"{entity_type}_{hash(keyword) % 100000}",
                        "name": keyword,
                        "type": entity_type,
                        "confidence": 0.8,
                        "start": idx,
                        "end": idx + len(keyword),
                    })

        return entities


# ────── Relation Classifier ──────


class RelationClassifier:
    """
    基于关键词的依赖关系分类器

    分类策略:
        1. 因果关键词 → CAUSAL
        2. 时序关键词或位置关系 → TEMPORAL
        3. 条件关键词 → CONDITIONAL
        4. 前置关键词 → PREREQUISITE
        5. 向量相似度高 → SUPPORT
        6. 默认 → HIERARCHICAL
    """

    CAUSAL_KEYWORDS = ["因为", "所以", "导致", "引起", "造成", "使得",
                       "causes", "leads to", "results in"]
    TEMPORAL_KEYWORDS = ["之前", "之后", "然后", "接着", "随后", "先", "后",
                         "before", "after", "then", "next"]
    CONDITIONAL_KEYWORDS = ["如果", "假如", "当", "只要", "除非", "假如",
                            "if", "when", "unless", "provided"]
    PREREQUISITE_KEYWORDS = ["前提", "基础", "需要", "必须", "依赖",
                             "prerequisite", "requires", "depends"]

    def classify(
        self,
        entity1: Dict[str, Any],
        entity2: Dict[str, Any],
        context: str,
        similarity: float = 0.0,
    ) -> Tuple[Any, float]:
        """
        分类两个实体之间的关系类型

        Returns:
            (DependencyType, confidence)
        """
        # 延迟导入避免循环依赖
        from .dependency_graph import DependencyType

        ctx = context.lower()

        # 1. 因果
        if any(kw in ctx for kw in self.CAUSAL_KEYWORDS):
            return DependencyType.CAUSAL, 0.8

        # 2. 条件（优先于时序位置判断）
        if any(kw in ctx for kw in self.CONDITIONAL_KEYWORDS):
            return DependencyType.CONDITIONAL, 0.7

        # 3. 前置条件
        if any(kw in ctx for kw in self.PREREQUISITE_KEYWORDS):
            return DependencyType.PREREQUISITE, 0.7

        # 4. 时序（显式时序关键词优先，位置判断作为兜底）
        if any(kw in ctx for kw in self.TEMPORAL_KEYWORDS):
            return DependencyType.TEMPORAL, 0.7
        if entity1.get("end", 0) < entity2.get("start", 0):
            return DependencyType.TEMPORAL, 0.6

        # 5. 向量相似度高 → 支持关系
        if similarity > 0.7:
            return DependencyType.SUPPORT, similarity

        # 6. 默认层次关系
        return DependencyType.HIERARCHICAL, 0.5


# ────── Extracted Dependency ──────


@dataclass
class ExtractedDependency:
    """提取的依赖关系"""
    source_entity: Dict[str, Any]
    target_entity: Dict[str, Any]
    dep_type: Any  # DependencyType
    confidence: float
    evidence_text: str = ""


# ────── MOE Extractor ──────


class MOEDependencyExtractor:
    """
    MOE 依赖提取器

    流程:
        1. EntityExtractor 提取实体
        2. 关系分类器对实体对分类
        3. 构建 DependencyGraph

    运行时成本: $0（纯规则 + Jaccard 相似度）
    """

    def __init__(
        self,
        vector_gating_network: Any = None,
        expert_retriever: Any = None,
        dependency_graph: Any = None,
    ):
        """
        初始化 MOE 依赖提取器
        
        Args:
            vector_gating_network: 向量门控网络（可选）
            expert_retriever: 专家检索器（可选）
            dependency_graph: 共享的依赖图谱实例（可选，不传则创建新实例）
        """
        self.entity_extractor = EntityExtractor()
        self.relation_classifier = RelationClassifier()
        self.vector_gating = vector_gating_network
        self.expert_retriever = expert_retriever
        self._dependency_graph = dependency_graph
        logger.info("MOEDependencyExtractor 初始化完成")

    async def extract_from_memory(
        self,
        memory_id: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> List[ExtractedDependency]:
        """
        从记忆内容中提取依赖关系

        Args:
            memory_id: 记忆 ID
            content: 记忆文本内容
            metadata: 额外元数据

        Returns:
            提取到的依赖关系列表
        """
        entities = self.entity_extractor.extract(content)
        if len(entities) < 2:
            return []

        dependencies: List[ExtractedDependency] = []

        for i, entity1 in enumerate(entities):
            for entity2 in entities[i + 1:]:
                similarity = self._compute_similarity(entity1["name"], entity2["name"])
                dep_type, confidence = self.relation_classifier.classify(
                    entity1, entity2, content, similarity,
                )
                if confidence >= 0.5:
                    dependencies.append(ExtractedDependency(
                        source_entity=entity1,
                        target_entity=entity2,
                        dep_type=dep_type,
                        confidence=confidence,
                        evidence_text=content[:200],
                    ))

        # 构建图谱
        self._build_graph(memory_id, entities, dependencies)

        logger.debug("从记忆 %s 提取到 %d 个实体, %d 个依赖",
                     memory_id, len(entities), len(dependencies))
        return dependencies

    def _compute_similarity(self, text1: str, text2: str) -> float:
        """Jaccard 相似度（纯本地计算，$0）"""
        if not text1 or not text2:
            return 0.0

        set1 = set(text1.lower().split())
        set2 = set(text2.lower().split())
        intersection = len(set1 & set2)
        union = len(set1 | set2)
        return intersection / union if union > 0 else 0.0

    def _build_graph(
        self,
        memory_id: str,
        entities: List[Dict[str, Any]],
        dependencies: List[ExtractedDependency],
    ) -> None:
        """将提取结果写入依赖图谱"""
        from .dependency_graph import DependencyGraph, DependencyEdge, EntityNode

        # 使用共享图谱实例或创建新实例
        graph = self._dependency_graph if self._dependency_graph is not None else DependencyGraph()

        for entity in entities:
            node = EntityNode(
                id=entity["id"],
                name=entity["name"],
                entity_type=entity["type"],
                metadata={"memory_id": memory_id},
            )
            graph.add_entity(node)

        for dep in dependencies:
            edge = DependencyEdge(
                id=str(uuid.uuid4())[:16],
                source_id=dep.source_entity["id"],
                target_id=dep.target_entity["id"],
                dep_type=dep.dep_type,
                confidence=dep.confidence,
                evidence=[memory_id],
            )
            graph.add_dependency(edge)
