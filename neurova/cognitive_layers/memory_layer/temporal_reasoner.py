"""
时序推理器 (Temporal Reasoner)

实现功能：
1. 时序关系提取（before, after, during, same_time, overlaps）
2. 传递性推理（A→B→C → A→C）
3. 时序矛盾检测（A→B 且 B→A）
4. 时间约束推理（deadline, order）
5. 时序排序（按时间排序实体）
"""

from neurova.core.logger import get_logger
import re
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

logger = get_logger(__name__)


class TemporalRelation(Enum):
    """时序关系枚举"""
    BEFORE = "before"
    AFTER = "after"
    DURING = "during"
    SAME_TIME = "same_time"
    OVERLAPS = "overlaps"


class TemporalFactTR:
    """时序事实数据类"""
    
    def __init__(
        self,
        subject: str,
        relation: TemporalRelation,
        object_: str,
        confidence: float = 1.0,
        source: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.subject = subject
        self.relation = relation
        self.object_ = object_
        self.confidence = confidence
        self.source = source
        self.metadata = metadata or {}
    
    def invert(self) -> "TemporalFactTR":
        """反转关系：A before B -> B after A"""
        # 关系反转映射
        inverse_map = {
            TemporalRelation.BEFORE: TemporalRelation.AFTER,
            TemporalRelation.AFTER: TemporalRelation.BEFORE,
            TemporalRelation.SAME_TIME: TemporalRelation.SAME_TIME,
            TemporalRelation.DURING: TemporalRelation.DURING,  # 保守处理
            TemporalRelation.OVERLAPS: TemporalRelation.OVERLAPS,  # 保守处理
        }
        
        return TemporalFactTR(
            subject=self.object_,
            relation=inverse_map.get(self.relation, self.relation),
            object_=self.subject,
            confidence=self.confidence,
            source=self.source,
            metadata=self.metadata.copy(),
        )
    
    def __repr__(self) -> str:
        return f"TemporalFactTR({self.subject!r}, {self.relation.value}, {self.object_!r})"
    
    def __eq__(self, other) -> bool:
        if not isinstance(other, TemporalFactTR):
            return False
        return (
            self.subject == other.subject
            and self.relation == other.relation
            and self.object_ == other.object_
        )
    
    def __hash__(self) -> int:
        return hash((self.subject, self.relation, self.object_))


class TemporalConstraint:
    """时间约束"""
    
    def __init__(
        self,
        entity: str,
        constraint_type: str,
        deadline: Optional[datetime] = None,
        required_before: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.entity = entity
        self.constraint_type = constraint_type
        self.deadline = deadline
        self.required_before = required_before
        self.metadata = metadata or {}
    
    def __repr__(self) -> str:
        if self.constraint_type == "deadline":
            return f"TemporalConstraint({self.entity!r}, deadline={self.deadline})"
        elif self.constraint_type == "order":
            return f"TemporalConstraint({self.entity!r}, required_before={self.required_before!r})"
        return f"TemporalConstraint({self.entity!r}, type={self.constraint_type})"


class TemporalReasoner:
    """时序推理器"""
    
    # 关系组合表：(关系1, 关系2) -> 组合结果
    # 表示：如果 A R1 B 且 B R2 C，则 A ? C
    _COMPOSITION_TABLE = {
        # BEFORE 组合
        (TemporalRelation.BEFORE, TemporalRelation.BEFORE): TemporalRelation.BEFORE,
        (TemporalRelation.BEFORE, TemporalRelation.AFTER): None,  # 不确定
        (TemporalRelation.BEFORE, TemporalRelation.SAME_TIME): TemporalRelation.BEFORE,
        (TemporalRelation.BEFORE, TemporalRelation.DURING): TemporalRelation.BEFORE,
        (TemporalRelation.BEFORE, TemporalRelation.OVERLAPS): TemporalRelation.BEFORE,
        
        # AFTER 组合
        (TemporalRelation.AFTER, TemporalRelation.AFTER): TemporalRelation.AFTER,
        (TemporalRelation.AFTER, TemporalRelation.BEFORE): None,  # 不确定
        (TemporalRelation.AFTER, TemporalRelation.SAME_TIME): TemporalRelation.AFTER,
        (TemporalRelation.AFTER, TemporalRelation.DURING): TemporalRelation.AFTER,
        (TemporalRelation.AFTER, TemporalRelation.OVERLAPS): TemporalRelation.AFTER,
        
        # SAME_TIME 组合
        (TemporalRelation.SAME_TIME, TemporalRelation.BEFORE): TemporalRelation.BEFORE,
        (TemporalRelation.SAME_TIME, TemporalRelation.AFTER): TemporalRelation.AFTER,
        (TemporalRelation.SAME_TIME, TemporalRelation.SAME_TIME): TemporalRelation.SAME_TIME,
        (TemporalRelation.SAME_TIME, TemporalRelation.DURING): TemporalRelation.DURING,
        (TemporalRelation.SAME_TIME, TemporalRelation.OVERLAPS): TemporalRelation.OVERLAPS,
        
        # DURING 组合
        (TemporalRelation.DURING, TemporalRelation.BEFORE): TemporalRelation.BEFORE,
        (TemporalRelation.DURING, TemporalRelation.AFTER): TemporalRelation.AFTER,
        (TemporalRelation.DURING, TemporalRelation.SAME_TIME): TemporalRelation.DURING,
        (TemporalRelation.DURING, TemporalRelation.DURING): TemporalRelation.DURING,
        (TemporalRelation.DURING, TemporalRelation.OVERLAPS): TemporalRelation.OVERLAPS,
        
        # OVERLAPS 组合
        (TemporalRelation.OVERLAPS, TemporalRelation.BEFORE): TemporalRelation.BEFORE,
        (TemporalRelation.OVERLAPS, TemporalRelation.AFTER): TemporalRelation.AFTER,
        (TemporalRelation.OVERLAPS, TemporalRelation.SAME_TIME): TemporalRelation.OVERLAPS,
        (TemporalRelation.OVERLAPS, TemporalRelation.DURING): TemporalRelation.OVERLAPS,
        (TemporalRelation.OVERLAPS, TemporalRelation.OVERLAPS): TemporalRelation.OVERLAPS,
    }
    
    def __init__(self):
        # 事实存储：(subject, object_) -> list of TemporalFactTR
        self._facts: Dict[Tuple[str, str], List[TemporalFactTR]] = defaultdict(list)
        # 所有实体集合
        self._entities: Set[str] = set()
        # 矛盾列表
        self._contradictions: List[Dict[str, Any]] = []
        # 传递闭包缓存：需要时计算
        self._transitive_closure: Optional[Dict[Tuple[str, str], TemporalFactTR]] = None
    
    def add_fact(
        self,
        subject: str,
        relation: TemporalRelation,
        object_: str,
        confidence: float = 1.0,
        source: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        添加时序事实，检测矛盾
        
        Returns:
            矛盾列表，如果没有矛盾则为空列表
        """
        # 创建事实对象
        fact = TemporalFactTR(
            subject=subject,
            relation=relation,
            object_=object_,
            confidence=confidence,
            source=source,
            metadata=metadata,
        )
        
        # 添加到存储
        self._facts[(subject, object_)].append(fact)
        self._entities.add(subject)
        self._entities.add(object_)
        
        # 使传递闭包缓存失效
        self._transitive_closure = None
        
        # 检测矛盾
        conflicts = self._detect_conflicts(fact)
        
        # 记录矛盾
        for conflict in conflicts:
            self._contradictions.append(conflict)
        
        return conflicts
    
    def infer_relation(
        self,
        subject: str,
        object_: str,
        max_depth: int = 10,
    ) -> Optional[TemporalFactTR]:
        """
        推断两个实体之间的时序关系
        
        使用 BFS 在关系图中搜索传递链
        """
        if subject == object_:
            return None
        
        # 直接关系
        direct_facts = self._facts.get((subject, object_), [])
        if direct_facts:
            # 返回置信度最高的关系
            return max(direct_facts, key=lambda f: f.confidence)
        
        # BFS 搜索传递链
        visited: Set[str] = set()
        queue: deque[Tuple[str, TemporalFactTR, int]] = deque()
        
        # 从 subject 开始
        for (s, o), facts in self._facts.items():
            if s == subject:
                for fact in facts:
                    queue.append((o, fact, 1))
                    visited.add(o)
        
        while queue:
            current, accumulated_fact, depth = queue.popleft()
            
            if depth > max_depth:
                continue
            
            if current == object_:
                return accumulated_fact
            
            # 继续搜索
            for (s, o), facts in self._facts.items():
                if s == current and o not in visited:
                    for fact in facts:
                        # 组合关系
                        combined = self._compose_relations(accumulated_fact, fact)
                        if combined is not None:
                            visited.add(o)
                            queue.append((o, combined, depth + 1))
        
        return None
    
    @staticmethod
    def _clean_entity(name: str) -> str:
        """清理实体名称：去除标点符号和多余空白"""
        # 去除首尾标点符号（中文和英文）
        cleaned = re.sub(r'^[\s，,。.；;：:、\-\—\–\(\)\[\]{}【】""\'\'\"\'‘]+', '', name)
        cleaned = re.sub(r'[\s，,。.；;：:、\-\—\–\(\)\[\]{}【】""\'\'\"\'‘]+$', '', cleaned)
        return cleaned.strip()
    
    def extract_from_text(self, text: str) -> List[TemporalFactTR]:
        """从文本中提取时序关系"""
        facts = []
        
        # 先按中文标点分句，避免跨句匹配
        segments = re.split(r'[，,。.；;]', text)
        
        # 模式1: A在B之前/后/同时
        pattern1 = r"(.+?)在(.+?)(之前|后|之后|同时)"
        for segment in segments:
            for match in re.finditer(pattern1, segment):
                entity1, entity2, relation_word = match.groups()
                entity1 = self._clean_entity(entity1)
                entity2 = self._clean_entity(entity2)
                
                if not entity1 or not entity2:
                    continue
                
                if "之前" in relation_word:
                    relation = TemporalRelation.BEFORE
                elif "之后" in relation_word or "后" in relation_word:
                    relation = TemporalRelation.AFTER
                elif "同时" in relation_word:
                    relation = TemporalRelation.SAME_TIME
                else:
                    continue
                
                facts.append(TemporalFactTR(subject=entity1, relation=relation, object_=entity2))
        
        # 模式2: A和B同时
        pattern2 = r"(.+?)和(.+?)同时"
        for segment in segments:
            for match in re.finditer(pattern2, segment):
                entity1, entity2 = match.groups()
                entity1 = self._clean_entity(entity1)
                entity2 = self._clean_entity(entity2)
                if entity1 and entity2:
                    facts.append(TemporalFactTR(subject=entity1, relation=TemporalRelation.SAME_TIME, object_=entity2))
        
        # 模式3: A before B (英文)
        pattern3 = r"(.+?)\s+before\s+(.+)"
        for match in re.finditer(pattern3, text, re.IGNORECASE):
            entity1, entity2 = match.groups()
            entity1 = self._clean_entity(entity1)
            entity2 = self._clean_entity(entity2)
            if entity1 and entity2:
                facts.append(TemporalFactTR(subject=entity1, relation=TemporalRelation.BEFORE, object_=entity2))
        
        # 模式4: A after B (英文)
        pattern4 = r"(.+?)\s+after\s+(.+)"
        for match in re.finditer(pattern4, text, re.IGNORECASE):
            entity1, entity2 = match.groups()
            entity1 = self._clean_entity(entity1)
            entity2 = self._clean_entity(entity2)
            if entity1 and entity2:
                facts.append(TemporalFactTR(subject=entity1, relation=TemporalRelation.AFTER, object_=entity2))
        
        # 模式5: A same_time B (英文)
        pattern5 = r"(.+?)\s+(?:same.?time|simultaneously)\s+(.+)"
        for match in re.finditer(pattern5, text, re.IGNORECASE):
            entity1, entity2 = match.groups()
            entity1 = self._clean_entity(entity1)
            entity2 = self._clean_entity(entity2)
            if entity1 and entity2:
                facts.append(TemporalFactTR(subject=entity1, relation=TemporalRelation.SAME_TIME, object_=entity2))
        
        # 去重
        unique_facts = []
        seen = set()
        for fact in facts:
            key = (fact.subject, fact.relation, fact.object_)
            if key not in seen:
                seen.add(key)
                unique_facts.append(fact)
        
        return unique_facts
    
    def check_constraint(
        self,
        constraint: TemporalConstraint,
        task_time: Optional[datetime] = None,
        timestamps: Optional[Dict[str, datetime]] = None,
    ) -> Dict[str, Any]:
        """
        检查时间约束是否满足
        
        Returns:
            dict: {"satisfied": bool, "reason": str, "details": dict}
        """
        result = {
            "satisfied": False,
            "reason": "",
            "details": {
                "constraint": constraint.constraint_type,
                "entity": constraint.entity,
            },
        }
        
        if constraint.constraint_type == "deadline":
            if task_time is None:
                result["reason"] = "未提供任务时间"
                return result
            
            if constraint.deadline is None:
                result["reason"] = "未设置截止日期"
                return result
            
            satisfied = task_time <= constraint.deadline
            result["satisfied"] = satisfied
            result["reason"] = f"任务时间 {task_time.isoformat()} {'在' if satisfied else '超过'}截止日期 {constraint.deadline.isoformat()}"
            result["details"]["task_time"] = task_time.isoformat()
            result["details"]["deadline"] = constraint.deadline.isoformat()
            
        elif constraint.constraint_type == "order":
            if timestamps is None:
                result["reason"] = "未提供时间戳"
                return result
            
            entity_time = timestamps.get(constraint.entity)
            required_before_time = timestamps.get(constraint.required_before)
            
            if entity_time is None:
                result["reason"] = f"未找到实体 {constraint.entity} 的时间戳"
                return result
            
            if required_before_time is None:
                result["reason"] = f"未找到实体 {constraint.required_before} 的时间戳"
                return result
            
            satisfied = entity_time < required_before_time
            result["satisfied"] = satisfied
            result["reason"] = (
                f"实体 {constraint.entity} 的时间 {entity_time.isoformat()} "
                f"{'在' if satisfied else '不在'}{constraint.required_before} 的时间 {required_before_time.isoformat()} 之前"
            )
            result["details"]["entity_time"] = entity_time.isoformat()
            result["details"]["required_before_time"] = required_before_time.isoformat()
            
        else:
            result["reason"] = f"未知约束类型: {constraint.constraint_type}"
        
        return result
    
    def sort_by_temporal_order(self, entities: List[str]) -> List[str]:
        """
        按时序关系排序实体列表
        
        使用拓扑排序，基于 BEFORE 关系构建有向图
        """
        if not entities:
            return []
        
        # 只保留请求的实体
        entity_set = set(entities)
        
        # 构建有向图：A before B -> A -> B
        graph: Dict[str, List[str]] = defaultdict(list)
        in_degree: Dict[str, int] = {e: 0 for e in entities}
        
        # 收集所有 BEFORE 关系
        for (s, o), facts in self._facts.items():
            if s in entity_set and o in entity_set:
                for fact in facts:
                    if fact.relation == TemporalRelation.BEFORE:
                        graph[s].append(o)
                        in_degree[o] = in_degree.get(o, 0) + 1
                    elif fact.relation == TemporalRelation.AFTER:
                        graph[o].append(s)
                        in_degree[s] = in_degree.get(s, 0) + 1
        
        # 拓扑排序（Kahn's algorithm）
        queue = deque([e for e in entities if in_degree.get(e, 0) == 0])
        sorted_result = []
        
        while queue:
            # 按原始顺序处理（稳定排序）
            current = queue.popleft()
            sorted_result.append(current)
            
            for neighbor in graph.get(current, []):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)
        
        # 处理循环或未处理的实体（按原始顺序添加）
        remaining = [e for e in entities if e not in sorted_result]
        sorted_result.extend(remaining)
        
        return sorted_result
    
    def get_contradictions(self) -> List[Dict[str, Any]]:
        """获取所有矛盾"""
        return self._contradictions.copy()
    
    def get_facts(self) -> List[TemporalFactTR]:
        """获取所有事实"""
        all_facts = []
        for facts in self._facts.values():
            all_facts.extend(facts)
        return all_facts
    
    def get_entities(self) -> Set[str]:
        """获取所有实体"""
        return self._entities.copy()
    
    def _detect_conflicts(self, new_fact: TemporalFactTR) -> List[Dict[str, Any]]:
        """检测新事实与现有事实的矛盾"""
        conflicts = []
        
        # 检查直接矛盾：A before B 且 A after B
        direct_facts = self._facts.get((new_fact.subject, new_fact.object_), [])
        for existing_fact in direct_facts:
            if self._is_contradictory(existing_fact, new_fact):
                conflicts.append({
                    "type": "direct_contradiction",
                    "fact1": existing_fact,
                    "fact2": new_fact,
                    "description": f"直接矛盾: {existing_fact.relation.value} vs {new_fact.relation.value}",
                })
        
        # 检查反向矛盾：A before B 且 B before A
        reverse_facts = self._facts.get((new_fact.object_, new_fact.subject), [])
        for existing_fact in reverse_facts:
            if self._is_contradictory_reverse(existing_fact, new_fact):
                conflicts.append({
                    "type": "reverse_contradiction",
                    "fact1": existing_fact,
                    "fact2": new_fact.invert(),
                    "description": f"反向矛盾: {existing_fact.relation.value} vs {new_fact.relation.value}",
                })
        
        # 检查循环矛盾：通过传递闭包检测
        if self._detect_cycle_conflict(new_fact):
            conflicts.append({
                "type": "cycle_contradiction",
                "fact": new_fact,
                "description": f"循环矛盾: 添加 {new_fact.subject} {new_fact.relation.value} {new_fact.object_} 会导致循环",
            })
        
        return conflicts
    
    def _is_contradictory(self, fact1: TemporalFactTR, fact2: TemporalFactTR) -> bool:
        """检查两个事实是否直接矛盾"""
        # 相同主体和客体
        if fact1.subject != fact2.subject or fact1.object_ != fact2.object_:
            return False
        
        # 矛盾关系对
        contradictory_pairs = {
            (TemporalRelation.BEFORE, TemporalRelation.AFTER),
            (TemporalRelation.AFTER, TemporalRelation.BEFORE),
            (TemporalRelation.BEFORE, TemporalRelation.SAME_TIME),
            (TemporalRelation.AFTER, TemporalRelation.SAME_TIME),
            (TemporalRelation.SAME_TIME, TemporalRelation.BEFORE),
            (TemporalRelation.SAME_TIME, TemporalRelation.AFTER),
        }
        
        return (fact1.relation, fact2.relation) in contradictory_pairs
    
    def _is_contradictory_reverse(self, existing_fact: TemporalFactTR, new_fact: TemporalFactTR) -> bool:
        """检查反向关系是否矛盾"""
        # existing_fact: A R1 B (A = new_fact.object_, B = new_fact.subject)
        # new_fact: B R2 A
        
        if existing_fact.subject != new_fact.object_ or existing_fact.object_ != new_fact.subject:
            return False
        
        # 检查反向矛盾
        contradictory_pairs = {
            (TemporalRelation.BEFORE, TemporalRelation.BEFORE),
            (TemporalRelation.AFTER, TemporalRelation.AFTER),
            (TemporalRelation.BEFORE, TemporalRelation.SAME_TIME),
            (TemporalRelation.AFTER, TemporalRelation.SAME_TIME),
            (TemporalRelation.SAME_TIME, TemporalRelation.BEFORE),
            (TemporalRelation.SAME_TIME, TemporalRelation.AFTER),
        }
        
        return (existing_fact.relation, new_fact.relation) in contradictory_pairs
    
    def _detect_cycle_conflict(self, new_fact: TemporalFactTR) -> bool:
        """检测添加新事实是否会导致循环矛盾"""
        # 只对 BEFORE 和 AFTER 关系检测循环
        if new_fact.relation not in {TemporalRelation.BEFORE, TemporalRelation.AFTER}:
            return False
        
        # 临时添加新事实，检查是否形成循环
        # 这是一个简化实现，实际应该用拓扑排序检测循环
        
        # 如果 new_fact 是 A before B，检查是否存在 B ... A 的路径
        if new_fact.relation == TemporalRelation.BEFORE:
            return self._has_path(new_fact.object_, new_fact.subject, {TemporalRelation.BEFORE, TemporalRelation.SAME_TIME})
        
        # 如果 new_fact 是 A after B，检查是否存在 B ... A 的路径（相当于 B before A）
        if new_fact.relation == TemporalRelation.AFTER:
            return self._has_path(new_fact.object_, new_fact.subject, {TemporalRelation.BEFORE, TemporalRelation.SAME_TIME})
        
        return False
    
    def _has_path(
        self,
        start: str,
        end: str,
        allowed_relations: Set[TemporalRelation],
        max_depth: int = 10,
    ) -> bool:
        """检查从 start 到 end 是否存在路径"""
        if start == end:
            return True
        
        visited = {start}
        queue = deque([(start, 0)])
        
        while queue:
            current, depth = queue.popleft()
            
            if depth >= max_depth:
                continue
            
            # 检查从 current 出发的边
            for (s, o), facts in self._facts.items():
                if s == current and o not in visited:
                    for fact in facts:
                        if fact.relation in allowed_relations:
                            if o == end:
                                return True
                            visited.add(o)
                            queue.append((o, depth + 1))
        
        return False
    
    def _compose_relations(
        self,
        fact1: TemporalFactTR,
        fact2: TemporalFactTR,
    ) -> Optional[TemporalFactTR]:
        """组合两个时序关系"""
        # fact1: A R1 B
        # fact2: B R2 C
        # 结果: A R3 C
        
        if fact1.object_ != fact2.subject:
            return None
        
        # 查找组合结果
        composition_key = (fact1.relation, fact2.relation)
        result_relation = self._COMPOSITION_TABLE.get(composition_key)
        
        if result_relation is None:
            return None
        
        # 创建组合事实
        return TemporalFactTR(
            subject=fact1.subject,
            relation=result_relation,
            object_=fact2.object_,
            confidence=min(fact1.confidence, fact2.confidence),
            source=f"composed: {fact1.source} + {fact2.source}" if fact1.source and fact2.source else "",
            metadata={
                "composed": True,
                "fact1": fact1,
                "fact2": fact2,
            },
        )
    
    def __repr__(self) -> str:
        return f"TemporalReasoner(entities={len(self._entities)}, facts={sum(len(f) for f in self._facts.values())})"


def create_temporal_reasoner() -> TemporalReasoner:
    """工厂函数：创建 TemporalReasoner 实例"""
    return TemporalReasoner()