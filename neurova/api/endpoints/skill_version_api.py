"""
技能版本管理 API 路由

提供技能版本检测、通知管理和手动更新的 API 接口。

P1-6：全端点换真实数据源——原
_VERSIONS_STORE 硬编码假版本表/内存 dict 是演示残留（前端零消费方，
留着就是下一个"页面按想象契约写"事故的种子）：

- 最新市场版 ← market catalog（get_market_store，单一事实源）
- 安装态/变更日志 ← SkillService manifest（identity/version_history 修订链）
- 更新动作 ← MarketImporter.import_skill(force=True) 真实重装通道
"""

import datetime
from neurova.core.logger import get_logger
from neurova.api.endpoints._pydantic_compat import safe_model_dump  # s9: pydantic v1 兼容
import json
import os
import tempfile
import typing

from fastapi import APIRouter, HTTPException, Request
from neurova.api.auth import get_current_user, Depends
from pydantic import BaseModel

try:
    from neurova.skills.market_importer import get_market_importer
except Exception:  # pragma: no cover - 可选依赖缺失时更新通道降级
    get_market_importer = None

logger = get_logger(__name__)

router = APIRouter(dependencies=[Depends(get_current_user)],)

# 版本 API 无 agent 上下文（桌面版全局默认 agent 口径，与原 user 级演示范围等价
# 且不更大）；通知已读态持久化在该目录下的小 JSON（原子写）。
_DEFAULT_AGENT_ID = "default"


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


# ── Real data helpers ──────────────────────────────────


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


# Wave H-W3 公共名：升级提交单型的版本单调校验跨模块复用（勿再各自复制
# 比较逻辑——孤岛时代多处散装版本比较是漂移源）。
compare_versions = _compare_versions


def _get_user_id_from_token(request) -> str:
    """Extract user ID from request state."""
    return getattr(request.state, "user_id", "anonymous")


def _latest_market_version(skill_id: str) -> typing.Optional[str]:
    """市场目录最新版（catalog 单一事实源）。无条目 → None。"""
    try:
        from neurova.skills.market_store import get_market_store

        entry = get_market_store().get(skill_id)
        if entry:
            return str(entry.get("version") or "") or None
    except Exception as e:
        logger.debug("market store 查询失败 %s: %s", skill_id, e)
    return None


def _installed_skills() -> typing.List[dict]:
    """默认 agent 的真实安装技能（manifest 修订链直读）。"""
    from neurova.skills.skill_service import SkillService

    rows = []
    try:
        service = SkillService(agent_id=_DEFAULT_AGENT_ID)
        for s in service.list_skills():
            entry = service._skills.get(s["id"], {}) if hasattr(service, "_skills") else {}
            hist = entry.get("version_history") or []
            changelog = ""
            if hist:
                last = hist[-1]
                changelog = f"v{last.get('version', '')} ({last.get('trigger', '')})".strip()
            rows.append(
                {
                    "skill_id": s["id"],
                    "version": s.get("version", "1.0.0"),
                    "changelog": changelog,
                }
            )
    except Exception as e:
        logger.warning("读取已安装技能失败: %s", e)
    return rows


def _installed_version(skill_id: str) -> typing.Optional[str]:
    for row in _installed_skills():
        if row["skill_id"] == skill_id:
            return row["version"]
    return None


def _installed_source(skill_id: str) -> str:
    from neurova.skills.skill_service import SkillService

    try:
        info = SkillService(agent_id=_DEFAULT_AGENT_ID).get_skill_info(skill_id) or {}
        return str((info.get("identity") or {}).get("origin") or "")
    except Exception:
        return ""


def _reads_path() -> str:
    from neurova.skills.skill_service import SkillService

    base = SkillService(agent_id=_DEFAULT_AGENT_ID).skills_dir
    return str(base / "version_reads.json")


def _load_reads() -> set:
    try:
        with open(_reads_path(), "r", encoding="utf-8") as f:
            return set(json.load(f))
    except Exception:
        return set()


def _save_reads(reads: set) -> None:
    """原子写（tmp + os.replace，manifest 同纪律）。"""
    path = _reads_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(path), prefix="vreads_", suffix=".tmp")
    try:
        with open(fd, "w", encoding="utf-8") as f:
            json.dump(sorted(reads), f)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _notification_items() -> typing.List[dict]:
    """从 manifest 修订链（有 parent 的修订 = 一次版本演进）派生更新通知。"""
    from neurova.skills.skill_service import SkillService

    items = []
    reads = _load_reads()
    try:
        service = SkillService(agent_id=_DEFAULT_AGENT_ID)
        for skill_id, entry in service.iter_skills():
            for rev in entry.get("version_history") or []:
                if not rev.get("parent_revision_id"):
                    continue  # 出生修订不通知
                rev_no = str(rev.get("revision_id", "")).rsplit("@", 1)[-1]
                items.append(
                    {
                        "id": f"{skill_id}@{rev_no}",
                        "skill_id": skill_id,
                        "skill_name": entry.get("name", skill_id),
                        "old_version": "",
                        "new_version": str(rev.get("version", "")),
                        "message": f"{skill_id} 版本演进至 {rev.get('version', '')}（{rev.get('trigger', '')}）",
                        "read": f"{skill_id}@{rev_no}" in reads,
                        "created_at": str(rev.get("created_at", "")),
                    }
                )
    except Exception as e:
        logger.warning("通知派生失败: %s", e)
    items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return items


