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
import difflib
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

# P0-2 revision 链：这些字段被覆盖前，旧值快照进条目 revisions 账本。
# graph_node_ids 等引擎簿记字段不在列——graph_bridge 回写不该刷屏账本。
_REVISION_FIELDS = ("title", "content", "category", "tags", "confidence", "source")


def _norm_title(title: str) -> str:
    """冲突检测的 subject 归一化：大小写/首尾空白不敏感。"""
    return (title or "").strip().lower()


def _chunk_hit(item: Dict[str, Any], chunk_index: int, score: float) -> Dict[str, Any]:
    """按块序号取块命中明细（content 实时从 content 切片，不存正文副本）。"""
    chunks = item.get("chunks") or []
    if 0 <= chunk_index < len(chunks):
        ch = chunks[chunk_index]
        content = ch.get("content", "")
        if not content and item.get("content"):
            content = item["content"][ch.get("char_start", 0) : ch.get("char_end", 0)]
    else:
        content = ""
    return {"chunk_index": chunk_index, "content": content, "score": score}


def _substring_chunk_hits(item: Dict[str, Any], q_lower: str) -> List[Dict[str, Any]]:
    """substring 兜底的块定位：返回首个包含查询词的块（整篇模式返回 []）。"""
    if not q_lower:
        return []
    for ch in item.get("chunks") or []:
        content = ch.get("content", "")
        if not content and item.get("content"):
            content = item["content"][ch.get("char_start", 0) : ch.get("char_end", 0)]
        if q_lower in content.lower():
            return [
                {
                    "chunk_index": ch.get("index", 0),
                    "content": content,
                    "score": 0.0,
                }
            ]
    return []


