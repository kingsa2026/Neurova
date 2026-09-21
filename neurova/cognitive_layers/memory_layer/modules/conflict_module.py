"""
ConflictModule — 冲突检测模块

检测和处理记忆之间的冲突。

**判据不在这里**：记忆侧冲突的唯一判据是
`memory_layer.conflict.judgeClauseConflict`（同一命题的否证 / 同一对象的矛盾取值）。
本模块此前自持一套"否定词子串包含 + 词重叠 < 0.3 算不一致"的判法，是同一根因的
第二份实现——中文没有词界，`split()` 让每个子句各成一个词元，任意两句都算"不一致"，
于是"正常/故障"被报成 inconsistency 而与"天气不错/天气很好"同级噪声。
一个根因两处实现，修一处等于没修，故收口为一处。
"""

from __future__ import annotations

from neurova.core.logger import get_logger
import threading
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

logger = get_logger(__name__)


class ConflictType(str, Enum):
    """冲突类型"""

    CONTRADICTION = "contradiction"  # 矛盾
    INCONSISTENCY = "inconsistency"  # 不一致
    OUTDATED = "outdated"  # 过时
    DUPLICATE = "duplicate"  # 重复


class ConflictResolution(str, Enum):
    """冲突解决策略"""

    KEEP_NEWEST = "keep_newest"
    KEEP_OLDEST = "keep_oldest"
    KEEP_HIGHEST_CONFIDENCE = "keep_highest_confidence"
    MERGE = "merge"
    MANUAL = "manual"


@dataclass
class Conflict:
    """冲突记录"""

    conflict_id: str
    memory_id_1: str
    memory_id_2: str
    conflict_type: ConflictType
    description: str
    confidence: float  # 冲突置信度 [0, 1]
    resolution: Optional[ConflictResolution] = None
    resolved: bool = False
    # 依据：凭哪两句、哪条规则认定的。为空即不得自动裁决（与底座侧
    # KnowledgeConflictJudge 的 policy_basis 同一条纪律）。
    basis: str = ""
    source: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "conflict_id": self.conflict_id,
            "memory_id_1": self.memory_id_1,
            "memory_id_2": self.memory_id_2,
            "conflict_type": self.conflict_type.value,
            "description": self.description,
            "confidence": self.confidence,
            "resolution": self.resolution.value if self.resolution else None,
            "resolved": self.resolved,
            "basis": self.basis,
            "source": self.source,
        }