def _run_update(skill_id: str, target_version: typing.Optional[str]) -> dict:
    """真实更新通道：MarketImporter 强制重装到目标版本。"""
    if get_market_importer is None:
        return {"ok": False, "error": "Market importer service not available"}
    latest = target_version or _latest_market_version(skill_id)
    if not latest:
        return {"ok": False, "error": f"Skill '{skill_id}' not found in marketplace catalog"}
    try:
        importer = get_market_importer()
        task = importer.import_skill(skill_id, version=latest, force=True)
        status_val = getattr(getattr(task, "status", None), "value", None) or str(
            getattr(task, "status", "")
        )
        ok = "complet" in str(status_val).lower()
        if not ok:
            return {"ok": False, "error": f"更新任务未完成: {status_val}"}
        return {"ok": True, "new_version": latest}
    except Exception as e:
        logger.exception("技能更新失败 %s: %s", skill_id, e)
        return {"ok": False, "error": str(e)}


# ── Endpoints ──────────────────────────────────────────


@router.post("/check")
async def check_version_update(body: VersionCheckRequest):
    """检查技能是否有新版本（市场 catalog 最新版 vs manifest 安装版）"""
    skill_id = body.skill_id
    latest = _latest_market_version(skill_id)
    installed = _installed_version(skill_id)
    if not latest and not installed:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_id}' not found")

    current = body.current_version or (installed or "0.0.0")
    latest = latest or current
    has_update = bool(latest) and _compare_versions(current, latest) < 0

    return {
        "code": 0,
        "message": "success",
        "data": safe_model_dump(VersionCheckResponse(  # s9: pydantic v1 兼容
            skill_id=skill_id,
            current_version=current,
            latest_version=latest,
            has_update=has_update,
            changelog=_installed_changelog(skill_id) if has_update else "",
        )),
    }


def _installed_changelog(skill_id: str) -> str:
    for row in _installed_skills():
        if row["skill_id"] == skill_id:
            return row.get("changelog", "")
    return ""


@router.post("/check-all")
async def check_all_versions_on_startup():
    """重启时检查全部已安装技能 vs 市场最新版（真实安装态）"""
    results = []
    for row in _installed_skills():
        latest = _latest_market_version(row["skill_id"]) or row["version"]
        results.append(
            {
                "skill_id": row["skill_id"],
                "current_version": row["version"],
                "latest_version": latest,
                "has_update": _compare_versions(row["version"], latest) < 0,
                "changelog": row.get("changelog", ""),
            }
        )
    return {"code": 0, "message": "success", "data": {"skills": results, "total": len(results)}}


@router.get("/notifications")
async def get_notifications(request, read: typing.Optional[bool] = None, page: int = 1, size: int = 20):
    """更新通知（manifest 版本演进修订链派生；已读态持久化）"""
    notifs = _notification_items()
    if read is not None:
        notifs = [n for n in notifs if n.get("read") == read]

    total = len(notifs)
    start = (page - 1) * size
    items = notifs[start : start + size]

    return {"code": 0, "message": "success", "data": {"items": items, "total": total, "page": page, "size": size}}


@router.put("/notifications/{notification_id}/read")
async def mark_notification_read(notification_id: str, request):
    """标记通知为已读（持久化）"""
    notifs = _notification_items()
    if not any(n.get("id") == notification_id for n in notifs):
        raise HTTPException(status_code=404, detail="Notification not found")
    reads = _load_reads()
    reads.add(notification_id)
    _save_reads(reads)
    return {"code": 0, "message": "Marked as read", "data": {"notification_id": notification_id}}


@router.post("/auto-update")
async def auto_update_agent_skills(request):
    """自动更新市场来源技能到目录最新版（真实重装通道）"""
    updated = []
    for row in _installed_skills():
        if _installed_source(row["skill_id"]) not in ("hub", "import", "marketplace"):
            continue
        latest = _latest_market_version(row["skill_id"])
        if latest and _compare_versions(row["version"], latest) < 0:
            result = _run_update(row["skill_id"], latest)
            if result.get("ok"):
                updated.append(
                    {
                        "skill_id": row["skill_id"],
                        "old_version": row["version"],
                        "new_version": result["new_version"],
                    }
                )
    return {"code": 0, "message": f"Updated {len(updated)} skills", "data": {"updated": updated}}


@router.post("/sync-from-public")
async def sync_from_public_pool(request):
    """按市场目录（公共池）比对安装态，落后即真实重装"""
    synced = []
    for row in _installed_skills():
        latest = _latest_market_version(row["skill_id"])
        if latest and _compare_versions(row["version"], latest) < 0:
            result = _run_update(row["skill_id"], latest)
            if result.get("ok"):
                synced.append({"skill_id": row["skill_id"], "version": result["new_version"]})
    return {"code": 0, "message": f"Synced {len(synced)} skills", "data": {"synced": synced}}


@router.post("/update")
async def manual_update_skill(body: UpdateSkillRequest, request):
    """手动更新技能到指定/最新市场版（真实重装）"""
    skill_id = body.skill_id
    old_version = _installed_version(skill_id) or "0.0.0"
    result = _run_update(skill_id, body.target_version)
    if not result.get("ok"):
        return {
            "code": 1,
            "message": result.get("error", "更新失败"),
            "data": {"skill_id": skill_id, "updated": False, "error": result.get("error", "")},
        }
    return {
        "code": 0,
        "message": f"Skill updated to {result['new_version']}",
        "data": {
            "skill_id": skill_id,
            "old_version": old_version,
            "new_version": result["new_version"],
            "updated": True,
        },
    }


@router.get("/startup-check")
async def startup_version_check():
    """系统启动时执行版本检查"""
    return await check_all_versions_on_startup()
