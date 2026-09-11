# -*- coding: utf-8 -*-
"""Agent 工作区文件管理 API（B3-4，QwenPaw #7078/#7151 对齐）。

提供 per-agent 工作区（agent_workspaces/{agent_id}）的文件管理能力：
- GET  列目录（含子目录）
- POST mkdir 建文件夹
- POST copy / move 复制与移动
- GET  zip 整目录打包下载

安全纪律：agent_id 走 [A-Za-z0-9_-] 校验（与 create_agent 同规）；相对
路径解析后强制落在该工作区根内（防路径穿越逃逸，同 relpath-sandbox 修复
语义）；写操作全部 fail-closed。
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import re
import shutil
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from neurova.core.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()

_AGENT_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")

# P1-8：工作区根以仓库为基准（原 CWD 相对路径与服务端 agent 加载口径分裂）
_WORKSPACES_ROOT = Path(__file__).resolve().parents[3] / "agent_workspaces"

# P0-4：Content-Disposition 文件名字符白名单（subdir 可达此处，防 header 注入）
_ZIP_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _ensure_workspace_owner(root: Path, agent_id: str, current_user: Dict[str, Any]) -> None:
    """P0-4：工作区归属校验（choke point——全部端点经 _workspace_root 进入）。

    归属以 {root}/agent_config.json 的 owner_user_id 为准：
    - 有主 → 仅属主或 admin 可访问（横向 IDOR 封口）；
    - 无主/无配置（共享、default、未注册新目录）→ 放行，与 console 会话
      "空 user_id 视为共享" 既有口径一致。
    """
    if not isinstance(current_user, dict) or not current_user.get("user_id"):
        raise HTTPException(status_code=401, detail="Not authenticated")
    config_path = root / "agent_config.json"
    owner = ""
    if config_path.is_file():
        try:
            owner = str((json.loads(config_path.read_text(encoding="utf-8")) or {}).get("owner_user_id") or "")
        except Exception:  # noqa: BLE001 — 配置损坏按无主处理，不放大为 500
            owner = ""
    if not owner:
        return
    if str(current_user.get("user_id") or "") == owner:
        return
    if current_user.get("role") == "admin":
        return
    raise HTTPException(status_code=403, detail=f"无权访问 agent 工作区: {agent_id}")


def _workspace_root(agent_id: str, current_user: Dict[str, Any]) -> Path:
    if not _AGENT_ID_PATTERN.match(agent_id or ""):
        raise HTTPException(status_code=400, detail=f"Invalid agent_id: '{agent_id}'")
    root = _WORKSPACES_ROOT / agent_id
    root.mkdir(parents=True, exist_ok=True)
    root = root.resolve()
    _ensure_workspace_owner(root, agent_id, current_user)
    return root


def _resolve_inside(root: Path, rel_path: str) -> Path:
    """把 rel_path 解析到 root 内；逃逸/隐藏目录一律 400（fail-closed）。"""
    rel = (rel_path or "").strip().replace("\\", "/").lstrip("/")
    if rel in ("", "."):
        return root
    # P0-4：隐藏目录（.git/.tmp 等）整棵拒绝，防凭据/内部文件借道读取
    if any(part.startswith(".") for part in rel.split("/")):
        raise HTTPException(status_code=400, detail=f"隐藏路径不允许访问: {rel_path}")
    candidate = (root / rel).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"路径越界: {rel_path}")
    return candidate


def _current_user_stub() -> Dict[str, Any]:
    """鉴权依赖占位：全局鉴权中间件已接管时此处仅为 OpenAPI 形参。"""
    return {"user_id": "anonymous"}


try:
    from neurova.api.deps import get_current_user as _get_current_user
except Exception:  # noqa: BLE001 — deps 不可用时退化为直通（中间件兜底）
    _get_current_user = _current_user_stub  # type: ignore[assignment]


class WorkspaceWriteRequest(BaseModel):
    """mkdir / copy / move 共用请求体"""

    path: str = Field(..., description="目标相对路径")
    source: Optional[str] = Field(default=None, description="copy/move 源相对路径")
    overwrite: bool = Field(default=False, description="目标已存在时是否覆盖")


@router.get("/{agent_id}/files")
async def list_workspace_files(
    agent_id: str,
    subdir: str = "",
    current_user: Dict[str, Any] = Depends(_get_current_user),
):
    """列出工作区目录内容（文件/文件夹 + 大小/修改时间）。"""
    _ = current_user
    root = _workspace_root(agent_id, current_user)
    target = _resolve_inside(root, subdir)
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"目录不存在: {subdir}")
    if not target.is_dir():
        raise HTTPException(status_code=400, detail=f"不是目录: {subdir}")

    entries: List[Dict[str, Any]] = []
    for child in sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
        # 隐藏系统文件不外露（.tmp 原子写残留等）
        if child.name.startswith("."):
            continue
        stat = child.stat()
        entries.append({
            "name": child.name,
            "type": "dir" if child.is_dir() else "file",
            "size": stat.st_size if child.is_file() else 0,
            "modified_at": stat.st_mtime,
        })
    return {
        "code": 0,
        "message": "success",
        "data": {"agent_id": agent_id, "path": subdir, "entries": entries},
    }


@router.post("/{agent_id}/files/mkdir")
async def mkdir_workspace(
    agent_id: str,
    body: WorkspaceWriteRequest,
    current_user: Dict[str, Any] = Depends(_get_current_user),
):
    """创建文件夹（含父级；已存在且未 overwrite 时 409）。"""
    _ = current_user
    root = _workspace_root(agent_id, current_user)
    target = _resolve_inside(root, body.path)
    if target.exists() and not body.overwrite:
        raise HTTPException(status_code=409, detail=f"已存在: {body.path}")
    target.mkdir(parents=True, exist_ok=True)
    return {"code": 0, "message": "success", "data": {"path": body.path}}


@router.post("/{agent_id}/files/copy")
async def copy_workspace_entry(
    agent_id: str,
    body: WorkspaceWriteRequest,
    current_user: Dict[str, Any] = Depends(_get_current_user),
):
    """复制文件/目录。"""
    _ = current_user
    root = _workspace_root(agent_id, current_user)
    source = _resolve_inside(root, body.source or "")
    target = _resolve_inside(root, body.path)
    if not source.exists():
        raise HTTPException(status_code=404, detail=f"源不存在: {body.source}")
    if target.exists() and not body.overwrite:
        raise HTTPException(status_code=409, detail=f"目标已存在: {body.path}")
    if source.is_dir():
        shutil.copytree(source, target, dirs_exist_ok=body.overwrite)
    else:
        shutil.copy2(source, target)
    return {"code": 0, "message": "success", "data": {"source": body.source, "path": body.path}}


@router.post("/{agent_id}/files/move")
async def move_workspace_entry(
    agent_id: str,
    body: WorkspaceWriteRequest,
    current_user: Dict[str, Any] = Depends(_get_current_user),
):
    """移动/重命名文件与目录（同工作区内）。"""
    _ = current_user
    root = _workspace_root(agent_id, current_user)
    source = _resolve_inside(root, body.source or "")
    target = _resolve_inside(root, body.path)
    if not source.exists():
        raise HTTPException(status_code=404, detail=f"源不存在: {body.source}")
    if source == target:
        raise HTTPException(status_code=400, detail="源与目标相同")
    if target.exists() and not body.overwrite:
        raise HTTPException(status_code=409, detail=f"目标已存在: {body.path}")
    shutil.move(str(source), str(target))
    return {"code": 0, "message": "success", "data": {"source": body.source, "path": body.path}}


def _zip_directory(target: Path) -> io.BytesIO:
    """整目录同步打包（P1-9：rglob 遍历 + DEFLATE 压缩在大工作区可达
    秒级~十秒级，必须丢线程池执行，不得阻塞事件循环）。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(Path(target).rglob("*")):
            if path.is_file() and not path.name.startswith("."):
                zf.write(path, arcname=str(path.relative_to(target)))
    buf.seek(0)
    return buf


@router.get("/{agent_id}/files/zip")
async def download_workspace_zip(
    agent_id: str,
    subdir: str = "",
    current_user: Dict[str, Any] = Depends(_get_current_user),
):
    """整目录打包下载（#7151 zip 下载对齐；运行时打包不落盘）。"""
    from fastapi.responses import StreamingResponse

    _ = current_user
    root = _workspace_root(agent_id, current_user)
    target = _resolve_inside(root, subdir)
    if not target.is_dir():
        raise HTTPException(status_code=400, detail=f"不是目录: {subdir}")

    # P1-9: rglob+压缩段丢线程池，事件循环不被打包阻塞
    buf = await asyncio.to_thread(_zip_directory, target)
    # P0-4：文件名白名单化，subdir 不可向 Content-Disposition 注入
    name = _ZIP_NAME_RE.sub("_", f"{agent_id}_{(subdir or 'workspace').replace('/', '_')}")[:100] or "workspace"
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )
