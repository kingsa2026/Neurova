"""回合文档型结论 → Markdown 工件（产出物面）。

产品口径（2026-11-14）：产出物面应展示 agent 的**文档型成果**，命名 =
任务内容 + 当前日期——而非工具大输出的内部引用（OutputRef，见
`tool_output_ref.py`，其落盘文件已从产出物提取中排除）。

判定（保守，宁缺勿滥——不给每轮长答案都造文件）：
- 回复长度 ≥ `NEUROVA_DOC_ARTIFACT_MIN_CHARS`（默认 800 字符）
- 且含至少一个 Markdown 标题（`^#{1,6}` 行）
- env `NEUROVA_DOC_ARTIFACT=0` 整体关闭（逃生开关）

命名：标题取回复第一个 Markdown 标题（去标记符/emoji/Windows 非法文件名
字符），清洗后为空则回退用户输入前 24 字；日期为当天 `YYYY-MM-DD`；
同名文件自动 `_2`/`_3` 递增，绝不覆盖既有产物。
落点 `<agent 工作区>/documents/`，注册进 artifacts 注册表（kind=markdown，
前端 dock 按 Markdown 面板预览）。

诚实降级：落盘/注册任一步失败返回 None 并告警，不阻断会话保存——
工件是增强能力，缺了不能伤害对话主链路。
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Any, Dict, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

_DEFAULT_MIN_CHARS = 800
_MAX_TITLE_CHARS = 40
_HEADING_RE = re.compile(r"^#{1,6}\s+(.+?)\s*$", re.MULTILINE)
_MD_MARKS_RE = re.compile(r"[*_`~\[\]()#]+")
# Windows 文件名非法字符 + 控制字符
_ILLEGAL_FS_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF"
    "\u2190-\u21FF\u2B00-\u2BFF]"
)


def _doc_artifact_enabled() -> bool:
    return os.environ.get("NEUROVA_DOC_ARTIFACT", "") != "0"


def _min_chars() -> int:
    raw = os.environ.get("NEUROVA_DOC_ARTIFACT_MIN_CHARS", "")
    try:
        return int(raw) if raw else _DEFAULT_MIN_CHARS
    except ValueError:
        return _DEFAULT_MIN_CHARS


def _clean_title(raw: str) -> str:
    """标题 → 可作文件名的干净串：去 Markdown 标记/emoji/非法字符，收敛空白。"""
    t = _MD_MARKS_RE.sub("", raw or "")
    t = _EMOJI_RE.sub("", t)
    t = _ILLEGAL_FS_CHARS.sub("", t)
    t = re.sub(r"\s+", " ", t).strip(" .-—…")
    return t[:_MAX_TITLE_CHARS].strip(" .-—…")


def _pick_path(docs_dir: Path, base: str) -> Path:
    """同名（同日）产物自动 _2/_3 递增，不覆盖既有文件。"""
    candidate = docs_dir / f"{base}.md"
    n = 2
    while candidate.exists():
        candidate = docs_dir / f"{base}_{n}.md"
        n += 1
    return candidate


def capture_document_artifact(
    *,
    user_input: str,
    reply: str,
    agent_id: str = "",
    user_id: str = "",
) -> Optional[Dict[str, Any]]:
    """把文档型回复落成 md 工件并注册；不满足判据/失败返回 None。

    返回值即 artifact SSE 事件形态（type/artifact_id/kind/name/size/path），
    与 `extract_tool_artifacts` 的输出同构，调用方可直接并入
    assistant_metadata.artifacts 供前端产出物面渲染。
    """
    if not _doc_artifact_enabled():
        return None
    if not agent_id:
        return None
    reply_text = str(reply or "")
    if len(reply_text) < _min_chars():
        return None
    if not _HEADING_RE.search(reply_text):
        # 无标题的长文是聊天回答，不是文档——不捕获
        return None

    title = _clean_title(_first_heading_text(reply_text))
    if not title:
        # 标题清洗后为空（如纯 emoji 标题）→ 回退任务内容（用户输入）
        title = _clean_title(str(user_input or ""))[:24]
    if not title:
        return None

    try:
        from neurova.core.agent_workspaces import get_agent_workspace_dir

        docs_dir = get_agent_workspace_dir(agent_id) / "documents"
        docs_dir.mkdir(parents=True, exist_ok=True)
        path = _pick_path(docs_dir, f"{title}_{time.strftime('%Y-%m-%d')}")
        path.write_text(reply_text, encoding="utf-8")
    except Exception as e:  # noqa: BLE001 - 落盘失败诚实降级
        logger.warning("文档工件落盘失败（跳过）: %s", e)
        return None

    try:
        from neurova.api.endpoints.artifacts_api import register_artifact

        info = register_artifact(str(path), agent_id=agent_id, user_id=user_id)
    except Exception as e:  # noqa: BLE001 - 注册失败不阻断会话保存
        logger.warning("文档工件注册失败（跳过）: %s", e)
        return None

    logger.info("文档型回复已落成工件: %s（%s）", path, info.get("kind"))
    return {
        "type": "artifact",
        "artifact_id": info["artifact_id"],
        "kind": info["kind"],
        "name": info["name"],
        "size": info["size"],
        "path": info["path"],
    }


def _first_heading_text(text: str) -> str:
    m = _HEADING_RE.search(text or "")
    return m.group(1).strip() if m else ""


__all__ = ["capture_document_artifact"]
