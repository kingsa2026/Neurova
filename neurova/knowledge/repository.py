"""
知识条目持久化仓库（R-4 知识库修复）

JSON 文件按 agent_id 分组存储知识条目（knowledge_id/title/content/category/
tags/source/confidence/created_at/updated_at），重启保留。
搜索为标题+内容不区分大小写包含匹配。

替换 knowledge.py 中「委托 memory_manager + 模拟数据兜底」的不可靠路径：
- 有持久化仓库时用真实数据
- 无条目时返回空列表（禁止假数据）
"""

import datetime
import json
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

DEFAULT_STORAGE_DIR = "./data/knowledge"


class KnowledgeRepository:
    """按 agent_id 分组的 JSON 知识条目仓库。"""

    def __init__(self, storage_dir: str) -> None:
        self._dir = Path(storage_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path = self._dir / "knowledge.json"
        self._lock = threading.RLock()
        self._items: Dict[str, List[Dict[str, Any]]] = {}  # agent_id -> items
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self._items = {
                        agent_id: items
                        for agent_id, items in data.items()
                        if isinstance(items, list)
                    }
            except Exception as e:  # noqa: BLE001
                logger.warning("Failed to load knowledge repo %s: %s", self._path, e)

    def _save(self) -> None:
        try:
            self._path.write_text(
                json.dumps(self._items, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:  # noqa: BLE001
            logger.error("Failed to save knowledge repo %s: %s", self._path, e)

    # ── CRUD ──────────────────────────────────────────────────

    def create_knowledge(
        self,
        agent_id: str,
        title: str,
        content: str,
        category: str = "general",
        tags: Optional[List[str]] = None,
        source: str = "",
        confidence: float = 0.5,
        knowledge_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        now = datetime.datetime.now(datetime.timezone.utc).timestamp()
        item: Dict[str, Any] = {
            "knowledge_id": knowledge_id or str(uuid.uuid4()),
            "title": title,
            "content": content,
            "category": category,
            "tags": list(tags or []),
            "source": source,
            "confidence": float(confidence),
            "created_at": now,
            "updated_at": now,
        }
        with self._lock:
            self._items.setdefault(agent_id, []).append(item)
            self._save()
        return item

    def get_item(self, agent_id: str, knowledge_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            for item in self._items.get(agent_id, []):
                if item.get("knowledge_id") == knowledge_id:
                    return dict(item)
        return None

    def list_knowledge(
        self,
        agent_id: str,
        category: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        with self._lock:
            items = list(self._items.get(agent_id, []))
        if category:
            items = [i for i in items if i.get("category") == category]
        return [dict(i) for i in items[offset : offset + limit]]

    def search_knowledge(
        self,
        agent_id: str,
        query: str,
        category: Optional[str] = None,
        tags: Optional[List[str]] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        q = (query or "").lower()
        with self._lock:
            items = list(self._items.get(agent_id, []))
        results = []
        for item in items:
            if category and item.get("category") != category:
                continue
            if tags and not all(t in (item.get("tags") or []) for t in tags):
                continue
            if q and q not in (item.get("title") or "").lower() and q not in (item.get("content") or "").lower():
                continue
            results.append(dict(item))
            if len(results) >= limit:
                break
        return results

    def update_knowledge(self, agent_id: str, knowledge_id: str, fields: Dict[str, Any]) -> bool:
        with self._lock:
            for item in self._items.get(agent_id, []):
                if item.get("knowledge_id") == knowledge_id:
                    for k, v in fields.items():
                        if k in ("title", "content", "category", "tags", "confidence", "source"):
                            item[k] = v
                    item["updated_at"] = datetime.datetime.now(datetime.timezone.utc).timestamp()
                    self._save()
                    return True
        return False

    def delete_knowledge(self, agent_id: str, knowledge_id: str) -> bool:
        with self._lock:
            items = self._items.get(agent_id, [])
            for idx, item in enumerate(items):
                if item.get("knowledge_id") == knowledge_id:
                    del items[idx]
                    self._save()
                    return True
        return False


_singleton: Optional[KnowledgeRepository] = None
_singleton_lock = threading.Lock()


def get_knowledge_repository() -> KnowledgeRepository:
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            _singleton = KnowledgeRepository(DEFAULT_STORAGE_DIR)
    return _singleton
