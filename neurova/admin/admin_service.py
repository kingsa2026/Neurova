from __future__ import annotations

import datetime
import json
from neurova.core.logger import get_logger
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = get_logger(__name__)


def _new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex}" if prefix else uuid.uuid4().hex


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _parse_iso(value: Any) -> datetime.datetime:
    if isinstance(value, datetime.datetime):
        return value
    if isinstance(value, str):
        return datetime.datetime.fromisoformat(value)
    return datetime.datetime.now(datetime.timezone.utc)


@dataclass
class UserBackup:
    backup_id: str
    user_id: str
    created_at: datetime.datetime
    backup_path: str
    size_bytes: int
    description: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        ca = self.created_at
        if isinstance(ca, datetime.datetime):
            ca = ca.isoformat()
        return {
            "backup_id": self.backup_id,
            "user_id": self.user_id,
            "created_at": ca,
            "backup_path": self.backup_path,
            "size_bytes": self.size_bytes,
            "description": self.description,
            "metadata": dict(self.metadata) if self.metadata else {},
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UserBackup":
        return cls(
            backup_id=data["backup_id"],
            user_id=data["user_id"],
            created_at=_parse_iso(data.get("created_at")),
            backup_path=data.get("backup_path", ""),
            size_bytes=int(data.get("size_bytes", 0)),
            description=data.get("description", ""),
            metadata=data.get("metadata") or {},
        )


class ResourceQuotaManager:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._usage: Dict[str, Dict[str, int]] = {}
        self._limits: Dict[str, Dict[str, int]] = {}

    def check(self, user_id: str, resource: str) -> bool:
        return True

    def record(self, user_id: str, resource: str, amount: int = 1) -> None:
        bucket = self._usage.setdefault(user_id, {})
        bucket[resource] = bucket.get(resource, 0) + int(amount)

    def get_usage(self, user_id: str) -> Dict[str, int]:
        return dict(self._usage.get(user_id, {}))


class AdminService:
    def __init__(self, storage_dir: str) -> None:
        self._dir = Path(storage_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._users_path = self._dir / "users.json"
        self._backups_path = self._dir / "backups.json"
        self._groups_path = self._dir / "groups.json"
        self._backups_dir = self._dir / "backups"
        self._backups_dir.mkdir(parents=True, exist_ok=True)
        self._users: Dict[str, Dict[str, Any]] = {}
        self._backups: Dict[str, Dict[str, Any]] = {}
        self._groups: Dict[str, Dict[str, Any]] = {"default": {"name": "default", "members": []}}
        self._lock = threading.RLock()
        self._quota = ResourceQuotaManager()
        self._load()

    def _load(self) -> None:
        for path, target in (
            (self._users_path, self._users),
            (self._backups_path, self._backups),
        ):
            if path.exists():
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    if isinstance(data, dict):
                        target.update(data)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Failed to load %s: %s", path, exc)
        if self._groups_path.exists():
            try:
                data = json.loads(self._groups_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self._groups.update(data)
            except Exception:  # noqa: BLE001
                pass

    def _save(self) -> None:
        self._users_path.write_text(
            json.dumps(self._users, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._backups_path.write_text(
            json.dumps(self._backups, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._groups_path.write_text(
            json.dumps(self._groups, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _username_exists(self, username: str, exclude_id: Optional[str] = None) -> bool:
        for uid, u in self._users.items():
            if uid == exclude_id:
                continue
            if u.get("username") == username:
                return True
        return False

    def create_user(
        self,
        username: str,
        email: str = "",
        password: Optional[str] = None,
        role: str = "user",
        group: str = "default",
        **extra: Any,
    ) -> Dict[str, Any]:
        with self._lock:
            if self._username_exists(username):
                raise ValueError(f"Username already exists: {username}")
            uid = _new_id("usr_")
            user: Dict[str, Any] = {
                "id": uid,
                "username": username,
                "email": email,
                "password_hash": password or "",
                "role": role,
                "status": "active",
                "group": group,
                "created_at": _now_iso(),
            }
            user.update(extra)
            self._users[uid] = user
            grp = self._groups.setdefault(group, {"name": group, "members": []})
            members = grp.setdefault("members", [])
            if uid not in members:
                members.append(uid)
            self._quota.record(uid, "user_created", 1)
            self._save()
            return dict(user)

    def update_user(self, user_id: str, **fields: Any) -> bool:
        with self._lock:
            if user_id not in self._users:
                return False
            user = self._users[user_id]
            new_username = fields.get("username")
            if (
                new_username is not None
                and new_username != user.get("username")
                and self._username_exists(new_username, exclude_id=user_id)
            ):
                raise ValueError(f"Username already exists: {new_username}")
            new_group = fields.get("group")
            if new_group is not None and new_group != user.get("group"):
                old_group = user.get("group", "default")
                old_members = self._groups.get(old_group, {}).get("members", [])
                if user_id in old_members:
                    old_members.remove(user_id)
                grp = self._groups.setdefault(new_group, {"name": new_group, "members": []})
                new_members = grp.setdefault("members", [])
                if user_id not in new_members:
                    new_members.append(user_id)
            for k, v in fields.items():
                user[k] = v
            user["updated_at"] = _now_iso()
            self._save()
            return True

    def delete_user(self, user_id: str) -> Dict[str, Any]:
        with self._lock:
            if user_id not in self._users:
                raise ValueError(f"User not found: {user_id}")
            user = self._users.pop(user_id)
            group = user.get("group", "default")
            members = self._groups.get(group, {}).get("members", [])
            if user_id in members:
                members.remove(user_id)
            self._save()
            return {
                "user_id": user_id,
                "deleted": True,
                "username": user.get("username"),
            }

    def get_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            u = self._users.get(user_id)
            return dict(u) if u else None

    def list_users(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(u) for u in self._users.values()]

    def backup_user(self, user_id: str, description: str = "") -> UserBackup:
        with self._lock:
            if user_id not in self._users:
                raise ValueError(f"User not found: {user_id}")
            user = self._users[user_id]
            backup_id = _new_id("bk_")
            backup_file = self._backups_dir / f"{backup_id}.json"
            snapshot = dict(user)
            payload = {
                "backup_id": backup_id,
                "user_id": user_id,
                "snapshot": snapshot,
                "created_at": _now_iso(),
                "description": description,
            }
            backup_file.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            size_bytes = backup_file.stat().st_size
            created_at = datetime.datetime.now(datetime.timezone.utc)
            entry: Dict[str, Any] = {
                "backup_id": backup_id,
                "user_id": user_id,
                "created_at": created_at.isoformat(),
                "backup_path": str(backup_file),
                "size_bytes": size_bytes,
                "description": description,
                "metadata": {"snapshot": snapshot},
            }
            self._backups[backup_id] = entry
            self._save()
            return UserBackup.from_dict(entry)

    def list_backups(self, user_id: Optional[str] = None) -> List[UserBackup]:
        with self._lock:
            items: List[UserBackup] = []
            for b in self._backups.values():
                if user_id is not None and b.get("user_id") != user_id:
                    continue
                items.append(UserBackup.from_dict(b))
            items.sort(key=lambda x: x.created_at)
            return items

    def delete_backup(self, backup_id: str) -> bool:
        with self._lock:
            entry = self._backups.pop(backup_id, None)
            if entry is None:
                return False
            try:
                p = Path(entry.get("backup_path", ""))
                if p.exists():
                    p.unlink()
            except Exception:  # noqa: BLE001
                pass
            self._save()
            return True

    def restore_user(self, backup_id: str) -> Dict[str, Any]:
        with self._lock:
            if backup_id not in self._backups:
                raise ValueError(f"Backup not found: {backup_id}")
            entry = self._backups[backup_id]
            user_id = entry.get("user_id")
            metadata = entry.get("metadata") or {}
            snapshot = metadata.get("snapshot") if isinstance(metadata, dict) else None
            if not user_id or not isinstance(snapshot, dict):
                raise ValueError("Backup snapshot is empty")
            self._users[user_id] = dict(snapshot)
            self._save()
            return {
                "user_id": user_id,
                "restored": True,
                "backup_id": backup_id,
            }

    def get_system_stats(self) -> Dict[str, Any]:
        with self._lock:
            total_users = len(self._users)
            group_stats: Dict[str, Any] = {}
            for gname, gdata in self._groups.items():
                members = gdata.get("members", []) if isinstance(gdata, dict) else []
                group_stats[gname] = {
                    "name": gname,
                    "count": len(members),
                    "members": list(members),
                }
            return {
                "total_users": total_users,
                "total_backups": len(self._backups),
                "group_stats": group_stats,
            }


_singleton: Optional[AdminService] = None
_singleton_lock = threading.Lock()
_DEFAULT_DIR = "./data/admin"


def get_admin_service() -> AdminService:
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            Path(_DEFAULT_DIR).mkdir(parents=True, exist_ok=True)
            _singleton = AdminService(_DEFAULT_DIR)
    return _singleton
