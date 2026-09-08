"""PlanDocStore —— 计划 MD 文档落盘层。

存放位置：agent_workspaces/<agent_id>/docs/plan/<YYYYMMDD-HHMMSS>-<标题slug>.md
（目录不存在自动创建；文件名同秒冲突自动加 -2/-3 后缀避让）。

安全：文件名白名单校验（含路径穿越防护），数据按 agent 目录隔离。
"""

from __future__ import annotations

import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

_DEFAULT_AGENT = "default"
_SLUG_FALLBACK = "plan"
_NAME_RE = re.compile(r"^\d{8}-\d{6}-[^/\\]+\.md$")
_WIN_RESERVED = {"CON", "PRN", "AUX", "NUL"}

from neurova.plan_mode.errors import PlanDocError, PlanDocNotFound  # noqa: E402


def _workspace_base() -> Path:
    """agent_workspaces 根目录（项目根，与 home.py/knowledge_graph 同基座）。"""
    return Path(__file__).resolve().parents[2] / "agent_workspaces"


def _slugify(title: str) -> str:
    """标题 → 文件名安全 slug：保留中日英数字与 '-'，其余折叠为 '-'。"""
    cleaned = re.sub(r"[^\w\u4e00-\u9fff\-]+", "-", (title or "").strip(), flags=re.UNICODE)
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-")
    cleaned = cleaned[:60].strip("-") or _SLUG_FALLBACK
    stem = cleaned.upper()
    if stem in _WIN_RESERVED or re.match(r"^(COM|LPT)\d", stem):
        cleaned = f"_{cleaned}"
    return cleaned


class PlanDocStore:
    """计划文档存储（按 agent 隔离；RLock 保护；文件系统即真相源）。"""

    def __init__(self, base_dir: Optional[str] = None):
        self.base_dir = Path(base_dir) if base_dir else _workspace_base()
        self._lock = threading.RLock()

    def _agent_plan_dir(self, agent_id: str) -> Path:
        safe_agent = re.sub(r"[^\w\-]", "_", agent_id or _DEFAULT_AGENT) or _DEFAULT_AGENT
        return self.base_dir / safe_agent / "docs" / "plan"

    def _agent_dir(self, agent_id: str) -> Path:
        safe_agent = re.sub(r"[^\w\-]", "_", agent_id or _DEFAULT_AGENT) or _DEFAULT_AGENT
        return self.base_dir / safe_agent

    def save(self, agent_id: str, title: str, content: str) -> Dict[str, Any]:
        """落盘一份计划文档，返回 {name, rel_path, size, modified}。

        rel_path 相对 agent 工作目录（docs/plan/<name>.md）。
        """
        plan_dir = self._agent_plan_dir(agent_id)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        slug = _slugify(title)
        with self._lock:
            plan_dir.mkdir(parents=True, exist_ok=True)
            name = f"{stamp}-{slug}.md"
            n = 2
            while (plan_dir / name).exists():
                name = f"{stamp}-{slug}-{n}.md"
                n += 1
            path = plan_dir / name
            path.write_text(content or "", encoding="utf-8")
        rel = path.relative_to(self._agent_dir(agent_id))
        logger.info("计划文档落盘: %s", path)
        return {
            "name": name,
            "rel_path": rel.as_posix(),
            "size": path.stat().st_size,
            "modified": path.stat().st_mtime,
        }

    def read(self, agent_id: str, name: str) -> str:
        """读取计划文档全文；非法名/不存在抛 PlanDocError。"""
        path = self._resolve(agent_id, name)
        try:
            return path.read_text(encoding="utf-8")
        except FileNotFoundError as e:
            raise PlanDocNotFound(f"计划文档不存在: {name}") from e

    def list_documents(self, agent_id: str) -> List[Dict[str, Any]]:
        """列出该 agent 的计划文档（最新在前）。"""
        plan_dir = self._agent_plan_dir(agent_id)
        if not plan_dir.exists():
            return []
        out: List[Dict[str, Any]] = []
        for p in plan_dir.glob("*.md"):
            st = p.stat()
            out.append(
                {
                    "name": p.name,
                    "rel_path": p.relative_to(self._agent_dir(agent_id)).as_posix(),
                    "size": st.st_size,
                    "modified": st.st_mtime,
                }
            )
        out.sort(key=lambda d: d["modified"], reverse=True)
        return out

    def _resolve(self, agent_id: str, name: str) -> Path:
        if not _NAME_RE.match(name or ""):
            raise PlanDocError(f"非法计划文档名: {name!r}")
        plan_dir = self._agent_plan_dir(agent_id).resolve()
        path = (plan_dir / name).resolve()
        if plan_dir not in path.parents:
            raise PlanDocError(f"非法计划文档名: {name!r}")
        return path


_doc_store_singleton: Optional[PlanDocStore] = None


def get_plan_doc_store() -> PlanDocStore:
    """进程级单例（惰性创建）。"""
    global _doc_store_singleton
    if _doc_store_singleton is None:
        _doc_store_singleton = PlanDocStore()
    return _doc_store_singleton


def reset_plan_doc_store() -> None:
    """重置单例（测试用）。"""
    global _doc_store_singleton
    _doc_store_singleton = None
