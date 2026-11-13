"""
ExplainabilityModule — 可解释性模块

提供记忆检索和决策的可解释性
"""

from __future__ import annotations

from neurova.core.logger import get_logger
import datetime
import json
import threading
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = get_logger(__name__)


@dataclass
class Explanation:
    """解释记录"""

    explanation_id: str
    action: str  # 描述被解释的动作
    reasons: List[str]  # 原因列表
    confidence: float  # 解释置信度 [0, 1]
    factors: Dict[str, float] = field(default_factory=dict)  # 影响因素及其权重

    def to_dict(self) -> Dict[str, Any]:
        return {
            "explanation_id": self.explanation_id,
            "action": self.action,
            "reasons": self.reasons,
            "confidence": self.confidence,
            "factors": self.factors,
        }

    def to_text(self) -> str:
        """转换为可读文本"""
        text = f"动作: {self.action}\n"
        text += f"置信度: {self.confidence:.2f}\n"
        text += "原因:\n"
        for i, reason in enumerate(self.reasons, 1):
            text += f"  {i}. {reason}\n"

        if self.factors:
            text += "影响因素:\n"
            for factor, weight in sorted(self.factors.items(), key=lambda x: x[1], reverse=True):
                text += f"  - {factor}: {weight:.2f}\n"

        return text


class TriggerNodeType(str, Enum):
    """触发链节点类型（自 explainability.py 取长补短，2026-11-14 退役裁定）"""

    INPUT = "input"  # 输入节点
    PROCESSING = "processing"  # 处理节点
    DECISION = "decision"  # 决策节点
    OUTPUT = "output"  # 输出节点
    MEMORY = "memory"  # 记忆节点
    TRIGGER = "trigger"  # 触发节点


@dataclass
class TriggerNode:
    """触发链节点"""

    node_id: str
    node_type: TriggerNodeType
    name: str
    description: str = ""
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime.datetime = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc))
    parent_id: Optional[str] = None
    children: List[str] = field(default_factory=list)

    def add_child(self, child_id: str) -> None:
        """添加子节点"""
        if child_id not in self.children:
            self.children.append(child_id)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "node_id": self.node_id,
            "node_type": self.node_type.value,
            "name": self.name,
            "description": self.description,
            "data": self.data,
            "timestamp": self.timestamp.isoformat(),
            "parent_id": self.parent_id,
            "children": self.children,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TriggerNode":
        """从字典创建"""
        return cls(
            node_id=data.get("node_id", ""),
            node_type=TriggerNodeType(data.get("node_type", "input")),
            name=data.get("name", ""),
            description=data.get("description", ""),
            data=data.get("data", {}),
            timestamp=datetime.datetime.fromisoformat(
                data.get("timestamp", datetime.datetime.now(datetime.timezone.utc).isoformat())
            ),
            parent_id=data.get("parent_id"),
            children=data.get("children", []),
        )


@dataclass
class TriggerChain:
    """触发链：一条「为什么被记住/召回」的因果树"""

    chain_id: str
    name: str
    description: str = ""
    created_at: datetime.datetime = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc))
    completed_at: Optional[datetime.datetime] = None
    nodes: Dict[str, TriggerNode] = field(default_factory=dict)
    root_node_id: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def add_node(self, node: TriggerNode) -> None:
        """添加节点（首节点为根；带父节点时建立父子关系）"""
        self.nodes[node.node_id] = node
        if self.root_node_id is None:
            self.root_node_id = node.node_id
        if node.parent_id and node.parent_id in self.nodes:
            parent = self.nodes[node.parent_id]
            parent.add_child(node.node_id)

    def set_result(self, result: Dict[str, Any]) -> None:
        """设置结果并标记完成"""
        self.result = result
        self.completed_at = datetime.datetime.now(datetime.timezone.utc)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "chain_id": self.chain_id,
            "name": self.name,
            "description": self.description,
            "created_at": self.created_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "nodes": {node_id: node.to_dict() for node_id, node in self.nodes.items()},
            "root_node_id": self.root_node_id,
            "result": self.result,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TriggerChain":
        """从字典创建"""
        chain = cls(
            chain_id=data.get("chain_id", ""),
            name=data.get("name", ""),
            description=data.get("description", ""),
            created_at=datetime.datetime.fromisoformat(
                data.get("created_at", datetime.datetime.now(datetime.timezone.utc).isoformat())
            ),
            metadata=data.get("metadata", {}),
        )
        if data.get("completed_at"):
            chain.completed_at = datetime.datetime.fromisoformat(data["completed_at"])
        chain.result = data.get("result")
        chain.root_node_id = data.get("root_node_id")
        for node_id, node_data in data.get("nodes", {}).items():
            chain.nodes[node_id] = TriggerNode.from_dict(node_data)
        return chain


