"""
经验知识库

存储和检索技能使用经验，支持经验学习和知识共享
"""

from __future__ import annotations

import datetime
import json
import logging
import threading
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ExperienceType(str, Enum):
    """经验类型"""
    SUCCESS = "success"
    FAILURE = "failure"
    OPTIMIZATION = "optimization"
    WORKAROUND = "workaround"
    PATTERN = "pattern"


@dataclass
class Experience:
    """经验条目"""
    exp_id: str
    skill_id: str
    exp_type: ExperienceType
    context: str  # 使用场景描述
    outcome: str  # 结果描述
    lessons: List[str]  # 经验教训
    created_at: datetime.datetime = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc))
    confidence: float = 1.0  # 置信度 [0, 1]
    usage_count: int = 0
    success_rate: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "exp_id": self.exp_id,
            "skill_id": self.skill_id,
            "exp_type": self.exp_type.value,
            "context": self.context,
            "outcome": self.outcome,
            "lessons": self.lessons,
            "created_at": self.created_at.isoformat(),
            "confidence": self.confidence,
            "usage_count": self.usage_count,
            "success_rate": self.success_rate,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Experience":
        return cls(
            exp_id=data["exp_id"],
            skill_id=data["skill_id"],
            exp_type=ExperienceType(data["exp_type"]),
            context=data["context"],
            outcome=data["outcome"],
            lessons=data.get("lessons", []),
            created_at=datetime.datetime.fromisoformat(data["created_at"]) if "created_at" in data else datetime.datetime.now(datetime.timezone.utc),
            confidence=data.get("confidence", 1.0),
            usage_count=data.get("usage_count", 0),
            success_rate=data.get("success_rate", 0.0),
            metadata=data.get("metadata", {}),
        )


