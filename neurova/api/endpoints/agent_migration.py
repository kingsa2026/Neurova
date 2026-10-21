# -*- coding: utf-8 -*-
"""agent 迁移包（zip）端点：完整导出 / 导入。

- 导出：`GET /v1/agents/{agent_id}/export-migration` → zip 文件
- 导入：`POST /v1/agents/import-migration`（multipart）
  - 目标 ID 冲突默认 409；`overwrite=true` 仅 admin
  - 归属按导入者：agent/会话/记忆/轨迹/配置属主一律改为导入者
"""
from __future__ import annotations

import asyncio
import inspect
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from neurova.api.auth import get_current_user
from neurova.core.logger import get_logger
from neurova.security.safe_archive import UnsafeArchiveError

from . import agent_package as package_api
from neurova.agent_migration import (
    MAX_PACKAGE_BYTES,
    MigrationConflict,
    MigrationError,
    MigrationForbidden,
    MigrationTooLarge,
    apply_import,
    discard_prepared,
    export_agent_migration,
    finalize_import,
    prepare_import,
)

logger = get_logger(__name__)

router = APIRouter()

_SHUTDOWN_TIMEOUT = 30.0


async def _shutdownAgent(agent: Any, agent_id: str) -> None:
    if agent is None or not hasattr(agent, "shutdown"):
        return
    try:
        result = agent.shutdown()
        if inspect.isawaitable(result):
            await asyncio.wait_for(result, timeout=_SHUTDOWN_TIMEOUT)
    except Exception as e:  # noqa: BLE001 - 覆盖导入继续尝试；失败会由文件操作暴露
        logger.warning("迁移导入前关闭 agent %s 失败：%s", agent_id, e)


def _httpError(exc: Exception) -> HTTPException:
    if isinstance(exc, MigrationConflict):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, MigrationForbidden):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, MigrationTooLarge):
        return HTTPException(status_code=413, detail=str(exc))
    if isinstance(exc, (MigrationError, UnsafeArchiveError)):
        return HTTPException(status_code=422, detail=str(exc))
    return HTTPException(status_code=500, detail=f"Agent migration failed: {exc}")


@router.get("/{agent_id}/export-migration")
async def export_agent_migration_endpoint(
    request: Request,
    agent_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """导出 agent 完整迁移包（zip）。"""
    agent = package_api._resolve_agent_or_404(agent_id)
    package_api._check_owner(agent, current_user)
    package_manifest = await asyncio.to_thread(
        package_api.buildAgentManifest, agent, agent_id
    )
    result = await asyncio.to_thread(
        export_agent_migration, agent_id, package_manifest
    )
    filename = f"agent-migration-{agent_id}-{time.strftime('%Y%m%d-%H%M%S')}.zip"
    return FileResponse(
        result.zip_path,
        media_type="application/zip",
        filename=filename,
        background=BackgroundTask(shutil.rmtree, str(result.temp_dir), ignore_errors=True),
    )


@router.post("/import-migration")
async def import_agent_migration_endpoint(
    request: Request,
    file: UploadFile = File(..., description="agent 迁移包 zip"),
    agent_id: str = Form("", description="目标 agent_id；留空沿用源 ID"),
    overwrite: bool = Form(False, description="覆盖同 ID 现有 agent（仅 admin）"),
    import_skills: bool = Form(True),
    import_cron: bool = Form(True),
    import_mcp: bool = Form(False),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """导入 agent 迁移包：完整数据 + 归属重写。"""
    importer = str(current_user.get("user_id") or "").strip()
    if not importer:
        raise HTTPException(status_code=401, detail="Not authenticated")
    is_admin = current_user.get("role") == "admin"

    upload_dir = Path(tempfile.mkdtemp(prefix="nvmig_upload_"))
    zip_path = upload_dir / "package.zip"
    prepared = None
    try:
        written = 0
        with open(zip_path, "wb") as f:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > MAX_PACKAGE_BYTES:
                    raise MigrationTooLarge(f"迁移包过大：> {MAX_PACKAGE_BYTES}")
                f.write(chunk)
        if written == 0:
            raise MigrationError("上传文件为空")

        prepared = await asyncio.to_thread(
            prepare_import,
            zip_path,
            agent_id,
            overwrite=overwrite,
            importer=importer,
            is_admin=is_admin,
            import_skills=import_skills,
            import_cron=import_cron,
            import_mcp=import_mcp,
        )

        from neurova.api.endpoints import get_app_state

        state = get_app_state() or {}
        existing_agent = (state.get("agents") or {}).get(prepared.target_id)
        old_agent_config = getattr(existing_agent, "config", None) if existing_agent else None
        if existing_agent is not None:
            await _shutdownAgent(existing_agent, prepared.target_id)
            state.get("agents", {}).pop(prepared.target_id, None)

        result = await asyncio.to_thread(apply_import, prepared, old_agent_config)
        await asyncio.to_thread(finalize_import, prepared)
        return result
    except Exception as exc:
        if prepared is not None:
            await asyncio.to_thread(discard_prepared, prepared)
        if isinstance(exc, HTTPException):
            raise
        logger.error("agent 迁移包导入失败：%s", exc, exc_info=True)
        raise _httpError(exc) from exc
    finally:
        try:
            await file.close()
        except Exception:
            pass
        shutil.rmtree(upload_dir, ignore_errors=True)
