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

import contextlib
import datetime
import difflib
import hashlib
import json
import os
import re
import threading
import unicodedata
import uuid
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

from neurova.core.logger import get_logger
from neurova.knowledge.foundation.entry_ledger import EntryLedger
from neurova.knowledge.foundation.knowledge_facts import (
    ADOPTION_OUTCOMES,
    KnowledgeFactStore,
)
from neurova.knowledge.foundation.narratives import FOUNDATION_DB_NAME, NarrativeStore
from neurova.knowledge.foundation.storage_fence import (
    PRODUCTION_STORAGE_DIR,
    assertNotUnderProductionStorage,
)
from neurova.knowledge.lifecycle import (
    ACTIVE,
    ARCHIVED,
    isExpired,
    isRetrievable,
    normalizeLifecycleStatus,
)

logger = get_logger(__name__)

DEFAULT_STORAGE_DIR = PRODUCTION_STORAGE_DIR
# 工单 019a–019b-4b：条目权威已从 knowledge.json 换到底座库，**默认开**。
# 留一个显式回退值（off/json）而不是删掉这条路：搬家是可逆动作，回退步骤见
# docs/specs/2026-09-20-knowledge-foundation-design.md 的开关台账。
NARRATIVE_STORE_ENV = "NEUROVA_KB_NARRATIVE_STORE"
_JSON_BACKEND_VALUES = ("0", "false", "off", "no", "json")
VISIBILITY_PUBLIC = "public"
VISIBILITY_PRIVATE = "private"
_SUBMISSION_PENDING = "pending"
_SUBMISSION_APPROVED = "approved"
_SUBMISSION_REJECTED = "rejected"

# P0-2 revision 链：这些字段被覆盖前，旧值快照进条目 revisions 账本。
# graph_node_ids 等引擎簿记字段不在列——graph_bridge 回写不该刷屏账本。
_REVISION_FIELDS = (
    "title", "content", "category", "tags", "confidence", "source",
    "valid_until", "lifecycle_status",
)

# 增量操作数达到该阈值退回全量重建——删除不回退 df/词表，
# 陈旧 IDF 由本阈值有界收敛（同时约束 TF-IDF 词表漂移导致的向量维度不齐）
_INCREMENTAL_OPS_LIMIT = 200


def _norm_title(title: str) -> str:
    """冲突检测的 subject 归一化：大小写/首尾空白不敏感。"""
    return (title or "").strip().lower()


def _narrativeStoreEnabled() -> bool:
    """叙述层权威在不在底座库。默认在——只有显式写 off/json 才退回旧行为。

    默认值翻向 SQLite 之后，"没设过环境变量"和"设成 off"是两件不同的事：
    前者是新常态，后者是一次有意的回退，日志与报错都按后者措辞。
    """
    return (os.environ.get(NARRATIVE_STORE_ENV) or "").strip().lower() not in _JSON_BACKEND_VALUES


def _chunk_hit(item: Dict[str, Any], chunk_index: int, score: float) -> Dict[str, Any]:
    """按块序号取块命中明细（content 实时从 content 切片，不存正文副本）。"""
    chunks = item.get("chunks") or []
    parent_index = None
    if 0 <= chunk_index < len(chunks):
        ch = chunks[chunk_index]
        content = ch.get("content", "")
        if not content and item.get("content"):
            content = item["content"][ch.get("char_start", 0) : ch.get("char_end", 0)]
        parent_index = ch.get("parent_index")
    else:
        content = ""
    hit = {"chunk_index": chunk_index, "content": content, "score": score}
    if parent_index is not None:
        hit["parent_index"] = parent_index
    return hit


def parent_context_text(item: Dict[str, Any], parent_index: int) -> str:
    """父块上下文（P1#6 + 下批①rebuildParentContent lite）：原文为底 + 已编辑子块叠加。

    - 只叠加 revision>0 的子块——未编辑子块原文天然含于父底，拼接反造成
      子块 overlap 窗口的重复；
    - 互叠的编辑区间并成冲突组：组内最高 revision 为 winner 区间替换生效，
      loser 文本尾部追加（信息不静默丢，对齐 WeKnora latest-wins/loser-appended）；
    - 无任何编辑 → 与旧版逐字节一致（零回归）。
    """
    parent = next(
        (p for p in (item.get("parents") or []) if p.get("index") == parent_index), None
    )
    if parent is None:
        return ""
    full = item.get("content") or ""
    base = str(parent.get("content") or "") or full[
        parent.get("char_start", 0) : parent.get("char_end", 0)
    ]
    base_start = int(parent.get("char_start", 0))
    edits = [
        c
        for c in (item.get("chunks") or [])
        if c.get("parent_index") == parent_index
        and int(c.get("revision", 0) or 0) > 0
        and c.get("content")
    ]
    if not edits:
        return base

    ordered = sorted(
        edits, key=lambda e: (int(e.get("char_start", 0)), -int(e.get("revision", 0) or 0))
    )
    out: List[str] = []
    tails: List[str] = []
    pos = base_start
    i = 0
    while i < len(ordered):
        first = ordered[i]
        group = [first]
        g_end = int(first.get("char_end", 0))
        j = i + 1
        while j < len(ordered) and int(ordered[j].get("char_start", 0)) <= g_end:
            group.append(ordered[j])
            g_end = max(g_end, int(ordered[j].get("char_end", 0)))
            j += 1
        winner = max(group, key=lambda g: int(g.get("revision", 0) or 0))
        ws = max(int(winner.get("char_start", 0)), pos)
        if ws - pos > 0:
            out.append(base[pos - base_start : ws - base_start])
        out.append(str(winner.get("content") or ""))
        for loser in sorted(group, key=lambda g: int(g.get("revision", 0) or 0)):
            if loser is not winner:
                tails.append(str(loser.get("content") or ""))
        pos = g_end
        i = j
    if pos - base_start < len(base):
        out.append(base[max(0, pos - base_start) :])
    result = "".join(out)
    if tails:
        result += "\n" + "\n".join(tails)
    return result


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


class ChunkRevisionConflict(Exception):
    """P1#8 chunk 编辑乐观锁：expected_revision 与块当前 revision 不符。

    时不静默覆盖，调用方须重读最新块后重试。"""


def _contentFingerprint(tenantId: str, content: str) -> str:
    """精确去重键：租户 + 规范化正文；空白差异不算不同文档。"""
    normalized = unicodedata.normalize("NFKC", str(content or ""))
    normalized = re.sub(r"\s+", " ", normalized).strip().casefold()
    seed = "%s|%s" % (str(tenantId or "default"), normalized)
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _sourceEvidence(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "source": str(item.get("source") or ""),
        "source_type": str(item.get("source_type") or ""),
        "source_path": str(item.get("source_path") or ""),
        "ingest_time": str(item.get("ingest_time") or ""),
    }


def _geoOf(geo: Any) -> Optional[Dict[str, float]]:
    """geo 入库形状：只收可解析的 lat/lon；坏形状归 None，不猜坐标。"""
    if not isinstance(geo, dict):
        return None
    try:
        lat, lon = float(geo.get("lat")), float(geo.get("lon"))
    except (TypeError, ValueError):
        return None
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return None
    return {"lat": lat, "lon": lon}


def _haversineKm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    import math

    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371.0088 * math.asin(math.sqrt(a))


