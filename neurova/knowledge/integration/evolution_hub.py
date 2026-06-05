"""Evolution hub — knowledge gap analysis, learning records, evolution progress."""

import datetime
import json
import logging
import threading
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional


logger = logging.getLogger(__name__)


def _new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex}" if prefix else uuid.uuid4().hex


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class GapPriority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class LearningStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class KnowledgeGap:
    id: str
    topic: str
    priority: str = GapPriority.LOW.value
    access_count: int = 0
    knowledge_available: bool = False
    detected_at: str = ""


@dataclass
class LearningRecord:
    id: str
    topic: str
    status: str = LearningStatus.PENDING.value
    created_at: str = ""
    completed_at: Optional[str] = None
    insights: List[str] = field(default_factory=list)


@dataclass
class EvolutionResult:
    records_created: int = 0
    insights_generated: int = 0
    capabilities_updated: int = 0
    topic: str = ""
    record_id: str = ""


class EvolutionHub:
    """Evolution hub — manages knowledge gaps, learning records, and evolution progress."""

    _DEFAULT_CANDIDATE_TOPICS: List[tuple] = [
        ("self-reflection", GapPriority.MEDIUM.value),
        ("reasoning", GapPriority.MEDIUM.value),
        ("metacognition", GapPriority.LOW.value),
    ]

    def __init__(self, storage_dir: str) -> None:
        self._dir = Path(storage_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._gaps_path = self._dir / "gaps.json"
        self._learning_path = self._dir / "learning.json"
        self._gaps: Dict[str, Dict[str, Any]] = {}
        self._learning: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()
        self._capabilities: Dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        for path, target in (
            (self._gaps_path, self._gaps),
            (self._learning_path, self._learning),
        ):
            if path.exists():
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    if isinstance(data, dict):
                        target.update(data)
                except Exception as exc:
                    logger.warning("Failed to load %s: %s", path, exc)
        for p in (self._gaps_path, self._learning_path):
            if not p.exists():
                p.write_text("{}", encoding="utf-8")

    def _save(self) -> None:
        self._gaps_path.write_text(
            json.dumps(self._gaps, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._learning_path.write_text(
            json.dumps(self._learning, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _find_gap_by_topic(self, topic: str) -> Optional[Dict[str, Any]]:
        for g in self._gaps.values():
            if g.get("topic") == topic:
                return g
        return None

    def _gap_to_dict(self, gap: KnowledgeGap) -> Dict[str, Any]:
        return {
            "id": gap.id,
            "topic": gap.topic,
            "priority": gap.priority,
            "access_count": gap.access_count,
            "knowledge_available": gap.knowledge_available,
            "detected_at": gap.detected_at or _now_iso(),
        }

    def analyze_knowledge_gaps(self) -> List[Dict[str, Any]]:
        with self._lock:
            recorded: List[Dict[str, Any]] = []
            for topic, priority in self._DEFAULT_CANDIDATE_TOPICS:
                existing = self._find_gap_by_topic(topic)
                if existing is None:
                    gap = KnowledgeGap(
                        id=_new_id("gap_"),
                        topic=topic,
                        priority=priority,
                        access_count=1,
                        knowledge_available=False,
                        detected_at=_now_iso(),
                    )
                    self._gaps[gap.id] = self._gap_to_dict(gap)
                    recorded.append(dict(self._gaps[gap.id]))
                else:
                    existing["access_count"] = int(existing.get("access_count", 0)) + 1
                    recorded.append(dict(existing))
            if recorded:
                self._save()
            return recorded

    def get_gaps(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(g) for g in self._gaps.values()]

    def learn_from_knowledge(
        self,
        topic: str,
        source: str = "knowledge_base",
        depth: int = 1,
    ) -> Dict[str, Any]:
        with self._lock:
            insights = self._extract_insights(topic, source, depth)
            rid = _new_id("lr_")
            record = LearningRecord(
                id=rid,
                topic=topic,
                status=LearningStatus.COMPLETED.value,
                created_at=_now_iso(),
                completed_at=_now_iso(),
                insights=insights,
            )
            self._learning[rid] = {
                "id": record.id,
                "topic": record.topic,
                "status": record.status,
                "created_at": record.created_at,
                "completed_at": record.completed_at,
                "insights": list(record.insights),
                "source": source,
                "depth": depth,
            }
            capabilities_updated = self._update_capabilities(topic, insights)
            existing_gap = self._find_gap_by_topic(topic)
            if existing_gap is not None:
                existing_gap["knowledge_available"] = True
                existing_gap["access_count"] = int(existing_gap.get("access_count", 0)) + 1
            self._save()
            return {
                "records_created": 1,
                "insights_generated": len(insights),
                "capabilities_updated": capabilities_updated,
                "topic": topic,
                "record_id": rid,
            }

    def get_learning_records(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._learning.values()]

    def on_knowledge_gap_detected(
        self, topic: str, priority: str = GapPriority.MEDIUM.value
    ) -> Dict[str, Any]:
        with self._lock:
            existing = self._find_gap_by_topic(topic)
            if existing is not None:
                existing["priority"] = priority
                existing["access_count"] = int(existing.get("access_count", 0)) + 1
                existing["detected_at"] = _now_iso()
                self._save()
                return dict(existing)
            gap = KnowledgeGap(
                id=_new_id("gap_"),
                topic=topic,
                priority=priority,
                access_count=1,
                knowledge_available=False,
                detected_at=_now_iso(),
            )
            self._gaps[gap.id] = self._gap_to_dict(gap)
            self._save()
            return dict(self._gaps[gap.id])

    def on_reflection_completed(self, reflection: str) -> Dict[str, Any]:
        with self._lock:
            rid = _new_id("ref_")
            improvements = self._extract_improvements(reflection)
            rec = {
                "id": rid,
                "topic": "reflection",
                "reflection": reflection,
                "improvements": improvements,
                "status": LearningStatus.COMPLETED.value,
                "created_at": _now_iso(),
                "completed_at": _now_iso(),
            }
            self._learning[rid] = rec
            self._save()
            return {
                "records_created": 1,
                "insights_generated": len(improvements),
                "capabilities_updated": 0,
                "reflection_id": rid,
                "improvements": improvements,
            }

    def on_idle_cycle(self) -> Dict[str, Any]:
        with self._lock:
            analyzed = self.analyze_knowledge_gaps()
            total = len(self._learning)
            completed = sum(
                1 for r in self._learning.values()
                if r.get("status") == LearningStatus.COMPLETED.value
            )
            return {
                "status": "idle_cycle_completed",
                "gaps_analyzed": len(analyzed),
                "total_gaps": len(self._gaps),
                "total_records": total,
                "completed_records": completed,
                "timestamp": _now_iso(),
            }

    def get_evolution_progress(self) -> Dict[str, Any]:
        with self._lock:
            total_gaps = len(self._gaps)
            total_records = len(self._learning)
            completed_records = sum(
                1 for r in self._learning.values()
                if r.get("status") == LearningStatus.COMPLETED.value
            )
            completion_rate = (
                (completed_records / total_records) if total_records else 0.0
            )
            return {
                "total_gaps": total_gaps,
                "total_records": total_records,
                "completed_records": completed_records,
                "completion_rate": completion_rate,
            }

    def _extract_insights(
        self, topic: str, source: str, depth: int
    ) -> List[str]:
        insights: List[str] = [
            f"Concept '{topic}' indexed from {source}.",
            f"Pattern recognized: {topic} (depth={depth}).",
            f"Relationship mapped for {topic} across {depth} layer(s).",
        ]
        if depth >= 2:
            insights.append(f"Cross-domain link discovered for {topic}.")
        if depth >= 3:
            insights.append(f"Meta-pattern abstracted from {topic}.")
        return insights

    def _update_capabilities(self, topic: str, insights: List[str]) -> int:
        cap_key = f"capability:{topic}"
        self._capabilities[cap_key] = {
            "topic": topic,
            "insight_count": len(insights),
            "updated_at": _now_iso(),
        }
        return 1

    def _extract_improvements(self, reflection: str) -> List[str]:
        if not reflection:
            return ["General improvement: log more reflective context."]
        tokens = [t.strip(" .,;:!?") for t in reflection.split() if t.strip(" .,;:!?")]
        seed = (tokens[0] if tokens else "context").lower()
        return [
            f"Improvement target: {seed}",
            f"Actionable adjustment derived from '{reflection[:60]}'",
        ]


_singleton: Optional[EvolutionHub] = None
_singleton_lock = threading.Lock()
_DEFAULT_DIR = "./data/evolution_hub"


def get_evolution_hub() -> EvolutionHub:
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            Path(_DEFAULT_DIR).mkdir(parents=True, exist_ok=True)
            _singleton = EvolutionHub(_DEFAULT_DIR)
    return _singleton
