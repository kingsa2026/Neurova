"""
Neurova 增强用户模型

功能:
1. 用户与本地 GroupType 关联（不依赖 user_group_model）
2. 基于组的权限与配额管理（本地实现，不依赖 resource_quota_manager）
3. 用户状态管理（active / inactive / locked）
4. 用户资料管理与登录审计
5. JSON 文件持久化 + 线程安全（RLock）
6. 密码使用 pbkdf2_hmac(sha256, 100k iters) + 随机 salt
"""

import base64
import binascii
import datetime
import hashlib
import hmac
import json
import logging
import secrets
import threading
import uuid
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional


logger = logging.getLogger(__name__)


DEFAULT_GROUP_TYPE = "user"
PASSWORD_ALGO = "pbkdf2_sha256"
PBKDF2_ITERATIONS = 100_000
PBKDF2_SALT_BYTES = 16
PBKDF2_KEY_BYTES = 32
LOCKOUT_THRESHOLD = 5
LOCKOUT_DURATION_MINUTES = 30
MAX_FAILED_ATTEMPTS_CAP = 10
DEFAULT_LOG_LIMIT = 200


class GroupType(str, Enum):
    USER = "user"
    ADMIN = "admin"
    GUEST = "guest"
    PREMIUM = "premium"
    DEVELOPER = "developer"


GROUP_PERMISSIONS: Dict[str, List[str]] = {
    GroupType.USER.value: [
        "read", "write", "profile.edit", "content.create",
    ],
    GroupType.ADMIN.value: [
        "read", "write", "delete", "admin",
        "manage_users", "manage_projects", "manage_settings",
        "content.create", "content.delete",
    ],
    GroupType.GUEST.value: ["read"],
    GroupType.PREMIUM.value: [
        "read", "write", "premium", "content.create", "profile.edit",
    ],
    GroupType.DEVELOPER.value: [
        "read", "write", "delete", "developer",
        "api.access", "content.create", "profile.edit",
    ],
}

DEFAULT_GROUP_PERMISSIONS: List[str] = list(GROUP_PERMISSIONS[GroupType.USER.value])


GROUP_QUOTAS: Dict[str, Dict[str, int]] = {
    GroupType.USER.value: {
        "storage_mb": 1024,
        "api_calls_per_day": 5000,
        "projects": 5,
    },
    GroupType.ADMIN.value: {
        "storage_mb": 102400,
        "api_calls_per_day": 100000,
        "projects": 500,
    },
    GroupType.GUEST.value: {
        "storage_mb": 100,
        "api_calls_per_day": 1000,
        "projects": 1,
    },
    GroupType.PREMIUM.value: {
        "storage_mb": 51200,
        "api_calls_per_day": 50000,
        "projects": 100,
    },
    GroupType.DEVELOPER.value: {
        "storage_mb": 10240,
        "api_calls_per_day": 20000,
        "projects": 50,
    },
}


def _new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex}" if prefix else uuid.uuid4().hex


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _now_plus_minutes(minutes: int) -> str:
    return (
        datetime.datetime.now(datetime.timezone.utc)
        + datetime.timedelta(minutes=minutes)
    ).isoformat()


def _hash_password(password: str) -> str:
    if not isinstance(password, str) or not password:
        raise ValueError("password must be a non-empty string")
    salt = secrets.token_bytes(PBKDF2_SALT_BYTES)
    derived = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PBKDF2_ITERATIONS,
        dklen=PBKDF2_KEY_BYTES,
    )
    return (
        f"{PASSWORD_ALGO}${PBKDF2_ITERATIONS}$"
        f"{base64.b64encode(salt).decode('ascii')}$"
        f"{base64.b64encode(derived).decode('ascii')}"
    )


def _verify_password(password: str, stored_hash: str) -> bool:
    if not stored_hash or not isinstance(stored_hash, str):
        return False
    try:
        parts = stored_hash.split("$", 3)
        if len(parts) != 4:
            return False
        algo, iters_str, salt_b64, hash_b64 = parts
    except (AttributeError, ValueError):
        return False
    if algo != PASSWORD_ALGO:
        return False
    try:
        iterations = int(iters_str)
        salt = base64.b64decode(salt_b64.encode("ascii"))
        expected = base64.b64decode(hash_b64.encode("ascii"))
    except (ValueError, binascii.Error, UnicodeDecodeError):
        return False
    if iterations <= 0 or not salt or not expected:
        return False
    derived = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
        dklen=len(expected),
    )
    return hmac.compare_digest(derived, expected)


