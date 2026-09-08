"""artifact 注册与预览 API（对话页右侧 dock 产物预览的后端桥）。

设计（2026-09-08 产物预览计划 W1-1/W1-2）：
- 工具产出文件（file_write / tts_synthesize / OutputRef 落盘）散落在
  agent_workspaces 与 %TEMP%/neurova_tts，原本对外不可达；
- console.py 的 SSE tool_result 出口在截断前调用 _extract_artifacts，
  把结果文本中的 file_path/audio_path/output_ref.path 注册成 artifact
  并追加 {"type": "artifact"} 事件，前端 dock 据此开预览 tab；
- 安全：注册时校验路径位于白名单根内；读取时重新 resolve 再校验一次
  （防注册后移动/软链绕过）；归属校验非属主 404（与 files_api 一致）。

存储：模块级 _artifacts_store（与 files_api._files_store 同生命周期；
artifact 是会话产物，重启丢失可接受——文件本体仍在磁盘，路径幂等键
意味着下次同名工具调用会重新注册）。
"""

from __future__ import annotations

import hashlib
import mimetypes
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from neurova.api.auth import get_current_user
from neurova.core.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()

# 注册白名单根：agent 工作区（项目根 agent_workspaces/）+ TTS 临时目录。
# 测试通过 mock.patch.object(artifacts_api, "_WORKSPACE_ROOT", ...) 注入。
_WORKSPACE_ROOT = Path("agent_workspaces")

# TTS 工具落盘目录（tool_executor._execute_tts_synthesize 的 out_dir）
_TTS_TEMP_DIRNAME = "neurova_tts"

# kind 按扩展名映射（前端 dock 据此选预览面板）
_KIND_BY_EXT = {
    ".md": "markdown",
    ".markdown": "markdown",
    ".html": "html",
    ".htm": "html",
    ".xhtml": "html",
    ".svg": "image",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".gif": "image",
    ".webp": "image",
    ".bmp": "image",
    ".wav": "audio",
    ".mp3": "audio",
    ".ogg": "audio",
    ".flac": "audio",
    ".aac": "audio",
    ".m4a": "audio",
}

_artifacts_store: Dict[str, Dict[str, Any]] = {}


class ArtifactInfo(BaseModel):
    artifact_id: str
    kind: str
    name: str
    size: int = 0
    mime_type: str = ""
    agent_id: str = ""
    user_id: str = ""
    created_at: float = 0


def _artifact_kind(name: str) -> str:
    ext = Path(name).suffix.lower()
    return _KIND_BY_EXT.get(ext, "text")


def _allowed_roots() -> List[Path]:
    roots = [_WORKSPACE_ROOT.resolve()]
    tts_dir = Path(tempfile.gettempdir()) / _TTS_TEMP_DIRNAME
    try:
        roots.append(tts_dir.resolve())
    except OSError:  # pragma: no cover - tempdir 异常时降级只剩工作区根
        pass
    return roots


def _resolve_if_allowed(path: Path) -> Path:
    """resolve 后校验位于白名单根内，非法抛 ValueError。"""
    resolved = path.resolve()
    for root in _allowed_roots():
        try:
            resolved.relative_to(root)
            return resolved
        except ValueError:
            continue
    raise ValueError(f"artifact 路径不在白名单内: {path}")


def register_artifact(path: str, agent_id: str = "", user_id: str = "") -> Dict[str, Any]:
    """把一个磁盘文件注册为 artifact（幂等：同路径同 id）。

    路径不在白名单根内 / 文件不存在 → ValueError（调用方按需吞掉，
    artifact 是增强能力，注册失败不影响工具结果本身）。
    """
    p = Path(path)
    if not p.is_file():
        raise ValueError(f"artifact 文件不存在: {path}")
    resolved = _resolve_if_allowed(p)

    artifact_id = hashlib.sha1(str(resolved).encode("utf-8", errors="replace")).hexdigest()[:16]
    existing = _artifacts_store.get(artifact_id)
    if existing:
        return existing

    try:
        stat = resolved.stat()
    except OSError as e:
        raise ValueError(f"artifact 文件不可访问: {e}") from e
    mime = mimetypes.guess_type(resolved.name)[0] or "application/octet-stream"
    import time

    info: Dict[str, Any] = {
        "artifact_id": artifact_id,
        "kind": _artifact_kind(resolved.name),
        "name": resolved.name,
        "size": stat.st_size,
        "mime_type": mime,
        "agent_id": agent_id,
        "user_id": user_id,
        "path": str(resolved),
        "created_at": stat.st_mtime or time.time(),
    }
    _artifacts_store[artifact_id] = info
    return info


def _get_owned_artifact(artifact_id: str, current_user: Dict[str, Any]) -> Dict[str, Any]:
    """按 id 取 artifact，非属主与不存在统一 404（防 IDOR 探测）。"""
    info = _artifacts_store.get(artifact_id)
    if not info or info.get("user_id") != current_user["user_id"]:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return info