class KnowledgeRepository:
    """按 agent_id 分组的条目仓库：权威默认在底座库叙述表，显式关闸才回 knowledge.json。

    `self._items` 是唯一的内存权威——分片索引、检索、冲突检测全部只读它，
    所以换后端只需要换 `_load` / `_save` 两个边界。
    """

    def __init__(self, storage_dir: str) -> None:
        self._dir = Path(storage_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path = self._dir / "knowledge.json"
        self._tombstones_path = self._dir / "knowledge_tombstones.json"
        self._conflicts_path = self._dir / "knowledge_conflicts.json"
        self._narrative_db_path = str(self._dir / FOUNDATION_DB_NAME)
        # 围栏必须在建库之前：默认翻向底座库之后，构造本身就会落文件（迁移建表），
        # 只守 _save 等于守不住——测试会话会在 data/knowledge/ 里造出真库。
        self._assertNotWritingProductionUnderPytest()
        self._narratives: Optional[NarrativeStore] = None
        # 治理投影只在闸内发生（工单 019b-2）；闸外三个写动词与旧行为逐字相同。
        # 账本与事实库句柄都是短命的：长持有会让 Windows 清不掉 tmp 目录。
        self._projectionDrift: List[str] = []
        if _narrativeStoreEnabled():
            self._narratives = NarrativeStore(self._narrative_db_path)
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
        self._index_dirty = True   # 索引脏标记（未建立/退回全量时置位，检索前按需重建）
        # P0#1 增量操作队列：[("reindex"|"remove", knowledge_id)]，检索前按序应用；
        # 达 _INCREMENTAL_OPS_LIMIT 或异常退回全量重建
        self._pending_ops: List[Tuple[str, str]] = []
        # FTS5 持久倒排按需创建；写路径只置脏，首次检索时 reconcile。
        self._fts: Any = None
        self._ftsDirty = True
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

    def _item_index_docs(self, item: Dict[str, Any]) -> List[Dict[str, Any]]:
        """条目 → 索引文档载荷（doc_id 形态与拼接的唯一单源，rebuild/增量共用）。

        - 分块条目：doc id = f"{knowledge_id}#{chunk_index}"，content 空时按
          偏移从正文切片复原（存储不存正文副本的旧契约兼容）。
        - 整篇模式：doc id = knowledge_id。
        两种形态都经 build_index_content（标题+context_header+正文）组装，
 preview/重索引/embedding 可字节级复现索引输入。
        """
        from neurova.knowledge.splitter import build_index_content

        kid = item.get("knowledge_id")
        if not kid:
            return []
        title = item.get("title", "")
        full = item.get("content", "")
        docs: List[Dict[str, Any]] = []
        chunks = item.get("chunks")
        if chunks:
            for ch in chunks:
                content = ch.get("content") or ""
                if not content and full:
                    content = full[ch.get("char_start", 0) : ch.get("char_end", 0)]
                docs.append(
                    {
                        "id": f"{kid}#{ch.get('index', 0)}",
                        "content": build_index_content(title, content, ch.get("context_header", "")),
                    }
                )
        else:
            docs.append({"id": str(kid), "content": build_index_content(title, full)})
        return docs

    def _rebuild_indexes(self, agent_id: str = "") -> None:
        """全量重建全部分片（覆盖**所有** agent 分组）。

        修复（P0#1 同根因放大视角）：原实现只重建传入 agent 的条目，其他
        分组条目在重建时被静默清出索引。索引按可见性分片、与 agent 分组
        无关，故全量重建必须遍历全库。agent_id 参数仅保留签名兼容。

        P0-2 分块粒度与 P0#1 增量共用 _item_index_docs 单源：
        - 存量条目无 chunks → 就地惰性分块（split_with_meta 回写，一次性成本）
        """
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        migrated = False
        for items in self._items.values():
            for it in items:
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
                docs.extend(self._item_index_docs(it))
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

        # 本帧已无条目的历史分片清空（全删后不留陈旧向量/漂移词表）
        for key, store in self._indexes.items():
            if store is not None and key not in grouped:
                store.memory_vectors = []
                store.memory_ids = []
                store.memory_metadata = []
                store._np_matrix = None

        self._pending_ops = []
        self._index_dirty = False
        logger.debug("知识库 TF-IDF 分片索引全量重建完成: shards=%d", len(grouped))

    def _record_index_op(self, kind: str, knowledge_id: str) -> None:
        """记录分片级增量操作（reindex / remove，调用方持锁）。

        索引未建立/待重建（dirty）时为空操作——随后的全量重建覆盖一切，
        增量操作无需也不必重复应用。
        """
        if self._index_dirty or not knowledge_id:
            return
        self._pending_ops.append((kind, str(knowledge_id)))

    def _apply_pending_ops(self) -> None:
        """把待应用操作落到分片索引（调用方持锁；异常由 _ensure_indexes 兜底）。

        reindex 统一语义 = 先从所有已加载分片剥离该条目的旧向量（含块级
        doc id），再按条目当前分片增量写入——新增/更新/换分片（visibility/
        shared_with 变更）共用一条路径，无需在记录侧区分。
        """
        ops = self._pending_ops
        self._pending_ops = []
        for kind, kid in ops:
            for store in self._indexes.values():
                if store is not None:
                    store.remove_documents(
                        lambda mid, _k=kid: mid == _k or str(mid).startswith(_k + "#")
                    )
            if kind != "reindex":
                continue
            found = self.find_item(kid)  # 墓碑/已删除 → None：只剥离不回灌
            if found is None:
                continue
            item = found[1]
            docs = self._item_index_docs(item)
            scope = self._get_shard_scope(item)
            store = (
                self._get_vector_store("private", item.get("owner_user_id", "default"))
                if scope == "private"
                else self._get_vector_store(scope)
            )
            if store is not None and docs:
                store.index_memories(docs, incremental=True)

    def _ensureFts(self) -> Any:
        with self._lock:
            if self._fts is None:
                from neurova.knowledge.fts_index import KnowledgeFtsIndex

                self._fts = KnowledgeFtsIndex(str(self._dir / "knowledge_fts.db"))
            if not self._ftsDirty:
                return self._fts
            snapshot = {
                aid: [dict(item) for item in items]
                for aid, items in self._items.items()
            }
            self._ftsDirty = False
        self._fts.reconcile(snapshot)
        return self._fts

    def ftsSearch(
        self,
        query: str,
        user: Optional[Dict[str, Any]] = None,
        *,
        scope: str = "all",
        agent_id: Optional[str] = None,
        category: Optional[str] = None,
        tags: Optional[List[str]] = None,
        source: Optional[str] = None,
        updated_after: Optional[float] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """FTS5 倒排检索；索引按需 reconcile，失败交给调用方降级。"""
        return self._ensureFts().search(
            query, user, scope=scope, agent_id=agent_id, category=category,
            tags=tags, source=source, updated_after=updated_after, limit=limit,
        )

    def ftsHealth(self) -> Dict[str, Any]:
        return self._ensureFts().health()

    def maintainIndexes(self, force: bool = False) -> Dict[str, Any]:
        """周期维护：增量应用 pending；force=True 时全量重建全部分片。"""
        with self._lock:
            if force:
                self._rebuild_indexes("")
            else:
                self._ensure_indexes("default")
            return {
                "force": bool(force),
                "dirty": bool(self._index_dirty),
                "pending_ops": len(self._pending_ops),
                "indexes": sum(1 for store in self._indexes.values() if store is not None),
            }

    def _ensure_indexes(self, agent_id: str) -> None:
        """检索前维护索引（幂等）：dirty→全量重建；有增量操作→按序应用；
        操作数达阈值/应用异常→退回全量重建（陈旧 IDF 有界收敛）。"""
        with self._lock:
            if self._index_dirty:
                self._rebuild_indexes(agent_id)
                return
            if not self._pending_ops:
                return
            if len(self._pending_ops) >= _INCREMENTAL_OPS_LIMIT:
                logger.debug(
                    "知识库增量操作达阈值(%d)，退回全量重建", len(self._pending_ops)
                )
                self._rebuild_indexes(agent_id)
                return
            try:
                self._apply_pending_ops()
            except Exception as e:  # noqa: BLE001
                logger.warning("知识库索引增量应用失败，退回全量重建: %s", e)
                self._rebuild_indexes(agent_id)

    # 兼容：旧方法名包装（分片架构下返回 public 分片）
    def _rebuild_vector_index_for_agent(self, agent_id: str, user: Optional[Dict] = None) -> None:
        self._rebuild_indexes(agent_id)

    def _ensure_index(self, agent_id: str) -> None:
        self._ensure_indexes(agent_id)

    def _load(self) -> None:
        if self._narratives is not None:
            self._items = self._itemsFromNarratives()
            # 装载即对齐：开闸后不必再手工跑回填，缺的治理行按同一口径补投
            # （admit 幂等，同内容即同一知识）。只报不修等于留一道人工断点。
            self._syncEntryGovernance()
            with self._entryLedger() as ledger:
                self._projectionDrift = ledger.verifyProjection(self._items)
            if self._projectionDrift:
                logger.error(
                    "条目与治理层仍分叉 %d 处（前 5 条：%s）——补投没能收敛，"
                    "先别把这份库当可信读数用", len(self._projectionDrift),
                    "; ".join(self._projectionDrift[:5]))
        elif self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self._items = {
                        agent_id: [self._migrate_entry(i) for i in items if isinstance(i, dict)]
                        for agent_id, items in data.items()
                        if isinstance(items, list)
                    }
            except Exception as e:  # noqa: BLE001
                # DATA-P1-2：解析失败必须把损坏文件隔离——留原路径的话，
                # 下一次 _save 会用内存空态覆盖真数据（整库丢失）
                from neurova.core.atomic_io import quarantine_corrupt_file

                quarantined = quarantine_corrupt_file(self._path)
                logger.error(
                    "知识库主文件损坏已隔离: %s → %s (%s)", self._path, quarantined, e
                )
        elif NarrativeStore.findArchivedJson(str(self._dir)):
            raise RuntimeError(
                "叙述层已搬进 %s（旧文件归档于 %s），此处回退成只读 JSON 会静默开一个空库。"
                "要保持新后端就别设 %s=off；要回退请把归档文件改回 knowledge.json "
                "并清空底座库里的 knowledge_narratives / knowledge_tombstones /"
                " knowledge_entry_conflicts 三张表。"
                % (self._narrative_db_path, NarrativeStore.findArchivedJson(str(self._dir))[0],
                   NARRATIVE_STORE_ENV)
            )
        if self._narratives is not None:
            if self._narratives.tombstoneCount() == 0 and self._tombstones_path.exists():
                report = self._narratives.importTombstonesFromJson(str(self._tombstones_path))
                archived = self._narratives.archiveSidecar(str(self._tombstones_path))
                logger.info("墓碑账本一次性搬入底座：导入 %s 条，旧文件归档为 %s",
                            report["imported"], archived)
            self._tombstones = self._narratives.loadTombstones()
        elif self._tombstones_path.exists():
            try:
                data = json.loads(self._tombstones_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self._tombstones = {
                        kid: rec for kid, rec in data.items() if isinstance(rec, dict)
                    }
            except Exception as e:  # noqa: BLE001
                logger.warning("Failed to load knowledge tombstones %s: %s", self._tombstones_path, e)
        if self._narratives is not None:
            if self._narratives.conflictCount() == 0 and self._conflicts_path.exists():
                report = self._narratives.importConflictsFromJson(str(self._conflicts_path))
                archived = self._narratives.archiveSidecar(str(self._conflicts_path))
                logger.info("冲突旁账一次性搬入底座：导入 %s 条，旧文件归档为 %s",
                            report["imported"], archived)
            self._conflicts = self._narratives.loadConflicts()
        elif self._conflicts_path.exists():
            try:
                data = json.loads(self._conflicts_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self._conflicts = {
                        cid: rec for cid, rec in data.items() if isinstance(rec, dict)
                    }
            except Exception as e:  # noqa: BLE001
                logger.warning("Failed to load knowledge conflicts %s: %s", self._conflicts_path, e)

    def _itemsFromNarratives(self) -> Dict[str, List[Dict[str, Any]]]:
        """闸内读条目：权威是底座库，但首次要把旧 JSON 搬进来再归档。

        搬家不写脚本而挂在读路径上，是因为闸一开就必须立即可用——缺这一步等于
        "开了开关却换到一本空库"。归档则保证它只发生一次：搬完旧文件不再被读到，
        删空后重启不会拿快照把已删条目复活。
        """
        if self._narratives.count() == 0 and self._path.exists():
            report = self._narratives.importFromJson(str(self._path))
            archived = self._narratives.archiveImportedJson(str(self._path))
            logger.info(
                "叙述层一次性搬入 %s：导入 %s 行，已把旧主文件归档为 %s",
                self._narrative_db_path, report["imported"], archived,
            )
        data = self._narratives.loadAll()
        return {
            agent_id: [self._migrate_entry(i) for i in items if isinstance(i, dict)]
            for agent_id, items in data.items()
            if isinstance(items, list)
        }

    def _save_tombstones(self) -> None:
        self._assertNotWritingProductionUnderPytest()
        if self._narratives is not None:
            # 与条目同理：吞掉写失败会让内存与库分叉，下一次成功写入抹平分叉期间的账
            self._narratives.replaceAllTombstones(self._tombstones)
            return
        try:
            self._tombstones_path.write_text(
                json.dumps(self._tombstones, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:  # noqa: BLE001
            logger.error("Failed to save knowledge tombstones %s: %s", self._tombstones_path, e)

    def _save_conflicts(self) -> None:
        self._assertNotWritingProductionUnderPytest()
        if self._narratives is not None:
            self._narratives.replaceAllConflicts(self._conflicts)
            return
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
        if not str(item.get("knowledge_id") or "").strip():
            # 缺 id 的旧条目永远进不了反馈/token/引用账：用内容指纹补一个
            # 稳定 id（不随机，重启后仍是同一条），后续 _save 自然固化。
            seed = "%s\n%s\n%s" % (
                item.get("title", ""), item.get("content", ""),
                item.get("created_at", ""),
            )
            item["knowledge_id"] = "legacy-" + hashlib.sha256(
                seed.encode("utf-8")
            ).hexdigest()[:32]
        if not isinstance(item.get("visibility"), str):
            item["visibility"] = VISIBILITY_PRIVATE
        if not isinstance(item.get("owner_user_id"), str):
            item["owner_user_id"] = "default"
        if not isinstance(item.get("shared_with"), list):
            item["shared_with"] = []
        if not isinstance(item.get("tenant_id"), str) or not item.get("tenant_id"):
            item["tenant_id"] = "default"
        if not isinstance(item.get("content_fingerprint"), str) or not item.get("content_fingerprint"):
            item["content_fingerprint"] = _contentFingerprint(
                item["tenant_id"], str(item.get("content") or "")
            )
        if not isinstance(item.get("sources"), list):
            evidence = _sourceEvidence(item)
            item["sources"] = [evidence] if evidence.get("source") else []
        if not isinstance(item.get("graph_node_ids"), list):
            item["graph_node_ids"] = []
        if not isinstance(item.get("valid_until"), str):
            item["valid_until"] = None
        if not isinstance(item.get("lifecycle_status"), str):
            item["lifecycle_status"] = ACTIVE
        if not isinstance(item.get("lifecycle_reason"), str):
            item["lifecycle_reason"] = ""
        if item.get("lifecycle_changed_at") is None:
            item["lifecycle_changed_at"] = None
        # 文档条目的采纳/注入回写（无 fact lineage 时的 entry 级反馈账）
        if item.get("adoption_outcome") not in ADOPTION_OUTCOMES:
            item["adoption_outcome"] = None
        if item.get("adoption_updated_at") is None:
            item["adoption_updated_at"] = None
        if not isinstance(item.get("injected_count"), int):
            item["injected_count"] = 0
        if item.get("last_injected_at") is None:
            item["last_injected_at"] = None
        # 文档标准化元数据（旧条目保持空值；不靠猜测补页码/OCR）
        for key in ("source_type", "source_path", "ingest_time", "author",
                    "ocr_engine", "document_id"):
            if not isinstance(item.get(key), str):
                item[key] = ""
        if item.get("page_count") is None:
            item["page_count"] = None
        if item.get("ocr_confidence_avg") is None:
            item["ocr_confidence_avg"] = None
        if not isinstance(item.get("ocr_used"), bool):
            item["ocr_used"] = False
        if not isinstance(item.get("geo"), dict) or _geoOf(item.get("geo")) is None:
            item["geo"] = None
        return item

    def _assertNotWritingProductionUnderPytest(self) -> None:
        """测试会话内禁止落盘到生产目录（判据与路径都在 `storage_fence`，此处只留调用位）。

        真实 knowledge.json 已证实被历史非隔离运行写入过（38 行纯冗余，见
        docs/specs/2026-09-20-knowledge-foundation-design.md §1.2）。围栏放在
        _save 的 try 之外——try 里 raise 会被下面的 except Exception 吞成一条日志。
        """
        assertNotUnderProductionStorage(self._dir, "条目仓库 %s" % self._path)

    def _save(self) -> None:
        self._assertNotWritingProductionUnderPytest()
        self._ftsDirty = True
        if self._narratives is not None:
            # 闸内不吞异常：写失败若只留一条日志，内存与库就分叉了，
            # 下一次成功写入会把分叉期间的编辑抹平。
            self._narratives.replaceAll(self._items)
            return
        try:
            from neurova.core.atomic_io import atomic_write_text

            atomic_write_text(
                self._path,
                json.dumps(self._items, ensure_ascii=False, indent=2),
            )
        except Exception as e:  # noqa: BLE001
            logger.error("Failed to save knowledge repo %s: %s", self._path, e)

    # ── 治理投影（工单 019b-2，闸内）───────────────────────────

    @contextlib.contextmanager
    def _entryLedger(self) -> Iterator[EntryLedger]:
        store = KnowledgeFactStore(self._narrative_db_path)
        try:
            yield EntryLedger(store)
        finally:
            store.close()

    def _syncEntryGovernance(self) -> None:
        """把当前 `_items` 投影到治理层，并把聚合出的置信度回写到条目上。

        闸外直接返回——旧行为一字不改。闸内**不捕异常**：投影失败却让条目写成功，
        就是"知识入库而无人知道它是谁说的"，正是这套底座要灭的病。

        只投影、不校验：校验在 `_load` 里做（见 `_projectionDrift`）。
        """
        if self._narratives is None:
            return
        with self._entryLedger() as ledger:
            report = ledger.syncFromEntries(self._items)
        confidences = report["confidences"]
        mediums = report.get("mediums", {})
        for items in self._items.values():
            for item in items:
                kid = str(item.get("knowledge_id", ""))
                derived = confidences.get(kid)
                if derived is not None:
                    # G11：条目上那个数从此是聚合出来的，不是调用方传进来的
                    item["confidence"] = derived
                medium = mediums.get(kid)
                if medium:
                    # G01：来源改成从断言 medium_ref 派生（审计读的是那张账，不是这个字段）
                    item["source"] = medium

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
        parents: Optional[List[Dict[str, Any]]] = None,
        detect_conflict: bool = True,
        valid_until: Optional[str] = None,
        lifecycle_status: str = ACTIVE,
        source_type: str = "",
        source_path: str = "",
        ingest_time: str = "",
        author: str = "",
        page_count: Optional[int] = None,
        ocr_used: bool = False,
        ocr_engine: str = "",
        ocr_confidence_avg: Optional[float] = None,
        document_id: str = "",
        tenant_id: str = "default",
        dedupe: bool = False,
        geo: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        status = normalizeLifecycleStatus(lifecycle_status)
        now = datetime.datetime.now(datetime.timezone.utc).timestamp()
        tenant = str(tenant_id or "default")
        fingerprint = _contentFingerprint(tenant, content)
        if dedupe:
            with self._lock:
                for existing in self._items.get(agent_id, []):
                    if (
                        str(existing.get("tenant_id") or "default") == tenant
                        and str(existing.get("content_fingerprint") or "") == fingerprint
                    ):
                        evidence = _sourceEvidence({
                            "source": source, "source_type": source_type,
                            "source_path": source_path, "ingest_time": ingest_time,
                        })
                        sources = existing.setdefault("sources", [])
                        if evidence.get("source") and evidence not in sources:
                            sources.append(evidence)
                            self._save()
                        duplicate = dict(existing)
                        duplicate["duplicate"] = True
                        return duplicate
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
            "tenant_id": tenant,
            "content_fingerprint": fingerprint,
            "sources": [_sourceEvidence({
                "source": source, "source_type": source_type,
                "source_path": source_path, "ingest_time": ingest_time,
            })] if source else [],
            "shared_with": [],
            "graph_node_ids": [],
            "submission": None,
            "valid_until": valid_until,
            "lifecycle_status": status,
            "lifecycle_reason": "",
            "lifecycle_changed_at": None,
            "adoption_outcome": None,
            "adoption_updated_at": None,
            "injected_count": 0,
            "last_injected_at": None,
            "source_type": source_type,
            "source_path": source_path,
            "ingest_time": ingest_time,
            "author": author,
            "page_count": page_count,
            "ocr_used": bool(ocr_used),
            "geo": _geoOf(geo),
            "ocr_engine": ocr_engine,
            "ocr_confidence_avg": ocr_confidence_avg,
            "document_id": document_id,
            # P0-2 分块（[{content, index, char_start, char_end}]）；None=整篇模式
            "chunks": chunks,
            # P1#6 父子分块：chunks 存子块（进索引），parents 存父块（LLM 上下文）；
            # None=扁平模式（存量条目与 create 默认，行为不变）
            "parents": parents if parents else None,
        }
        with self._lock:
            self._items.setdefault(agent_id, []).append(item)
            self._syncEntryGovernance()
            self._save()
            # P0#1：索引已建立时走分片级增量；dirty 时空操作（重建覆盖）
            self._record_index_op("reindex", item["knowledge_id"])
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
    def _tenant(user: Optional[Dict[str, Any]]) -> str:
        return str((user or {}).get("tenant_id") or "default")

    @staticmethod
    def _is_admin(user: Optional[Dict[str, Any]]) -> bool:
        return str((user or {}).get("role") or "") == "admin"

    def can_view(self, user: Optional[Dict[str, Any]], item: Dict[str, Any]) -> bool:
        # 租户先于角色：管理员只在自己租户内全可见，不是跨租户穿透。
        if str(item.get("tenant_id") or "default") != self._tenant(user):
            return False
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
        tags: Optional[List[str]] = None,
        source: Optional[str] = None,
        updated_after: Optional[float] = None,
        author: Optional[str] = None,
        source_type: Optional[str] = None,
        ocr_used: Optional[bool] = None,
        page_min: Optional[int] = None,
        geo_radius: Optional[Dict[str, Any]] = None,
        geo_bbox: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """按当前用户可见性返回条目视图（scope: all/public/private/shared）。

        tags 是 AND 口径：请求的每个标签都必须出现在条目的 tags 里。
        source/updated_after 同样是“先筛后检”的候选集约束——过滤必须发生在
        索引检索之前，否则候选集已经带着不该出现的条目，下游再截断就会把
        标签/来源/时间窗外的内容挤进 top-k。
        """
        uid = self._user_id(user)
        with self._lock:
            groups = self._items.items() if not agent_id else [(agent_id, self._items.get(agent_id, []))]
            snapshot = [(aid, [dict(i) for i in items]) for aid, items in groups]
        results: List[Dict[str, Any]] = []
        for aid, items in snapshot:
            for item in items:
                if agent_id and aid != agent_id:
                    continue
                if str(item.get("tenant_id") or "default") != self._tenant(user):
                    continue
                if not isRetrievable(item):
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
                if tags and not all(tag in (item.get("tags") or []) for tag in tags):
                    continue
                if source and str(item.get("source") or "") != str(source):
                    continue
                if author and str(item.get("author") or "") != str(author):
                    continue
                if source_type and str(item.get("source_type") or "") != str(source_type):
                    continue
                if ocr_used is not None and bool(item.get("ocr_used")) is not bool(ocr_used):
                    continue
                if page_min is not None and int(item.get("page_count") or 0) < int(page_min):
                    continue
                # GIS 过滤（A6）：无坐标条目在任何 geo 过滤下不参与；
                # 过滤被请求而参数残缺时按不匹配处理——空间过滤宁可漏给，不可误扩大结果集。
                geoPoint = item.get("geo") or {}
                if geo_radius is not None:
                    radiusKm = geo_radius.get("radius_km")
                    if (not geoPoint or radiusKm is None
                            or _haversineKm(
                                float(geo_radius["lat"]), float(geo_radius["lon"]),
                                float(geoPoint["lat"]), float(geoPoint["lon"])) > float(radiusKm)):
                        continue
                if geo_bbox is not None:
                    if not geoPoint:
                        continue
                    if not (float(geo_bbox["min_lat"]) <= float(geoPoint["lat"]) <= float(geo_bbox["max_lat"])
                            and float(geo_bbox["min_lon"]) <= float(geoPoint["lon"]) <= float(geo_bbox["max_lon"])):
                        continue
                if updated_after is not None:
                    try:
                        if float(item.get("updated_at") or 0) < float(updated_after):
                            continue
                    except (TypeError, ValueError):
                        # 时间戳坏了不隐藏条目：错误方向是“多检一条”，不是“知识消失”
                        pass
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
                    # 仅分片归属变化才需要重索引（visibility/shared_with 影响分片；
                    # submission 等簿记字段不进索引文本）
                    moved = self._get_shard_scope(stored) != self._get_shard_scope(item)
                    item["updated_at"] = datetime.datetime.now(datetime.timezone.utc).timestamp()
                    items[idx] = item
                    self._save()
                    if moved:
                        self._record_index_op("reindex", str(item["knowledge_id"]))
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

    def pending_submissions(self, tenantId: Optional[str] = None) -> List[Dict[str, Any]]:
        """待审批提交清单（仅 admin 消费，API 层把关）；可按租户过滤。"""
        with self._lock:
            snapshot = [dict(i) for items in self._items.values() for i in items]
        tenant = None if tenantId is None else str(tenantId or "default")
        return [
            i for i in snapshot
            if (i.get("submission") or {}).get("status") == _SUBMISSION_PENDING
            and (tenant is None or str(i.get("tenant_id") or "default") == tenant)
        ]

    def listAgents(self) -> List[str]:
        with self._lock:
            return sorted(self._items)

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
            if not isRetrievable(item):
                continue
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
        tags: Optional[List[str]] = None,
        source: Optional[str] = None,
        updated_after: Optional[float] = None,
        author: Optional[str] = None,
        source_type: Optional[str] = None,
        ocr_used: Optional[bool] = None,
        page_min: Optional[int] = None,
        geo_radius: Optional[Dict[str, Any]] = None,
        geo_bbox: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """在当前用户可见视图内检索知识。

        优先走 TF-IDF 索引（按相关性 score 降序 top-k）；索引不可用/覆盖不足时
        回退标题+内容包含匹配（不区分大小写）。可见性过滤先于索引检索（隔离优先）。
        """
        q = (query or "").lower()

        # 可见性过滤（隔离优先，索引只做相似度排序）；元数据同一时点过滤
        visible = self.visible_items(
            user, scope=scope, category=category, agent_id=agent_id, tags=tags,
            source=source, updated_after=updated_after,
            author=author, source_type=source_type, ocr_used=ocr_used,
            page_min=page_min, geo_radius=geo_radius, geo_bbox=geo_bbox,
        )
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
            self._ensure_indexes(agent_id or "default")
        except Exception as e:
            logger.warning("知识库索引维护失败（回退 substring）: %s", e)
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
                if score <= 0.0:
                    # 零词面重叠=不相关，不进结果（与 substring 路径"须命中"语义对齐；
                    # 否则 TF-IDF 路把全部可见条目以 score=0 灌进检索链）
                    continue
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
            # P1#6：命中子块 → 回传父块上下文（LLM 消费父非子），
            # 按命中分数序去重、封顶 3 个父块（防超长文档灌爆窗口）
            if r.get("parents"):
                passages: List[str] = []
                seen_parents: set = set()
                for h in hits:
                    pi = h.get("parent_index")
                    if pi is None or pi in seen_parents:
                        continue
                    text = parent_context_text(r, pi)
                    if text:
                        passages.append(text)
                        seen_parents.add(pi)
                    if len(passages) >= 3:
                        break
                if passages:
                    r["context_passages"] = passages
        if not results:
            # 索引零命中交回 substring 兜底：TF-IDF 分词对字母数字混合词
            # （"BatchTerm2"）与纯数字（"2024"）失明（\b[a-zA-Z]+\b 不匹配），
            # 包含匹配仍可命中——避免 score floor 把这类查询整体打死
            return None
        return results[:limit]

    def update_knowledge(self, agent_id: str, knowledge_id: str, fields: Dict[str, Any]) -> bool:
        lifecycle_change = "lifecycle_status" in fields
        if lifecycle_change:
            fields = dict(fields)
            fields["lifecycle_status"] = normalizeLifecycleStatus(fields["lifecycle_status"])
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
                        if k in (
                            "title", "content", "category", "tags", "confidence",
                            "source", "graph_node_ids", "valid_until", "lifecycle_status",
                        ):
                            item[k] = v
                    # P0#1：content 变更时同步重切 chunks——旧块正文/偏移会同时
                    # 污染索引与 chunk_hits（读到已删除的旧文本）
                    if "content" in fields and item.get("chunks") is not None:
                        try:
                            new_content = str(fields.get("content", ""))
                            if item.get("parents") is not None:
                                # P1#6：父子模式条目重切走同一构造，parents 同步更新
                                from neurova.knowledge.splitter import build_entry_chunks

                                item["chunks"], item["parents"] = build_entry_chunks(new_content)
                            else:
                                from neurova.knowledge.splitter import split_with_meta

                                item["chunks"] = split_with_meta(new_content)
                        except Exception as e:  # noqa: BLE001
                            logger.warning("知识条目内容更新重切分块失败（保留旧块）: %s", e)
                    if lifecycle_change:
                        item["lifecycle_reason"] = (
                            "" if fields["lifecycle_status"] == ACTIVE else "manual"
                        )
                        item["lifecycle_changed_at"] = (
                            datetime.datetime.now(datetime.timezone.utc).isoformat()
                        )
                    item["updated_at"] = datetime.datetime.now(datetime.timezone.utc).timestamp()
                    self._syncEntryGovernance()
                    self._save()
                    # 索引文本只含 title+chunks(+header)：graph_node_ids 等回写
                    # （graph_bridge）不再触发任何索引操作
                    if "title" in fields or "content" in fields:
                        self._record_index_op("reindex", knowledge_id)
                    return True
        return False

    def replaceDocumentParsing(
        self, agent_id: str, knowledge_id: str, parsed: Any, *,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """用新解析结果替换文档条目正文/块/文档元数据；旧值进 revision 账。

        只做"文档再解析"这一种受控写：不改 title/visibility/owner/tenant，
        也不做正文重切（新块必须保留页码/标题映射，重切会丢）。
        """
        with self._lock:
            for item in self._items.get(agent_id, []):
                if item.get("knowledge_id") != knowledge_id:
                    continue
                old = {
                    key: item.get(key)
                    for key in ("content", "chunks", "parents", "source_type",
                                "source_path", "ingest_time", "author",
                                "page_count", "ocr_used", "ocr_engine",
                                "ocr_confidence_avg", "document_id")
                }
                changed = [key for key in old if old[key] != item.get(key)]
                item.setdefault("revisions", []).append({
                    "old": old,
                    "changed_fields": changed,
                    "updated_at": datetime.datetime.now(
                        datetime.timezone.utc
                    ).isoformat(),
                    "reason": "document_reparse",
                })
                item["content"] = str(parsed.content)
                item["chunks"] = list(parsed.chunks)
                item["parents"] = list(parsed.parents)
                meta = metadata if metadata is not None else parsed.metadata
                item["source_type"] = str(meta.get("source_type") or item.get("source_type") or "")
                item["source_path"] = str(item.get("source_path") or parsed.source_path or "")
                item["ingest_time"] = str(parsed.ingest_time or item.get("ingest_time") or "")
                item["author"] = str(meta.get("author") or "")
                item["page_count"] = meta.get("page_count")
                item["ocr_used"] = bool(meta.get("ocr_used"))
                item["ocr_engine"] = str(meta.get("ocr_engine") or "")
                item["ocr_confidence_avg"] = meta.get("ocr_confidence_avg")
                item["document_id"] = str(item.get("document_id") or parsed.doc_id or "")
                item["updated_at"] = datetime.datetime.now(
                    datetime.timezone.utc
                ).timestamp()
                self._syncEntryGovernance()
                self._save()
                self._record_index_op("reindex", knowledge_id)
                return True
        return False

    # ── entry 级反馈（文档条目无 fact lineage 时的采纳/注入账）──────

    def findBySource(
        self, agent_id: str, source: str, tenant_id: str = "default"
    ) -> Optional[Dict[str, Any]]:
        """按 source 找条目（入站幂等：同一消息不重复建知识；租户内幂等）。"""
        with self._lock:
            for item in self._items.get(agent_id, []):
                if str(item.get("tenant_id") or "default") != str(tenant_id or "default"):
                    continue
                if str(item.get("source") or "") == str(source or ""):
                    return dict(item)
        return None

    def recordEntryAdoption(
        self, agent_id: str, knowledge_id: str, outcome: str
    ) -> bool:
        """写文档条目的采纳三态；只改反馈字段，不碰 updated_at/正文。"""
        if outcome not in ADOPTION_OUTCOMES:
            raise ValueError("未知 adoption_outcome: %r" % (outcome,))
        stamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with self._lock:
            for item in self._items.get(agent_id, []):
                if item.get("knowledge_id") == knowledge_id:
                    item["adoption_outcome"] = outcome
                    item["adoption_updated_at"] = stamp
                    self._save()
                    return True
        return False

    def recordEntryInjections(
        self, agent_id: str, knowledge_ids: List[str]
    ) -> int:
        """对最终注入的文档条目累计 injected_count；不改 updated_at。"""
        wanted = {str(kid) for kid in (knowledge_ids or []) if kid}
        if not wanted:
            return 0
        stamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
        written = 0
        with self._lock:
            for item in self._items.get(agent_id, []):
                if item.get("knowledge_id") in wanted:
                    item["injected_count"] = int(item.get("injected_count") or 0) + 1
                    item["last_injected_at"] = stamp
                    written += 1
            if written:
                self._save()
        return written

    def entryFeedbackMap(self, knowledge_ids: List[str]) -> Dict[str, Dict[str, Any]]:
        """按 id 取条目反馈；跨 agent 查找（knowledge_id 全局唯一）。"""
        wanted = {str(kid) for kid in (knowledge_ids or []) if kid}
        if not wanted:
            return {}
        result: Dict[str, Dict[str, Any]] = {}
        with self._lock:
            for items in self._items.values():
                for item in items:
                    kid = str(item.get("knowledge_id") or "")
                    if kid in wanted:
                        result[kid] = {
                            "adoption_outcome": item.get("adoption_outcome"),
                            "adoption_updated_at": item.get("adoption_updated_at"),
                            "injected_count": int(item.get("injected_count") or 0),
                            "last_injected_at": item.get("last_injected_at"),
                        }
        return result

    def entryFeedbackMetrics(self) -> Dict[str, Any]:
        """条目反馈读数：三态分布 + 注入覆盖率；静默缺失按未回写计。"""
        with self._lock:
            items = [item for group in self._items.values() for item in group]
        counts = {"success": 0, "failure": 0, "unevidenced": 0, "never_written": 0}
        injected = 0
        for item in items:
            outcome = item.get("adoption_outcome")
            if outcome in counts:
                counts[outcome] += 1
            else:
                counts["never_written"] += 1
            if int(item.get("injected_count") or 0) > 0:
                injected += 1
        total = len(items)
        return {
            "total": total,
            "outcomes": counts,
            "injected_entries": injected,
            "injection_coverage": round(injected / total, 6) if total else None,
        }

    def delete_knowledge(
        self, agent_id: str, knowledge_id: str, deleted_by: str = ""
    ) -> bool:
        """tombstone 软删：条目移入墓碑账本（所有读路径不可见），数据保留可恢复。

物理清除走 purge_knowledge 显式通道
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
                    self._syncEntryGovernance()
                    self._save()
                    self._save_tombstones()
                    self._record_index_op("remove", knowledge_id)
                    return True
        return False

    def purge_knowledge(self, agent_id: str, knowledge_id: str,
                        reason: str = "") -> Dict[str, Any]:
        """条目擦除喉：让一个条目在所有存储面留下的正文都取不回来（批次 K2 / 断点 N2）。

        原先这里只清条目行与墓碑再回一个 bool，而 `?purge=true` 对外承诺的是
        "物理删除整条（清除违规内容的显式通道）"（`knowledge_core.py:418`）。同一条
        内容的正文其实还留在五处：权威事实行的 `content`/`object_term`、断言的
        `statement_text`、活动信封的 `inputs_json`、向量分片里的 `content[:2000]`、
        投影节点的 `description`。端点又不读那个 bool，于是"只删了一处"被报成
        "已删除"。现在逐面动作、逐面回执，回执五态见 `foundation/erasure.py`。

        次序是**副本先清、条目行后删**：条目行是唯一还能把这件事重试一遍的入口
        （`find_item` 查得到才谈得上再擦一次），先删条目再删副本，中途失败就只剩下
        一个无人认领也无人能再认领的残局。

        软删不走这里——`delete_knowledge` 的语义是"下架但保住属主数据"，
        正文留在账上是**有意**的，别拿擦除冒充它。
        """
        faces: Dict[str, Any] = dict(self._eraseAuthorityCopies(knowledge_id, reason))

        def _blocked() -> bool:
            return any(str(f.get("state")) == "failed" for f in faces.values())

        for face, action in (("vectors", lambda: self._eraseVectorCopy(knowledge_id)),
                             ("projection", lambda: self._eraseProjectionCopy(knowledge_id)),
                             ("entry", lambda: self._eraseEntryRow(agent_id, knowledge_id,
                                                                    reason))):
            faces[face] = ({"state": "not_attempted", "count": 0,
                            "detail": "前面有面失败，本轮不推进"}
                           if _blocked() else action())
        complete = not _blocked()
        if not complete:
            logger.error("条目擦除未完成 %s：%s", knowledge_id,
                         {k: v.get("state") for k, v in faces.items()
                          if v.get("state") in ("failed", "not_attempted")})
        return {"knowledge_id": knowledge_id, "faces": faces,
                "complete": complete, "reason": reason}

    def _eraseAuthorityCopies(self, knowledgeId: str, reason: str) -> Dict[str, Any]:
        """权威库那一侧交棒给擦除喉——DELETE 只许有那一份实现。"""
        from neurova.knowledge.foundation.erasure import EntryErasure

        names = ("facts", "assertions", "derivations", "conflicts", "subjects", "activities")
        store = KnowledgeFactStore(self._narrative_db_path)
        try:
            return EntryErasure(store).eraseEntry(knowledgeId, reason=reason)
        except Exception as e:  # noqa: BLE001 - 擦除失败必须点名，不能折成"删好了"
            logger.error("权威库条目擦除失败 %s: %s", knowledgeId, e)
            return {n: {"state": "failed", "count": 0, "detail": str(e)} for n in names}
        finally:
            store.close()

    def _eraseVectorCopy(self, knowledgeId: str) -> Dict[str, Any]:
        try:
            from neurova.knowledge.vector_index import get_knowledge_vector_index

            index = get_knowledge_vector_index()
        except Exception as e:  # noqa: BLE001 - 引擎没配起来是"这一面无副本可删"，不是失败
            return {"state": "unavailable", "count": 0, "detail": str(e)}
        try:
            dropped = index.dropEntry(knowledgeId)
        except Exception as e:  # noqa: BLE001
            return {"state": "failed", "count": 0, "detail": str(e)}
        if not dropped.get("records"):
            return {"state": "absent", "count": 0, "files": dropped.get("files", 0)}
        return {"state": "erased", "count": dropped["records"],
                "files": dropped.get("files", 0)}

    def _eraseProjectionCopy(self, knowledgeId: str) -> Dict[str, Any]:
        """投影节点的正文副本：独认领的连节点带边删掉，被别人也在用的只摘 description。

        只摘不删是因为 `label` 是身份消解后共享的实体名——另一个条目还在用它，
        删节点会把别人的图画出一个洞。共享节点留下的 `label` 要在回执里说清（
        `shared_kept`），别让"投影已擦"被读成"投影里一个字都不剩"。
        """
        try:
            from neurova.cognitive_layers.knowledge_graph.manager import (
                get_knowledge_graph_manager,
            )

            manager = get_knowledge_graph_manager()
        except Exception as e:  # noqa: BLE001
            return {"state": "unavailable", "count": 0, "detail": str(e)}
        with self._lock:
            claimedByOthers = self._nodeIdsClaimedByOthers(knowledgeId)
            # `find_item` 回的是 (agent_id, item) 两元组——当 dict 用会一路 AttributeError
            found = self.find_item(knowledgeId)
            claimed = set(str(n) for n in ((found[1].get("graph_node_ids") or [])
                                           if found else []))
        candidates = set(manager.nodesForSourceKnowledge(knowledgeId)) | claimed
        deleted = scrubbed = 0
        for nodeId in candidates:
            node = manager.get_node(nodeId)
            if node is None:
                continue
            if nodeId in claimedByOthers:
                props = dict(node.properties or {})
                if "description" not in props:
                    continue
                props.pop("description")
                manager.update_node(nodeId, properties=props)
                scrubbed += 1
                continue
            if manager.delete_node(nodeId):
                deleted += 1
        if not (deleted or scrubbed):
            return {"state": "absent", "count": 0}
        state = "erased" if deleted else "redacted"
        return {"state": state, "count": deleted + scrubbed,
                "nodes_deleted": deleted, "shared_kept": scrubbed}

    def _nodeIdsClaimedByOthers(self, knowledgeId: str) -> set:
        """除本条目外，仍在被其它条目认领的投影节点 id。调用方须持 `self._lock`。"""
        claimed: set = set()
        for items in self._items.values():
            for it in items:
                if str(it.get("knowledge_id", "")) == knowledgeId:
                    continue
                claimed |= {str(n) for n in (it.get("graph_node_ids") or [])}
        return claimed

    def _pruneEntryConflicts(self, knowledgeId: str) -> int:
        """同值冲突账本里不许挂着已擦除条目的 id——挂着就是"待审项指向空气"。"""
        dropped = 0
        for conflict_id in [cid for cid, rec in self._conflicts.items()
                            if knowledgeId in (str(rec.get("old_id", "")),
                                               str(rec.get("new_id", "")))]:
            del self._conflicts[conflict_id]
            dropped += 1
        if dropped:
            self._save_conflicts()
        return dropped

    def _eraseEntryRow(self, agent_id: str, knowledge_id: str,
                       reason: str) -> Dict[str, Any]:
        """条目层与墓碑：叙述行经 `_save()` 落到 `knowledge_narratives`，正文唯一副本在此。"""
        with self._lock:
            items = self._items.get(agent_id, [])
            for idx, item in enumerate(items):
                if item.get("knowledge_id") == knowledge_id:
                    del items[idx]
                    self._tombstones.pop(knowledge_id, None)
                    pruned = self._pruneEntryConflicts(knowledge_id)
                    # 条目与墓碑都没了，治理行必须跟着退场——否则它成为"活着却无人认领"
                    self._syncEntryGovernance()
                    self._save()
                    self._save_tombstones()
                    self._record_index_op("remove", knowledge_id)
                    return {"state": "erased", "count": 1, "conflicts_pruned": pruned}
            if knowledge_id in self._tombstones:
                del self._tombstones[knowledge_id]
                pruned = self._pruneEntryConflicts(knowledge_id)
                self._save_tombstones()
                return {"state": "erased", "count": 1, "from": "tombstone",
                        "conflicts_pruned": pruned}
            return {"state": "absent", "count": 0,
                    "conflicts_pruned": self._pruneEntryConflicts(knowledge_id)}

    def restore_knowledge(self, knowledge_id: str, tenantId: Optional[str] = None) -> bool:
        """从墓碑复活条目（普通复活不带 supersede 链）。活着/不存在/跨租户返回 False。"""
        with self._lock:
            rec = self._tombstones.get(knowledge_id)
            if rec is None:
                return False
            if tenantId is not None and str(
                (rec.get("item") or {}).get("tenant_id") or "default"
            ) != str(tenantId or "default"):
                return False
            agent_id = rec.get("agent_id") or "default"
            self._items.setdefault(agent_id, []).append(rec["item"])
            del self._tombstones[knowledge_id]
            # 恢复 = 这条说法又有人认领了，治理行必须同步回到 active（闸内）
            self._syncEntryGovernance()
            self._save()
            self._save_tombstones()
            self._record_index_op("reindex", knowledge_id)
            return True

    def list_deleted(self, tenantId: Optional[str] = None) -> List[Dict[str, Any]]:
        """墓碑清单（admin 审计消费）。记录含 item 快照 + 删除元数据；可按租户过滤。"""
        with self._lock:
            recs = [dict(rec, knowledge_id=kid) for kid, rec in self._tombstones.items()]
        if tenantId is None:
            return recs
        tenant = str(tenantId or "default")
        return [
            rec for rec in recs
            if str((rec.get("item") or {}).get("tenant_id") or "default") == tenant
        ]

    def expireDueEntries(self, now: Optional[datetime.datetime] = None,
                         apply: bool = False,
                         tenantId: Optional[str] = None) -> Dict[str, Any]:
        """到期条目自动归档：dry-run 只报数；apply 把 active→archived。

        不删除、不改正文；归档后仍可 PUT 回 active（保留 valid_until）。
        启动路径与管理员端点共用本方法，不另写第二份判定。
        """
        due: List[tuple] = []
        with self._lock:
            for agent_id, items in self._items.items():
                for item in items:
                    if tenantId is not None and str(
                        item.get("tenant_id") or "default"
                    ) != str(tenantId or "default"):
                        continue
                    try:
                        status = normalizeLifecycleStatus(item.get("lifecycle_status"))
                    except ValueError:
                        status = ARCHIVED
                    if status == ACTIVE and isExpired(item, now):
                        due.append((agent_id, item))
            if apply and due:
                stamp = datetime.datetime.now(datetime.timezone.utc)
                for _agent_id, item in due:
                    item["lifecycle_status"] = ARCHIVED
                    item["lifecycle_reason"] = "expired"
                    item["lifecycle_changed_at"] = stamp.isoformat()
                    item["updated_at"] = stamp.timestamp()
                    self._record_index_op("remove", item["knowledge_id"])
                self._syncEntryGovernance()
                self._save()
        return {"due": len(due), "archived": len(due) if apply else 0, "applied": bool(apply)}

    def lifecycleReport(
        self, now: Optional[datetime.datetime] = None,
        tenantId: Optional[str] = None,
    ) -> Dict[str, Any]:
        """生命周期只读报告：active/archived/expired 计数 + 不可检索条目清单。"""
        counts = {ACTIVE: 0, ARCHIVED: 0, "expired": 0}
        rows: List[Dict[str, Any]] = []
        with self._lock:
            snapshot = [
                (aid, [dict(item) for item in items])
                for aid, items in self._items.items()
            ]
        for agent_id, items in snapshot:
            for item in items:
                if tenantId is not None and str(
                    item.get("tenant_id") or "default"
                ) != str(tenantId or "default"):
                    continue
                try:
                    status = normalizeLifecycleStatus(item.get("lifecycle_status"))
                except ValueError:
                    status = ARCHIVED
                if status == ARCHIVED:
                    state = ARCHIVED
                elif isExpired(item, now):
                    state = "expired"
                else:
                    state = ACTIVE
                counts[state] += 1
                if state != ACTIVE:
                    rows.append({
                        "agent_id": agent_id,
                        "knowledge_id": item.get("knowledge_id"),
                        "title": item.get("title", ""),
                        "lifecycle_status": status,
                        "lifecycle_reason": item.get("lifecycle_reason", ""),
                        "lifecycle_changed_at": item.get("lifecycle_changed_at"),
                        "valid_until": item.get("valid_until"),
                        "state": state,
                    })
        return {
            "total": sum(counts.values()),
            "counts": counts,
            "non_retrievable": rows,
        }

    def list_revisions(self, knowledge_id: str) -> List[Dict[str, Any]]:
        """条目 revision 账本（最新在前）。条目不存在返回 []。"""
        with self._lock:
            found = self.find_item(knowledge_id)
            if found is None:
                return []
            return list(reversed((found[1].get("revisions") or [])))

    # ── P1#8 块级编辑──

    def list_chunks(self, knowledge_id: str) -> List[Dict[str, Any]]:
        """块清单（含 revision/index_status 视图）。条目不存在返回 None。"""
        with self._lock:
            found = self.find_item(knowledge_id)
            if found is None:
                return None
            return [dict(ch) for ch in (found[1].get("chunks") or [])]

    def chunk_revisions(self, knowledge_id: str, index: int) -> Optional[List[Dict[str, Any]]]:
        """单块追加式修订账本（最新在前）。条目不存在 None。"""
        with self._lock:
            found = self.find_item(knowledge_id)
            if found is None:
                return None
            chunks = found[1].get("chunks") or []
            if not (0 <= index < len(chunks)):
                return []
            return list(reversed(chunks[index].get("revisions") or []))

    def update_chunk(
        self,
        knowledge_id: str,
        index: int,
        content: str,
        user: Optional[Dict[str, Any]] = None,
        expected_revision: Optional[int] = None,
    ) -> int:
        """编辑单个块，返回新 revision。

        - 块是其文本的权威副本：_chunk_hit/_item_index_docs 优先读块 content，
          整篇 content 保持原文不联动重写（导出/参照语义）；
        - expected_revision 乐观锁（None = 不校验，属主自担）；
        - 旧值先进块 revisions 账本再覆盖（append-only，对齐条目级 P0-2 账本）；
        - 写完记录 reindex 增量操作——下一次检索即带新文本（P0#1 通道）。
        """
        text = str(content or "").strip()
        if not text:
            raise ValueError("块内容不得为空")
        with self._lock:
            found = self.find_item(knowledge_id)
            if found is None:
                raise LookupError("知识条目不存在: %s" % knowledge_id)
            agent_id = found[0]
            stored = None
            for item in self._items.get(agent_id, []):
                if item.get("knowledge_id") == knowledge_id:
                    stored = item
                    break
            if stored is None:
                raise LookupError("知识条目不存在: %s" % knowledge_id)
            if not self.can_modify(user, stored):
                raise PermissionError("仅条目属主或管理员可编辑块")
            chunks = stored.get("chunks")
            if not chunks:
                raise ValueError("条目未分块（整篇模式），请走条目更新")
            if not (0 <= index < len(chunks)):
                raise LookupError("块序号越界: %s" % index)
            ch = chunks[index]
            cur_rev = int(ch.get("revision", 0) or 0)
            if expected_revision is not None and int(expected_revision) != cur_rev:
                raise ChunkRevisionConflict(
                    "块 %d 修订冲突：期望 %s，当前 %s" % (index, expected_revision, cur_rev)
                )
            ch.setdefault("revisions", []).append(
                {
                    "content": ch.get("content", ""),
                    "at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    "by": self._user_id(user),
                }
            )
            ch["content"] = text
            ch["revision"] = cur_rev + 1
            ch["updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            # 索引器可用 → 编辑将被增量应用；不可用（store=None）如实标 pending
            ch["index_status"] = "pending" if self._index_dirty else "ready"
            item_meta = stored
            item_meta["updated_at"] = datetime.datetime.now(datetime.timezone.utc).timestamp()
            self._save()
            self._record_index_op("reindex", knowledge_id)
            return ch["revision"]

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
            if str(old.get("tenant_id") or "default") != str(
                new_item.get("tenant_id") or "default"
            ):
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
        from neurova.knowledge.conflict_features import (
            buildConflictFeatures,
            classifyConflict,
        )

        features = buildConflictFeatures(
            str(old_item.get("content", "")), str(new_item.get("content", "")),
            subjectSimilarity=title_sim,
        )
        decision, featureReason = classifyConflict(features)
        self._conflicts[str(uuid.uuid4())] = {
            "features": features,
            "decision": decision,
            "feature_reason": featureReason,
            "old_id": old_item.get("knowledge_id"),
            "new_id": new_id,
            "knowledge_id": old_item.get("knowledge_id"),
            "title": new_item.get("title", ""),
            "similarity": round(title_sim, 4),
            "reason": "same_title: 新条目与旧条目标题一致，疑似同一事实的新说法",
            "detected_at": datetime.datetime.now(datetime.timezone.utc).timestamp(),
            "status": "pending",
            "tenant_id": str(new_item.get("tenant_id") or "default"),
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
        # 冲突通知走声明过的主题；订阅者可接 Supervisor/控制台。
        # 通知失败只降级观测，不回滚已成立的冲突账。
        try:
            from neurova.knowledge.ingest_bus import (
                KB_CONFLICT_NOTIFY_TOPIC,
                get_ingest_bus,
            )

            get_ingest_bus().publish(KB_CONFLICT_NOTIFY_TOPIC, {
                "agent_id": agent_id,
                "tenant_id": str(new_item.get("tenant_id") or "default"),
                "old_id": old_item.get("knowledge_id"),
                "new_id": new_id,
                "decision": decision,
                "feature_reason": featureReason,
            })
        except Exception as exc:  # noqa: BLE001 - 通知失败不影响冲突账
            logger.debug("冲突通知发布失败: %s", exc)

    def list_conflicts(
        self, status: str = "pending", tenantId: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """冲突清单（默认待审 pending；status='resolved' 查裁决历史）；可按租户过滤。"""
        with self._lock:
            recs = [
                dict(rec, conflict_id=cid)
                for cid, rec in self._conflicts.items()
                if rec.get("status") == status
                and (
                    tenantId is None
                    or str(rec.get("tenant_id") or "default") == str(tenantId or "default")
                )
            ]
        recs.sort(key=lambda r: r.get("detected_at", 0), reverse=True)
        return recs

    def findByDocumentId(
        self, user: Optional[Dict[str, Any]], documentId: str
    ) -> Optional[Dict[str, Any]]:
        """按 document_id（或 knowledge_id）在可见集内找文档条目。"""
        wanted = str(documentId or "").strip()
        if not wanted:
            return None
        for item in self.visible_items(user):
            if wanted in (
                str(item.get("document_id") or ""),
                str(item.get("knowledge_id") or ""),
            ):
                return dict(item)
        return None

    def documentStats(self, tenantId: str = "default") -> Dict[str, Any]:
        """文档级观测：条目数、OCR 覆盖率、页数/块数与置信度均值。"""
        tenant = str(tenantId or "default")
        with self._lock:
            snapshot = [
                dict(item)
                for items in self._items.values() for item in items
                if str(item.get("tenant_id") or "default") == tenant
            ]
        documents = [item for item in snapshot if item.get("document_id")]
        ocr = [item for item in documents if item.get("ocr_used")]
        pages = sum(int(item.get("page_count") or 0) for item in documents)
        chunks = sum(len(item.get("chunks") or []) for item in documents)
        scores = [
            float(item.get("ocr_confidence_avg"))
            for item in ocr
            if item.get("ocr_confidence_avg") is not None
        ]
        total = len(documents)
        return {
            "document_count": total,
            "ocr_document_count": len(ocr),
            "ocr_coverage": round(len(ocr) / total, 4) if total else None,
            "page_count": pages,
            "chunk_count": chunks,
            "ocr_confidence_avg": round(sum(scores) / len(scores), 4) if scores else None,
            "missing_reason": (
                "" if total else "当前租户还没有带 document_id 的文档条目，覆盖率无分母"
            ),
        }

    def getConflict(
        self, conflictId: str, tenantId: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        with self._lock:
            rec = self._conflicts.get(str(conflictId or ""))
            if rec is None:
                return None
            if tenantId is not None and str(
                rec.get("tenant_id") or "default"
            ) != str(tenantId or "default"):
                return None
            return dict(rec, conflict_id=conflictId)

    def conflictRecords(self, tenantId: Optional[str] = None) -> List[Dict[str, Any]]:
        """全部冲突账（含已裁决），供度量按 decision/状态统计；可按租户过滤。"""
        with self._lock:
            return [
                dict(rec, conflict_id=cid)
                for cid, rec in self._conflicts.items()
                if tenantId is None
                or str(rec.get("tenant_id") or "default") == str(tenantId or "default")
            ]

    def has_conflict(self, conflict_id: str) -> bool:
        """这条 id 是不是条目侧账本的——队列端点要靠它分派，不能猜 id 长相。

        只判存在、不判租户：分派是"这个 id 归哪条轴"，租户校验在变更点
        （`resolve_conflict(tenantId=...)`）——否则跨租户 id 会被分派到事实轴，
        去另一个库里找一条根本不存在于本租户的记录。
        """
        with self._lock:
            return conflict_id in self._conflicts

    def resolve_conflict(
        self, conflict_id: str, resolution: str, resolved_by: str = "",
        tenantId: Optional[str] = None,
    ) -> bool:
        """人工裁决冲突：keep_both 保留双条目关闭记录；supersede_old 旧条目
 打 superseded_by 链并 tombstone（新说法接管
        入墓碑可复活）。非法裁决值抛 ValueError。"""
        if resolution not in ("keep_both", "supersede_old"):
            raise ValueError("未知裁决: %r（有效值: keep_both / supersede_old）" % resolution)
        with self._lock:
            rec = self._conflicts.get(conflict_id)
            if rec is None or rec.get("status") != "pending":
                return False
            if tenantId is not None and str(
                rec.get("tenant_id") or "default"
            ) != str(tenantId or "default"):
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
            # keep_both 不改条目文本（conflict 簿记字段不进索引）；仅
            # supersede_old 使旧条目墓碑化 → 增量剥离
            if resolution == "supersede_old":
                # 批 D1：pop 只动了内存——漏 _save 会重启反转裁决（水合把
                # 旧条目装回来）。与 delete_knowledge/restore 同序收尾。
                self._syncEntryGovernance()
                self._save()
                self._record_index_op("remove", rec["old_id"])
            return True


_singleton: Optional[KnowledgeRepository] = None
_singleton_lock = threading.Lock()


def get_knowledge_repository() -> KnowledgeRepository:
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            _singleton = KnowledgeRepository(DEFAULT_STORAGE_DIR)
    return _singleton
