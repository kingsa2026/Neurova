"""
记忆冲突检测系统 - Memory Conflict Detection

检测记忆之间的矛盾和冲突，提供自动标记和解决建议。

冲突类型：
1. 事实冲突 - 两个记忆陈述了矛盾的事实
2. 时间冲突 - 时间线或事件顺序矛盾
3. 语义冲突 - 语义上相互否定的记忆
4. 规则冲突 - 违反已有规则的记忆
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Set
import logging
import re
import uuid

from .models import Memory

logger = logging.getLogger(__name__)


# ────── Enums ──────

class ConflictLevel(Enum):
    """冲突级别"""
    LOW = "low"           # 低级别冲突，可能只是表述差异
    MEDIUM = "medium"     # 中级别冲突，需要关注
    HIGH = "high"         # 高级别冲突，明确矛盾
    CRITICAL = "critical" # 严重冲突，可能影响系统一致性


class ConflictType(Enum):
    """冲突类型"""
    FACT = "fact"         # 事实冲突
    TIME = "time"         # 时间冲突
    SEMANTIC = "semantic" # 语义冲突
    RULE = "rule"         # 规则冲突
    NEGATION = "negation" # 否定冲突
    NUMBER = "number"     # 数字冲突
    ENTITY = "entity"     # 实体冲突


# ────── Data Models ──────

@dataclass
class ConflictMarker:
    """冲突标记"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    conflict_type: ConflictType = ConflictType.SEMANTIC
    level: ConflictLevel = ConflictLevel.MEDIUM
    memory_ids: List[str] = field(default_factory=list)
    description: str = ""
    evidence: List[str] = field(default_factory=list)
    confidence: float = 0.0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    resolved: bool = False
    resolution_notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "conflict_type": self.conflict_type.value,
            "level": self.level.value,
            "memory_ids": self.memory_ids,
            "description": self.description,
            "evidence": self.evidence,
            "confidence": self.confidence,
            "created_at": self.created_at.isoformat(),
            "resolved": self.resolved,
            "resolution_notes": self.resolution_notes,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ConflictMarker":
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            conflict_type=ConflictType(data.get("conflict_type", "semantic")),
            level=ConflictLevel(data.get("level", "medium")),
            memory_ids=data.get("memory_ids", []),
            description=data.get("description", ""),
            evidence=data.get("evidence", []),
            confidence=data.get("confidence", 0.0),
            resolved=data.get("resolved", False),
            resolution_notes=data.get("resolution_notes", ""),
        )


@dataclass
class ConflictCheckResult:
    """冲突检查结果"""
    has_conflict: bool = False
    conflicts: List[ConflictMarker] = field(default_factory=list)
    checked_memories: int = 0
    check_duration_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "has_conflict": self.has_conflict,
            "conflicts": [c.to_dict() for c in self.conflicts],
            "checked_memories": self.checked_memories,
            "check_duration_ms": self.check_duration_ms,
        }


# ────── Main Detector ──────

