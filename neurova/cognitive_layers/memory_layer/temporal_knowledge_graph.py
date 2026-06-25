"""
时序知识图谱引擎 (Temporal Knowledge Graph Engine)

基于 Zep/Graphiti 架构 (arxiv:2501.13956)
实现功能：
1. 时序事实管理（带有效期窗口）
2. 历史状态查询
3. 事实演变追踪
4. 冲突检测与解决
5. 高效检索优化
"""

import hashlib
import json
from neurova.core.logger import get_logger
import re
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = get_logger(__name__)


# ────── Enums ──────


class FactStatus(Enum):
    """事实状态"""

    ACTIVE = "active"
    EXPIRED = "expired"
    CONFLICTED = "conflicted"
    SUPERSEDED = "superseded"


class RelationType(Enum):
    """关系类型"""

    IS_A = "is_a"
    HAS_A = "has_a"
    PART_OF = "part_of"
    CAUSES = "causes"
    LOCATED_IN = "located_in"
    OCCURRED_AT = "occurred_at"
    RELATED_TO = "related_to"
    CONTRADICTS = "contradicts"
    SUPERSEDES = "supersedes"


# ────── Data Models ──────


@dataclass
class TemporalFact:
    """时序事实"""

    id: str = ""
    subject: str = ""
    predicate: str = ""
    object: str = ""
    relation_type: RelationType = RelationType.RELATED_TO
    confidence: float = 1.0
    status: FactStatus = FactStatus.ACTIVE
    valid_from: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    valid_until: Optional[datetime] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    source_memory_id: str = ""
    source_text: str = ""
    extraction_method: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.id:
            content = f"{self.subject}:{self.predicate}:{self.object}:{self.valid_from.isoformat()}"
            self.id = hashlib.md5(content.encode()).hexdigest()[:16]

    def is_valid_at(self, time_point: Optional[datetime] = None) -> bool:
        if time_point is None:
            time_point = datetime.now(timezone.utc)
        if self.status != FactStatus.ACTIVE:
            return False
        if time_point < self.valid_from:
            return False
        if self.valid_until and time_point > self.valid_until:
            return False
        return True

    def expire(self):
        self.status = FactStatus.EXPIRED
        self.valid_until = datetime.now(timezone.utc)
        self.updated_at = self.valid_until

    def supersede(self, new_fact_id: str):
        self.status = FactStatus.SUPERSEDED
        self.metadata["superseded_by"] = new_fact_id
        self.updated_at = datetime.now(timezone.utc)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "subject": self.subject,
            "predicate": self.predicate,
            "object": self.object,
            "relation_type": self.relation_type.value,
            "confidence": self.confidence,
            "status": self.status.value,
            "valid_from": self.valid_from.isoformat(),
            "valid_until": self.valid_until.isoformat() if self.valid_until else None,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "source_memory_id": self.source_memory_id,
            "source_text": self.source_text,
            "extraction_method": self.extraction_method,
            "metadata": self.metadata,
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TemporalFact":
        def _parse_dt(val):
            if isinstance(val, datetime):
                return val
            if isinstance(val, str):
                try:
                    return datetime.fromisoformat(val)
                except ValueError:
                    return datetime.now(timezone.utc)
            return datetime.now(timezone.utc)

        return cls(
            id=data.get("id", ""),
            subject=data.get("subject", ""),
            predicate=data.get("predicate", ""),
            object=data.get("object", ""),
            relation_type=RelationType(data.get("relation_type", "related_to")),
            confidence=data.get("confidence", 1.0),
            status=FactStatus(data.get("status", "active")),
            valid_from=_parse_dt(data.get("valid_from")),
            valid_until=_parse_dt(data["valid_until"]) if data.get("valid_until") else None,
            created_at=_parse_dt(data.get("created_at")),
            updated_at=_parse_dt(data.get("updated_at")),
            source_memory_id=data.get("source_memory_id", ""),
            source_text=data.get("source_text", ""),
            extraction_method=data.get("extraction_method", ""),
            metadata=data.get("metadata", {}),
            tags=data.get("tags", []),
        )


