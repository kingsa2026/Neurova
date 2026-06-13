from __future__ import annotations

import datetime
import hashlib
import json
import logging
import mimetypes
import os
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex}" if prefix else uuid.uuid4().hex


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class MediaManager:
    """Media asset tracker backed by JSON persistence."""

    def __init__(self, storage_dir: str) -> None:
        self._dir = Path(storage_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._index_path = self._dir / "media.json"
        self._records: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()
        self._load()

    def _load(self) -> None:
        if not self._index_path.exists():
            return
        try:
            data = json.loads(self._index_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self._records.update(data)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to load media index: %s", exc)

    def _save(self) -> None:
        self._index_path.write_text(
            json.dumps(self._records, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def save_media(
        self,
        filename: str,
        content: bytes = b"",
        agent_id: str = "",
        user_id: Optional[str] = None,
        **extra: Any,
    ) -> str:
        with self._lock:
            mid = _new_id("med_")
            media_type = self._detect_media_type(filename)
            mime = self._get_mime_type(filename)
            checksum = hashlib.sha256(content).hexdigest() if content else None
            record: Dict[str, Any] = {
                "media_id": mid,
                "filename": filename,
                "agent_id": agent_id,
                "user_id": user_id,
                "media_type": media_type,
                "mime_type": mime,
                "size": len(content) if content else 0,
                "checksum": checksum,
                "description": "",
                "is_deleted": False,
                "created_at": _now_iso(),
                "updated_at": _now_iso(),
            }
            record.update(extra)
            self._records[mid] = record
            self._save()
            return mid

    def get_media(self, media_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            rec = self._records.get(media_id)
            if rec is None:
                return None
            return dict(rec)

    def list_media(
        self,
        agent_id: Optional[str] = None,
        media_type: Optional[str] = None,
        include_deleted: bool = False,
    ) -> List[Dict[str, Any]]:
        with self._lock:
            results: List[Dict[str, Any]] = []
            for rec in self._records.values():
                if not include_deleted and rec.get("is_deleted"):
                    continue
                if agent_id is not None and rec.get("agent_id") != agent_id:
                    continue
                if media_type is not None and rec.get("media_type") != media_type:
                    continue
                results.append(dict(rec))
            return results

    def update_media(self, media_id: str, **fields: Any) -> bool:
        with self._lock:
            rec = self._records.get(media_id)
            if rec is None:
                return False
            rec.update(fields)
            rec["updated_at"] = _now_iso()
            self._save()
            return True

    def delete_media(self, media_id: str, permanent: bool = False) -> bool:
        with self._lock:
            rec = self._records.get(media_id)
            if rec is None:
                return False
            if permanent:
                self._records.pop(media_id, None)
            else:
                rec["is_deleted"] = True
                rec["updated_at"] = _now_iso()
            self._save()
            return True

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            total = 0
            by_type: Dict[str, int] = {}
            by_agent: Dict[str, int] = {}
            total_size = 0
            for rec in self._records.values():
                if rec.get("is_deleted"):
                    continue
                total += 1
                mt = rec.get("media_type", "other") or "other"
                by_type[mt] = by_type.get(mt, 0) + 1
                ag = rec.get("agent_id", "") or ""
                if ag:
                    by_agent[ag] = by_agent.get(ag, 0) + 1
                total_size += int(rec.get("size", 0) or 0)
            return {
                "total_files": total,
                "total_size": total_size,
                "by_type": by_type,
                "by_agent": by_agent,
            }

    def _detect_media_type(self, filename: str) -> str:
        ext = os.path.splitext(filename)[1].lower().lstrip(".")
        if ext in ("png", "jpg", "jpeg", "gif", "bmp", "webp", "svg", "tiff", "tif"):
            return "image"
        if ext in ("mp4", "avi", "mov", "mkv", "webm", "flv", "m4v"):
            return "video"
        if ext in ("mp3", "wav", "ogg", "flac", "m4a", "aac", "wma"):
            return "audio"
        if ext in ("pdf", "doc", "docx", "odt", "txt", "md", "rst"):
            return "document"
        return "other"

    def _get_mime_type(self, filename: str) -> str:
        mime, _ = mimetypes.guess_type(filename)
        return mime or "application/octet-stream"


_singleton: Optional[MediaManager] = None
_singleton_lock = threading.Lock()
_DEFAULT_DIR = "./data/media"


def get_media_manager() -> MediaManager:
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            Path(_DEFAULT_DIR).mkdir(parents=True, exist_ok=True)
            _singleton = MediaManager(_DEFAULT_DIR)
    return _singleton
