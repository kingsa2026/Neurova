"""
模型能力缓存

缓存模型能力探测结果，减少重复探测请求
"""

import datetime
import json
from neurova.core.logger import get_logger
import threading
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = get_logger(__name__)


def _new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex}" if prefix else uuid.uuid4().hex


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


@dataclass
class CachedCapability:
    model: str
    capabilities: Dict[str, Any] = field(default_factory=dict)
    provider_id: str = ""
    context_window: int = 0
    max_output_tokens: int = 0
    supports_functions: bool = False
    supports_vision: bool = False
    supports_streaming: bool = False
    supports_json_mode: bool = False
    cached_at: str = field(default_factory=_now_iso)
    ttl: int = 3600
    id: str = field(default_factory=lambda: _new_id("cap_"))

    def is_expired(self) -> bool:
        if self.ttl <= 0:
            return False
        try:
            cached_dt = datetime.datetime.fromisoformat(self.cached_at)
        except (ValueError, TypeError):
            return True
        if cached_dt.tzinfo is None:
            cached_dt = cached_dt.replace(tzinfo=datetime.timezone.utc)
        now = datetime.datetime.now(datetime.timezone.utc)
        return (now - cached_dt).total_seconds() > self.ttl

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CachedCapability":
        known = {f for f in cls.__dataclass_fields__}
        filtered = {k: v for k, v in data.items() if k in known}
        if "model" not in filtered:
            filtered["model"] = data.get("model_id", "")
        if "capabilities" not in filtered or filtered["capabilities"] is None:
            filtered["capabilities"] = {}
        return cls(**filtered)


class CapabilityCache:
    """模型能力缓存：线程安全、JSON 持久化、TTL 过期。"""

    DEFAULT_TTL = 3600

    def __init__(
        self,
        storage_dir: Optional[str] = None,
        default_ttl: int = DEFAULT_TTL,
    ) -> None:
        self._default_ttl = default_ttl
        self._lock = threading.RLock()
        self._entries: Dict[str, CachedCapability] = {}
        self._hits = 0
        self._misses = 0
        self._cache_path: Optional[Path] = None
        if storage_dir is not None:
            base = Path(storage_dir)
            base.mkdir(parents=True, exist_ok=True)
            self._cache_path = base / "capability_cache.json"
            self._load_cache()

    def _get_default_cache_path(self) -> Path:
        return Path("./data/llm/capability_cache.json")

    def _make_key(self, provider_id: str, model: str) -> str:
        return f"{provider_id}::{model}"

    def _load_cache(self) -> None:
        if self._cache_path is None or not self._cache_path.exists():
            return
        try:
            raw = self._cache_path.read_text(encoding="utf-8")
            if not raw.strip():
                return
            data = json.loads(raw)
        except (OSError, ValueError) as exc:
            logger.warning("Failed to load capability cache: %s", exc)
            return
        if not isinstance(data, dict):
            return
        for key, value in data.items():
            if not isinstance(value, dict):
                continue
            try:
                entry = CachedCapability.from_dict(value)
            except (TypeError, ValueError) as exc:
                logger.debug("Skip invalid cache entry %s: %s", key, exc)
                continue
            if not entry.is_expired():
                self._entries[key] = entry

    def _save_cache(self) -> None:
        if self._cache_path is None:
            return
        payload = {k: v.to_dict() for k, v in self._entries.items()}
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            self._cache_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            logger.warning("Failed to save capability cache: %s", exc)

    def get(self, provider_id: str, model: str) -> Optional[CachedCapability]:
        key = self._make_key(provider_id, model)
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                self._misses += 1
                return None
            if entry.is_expired():
                self._entries.pop(key, None)
                self._save_cache()
                self._misses += 1
                return None
            self._hits += 1
            return entry

    def set(
        self,
        provider_id: str,
        model: str,
        capabilities: Optional[Dict[str, Any]] = None,
        ttl: Optional[int] = None,
        **extra: Any,
    ) -> CachedCapability:
        if capabilities is None:
            capabilities = {}
        effective_ttl = ttl if ttl is not None else self._default_ttl
        entry = CachedCapability(
            model=model,
            capabilities=dict(capabilities),
            provider_id=provider_id,
            ttl=effective_ttl,
        )
        for field_name, value in extra.items():
            if field_name in CachedCapability.__dataclass_fields__:
                setattr(entry, field_name, value)
        key = self._make_key(provider_id, model)
        with self._lock:
            self._entries[key] = entry
            self._save_cache()
            return entry

    def invalidate(self, provider_id: str, model: str) -> bool:
        key = self._make_key(provider_id, model)
        with self._lock:
            existed = self._entries.pop(key, None) is not None
            if existed:
                self._save_cache()
            return existed

    def clear(self) -> int:
        with self._lock:
            count = len(self._entries)
            self._entries.clear()
            self._hits = 0
            self._misses = 0
            self._save_cache()
            return count

    def preheat(
        self,
        provider_id: str,
        model_ids: List[str],
        probe_func: Callable[[str, str], Dict[str, Any]],
        ttl: Optional[int] = None,
    ) -> Dict[str, CachedCapability]:
        results: Dict[str, CachedCapability] = {}
        for model_id in model_ids:
            cached = self.get(provider_id, model_id)
            if cached is not None:
                results[model_id] = cached
                continue
            try:
                caps = probe_func(provider_id, model_id)
            except Exception as exc:
                logger.warning(
                    "Preheat probe failed for %s/%s: %s",
                    provider_id,
                    model_id,
                    exc,
                )
                continue
            if not isinstance(caps, dict):
                caps = {}
            results[model_id] = self.set(provider_id, model_id, caps, ttl=ttl)
        return results

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            total = len(self._entries)
            expired = sum(1 for e in self._entries.values() if e.is_expired())
            total_requests = self._hits + self._misses
            hit_rate = (self._hits / total_requests) if total_requests > 0 else 0.0
            return {
                "total": total,
                "active": total - expired,
                "expired": expired,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": hit_rate,
            }


_singleton: Optional[CapabilityCache] = None
_singleton_lock = threading.Lock()
_DEFAULT_DIR = "./data/llm"


def get_capability_cache() -> CapabilityCache:
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            _singleton = CapabilityCache(storage_dir=_DEFAULT_DIR)
    return _singleton
