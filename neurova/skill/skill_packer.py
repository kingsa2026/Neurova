"""
Skill Packer - Agent automatic skill packaging

Packs successful task-execution patterns into reusable skills.
Implements Neurova CogArch 1.0.0 automatic-skill-extraction rules.

Pack prerequisites:
1. skill library has no matching skill
2. problem solution has more than 2 steps
3. two or more successful executions of the same task type
"""

from __future__ import annotations

import datetime
import json
import logging
import re
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


class SkillCategory(str, Enum):
    COGNITIVE = "cognitive"
    MEMORY = "memory"
    REASONING = "reasoning"
    LEARNING = "learning"
    COMMUNICATION = "communication"
    EXECUTION = "execution"
    MONITORING = "monitoring"
    INTEGRATION = "integration"


@dataclass
class PackedSkill:
    skill_id: str
    name: str
    description: str
    category: SkillCategory
    version: str = "1.0.0"
    created_at: datetime.datetime = None
    updated_at: datetime.datetime = None
    parameters: Dict[str, Any] = field(default_factory=dict)
    examples: List[Dict[str, Any]] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.created_at is None:
            self.created_at = datetime.datetime.now()
        if self.updated_at is None:
            self.updated_at = self.created_at
        if isinstance(self.category, str):
            try:
                self.category = SkillCategory(self.category)
            except ValueError:
                self.category = SkillCategory.COGNITIVE

    def to_dict(self) -> Dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "name": self.name,
            "description": self.description,
            "category": self.category.value if isinstance(self.category, SkillCategory) else str(self.category),
            "version": self.version,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "parameters": dict(self.parameters),
            "examples": [dict(e) for e in self.examples],
            "dependencies": list(self.dependencies),
            "tags": list(self.tags),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PackedSkill":
        return cls(
            skill_id=data["skill_id"],
            name=data["name"],
            description=data["description"],
            category=SkillCategory(data["category"]) if data.get("category") else SkillCategory.COGNITIVE,
            version=data.get("version", "1.0.0"),
            created_at=datetime.datetime.fromisoformat(data["created_at"]) if data.get("created_at") else None,
            updated_at=datetime.datetime.fromisoformat(data["updated_at"]) if data.get("updated_at") else None,
            parameters=dict(data.get("parameters", {})),
            examples=[dict(e) for e in data.get("examples", [])],
            dependencies=list(data.get("dependencies", [])),
            tags=list(data.get("tags", [])),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass
class TaskExecutionRecord:
    task_id: str
    task_type: str
    skill_id: str
    start_time: datetime.datetime
    end_time: Optional[datetime.datetime] = None
    success: bool = False
    input_data: Dict[str, Any] = field(default_factory=dict)
    output_data: Dict[str, Any] = field(default_factory=dict)
    error_message: str = ""
    execution_time_ms: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.end_time is None:
            self.end_time = self.start_time
        if self.execution_time_ms == 0.0 and self.end_time and self.start_time:
            delta = self.end_time - self.start_time
            self.execution_time_ms = max(delta.total_seconds() * 1000.0, 0.0)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "skill_id": self.skill_id,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "success": self.success,
            "input_data": dict(self.input_data),
            "output_data": dict(self.output_data),
            "error_message": self.error_message,
            "execution_time_ms": float(self.execution_time_ms),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskExecutionRecord":
        return cls(
            task_id=data["task_id"],
            task_type=data["task_type"],
            skill_id=data.get("skill_id", ""),
            start_time=datetime.datetime.fromisoformat(data["start_time"]) if data.get("start_time") else datetime.datetime.now(),
            end_time=datetime.datetime.fromisoformat(data["end_time"]) if data.get("end_time") else None,
            success=bool(data.get("success", False)),
            input_data=dict(data.get("input_data", {})),
            output_data=dict(data.get("output_data", {})),
            error_message=str(data.get("error_message", "")),
            execution_time_ms=float(data.get("execution_time_ms", 0.0)),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass
class Skill:
    skill_id: str
    name: str
    description: str
    category: SkillCategory
    version: str = "1.0.0"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "name": self.name,
            "description": self.description,
            "category": self.category.value,
            "version": self.version,
            "metadata": dict(self.metadata),
        }


@dataclass
class MuscleMemory:
    memory_id: str
    skill_id: str
    proficiency: float = 0.0
    usage_count: int = 0
    last_used: Optional[datetime.datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "memory_id": self.memory_id,
            "skill_id": self.skill_id,
            "proficiency": float(self.proficiency),
            "usage_count": int(self.usage_count),
            "last_used": self.last_used.isoformat() if self.last_used else None,
            "metadata": dict(self.metadata),
        }


class SkillPacker:
    """SkillPacker — observes task executions, extracts patterns, and packs them into reusable skills."""

    def __init__(self, storage_dir: Optional[str] = None) -> None:
        self._dir = Path(storage_dir) if storage_dir else Path("./data/skill_packer")
        self._dir.mkdir(parents=True, exist_ok=True)
        self._skills_path = self._dir / "packed_skills.json"
        self._records_path = self._dir / "task_records.json"
        self._muscle_path = self._dir / "muscle_memory.json"
        self._skills: Dict[str, PackedSkill] = {}
        self._records: List[TaskExecutionRecord] = []
        self._muscle: Dict[str, MuscleMemory] = {}
        self._lock = threading.RLock()
        self._state = "uninitialized"
        self._load()

    def on_initialize(self) -> None:
        self._state = "initialized"
        logger.info("SkillPacker initialized at %s", self._dir)

    def on_start(self) -> None:
        self._state = "running"
        logger.info("SkillPacker started")

    def on_stop(self) -> None:
        self._state = "stopped"
        self._save()
        logger.info("SkillPacker stopped")

    def initialize(self) -> None:
        with self._lock:
            self.on_initialize()

    def start(self) -> None:
        with self._lock:
            self.on_start()

    def stop(self) -> None:
        with self._lock:
            self.on_stop()

    def shutdown(self) -> None:
        self.stop()

    def record_task_execution(
        self,
        skill_id: str = "",
        task_type: str = "",
        success: bool = True,
        input_data: Optional[Dict[str, Any]] = None,
        output_data: Optional[Dict[str, Any]] = None,
        error_message: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        with self._lock:
            now = datetime.datetime.now()
            record = TaskExecutionRecord(
                task_id=_new_id("te_"),
                task_type=task_type,
                skill_id=skill_id,
                start_time=now,
                end_time=now,
                success=bool(success),
                input_data=dict(input_data) if input_data else {},
                output_data=dict(output_data) if output_data else {},
                error_message=error_message,
                metadata=dict(metadata) if metadata else {},
            )
            self._records.append(record)
            self._save()
            return record.task_id

    def get_task_records(self, skill_id: Optional[str] = None, task_type: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._lock:
            items = list(self._records)
            if skill_id is not None:
                items = [r for r in items if r.skill_id == skill_id]
            if task_type is not None:
                items = [r for r in items if r.task_type == task_type]
            return [r.to_dict() for r in items]

    def _check_and_pack(
        self,
        task_type: str = "",
        steps: int = 0,
        min_success: int = 2,
    ) -> Optional[str]:
        with self._lock:
            relevant = [r for r in self._records if r.task_type == task_type and r.success]
            if not self.evaluate_pattern_for_packing(
                task_type=task_type,
                success_count=len(relevant),
                failure_count=sum(1 for r in self._records if r.task_type == task_type and not r.success),
                step_count=steps,
                min_success=min_success,
            ):
                return None
            if self._skill_exists(task_type=task_type):
                return None
            return self._create_skill_from_records(task_type=task_type, records=relevant)

    def _skill_exists(self, task_type: str = "", name: Optional[str] = None) -> bool:
        with self._lock:
            for s in self._skills.values():
                if task_type and s.metadata.get("task_type") == task_type:
                    return True
                if name and s.name == name:
                    return True
            return False

    def _create_skill_from_records(
        self,
        task_type: str = "",
        records: Optional[List[TaskExecutionRecord]] = None,
    ) -> str:
        with self._lock:
            records = records or []
            examples: List[Dict[str, Any]] = []
            for r in records[:5]:
                examples.append({"input": dict(r.input_data), "output": dict(r.output_data)})
            sid = _new_id("sk_")
            packed = PackedSkill(
                skill_id=sid,
                name=task_type or "auto_skill",
                description=f"Auto-packed skill for task_type={task_type}",
                category=self._determine_category(task_type),
                parameters={},
                examples=examples,
                dependencies=[],
                tags=["auto", "packed"],
                metadata={"task_type": task_type, "source_records": len(records)},
            )
            self._skills[sid] = packed
            self._write_to_toolmemory(packed)
            self._record_experience(packed)
            self._save()
            return sid

    def pack_skill(
        self,
        name: str,
        description: str = "",
        category: Any = SkillCategory.COGNITIVE,
        parameters: Optional[Dict[str, Any]] = None,
        examples: Optional[List[Dict[str, Any]]] = None,
        dependencies: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        with self._lock:
            sid = _new_id("sk_")
            if isinstance(category, str):
                try:
                    category = SkillCategory(category)
                except ValueError:
                    category = SkillCategory.COGNITIVE
            packed = PackedSkill(
                skill_id=sid,
                name=name,
                description=description,
                category=category,
                parameters=dict(parameters) if parameters else {},
                examples=[dict(e) for e in examples] if examples else [],
                dependencies=list(dependencies) if dependencies else [],
                tags=list(tags) if tags else [],
                metadata=dict(metadata) if metadata else {},
            )
            self._skills[sid] = packed
            self._write_to_toolmemory(packed)
            self._record_experience(packed)
            self._save()
            return sid

    def _determine_category(self, task_type: str) -> SkillCategory:
        t = (task_type or "").lower()
        mapping = {
            "search": SkillCategory.COGNITIVE,
            "plan": SkillCategory.REASONING,
            "reason": SkillCategory.REASONING,
            "remember": SkillCategory.MEMORY,
            "recall": SkillCategory.MEMORY,
            "communicate": SkillCategory.COMMUNICATION,
            "chat": SkillCategory.COMMUNICATION,
            "execute": SkillCategory.EXECUTION,
            "run": SkillCategory.EXECUTION,
            "monitor": SkillCategory.MONITORING,
            "watch": SkillCategory.MONITORING,
            "learn": SkillCategory.LEARNING,
            "integrate": SkillCategory.INTEGRATION,
        }
        for keyword, cat in mapping.items():
            if keyword in t:
                return cat
        return SkillCategory.COGNITIVE

    def _generate_skill_content(self, packed: PackedSkill) -> Dict[str, Any]:
        return {
            "name": packed.name,
            "description": packed.description,
            "parameters": dict(packed.parameters),
            "examples": [dict(e) for e in packed.examples],
            "dependencies": list(packed.dependencies),
            "tags": list(packed.tags),
        }

    def _write_to_toolmemory(self, packed: PackedSkill) -> None:
        with self._lock:
            mid = _new_id("mm_")
            self._muscle[mid] = MuscleMemory(
                memory_id=mid,
                skill_id=packed.skill_id,
                proficiency=0.1,
                usage_count=0,
                last_used=datetime.datetime.now(),
                metadata={"source": "skill_packer"},
            )

    def _record_experience(self, packed: PackedSkill) -> None:
        with self._lock:
            logger.info("Packed skill %s (%s) category=%s", packed.skill_id, packed.name, packed.category.value)

    def iterate_skill(
        self,
        skill_id: str,
        description: Optional[str] = None,
        tags: Optional[List[str]] = None,
        parameters: Optional[Dict[str, Any]] = None,
    ) -> bool:
        with self._lock:
            s = self._skills.get(skill_id)
            if s is None:
                return False
            if description is not None:
                s.description = description
            if tags is not None:
                s.tags = list(tags)
            if parameters is not None:
                s.parameters = dict(parameters)
            s.version = self._bump_version(s.version)
            s.updated_at = datetime.datetime.now()
            self._save()
            return True

    @staticmethod
    def _bump_version(version: str) -> str:
        parts = (version or "1.0.0").split(".")
        try:
            parts = [int(p) for p in parts]
        except ValueError:
            return "1.0.1"
        while len(parts) < 3:
            parts.append(0)
        parts[2] = parts[2] + 1
        return ".".join(str(p) for p in parts[:3])

    def get_packed_skills(self, category: Optional[Any] = None) -> List[Dict[str, Any]]:
        with self._lock:
            items = list(self._skills.values())
            if category is not None:
                cat_value = category.value if isinstance(category, SkillCategory) else str(category)
                items = [s for s in items if s.category.value == cat_value]
            return [s.to_dict() for s in items]

    def get_packed_skill(self, skill_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            s = self._skills.get(skill_id)
            return s.to_dict() if s else None

    def _load_packed_skills(self) -> None:
        if not self._skills_path.exists():
            return
        try:
            data = json.loads(self._skills_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for k, v in data.items():
                    if isinstance(v, dict):
                        try:
                            self._skills[k] = PackedSkill.from_dict(v)
                        except Exception as exc:
                            logger.warning("Failed to load skill %s: %s", k, exc)
        except Exception as exc:
            logger.warning("Failed to load packed skills: %s", exc)

    def _save_packed_skills(self) -> None:
        self._skills_path.write_text(
            json.dumps({k: v.to_dict() for k, v in self._skills.items()}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _load_task_records(self) -> None:
        if not self._records_path.exists():
            return
        try:
            data = json.loads(self._records_path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                for entry in data:
                    if isinstance(entry, dict):
                        try:
                            self._records.append(TaskExecutionRecord.from_dict(entry))
                        except Exception as exc:
                            logger.warning("Failed to load record: %s", exc)
        except Exception as exc:
            logger.warning("Failed to load task records: %s", exc)

    def _save_task_records(self) -> None:
        self._records_path.write_text(
            json.dumps([r.to_dict() for r in self._records], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _load_muscle_memory(self) -> None:
        if not self._muscle_path.exists():
            return
        try:
            data = json.loads(self._muscle_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for k, v in data.items():
                    if isinstance(v, dict):
                        self._muscle[k] = MuscleMemory(
                            memory_id=k,
                            skill_id=v.get("skill_id", ""),
                            proficiency=float(v.get("proficiency", 0.0)),
                            usage_count=int(v.get("usage_count", 0)),
                            last_used=datetime.datetime.fromisoformat(v["last_used"]) if v.get("last_used") else None,
                            metadata=dict(v.get("metadata", {})),
                        )
        except Exception as exc:
            logger.warning("Failed to load muscle memory: %s", exc)

    def _save_muscle_memory(self) -> None:
        self._muscle_path.write_text(
            json.dumps({k: v.to_dict() for k, v in self._muscle.items()}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _load(self) -> None:
        self._load_packed_skills()
        self._load_task_records()
        self._load_muscle_memory()

    def _save(self) -> None:
        self._save_packed_skills()
        self._save_task_records()
        self._save_muscle_memory()

    def evaluate_pattern_for_packing(
        self,
        task_type: str = "",
        success_count: int = 0,
        failure_count: int = 0,
        step_count: int = 0,
        min_success: int = 2,
    ) -> bool:
        if not task_type:
            return False
        if step_count < 2:
            return False
        if success_count < min_success:
            return False
        if failure_count > success_count:
            return False
        return True

    def pack_pattern(
        self,
        task_type: str,
        steps: List[Dict[str, Any]],
        success_count: int = 0,
    ) -> Optional[str]:
        with self._lock:
            if not self.evaluate_pattern_for_packing(
                task_type=task_type,
                success_count=success_count,
                failure_count=0,
                step_count=len(steps),
            ):
                return None
            if self._skill_exists(task_type=task_type):
                return None
            return self._create_skill_from_records(
                task_type=task_type,
                records=[r for r in self._records if r.task_type == task_type and r.success],
            )


_singleton: Optional[SkillPacker] = None
_singleton_lock = threading.Lock()
_DEFAULT_DIR = "./data/skill_packer"


def get_skill_packer() -> SkillPacker:
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            Path(_DEFAULT_DIR).mkdir(parents=True, exist_ok=True)
            _singleton = SkillPacker(storage_dir=_DEFAULT_DIR)
    return _singleton
