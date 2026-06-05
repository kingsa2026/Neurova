"""
Neurova 资源配额管理器

功能:
1. 检查用户资源配额（Agent数量、项目数量、LLM调用次数等）
2. 记录资源使用量
3. 配额超限时拒绝操作
4. 支持按用户组配置不同的配额
"""

import datetime
import json
import logging
import threading
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


logger = logging.getLogger(__name__)


def _new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex}" if prefix else uuid.uuid4().hex


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


DEFAULT_LIMITS: Dict[str, int] = {
    "max_agents": 5,
    "max_projects": 10,
    "max_llm_calls_per_day": 100,
    "max_llm_tokens_per_day": 100_000,
    "max_storage_bytes": 10 * 1024 * 1024 * 1024,
    "max_file_size_bytes": 100 * 1024 * 1024,
    "max_private_skills": 20,
    "max_collab_projects": 5,
    "max_api_calls_per_minute": 60,
    "max_concurrent_sessions": 5,
}


_USAGE_TO_LIMIT: Dict[str, str] = {
    "agent_count": "max_agents",
    "project_count": "max_projects",
    "llm_call_count": "max_llm_calls_per_day",
    "llm_token_count": "max_llm_tokens_per_day",
    "storage_bytes": "max_storage_bytes",
    "file_size_bytes": "max_file_size_bytes",
    "private_skill_count": "max_private_skills",
    "collab_project_count": "max_collab_projects",
    "api_call_count": "max_api_calls_per_minute",
    "concurrent_session_count": "max_concurrent_sessions",
}


@dataclass
class ResourceUsage:
    user_id: str
    group_type: str = "user"
    agent_count: int = 0
    project_count: int = 0
    llm_call_count: int = 0
    llm_token_count: int = 0
    storage_bytes: int = 0
    file_size_bytes: int = 0
    private_skill_count: int = 0
    collab_project_count: int = 0
    api_call_count: int = 0
    concurrent_session_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ResourceUsage":
        valid = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**valid)

    def reset_daily_usage(self) -> None:
        self.llm_call_count = 0
        self.llm_token_count = 0
        self.api_call_count = 0

    def check_daily_reset(self, now: Optional[datetime.datetime] = None) -> bool:
        last = getattr(self, "_last_reset", None)
        if now is None:
            now = datetime.datetime.now(datetime.timezone.utc)
        if last is None or (now - last).total_seconds() >= 86400:
            self.reset_daily_usage()
            self._last_reset = now
            return True
        return False