class ExperienceKnowledgeBase:
    """
    经验知识库
    
    存储、检索和管理技能使用经验，支持：
    - 经验记录和检索
    - 按技能/类型查询
    - 相似经验搜索
    - 经验统计
    """
    
    def __init__(self, data_dir: Optional[Path] = None):
        """
        Args:
            data_dir: 数据存储目录，None 则使用内存存储
        """
        self._lock = threading.RLock()
        self._experiences: Dict[str, Experience] = {}
        self._skill_index: Dict[str, List[str]] = {}  # skill_id -> [exp_ids]
        self._type_index: Dict[ExperienceType, List[str]] = {}
        self._data_dir = Path(data_dir) if data_dir else None
        
        if self._data_dir:
            self._data_dir.mkdir(parents=True, exist_ok=True)
            self._load_from_disk()
    
    def add_experience(
        self,
        skill_id: str,
        exp_type: ExperienceType,
        context: str,
        outcome: str,
        lessons: List[str],
        confidence: float = 1.0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Experience:
        """
        添加经验
        
        Args:
            skill_id: 技能ID
            exp_type: 经验类型
            context: 使用场景
            outcome: 结果
            lessons: 经验教训
            confidence: 置信度
            metadata: 额外元数据
            
        Returns:
            创建的经验条目
        """
        exp_id = f"{skill_id}_{datetime.datetime.now().strftime('%Y%m%d%H%M%S%f')}"
        
        exp = Experience(
            exp_id=exp_id,
            skill_id=skill_id,
            exp_type=exp_type,
            context=context,
            outcome=outcome,
            lessons=lessons,
            confidence=confidence,
            metadata=metadata or {},
        )
        
        with self._lock:
            self._experiences[exp_id] = exp
            
            # 更新索引
            if skill_id not in self._skill_index:
                self._skill_index[skill_id] = []
            self._skill_index[skill_id].append(exp_id)
            
            if exp_type not in self._type_index:
                self._type_index[exp_type] = []
            self._type_index[exp_type].append(exp_id)
        
        self._save_to_disk()
        logger.debug(f"Added experience '{exp_id}' for skill '{skill_id}'")
        return exp
    
    def get_experience(self, exp_id: str) -> Optional[Experience]:
        """获取经验"""
        with self._lock:
            return self._experiences.get(exp_id)
    
    def search_by_skill(
        self,
        skill_id: str,
        exp_type: Optional[ExperienceType] = None,
        limit: int = 20,
    ) -> List[Experience]:
        """按技能搜索经验"""
        with self._lock:
            exp_ids = self._skill_index.get(skill_id, [])
            
            if exp_type:
                type_ids = set(self._type_index.get(exp_type, []))
                exp_ids = [eid for eid in exp_ids if eid in type_ids]
            
            exps = [self._experiences[eid] for eid in exp_ids if eid in self._experiences]
            exps.sort(key=lambda e: e.created_at, reverse=True)
            return exps[:limit]
    
    def search_by_context(
        self,
        keywords: List[str],
        skill_id: Optional[str] = None,
        limit: int = 10,
    ) -> List[Experience]:
        """
        按上下文关键词搜索经验
        
        Args:
            keywords: 关键词列表
            skill_id: 可选的技能过滤
            limit: 返回数量限制
            
        Returns:
            匹配的经验列表
        """
        with self._lock:
            candidates = self._experiences.values()
            
            if skill_id:
                exp_ids = set(self._skill_index.get(skill_id, []))
                candidates = [e for e in candidates if e.exp_id in exp_ids]
            
            # 简单的关键词匹配
            scored = []
            for exp in candidates:
                score = 0
                text = f"{exp.context} {exp.outcome} {' '.join(exp.lessons)}".lower()
                for kw in keywords:
                    if kw.lower() in text:
                        score += 1
                if score > 0:
                    scored.append((score, exp))
            
            scored.sort(key=lambda x: x[0], reverse=True)
            return [exp for _, exp in scored[:limit]]
    
    def record_outcome(self, exp_id: str, success: bool) -> bool:
        """记录经验使用结果"""
        with self._lock:
            exp = self._experiences.get(exp_id)
            if exp is None:
                return False
            
            exp.usage_count += 1
            # 更新成功率（指数移动平均）
            alpha = 0.1
            exp.success_rate = alpha * (1.0 if success else 0.0) + (1 - alpha) * exp.success_rate
            
            self._save_to_disk()
            return True
    
    def get_skill_stats(self, skill_id: str) -> Dict[str, Any]:
        """获取技能经验统计"""
        with self._lock:
            exp_ids = self._skill_index.get(skill_id, [])
            exps = [self._experiences[eid] for eid in exp_ids if eid in self._experiences]
            
            if not exps:
                return {"skill_id": skill_id, "total_experiences": 0}
            
            type_counts = {}
            total_confidence = 0
            total_success_rate = 0
            
            for exp in exps:
                type_counts[exp.exp_type.value] = type_counts.get(exp.exp_type.value, 0) + 1
                total_confidence += exp.confidence
                total_success_rate += exp.success_rate
            
            return {
                "skill_id": skill_id,
                "total_experiences": len(exps),
                "by_type": type_counts,
                "avg_confidence": total_confidence / len(exps),
                "avg_success_rate": total_success_rate / len(exps),
                "total_usage": sum(e.usage_count for e in exps),
            }
    
    def get_stats(self) -> Dict[str, Any]:
        """获取全局统计"""
        with self._lock:
            return {
                "total_experiences": len(self._experiences),
                "skills_with_experience": len(self._skill_index),
                "by_type": {
                    t.value: len(ids) for t, ids in self._type_index.items()
                },
            }
    
    def _save_to_disk(self) -> None:
        """保存到磁盘"""
        if not self._data_dir:
            return
        
        try:
            data = {
                "experiences": {eid: exp.to_dict() for eid, exp in self._experiences.items()},
                "skill_index": self._skill_index,
                "type_index": {t.value: ids for t, ids in self._type_index.items()},
            }
            filepath = self._data_dir / "experience_kb.json"
            filepath.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning(f"Failed to save experience KB: {e}")
    
    def _load_from_disk(self) -> None:
        """从磁盘加载"""
        if not self._data_dir:
            return
        
        filepath = self._data_dir / "experience_kb.json"
        if not filepath.exists():
            return
        
        try:
            data = json.loads(filepath.read_text(encoding="utf-8"))
            
            for eid, exp_data in data.get("experiences", {}).items():
                self._experiences[eid] = Experience.from_dict(exp_data)
            
            self._skill_index = data.get("skill_index", {})
            self._type_index = {
                ExperienceType(t): ids for t, ids in data.get("type_index", {}).items()
            }
            
            logger.info(f"Loaded {len(self._experiences)} experiences from disk")
        except Exception as e:
            logger.warning(f"Failed to load experience KB: {e}")


# 全局单例
_experience_kb: Optional[ExperienceKnowledgeBase] = None
_kb_lock = threading.Lock()


def get_experience_knowledge_base(data_dir: Optional[Path] = None) -> ExperienceKnowledgeBase:
    """获取全局经验知识库单例"""
    global _experience_kb
    if _experience_kb is None:
        with _kb_lock:
            if _experience_kb is None:
                _experience_kb = ExperienceKnowledgeBase(data_dir=data_dir)
    return _experience_kb


def reset_experience_knowledge_base() -> None:
    """重置全局经验知识库（用于测试）"""
    global _experience_kb
    with _kb_lock:
        _experience_kb = None
