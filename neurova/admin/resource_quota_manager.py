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
from neurova.core.logger import get_logger
import threading
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional
from neurova.core.data_root import dataPath

logger = get_logger(__name__)


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
    "concurrent_session_count": "max_concurrent_sessions",
}


def _validated_limit(value: Any) -> Optional[int]:
    """设置面来的额度值只收 **int ≥ 1**；其余（bool/浮点/字符串/0/负数）一律
    视为未配置（返回 None，调用方回落默认）——判额面不收垃圾。"""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value >= 1 else None


def _username_for_user(user_id: str) -> Optional[str]:
    """user_id → username（组员名册按 username 记账）。查无此人/库不可达返回 None。"""
    try:
        from neurova.auth.user_model import UserModel

        user = UserModel().get_user_by_id(int(str(user_id).strip()))
        if not user:
            return None
        username = getattr(user, "username", None)
        if not username and isinstance(user, dict):
            username = user.get("username")
        return str(username) if username else None
    except Exception:
        return None


def _map_group_quota(quota: Any) -> Dict[str, int]:
    """ResourceQuota 字段 → 管理器额度键（单位对齐：MB→Bytes 两格换算）。

    只映射管理器**有判额闸**的键；组的其余配额字段（内存/每分钟请求/并发
    任务/组员数）暂无对应闸，不伪造覆盖。
    """
    mib = 1024 * 1024
    mapped: Dict[str, int] = {}
    for src, dst, scale in (
        ("max_llm_calls_per_day", "max_llm_calls_per_day", 1),
        ("max_tokens_per_day", "max_llm_tokens_per_day", 1),
        ("max_agents", "max_agents", 1),
        ("max_storage_mb", "max_storage_bytes", mib),
        ("max_file_size_mb", "max_file_size_bytes", mib),
    ):
        v = getattr(quota, src, None)
        if isinstance(v, int) and not isinstance(v, bool) and v >= 1:
            mapped[dst] = v * scale
    return mapped


def _first_nondefault_quota_in_chain(mgr: Any, start_group: Any) -> Optional[Any]:
    """从直接组沿 parent_group_id 向部门根取**第一个非默认**配额
    （子组覆盖、未配置继承父组）；全链默认 → None（不 overlay）。"""
    from neurova.auth.user_group_model import ResourceQuota

    blank = ResourceQuota()
    seen: set = set()
    cursor = start_group
    while cursor is not None and cursor.group_id not in seen:
        seen.add(cursor.group_id)
        q = getattr(cursor, "resource_quota", None)
        if q is not None and q != blank:
            return q
        parent_id = getattr(cursor, "parent_group_id", None)
        cursor = mgr.get_group(parent_id) if parent_id else None
    return None


def _resolve_group_quota_overlay(user_id: str) -> Dict[str, int]:
    """用户所属组（T-A 单主组沿父链继承）的 ResourceQuota → 额度覆盖层。

    组解析与 resolveUserDepartment 同源：组员名册按 username、只认 CUSTOM
    主组。任何失败 fail-soft 返回 {}（不 overlay，回落默认/设置）。
    """
    try:
        from neurova.auth.user_group_model import UserGroupType

        username = _username_for_user(user_id)
        if not username:
            return {}
        mgr = _user_group_manager()
        custom = [
            g
            for g in mgr.get_groups_for_user(username)
            if getattr(g, "group_type", None) == UserGroupType.CUSTOM
        ]
        if not custom:
            return {}
        quota = _first_nondefault_quota_in_chain(mgr, custom[0])
        if quota is None:
            return {}
        return _map_group_quota(quota)
    except Exception as e:  # noqa: BLE001 - 组配额解析失败不阻断判额
        logger.warning("组级配额解析失败（忽略 overlay）: %s", e)
        return {}