class MemoryConflictDetector:
    """
    记忆冲突检测器
    
    检测记忆之间的矛盾和冲突，提供自动标记和解决建议。
    """
    
    def __init__(self):
        """初始化冲突检测器"""
        # 否定词模式
        self._negation_patterns = [
            re.compile(r'\b不[是能会要对愿]\b', re.IGNORECASE),
            re.compile(r'\b没[有在]\b', re.IGNORECASE),
            re.compile(r'\b非[常法]\b', re.IGNORECASE),
            re.compile(r'\b无[法效论]\b', re.IGNORECASE),
            re.compile(r'\b未[曾必]\b', re.IGNORECASE),
            re.compile(r'\b别[人说]\b', re.IGNORECASE),
            re.compile(r'\b否认\b', re.IGNORECASE),
            re.compile(r'\b否定\b', re.IGNORECASE),
            re.compile(r'\b错误\b', re.IGNORECASE),
            re.compile(r'\b虚假\b', re.IGNORECASE),
            re.compile(r'\bnot\b', re.IGNORECASE),
            re.compile(r'\bno\b', re.IGNORECASE),
            re.compile(r'\bnever\b', re.IGNORECASE),
            re.compile(r'\bneither\b', re.IGNORECASE),
            re.compile(r'\bnor\b', re.IGNORECASE),
            re.compile(r'\bnone\b', re.IGNORECASE),
            re.compile(r'\bnobody\b', re.IGNORECASE),
            re.compile(r'\bnothing\b', re.IGNORECASE),
            re.compile(r'\bnowhere\b', re.IGNORECASE),
            re.compile(r'\bcannot\b', re.IGNORECASE),
            re.compile(r"\bcan't\b", re.IGNORECASE),
            re.compile(r"\bdon't\b", re.IGNORECASE),
            re.compile(r"\bdoesn't\b", re.IGNORECASE),
            re.compile(r"\bdidn't\b", re.IGNORECASE),
            re.compile(r"\bwon't\b", re.IGNORECASE),
            re.compile(r"\bwouldn't\b", re.IGNORECASE),
            re.compile(r"\bshouldn't\b", re.IGNORECASE),
            re.compile(r"\bisn't\b", re.IGNORECASE),
            re.compile(r"\baren't\b", re.IGNORECASE),
            re.compile(r"\bwasn't\b", re.IGNORECASE),
            re.compile(r"\bweren't\b", re.IGNORECASE),
        ]
        
        # 数字提取模式
        self._number_pattern = re.compile(r'\b\d+(?:\.\d+)?\b')
        
        # 时间提取模式
        self._time_patterns = [
            re.compile(r'\b\d{4}[-/]\d{1,2}[-/]\d{1,2}\b'),
            re.compile(r'\b\d{1,2}[-/]\d{1,2}[-/]\d{4}\b'),
            re.compile(r'\b\d{1,2}:\d{2}(?::\d{2})?\b'),
            re.compile(r'\b[一二三四五六七八九十]+年[一二三四五六七八九十]+月\b'),
            re.compile(r'\b\d+年\d+月\d+日\b'),
            re.compile(r'\b昨天|今天|明天|前天|后天\b'),
            re.compile(r'\blast|this|next\b', re.IGNORECASE),
        ]
        
        # 实体提取模式（简化版）
        self._entity_patterns = [
            re.compile(r'《([^》]+)》'),  # 书名
            re.compile(r'"([^"]+)"'),     # 引号内容
            re.compile(r"'([^']+)'"),     # 单引号内容
            re.compile(r'【([^】]+)】'),   # 方括号内容
        ]
        
        logger.info("MemoryConflictDetector 初始化完成")
    
    def check_conflict(self, memory1: Memory, memory2: Memory) -> ConflictCheckResult:
        """
        检查两个记忆之间的冲突
        
        Args:
            memory1: 第一个记忆
            memory2: 第二个记忆
            
        Returns:
            冲突检查结果
        """
        import time
        start_time = time.time()
        
        conflicts = []
        
        # 检查各种类型的冲突
        negation_conflict = self._check_negation_conflict(memory1, memory2)
        if negation_conflict:
            conflicts.append(negation_conflict)
        
        number_conflict = self._check_number_conflict(memory1, memory2)
        if number_conflict:
            conflicts.append(number_conflict)
        
        time_conflict = self._check_time_conflict(memory1, memory2)
        if time_conflict:
            conflicts.append(time_conflict)
        
        entity_conflict = self._check_entity_conflict(memory1, memory2)
        if entity_conflict:
            conflicts.append(entity_conflict)
        
        duration_ms = (time.time() - start_time) * 1000
        
        return ConflictCheckResult(
            has_conflict=len(conflicts) > 0,
            conflicts=conflicts,
            checked_memories=2,
            check_duration_ms=duration_ms,
        )
    
    def _detect_conflict(self, memory1: Memory, memory2: Memory) -> Optional[ConflictMarker]:
        """检测主要冲突（综合检测）"""
        # 首先检查内容相似度
        similarity = self._calculate_similarity(memory1.content, memory2.content)
        
        # 如果内容完全不同，不太可能是冲突
        if similarity < 0.3:
            return None
        
        # 检查否定冲突
        negation_conflict = self._check_negation_conflict(memory1, memory2)
        if negation_conflict:
            return negation_conflict
        
        # 检查数字冲突
        number_conflict = self._check_number_conflict(memory1, memory2)
        if number_conflict:
            return number_conflict
        
        return None
    
    def _check_negation_conflict(self, memory1: Memory, memory2: Memory) -> Optional[ConflictMarker]:
        """检查否定冲突"""
        content1 = memory1.content
        content2 = memory2.content
        
        # 提取否定词
        negations1 = self._extract_negations(content1)
        negations2 = self._extract_negations(content2)
        
        # 如果一个有否定词，另一个没有，可能是冲突
        if (negations1 and not negations2) or (negations2 and not negations1):
            # 计算内容相似度
            similarity = self._calculate_similarity(content1, content2)
            
            if similarity > 0.6:
                # 提取核心内容（去掉否定词）
                core1 = self._extract_core_content(content1)
                core2 = self._extract_core_content(content2)
                
                # 如果核心内容相似，说明是同一主题的不同表述
                core_similarity = self._calculate_similarity(core1, core2)
                
                if core_similarity > 0.5:
                    level = ConflictLevel.HIGH if similarity > 0.8 else ConflictLevel.MEDIUM
                    
                    return ConflictMarker(
                        conflict_type=ConflictType.NEGATION,
                        level=level,
                        memory_ids=[memory1.id, memory2.id],
                        description=f"否定冲突：一个记忆包含否定，另一个不包含",
                        evidence=[
                            f"记忆1: {content1[:100]}...",
                            f"记忆2: {content2[:100]}...",
                            f"否定词: {negations1 if negations1 else negations2}",
                        ],
                        confidence=similarity,
                    )
        
        return None
    
    def _check_number_conflict(self, memory1: Memory, memory2: Memory) -> Optional[ConflictMarker]:
        """检查数字冲突"""
        numbers1 = self._extract_numbers(memory1.content)
        numbers2 = self._extract_numbers(memory2.content)
        
        if not numbers1 or not numbers2:
            return None
        
        # 获取数字上下文
        contexts1 = self._get_number_contexts(memory1.content, numbers1)
        contexts2 = self._get_number_contexts(memory2.content, numbers2)
        
        # 查找冲突的数字对
        conflicting_pairs = []
        for ctx1, num1 in contexts1:
            for ctx2, num2 in contexts2:
                # 如果上下文相似但数字不同
                ctx_similarity = self._calculate_similarity(ctx1, ctx2)
                if ctx_similarity > 0.7 and num1 != num2:
                    conflicting_pairs.append((ctx1, num1, ctx2, num2, ctx_similarity))
        
        if conflicting_pairs:
            # 找到最相似的冲突对
            best_pair = max(conflicting_pairs, key=lambda x: x[4])
            ctx1, num1, ctx2, num2, similarity = best_pair
            
            level = ConflictLevel.HIGH if similarity > 0.9 else ConflictLevel.MEDIUM
            
            return ConflictMarker(
                conflict_type=ConflictType.NUMBER,
                level=level,
                memory_ids=[memory1.id, memory2.id],
                description=f"数字冲突：相同上下文中的数字不同 ({num1} vs {num2})",
                evidence=[
                    f"上下文1: {ctx1}",
                    f"数字1: {num1}",
                    f"上下文2: {ctx2}",
                    f"数字2: {num2}",
                ],
                confidence=similarity,
            )
        
        return None
    
    def _check_time_conflict(self, memory1: Memory, memory2: Memory) -> Optional[ConflictMarker]:
        """检查时间冲突"""
        times1 = self._extract_times(memory1.content)
        times2 = self._extract_times(memory2.content)
        
        if not times1 or not times2:
            return None
        
        # 检查是否有矛盾的时间线
        # 这里简化处理：如果两个记忆描述相同事件但时间不同
        similarity = self._calculate_similarity(memory1.content, memory2.content)
        
        if similarity > 0.6:
            # 提取核心事件描述
            core1 = self._extract_core_content(memory1.content)
            core2 = self._extract_core_content(memory2.content)
            
            core_similarity = self._calculate_similarity(core1, core2)
            
            if core_similarity > 0.7:
                # 检查时间是否不同
                time_diff = self._compare_times(times1, times2)
                
                if time_diff and abs(time_diff) > 3600:  # 超过1小时的差异
                    level = ConflictLevel.HIGH if abs(time_diff) > 86400 else ConflictLevel.MEDIUM  # 超过1天为高级别
                    
                    return ConflictMarker(
                        conflict_type=ConflictType.TIME,
                        level=level,
                        memory_ids=[memory1.id, memory2.id],
                        description=f"时间冲突：相同事件的时间不同",
                        evidence=[
                            f"记忆1时间: {times1}",
                            f"记忆2时间: {times2}",
                            f"时间差: {abs(time_diff)}秒",
                        ],
                        confidence=similarity,
                    )
        
        return None
    
    def _check_entity_conflict(self, memory1: Memory, memory2: Memory) -> Optional[ConflictMarker]:
        """检查实体冲突"""
        entities1 = self._extract_entities(memory1.content)
        entities2 = self._extract_entities(memory2.content)
        
        if not entities1 or not entities2:
            return None
        
        # 检查相同上下文中的实体是否不同
        # 这里简化处理：如果两个记忆高度相似但关键实体不同
        similarity = self._calculate_similarity(memory1.content, memory2.content)
        
        if similarity > 0.7:
            # 找到不同的实体
            diff_entities1 = entities1 - entities2
            diff_entities2 = entities2 - entities1
            
            if diff_entities1 and diff_entities2:
                # 提取核心内容
                core1 = self._extract_core_content(memory1.content)
                core2 = self._extract_core_content(memory2.content)
                
                core_similarity = self._calculate_similarity(core1, core2)
                
                if core_similarity > 0.6:
                    level = ConflictLevel.MEDIUM
                    
                    return ConflictMarker(
                        conflict_type=ConflictType.ENTITY,
                        level=level,
                        memory_ids=[memory1.id, memory2.id],
                        description=f"实体冲突：相同上下文中的实体不同",
                        evidence=[
                            f"记忆1独有实体: {diff_entities1}",
                            f"记忆2独有实体: {diff_entities2}",
                        ],
                        confidence=similarity,
                    )
        
        return None
    
    def _extract_negations(self, text: str) -> List[str]:
        """提取否定词"""
        negations = []
        for pattern in self._negation_patterns:
            matches = pattern.findall(text)
            negations.extend(matches)
        return negations
    
    def _extract_facts(self, text: str) -> List[str]:
        """提取事实（简化版）"""
        # 简单分割句子
        sentences = re.split(r'[。！？.!?]', text)
        return [s.strip() for s in sentences if s.strip()]
    
    def _is_contradictory(self, fact1: str, fact2: str) -> bool:
        """判断两个事实是否矛盾（简化版）"""
        # 检查否定词
        negations1 = self._extract_negations(fact1)
        negations2 = self._extract_negations(fact2)
        
        # 如果一个有否定词，另一个没有
        if (negations1 and not negations2) or (negations2 and not negations1):
            # 计算相似度
            similarity = self._calculate_similarity(fact1, fact2)
            return similarity > 0.7
        
        return False
    
    def _extract_core_content(self, text: str) -> str:
        """提取核心内容（去掉否定词和修饰词）"""
        # 去掉否定词
        core = text
        for pattern in self._negation_patterns:
            core = pattern.sub('', core)
        
        # 去掉多余空格
        core = re.sub(r'\s+', ' ', core).strip()
        
        return core
    
    def _extract_numbers(self, text: str) -> List[str]:
        """提取数字"""
        return self._number_pattern.findall(text)
    
    def _get_number_contexts(self, text: str, numbers: List[str]) -> List[Tuple[str, str]]:
        """获取数字及其上下文"""
        contexts = []
        for number in numbers:
            # 查找数字在文本中的位置
            idx = text.find(number)
            if idx >= 0:
                # 获取前后20个字符作为上下文
                start = max(0, idx - 20)
                end = min(len(text), idx + len(number) + 20)
                context = text[start:end]
                contexts.append((context, number))
        return contexts
    
    def _extract_times(self, text: str) -> List[str]:
        """提取时间表达式"""
        times = []
        for pattern in self._time_patterns:
            matches = pattern.findall(text)
            times.extend(matches)
        return times
    
    def _extract_entities(self, text: str) -> Set[str]:
        """提取实体"""
        entities = set()
        for pattern in self._entity_patterns:
            matches = pattern.findall(text)
            entities.update(matches)
        return entities
    
    def _calculate_similarity(self, text1: str, text2: str) -> float:
        """计算两个文本的相似度（简化版）"""
        # 简单使用字符重叠率
        if not text1 or not text2:
            return 0.0
        
        # 转换为小写
        text1_lower = text1.lower()
        text2_lower = text2.lower()
        
        # 计算字符集合
        set1 = set(text1_lower)
        set2 = set(text2_lower)
        
        # 计算交集和并集
        intersection = len(set1.intersection(set2))
        union = len(set1.union(set2))
        
        if union == 0:
            return 0.0
        
        return intersection / union
    
    def _compare_times(self, times1: List[str], times2: List[str]) -> Optional[float]:
        """比较时间差异（返回秒数，简化版）"""
        # 这里简化处理，实际应该解析时间字符串
        # 假设时间格式为 "YYYY-MM-DD" 或 "HH:MM"
        
        # 简单返回第一个时间对的差异
        if times1 and times2:
            # 尝试解析时间
            try:
                # 尝试解析日期格式
                for t1 in times1:
                    for t2 in times2:
                        try:
                            dt1 = datetime.strptime(t1, "%Y-%m-%d")
                            dt2 = datetime.strptime(t2, "%Y-%m-%d")
                            return (dt1 - dt2).total_seconds()
                        except ValueError:
                            continue
                
                # 尝试解析时间格式
                for t1 in times1:
                    for t2 in times2:
                        try:
                            dt1 = datetime.strptime(t1, "%H:%M")
                            dt2 = datetime.strptime(t2, "%H:%M")
                            return (dt1 - dt2).total_seconds()
                        except ValueError:
                            continue
            except Exception:
                pass
        
        return None
    
    def _generate_id(self) -> str:
        """生成唯一ID"""
        return str(uuid.uuid4())
    
    def resolve_conflict(self, conflict: ConflictMarker, resolution: str) -> ConflictMarker:
        """
        解决冲突
        
        Args:
            conflict: 冲突标记
            resolution: 解决方案
            
        Returns:
            更新后的冲突标记
        """
        conflict.resolved = True
        conflict.resolution_notes = resolution
        return conflict
    
    def generate_suggestion(self, conflict: ConflictMarker) -> str:
        """
        生成冲突解决建议
        
        Args:
            conflict: 冲突标记
            
        Returns:
            建议文本
        """
        suggestions = []
        
        if conflict.conflict_type == ConflictType.NEGATION:
            suggestions.append("建议检查哪个记忆是正确的，保留正确的记忆，修正或删除错误的记忆。")
            suggestions.append("如果两个记忆描述的是不同时间的情况，请更新时间信息。")
        
        elif conflict.conflict_type == ConflictType.NUMBER:
            suggestions.append("建议核实正确的数字，更新错误的记忆。")
            suggestions.append("如果数字变化是时间相关的，请添加时间上下文。")
        
        elif conflict.conflict_type == ConflictType.TIME:
            suggestions.append("建议确认正确的时间线，更新错误的时间信息。")
            suggestions.append("如果时间差异是合理的（如不同年份的相同事件），请添加更多上下文。")
        
        elif conflict.conflict_type == ConflictType.ENTITY:
            suggestions.append("建议确认正确的实体，更新错误的记忆。")
            suggestions.append("如果实体变化是合理的（如更名），请添加变化说明。")
        
        else:
            suggestions.append("建议人工审核这两个记忆，确定哪个是正确的。")
        
        # 根据冲突级别添加额外建议
        if conflict.level == ConflictLevel.CRITICAL:
            suggestions.insert(0, "⚠️ 严重冲突：请立即处理，可能影响系统一致性。")
        elif conflict.level == ConflictLevel.HIGH:
            suggestions.insert(0, "⚠️ 高级别冲突：建议优先处理。")
        
        return "\n".join(suggestions)