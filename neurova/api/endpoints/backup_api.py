# -*- coding: utf-8 -*-
"""备份管理 API（BackupOrchestrator 系统接线，全方位补课 P1-a）。

孤儿接线：orchestrator（commit 3923ce3）能力完整但此前无 API/CLI 触达。
诚实边界：
- create 的 sources 固定为 sessions/agent_workspaces 目录映射（可用
  NEUROVA_BACKUP_SOURCES 覆盖）；data/ 运行态 SQLite 不入包（在线文件
  打包不一致，热备需 sqlite3 backup API，另行立项）。
- restore 的 apply_fn 把 files 写回原前缀目录，带 Zip Slip 防护。
- FOREIGN（他实例签名/篡改）restore 无条件拒绝；LEGACY 需显式 trust。
"""
import json
import os
import threading
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from neurova.api.deps import require_admin
from neurova.core.logger import get_logger
from neurova.core.data_root import dataPath

logger = get_logger(__name__)

# 整路由级 admin 门（enhanced_users_api.py:28 同款模式）
router = APIRouter(dependencies=[Depends(require_admin())])

_orchestrator: Optional[Any] = None
_orch_lock = threading.RLock()


def _defaultBackupSources() -> Dict[str, str]:
    """按 v2 统一布局逐 agent 备份 `data/<agent_id>/` 根。"""
    from neurova.core.agent_workspaces import discover_agent_ids, get_agent_root_dir

    return {
        f"agents/{agent_id}": str(get_agent_root_dir(agent_id))
        for agent_id in discover_agent_ids()
    }


def get_backup_orchestrator():
    """惰性单例（DCL，对齐仓库 singleton 收敛规约）。"""
    global _orchestrator
    if _orchestrator is None:
        with _orch_lock:
            if _orchestrator is None:
                from neurova.backup.orchestrator import BackupOrchestrator
                from neurova.backup.trust import SigningKey

                override = os.environ.get("NEUROVA_BACKUP_SOURCES")
                sources = (
                    json.loads(override)
                    if override
                    else _defaultBackupSources()
                )
                _orchestrator = BackupOrchestrator(
                    key=SigningKey(
                        os.environ.get("NEUROVA_BACKUP_KEY_PATH") or dataPath("backup_signing.key")
                    ),
                    work_dir=os.environ.get("NEUROVA_BACKUP_WORK_DIR") or dataPath("backups"),
                )
                _orchestrator.default_sources = sources  # type: ignore[attr-defined]
    return _orchestrator


def _reset_backup_orchestrator() -> None:
    """测试/teardown 用。"""
    global _orchestrator
    with _orch_lock:
        _orchestrator = None


class RestoreRequest(BaseModel):
    zip_path: str
    trust: bool = False  # LEGACY 显式信任；FOREIGN 恒拒（orchestrator 语义）


def _safe_write_back(payload: Dict[str, Any]) -> Dict[str, int]:
    """apply_fn：按 `<前缀>/<相对路径>` 写回原目录。Zip Slip 防护。"""
    written = 0
    skipped = 0
    sources: Dict[str, str] = getattr(get_backup_orchestrator(), "default_sources", {})
    prefixes = sorted(sources, key=len, reverse=True)
    for name, content in payload.get("files", {}).items():
        base = ""
        rel = ""
        for prefix in prefixes:
            if name.startswith(prefix + "/"):
                base = sources[prefix]
                rel = name[len(prefix) + 1:]
                break
        if not base or not rel:
            skipped += 1
            continue
        base_p = Path(base).resolve()
        target = (base_p / rel).resolve()
        if base_p != target and base_p not in target.parents:
            skipped += 1  # Zip Slip：解析后越界
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        written += 1
    payload["write_back"] = {"written": written, "skipped": skipped}
    return payload["write_back"]


@router.post("/create")
async def create_backup(admin: dict = Depends(require_admin())):
    orch = get_backup_orchestrator()
    sources = {k: Path(v) for k, v in orch.default_sources.items()}
    out = orch.create_backup(sources)
    return {
        "success": True,
        "data": {"zip_path": str(out), "created_by": admin.get("username")},
        "message": "备份创建完成",
    }


@router.get("")
async def list_backups():
    work_dir = Path(get_backup_orchestrator().work_dir)
    items = [
        {"zip_path": str(p), "size": p.stat().st_size}
        for p in sorted(work_dir.glob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
    ]
    return {"success": True, "data": {"items": items}, "message": ""}


@router.post("/restore")
async def restore_backup(body: RestoreRequest):
    from neurova.backup.orchestrator import TrustRequiredError

    orch = get_backup_orchestrator()
    try:
        payload = orch.restore_backup(body.zip_path, _safe_write_back, trust=body.trust)
    except TrustRequiredError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"恢复失败: {exc}")
    return {
        "success": True,
        "data": {
            "mode": payload["mode"].value if hasattr(payload["mode"], "value") else payload["mode"],
            "files": len(payload["files"]),
            "write_back": payload.get("write_back"),
        },
        "message": "备份恢复完成",
    }