def _user_group_manager() -> Any:
    from neurova.auth.user_group_model import get_user_group_manager

    return get_user_group_manager()


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
    concurrent_session_count: int = 0
    # 「每日」两个计数器（llm_call_count / llm_token_count）
    # 的结算窗口 = 自然日 YYYY-MM-DD；空串 = 尚未结算，视为新窗口。
    # 必需是 dataclass 字段：旧实现的锚点 `_last_reset` 不是字段，from_dict 即丢，
    # 跨天结算根本无从判定，且它按「距今 86400 秒」滚动判定——不是每日语义。
    daily_window: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ResourceUsage":
        valid = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**valid)

    def reset_daily_usage(self) -> None:
        self.llm_call_count = 0
        self.llm_token_count = 0

    def check_daily_reset(self, now: Optional[datetime.datetime] = None) -> bool:
        """本副本的「每日」计数是否还在今天；不在则归零并把窗口改到今天。

        返回是否发生了结算——调用方（管理器）据此决定是否落盘。
        为什么由管理器落盘：值对象是账本副本，归零只发生在副本上等于没结算
        （重启后计数原样复活）。
        为什么按自然日、不按「距今 86400 秒」滚动：额度字段的名字就是
        `max_llm_calls_per_day`——「每日配额」的语义是自然日，滚动窗口会让
        昨天下午用满的用户今天上午仍被拒。
        """
        today = (now or datetime.datetime.now()).date().isoformat()
        if self.daily_window == today:
            return False
        self.reset_daily_usage()
        self.daily_window = today
        return True


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
        self._group_limits: Dict[str, Dict[str, int]] = {g: dict(limits) for g, limits in (group_limits or {}).items()}
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
        """取账本副本，副本一律先做自然日结算（有变更即落盘）。

        结算点收口在这里与 `_get_or_create_usage` 两处：判定（_check）、
        消费（try_consume）、记账（_add）、报表（get_quota_status）四条路径
        全部经由这两个函数取数，不再逐点补结算。
        未入账的新副本不落盘——「查一下」不该给用户凭空建一条记录。
        """
        existing = self._usage.get(user_id)
        if existing is None:
            return ResourceUsage(user_id=user_id, group_type=group_type)
        usage = ResourceUsage.from_dict(existing)
        if usage.check_daily_reset():
            self._persist(usage)
        return usage

    def _get_or_create_usage(self, user_id: str, group_type: str = "user") -> ResourceUsage:
        """同 `_peek_usage`；缺记录则先建一条（新建记录也先落窗口标记再落盘）。"""
        if user_id in self._usage:
            return self._peek_usage(user_id, group_type)
        usage = ResourceUsage(user_id=user_id, group_type=group_type)
        usage.check_daily_reset()
        self._persist(usage)
        return usage

    def get_user_quota(self, user_id: str, group_type: str = "user") -> Dict[str, int]:
        with self._lock:
            quota: Dict[str, int] = dict(DEFAULT_LIMITS)
            # 运营设置覆盖（2026-11-14 LLM 日配额运营化）：app_settings.quota
            # 的合法值（int ≥ 1）覆盖硬编码默认，判额时现读——改完即生效。
            # 优先级：硬编码默认 < 运营设置 < custom_limits < group_limits
            # < 用户所属组（组级 ResourceQuota，最具体的额度事实）。
            try:
                from neurova.core.app_settings import get_quota_settings

                for key, value in get_quota_settings().items():
                    if key in DEFAULT_LIMITS:
                        validated = _validated_limit(value)
                        if validated is not None:
                            quota[key] = validated
            except Exception as e:  # noqa: BLE001 - 设置读取失败回退默认
                logger.warning("配额设置读取失败，使用默认值: %s", e)
            quota.update(self._custom_limits)
            if group_type in self._group_limits:
                quota.update(self._group_limits[group_type])
            quota.update(_resolve_group_quota_overlay(user_id))
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

    def check_storage_quota(self, user_id: str, additional_bytes: int = 0) -> Dict[str, Any]:
        with self._lock:
            return self._check(user_id, "storage_bytes", "max_storage_bytes", additional_bytes)

    def check_file_size_quota(self, user_id: str, file_size_bytes: int = 0) -> Dict[str, Any]:
        with self._lock:
            return self._check(user_id, "file_size_bytes", "max_file_size_bytes", file_size_bytes)

    def check_private_skill_quota(self, user_id: str) -> Dict[str, Any]:
        with self._lock:
            return self._check(user_id, "private_skill_count", "max_private_skills")

    def check_collab_project_quota(self, user_id: str) -> Dict[str, Any]:
        with self._lock:
            return self._check(user_id, "collab_project_count", "max_collab_projects")

    def check_concurrent_session_quota(self, user_id: str) -> Dict[str, Any]:
        with self._lock:
            return self._check(user_id, "concurrent_session_count", "max_concurrent_sessions")

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

    def list_users_near_limits(self, threshold: float = 0.8) -> List[Dict[str, Any]]:
        with self._lock:
            results: List[Dict[str, Any]] = []
            for user_id in list(self._usage.keys()):
                usage = self._peek_usage(user_id)
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
                    results.append(
                        {
                            "user_id": user_id,
                            "max_ratio": max_ratio,
                            "ratios": ratios,
                            "usage": usage.to_dict(),
                            "limits": quota,
                        }
                    )
            return results

    def try_consume(self, user_id: str, usage_field: str, limit_field: str) -> bool:
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
            return {uid: self._peek_usage(uid).to_dict() for uid in list(self._usage.keys())}

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            totals = {f: 0 for f in _USAGE_TO_LIMIT.keys()}
            for uid in list(self._usage.keys()):
                u = self._peek_usage(uid)
                for f in totals:
                    totals[f] += int(getattr(u, f, 0))
            return {
                "total_users": len(self._usage),
                "totals": totals,
                "limits": self.get_user_quota("__stats__"),
            }


_singleton: Optional[ResourceQuotaManager] = None
_singleton_lock = threading.Lock()
_DEFAULT_DIR = dataPath("resource_quota")


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