class ConflictModule:
    """
    冲突检测模块

    检测和处理记忆之间的冲突，支持：
    - 矛盾检测
    - 不一致检测
    - 过时检测
    - 自动/手动解决
    """

    def __init__(self, auto_resolve: bool = False):
        """
        Args:
            auto_resolve: 是否自动解决冲突
        """
        self._auto_resolve = auto_resolve
        self._lock = threading.RLock()
        self._initialized = False

        # 冲突存储
        self._conflicts: Dict[str, Conflict] = {}  # conflict_id -> Conflict
        self._memory_conflicts: Dict[str, List[str]] = {}  # memory_id -> [conflict_ids]

    @property
    def name(self) -> str:
        """模块名称"""
        return "conflict_module"

    def init(self) -> bool:
        """初始化模块"""
        self._initialized = True
        logger.info("ConflictModule initialized")
        return True

    def shutdown(self) -> None:
        """关闭模块"""
        self._initialized = False
        logger.info("ConflictModule shutdown")

    def detect_conflict(
        self,
        memory_id_1: str,
        content_1: str,
        memory_id_2: str,
        content_2: str,
    ) -> Optional[Conflict]:
        """
        检测两个记忆之间的冲突

        Args:
            memory_id_1: 记忆1 ID
            content_1: 记忆1 内容
            memory_id_2: 记忆2 ID
            content_2: 记忆2 内容

        Returns:
            冲突记录，无冲突返回 None
        """
        # 判据收口到记忆侧唯一实现（同一命题的否证 / 同一对象的矛盾取值）
        from neurova.cognitive_layers.memory_layer.conflict import judgeClauseConflict

        if content_1.strip() == content_2.strip():
            conflict_type = ConflictType.DUPLICATE
            basis = "完全重复的内容"
            confidence = 1.0
        else:
            hit = judgeClauseConflict(content_1, content_2)
            if hit is None:
                return None
            kind, _left, _right, basis = hit
            conflict_type = ConflictType.CONTRADICTION
            confidence = 0.7 if kind == "negation_conflict" else 0.5

        # 创建冲突记录
        conflict_id = f"conflict_{memory_id_1}_{memory_id_2}"
        conflict = Conflict(
            conflict_id=conflict_id,
            memory_id_1=memory_id_1,
            memory_id_2=memory_id_2,
            conflict_type=conflict_type,
            description=basis,
            confidence=confidence,
            basis=basis,
        )

        # 存储冲突
        with self._lock:
            self._conflicts[conflict_id] = conflict

            if memory_id_1 not in self._memory_conflicts:
                self._memory_conflicts[memory_id_1] = []
            self._memory_conflicts[memory_id_1].append(conflict_id)

            if memory_id_2 not in self._memory_conflicts:
                self._memory_conflicts[memory_id_2] = []
            self._memory_conflicts[memory_id_2].append(conflict_id)

        # 自动解决
        if self._auto_resolve:
            self._auto_resolve_conflict(conflict)

        logger.info("Detected conflict: %s (%s)", conflict_id, conflict_type.value)
        return conflict

    def record(
        self,
        memory_id_1: str,
        memory_id_2: str,
        conflict_type: ConflictType,
        basis: str,
        *,
        confidence: float = 0.7,
        source: str = "",
    ) -> Optional[Conflict]:
        """把**已认定**的冲突落账；依据为空不收。

        依据是冲突账的唯一价值：没有"凭哪两句、哪条规则认定的"，这条账就只是
        "发生了点什么"，下游既判不出哪条为准、也无从复核。故 basis 空即拒绝落账
        （诚实边界：宁可不记，也不记一条读不懂的账）。
        """
        basis = str(basis or "").strip()
        if not basis:
            return None
        conflict_id = f"conflict_{memory_id_1}_{memory_id_2}"
        with self._lock:
            existing = self._conflicts.get(conflict_id)
            if existing is not None:
                existing.basis = basis
                existing.source = source or existing.source
                return existing
            conflict = Conflict(
                conflict_id=conflict_id,
                memory_id_1=memory_id_1,
                memory_id_2=memory_id_2,
                conflict_type=conflict_type,
                description=basis,
                confidence=confidence,
                basis=basis,
                source=source,
            )
            self._conflicts[conflict_id] = conflict
            for mid in (memory_id_1, memory_id_2):
                self._memory_conflicts.setdefault(mid, []).append(conflict_id)
        return conflict

    def resolve_conflict(
        self,
        conflict_id: str,
        resolution: ConflictResolution,
    ) -> bool:
        """
        解决冲突

        Args:
            conflict_id: 冲突ID
            resolution: 解决策略

        Returns:
            是否解决成功
        """
        with self._lock:
            conflict = self._conflicts.get(conflict_id)
            if conflict is None:
                return False

            conflict.resolution = resolution
            conflict.resolved = True

            logger.info("Resolved conflict '%s' with strategy: %s", conflict_id, resolution.value)
            return True

    def get_conflicts(
        self,
        memory_id: Optional[str] = None,
        conflict_type: Optional[ConflictType] = None,
        resolved: Optional[bool] = None,
        source: Optional[str] = None,
    ) -> List[Conflict]:
        """获取冲突列表"""
        with self._lock:
            conflicts = list(self._conflicts.values())

        if memory_id:
            conflict_ids = set(self._memory_conflicts.get(memory_id, []))
            conflicts = [c for c in conflicts if c.conflict_id in conflict_ids]

        if conflict_type:
            conflicts = [c for c in conflicts if c.conflict_type == conflict_type]

        if resolved is not None:
            conflicts = [c for c in conflicts if c.resolved == resolved]

        if source:
            conflicts = [c for c in conflicts if c.source == source]

        return conflicts

    def get_unresolved_conflicts(self) -> List[Conflict]:
        """获取未解决的冲突"""
        return self.get_conflicts(resolved=False)

    def remove_conflict(self, conflict_id: str) -> bool:
        """移除冲突记录"""
        with self._lock:
            conflict = self._conflicts.pop(conflict_id, None)
            if conflict is None:
                return False

            # 清理索引
            for mid in [conflict.memory_id_1, conflict.memory_id_2]:
                if mid in self._memory_conflicts:
                    self._memory_conflicts[mid] = [cid for cid in self._memory_conflicts[mid] if cid != conflict_id]

            return True

    def remove_memory_conflicts(self, memory_id: str) -> int:
        """移除与记忆相关的所有冲突"""
        with self._lock:
            conflict_ids = self._memory_conflicts.pop(memory_id, [])
            count = 0

            for cid in conflict_ids:
                if cid in self._conflicts:
                    del self._conflicts[cid]
                    count += 1

            return count

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self._lock:
            type_counts = {}
            resolved_count = 0

            for conflict in self._conflicts.values():
                type_counts[conflict.conflict_type.value] = type_counts.get(conflict.conflict_type.value, 0) + 1
                if conflict.resolved:
                    resolved_count += 1

            return {
                "total_conflicts": len(self._conflicts),
                "resolved": resolved_count,
                "unresolved": len(self._conflicts) - resolved_count,
                "by_type": type_counts,
                "memories_with_conflicts": len(self._memory_conflicts),
            }

    def _auto_resolve_conflict(self, conflict: Conflict) -> None:
        """自动解决冲突"""
        # 默认策略：保留最新的
        self.resolve_conflict(conflict.conflict_id, ConflictResolution.KEEP_NEWEST)
