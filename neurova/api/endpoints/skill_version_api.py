"""
技能版本管理 API 路由

提供技能版本检测、通知管理和手动更新的 API 接口。
"""

import datetime
from neurova.core.logger import get_logger
from neurova.api.endpoints._pydantic_compat import safe_model_dump  # s9: pydantic v1 兼容
import typing

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = get_logger(__name__)

router = APIRouter()


# ── Models ─────────────────────────────────────────────


class VersionCheckRequest(BaseModel):
    skill_id: str
    current_version: str = ""


class VersionCheckResponse(BaseModel):
    skill_id: str
    current_version: str
    latest_version: str
    has_update: bool = False
    changelog: str = ""


class NotificationItem(BaseModel):
    id: str
    skill_id: str
    skill_name: str
    old_version: str
    new_version: str
    message: str
    read: bool = False
    created_at: str


class UpdateSkillRequest(BaseModel):
    skill_id: str
    target_version: typing.Optional[str] = None


# ── In-memory stores ───────────────────────────────────

_VERSIONS_STORE: typing.Dict[str, dict] = {
    "web-search": {"latest_version": "1.3.0", "changelog": "Added pagination and filter support"},
    "code-interpreter": {"latest_version": "2.1.0", "changelog": "Improved error handling, added sandbox mode"},
    "file-manager": {"latest_version": "1.1.0", "changelog": "Added batch operations"},
    "data-analysis": {"latest_version": "1.6.0", "changelog": "New chart types, performance improvements"},
    "email-sender": {"latest_version": "1.2.0", "changelog": "Added template support"},
    "task-scheduler": {"latest_version": "1.4.0", "changelog": "Added cron expression editor"},
}

_NOTIFICATIONS_STORE: typing.Dict[str, list] = {}  # user_id -> [notifications]
_installed_versions: typing.Dict[str, typing.Dict[str, str]] = {}  # user_id -> {skill_id: version}


def _compare_versions(v1: str, v2: str) -> int:
    """Compare two semver strings. Returns -1, 0, or 1."""
    parts1 = [int(x) for x in v1.split(".") if x.isdigit()]
    parts2 = [int(x) for x in v2.split(".") if x.isdigit()]
    for a, b in zip(parts1, parts2):
        if a < b:
            return -1
        if a > b:
            return 1
    return len(parts1) - len(parts2)


def _get_user_id_from_token(request) -> str:
    """Extract user ID from request state."""
    return getattr(request.state, "user_id", "anonymous")


# ── Endpoints ──────────────────────────────────────────


@router.post("/check")
async def check_version_update(body: VersionCheckRequest):
    """检查技能是否有新版本"""
    skill_id = body.skill_id
    version_info = _VERSIONS_STORE.get(skill_id)
    if not version_info:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_id}' not found")

    latest = version_info["latest_version"]
    current = body.current_version or "0.0.0"
    has_update = _compare_versions(current, latest) < 0

    return {
        "code": 0,
        "message": "success",
        "data": safe_model_dump(VersionCheckResponse(  # s9: pydantic v1 兼容
            skill_id=skill_id,
            current_version=current,
            latest_version=latest,
            has_update=has_update,
            changelog=version_info.get("changelog", ""),
        )),
    }


@router.post("/check-all")
async def check_all_versions_on_startup():
    """系统重启时检查所有技能的版本更新"""
    results = []
    for skill_id, info in _VERSIONS_STORE.items():
        results.append(
            {
                "skill_id": skill_id,
                "latest_version": info["latest_version"],
                "changelog": info.get("changelog", ""),
            }
        )
    return {"code": 0, "message": "success", "data": {"skills": results, "total": len(results)}}


@router.get("/notifications")
async def get_notifications(request, read: typing.Optional[bool] = None, page: int = 1, size: int = 20):
    """获取当前用户的更新通知"""
    user_id = _get_user_id_from_token(request)
    notifs = _NOTIFICATIONS_STORE.get(user_id, [])

    if read is not None:
        notifs = [n for n in notifs if n.get("read") == read]

    total = len(notifs)
    start = (page - 1) * size
    items = notifs[start : start + size]

    return {"code": 0, "message": "success", "data": {"items": items, "total": total, "page": page, "size": size}}


@router.put("/notifications/{notification_id}/read")
async def mark_notification_read(notification_id: str, request):
    """标记通知为已读"""
    user_id = _get_user_id_from_token(request)
    notifs = _NOTIFICATIONS_STORE.get(user_id, [])
    for n in notifs:
        if n.get("id") == notification_id:
            n["read"] = True
            return {"code": 0, "message": "Marked as read", "data": {"notification_id": notification_id}}
    raise HTTPException(status_code=404, detail="Notification not found")


@router.post("/auto-update")
async def auto_update_agent_skills(request):
    """自动更新 Agent 专属技能池中的技能"""
    user_id = _get_user_id_from_token(request)
    installed = _installed_versions.get(user_id, {})
    updated = []

    for skill_id, current_ver in installed.items():
        version_info = _VERSIONS_STORE.get(skill_id)
        if not version_info:
            continue
        latest = version_info["latest_version"]
        if _compare_versions(current_ver, latest) < 0:
            installed[skill_id] = latest
            updated.append({"skill_id": skill_id, "old_version": current_ver, "new_version": latest})

            notif_id = f"notif-{skill_id}-{int(datetime.datetime.now(datetime.timezone.utc).timestamp())}"
            _NOTIFICATIONS_STORE.setdefault(user_id, []).append(
                {
                    "id": notif_id,
                    "skill_id": skill_id,
                    "skill_name": skill_id,
                    "old_version": current_ver,
                    "new_version": latest,
                    "message": f"{skill_id} updated from {current_ver} to {latest}",
                    "read": False,
                    "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                }
            )

    return {"code": 0, "message": f"Updated {len(updated)} skills", "data": {"updated": updated}}


@router.post("/sync-from-public")
async def sync_from_public_pool(request):
    """从公共技能池同步技能更新"""
    user_id = _get_user_id_from_token(request)
    installed = _installed_versions.get(user_id, {})
    synced = []

    for skill_id, info in _VERSIONS_STORE.items():
        latest = info["latest_version"]
        current = installed.get(skill_id, "0.0.0")
        if _compare_versions(current, latest) < 0:
            installed[skill_id] = latest
            synced.append({"skill_id": skill_id, "version": latest})

    _installed_versions[user_id] = installed
    return {"code": 0, "message": f"Synced {len(synced)} skills", "data": {"synced": synced}}


@router.post("/update")
async def manual_update_skill(body: UpdateSkillRequest, request):
    """手动更新技能到指定版本"""
    skill_id = body.skill_id
    version_info = _VERSIONS_STORE.get(skill_id)
    if not version_info:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_id}' not found")

    target = body.target_version or version_info["latest_version"]
    user_id = _get_user_id_from_token(request)
    installed = _installed_versions.setdefault(user_id, {})
    old_version = installed.get(skill_id, "0.0.0")

    installed[skill_id] = target

    return {
        "code": 0,
        "message": f"Skill updated to {target}",
        "data": {"skill_id": skill_id, "old_version": old_version, "new_version": target},
    }


@router.get("/startup-check")
async def startup_version_check():
    """系统启动时执行版本检查"""
    return await check_all_versions_on_startup()
