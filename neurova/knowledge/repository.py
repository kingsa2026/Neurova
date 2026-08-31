"""
知识条目持久化仓库（R-4 知识库修复 + 三层隔离知识库扩展）

JSON 文件按 agent_id 分组存储知识条目（knowledge_id/title/content/category/
tags/source/confidence/created_at/updated_at），重启保留。
搜索为标题+内容不区分大小写包含匹配。

可见性模型（批次 1 隔离共享）：
- visibility="public"：任何认证用户可见；直接创建仅限 admin（API 层把关）
- visibility="private"：owner_user_id 本人可见；shared_with 内用户只读可见
- admin 角色全可见全可改；公共化须走 submit_to_public → admin 审批
- 存量条目迁移：无 visibility 字段 → private + owner_user_id="default"

替换 knowledge.py 中「委托 memory_manager + 模拟数据兜底」的不可靠路径：
- 有持久化仓库时用真实数据
- 无条目时返回空列表（禁止假数据）
"""

import datetime
import json
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from neurova.core.logger import get_logger

logger = get_logger(__name__)

DEFAULT_STORAGE_DIR = "./data/knowledge"

VISIBILITY_PUBLIC = "public"
VISIBILITY_PRIVATE = "private"
_SUBMISSION_PENDING = "pending"
_SUBMISSION_APPROVED = "approved"
_SUBMISSION_REJECTED = "rejected"


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
                        agent_id: [self._migrate_entry(i) for i in items if isinstance(i, dict)]
                        for agent_id, items in data.items()
                        if isinstance(items, list)
                    }
            except Exception as e:  # noqa: BLE001
                logger.warning("Failed to load knowledge repo %s: %s", self._path, e)

    @staticmethod
    def _migrate_entry(item: Dict[str, Any]) -> Dict[str, Any]:
        """存量条目补齐隔离字段：private + 虚拟 default 属主（保守策略）。"""
        if not isinstance(item.get("visibility"), str):
            item["visibility"] = VISIBILITY_PRIVATE
        if not isinstance(item.get("owner_user_id"), str):
            item["owner_user_id"] = "default"
        if not isinstance(item.get("shared_with"), list):
            item["shared_with"] = []
        if not isinstance(item.get("graph_node_ids"), list):
            item["graph_node_ids"] = []
        return item

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
        visibility: str = VISIBILITY_PRIVATE,
        owner_user_id: str = "",
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
            "visibility": visibility if visibility in (VISIBILITY_PUBLIC, VISIBILITY_PRIVATE) else VISIBILITY_PRIVATE,
            "owner_user_id": str(owner_user_id or "default"),
            "shared_with": [],
            "graph_node_ids": [],
            "submission": None,
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

    # ── 隔离与共享 ────────────────────────────────────────────

    def find_item(self, knowledge_id: str) -> Optional[Tuple[str, Dict[str, Any]]]:
        """跨 agent 分组查找条目，返回 (agent_id, 条目副本)；不存在返回 None"""
        with self._lock:
            for agent_id, items in self._items.items():
                for item in items:
                    if item.get("knowledge_id") == knowledge_id:
                        return agent_id, dict(item)
        return None

    @staticmethod
    def _user_id(user: Optional[Dict[str, Any]]) -> str:
        return str((user or {}).get("user_id") or "")

    @staticmethod
    def _is_admin(user: Optional[Dict[str, Any]]) -> bool:
        return str((user or {}).get("role") or "") == "admin"

    def can_view(self, user: Optional[Dict[str, Any]], item: Dict[str, Any]) -> bool:
        if self._is_admin(user):
            return True
        if item.get("visibility") == VISIBILITY_PUBLIC:
            return True
        uid = self._user_id(user)
        return uid != "" and (
            item.get("owner_user_id") == uid or uid in (item.get("shared_with") or [])
        )

    def can_modify(self, user: Optional[Dict[str, Any]], item: Dict[str, Any]) -> bool:
        if self._is_admin(user):
            return True
        return self._user_id(user) != "" and item.get("owner_user_id") == self._user_id(user)

    def visible_items(
        self,
        user: Optional[Dict[str, Any]],
        scope: str = "all",
        category: Optional[str] = None,
        agent_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """按当前用户可见性返回条目视图（scope: all/public/private/shared）。"""
        uid = self._user_id(user)
        with self._lock:
            groups = self._items.items() if not agent_id else [(agent_id, self._items.get(agent_id, []))]
            snapshot = [(aid, [dict(i) for i in items]) for aid, items in groups]
        results: List[Dict[str, Any]] = []
        for aid, items in snapshot:
            for item in items:
                if agent_id and aid != agent_id:
                    continue
                if scope == "public" and item.get("visibility") != VISIBILITY_PUBLIC:
                    continue
                if scope == "private" and not (
                    item.get("visibility") == VISIBILITY_PRIVATE
                    and item.get("owner_user_id") == uid
                ):
                    continue
                if scope == "shared" and not (
                    item.get("visibility") == VISIBILITY_PRIVATE
                    and uid in (item.get("shared_with") or [])
                ):
                    continue
                if scope == "all" and not self.can_view(user, item):
                    continue
                if category and item.get("category") != category:
                    continue
                results.append(item)
        return results

    def _find_or_raise(self, knowledge_id: str) -> Tuple[str, Dict[str, Any]]:
        found = self.find_item(knowledge_id)
        if found is None:
            raise LookupError("知识条目不存在: %s" % knowledge_id)
        return found

    def _set_entry(self, agent_id: str, item: Dict[str, Any]) -> Dict[str, Any]:
        """把修改后的条目副本写回存储并持久化。"""
        with self._lock:
            items = self._items.get(agent_id, [])
            for idx, stored in enumerate(items):
                if stored.get("knowledge_id") == item["knowledge_id"]:
                    item["updated_at"] = datetime.datetime.now(datetime.timezone.utc).timestamp()
                    items[idx] = item
                    self._save()
                    return dict(item)
        raise LookupError("知识条目不存在: %s" % item.get("knowledge_id"))

    def share_entry(
        self, user: Optional[Dict[str, Any]], knowledge_id: str, user_ids: List[str]
    ) -> Dict[str, Any]:
        """把私有条目共享给指定用户（只读）。owner/admin 可操作。"""
        agent_id, item = self._find_or_raise(knowledge_id)
        if not self.can_modify(user, item):
            raise PermissionError("仅条目属主或管理员可共享")
        if item.get("visibility") == VISIBILITY_PUBLIC:
            raise ValueError("公开条目无需共享")
        current = list(item.get("shared_with") or [])
        for uid in user_ids:
            uid = str(uid)
            if uid and uid not in current:
                current.append(uid)
        item["shared_with"] = current
        return self._set_entry(agent_id, item)

    def unshare_entry(
        self, user: Optional[Dict[str, Any]], knowledge_id: str, user_ids: List[str]
    ) -> Dict[str, Any]:
        agent_id, item = self._find_or_raise(knowledge_id)
        if not self.can_modify(user, item):
            raise PermissionError("仅条目属主或管理员可取消共享")
        removed = {str(u) for u in user_ids}
        item["shared_with"] = [u for u in (item.get("shared_with") or []) if u not in removed]
        return self._set_entry(agent_id, item)

    def submit_to_public(self, user: Optional[Dict[str, Any]], knowledge_id: str) -> Dict[str, Any]:
        """把私有条目提交公共库，进入 pending 待管理员审批。"""
        agent_id, item = self._find_or_raise(knowledge_id)
        if not self.can_modify(user, item):
            raise PermissionError("仅条目属主可提交公共库")
        if item.get("visibility") == VISIBILITY_PUBLIC:
            raise ValueError("条目已是公开状态")
        submission = item.get("submission") or {}
        if submission.get("status") == _SUBMISSION_PENDING:
            raise ValueError("该条目已在审批中")
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        item["submission"] = {
            "status": _SUBMISSION_PENDING,
            "submitted_at": now,
            "submitted_by": self._user_id(user),
            "reviewed_by": None,
            "note": None,
            "decided_at": None,
        }
        return self._set_entry(agent_id, item)

    def review_public_submission(
        self,
        user: Optional[Dict[str, Any]],
        knowledge_id: str,
        approve: bool,
        reviewed_by: str = "",
        note: str = "",
    ) -> Dict[str, Any]:
        """管理员审批公共库提交：approve 置 public，reject 维持 private。"""
        if not self._is_admin(user):
            raise PermissionError("仅管理员可审批公共库提交")
        agent_id, item = self._find_or_raise(knowledge_id)
        submission = item.get("submission") or {}
        if submission.get("status") != _SUBMISSION_PENDING:
            raise ValueError("该条目没有待审批的公共库提交")
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        submission.update(
            {
                "status": _SUBMISSION_APPROVED if approve else _SUBMISSION_REJECTED,
                "reviewed_by": str(reviewed_by or self._user_id(user)),
                "note": note or None,
                "decided_at": now,
            }
        )
        item["submission"] = submission
        if approve:
            item["visibility"] = VISIBILITY_PUBLIC
        return self._set_entry(agent_id, item)

    def pending_submissions(self) -> List[Dict[str, Any]]:
        """待审批提交清单（仅 admin 消费，API 层把关）。"""
        with self._lock:
            snapshot = [dict(i) for items in self._items.values() for i in items]
        return [i for i in snapshot if (i.get("submission") or {}).get("status") == _SUBMISSION_PENDING]

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

    def search_visible_items(
        self,
        user: Optional[Dict[str, Any]],
        query: str,
        scope: str = "all",
        category: Optional[str] = None,
        agent_id: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """在当前用户可见视图内做标题+内容包含匹配（不区分大小写）。"""
        q = (query or "").lower()
        results: List[Dict[str, Any]] = []
        for item in self.visible_items(user, scope=scope, category=category, agent_id=agent_id):
            if q and q not in (item.get("title") or "").lower() and q not in (item.get("content") or "").lower():
                continue
            results.append(item)
            if len(results) >= limit:
                break
        return results

    def update_knowledge(self, agent_id: str, knowledge_id: str, fields: Dict[str, Any]) -> bool:
        with self._lock:
            for item in self._items.get(agent_id, []):
                if item.get("knowledge_id") == knowledge_id:
                    for k, v in fields.items():
                        # 注意：visibility/shared_with/submission 不在白名单内——
                        # 公开与共享只能走专用方法（share/submit/review），防提权
                        if k in ("title", "content", "category", "tags", "confidence", "source", "graph_node_ids"):
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
