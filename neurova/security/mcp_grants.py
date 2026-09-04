"""E3 MCP 工具授权铸造（P2，docs/Neurova_OpenClaw工具技能专项对比 §5 E3）。

审批流（P0-6 分段审批）里用户以 remember 批准某个 MCP 工具后，铸造
(server, tool) 粒度的持久授权——后续同名调用免审批直达（治理预检短路，
等价 skip_governance 语义）。与 ApprovalManager 的命令级 remember
（_remember_approval exact/similar）互补：那是整条命令，这是工具粒度。

存储：data/security/mcp_tool_grants.json（原子写；单例懒加载，首次读前
零 IO）。has_grant 只读不建文件。
"""

import json
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

_DEFAULT_PATH = "data/security/mcp_tool_grants.json"


class ToolGrantStore:
    """MCP 工具持久授权（server, tool 粒度；原子 JSON 写）。"""

    def __init__(self, path: Optional[str] = None):
        self._path = Path(path or _DEFAULT_PATH)
        self._lock = threading.RLock()
        self._grants: Dict[str, Dict[str, Any]] = {}
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            if self._path.exists():
                self._grants = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("工具授权存储读取失败（回退空表）: %s", e)
            self._grants = {}

    def _save(self) -> bool:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._grants, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self._path)
            return True
        except Exception as e:
            logger.warning("工具授权存储写入失败: %s", e)
            return False

    @staticmethod
    def _key(server: str, tool: str) -> str:
        return f"{server}::{tool}"

    def mint_grant(self, server: str, tool: str, approved_by: str = "") -> bool:
        """铸造工具级持久授权（幂等；同一事务语义由调用方保证）。"""
        server, tool = str(server), str(tool)
        if not server or not tool:
            return False
        with self._lock:
            self._load()
            key = self._key(server, tool)
            if key not in self._grants:
                self._grants[key] = {
                    "server": server,
                    "tool": tool,
                    "approved_by": approved_by,
                    "granted_at": time.time(),
                }
                return self._save()
            return True

    def has_grant(self, server: str, tool: str) -> bool:
        with self._lock:
            self._load()
            return self._key(server, tool) in self._grants

    def revoke_grant(self, server: str, tool: str) -> bool:
        with self._lock:
            self._load()
            if self._key(server, tool) in self._grants:
                del self._grants[self._key(server, tool)]
                return self._save()
            return False

    def list_grants(self) -> List[Dict[str, Any]]:
        with self._lock:
            self._load()
            return list(self._grants.values())


_store: Optional[ToolGrantStore] = None
_store_lock = threading.Lock()


def get_tool_grant_store(path: Optional[str] = None) -> ToolGrantStore:
    global _store
    with _store_lock:
        if _store is None:
            _store = ToolGrantStore(path)
        return _store


def reset_tool_grant_store() -> None:
    global _store
    with _store_lock:
        _store = None


def parse_mcp_tool_name(tool_name: str) -> Optional[tuple]:
    """解析 mcp.{server_id}.{tool_name} 命名 → (server, tool)；非 MCP 返回 None。"""
    parts = str(tool_name).split(".", 2)
    if len(parts) == 3 and parts[0] == "mcp" and parts[1] and parts[2]:
        return (parts[1], parts[2])
    return None
