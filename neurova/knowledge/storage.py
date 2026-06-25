"""
知识库存储模块

用户级 API Key 和知识库配置的存储管理。基于 JSON 文件的轻量持久化。
"""

import datetime
import hashlib
import json
from neurova.core.logger import get_logger
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = get_logger(__name__)


def _new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex}" if prefix else uuid.uuid4().hex


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class KnowledgeStorage:
    """知识库配置与 API Key 的本地存储。"""

    def __init__(self, storage_dir: str) -> None:
        self._dir = Path(storage_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._configs_path = self._dir / "configs.json"
        self._collections_path = self._dir / "collections.json"
        self._memory_links_path = self._dir / "memory_links.json"
        self._configs: Dict[str, Dict[str, Any]] = {}
        self._collections: Dict[str, Dict[str, Any]] = {}
        self._memory_links: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()
        self._load()

    def _load(self) -> None:
        for path, target in (
            (self._configs_path, self._configs),
            (self._collections_path, self._collections),
            (self._memory_links_path, self._memory_links),
        ):
            if path.exists():
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    if isinstance(data, dict):
                        target.update(data)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Failed to load %s: %s", path, exc)

    def _save_configs(self) -> None:
        self._configs_path.write_text(
            json.dumps(self._configs, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _save_collections(self) -> None:
        self._collections_path.write_text(
            json.dumps(self._collections, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _save_memory_links(self) -> None:
        self._memory_links_path.write_text(
            json.dumps(self._memory_links, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _hash_api_key(self, key: str) -> str:
        salt = "neurova-knowledge-salt"
        return hashlib.sha256(f"{salt}:{key}".encode("utf-8")).hexdigest()

    def verify_api_key(self, key: str, hashed: str) -> bool:
        if not key or not hashed:
            return False
        return self._hash_api_key(key) == hashed

    def create_config(
        self,
        user_id: str,
        name: str,
        source_type: str,
        is_default: bool = False,
        is_active: bool = False,
        api_key: Optional[str] = None,
        settings: Optional[Dict[str, Any]] = None,
    ) -> str:
        with self._lock:
            cid = _new_id("kbc_")
            entry: Dict[str, Any] = {
                "id": cid,
                "user_id": user_id,
                "name": name,
                "source_type": source_type,
                "is_default": bool(is_default),
                "is_active": bool(is_active),
                "api_key_hash": self._hash_api_key(api_key) if api_key else None,
                "settings": dict(settings) if settings else {},
                "created_at": _now_iso(),
                "updated_at": _now_iso(),
            }
            if is_default:
                self._clear_default(user_id)
            if is_active:
                self._clear_active(user_id)
            self._configs[cid] = entry
            self._save_configs()
            return cid

    def _clear_default(self, user_id: str) -> None:
        for cfg in self._configs.values():
            if cfg.get("user_id") == user_id and cfg.get("is_default"):
                cfg["is_default"] = False
                cfg["updated_at"] = _now_iso()

    def _clear_active(self, user_id: str) -> None:
        for cfg in self._configs.values():
            if cfg.get("user_id") == user_id and cfg.get("is_active"):
                cfg["is_active"] = False
                cfg["updated_at"] = _now_iso()

    def get_config_by_id(self, config_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            cfg = self._configs.get(config_id)
            return dict(cfg) if cfg else None

    def get_configs_by_user(self, user_id: str) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(c) for c in self._configs.values() if c.get("user_id") == user_id]

    def get_default_config(self, user_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            for c in self._configs.values():
                if c.get("user_id") == user_id and c.get("is_default"):
                    return dict(c)
            return None

    def get_active_config(self, user_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            for c in self._configs.values():
                if c.get("user_id") == user_id and c.get("is_active"):
                    return dict(c)
            return None

    def update_config(self, config_id: str, **fields: Any) -> bool:
        with self._lock:
            cfg = self._configs.get(config_id)
            if not cfg:
                return False
            if "api_key" in fields:
                api_key = fields.pop("api_key")
                cfg["api_key_hash"] = self._hash_api_key(api_key) if api_key else None
            for k, v in fields.items():
                cfg[k] = v
            cfg["updated_at"] = _now_iso()
            self._save_configs()
            return True

    def delete_config(self, config_id: str) -> bool:
        with self._lock:
            existed = self._configs.pop(config_id, None) is not None
            if existed:
                self._save_configs()
            return existed

    def create_collection_mapping(
        self,
        user_id: str,
        config_id: str,
        collection_name: str,
        vector_store: str = "qdrant",
    ) -> str:
        with self._lock:
            mid = _new_id("kbm_")
            self._collections[mid] = {
                "id": mid,
                "user_id": user_id,
                "config_id": config_id,
                "collection_name": collection_name,
                "vector_store": vector_store,
                "created_at": _now_iso(),
            }
            self._save_collections()
            return mid

    def get_user_collections(self, user_id: str) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(m) for m in self._collections.values() if m.get("user_id") == user_id]

    def delete_collection_mapping(self, mapping_id: str) -> bool:
        with self._lock:
            existed = self._collections.pop(mapping_id, None) is not None
            if existed:
                self._save_collections()
            return existed

    def create_memory_knowledge_link(
        self,
        memory_id: str,
        knowledge_id: str,
        relation: str = "references",
    ) -> str:
        with self._lock:
            lid = _new_id("kbl_")
            self._memory_links[lid] = {
                "id": lid,
                "memory_id": memory_id,
                "knowledge_id": knowledge_id,
                "relation": relation,
                "created_at": _now_iso(),
            }
            self._save_memory_links()
            return lid

    def get_memory_links(self, memory_id: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._lock:
            if memory_id is None:
                return [dict(m) for m in self._memory_links.values()]
            return [dict(m) for m in self._memory_links.values() if m.get("memory_id") == memory_id]

    def delete_memory_link(self, link_id: str) -> bool:
        with self._lock:
            existed = self._memory_links.pop(link_id, None) is not None
            if existed:
                self._save_memory_links()
            return existed


_singleton: Optional["KnowledgeStorage"] = None
_singleton_lock = threading.Lock()
_DEFAULT_DIR = "./data/knowledge"


def get_knowledge_storage() -> KnowledgeStorage:
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            Path(_DEFAULT_DIR).mkdir(parents=True, exist_ok=True)
            _singleton = KnowledgeStorage(_DEFAULT_DIR)
    return _singleton
