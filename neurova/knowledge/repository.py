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
        # 分片索引：public（公库无隔离）/ user:<uid>（按属主私库）/ shared（共享集）
        self._indexes: Dict[str, Any] = {}
        self._index_dirty = True   # 索引脏标记（写入后置位，检索时按需重建）
        self._load()

    # ── TF-IDF 分片索引（复用 UnifiedVectorStore tfidf 后端）─────────────────

    @staticmethod
    def _shard_key(scope: str, user_id: str = "") -> str:
        """分片键：public / user:<uid> / shared"""
        if scope == "public":
            return "public"
        if scope == "shared":
            return "shared"
        return f"user:{user_id}"

    def _get_shard_scope(self, item: Dict[str, Any]) -> str:
        """条目所属分片：public 条目 → public；shared_with 非空 → shared；否则 → 属主私库"""
        if item.get("visibility") == VISIBILITY_PUBLIC:
            return "public"
        if item.get("shared_with"):
            return "shared"
        return "private"

    def _get_vector_store(self, scope: str = "public", user_id: str = "") -> Any:
        """按分片懒加载 TF-IDF 向量索引（失败返回 None，检索回退 substring）。"""
        key = self._shard_key(scope, user_id)
        return self._get_vector_store_by_shard_key(key)

    def _get_vector_store_by_shard_key(self, key: str) -> Any:
        """按完整分片键懒加载（public / user:<uid> / shared）。"""
        if key in self._indexes:
            return self._indexes[key]
        try:
            from neurova.cognitive_layers.memory_layer.unified_vector_store import UnifiedVectorStore

            self._indexes[key] = UnifiedVectorStore(backend="tfidf")
        except Exception as e:
            logger.warning("知识库 TF-IDF 索引(%s)初始化失败（回退 substring 检索）: %s", key, e)
            self._indexes[key] = None
        return self._indexes[key]

    def _rebuild_indexes(self, agent_id: str) -> None:
        """重建全部相关分片（懒重建，按脏标记触发）。仅在 dirty 时全量；否则增量由各分片维护。"""
        # 收集当前 agent 的条目 → 分组到分片
        items = self._items.get(agent_id, [])
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for it in items:
            scope = self._get_shard_scope(it)
            if scope == "private":
                grouped.setdefault(f"user:{it.get('owner_user_id', 'default')}", []).append(it)
            else:
                grouped.setdefault(scope, []).append(it)

        # 重建全部分片（每个分片小、non-incremental 重建成本可控）
        for key, shard_items in grouped.items():
            # key 已是完整分片键（user:<uid> / public / shared）
            store = self._get_vector_store_by_shard_key(key)
            if store is None:
                continue
            docs = [
                {"id": it.get("knowledge_id"), "content": f"{it.get('title', '')} {it.get('content', '')}"}
                for it in shard_items if it.get("knowledge_id")
            ]
            try:
                if docs:
                    store.index_memories(docs, incremental=False)
                else:
                    store.memory_vectors = []
                    store.memory_ids = []
                    store.memory_metadata = []
                    store._np_matrix = None
            except Exception as e:
                logger.warning("知识库 TF-IDF 分片 %s 重建失败: %s", key, e)

        self._index_dirty = False
        logger.debug("知识库 TF-IDF 分片索引重建完成: agent=%s, shards=%d", agent_id, len(grouped))

    def _ensure_indexes(self, agent_id: str) -> None:
        """检索前按脏标记重建索引（幂等）。"""
        with self._lock:
            if self._index_dirty:
                self._rebuild_indexes(agent_id)

    # 兼容：旧方法名包装（分片架构下返回 public 分片）
    def _rebuild_vector_index_for_agent(self, agent_id: str, user: Optional[Dict] = None) -> None:
        self._rebuild_indexes(agent_id)

    def _ensure_index(self, agent_id: str) -> None:
        self._ensure_indexes(agent_id)

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
            self._index_dirty = True
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
                    self._index_dirty = True
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

    def unpublish(self, knowledge_id: str, reviewed_by: str = "", note: str = "") -> Optional[Dict[str, Any]]:
        """管理员下架公共条目：保留数据，visibility 回 private，submission 置 rejected。

        与 delete_knowledge（物理删除）相对——公共库与私人库是同一份物理
        数据，管理员在公共库视角删除他人提交时必须走下架，否则会连坐删除
        属主的私人原始数据。

        非 public 条目返回 None（调用方自行决定是否物理删除）。
        """
        with self._lock:
            agent_id, item = self._find_or_raise(knowledge_id)
            if item.get("visibility") != VISIBILITY_PUBLIC:
                return None
            item["visibility"] = VISIBILITY_PRIVATE
            item["submission"] = {
                "status": _SUBMISSION_REJECTED,
                "submitted_at": (item.get("submission") or {}).get("submitted_at"),
                "submitted_by": (item.get("submission") or {}).get("submitted_by"),
                "reviewed_by": str(reviewed_by or ""),
                "note": note or "管理员下架",
                "decided_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
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
        """在当前用户可见视图内检索知识。

        优先走 TF-IDF 索引（按相关性 score 降序 top-k）；索引不可用/覆盖不足时
        回退标题+内容包含匹配（不区分大小写）。可见性过滤先于索引检索（隔离优先）。
        """
        q = (query or "").lower()

        # 可见性过滤（隔离优先，索引只做相似度排序）
        visible = self.visible_items(user, scope=scope, category=category, agent_id=agent_id)
        if not visible:
            return []

        # TF-IDF 索引路径：按脏标记重建后检索（相似度 top-k）
        idx_results = self._search_by_index(query, limit, agent_id, visible, user, scope, category)
        if idx_results is not None:
            return idx_results

        # Substring 兜底（索引不可用）
        results: List[Dict[str, Any]] = []
        for item in visible:
            if q and q not in (item.get("title") or "").lower() and q not in (item.get("content") or "").lower():
                continue
            results.append(item)
            if len(results) >= limit:
                break
        return results

    def _search_by_index(self, query, limit, agent_id, visible, user, scope, category):
        """分片索引检索；索引不可用返回 None（触发 substring 兜底）。

        检索分片：用户私库（user:<uid>）+ 公库（public）+ 共享集（shared），
        合并按 score 排序，再回映可见集过滤（隔离双保险）。
        """
        try:
            with self._lock:
                if self._index_dirty:
                    self._rebuild_indexes(agent_id or "default")
        except Exception as e:
            logger.warning("知识库索引重建失败（回退 substring）: %s", e)
            return None

        uid = self._user_id(user) or ""
        # 候选分片：公库 + 用户私库 + 共享集（无隔离需求的公库；有共享语义的共享集）
        shard_scopes = []
        public_store = self._get_vector_store("public")
        if public_store is not None and getattr(public_store, "memory_vectors", None):
            shard_scopes.append(public_store)
        if uid:
            user_store = self._get_vector_store("private", uid)
            if user_store is not None and getattr(user_store, "memory_vectors", None):
                shard_scopes.append(user_store)
        shared_store = self._get_vector_store("shared")
        if shared_store is not None and getattr(shared_store, "memory_vectors", None):
            shard_scopes.append(shared_store)

        if not shard_scopes:
            return None

        # 回映可见条目（按 knowledge_id 匹配，隔离兜底）
        visible_by_id = {it.get("knowledge_id"): it for it in visible if it.get("knowledge_id")}
        results: List[Dict[str, Any]] = []
        seen_id = set()

        for store in shard_scopes:
            try:
                raw = store.search(query, limit=limit * 2)
            except Exception as e:
                logger.debug("知识库分片检索失败: %s", e)
                continue
            for hit in raw:
                hid = hit.get("id") or hit.get("memory_id") or ""
                if hid in seen_id:
                    continue
                item = visible_by_id.get(hid)
                if item is None:
                    continue
                merged = dict(item)
                merged["score"] = float(hit.get("score", 0.0))
                results.append(merged)
                seen_id.add(hid)

        # 按 score 降序，取 top-limit
        results.sort(key=lambda r: r.get("score", 0.0), reverse=True)
        return results[:limit]

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
                    self._index_dirty = True
                    return True
        return False

    def delete_knowledge(self, agent_id: str, knowledge_id: str) -> bool:
        with self._lock:
            items = self._items.get(agent_id, [])
            for idx, item in enumerate(items):
                if item.get("knowledge_id") == knowledge_id:
                    del items[idx]
                    self._save()
                    self._index_dirty = True
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
