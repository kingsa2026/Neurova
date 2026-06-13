"""
多Agent协作服务

最小可用实现：基于 JSON 存储的协作计划/任务分配/状态流转/统计。
"""

import datetime
import json
import logging
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


_VALID_PLAN_STATUSES = {"planned", "running", "completed", "failed", "cancelled"}
_VALID_ASSIGNMENT_STATUSES = {"pending", "running", "completed", "failed", "cancelled"}


def _new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex}" if prefix else uuid.uuid4().hex


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class AgentCollaborationService:
    """多Agent协作计划与任务分配服务。"""

    def __init__(self, storage_path: str) -> None:
        self._dir = Path(storage_path)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._plans_path = self._dir / "plans.json"
        self._plans: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()
        self._load()

    def _load(self) -> None:
        if self._plans_path.exists():
            try:
                data = json.loads(self._plans_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self._plans.update(data)
            except Exception as exc:
                logger.warning("Failed to load %s: %s", self._plans_path, exc)

    def _save(self) -> None:
        self._plans_path.write_text(
            json.dumps(self._plans, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _snapshot(self, plan: Dict[str, Any]) -> Dict[str, Any]:
        return {
            **plan,
            "assignments": [dict(a) for a in plan.get("assignments", [])],
        }

    def create_plan(
        self,
        name: str,
        strategy: str = "sequential",
        description: str = "",
        **extra: Any,
    ) -> str:
        with self._lock:
            pid = _new_id("pl_")
            plan = {
                "id": pid,
                "name": name,
                "strategy": strategy,
                "description": description,
                "status": "planned",
                "assignments": [],
                "created_at": _now_iso(),
            }
            plan.update(extra)
            self._plans[pid] = plan
            self._save()
            return pid

    def get_plan(self, plan_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            p = self._plans.get(plan_id)
            if p is None:
                return None
            return self._snapshot(p)

    def list_plans(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._lock:
            plans = list(self._plans.values())
            if status is not None:
                plans = [p for p in plans if p.get("status") == status]
            return [self._snapshot(p) for p in plans]

    def cancel_plan(self, plan_id: str) -> bool:
        with self._lock:
            plan = self._plans.get(plan_id)
            if plan is None:
                return False
            if plan.get("status") == "cancelled":
                return False
            plan["status"] = "cancelled"
            for a in plan.get("assignments", []):
                a["status"] = "cancelled"
                a["updated_at"] = _now_iso()
            plan["updated_at"] = _now_iso()
            self._save()
            return True

    def add_assignment(
        self,
        plan_id: str,
        agent_id: str,
        agent_role: str = "",
        task_description: str = "",
        task_parameters: Optional[Dict[str, Any]] = None,
        priority: int = 0,
        dependencies: Optional[List[str]] = None,
        **extra: Any,
    ) -> str:
        with self._lock:
            plan = self._plans.get(plan_id)
            if plan is None:
                raise KeyError(f"plan not found: {plan_id}")
            aid = _new_id("as_")
            assignment = {
                "id": aid,
                "plan_id": plan_id,
                "agent_id": agent_id,
                "agent_role": agent_role,
                "task_description": task_description,
                "task_parameters": dict(task_parameters) if task_parameters else {},
                "priority": priority,
                "dependencies": list(dependencies) if dependencies else [],
                "status": "pending",
                "execution_time_ms": None,
                "result": None,
                "created_at": _now_iso(),
            }
            assignment.update(extra)
            plan.setdefault("assignments", []).append(assignment)
            self._save()
            return aid

    def get_assignment(self, plan_id: str, assignment_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            plan = self._plans.get(plan_id)
            if plan is None:
                return None
            for a in plan.get("assignments", []):
                if a.get("id") == assignment_id:
                    return dict(a)
            return None

    def list_assignments(self, plan_id: str) -> List[Dict[str, Any]]:
        with self._lock:
            plan = self._plans.get(plan_id)
            if plan is None:
                return []
            return [dict(a) for a in plan.get("assignments", [])]

    def update_assignment(
        self,
        plan_id: str,
        assignment_id: str,
        status: Optional[str] = None,
        **fields: Any,
    ) -> bool:
        with self._lock:
            plan = self._plans.get(plan_id)
            if plan is None:
                return False
            target = None
            for a in plan.get("assignments", []):
                if a.get("id") == assignment_id:
                    target = a
                    break
            if target is None:
                return False
            if status is not None:
                if status not in _VALID_ASSIGNMENT_STATUSES:
                    return False
                target["status"] = status
            for k, v in fields.items():
                target[k] = v
            target["updated_at"] = _now_iso()
            self._save()
            return True

    def get_statistics(self) -> Dict[str, Any]:
        with self._lock:
            total_plans = len(self._plans)
            total_assignments = 0
            completed_assignments = 0
            exec_times: List[float] = []
            for p in self._plans.values():
                for a in p.get("assignments", []):
                    total_assignments += 1
                    if a.get("status") == "completed":
                        completed_assignments += 1
                        et = a.get("execution_time_ms")
                        if et is not None:
                            try:
                                exec_times.append(float(et))
                            except (TypeError, ValueError):
                                pass
            avg = sum(exec_times) / len(exec_times) if exec_times else 0.0
            return {
                "total_plans": total_plans,
                "total_assignments": total_assignments,
                "completed_assignments": completed_assignments,
                "average_execution_time_ms": avg,
            }


_singleton: Optional[AgentCollaborationService] = None
_singleton_lock = threading.Lock()
_DEFAULT_DIR = "./data/agent_colab"


def get_agent_collaboration_service() -> AgentCollaborationService:
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            Path(_DEFAULT_DIR).mkdir(parents=True, exist_ok=True)
            _singleton = AgentCollaborationService(_DEFAULT_DIR)
    return _singleton