class KnowledgeRepository:
    """按 agent_id 分组的 JSON 知识条目仓库。"""

    def __init__(self, storage_dir: str) -> None:
        self._dir = Path(storage_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path = self._dir / "knowledge.json"
        self._tombstones_path = self._dir / "knowledge_tombstones.json"
        self._conflicts_path = self._dir / "knowledge_conflicts.json"
        self._lock = threading.RLock()
        self._items: Dict[str, List[Dict[str, Any]]] = {}  # agent_id -> items
        # P0-2 tombstone：knowledge_id -> {item, deleted_at, deleted_by, superseded_by}
        # 独立结构而非条目打标——读路径漏过滤的错误方向是"复活条目不可见"
        # （缺一个可见物），不是"已删数据混进主列表"（脏数据）。
        self._tombstones: Dict[str, Dict[str, Any]] = {}
        # P0-3 同值冲突账本：conflict_id -> {old_id, new_id, similarity, reason,
        # detected_at, status, resolution, resolved_by, resolved_at}
        self._conflicts: Dict[str, Dict[str, Any]] = {}
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
        """重建全部相关分片（懒重建，按脏标记触发）。仅在 dirty 时全量；否则增量由各分片维护。

        P0-2 分块：索引粒度从"条目"降为"块"——
        - 存量条目无 chunks 字段 → 就地惰性分块（split_with_meta 回写，一次性成本）
        - doc id = f"{knowledge_id}#{chunk_index}"，content = 标题 + 块正文
          （标题进块正文提升命中率，同 Dify chunk 策略）
        """
        items = self._items.get(agent_id, [])
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        migrated = False
        for it in items:
            # 惰性分块迁移：整篇模式条目补 chunks（幂等）
            if it.get("chunks") is None and it.get("content"):
                try:
                    from neurova.knowledge.splitter import split_with_meta

                    it["chunks"] = split_with_meta(it["content"])
                    migrated = True
                except Exception as e:  # noqa: BLE001
                    logger.warning("知识条目分块失败（按整篇索引）: %s", e)
            scope = self._get_shard_scope(it)
            if scope == "private":
                grouped.setdefault(f"user:{it.get('owner_user_id', 'default')}", []).append(it)
            else:
                grouped.setdefault(scope, []).append(it)
        if migrated:
            self._save()

        # 重建全部分片（每个分片小、non-incremental 重建成本可控）
        for key, shard_items in grouped.items():
            # key 已是完整分片键（user:<uid> / public / shared）
            store = self._get_vector_store_by_shard_key(key)
            if store is None:
                continue
            docs: List[Dict[str, Any]] = []
            for it in shard_items:
                kid = it.get("knowledge_id")
                if not kid:
                    continue
                title = it.get("title", "")
                chunks = it.get("chunks")
                if chunks:
                    for ch in chunks:
                        docs.append(
                            {
                                "id": f"{kid}#{ch.get('index', 0)}",
                                "content": f"{title}\n{ch.get('content', '')}",
                            }
                        )
                else:
                    docs.append({"id": kid, "content": f"{title} {it.get('content', '')}"})
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
        if self._tombstones_path.exists():
            try:
                data = json.loads(self._tombstones_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self._tombstones = {
                        kid: rec for kid, rec in data.items() if isinstance(rec, dict)
                    }
            except Exception as e:  # noqa: BLE001
                logger.warning("Failed to load knowledge tombstones %s: %s", self._tombstones_path, e)
        if self._conflicts_path.exists():
            try:
                data = json.loads(self._conflicts_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self._conflicts = {
                        cid: rec for cid, rec in data.items() if isinstance(rec, dict)
                    }
            except Exception as e:  # noqa: BLE001
                logger.warning("Failed to load knowledge conflicts %s: %s", self._conflicts_path, e)

    def _save_tombstones(self) -> None:
        try:
            self._tombstones_path.write_text(
                json.dumps(self._tombstones, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:  # noqa: BLE001
            logger.error("Failed to save knowledge tombstones %s: %s", self._tombstones_path, e)

    def _save_conflicts(self) -> None:
        try:
            self._conflicts_path.write_text(
                json.dumps(self._conflicts, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:  # noqa: BLE001
            logger.error("Failed to save knowledge conflicts %s: %s", self._conflicts_path, e)

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
        chunks: Optional[List[Dict[str, Any]]] = None,
        detect_conflict: bool = True,
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
            # P0-2 分块（[{content, index, char_start, char_end}]）；None=整篇模式
            "chunks": chunks,
        }
        with self._lock:
            self._items.setdefault(agent_id, []).append(item)
            self._save()
            self._index_dirty = True
            if detect_conflict:
                # P0-3 同值冲突可见化：检测失败绝不阻断写入（错误方向是
                # "少一个待审项"，不是"新知识丢失"）
                try:
                    self._detect_conflicts(agent_id, item)
                    self._save_conflicts()
                except Exception as e:  # noqa: BLE001
                    logger.warning("知识冲突检测失败（条目已入库）: %s", e)
        return item

    def get_item(self, agent_id: str, knowledge_id: str) -> Optional[Dict[str, Any]]:
        if knowledge_id in self._tombstones:
            return None
        with self._lock:
            for item in self._items.get(agent_id, []):
                if item.get("knowledge_id") == knowledge_id:
                    return dict(item)
        return None

    # ── 隔离与共享 ────────────────────────────────────────────

    def find_item(self, knowledge_id: str) -> Optional[Tuple[str, Dict[str, Any]]]:
        """跨 agent 分组查找条目，返回 (agent_id, 条目副本)；不存在返回 None"""
        if knowledge_id in self._tombstones:
            return None
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

        # Substring 兜底（索引不可用）——命中块定位到首个含查询词的块
        results: List[Dict[str, Any]] = []
        for item in visible:
            if q and q not in (item.get("title") or "").lower() and q not in (item.get("content") or "").lower():
                continue
            merged = dict(item)
            merged["chunk_hits"] = _substring_chunk_hits(item, q)
            results.append(merged)
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

        # 回映可见条目（按 knowledge_id 匹配，隔离兜底）；块级命中聚为 chunk_hits
        visible_by_id = {it.get("knowledge_id"): it for it in visible if it.get("knowledge_id")}
        results: List[Dict[str, Any]] = []
        hits_by_kid: Dict[str, List[Dict[str, Any]]] = {}
        seen_id = set()

        for store in shard_scopes:
            try:
                raw = store.search(query, limit=limit * 2)
            except Exception as e:
                logger.debug("知识库分片检索失败: %s", e)
                continue
            for hit in raw:
                hid = hit.get("id") or hit.get("memory_id") or ""
                kid, _, chunk_idx = hid.partition("#")
                item = visible_by_id.get(kid)
                if item is None:
                    continue
                score = float(hit.get("score", 0.0))
                if chunk_idx:
                    hits_by_kid.setdefault(kid, []).append(
                        _chunk_hit(item, int(chunk_idx), score)
                    )
                if kid in seen_id:
                    continue
                merged = dict(item)
                merged["score"] = score
                results.append(merged)
                seen_id.add(kid)

        # 按 score 降序，取 top-limit；附块级命中明细（按块得分降序）
        results.sort(key=lambda r: r.get("score", 0.0), reverse=True)
        for r in results:
            hits = hits_by_kid.get(r.get("knowledge_id", ""), [])
            hits.sort(key=lambda h: h.get("score", 0.0), reverse=True)
            r["chunk_hits"] = hits
        return results[:limit]

    def update_knowledge(self, agent_id: str, knowledge_id: str, fields: Dict[str, Any]) -> bool:
        with self._lock:
            for item in self._items.get(agent_id, []):
                if item.get("knowledge_id") == knowledge_id:
                    # P0-2 revision 链：知识实体字段被覆盖前，旧值快照进账本
                    # （append-only，重启保留）。失败不阻断更新。
                    changed = [k for k in fields if k in _REVISION_FIELDS and k in item and item[k] != fields[k]]
                    if changed:
                        try:
                            revs = item.setdefault("revisions", [])
                            revs.append(
                                {
                                    "old": {k: item[k] for k in changed},
                                    "changed_fields": changed,
                                    "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                                }
                            )
                        except Exception as e:  # noqa: BLE001
                            logger.warning("知识条目 revision 快照失败: %s", e)
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

    def delete_knowledge(
        self, agent_id: str, knowledge_id: str, deleted_by: str = ""
    ) -> bool:
        """tombstone 软删：条目移入墓碑账本（所有读路径不可见），数据保留可恢复。

        Utopia 0022「删除是事件不是减法」：物理清除走 purge_knowledge 显式通道。
        """
        with self._lock:
            items = self._items.get(agent_id, [])
            for idx, item in enumerate(items):
                if item.get("knowledge_id") == knowledge_id:
                    items.pop(idx)
                    self._tombstones[knowledge_id] = {
                        "item": item,
                        "agent_id": agent_id,
                        "deleted_at": datetime.datetime.now(datetime.timezone.utc).timestamp(),
                        "deleted_by": str(deleted_by or ""),
                        "superseded_by": None,
                    }
                    self._save()
                    self._save_tombstones()
                    self._index_dirty = True
                    return True
        return False

    def purge_knowledge(self, agent_id: str, knowledge_id: str) -> bool:
        """物理删除（显式清除通道：违规内容清理等）。墓碑与正文一并清除。"""
        with self._lock:
            items = self._items.get(agent_id, [])
            for idx, item in enumerate(items):
                if item.get("knowledge_id") == knowledge_id:
                    del items[idx]
                    self._tombstones.pop(knowledge_id, None)
                    self._save()
                    self._save_tombstones()
                    self._index_dirty = True
                    return True
        # 不在主存储也可能躺在墓碑里（已被软删过）
        if knowledge_id in self._tombstones:
            del self._tombstones[knowledge_id]
            self._save_tombstones()
            return True
        return False

    def restore_knowledge(self, knowledge_id: str) -> bool:
        """从墓碑复活条目（普通复活不带 supersede 链）。活着/不存在返回 False。"""
        with self._lock:
            rec = self._tombstones.get(knowledge_id)
            if rec is None:
                return False
            agent_id = rec.get("agent_id") or "default"
            self._items.setdefault(agent_id, []).append(rec["item"])
            del self._tombstones[knowledge_id]
            self._save()
            self._save_tombstones()
            self._index_dirty = True
            return True

    def list_deleted(self) -> List[Dict[str, Any]]:
        """墓碑清单（admin 审计消费）。记录含 item 快照 + 删除元数据。"""
        with self._lock:
            return [dict(rec, knowledge_id=kid) for kid, rec in self._tombstones.items()]

    def list_revisions(self, knowledge_id: str) -> List[Dict[str, Any]]:
        """条目 revision 账本（最新在前）。条目不存在返回 []。"""
        with self._lock:
            found = self.find_item(knowledge_id)
            if found is None:
                return []
            return list(reversed((found[1].get("revisions") or [])))

    # ── P0-3 同值冲突可见化 ────────────────────────────────────

    _CONFLICT_SIMILARITY_THRESHOLD = 0.9

    def _detect_conflicts(self, agent_id: str, new_item: Dict[str, Any]) -> None:
        """新条目 vs 同 agent 旧条目的同值冲突检测（调用方持有锁）。

        判定：标题归一化相似 ≥ 阈值 = "同一事实的新说法"候选（subject 强匹配），
        内容相异才是冲突本体；内容也相同属完全一致重复（P1 实体消解范围）。
        每条新条目只对内容最接近的旧条目记一条冲突，防批量导入刷屏。
        检测只记账不阻断写入——错误方向是"少一个待审项"，不是"新知识丢失"。
        """
        title = _norm_title(new_item.get("title", ""))
        if not title:
            return
        new_id = new_item.get("knowledge_id")
        best: Optional[Tuple[Dict[str, Any], float]] = None
        for old in self._items.get(agent_id, []):
            old_id = old.get("knowledge_id")
            if not old_id or old_id == new_id:
                continue
            old_title = _norm_title(old.get("title", ""))
            if not old_title:
                continue
            title_sim = difflib.SequenceMatcher(None, old_title, title).ratio()
            if title_sim < self._CONFLICT_SIMILARITY_THRESHOLD:
                continue
            content_sim = difflib.SequenceMatcher(
                None, str(old.get("content", "")), str(new_item.get("content", ""))
            ).ratio()
            if content_sim >= 0.999:
                continue  # 完全一致重复：不算同值冲突
            if best is None or content_sim > best[1]:
                best = (old, title_sim)
        if best is None:
            return
        old_item, title_sim = best
        self._conflicts[str(uuid.uuid4())] = {
            "old_id": old_item.get("knowledge_id"),
            "new_id": new_id,
            "knowledge_id": old_item.get("knowledge_id"),
            "title": new_item.get("title", ""),
            "similarity": round(title_sim, 4),
            "reason": "same_title: 新条目与旧条目标题一致，疑似同一事实的新说法",
            "detected_at": datetime.datetime.now(datetime.timezone.utc).timestamp(),
            "status": "pending",
            "resolution": None,
            "resolved_by": None,
            "resolved_at": None,
        }
        # 双端可追溯：旧条目自身视角的标记（读路径漏读只是少一个展示位，
        # 权威账本在 _conflicts，混入风险为零）
        old_item["conflict"] = {
            "status": "pending",
            "against": new_id,
        }

    def list_conflicts(self, status: str = "pending") -> List[Dict[str, Any]]:
        """冲突清单（默认待审 pending；status='resolved' 查裁决历史）。"""
        with self._lock:
            recs = [
                dict(rec, conflict_id=cid)
                for cid, rec in self._conflicts.items()
                if rec.get("status") == status
            ]
        recs.sort(key=lambda r: r.get("detected_at", 0), reverse=True)
        return recs

    def resolve_conflict(
        self, conflict_id: str, resolution: str, resolved_by: str = ""
    ) -> bool:
        """人工裁决冲突：keep_both 保留双条目关闭记录；supersede_old 旧条目
        打 superseded_by 链并 tombstone（新说法接管，旧值按 Utopia 0022 原路
        入墓碑可复活）。非法裁决值抛 ValueError。"""
        if resolution not in ("keep_both", "supersede_old"):
            raise ValueError("未知裁决: %r（有效值: keep_both / supersede_old）" % resolution)
        with self._lock:
            rec = self._conflicts.get(conflict_id)
            if rec is None or rec.get("status") != "pending":
                return False
            supersede_payload: Optional[Dict[str, Any]] = None
            if resolution == "supersede_old":
                old_id = rec.get("old_id")
                new_id = rec.get("new_id")
                found = self.find_item(old_id or "")
                if found is None:
                    raise LookupError("旧条目不存在或已删除: %s" % old_id)
                agent_id = found[0]
                old_item = None
                items_list = self._items.get(agent_id, [])
                for idx, stored in enumerate(items_list):
                    if stored.get("knowledge_id") == old_id:
                        old_item = items_list.pop(idx)
                        break
                if old_item is None:
                    raise LookupError("旧条目不存在或已删除: %s" % old_id)
                supersede_payload = {
                    "item": old_item,
                    "agent_id": agent_id,
                    "deleted_at": datetime.datetime.now(datetime.timezone.utc).timestamp(),
                    "deleted_by": str(resolved_by or ""),
                    "superseded_by": new_id,
                }
            rec["status"] = "resolved"
            rec["resolution"] = resolution
            rec["resolved_by"] = str(resolved_by or "")
            rec["resolved_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            if supersede_payload is not None:
                self._tombstones[rec["old_id"]] = supersede_payload
                self._save_tombstones()
            self._save_conflicts()
            self._index_dirty = True
            return True


_singleton: Optional[KnowledgeRepository] = None
_singleton_lock = threading.Lock()


def get_knowledge_repository() -> KnowledgeRepository:
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            _singleton = KnowledgeRepository(DEFAULT_STORAGE_DIR)
    return _singleton