class ResourceQuotaManager:
    def __init__(
        self,
        storage_dir: str,
        custom_limits: Optional[Dict[str, int]] = None,
        group_limits: Optional[Dict[str, Dict[str, int]]] = None,
    ) -> None:
        self._dir = Path(storage_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._usage_path = self._dir / "usage.json"
        self._usage: Dict[str, Dict[str, Any]] = {}
        self._custom_limits: Dict[str, int] = dict(custom_limits) if custom_limits else {}
        self._group_limits: Dict[str, Dict[str, int]] = {
            g: dict(limits) for g, limits in (group_limits or {}).items()
        }
        self._lock = threading.RLock()
        self._load()

    def _load(self) -> None:
        if not self._usage_path.exists():
            return
        try:
            data = json.loads(self._usage_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self._usage.update(data)
        except Exception as exc:
            logger.warning("Failed to load %s: %s", self._usage_path, exc)

    def _save(self) -> None:
        self._usage_path.write_text(
            json.dumps(self._usage, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _persist(self, usage: ResourceUsage) -> None:
        self._usage[usage.user_id] = usage.to_dict()
        self._save()

    def _peek_usage(self, user_id: str, group_type: str = "user") -> ResourceUsage:
        existing = self._usage.get(user_id)
        if existing is not None:
            return ResourceUsage.from_dict(existing)
        return ResourceUsage(user_id=user_id, group_type=group_type)

    def _get_or_create_usage(
        self, user_id: str, group_type: str = "user"
    ) -> ResourceUsage:
        existing = self._usage.get(user_id)
        if existing is not None:
            return ResourceUsage.from_dict(existing)
        usage = ResourceUsage(user_id=user_id, group_type=group_type)
        self._persist(usage)
        return usage

    def get_user_quota(
        self, user_id: str, group_type: str = "user"
    ) -> Dict[str, int]:
        with self._lock:
            quota: Dict[str, int] = dict(DEFAULT_LIMITS)
            quota.update(self._custom_limits)
            if group_type in self._group_limits:
                quota.update(self._group_limits[group_type])
            return quota

    def get_usage(self, user_id: str) -> ResourceUsage:
        with self._lock:
            return self._peek_usage(user_id)

    def _check(
        self,
        user_id: str,
        usage_field: str,
        limit_field: str,
        additional: int = 0,
    ) -> Dict[str, Any]:
        quota = self.get_user_quota(user_id)
        usage = self._peek_usage(user_id)
        limit = int(quota.get(limit_field, 0))
        current = int(getattr(usage, usage_field, 0))
        projected = current + max(0, int(additional))
        if projected >= limit:
            return {
                "allowed": False,
                "reason": f"{usage_field} {projected} >= {limit_field} {limit}",
                "current": current,
                "projected": projected,
                "limit": limit,
            }
        return {
            "allowed": True,
            "current": current,
            "projected": projected,
            "limit": limit,
        }

    def check_agent_quota(self, user_id: str) -> Dict[str, Any]:
        with self._lock:
            return self._check(user_id, "agent_count", "max_agents")

    def check_project_quota(self, user_id: str) -> Dict[str, Any]:
        with self._lock:
            return self._check(user_id, "project_count", "max_projects")

    def check_llm_call_quota(self, user_id: str) -> Dict[str, Any]:
        with self._lock:
            return self._check(user_id, "llm_call_count", "max_llm_calls_per_day")

    def check_llm_token_quota(self, user_id: str) -> Dict[str, Any]:
        with self._lock:
            return self._check(user_id, "llm_token_count", "max_llm_tokens_per_day")

    def check_storage_quota(
        self, user_id: str, additional_bytes: int = 0
    ) -> Dict[str, Any]:
        with self._lock:
            return self._check(
                user_id, "storage_bytes", "max_storage_bytes", additional_bytes
            )

    def check_file_size_quota(
        self, user_id: str, file_size_bytes: int = 0
    ) -> Dict[str, Any]:
        with self._lock:
            return self._check(
                user_id, "file_size_bytes", "max_file_size_bytes", file_size_bytes
            )

    def check_private_skill_quota(self, user_id: str) -> Dict[str, Any]:
        with self._lock:
            return self._check(user_id, "private_skill_count", "max_private_skills")

    def check_collab_project_quota(self, user_id: str) -> Dict[str, Any]:
        with self._lock:
            return self._check(
                user_id, "collab_project_count", "max_collab_projects"
            )

    def check_api_call_quota(self, user_id: str) -> Dict[str, Any]:
        with self._lock:
            return self._check(
                user_id, "api_call_count", "max_api_calls_per_minute"
            )

    def check_concurrent_session_quota(self, user_id: str) -> Dict[str, Any]:
        with self._lock:
            return self._check(
                user_id, "concurrent_session_count", "max_concurrent_sessions"
            )

    def _add(self, user_id: str, field: str, delta: int, floor: int = 0) -> None:
        with self._lock:
            usage = self._get_or_create_usage(user_id)
            current = int(getattr(usage, field, 0))
            new_value = max(floor, current + int(delta))
            setattr(usage, field, new_value)
            self._persist(usage)

    def increment_agent_count(self, user_id: str) -> None:
        self._add(user_id, "agent_count", 1)

    def decrement_agent_count(self, user_id: str) -> None:
        self._add(user_id, "agent_count", -1, floor=0)

    def increment_project_count(self, user_id: str) -> None:
        self._add(user_id, "project_count", 1)

    def decrement_project_count(self, user_id: str) -> None:
        self._add(user_id, "project_count", -1, floor=0)

    def increment_llm_call(self, user_id: str, count: int = 1) -> None:
        self._add(user_id, "llm_call_count", count, floor=0)

    def increment_llm_token(self, user_id: str, tokens: int = 0) -> None:
        self._add(user_id, "llm_token_count", tokens, floor=0)

    def increment_storage(self, user_id: str, num_bytes: int) -> None:
        self._add(user_id, "storage_bytes", num_bytes, floor=0)

    def decrement_storage(self, user_id: str, num_bytes: int) -> None:
        self._add(user_id, "storage_bytes", -abs(int(num_bytes)), floor=0)

    def increment_file_size(self, user_id: str, num_bytes: int = 0) -> None:
        self._add(user_id, "file_size_bytes", num_bytes, floor=0)

    def increment_private_skill_count(self, user_id: str) -> None:
        self._add(user_id, "private_skill_count", 1)

    def decrement_private_skill_count(self, user_id: str) -> None:
        self._add(user_id, "private_skill_count", -1, floor=0)

    def increment_api_call(self, user_id: str, count: int = 1) -> None:
        self._add(user_id, "api_call_count", count, floor=0)

    def reset_api_call(self, user_id: str) -> None:
        self._add(user_id, "api_call_count", 0)
        with self._lock:
            usage = self._get_or_create_usage(user_id)
            usage.api_call_count = 0
            self._persist(usage)

    def increment_concurrent_session(self, user_id: str) -> None:
        self._add(user_id, "concurrent_session_count", 1)

    def decrement_concurrent_session(self, user_id: str) -> None:
        self._add(user_id, "concurrent_session_count", -1, floor=0)

    def increment_collab_project_count(self, user_id: str) -> None:
        self._add(user_id, "collab_project_count", 1)

    def decrement_collab_project_count(self, user_id: str) -> None:
        self._add(user_id, "collab_project_count", -1, floor=0)

    def get_quota_status(self, user_id: str) -> Dict[str, Any]:
        with self._lock:
            quota = self.get_user_quota(user_id)
            usage = self._get_or_create_usage(user_id)
            return {
                "user_id": user_id,
                "limits": quota,
                "usage": usage.to_dict(),
            }

    def list_users_near_limits(
        self, threshold: float = 0.8
    ) -> List[Dict[str, Any]]:
        with self._lock:
            results: List[Dict[str, Any]] = []
            for user_id, payload in self._usage.items():
                usage = ResourceUsage.from_dict(payload)
                quota = self.get_user_quota(user_id, group_type=usage.group_type)
                ratios: Dict[str, float] = {}
                for usage_field, limit_field in _USAGE_TO_LIMIT.items():
                    value = int(getattr(usage, usage_field, 0))
                    limit = int(quota.get(limit_field, 0))
                    if limit > 0:
                        ratios[usage_field] = value / limit
                if not ratios:
                    continue
                max_ratio = max(ratios.values())
                if max_ratio >= threshold:
                    results.append({
                        "user_id": user_id,
                        "max_ratio": max_ratio,
                        "ratios": ratios,
                        "usage": usage.to_dict(),
                        "limits": quota,
                    })
            return results

    def try_consume(
        self, user_id: str, usage_field: str, limit_field: str
    ) -> bool:
        with self._lock:
            quota = self.get_user_quota(user_id)
            usage = self._get_or_create_usage(user_id)
            limit = int(quota.get(limit_field, 0))
            current = int(getattr(usage, usage_field, 0))
            if current >= limit:
                return False
            setattr(usage, usage_field, current + 1)
            self._persist(usage)
            return True

    def reset_user(self, user_id: str) -> None:
        with self._lock:
            if user_id in self._usage:
                del self._usage[user_id]
                self._save()

    def reset_all(self) -> None:
        with self._lock:
            self._usage.clear()
            self._save()

    def get_all_usage(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            return {
                uid: ResourceUsage.from_dict(data).to_dict()
                for uid, data in self._usage.items()
            }

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            totals = {f: 0 for f in _USAGE_TO_LIMIT.keys()}
            for data in self._usage.values():
                u = ResourceUsage.from_dict(data)
                for f in totals:
                    totals[f] += int(getattr(u, f, 0))
            return {
                "total_users": len(self._usage),
                "totals": totals,
                "limits": self.get_user_quota("__stats__"),
            }


_singleton: Optional[ResourceQuotaManager] = None
_singleton_lock = threading.Lock()
_DEFAULT_DIR = "./data/resource_quota"


def get_resource_quota_manager() -> ResourceQuotaManager:
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            Path(_DEFAULT_DIR).mkdir(parents=True, exist_ok=True)
            _singleton = ResourceQuotaManager(_DEFAULT_DIR)
    return _singleton


def reset_resource_quota_manager() -> None:
    global _singleton
    with _singleton_lock:
        _singleton = None
