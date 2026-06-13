"""
因果推理引擎

基于记忆关联图进行因果推理，支持：
- 查找因果链
- 预测原因的可能结果
- 找到结果的根本原因
- 生成因果关系的自然语言解释
"""

import logging
from collections import deque
from typing import Any, Dict, List, Set, Tuple

from .graph_traversal import GraphTraversal

logger = logging.getLogger(__name__)


class CausalReasoningEngine:
    """因果推理引擎

    在记忆关联图上执行因果推理，支持多跳因果分析。
    """

    def __init__(self, graph: GraphTraversal):
        """初始化因果推理引擎

        Args:
            graph: 图遍历引擎实例
        """
        self.graph = graph
        self._causal_types = {"causes", "caused_by", "enables", "enabled_by", "prevents", "prevented_by", "requires"}
        # 前向因果关系（从因到果的边）：这些关系的 target 是 effect
        self._effect_types = {"causes", "enables", "prevents", "requires"}
        # 反向因果关系（搜索根本原因时，入边中的因果关系类型）：
        #   "caused_by" 入边 → source 是原因
        #   "causes" 入边 → source 也是原因（B causes C → B 是 C 的原因）
        self._cause_types = {"caused_by", "enabled_by", "prevented_by", "requires", "causes", "enables", "prevents"}

        logger.debug("CausalReasoningEngine 初始化完成")

    def find_causal_chain(self, start_id: str, end_id: str) -> List[List[str]]:
        """查找两个记忆之间的因果链

        Args:
            start_id: 起始记忆ID（原因）
            end_id: 结束记忆ID（结果）

        Returns:
            List[List[str]]: 因果链列表，每个链是一个节点ID列表
        """
        # 使用BFS查找所有路径
        all_paths = []
        queue = deque()
        queue.append((start_id, [start_id]))

        while queue:
            current_id, path = queue.popleft()

            if current_id == end_id:
                all_paths.append(path)
                continue

            if len(path) > 10:  # 防止无限循环
                continue

            # 获取因果关系
            relations = self.graph.get_relations(current_id, direction="outgoing")
            for relation in relations:
                if relation.relation_type in self._causal_types:
                    next_id = relation.target_id
                    if next_id not in path:  # 避免循环
                        queue.append((next_id, path + [next_id]))

        # 按路径长度排序
        all_paths.sort(key=len)
        return all_paths

    def predict_effects(self, cause_id: str) -> List[Tuple[str, float]]:
        """预测原因的可能结果

        Args:
            cause_id: 原因记忆ID

        Returns:
            List[Tuple[str, float]]: 结果列表，每个元素是 (结果ID, 置信度)
        """
        effects = []
        visited = set()
        queue = deque()
        queue.append((cause_id, 1.0, 0))

        while queue:
            current_id, confidence, depth = queue.popleft()

            if depth > 5:  # 限制深度
                continue

            if current_id in visited:
                continue
            visited.add(current_id)

            # 获取因果关系
            relations = self.graph.get_relations(current_id, direction="outgoing")
            for relation in relations:
                if relation.relation_type in self._effect_types:
                    next_id = relation.target_id
                    # 计算置信度：关系强度 * 衰减因子
                    decay = 0.8**depth
                    next_confidence = confidence * relation.strength * decay

                    effects.append((next_id, next_confidence))
                    queue.append((next_id, next_confidence, depth + 1))

        # 按置信度排序
        effects.sort(key=lambda x: x[1], reverse=True)

        # 去重，保留最高置信度
        seen = set()
        unique_effects = []
        for effect_id, confidence in effects:
            if effect_id not in seen:
                seen.add(effect_id)
                unique_effects.append((effect_id, confidence))

        return unique_effects

    def find_root_causes(self, effect_id: str) -> List[Tuple[str, float]]:
        """找到结果的根本原因

        Args:
            effect_id: 结果记忆ID

        Returns:
            List[Tuple[str, float]]: 根本原因列表，每个元素是 (原因ID, 置信度)
        """
        root_causes = []
        visited = set()
        queue = deque()
        queue.append((effect_id, 1.0, 0))

        while queue:
            current_id, confidence, depth = queue.popleft()

            if depth > 5:  # 限制深度
                continue

            if current_id in visited:
                continue
            visited.add(current_id)

            # 获取因果关系（反向）
            relations = self.graph.get_relations(current_id, direction="incoming")
            for relation in relations:
                if relation.relation_type in self._cause_types:
                    prev_id = relation.source_id
                    # 计算置信度
                    decay = 0.8**depth
                    prev_confidence = confidence * relation.strength * decay

                    root_causes.append((prev_id, prev_confidence))
                    queue.append((prev_id, prev_confidence, depth + 1))

        # 按置信度排序
        root_causes.sort(key=lambda x: x[1], reverse=True)

        # 去重，保留最高置信度
        seen = set()
        unique_causes = []
        for cause_id, confidence in root_causes:
            if cause_id not in seen:
                seen.add(cause_id)
                unique_causes.append((cause_id, confidence))

        return unique_causes

    def explain_causality(self, cause_id: str, effect_id: str) -> str:
        """生成因果关系的自然语言解释

        Args:
            cause_id: 原因记忆ID
            effect_id: 结果记忆ID

        Returns:
            str: 自然语言解释
        """
        # 查找因果链
        chains = self.find_causal_chain(cause_id, effect_id)

        if not chains:
            return f"未找到 {cause_id} 和 {effect_id} 之间的因果关系"

        # 获取最短路径
        shortest_chain = chains[0]

        # 构建解释
        explanation_parts = []

        for i in range(len(shortest_chain) - 1):
            source_id = shortest_chain[i]
            target_id = shortest_chain[i + 1]

            # 获取关系类型
            relations = self.graph.get_relations(source_id, direction="outgoing")
            relation_type = "related"
            strength = 0.5

            for relation in relations:
                if relation.target_id == target_id:
                    relation_type = relation.relation_type
                    strength = relation.strength
                    break

            # 翻译关系类型
            relation_translations = {
                "causes": "导致",
                "caused_by": "由...引起",
                "enables": "使能",
                "enabled_by": "由...使能",
                "prevents": "阻止",
                "prevented_by": "被...阻止",
                "requires": "需要",
                "related": "相关",
                "supports": "支持",
                "contradicts": "矛盾",
                "part_of": "是...的一部分",
                "derived_from": "来源于",
                "temporal": "时间上相关",
                "evolves_to": "演化为",
                "evolved_from": "由...演化而来",
                "replaces": "替代",
                "replaced_by": "被...替代",
                "version_of": "是...的版本",
                "synonym": "同义于",
                "antonym": "反义于",
                "hypernym": "是...的上位词",
                "hyponym": "是...的下位词",
            }

            relation_text = relation_translations.get(relation_type, relation_type)

            explanation_parts.append(f"{source_id} {relation_text} {target_id} (强度: {strength:.2f})")

        # 组合解释
        if len(explanation_parts) == 1:
            return f"因果关系: {explanation_parts[0]}"
        else:
            chain_text = " → ".join(shortest_chain)
            details = "\n".join([f"  - {part}" for part in explanation_parts])
            return f"因果链: {chain_text}\n详细关系:\n{details}"

    def get_causal_graph_summary(self, memory_id: str, depth: int = 2) -> Dict[str, Any]:
        """获取记忆的因果图摘要

        Args:
            memory_id: 记忆ID
            depth: 遍历深度

        Returns:
            Dict[str, Any]: 因果图摘要
        """
        # 获取前向因果
        forward_effects = self.predict_effects(memory_id)

        # 获取反向因果
        backward_causes = self.find_root_causes(memory_id)

        # 获取直接关系
        direct_relations = self.graph.get_relations(memory_id, direction="both")
        causal_relations = [r for r in direct_relations if r.relation_type in self._causal_types]

        return {
            "memory_id": memory_id,
            "forward_effects": forward_effects[:10],  # 前10个结果
            "backward_causes": backward_causes[:10],  # 前10个原因
            "direct_causal_relations": len(causal_relations),
            "total_forward_effects": len(forward_effects),
            "total_backward_causes": len(backward_causes),
        }

    def detect_causal_loops(self) -> List[List[str]]:
        """检测因果循环

        Returns:
            List[List[str]]: 循环列表，每个循环是一个节点ID列表
        """
        loops = []
        visited = set()

        # 使用DFS检测循环
        def dfs(node_id: str, path: List[str], visited_in_path: Set[str]):
            if node_id in visited_in_path:
                # 找到循环
                cycle_start = path.index(node_id)
                loop = path[cycle_start:] + [node_id]
                loops.append(loop)
                return

            if node_id in visited:
                return

            visited.add(node_id)
            visited_in_path.add(node_id)
            path.append(node_id)

            # 遍历因果关系
            relations = self.graph.get_relations(node_id, direction="outgoing")
            for relation in relations:
                if relation.relation_type in self._causal_types:
                    dfs(relation.target_id, path, visited_in_path)

            path.pop()
            visited_in_path.remove(node_id)

        # 获取所有节点
        all_nodes = set()
        for node_id in self.graph._graph.keys():
            all_nodes.add(node_id)
        for node_id in self.graph._reverse_graph.keys():
            all_nodes.add(node_id)

        # 检测每个节点的循环
        for node_id in all_nodes:
            if node_id not in visited:
                dfs(node_id, [], set())

        # 去重
        unique_loops = []
        seen = set()
        for loop in loops:
            loop_tuple = tuple(sorted(set(loop[:-1])))  # 去掉最后一个重复节点
            if loop_tuple not in seen:
                seen.add(loop_tuple)
                unique_loops.append(loop)

        return unique_loops


def get_causal_reasoning_engine(graph: GraphTraversal) -> CausalReasoningEngine:
    """获取因果推理引擎实例

    Args:
        graph: 图遍历引擎实例

    Returns:
        CausalReasoningEngine: 因果推理引擎实例
    """
    return CausalReasoningEngine(graph)
