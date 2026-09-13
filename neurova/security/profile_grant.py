"""camofox 登录态 profile 附身授权（CUA Phase 3 立项 R3-4，docs/Neurova_CUA_Phase3立项_2026-09-12.md §3）

camofox 后端携带用户真实网站登录态（profiles + cookies 跨会话保留）。agent 以
该 profile 对外操作 = 以用户身份行动，属不可逆/外部可见动作，使用前必须显式授权。

模型（镜像 mcp_grants 的 JSON 原子写 + 单例懒加载）：
- ProfileGrantStore：data/security/profile_grants.json，键 user_id::profile，
  值 {scope, granted_at, expires_at, approved_by}；scope ∈ task/session/long，
  session/task 作用域带 TTL（long 不过期）。
- ensure_profile_grant：有有效授权→放行；无→经 ApprovalManager 铸造一条
  kind=profile_grant 审批请求（用户在审批现场确认），并 fail-closed 拒绝本次动作。
- 审批通过钩子（governance approve）调 mint_profile_grant 落库。

fail-closed：无 grant 即拒，绝不静默降级到"偷偷用 profile"。
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

_DEFAULT_PATH = "data/security/profile_grants.json"

# 作用域 → TTL 秒（long=0 表示不过期）
_SCOPE_TTL = {"task": 3600, "session": 4 * 3600, "long": 0}


class ProfileGrantStore:
    """profile 附身授权存储（user_id::profile 粒度；原子 JSON 写）。"""

    def __init__(self, path: Optional[str] = None):
        self._path = Path(path or _DEFAULT_PATH)
        self._lock = threading.RLock()
        self._grants: Dict[str, Dict[str, Any]] = {}
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            if self._path.exists():
                self._grants = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            logger.warning("profile 授权存储读取失败（回退空表）: %s", e)
            self._grants = {}

    def _save(self) -> bool:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._grants, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self._path)
            return True
        except Exception as e:  # noqa: BLE001
            logger.warning("profile 授权存储写入失败: %s", e)
            return False

    @staticmethod
    def _key(user_id: str, profile: str) -> str:
        return f"{user_id}::{profile}"

    def mint(self, user_id: str, profile: str, scope: str = "session",
             approved_by: str = "") -> bool:
        """铸造授权（幂等刷新 TTL）。scope 非法回退 session。"""
        user_id, profile = str(user_id), str(profile)
        if not user_id or not profile:
            return False
        if scope not in _SCOPE_TTL:
            scope = "session"
        ttl = _SCOPE_TTL[scope]
        now = time.time()
        with self._lock:
            self._load()
            self._grants[self._key(user_id, profile)] = {
                "user_id": user_id,
                "profile": profile,
                "scope": scope,
                "granted_at": now,
                "expires_at": (now + ttl) if ttl else None,
                "approved_by": approved_by,
            }
            return self._save()

    def has_valid_grant(self, user_id: str, profile: str, now: Optional[float] = None) -> bool:
        with self._lock:
            self._load()
            g = self._grants.get(self._key(user_id, profile))
            if not g:
                return False
            exp = g.get("expires_at")
            if exp is None:  # long 作用域不过期
                return True
            return (now if now is not None else time.time()) < float(exp)

    def revoke(self, user_id: str, profile: str) -> bool:
        with self._lock:
            self._load()
            if self._grants.pop(self._key(user_id, profile), None) is not None:
                return self._save()
            return False

    def list_grants(self) -> list:
        with self._lock:
            self._load()
            return list(self._grants.values())


_store: Optional[ProfileGrantStore] = None
_store_lock = threading.Lock()


def get_profile_grant_store(path: Optional[str] = None) -> ProfileGrantStore:
    global _store
    with _store_lock:
        if _store is None:
            _store = ProfileGrantStore(path=path)
        return _store


def reset_profile_grant_store() -> None:
    global _store
    with _store_lock:
        _store = None


def ensure_profile_grant(
    user_id: str,
    profile: str,
    *,
    agent_id: str = "",
    session_id: Optional[str] = None,
    reason: str = "",
) -> Dict[str, Any]:
    """profile 使用前的授权门（fail-closed）。

    返回 {granted: bool, request_id?: str, message: str}。无有效授权时经
    ApprovalManager 铸造 kind=profile_grant 审批请求供用户在审批现场确认，
    本次动作拒绝。ApprovalManager 不可用时仍拒绝（不放行），仅无 request_id。
    """
    store = get_profile_grant_store()
    if store.has_valid_grant(user_id, profile):
        return {"granted": True, "message": "已授权"}

    request_id = None
    try:
        from neurova.security.approval_manager import get_approval_manager

        am = get_approval_manager()
        req = am.create_approval_request(
            agent_id=agent_id or "",
            user_id=user_id,
            command=f"profile_grant::{user_id}::{profile}",
            description=reason or f"agent 请求以你的登录态 profile（{profile}）操作外部站点",
            danger_reason="附身授权：以用户身份对外可见操作",
            metadata={
                "kind": "profile_grant",
                "user_id": user_id,
                "profile": profile,
                "scope": "session",
                "session_id": session_id,
            },
        )
        request_id = getattr(req, "request_id", None)
    except Exception as e:  # noqa: BLE001 — 审批子系统不可用仍 fail-closed
        logger.warning("profile 授权审批请求铸造失败（仍拒绝）: %s", e)

    msg = (
        "需要附身授权：agent 将以你的登录态 profile 对外操作，"
        + (f"已发起审批请求 {request_id}，请在治理面板批准后重试。" if request_id else "当前无法发起审批，已拒绝。")
    )
    return {"granted": False, "request_id": request_id, "message": msg}


def mint_from_approval(metadata: Dict[str, Any], approved_by: str = "") -> bool:
    """审批通过钩子：kind=profile_grant 的请求批准后落授权。"""
    if not isinstance(metadata, dict) or metadata.get("kind") != "profile_grant":
        return False
    return get_profile_grant_store().mint(
        str(metadata.get("user_id", "")),
        str(metadata.get("profile", "")),
        scope=str(metadata.get("scope", "session")),
        approved_by=approved_by,
    )
