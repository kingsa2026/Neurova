"""
技能市场 提交审批 存储（skill submissions）

用户提交技能上架申请 → pending → 管理员审批（approved=写入市场目录 /
rejected=不上架）。与 market_store 的"已上架目录"分离：提交单独立存储
（data/marketplace/submissions.json），公开列表天然只见已上架技能。

契约见 tests/unit/api/test_skill_submission.py。
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

_DEFAULT_PATH = "./data/marketplace/submissions.json"

_SUBMISSION_PENDING = "pending"
_SUBMISSION_APPROVED = "approved"
_SUBMISSION_REJECTED = "rejected"


class MarketSubmissionStore:
    """市场技能提交单存储：JSON 持久化 + RLock 并发保护。"""

    def __init__(self, storage_path: Optional[str] = None):
        self._path = Path(
            storage_path
            or os.environ.get("NEUROVA_MARKET_SUBMISSIONS")
            or _DEFAULT_PATH
        )
        self._items: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()
        self._load()

    # ── 持久化 ──────────────────────────────────────────

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                self._items = raw
        except Exception as exc:  # noqa: BLE001
            logger.warning("load market submissions failed: %s", exc)

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(self._items, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("save market submissions failed: %s", exc)

    # ── 操作 ────────────────────────────────────────────

    def create(self, entry: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            sid = f"subs_{uuid.uuid4().hex[:12]}"
            item = dict(entry)
            item["id"] = sid
            item["status"] = _SUBMISSION_PENDING
            item["created_at"] = time.time()
            item["reviewed_by"] = None
            item["review_note"] = None
            item["decided_at"] = None
            self._items[sid] = item
            self._save()
            return dict(item)

    def list_all(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._lock:
            items = [dict(i) for i in self._items.values()]
        if status:
            items = [i for i in items if i.get("status") == status]
        items.sort(key=lambda i: i.get("created_at", 0.0), reverse=True)
        return items

    def get(self, submission_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            item = self._items.get(submission_id)
            return dict(item) if item else None

    def set_status(
        self,
        submission_id: str,
        status: str,
        reviewed_by: str = "",
        note: str = "",
    ) -> Optional[Dict[str, Any]]:
        with self._lock:
            item = self._items.get(submission_id)
            if not item:
                return None
            item["status"] = status
            item["reviewed_by"] = reviewed_by or None
            item["review_note"] = note or None
            item["decided_at"] = time.time()
            self._save()
            return dict(item)


_singleton: Optional[MarketSubmissionStore] = None
_singleton_lock = threading.Lock()


def get_market_submission_store() -> MarketSubmissionStore:
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            _singleton = MarketSubmissionStore()
    return _singleton


def reset_market_submission_store() -> None:
    """重置单例（测试用；配合 NEUROVA_MARKET_SUBMISSIONS 隔离路径）。"""
    global _singleton
    with _singleton_lock:
        _singleton = None
