"""
MCP Client Manager - MCP 客户端注册与连接生命周期管理
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


class MCPClientManager:
    """MCP 客户端注册表 - 基于 JSON 存储的轻量级实现。"""

    def __init__(self, storage_dir: str) -> None:
        self._dir = Path(storage_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path = self._dir / "clients.json"
        self._clients: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self._clients.update(data)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to load %s: %s", self._path, exc)

    def _save(self) -> None:
        self._path.write_text(
            json.dumps(self._clients, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def register_client(
        self,
        name: str,
        host: str,
        port: int,
        capabilities: Optional[List[str]] = None,
    ) -> str:
        with self._lock:
            cid = _new_id("mc_")
            caps = list(capabilities) if capabilities else []
            self._clients[cid] = {
                "id": cid,
                "name": name,
                "host": host,
                "port": port,
                "capabilities": caps,
                "status": "registered",
                "created_at": _now_iso(),
                "updated_at": _now_iso(),
            }
            self._save()
            return cid

    def get_client(self, client_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            c = self._clients.get(client_id)
            return dict(c) if c else None

    def connect_client(self, client_id: str) -> bool:
        with self._lock:
            c = self._clients.get(client_id)
            if not c:
                return False
            c["status"] = "connected"
            c["connected_at"] = _now_iso()
            c["updated_at"] = _now_iso()
            self._save()
            return True

    def disconnect_client(self, client_id: str) -> bool:
        with self._lock:
            c = self._clients.get(client_id)
            if not c:
                return False
            c["status"] = "disconnected"
            c["disconnected_at"] = _now_iso()
            c["updated_at"] = _now_iso()
            self._save()
            return True

    def list_clients(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._lock:
            if status is None:
                return [dict(c) for c in self._clients.values()]
            return [dict(c) for c in self._clients.values() if c.get("status") == status]

    def unregister_client(self, client_id: str) -> bool:
        with self._lock:
            existed = self._clients.pop(client_id, None) is not None
            if existed:
                self._save()
            return existed

    def update_client(self, client_id: str, **fields: Any) -> bool:
        with self._lock:
            c = self._clients.get(client_id)
            if not c:
                return False
            c.update(fields)
            c["updated_at"] = _now_iso()
            self._save()
            return True

    def get_statistics(self) -> Dict[str, Any]:
        with self._lock:
            total = len(self._clients)
            by_status: Dict[str, int] = {}
            for c in self._clients.values():
                s = c.get("status", "unknown")
                by_status[s] = by_status.get(s, 0) + 1
            return {
                "total_clients": total,
                "by_status": by_status,
            }


_singleton: Optional[MCPClientManager] = None
_singleton_lock = threading.Lock()
_DEFAULT_DIR = "./data/mcp_clients"


def get_mcp_client_manager() -> MCPClientManager:
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            Path(_DEFAULT_DIR).mkdir(parents=True, exist_ok=True)
            _singleton = MCPClientManager(_DEFAULT_DIR)
    return _singleton