class ExplainabilityModule:
    """
    可解释性模块

    提供记忆检索和决策的可解释性，支持：
    - 检索解释：为什么返回这些记忆
    - 决策解释：为什么做出这个决策
    - 因素分析：哪些因素影响了结果
    """

    def __init__(self, max_explanations: int = 100, max_chains: int = 10000):
        """
        Args:
            max_explanations: 最大解释记录数
            max_chains: 最大触发链数（超出淘汰最旧，2026-11-14 自 explainability.py 并入）
        """
        self._max_explanations = max_explanations
        self._lock = threading.RLock()
        self._initialized = False

        # 解释历史
        self._explanations: List[Explanation] = []

        # 因素权重
        self._factor_weights: Dict[str, float] = {
            "relevance": 0.3,
            "recency": 0.2,
            "importance": 0.2,
            "frequency": 0.15,
            "emotion": 0.15,
        }

        # 触发链存储（D3 取长补短：memory_id ↔ 链双向索引）
        self._chains: Dict[str, TriggerChain] = {}
        self._memory_chains: Dict[str, List[str]] = defaultdict(list)
        self._max_chains = max_chains
        self._total_chains = 0
        self._total_chain_nodes = 0

    @property
    def name(self) -> str:
        """模块名称"""
        return "explainability_module"

    def init(self) -> bool:
        """初始化模块"""
        self._initialized = True
        logger.info("ExplainabilityModule initialized")
        return True

    def shutdown(self) -> None:
        """关闭模块"""
        self._initialized = False
        logger.info("ExplainabilityModule shutdown")

    def explain_retrieval(
        self,
        query: str,
        retrieved_ids: List[str],
        scores: Dict[str, float],
        factors: Optional[Dict[str, Dict[str, float]]] = None,
    ) -> Explanation:
        """
        解释检索结果

        Args:
            query: 查询
            retrieved_ids: 检索到的记忆ID列表
            scores: 记忆ID -> 分数
            factors: 记忆ID -> 因素 -> 分数

        Returns:
            解释记录
        """
        reasons = []

        # 分析检索原因
        if retrieved_ids:
            top_id = retrieved_ids[0]
            top_score = scores.get(top_id, 0)

            reasons.append(f"查询 '{query}' 与 {len(retrieved_ids)} 条记忆匹配")
            reasons.append(f"最高匹配分数: {top_score:.2f}")

            # 分析因素
            if factors and top_id in factors:
                top_factors = factors[top_id]
                # Bug 17 修复: 防空字典 max() 抛 ValueError
                if top_factors:
                    max_factor = max(top_factors.items(), key=lambda x: x[1])
                    reasons.append(f"主要匹配因素: {max_factor[0]} ({max_factor[1]:.2f})")

        # 计算置信度
        confidence = 0.0
        if scores:
            avg_score = sum(scores.values()) / len(scores)
            confidence = min(1.0, avg_score)

        explanation = Explanation(
            explanation_id=f"retrieval_{len(self._explanations)}",
            action=f"检索 '{query}'",
            reasons=reasons,
            confidence=confidence,
            factors=self._factor_weights,
        )

        with self._lock:
            self._explanations.append(explanation)
            if len(self._explanations) > self._max_explanations:
                self._explanations = self._explanations[-self._max_explanations :]

        return explanation

    def explain_decision(
        self,
        decision: str,
        context: Dict[str, Any],
        alternatives: Optional[List[str]] = None,
    ) -> Explanation:
        """
        解释决策

        Args:
            decision: 决策内容
            context: 决策上下文
            alternatives: 备选方案

        Returns:
            解释记录
        """
        reasons = []

        # 分析决策原因
        reasons.append(f"选择: {decision}")

        if alternatives:
            reasons.append(f"考虑了 {len(alternatives)} 个备选方案")

        # 从上下文中提取因素
        factors = {}
        if "importance" in context:
            factors["importance"] = context["importance"]
        if "confidence" in context:
            factors["confidence"] = context["confidence"]
        if "risk" in context:
            factors["risk"] = context["risk"]

        confidence = context.get("confidence", 0.7)

        explanation = Explanation(
            explanation_id=f"decision_{len(self._explanations)}",
            action=decision,
            reasons=reasons,
            confidence=confidence,
            factors=factors,
        )

        with self._lock:
            self._explanations.append(explanation)
            if len(self._explanations) > self._max_explanations:
                self._explanations = self._explanations[-self._max_explanations :]

        return explanation

    def add_explanation(
        self,
        action: str,
        reasons: List[str],
        confidence: float = 0.7,
        factors: Optional[Dict[str, float]] = None,
    ) -> Explanation:
        """添加自定义解释"""
        explanation = Explanation(
            explanation_id=f"custom_{len(self._explanations)}",
            action=action,
            reasons=reasons,
            confidence=confidence,
            factors=factors or {},
        )

        with self._lock:
            self._explanations.append(explanation)
            if len(self._explanations) > self._max_explanations:
                self._explanations = self._explanations[-self._max_explanations :]

        return explanation

    def get_explanations(self, limit: int = 10) -> List[Explanation]:
        """获取解释历史"""
        with self._lock:
            return self._explanations[-limit:]

    def get_explanation(self, explanation_id: str) -> Optional[Explanation]:
        """获取特定解释"""
        with self._lock:
            for exp in self._explanations:
                if exp.explanation_id == explanation_id:
                    return exp
        return None

    def set_factor_weights(self, weights: Dict[str, float]) -> None:
        """设置因素权重"""
        with self._lock:
            self._factor_weights.update(weights)

    def get_factor_weights(self) -> Dict[str, float]:
        """获取因素权重"""
        with self._lock:
            return dict(self._factor_weights)

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self._lock:
            if not self._explanations:
                base: Dict[str, Any] = {
                    "total_explanations": 0,
                    "avg_confidence": 0,
                }
            else:
                avg_confidence = sum(e.confidence for e in self._explanations) / len(self._explanations)
                base = {
                    "total_explanations": len(self._explanations),
                    "avg_confidence": avg_confidence,
                    "factor_weights": dict(self._factor_weights),
                }
            # 触发链接数（D3 并入能力）
            base.update(
                {
                    "active_chains": len(self._chains),
                    "total_chains": self._total_chains,
                    "total_chain_nodes": self._total_chain_nodes,
                    "memory_chain_associations": len(self._memory_chains),
                    "max_chains": self._max_chains,
                }
            )
            return base

    # ============================================================
    # 触发链（D3 自 explainability.py 取长补短并入，2026-11-14 退役裁定）
    # ============================================================

    def start_chain(
        self,
        name: str,
        description: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """开始新的触发链，返回链 ID"""
        with self._lock:
            chain_id = str(uuid.uuid4())
            self._chains[chain_id] = TriggerChain(
                chain_id=chain_id,
                name=name,
                description=description,
                metadata=metadata or {},
            )
            self._total_chains += 1
            self._cleanup_old_chains()
            logger.debug("Trigger chain started: %s (%s)", chain_id, name)
            return chain_id

    def add_node_to_chain(
        self,
        chain_id: str,
        node_type: TriggerNodeType,
        name: str,
        description: str = "",
        data: Optional[Dict[str, Any]] = None,
        parent_node_id: Optional[str] = None,
    ) -> Optional[str]:
        """向触发链添加节点（parent 缺省挂到最后一个叶子），返回节点 ID"""
        with self._lock:
            chain = self._chains.get(chain_id)
            if not chain:
                logger.warning("Chain not found: %s", chain_id)
                return None

            node_id = str(uuid.uuid4())
            if parent_node_id is None and chain.nodes:
                parent_node_id = next(
                    (nid for nid, node in chain.nodes.items() if not node.children),
                    None,
                )

            node = TriggerNode(
                node_id=node_id,
                node_type=node_type,
                name=name,
                description=description,
                data=data or {},
                parent_id=parent_node_id,
            )
            chain.add_node(node)
            self._total_chain_nodes += 1
            logger.debug("Node added to chain %s: %s (%s)", chain_id, node_id, name)
            return node_id

    def complete_chain(
        self,
        chain_id: str,
        result: Optional[Dict[str, Any]] = None,
        memory_id: Optional[str] = None,
    ) -> bool:
        """完成触发链；给 memory_id 时建立记忆↔链双向索引"""
        with self._lock:
            chain = self._chains.get(chain_id)
            if not chain:
                logger.warning("Chain not found: %s", chain_id)
                return False
            chain.set_result(result or {})
            if memory_id:
                self._memory_chains[memory_id].append(chain_id)
            logger.debug("Chain completed: %s", chain_id)
            return True

    def get_chain(self, chain_id: str) -> Optional[TriggerChain]:
        """获取触发链"""
        return self._chains.get(chain_id)

    def get_memory_chains(self, memory_id: str) -> List[TriggerChain]:
        """获取记忆的所有触发链"""
        chains = []
        for chain_id in self._memory_chains.get(memory_id, []):
            chain = self._chains.get(chain_id)
            if chain:
                chains.append(chain)
        return chains

    def explain_memory_chains(self, memory_id: str) -> Dict[str, Any]:
        """按记忆聚合触发链并展开节点路径（诚实形态：无链时如实回报 0 条）"""
        chains = self.get_memory_chains(memory_id)
        explanations = []
        for chain in chains:
            entry: Dict[str, Any] = {
                "chain_id": chain.chain_id,
                "name": chain.name,
                "description": chain.description,
                "created_at": chain.created_at.isoformat(),
                "completed_at": chain.completed_at.isoformat() if chain.completed_at else None,
                "node_count": len(chain.nodes),
                "result": chain.result,
            }
            if chain.root_node_id:
                entry["path"] = self._build_node_path(chain, chain.root_node_id)
            explanations.append(entry)
        return {
            "memory_id": memory_id,
            "chain_count": len(chains),
            "chains": explanations,
        }

    def _build_node_path(self, chain: TriggerChain, node_id: str) -> List[Dict[str, Any]]:
        """沿首子链展开节点路径（防环）"""
        path: List[Dict[str, Any]] = []
        current_id: Optional[str] = node_id
        visited: set = set()
        while current_id and current_id not in visited:
            visited.add(current_id)
            node = chain.nodes.get(current_id)
            if not node:
                break
            path.append(
                {
                    "node_id": node.node_id,
                    "node_type": node.node_type.value,
                    "name": node.name,
                    "description": node.description,
                    "timestamp": node.timestamp.isoformat(),
                }
            )
            current_id = node.children[0] if node.children else None
        return path

    def visualize_chain(self, chain_id: str) -> str:
        """树状文本可视化触发链"""
        chain = self._chains.get(chain_id)
        if not chain:
            return f"Chain not found: {chain_id}"

        lines = [
            f"Trigger Chain: {chain.name}",
            f"ID: {chain.chain_id}",
            f"Description: {chain.description}",
            f"Created: {chain.created_at.isoformat()}",
        ]
        if chain.completed_at:
            lines.append(f"Completed: {chain.completed_at.isoformat()}")
        lines.append("")
        if chain.root_node_id:
            self._visualize_node(chain, chain.root_node_id, lines, indent=0)
        if chain.result:
            lines.append("")
            lines.append("Result:")
            lines.append(json.dumps(chain.result, indent=2, ensure_ascii=False))
        return "\n".join(lines)

    def _visualize_node(
        self,
        chain: TriggerChain,
        node_id: str,
        lines: List[str],
        indent: int = 0,
    ) -> None:
        """递归可视化节点"""
        node = chain.nodes.get(node_id)
        if not node:
            return
        prefix = "  " * indent
        type_symbol = {
            TriggerNodeType.INPUT: "📥",
            TriggerNodeType.PROCESSING: "⚙️",
            TriggerNodeType.DECISION: "🔀",
            TriggerNodeType.OUTPUT: "📤",
            TriggerNodeType.MEMORY: "🧠",
            TriggerNodeType.TRIGGER: "⚡",
        }.get(node.node_type, "❓")
        lines.append(f"{prefix}{type_symbol} {node.name}")
        if node.description:
            lines.append(f"{prefix}   {node.description}")
        for child_id in node.children:
            self._visualize_node(chain, child_id, lines, indent + 1)

    def _cleanup_old_chains(self) -> None:
        """容量治理：超出 max_chains 时淘汰最旧链并同步清理记忆关联索引"""
        if len(self._chains) <= self._max_chains:
            return
        sorted_chains = sorted(self._chains.items(), key=lambda x: x[1].created_at)
        to_remove = len(self._chains) - self._max_chains
        for i in range(to_remove):
            chain_id, _chain = sorted_chains[i]
            for chain_ids in self._memory_chains.values():
                if chain_id in chain_ids:
                    chain_ids.remove(chain_id)
            del self._chains[chain_id]
        logger.debug("Cleaned up %s old trigger chains", to_remove)

    def export_chain(self, chain_id: str) -> Optional[str]:
        """导出触发链为 JSON（跨进程回放用）；失败返回 None"""
        chain = self._chains.get(chain_id)
        if not chain:
            return None
        try:
            return json.dumps(chain.to_dict(), indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error("Failed to export chain: %s", e)
            return None

    def import_chain(self, json_str: str) -> Optional[str]:
        """从 JSON 导入触发链（含记忆关联重建）；失败返回 None"""
        try:
            data = json.loads(json_str)
            chain = TriggerChain.from_dict(data)
            with self._lock:
                self._chains[chain.chain_id] = chain
                self._total_chains += 1
                if chain.result and "memory_id" in chain.result:
                    self._memory_chains[str(chain.result["memory_id"])].append(chain.chain_id)
            logger.info("Chain imported: %s", chain.chain_id)
            return chain.chain_id
        except Exception as e:
            logger.error("Failed to import chain: %s", e)
            return None