@router.get("/{artifact_id}", response_model=ArtifactInfo)
async def get_artifact_meta(artifact_id: str, current_user: Dict[str, Any] = Depends(get_current_user)):
    info = _get_owned_artifact(artifact_id, current_user)
    return ArtifactInfo(**{k: v for k, v in info.items() if k in ArtifactInfo.model_fields})


@router.get("/{artifact_id}/content")
async def get_artifact_content(artifact_id: str, current_user: Dict[str, Any] = Depends(get_current_user)):
    """内联返回产物文件（预览用）。读取时重新 resolve+白名单校验。"""
    info = _get_owned_artifact(artifact_id, current_user)
    p = Path(info.get("path", ""))
    try:
        resolved = _resolve_if_allowed(p)
    except (ValueError, OSError) as e:
        raise HTTPException(status_code=404, detail="Artifact file unavailable") from e
    if not resolved.is_file():
        raise HTTPException(status_code=404, detail="Artifact file unavailable")
    return FileResponse(resolved, media_type=info.get("mime_type") or "application/octet-stream")


# ---------------------------------------------------------------------------
# SSE 事件提取（供 console.py 两条 tool_result 出口调用）
# ---------------------------------------------------------------------------

_PATH_FIELDS = ("file_path", "audio_path", "output_ref.path")

# 截断/半截 JSON 的正则兜底：抓 "字段": "路径值"（与 _extract_approval_payload 同思路）。
# 值字符类排除引号，因此不需要尾引号也能正确停在上边界——同时覆盖
# [:500] 截断把收尾引号切掉的形态与完整 JSON 形态。
import re as _re

_PATH_RE = _re.compile(r'"(file_path|audio_path|output_ref\.path)"\s*:\s*"((?:[^"\\]|\\.)*)')


def _iter_candidate_paths(result_text: str) -> List[str]:
    """从工具结果文本提取候选产物路径（dict 精确解析优先，截断 JSON 正则兜底）。"""
    import json

    paths: List[str] = []
    try:
        parsed = json.loads(result_text)
    except Exception:
        parsed = None
    if isinstance(parsed, dict):
        for field in _PATH_FIELDS:
            node: Any = parsed
            ok = True
            for part in field.split("."):
                if isinstance(node, dict) and part in node:
                    node = node[part]
                else:
                    ok = False
                    break
            if ok and isinstance(node, str) and node:
                paths.append(node)
        # output_ref 嵌套 dict 形态（tool_output_ref.py 的引用结构）
        ref = parsed.get("output_ref")
        if isinstance(ref, dict) and isinstance(ref.get("path"), str) and ref["path"]:
            if ref["path"] not in paths:
                paths.append(ref["path"])
        return paths
    # 正则兜底（截断 JSON）
    for m in _PATH_RE.finditer(result_text):
        raw = m.group(2)
        try:
            raw = json.loads(f'"{raw}"')
        except Exception:
            pass
        if raw and raw not in paths:
            paths.append(raw)
    return paths


def extract_tool_artifacts(tool_name: str, result_text: str, agent_id: str = "", user_id: str = "") -> List[Dict[str, Any]]:
    """带工具名判读的产物提取（SSE 出口统一入口）。

    - file_operation **读形态**（结果 JSON 含 "content" 键=文件内容回显）
      不产生 artifact——读文件不是产出；写形态（success+file_path）才提取
    - 非 JSON 文本不判读工具名（解析不了读/写形态），按原通道正则兜底提取
      （半截 JSON 里的路径仍可注册）
    其余工具一律走 _extract_artifacts 原语义。
    """
    import json as _json

    if tool_name == "file_operation" and result_text:
        try:
            parsed = _json.loads(result_text)
        except Exception:
            parsed = None
        if isinstance(parsed, dict) and "content" in parsed:
            return []
    return _extract_artifacts(result_text, agent_id=agent_id, user_id=user_id)


def _extract_artifacts(result_text: str, agent_id: str = "", user_id: str = "") -> List[Dict[str, Any]]:
    """工具结果完整文本 → artifact SSE 事件列表。

    在 console.py 的脱敏/截断前调用（截断文本里路径可能只剩半截，
    正则兜底就是为它准备的）。env NEUROVA_ARTIFACT_EVENTS=0 关闭。
    """
    if os.environ.get("NEUROVA_ARTIFACT_EVENTS", "") == "0":
        return []
    if not result_text or not isinstance(result_text, str):
        return []
    events: List[Dict[str, Any]] = []
    for cand in _iter_candidate_paths(result_text):
        try:
            info = register_artifact(cand, agent_id=agent_id, user_id=user_id)
        except ValueError as e:
            logger.debug("artifact 注册跳过: %s", e)
            continue
        events.append(
            {
                "type": "artifact",
                "artifact_id": info["artifact_id"],
                "kind": info["kind"],
                "name": info["name"],
                "size": info["size"],
                "path": info["path"],
            }
        )
    return events