def _default_quota(group_type: str) -> Dict[str, int]:
    return dict(GROUP_QUOTAS.get(group_type, GROUP_QUOTAS[GroupType.USER.value]))


def _coerce_group_type(value: Optional[str]) -> str:
    if not value:
        return DEFAULT_GROUP_TYPE
    val = str(value)
    if val in GROUP_PERMISSIONS:
        return val
    try:
        return GroupType(val).value
    except ValueError:
        return DEFAULT_GROUP_TYPE


def _parse_iso(value: Optional[str]) -> Optional[datetime.datetime]:
    if not value or not isinstance(value, str):
        return None
    try:
        dt = datetime.datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


class EnhancedUserModel:
    """增强用户模型服务。"""

    _PROFILE_FIELDS = frozenset({
        "display_name", "bio", "avatar_url", "email",
        "group_type", "status", "metadata", "password_hash",
    })

    def __init__(self, storage_dir: str) -> None:
        self._dir = Path(storage_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._users_path = self._dir / "users.json"
        self._logs_path = self._dir / "login_logs.json"
        self._quotas_path = self._dir / "quotas.json"
        self._users: Dict[str, Dict[str, Any]] = {}
        self._logs: List[Dict[str, Any]] = []
        self._quotas: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()
        self._load()

    def _load(self) -> None:
        self._load_dict(self._users_path, self._users)
        self._load_list(self._logs_path, self._logs)
        self._load_dict(self._quotas_path, self._quotas)

    def _load_dict(self, path: Path, target: Dict[str, Dict[str, Any]]) -> None:
        if not path.exists():
            return
        try:
            text = path.read_text(encoding="utf-8")
            if not text.strip():
                return
            data = json.loads(text)
            if isinstance(data, dict):
                target.update(data)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Failed to load %s: %s", path, exc)

    def _load_list(self, path: Path, target: List[Dict[str, Any]]) -> None:
        if not path.exists():
            return
        try:
            text = path.read_text(encoding="utf-8")
            if not text.strip():
                return
            data = json.loads(text)
            if isinstance(data, list):
                target.extend(data)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Failed to load %s: %s", path, exc)

    def _save(self) -> None:
        self._users_path.write_text(
            json.dumps(self._users, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._logs_path.write_text(
            json.dumps(self._logs, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._quotas_path.write_text(
            json.dumps(self._quotas, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _build_user(
        self,
        username: str,
        email: str,
        password: str,
        group_type: str,
    ) -> Dict[str, Any]:
        uid = _new_id("usr_")
        now = _now_iso()
        gtype = _coerce_group_type(group_type)
        return {
            "id": uid,
            "username": username,
            "email": email,
            "password_hash": _hash_password(password),
            "display_name": username,
            "bio": "",
            "avatar_url": "",
            "group_type": gtype,
            "status": "active",
            "failed_attempts": 0,
            "locked_until": None,
            "last_login": None,
            "last_active": None,
            "metadata": {},
            "created_at": now,
            "updated_at": now,
        }

    def _build_quota(self, user_id: str, group_type: str) -> Dict[str, Any]:
        gtype = _coerce_group_type(group_type)
        return {
            "user_id": user_id,
            "group_type": gtype,
            "quota": _default_quota(gtype),
            "usage": {
                "storage_mb": 0,
                "api_calls_per_day": 0,
                "api_calls_today": 0,
                "projects": 0,
            },
            "updated_at": _now_iso(),
        }

    def _username_exists(self, username: str) -> bool:
        return any(u.get("username") == username for u in self._users.values())

    def _email_exists(self, email: str) -> bool:
        if not email:
            return False
        return any(u.get("email") == email for u in self._users.values())

    # -- create --

    def create_user(
        self,
        username: str,
        password: str,
        email: str,
        group_type: str = DEFAULT_GROUP_TYPE,
    ) -> Optional[Dict[str, Any]]:
        if not username or not isinstance(username, str):
            return None
        if not password or not isinstance(password, str):
            return None
        with self._lock:
            if self._username_exists(username):
                return None
            if email and self._email_exists(email):
                return None
            gtype = _coerce_group_type(group_type)
            user = self._build_user(username, email, password, gtype)
            self._users[user["id"]] = user
            self._quotas[user["id"]] = self._build_quota(user["id"], gtype)
            self._save()
            return dict(user)

    # -- read --

    def get_user_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        if not user_id:
            return None
        with self._lock:
            u = self._users.get(user_id)
            return dict(u) if u else None

    def get_user_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        if not username:
            return None
        with self._lock:
            for u in self._users.values():
                if u.get("username") == username:
                    return dict(u)
            return None

    def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        if not email:
            return None
        with self._lock:
            for u in self._users.values():
                if u.get("email") == email:
                    return dict(u)
            return None

    def list_users(
        self,
        group_type: Optional[str] = None,
        status: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        with self._lock:
            items = list(self._users.values())
        if group_type is not None:
            target = _coerce_group_type(group_type)
            items = [u for u in items if u.get("group_type") == target]
        if status is not None:
            items = [u for u in items if u.get("status") == status]
        items.sort(key=lambda u: u.get("created_at", ""))
        if limit is not None and limit >= 0:
            items = items[:limit]
        return [dict(u) for u in items]

    def count_users(
        self,
        group_type: Optional[str] = None,
        status: Optional[str] = None,
    ) -> int:
        return len(self.list_users(group_type=group_type, status=status))

    # -- update --

    def update_user(self, user_id: str, **fields: Any) -> bool:
        if not user_id or not fields:
            return False
        with self._lock:
            u = self._users.get(user_id)
            if not u:
                return False
            group_changed = False
            for k, v in fields.items():
                if k in self._PROFILE_FIELDS:
                    if k == "group_type":
                        new_gtype = _coerce_group_type(v)
                        if new_gtype != u.get("group_type"):
                            u[k] = new_gtype
                            group_changed = True
                    else:
                        u[k] = v
            if group_changed and user_id in self._quotas:
                gtype = u.get("group_type") or DEFAULT_GROUP_TYPE
                self._quotas[user_id]["group_type"] = gtype
                self._quotas[user_id]["quota"] = _default_quota(gtype)
                self._quotas[user_id]["updated_at"] = _now_iso()
            u["updated_at"] = _now_iso()
            self._save()
            return True

    def delete_user(self, user_id: str) -> bool:
        if not user_id:
            return False
        with self._lock:
            existed = self._users.pop(user_id, None) is not None
            if existed:
                self._quotas.pop(user_id, None)
                self._save()
            return existed

    # -- auth --

    def authenticate_user(
        self, username: str, password: str
    ) -> Optional[Dict[str, Any]]:
        if not username or password is None:
            return None
        with self._lock:
            user = None
            for u in self._users.values():
                if u.get("username") == username:
                    user = u
                    break
            if user is None:
                return None
            if user.get("status") != "active":
                return None
            locked_until = _parse_iso(user.get("locked_until"))
            now_utc = datetime.datetime.now(datetime.timezone.utc)
            if locked_until is not None and locked_until > now_utc:
                return None
            if locked_until is not None and locked_until <= now_utc:
                user["locked_until"] = None
                if user.get("status") == "locked":
                    user["status"] = "active"
            password_ok = _verify_password(
                password, user.get("password_hash") or ""
            )
            if not password_ok:
                self._increment_failed_attempts(user)
                return None
            self._reset_failed_attempts(user)
            self._update_last_login(user)
            self._save()
            return dict(user)

    def _increment_failed_attempts(self, user: Dict[str, Any]) -> None:
        current = int(user.get("failed_attempts") or 0) + 1
        if current > MAX_FAILED_ATTEMPTS_CAP:
            current = MAX_FAILED_ATTEMPTS_CAP
        user["failed_attempts"] = current
        if current >= LOCKOUT_THRESHOLD:
            user["status"] = "locked"
            user["locked_until"] = _now_plus_minutes(LOCKOUT_DURATION_MINUTES)
        self._save()

    def _reset_failed_attempts(self, user: Dict[str, Any]) -> None:
        user["failed_attempts"] = 0
        user["locked_until"] = None
        if user.get("status") == "locked":
            user["status"] = "active"

    def _update_last_login(self, user: Dict[str, Any]) -> None:
        stamp = _now_iso()
        user["last_login"] = stamp
        user["last_active"] = stamp

    def update_last_active(self, user_id: str) -> Optional[bool]:
        if not user_id:
            return None
        with self._lock:
            u = self._users.get(user_id)
            if not u:
                return None
            u["last_active"] = _now_iso()
            u["updated_at"] = _now_iso()
            self._save()
            return True

    # -- logs --

    def log_login(
        self,
        user_id: str,
        username: str,
        ip_address: str = "",
        success: bool = True,
        reason: str = "",
    ) -> str:
        with self._lock:
            lid = _new_id("log_")
            entry = {
                "id": lid,
                "user_id": user_id or "",
                "username": username or "",
                "ip_address": ip_address or "",
                "success": bool(success),
                "reason": reason or "",
                "timestamp": _now_iso(),
            }
            self._logs.append(entry)
            self._save()
            return lid

    def get_login_logs(
        self,
        user_id: Optional[str] = None,
        username: Optional[str] = None,
        success: Optional[bool] = None,
        limit: int = DEFAULT_LOG_LIMIT,
    ) -> List[Dict[str, Any]]:
        if limit is None or limit < 0:
            limit = DEFAULT_LOG_LIMIT
        with self._lock:
            items = list(self._logs)
        if user_id is not None:
            items = [x for x in items if x.get("user_id") == user_id]
        if username is not None:
            items = [x for x in items if x.get("username") == username]
        if success is not None:
            items = [x for x in items if x.get("success") == success]
        return [dict(x) for x in items[-limit:]]

    # -- permissions --

    def get_user_permissions(self, user_id: str) -> List[str]:
        if not user_id:
            return []
        with self._lock:
            u = self._users.get(user_id)
            if not u:
                return []
            gtype = u.get("group_type") or DEFAULT_GROUP_TYPE
        return list(GROUP_PERMISSIONS.get(gtype, DEFAULT_GROUP_PERMISSIONS))

    def check_user_permission(self, user_id: str, permission: str) -> bool:
        if not permission:
            return False
        return permission in self.get_user_permissions(user_id)

    def get_user_groups(self, user_id: str) -> List[str]:
        if not user_id:
            return []
        with self._lock:
            u = self._users.get(user_id)
            if not u:
                return []
            gtype = u.get("group_type") or DEFAULT_GROUP_TYPE
        return [gtype]

    # -- quota (local, no cross-import) --

    def get_user_quota(self, user_id: str) -> Optional[Dict[str, Any]]:
        if not user_id:
            return None
        with self._lock:
            q = self._quotas.get(user_id)
            if q:
                return dict(q)
            u = self._users.get(user_id)
            if not u:
                return None
            gtype = u.get("group_type") or DEFAULT_GROUP_TYPE
            q = self._build_quota(user_id, gtype)
            self._quotas[user_id] = q
            self._save()
            return dict(q)

    def get_user_usage(self, user_id: str) -> Dict[str, Any]:
        quota = self.get_user_quota(user_id)
        if not quota:
            return {
                "storage_mb": 0,
                "api_calls_per_day": 0,
                "api_calls_today": 0,
                "projects": 0,
            }
        return dict(quota.get("usage") or {})

    def get_user_quota_status(self, user_id: str) -> Dict[str, Any]:
        quota = self.get_user_quota(user_id)
        if not quota:
            return {
                "exists": False,
                "user_id": user_id,
                "quota": None,
                "usage": None,
                "ratios": {},
            }
        q = dict(quota.get("quota") or {})
        u = dict(quota.get("usage") or {})
        ratios: Dict[str, float] = {}
        for k, v in q.items():
            if isinstance(v, (int, float)) and v:
                used = float(u.get(k, 0))
                ratios[k] = round(used / float(v), 4)
        return {
            "exists": True,
            "user_id": user_id,
            "group_type": quota.get("group_type"),
            "quota": q,
            "usage": u,
            "ratios": ratios,
        }

    def record_usage(
        self,
        user_id: str,
        storage_mb: int = 0,
        api_calls: int = 0,
        projects: int = 0,
    ) -> bool:
        if not user_id:
            return False
        with self._lock:
            q = self._quotas.get(user_id)
            if not q:
                u = self._users.get(user_id)
                if not u:
                    return False
                gtype = u.get("group_type") or DEFAULT_GROUP_TYPE
                q = self._build_quota(user_id, gtype)
                self._quotas[user_id] = q
            usage = q.setdefault("usage", {})
            usage["storage_mb"] = int(usage.get("storage_mb", 0)) + int(storage_mb)
            usage["api_calls_per_day"] = int(usage.get("api_calls_per_day", 0)) + int(api_calls)
            usage["api_calls_today"] = int(usage.get("api_calls_today", 0)) + int(api_calls)
            usage["projects"] = int(usage.get("projects", 0)) + int(projects)
            q["updated_at"] = _now_iso()
            self._save()
            return True


# ============== 全局单例 ==============

_singleton: Optional[EnhancedUserModel] = None
_singleton_lock = threading.Lock()
_DEFAULT_DIR = "./data/enhanced_user_model"


def get_enhanced_user_model() -> EnhancedUserModel:
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            Path(_DEFAULT_DIR).mkdir(parents=True, exist_ok=True)
            _singleton = EnhancedUserModel(_DEFAULT_DIR)
    return _singleton