@dataclass
class FactConflict:
    """事实冲突"""

    fact1_id: str
    fact2_id: str
    conflict_type: str
    description: str
    severity: float
    detected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    resolved: bool = False
    resolution: str = ""


# ────── 主类 ──────


class TemporalKnowledgeGraph:
    """时序知识图谱引擎，管理带时间窗口的事实"""

    _CREATE_SQL = """
        CREATE TABLE IF NOT EXISTS temporal_facts (
            id TEXT PRIMARY KEY,
            subject TEXT NOT NULL,
            predicate TEXT NOT NULL,
            object TEXT NOT NULL,
            relation_type TEXT NOT NULL,
            confidence REAL DEFAULT 1.0,
            status TEXT DEFAULT 'active',
            valid_from TEXT NOT NULL,
            valid_until TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            source_memory_id TEXT,
            source_text TEXT,
            extraction_method TEXT,
            metadata TEXT,
            tags TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_tkg_subject ON temporal_facts(subject);
        CREATE INDEX IF NOT EXISTS idx_tkg_predicate ON temporal_facts(predicate);
        CREATE INDEX IF NOT EXISTS idx_tkg_status ON temporal_facts(status);
        CREATE INDEX IF NOT EXISTS idx_tkg_valid_from ON temporal_facts(valid_from);
        CREATE INDEX IF NOT EXISTS idx_tkg_valid_until ON temporal_facts(valid_until);

        CREATE TABLE IF NOT EXISTS fact_conflicts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fact1_id TEXT NOT NULL,
            fact2_id TEXT NOT NULL,
            conflict_type TEXT NOT NULL,
            description TEXT,
            severity REAL DEFAULT 0.5,
            detected_at TEXT NOT NULL,
            resolved BOOLEAN DEFAULT 0,
            resolution TEXT
        );
    """

    def __init__(self, db_path: Optional[str] = None, auto_expire: bool = True):
        self._db_path = db_path or ":memory:"
        self._auto_expire = auto_expire
        self._lock = threading.RLock()
        self._facts_cache: Dict[str, TemporalFact] = {}
        self._subject_index: Dict[str, List[str]] = {}
        self._predicate_index: Dict[str, List[str]] = {}
        self._time_index: List[Tuple[datetime, str]] = []
        self._conn: Optional[sqlite3.Connection] = None
        self._initialize_db()
        self._load_facts_into_cache()
        logger.info("TemporalKnowledgeGraph initialized with db_path=%s", db_path)

    def _initialize_db(self):
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(self._CREATE_SQL)
        self._conn.commit()

    def _get_connection(self) -> sqlite3.Connection:
        if self._conn is None:
            self._initialize_db()
        return self._conn

    def _ensure_db_initialized(self):
        if self._conn is None:
            self._initialize_db()

    def _load_facts_into_cache(self):
        with self._lock:
            self._facts_cache.clear()
            self._subject_index.clear()
            self._predicate_index.clear()
            self._time_index.clear()
            conn = self._get_connection()
            for row in conn.execute("SELECT * FROM temporal_facts"):
                fact = self._row_to_fact(row)
                self._facts_cache[fact.id] = fact
                self._subject_index.setdefault(fact.subject, []).append(fact.id)
                self._predicate_index.setdefault(fact.predicate, []).append(fact.id)
                self._time_index.append((fact.valid_from, fact.id))
            self._time_index.sort(key=lambda x: x[0])

    def _row_to_fact(self, row: sqlite3.Row) -> TemporalFact:
        def _parse_dt(val):
            if val is None:
                return None
            try:
                return datetime.fromisoformat(val)
            except ValueError:
                return datetime.now(timezone.utc)

        return TemporalFact(
            id=row["id"],
            subject=row["subject"],
            predicate=row["predicate"],
            object=row["object"],
            relation_type=RelationType(row["relation_type"]),
            confidence=row["confidence"],
            status=FactStatus(row["status"]),
            valid_from=_parse_dt(row["valid_from"]) or datetime.now(timezone.utc),
            valid_until=_parse_dt(row["valid_until"]),
            created_at=_parse_dt(row["created_at"]) or datetime.now(timezone.utc),
            updated_at=_parse_dt(row["updated_at"]) or datetime.now(timezone.utc),
            source_memory_id=row["source_memory_id"] or "",
            source_text=row["source_text"] or "",
            extraction_method=row["extraction_method"] or "",
            metadata=json.loads(row["metadata"]) if row["metadata"] else {},
            tags=json.loads(row["tags"]) if row["tags"] else [],
        )

    def _insert_fact_to_db(self, fact: TemporalFact):
        conn = self._get_connection()
        conn.execute(
            """INSERT INTO temporal_facts
            (id,subject,predicate,object,relation_type,confidence,status,
             valid_from,valid_until,created_at,updated_at,
             source_memory_id,source_text,extraction_method,metadata,tags)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                fact.id,
                fact.subject,
                fact.predicate,
                fact.object,
                fact.relation_type.value,
                fact.confidence,
                fact.status.value,
                fact.valid_from.isoformat(),
                fact.valid_until.isoformat() if fact.valid_until else None,
                fact.created_at.isoformat(),
                fact.updated_at.isoformat(),
                fact.source_memory_id,
                fact.source_text,
                fact.extraction_method,
                json.dumps(fact.metadata),
                json.dumps(fact.tags),
            ),
        )
        conn.commit()

    def _update_fact_in_db(self, fact: TemporalFact):
        conn = self._get_connection()
        conn.execute(
            """UPDATE temporal_facts SET
            subject=?,predicate=?,object=?,relation_type=?,confidence=?,
            status=?,valid_from=?,valid_until=?,updated_at=?,
            source_memory_id=?,source_text=?,extraction_method=?,metadata=?,tags=?
            WHERE id=?""",
            (
                fact.subject,
                fact.predicate,
                fact.object,
                fact.relation_type.value,
                fact.confidence,
                fact.status.value,
                fact.valid_from.isoformat(),
                fact.valid_until.isoformat() if fact.valid_until else None,
                fact.updated_at.isoformat(),
                fact.source_memory_id,
                fact.source_text,
                fact.extraction_method,
                json.dumps(fact.metadata),
                json.dumps(fact.tags),
                fact.id,
            ),
        )
        conn.commit()

    def _expire_older_facts(self, new_fact: TemporalFact):
        related = self.query_current(subject=new_fact.subject, predicate=new_fact.predicate)
        for old_fact in related:
            if old_fact.id == new_fact.id:
                continue
            if old_fact.valid_until is None or old_fact.valid_until > new_fact.valid_from:
                old_fact.supersede(new_fact.id)
                self._update_fact_in_db(old_fact)
                logger.info("Superseded fact %s with %s", old_fact.id, new_fact.id)

    def add_fact(self, fact: TemporalFact, check_conflicts: bool = True) -> Tuple[bool, List[FactConflict]]:
        with self._lock:
            conflicts: List[FactConflict] = []
            if check_conflicts:
                conflicts = self.detect_conflicts(fact)
                if any(c.severity > 0.7 for c in conflicts):
                    logger.warning("High severity conflicts detected for %s", fact.id)
                    return False, conflicts
            existing = self._facts_cache.get(fact.id)
            if existing:
                self._update_fact_in_db(fact)
            else:
                self._insert_fact_to_db(fact)
                self._subject_index.setdefault(fact.subject, []).append(fact.id)
                self._predicate_index.setdefault(fact.predicate, []).append(fact.id)
                self._time_index.append((fact.valid_from, fact.id))
                self._time_index.sort(key=lambda x: x[0])
            self._facts_cache[fact.id] = fact
            if self._auto_expire:
                self._expire_older_facts(fact)
            return True, conflicts

    def query_current(
        self,
        subject: Optional[str] = None,
        predicate: Optional[str] = None,
        object_: Optional[str] = None,
        relation_type: Optional[RelationType] = None,
        time_point: Optional[datetime] = None,
    ) -> List[TemporalFact]:
        if time_point is None:
            time_point = datetime.now(timezone.utc)
        with self._lock:
            results = []
            for fact in self._facts_cache.values():
                if not fact.is_valid_at(time_point):
                    continue
                if subject and fact.subject != subject:
                    continue
                if predicate and fact.predicate != predicate:
                    continue
                if object_ and fact.object != object_:
                    continue
                if relation_type and fact.relation_type != relation_type:
                    continue
                results.append(fact)
            results.sort(key=lambda x: x.confidence, reverse=True)
            return results

    def query_at_time(
        self, time_point: datetime, subject: Optional[str] = None, predicate: Optional[str] = None
    ) -> List[TemporalFact]:
        return self.query_current(subject=subject, predicate=predicate, time_point=time_point)

    def get_fact_history(self, subject: str, predicate: Optional[str] = None, limit: int = 100) -> List[TemporalFact]:
        with self._lock:
            results = [
                f
                for f in self._facts_cache.values()
                if f.subject == subject and (predicate is None or f.predicate == predicate)
            ]
            results.sort(key=lambda x: x.valid_from, reverse=True)
            return results[:limit]

    def detect_conflicts(self, new_fact: TemporalFact) -> List[FactConflict]:
        conflicts: List[FactConflict] = []
        with self._lock:
            for existing in self.query_current(subject=new_fact.subject):
                if existing.id == new_fact.id:
                    continue
                if self._is_contradiction(existing, new_fact):
                    conflicts.append(
                        FactConflict(
                            existing.id,
                            new_fact.id,
                            "contradiction",
                            f"矛盾事实: {existing.object} vs {new_fact.object}",
                            0.8,
                        )
                    )
                if self._is_relation_mutually_exclusive(existing, new_fact):
                    conflicts.append(
                        FactConflict(
                            existing.id,
                            new_fact.id,
                            "mutual_exclusion",
                            f"互斥关系: {existing.predicate} vs {new_fact.predicate}",
                            0.6,
                        )
                    )
                if self._has_temporal_overlap(existing, new_fact):
                    conflicts.append(FactConflict(existing.id, new_fact.id, "temporal_overlap", "时间范围重叠", 0.4))
            for c in conflicts:
                self._store_conflict(c)
        return conflicts

    def _is_contradiction(self, f1: TemporalFact, f2: TemporalFact) -> bool:
        if f1.subject == f2.subject and f1.predicate == f2.predicate and f1.object != f2.object:
            return f1.predicate in {"is_married_to", "works_at", "lives_in", "is_president_of"}
        return False

    def _is_relation_mutually_exclusive(self, f1: TemporalFact, f2: TemporalFact) -> bool:
        pairs = {(RelationType.IS_A, RelationType.PART_OF), (RelationType.CAUSES, RelationType.RELATED_TO)}
        pair = (f1.relation_type, f2.relation_type)
        return pair in pairs or (pair[1], pair[0]) in pairs

    def _has_temporal_overlap(self, f1: TemporalFact, f2: TemporalFact) -> bool:
        if f1.valid_until is None or f2.valid_until is None:
            return True
        return f1.valid_from < f2.valid_until and f2.valid_from < f1.valid_until

    def _store_conflict(self, conflict: FactConflict):
        conn = self._get_connection()
        conn.execute(
            """INSERT INTO fact_conflicts
            (fact1_id,fact2_id,conflict_type,description,severity,detected_at,resolved,resolution)
            VALUES (?,?,?,?,?,?,?,?)""",
            (
                conflict.fact1_id,
                conflict.fact2_id,
                conflict.conflict_type,
                conflict.description,
                conflict.severity,
                conflict.detected_at.isoformat(),
                conflict.resolved,
                conflict.resolution,
            ),
        )
        conn.commit()

    def get_fact_by_id(self, fact_id: str) -> Optional[TemporalFact]:
        return self._facts_cache.get(fact_id)

    def get_all_facts(self, status_filter: Optional[FactStatus] = None, limit: int = 1000) -> List[TemporalFact]:
        with self._lock:
            facts = list(self._facts_cache.values())
            if status_filter:
                facts = [f for f in facts if f.status == status_filter]
            facts.sort(key=lambda x: x.created_at, reverse=True)
            return facts[:limit]

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            status_counts: Dict[str, int] = {}
            relation_counts: Dict[str, int] = {}
            for f in self._facts_cache.values():
                status_counts[f.status.value] = status_counts.get(f.status.value, 0) + 1
                relation_counts[f.relation_type.value] = relation_counts.get(f.relation_type.value, 0) + 1
            conn = self._get_connection()
            total_conflicts = conn.execute("SELECT COUNT(*) FROM fact_conflicts").fetchone()[0]
            resolved = conn.execute("SELECT COUNT(*) FROM fact_conflicts WHERE resolved=1").fetchone()[0]
            return {
                "total_facts": len(self._facts_cache),
                "by_status": status_counts,
                "by_relation_type": relation_counts,
                "conflicts": {"total": total_conflicts, "resolved": resolved, "unresolved": total_conflicts - resolved},
            }

    def clear_cache(self):
        with self._lock:
            self._facts_cache.clear()
            self._subject_index.clear()
            self._predicate_index.clear()
            self._time_index.clear()
            self._load_facts_into_cache()

    def close(self):
        with self._lock:
            if self._conn:
                self._conn.close()
                self._conn = None

    def __del__(self):
        self.close()


# ────── 桥梁类 ──────


class TemporalKGMemoryBridge:
    """时序知识图谱与记忆系统的桥梁"""

    _EXTRACTION_RULES = [
        {"name": "is_a", "pattern": r"(.+?)是一种(.+)", "predicate": "is_a", "relation_type": RelationType.IS_A},
        {
            "name": "works_at",
            "pattern": r"(.+?)在(.+?)工作",
            "predicate": "works_at",
            "relation_type": RelationType.RELATED_TO,
        },
        {
            "name": "lives_in",
            "pattern": r"(.+?)住在(.+)",
            "predicate": "lives_in",
            "relation_type": RelationType.LOCATED_IN,
        },
        {
            "name": "born_in",
            "pattern": r"(.+?)出生于(.+)",
            "predicate": "born_in",
            "relation_type": RelationType.OCCURRED_AT,
        },
        {
            "name": "created_by",
            "pattern": r"(.+?)由(.+?)创建",
            "predicate": "created_by",
            "relation_type": RelationType.HAS_A,
        },
        {
            "name": "occurred_at",
            "pattern": r"(.+?)发生在(.+)",
            "predicate": "occurred_at",
            "relation_type": RelationType.OCCURRED_AT,
        },
    ]

    _STOP_WORDS = frozenset(
        {
            "的",
            "了",
            "在",
            "是",
            "我",
            "有",
            "和",
            "就",
            "不",
            "人",
            "都",
            "一",
            "也",
            "很",
            "到",
            "说",
            "要",
            "去",
            "你",
            "会",
            "着",
            "没有",
            "看",
            "好",
            "the",
            "a",
            "an",
            "is",
            "are",
            "was",
            "were",
            "be",
            "have",
            "has",
            "had",
            "do",
            "does",
            "did",
            "will",
            "would",
            "could",
            "should",
            "may",
            "can",
            "what",
            "which",
            "who",
            "this",
            "that",
            "i",
            "me",
            "my",
            "we",
            "our",
            "you",
            "your",
            "he",
            "him",
            "she",
            "her",
            "it",
            "its",
            "they",
            "them",
        }
    )

    def __init__(self, tkg: TemporalKnowledgeGraph):
        self._tkg = tkg
        logger.info("TemporalKGMemoryBridge initialized")

    def _initialize_extraction_rules(self) -> List[Dict[str, Any]]:
        return list(self._EXTRACTION_RULES)

    def extract_facts_from_memory(
        self, memory_id: str, content: str, timestamp: Optional[datetime] = None
    ) -> List[TemporalFact]:
        if timestamp is None:
            timestamp = datetime.now(timezone.utc)
        facts: List[TemporalFact] = []
        for rule in self._EXTRACTION_RULES:
            try:
                matches = re.findall(rule["pattern"], content)
                for match in matches:
                    subj, obj = match if isinstance(match, tuple) else (match, "")
                    subj, obj = subj.strip(), obj.strip()
                    if subj and obj:
                        facts.append(
                            TemporalFact(
                                subject=subj,
                                predicate=rule["predicate"],
                                object=obj,
                                relation_type=rule["relation_type"],
                                confidence=0.8,
                                valid_from=timestamp,
                                source_memory_id=memory_id,
                                source_text=content,
                                extraction_method="pattern_matching",
                                tags=["extracted", "auto"],
                            )
                        )
            except Exception as e:
                logger.error("Error applying rule %s: %s", rule['name'], e)
        nouns = self._extract_noun_phrases(content)
        for i in range(len(nouns) - 1):
            facts.append(
                TemporalFact(
                    subject=nouns[i],
                    predicate="related_to",
                    object=nouns[i + 1],
                    relation_type=RelationType.RELATED_TO,
                    confidence=0.5,
                    valid_from=timestamp,
                    source_memory_id=memory_id,
                    source_text=content,
                    extraction_method="noun_phrase",
                    tags=["extracted", "auto", "noun_phrase"],
                )
            )
        return facts

    def _extract_noun_phrases(self, text: str) -> List[str]:
        text = re.sub(r"[^\w\s]", " ", text)
        phrases = []
        current: List[str] = []
        for word in text.split():
            if word.lower() not in self._STOP_WORDS and len(word) > 1:
                current.append(word)
            else:
                if current:
                    phrases.append(" ".join(current))
                    current = []
        if current:
            phrases.append(" ".join(current))
        return phrases[:5]

    def sync_memory_to_tkg(
        self, memory_id: str, content: str, timestamp: Optional[datetime] = None
    ) -> List[TemporalFact]:
        facts = self.extract_facts_from_memory(memory_id, content, timestamp)
        added = []
        for fact in facts:
            success, conflicts = self._tkg.add_fact(fact)
            if success:
                added.append(fact)
                if conflicts:
                    logger.warning("Conflicts for fact %s: %s", fact.id, len(conflicts))
        logger.info("Synced %s facts from memory %s", len(added), memory_id)
        return added

    def query_tkg_for_context(
        self, query: str, max_facts: int = 10, time_window_days: int = 30
    ) -> List[Dict[str, Any]]:
        now = datetime.now(timezone.utc)
        window_start = now - timedelta(days=time_window_days)
        keywords = self._extract_keywords(query)
        seen: set = set()
        unique: List[TemporalFact] = []
        for kw in keywords:
            for fact in self._tkg.query_current(subject=kw, time_point=now):
                if fact.id not in seen and fact.valid_from >= window_start:
                    seen.add(fact.id)
                    unique.append(fact)
        unique.sort(key=lambda x: x.confidence, reverse=True)
        return [
            {
                "id": f.id,
                "subject": f.subject,
                "predicate": f.predicate,
                "object": f.object,
                "confidence": f.confidence,
                "valid_from": f.valid_from.isoformat(),
                "source": f.source_memory_id,
            }
            for f in unique[:max_facts]
        ]

    def _extract_keywords(self, text: str) -> List[str]:
        text = re.sub(r"[^\w\s]", " ", text)
        return [w for w in text.split() if w.lower() not in self._STOP_WORDS and len(w) > 1][:10]
