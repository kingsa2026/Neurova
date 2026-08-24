"""
Cognition Orchestrator - 认知编排器

实现 Neurova 认知编排功能，包括代理注册、任务编排、状态跟踪、
注意力管理和记忆管理。
"""

import datetime
import json
from neurova.core.logger import get_logger
import pathlib
import threading
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional

logger = get_logger(__name__)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat() + "Z"


class AttentionLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class MemoryType(str, Enum):
    SHORT_TERM = "short_term"
    LONG_TERM = "long_term"
    WORKING = "working"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"


class CognitiveState(str, Enum):
    IDLE = "idle"
    FOCUSED = "focused"
    EXPLORING = "exploring"
    LEARNING = "learning"
    CREATING = "creating"
    ANALYZING = "analyzing"
    DECIDING = "deciding"
    REFLECTING = "reflecting"


class AttentionManager:
    def __init__(self, storage_path: pathlib.Path):
        self._lock = threading.RLock()
        self._storage_path = storage_path
        self._records: Dict[str, Dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if self._storage_path.exists():
            try:
                with self._storage_path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    self._records = {k: dict(v) for k, v in data.items() if isinstance(v, dict)}
            except (json.JSONDecodeError, OSError):
                self._records = {}

    def _save(self) -> None:
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        with self._storage_path.open("w", encoding="utf-8") as f:
            json.dump(self._records, f, ensure_ascii=False, indent=2)

    def set_attention(self, focus_id: str, level: str = "medium", weight: float = 0.5) -> str:
        with self._lock:
            self._records[focus_id] = {
                "focus_id": focus_id,
                "level": level,
                "weight": float(weight),
                "updated_at": _now_iso(),
            }
            self._save()
            return focus_id

    def get_attention(self, focus_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            return dict(self._records.get(focus_id, {})) or None

    def list_attention(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(v) for v in self._records.values()]

    def clear_attention(self) -> int:
        with self._lock:
            n = len(self._records)
            self._records.clear()
            self._save()
            return n

    def should_switch_attention(self, from_id: str, to_id: str) -> bool:
        with self._lock:
            a = self._records.get(from_id, {})
            b = self._records.get(to_id, {})
            wa = float(a.get("weight", 0.0))
            wb = float(b.get("weight", 0.0))
            return wb > wa


class MemoryManager:
    def __init__(self, storage_path: pathlib.Path):
        self._lock = threading.RLock()
        self._storage_path = storage_path
        self._records: Dict[str, Dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if self._storage_path.exists():
            try:
                with self._storage_path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    self._records = {k: dict(v) for k, v in data.items() if isinstance(v, dict)}
            except (json.JSONDecodeError, OSError):
                self._records = {}

    def _save(self) -> None:
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        with self._storage_path.open("w", encoding="utf-8") as f:
            json.dump(self._records, f, ensure_ascii=False, indent=2)

    def add_memory(self, content: str, memory_type: str = "short_term", tags: Optional[List[str]] = None) -> str:
        with self._lock:
            mid = _new_id("mem")
            self._records[mid] = {
                "id": mid,
                "content": content,
                "memory_type": memory_type,
                "tags": list(tags or []),
                "created_at": _now_iso(),
            }
            self._save()
            return mid

    def retrieve_memory(self, memory_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            rec = self._records.get(memory_id)
            return dict(rec) if rec else None

    def consolidate_memories(self) -> int:
        return 0

    def get_memories_by_type(self, memory_type: str) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(v) for v in self._records.values() if v.get("memory_type") == memory_type]

    def clear_memories(self, memory_type: Optional[str] = None) -> int:
        with self._lock:
            if memory_type is None:
                n = len(self._records)
                self._records.clear()
                self._save()
                return n
            to_remove = [k for k, v in self._records.items() if v.get("memory_type") == memory_type]
            for k in to_remove:
                del self._records[k]
            self._save()
            return len(to_remove)


class CognitionOrchestrator:
    def __init__(self, storage_dir: Optional[str] = None):
        self._lock = threading.RLock()
        base = pathlib.Path(storage_dir) if storage_dir else pathlib.Path("./data/orchestrator")
        base.mkdir(parents=True, exist_ok=True)
        self._storage_dir = base
        self._agents_path = base / "agents.json"
        self._tasks_path = base / "tasks.json"
        self._state_path = base / "state.json"
        self._agents: Dict[str, Dict[str, Any]] = {}
        self._tasks: Dict[str, Dict[str, Any]] = {}
        self._state: Dict[str, Any] = {"state": CognitiveState.IDLE.value, "updated_at": _now_iso()}
        self._attention = AttentionManager(base / "attention.json")
        self._memory = MemoryManager(base / "memory.json")
        self._load()

    def _load(self) -> None:
        for path, target in (
            (self._agents_path, self._agents),
            (self._tasks_path, self._tasks),
        ):
            if path.exists():
                try:
                    with path.open("r", encoding="utf-8") as f:
                        data = json.load(f)
                    if isinstance(data, dict):
                        target.clear()
                        target.update({k: dict(v) for k, v in data.items() if isinstance(v, dict)})
                except (json.JSONDecodeError, OSError):
                    pass
        if self._state_path.exists():
            try:
                with self._state_path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    self._state.update(data)
            except (json.JSONDecodeError, OSError):
                pass

    def _save_agents(self) -> None:
        with self._agents_path.open("w", encoding="utf-8") as f:
            json.dump(self._agents, f, ensure_ascii=False, indent=2)

    def _save_tasks(self) -> None:
        with self._tasks_path.open("w", encoding="utf-8") as f:
            json.dump(self._tasks, f, ensure_ascii=False, indent=2)

    def _save_state(self) -> None:
        with self._state_path.open("w", encoding="utf-8") as f:
            json.dump(self._state, f, ensure_ascii=False, indent=2)

    def register_agent(self, name: str, role: str = "executor", capabilities: Optional[List[str]] = None) -> str:
        with self._lock:
            aid = _new_id("agt")
            self._agents[aid] = {
                "id": aid,
                "name": name,
                "role": role,
                "capabilities": list(capabilities or []),
                "created_at": _now_iso(),
            }
            self._save_agents()
            return aid

    def deregister_agent(self, agent_id: str) -> bool:
        with self._lock:
            if agent_id in self._agents:
                del self._agents[agent_id]
                self._save_agents()
                return True
            return False

    def list_agents(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(v) for v in self._agents.values()]

    def get_agent(self, agent_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            rec = self._agents.get(agent_id)
            return dict(rec) if rec else None

    def submit_task(self, agent_id: str, name: str, payload: Optional[Dict[str, Any]] = None) -> str:
        with self._lock:
            if agent_id not in self._agents:
                raise KeyError(f"unknown agent: {agent_id}")
            tid = _new_id("tsk")
            payload = dict(payload or {})
            record = {
                "id": tid,
                "agent_id": agent_id,
                "name": name,
                "payload": payload,
                "status": "pending",
                "error": None,
                "created_at": _now_iso(),
            }
            if isinstance(payload, dict) and payload.get("raise"):
                record["status"] = "failed"
                record["error"] = "task payload requested failure"
            self._tasks[tid] = record
            self._save_tasks()
            return tid

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            rec = self._tasks.get(task_id)
            return dict(rec) if rec else None

    def list_tasks(self, agent_id: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._lock:
            if agent_id is None:
                return [dict(v) for v in self._tasks.values()]
            return [dict(v) for v in self._tasks.values() if v.get("agent_id") == agent_id]

    def update_task_status(self, task_id: str, status: str) -> bool:
        with self._lock:
            rec = self._tasks.get(task_id)
            if not rec:
                return False
            rec["status"] = status
            rec["updated_at"] = _now_iso()
            self._save_tasks()
            return True

    def orchestrate(self, pipeline: List[Dict[str, Any]]) -> Dict[str, Any]:
        with self._lock:
            executed: List[Dict[str, Any]] = []
            for step in pipeline:
                agent_id = step.get("agent_id")
                name = step.get("name", "step")
                payload = dict(step.get("payload") or {})
                if agent_id not in self._agents:
                    return {
                        "status": "failed",
                        "error": f"unknown agent: {agent_id}",
                        "tasks": executed,
                    }
                tid = _new_id("tsk")
                status = "pending"
                error: Optional[str] = None
                if isinstance(payload, dict) and payload.get("raise"):
                    status = "failed"
                    error = "task payload requested failure"
                else:
                    status = "completed"
                task_record = {
                    "id": tid,
                    "agent_id": agent_id,
                    "name": name,
                    "payload": payload,
                    "status": status,
                    "error": error,
                    "created_at": _now_iso(),
                }
                self._tasks[tid] = task_record
                executed.append(dict(task_record))
                if status == "failed":
                    self._save_tasks()
                    return {
                        "status": "failed",
                        "error": error,
                        "tasks": executed,
                    }
            self._save_tasks()
            return {
                "status": "completed",
                "tasks": executed,
            }

    def get_cognitive_state(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._state)

    def update_cognitive_state(self, new_state: str) -> None:
        with self._lock:
            self._state = {"state": new_state, "updated_at": _now_iso()}
            self._save_state()

    def get_attention_manager(self) -> AttentionManager:
        return self._attention

    def get_memory_manager(self) -> MemoryManager:
        return self._memory


_singleton: Optional[CognitionOrchestrator] = None
_singleton_lock = threading.Lock()
_DEFAULT_DIR = "./data/orchestrator"


def get_cognition_orchestrator(storage_dir: Optional[str] = None) -> CognitionOrchestrator:
    global _singleton
    target_dir = storage_dir or _DEFAULT_DIR
    with _singleton_lock:
        if _singleton is None:
            _singleton = CognitionOrchestrator(storage_dir=target_dir)
        return _singleton


def reset_cognition_orchestrator() -> None:
    global _singleton
    with _singleton_lock:
        _singleton = None
