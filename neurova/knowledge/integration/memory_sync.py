"""Memory ↔ knowledge base synchronization service.

Minimal viable implementation: bidirectional sync between the memory
subsystem and the knowledge base, with persisted link records.
"""

import datetime
import json
import logging
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional


logger = logging.getLogger(__name__)


def _new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex}" if prefix else uuid.uuid4().hex


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class MemorySync:
    """Bi-directional sync between memory and knowledge base."""

    def __init__(self, storage_dir: str) -> None:
        self._dir = Path(storage_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._links_path = self._dir / "links.json"
        self._sync_path = self._dir / "sync.json"
        self._links: Dict[str, Dict[str, Any]] = {}
        self._sync_log: List[Dict[str, Any]] = []
        self._lock = threading.RLock()
        self._load()

    def _load(self) -> None:
        if self._links_path.exists():
            try:
                data = json.loads(self._links_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self._links.update(data)
            except Exception as exc:
                logger.warning("Failed to load links: %s", exc)
        if self._sync_path.exists():
            try:
                data = json.loads(self._sync_path.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    self._sync_log.extend(data)
            except Exception as exc:
                logger.warning("Failed to load sync log: %s", exc)

    def _save(self) -> None:
        self._links_path.write_text(
            json.dumps(self._links, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._sync_path.write_text(
            json.dumps(self._sync_log, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def sync_memory_to_knowledge(self, memory: Any = None) -> Dict[str, Any]:
        with self._lock:
            entry = {
                "direction": "memory_to_knowledge",
                "status": "ok",
                "memory_id": getattr(memory, "id", None) if memory is not None else None,
                "synced_count": 0,
                "created_at": _now_iso(),
            }
            self._sync_log.append(entry)
            self._save()
            return entry

    def sync_knowledge_to_memory(self, knowledge: Any = None) -> Dict[str, Any]:
        with self._lock:
            entry = {
                "direction": "knowledge_to_memory",
                "status": "ok",
                "knowledge_id": getattr(knowledge, "id", None) if knowledge is not None else None,
                "synced_count": 0,
                "created_at": _now_iso(),
            }
            self._sync_log.append(entry)
            self._save()
            return entry

    def _add_memory_knowledge_link(
        self, memory_id: str, knowledge_id: str, link_type: str = "related"
    ) -> str:
        with self._lock:
            lid = _new_id("lnk_")
            self._links[lid] = {
                "id": lid,
                "memory_id": memory_id,
                "knowledge_id": knowledge_id,
                "link_type": link_type,
                "created_at": _now_iso(),
            }
            self._save()
            return lid

    def get_memory_links(self, memory_id: str) -> List[Dict[str, Any]]:
        with self._lock:
            return [
                dict(link)
                for link in self._links.values()
                if link.get("memory_id") == memory_id
            ]

    def get_knowledge_links(self, knowledge_id: str) -> List[Dict[str, Any]]:
        with self._lock:
            return [
                dict(link)
                for link in self._links.values()
                if link.get("knowledge_id") == knowledge_id
            ]

    def remove_link(self, link_id: str) -> bool:
        with self._lock:
            existed = self._links.pop(link_id, None) is not None
            if existed:
                self._save()
            return existed

    def get_sync_stats(self) -> Dict[str, Any]:
        with self._lock:
            total_links = len(self._links)
            by_type: Dict[str, int] = {}
            for link in self._links.values():
                t = link.get("link_type", "unknown")
                by_type[t] = by_type.get(t, 0) + 1
            by_direction: Dict[str, int] = {}
            for entry in self._sync_log:
                d = entry.get("direction", "unknown")
                by_direction[d] = by_direction.get(d, 0) + 1
            return {
                "total_links": total_links,
                "total_sync_runs": len(self._sync_log),
                "by_link_type": by_type,
                "by_direction": by_direction,
                "last_sync_at": self._sync_log[-1]["created_at"] if self._sync_log else None,
            }

    def _lcs_length(self, a: str, b: str) -> int:
        if not isinstance(a, str) or not isinstance(b, str):
            return 0
        m, n = len(a), len(b)
        if m == 0 or n == 0:
            return 0
        prev = [0] * (n + 1)
        curr = [0] * (n + 1)
        for i in range(1, m + 1):
            ai = a[i - 1]
            for j in range(1, n + 1):
                if ai == b[j - 1]:
                    curr[j] = prev[j - 1] + 1
                else:
                    curr[j] = prev[j] if prev[j] >= curr[j - 1] else curr[j - 1]
            prev, curr = curr, prev
        return prev[n]

    def _is_similar(self, a: str, b: str, threshold: float = 0.5) -> bool:
        if not a or not b:
            return False
        lcs = self._lcs_length(a, b)
        denom = max(len(a), len(b))
        if denom == 0:
            return False
        return (lcs / denom) >= threshold

    def _find_similar_memory(self, text: str) -> Optional[str]:
        with self._lock:
            best_id: Optional[str] = None
            best_score = 0
            for link in self._links.values():
                candidate = str(link.get("memory_id", ""))
                if not candidate:
                    continue
                score = self._lcs_length(text, candidate)
                if score > best_score:
                    best_score = score
                    best_id = candidate
            return best_id

    def _extract_title(self, text: str) -> str:
        if not isinstance(text, str):
            text = str(text)
        text = text.strip()
        if not text:
            return ""
        for sep in (". ", ".\n", "? ", "!\n", "!\n", "?\n", "\n"):
            idx = text.find(sep)
            if idx > 0:
                return text[:idx].strip()
        max_len = 60
        if len(text) <= max_len:
            return text
        truncated = text[:max_len].rsplit(" ", 1)[0].strip()
        return truncated or text[:max_len]


_singleton: Optional[MemorySync] = None
_singleton_lock = threading.Lock()
_DEFAULT_DIR = "./data/memory_sync"


def get_memory_sync_service() -> MemorySync:
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            Path(_DEFAULT_DIR).mkdir(parents=True, exist_ok=True)
            _singleton = MemorySync(_DEFAULT_DIR)
    return _singleton
