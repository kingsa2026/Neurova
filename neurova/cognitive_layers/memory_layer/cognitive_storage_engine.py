"""认知记忆的 L0 缓冲与检索编排层——**正文只有一个库**：`MemoryManager` 的配对持久库。

本模块此前自己建第二张 `memories` 表（落 `data/<agent>/memory.db`），并自带 FTS5、
向量列与 LSM 分层。实测那张表 0 行、连崩溃恢复文件都从未被创建（档案
`audit-reports/memory-dual-root-comparison-2026-10-14.md`）——正文的写入与召回
一直由 `MemoryManager` 那份承担，这边只是一套没人喂数据的平行 schema。

按裁定（三层能力保）的处置是**取长补短后收口**，不是退役能力：

- FTS5 全文：并到正文库上（`manager.py` 的 memory 域迁移 v3，分词器 `trigram`）；
  检索查询也归 `MemoryManager`——作用域三元组只有它那一处出处。
- 向量：`embedding` 随正文一起落库（v2 加列），由既有装载路径与向量面消费；
  本模块那份只写不读的进程内向量索引退役。
- LSM：L0 缓冲 + 崩溃恢复文件保留，落点改到正文库同目录；温度/`access_count`
  分层记账保留。

写侧一律经 `MemoryManager` 的唯一写入口（`persist_memory_batch`），本模块不再出现
任何 `INSERT`/`CREATE TABLE`——两处 schema、两套写语义就是本轮要灭的病根。

层级:
  L0 Buffer  — 内存缓冲 + 崩溃恢复文件（秒级）
  L1 Hot     — 正文库（`MemoryManager` 的配对持久库，分钟级）
  L2 Warm    — JSON 温存储（NeurovaHebb 专用，小时级）
  L3 Cold    — 压缩冷存储（天级）
  L4 Crystal — 结晶经验（永久）
"""

from __future__ import annotations

import json
from neurova.core.logger import get_logger
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = get_logger(__name__)


# ── 数据模型 ──────────────────────────────────────────────────────────────────


class MemoryType(Enum):
    """记忆类型"""

    EPISODIC = "episodic"  # 事件记忆
    SEMANTIC = "semantic"  # 语义知识
    PROCEDURAL = "procedural"  # 程序性知识（工具执行）
    PATTERN = "pattern"  # 结晶经验
    TOOL_MEMORY = "tool_memory"  # 工具记忆


class StorageLayer(Enum):
    """存储层级"""

    L0_BUFFER = 0  # 缓冲区（秒级）
    L1_HOT = 1  # 正文库（分钟级）
    L2_WARM = 2  # JSON 温存储（小时级）
    L3_COLD = 3  # 压缩冷存储（天级）
    L4_CRYSTAL = 4  # 结晶经验（永久）


#: 正文表没有的节点字段落在 Memory.metadata 里随正文一起走——另开一张表就是把
#: 刚收口的第二落点换个地方再建一遍。键名以本组常量为唯一出处。
META_LAYER = "cse_layer"
META_TRACE_ID = "cse_trace_id"
META_CATEGORY = "cse_category"
META_MEMORY_TYPE = "cse_memory_type"
META_AGENT_SCOPE = "cse_agent_id"
_CARRY_KEYS = frozenset(
    {META_LAYER, META_TRACE_ID, META_CATEGORY, META_MEMORY_TYPE, META_AGENT_SCOPE}
)

#: 生产侧节点类别的**上下文可见性表态表**：每个新增类别都必须在这里点名（枚举守卫
#: `test_everyDeclaredProducerCategory` 按 AST 扫 `UnifiedMemoryNode(category="X")` 的字面量逼这条）。
#: 未点名的类别**默认放行**——正文库里的普通记忆（general/conversation/reflection…）本来
#: 就走这条路进上下文，把它们并进白名单会当场掐死现网检索；所以杠杆只能是"显式禁"。
#:
#: `reasoning_trace` 为什么必须禁（2026-09-05 事故）：每轮对话把整条推理链
#: （含"晚上好→晚上好呀"这类寒暄）存成记忆，而检索侧不带 category 过滤 ⇒ 寒暄链被当
#: 相关记忆捞回上下文形成回声污染；§6-206 把持久化门接进治理面之后，"门能开"与
#: "开了会不会污染"分成两件事，这张表负责后者。
CONTEXT_VISIBILITY: Dict[str, bool] = {
    "crystallized": True,     # 结晶经验：设计上就要注入
    "reasoning_trace": False,  # 推理链回声：永不进上下文
}


def mayEnterContext(category: Any) -> bool:
    """这一类节点是否允许被检索进上下文。只认这张表，别处不许再判第二遍。"""
    return CONTEXT_VISIBILITY.get(category or "", True) is not False

#: L0 攒够多少条并进正文。崩溃恢复文件在每次 store 时已落盘，未 flush 的节点
#: 检索照样覆盖（retrieve 先扫 L0），所以阈值只决定"什么时候省一次内存态"。
_FLUSH_THRESHOLD = 100


def _enumValue(value) -> Any:
    return value.value if hasattr(value, "value") else value


@dataclass
class UnifiedMemoryNode:
    """统一记忆节点 — 所有记忆类型的唯一数据模型"""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    content: str = ""
    memory_type: MemoryType = MemoryType.SEMANTIC
    category: str = "general"
    temperature: float = 100.0  # 0-100 scale，统一
    layer: StorageLayer = StorageLayer.L1_HOT
    metadata: Dict[str, Any] = field(default_factory=dict)
    embedding: Optional[List[float]] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    access_count: int = 0
    trace_id: Optional[str] = None  # 推理链溯源

    def touch(self):
        """访问一次，温度升高"""
        self.access_count += 1
        self.temperature = min(100.0, self.temperature + 10.0)
        self.updated_at = datetime.now(timezone.utc)

    def decay(self, hours: float = 1.0, rate: float = 1.0):
        """温度衰减"""
        self.temperature = max(0.0, self.temperature - rate * hours)

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典"""
        d = asdict(self)
        d["memory_type"] = self.memory_type.value
        d["layer"] = self.layer.value
        d["created_at"] = self.created_at.isoformat()
        d["updated_at"] = self.updated_at.isoformat()
        return d

    def withAgentScope(self, agent_id: str) -> "UnifiedMemoryNode":
        """把 agent 归属钉在节点上：正文行的 agent_id 必须有值，不许回落 default。"""
        if agent_id:
            self.metadata[META_AGENT_SCOPE] = agent_id
        return self

    def agentScope(self) -> str:
        return str(self.metadata.get(META_AGENT_SCOPE, "") or "")

    def to_memory(self, agent_id: str = ""):
        """转换为 models.Memory（正文库的行模型）。

        Tier 4A.5：量纲映射
        - temperature: 0-100 量纲一致（无需转换）
        - memory_type / category: 本层词表与正文闭集不一定同名，不同名时
          **列里存合法的、原值进 metadata**——写一个正文装载不了的枚举值，
          等于让下一次装载整批抛 ValueError。
        - importance: UnifiedMemoryNode 无此字段 → 由 Memory 缺省 50.0
        """
        from neurova.cognitive_layers.memory_layer.models import (
            Memory,
            MemoryCategory,
            MemoryType as ModelMemoryType,
        )

        metadata = dict(self.metadata) if self.metadata else {}
        metadata[META_LAYER] = self.layer.value
        if self.trace_id:
            metadata[META_TRACE_ID] = self.trace_id

        def _map(value, enumCls, metaKey: str, fallback):
            try:
                return enumCls(_enumValue(value))
            except (ValueError, KeyError, TypeError):
                metadata[metaKey] = _enumValue(value)
                return fallback

        return Memory(
            id=self.id,
            content=self.content,
            memory_type=_map(
                self.memory_type, ModelMemoryType, META_MEMORY_TYPE, ModelMemoryType.SEMANTIC
            ),
            category=_map(self.category, MemoryCategory, META_CATEGORY, MemoryCategory.GENERAL),
            temperature=self.temperature,
            metadata=metadata,
            access_count=self.access_count,
            embedding=list(self.embedding) if self.embedding else None,
            agent_id=agent_id or self.agentScope(),
            created_at=self.created_at,
            updated_at=self.updated_at,
        )

    @classmethod
    def from_memory(cls, mem) -> "UnifiedMemoryNode":
        """从 models.Memory 还原节点（与 to_memory 同一套 metadata 键，双向不丢字段）"""
        metadata = dict(mem.metadata) if mem.metadata else {}
        rawType = metadata.get(META_MEMORY_TYPE) or _enumValue(mem.memory_type)
        rawCategory = metadata.get(META_CATEGORY) or _enumValue(mem.category)
        try:
            memoryType = MemoryType(rawType)
        except (ValueError, KeyError):
            memoryType = MemoryType.SEMANTIC
        rawLayer = metadata.get(META_LAYER)
        layer = (
            StorageLayer(rawLayer)
            if rawLayer in {e.value for e in StorageLayer}
            else StorageLayer.L1_HOT
        )
        return cls(
            id=mem.id,
            content=mem.content,
            memory_type=memoryType,
            category=str(rawCategory),
            temperature=mem.temperature,
            layer=layer,
            metadata={k: v for k, v in metadata.items() if k not in _CARRY_KEYS},
            embedding=list(mem.embedding) if getattr(mem, "embedding", None) else None,
            access_count=mem.access_count,
            created_at=mem.created_at,
            updated_at=mem.updated_at,
            trace_id=metadata.get(META_TRACE_ID),
        )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UnifiedMemoryNode":
        """从字典反序列化"""
        data = dict(data)  # copy
        if "memory_type" in data and isinstance(data["memory_type"], str):
            data["memory_type"] = MemoryType(data["memory_type"])
        if "layer" in data and isinstance(data["layer"], int):
            data["layer"] = StorageLayer(data["layer"])
        if "created_at" in data and isinstance(data["created_at"], str):
            data["created_at"] = datetime.fromisoformat(data["created_at"])
        if "updated_at" in data and isinstance(data["updated_at"], str):
            data["updated_at"] = datetime.fromisoformat(data["updated_at"])
        known = {k for k in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


# ── L0 缓冲与检索编排 ─────────────────────────────────────────────────────────

#: 本层与正文库的唯一接缝。缺任何一个都当场点名，不给"静默当这层不存在"第二次机会。
_BODY_CONTRACT = (
    "persist_memory_batch",
    "searchMemoriesFulltext",
    "iterBodyMemories",
    "bodyMemoryById",
    "bodyMemoryCount",
    "persistenceDbPath",
    "memoryScope",
)


class CognitiveStorageEngine:
    """正文库之上的 L0 缓冲 + 检索编排层（不再持有自己的库与 schema）。"""

    def __init__(self, agent_id: str, memory_manager):
        """
        Args:
            agent_id: 本引擎服务的 agent；正文行的 agent_id 由它写死，不带默认。
            memory_manager: 正文库的所有者（`MemoryManager`）。写走它的
                `persist_memory_batch`，读走它的 `searchMemoriesFulltext`——
                作用域三元组只有它那一处出处，绕开它就等于绕过隔离口径。
        """
        if not agent_id:
            raise ValueError("agent_id 不得为空——正文行的归属必须有值")
        if memory_manager is None:
            raise ValueError(
                "memory_manager 必填：正文库归 MemoryManager，本层已无第二个落点可退。"
                "要降级请显式不装配本层，不要静默造一份空库。"
            )
        missing = [n for n in _BODY_CONTRACT if not callable(getattr(memory_manager, n, None))]
        if missing:
            raise AttributeError(
                "memory_manager 缺少 %s——本层与正文库的契约以这几个方法为唯一接缝"
                % ", ".join(missing)
            )

        self.agent_id = agent_id
        self._memory = memory_manager

        bodyPath = memory_manager.persistenceDbPath()
        # 崩溃恢复文件与正文库同目录、同命运：正文不落盘的地方（`:memory:`）它也不该落。
        self._wal_path: Optional[Path] = (
            Path(bodyPath).parent / "cognitive_wal.jsonl" if bodyPath else None
        )

        self._l0_buffer: List[UnifiedMemoryNode] = []
        # 必须用 RLock：_walAppend 在持 _wal_lock 时会调 _flushL0ToBody，后者再取同一把锁。
        self._wal_lock = threading.RLock()
        self._buffer_lock = threading.RLock()

        self._recoverWal()

        logger.info(
            "CognitiveStorageEngine 已挂到正文库: agent=%s, L0=%d 条, body=%s",
            agent_id, len(self._l0_buffer), bodyPath or "未落盘",
        )

    _WAL_MAX_SIZE_BYTES = 10 * 1024 * 1024  # S-2: 恢复文件最大 10MB

    def _recoverWal(self) -> None:
        """S-1: 从崩溃恢复文件把没并进的节点取回 L0（整体在锁内保护）。"""
        if self._wal_path is None or not self._wal_path.exists():
            return
        try:
            with self._wal_lock, self._buffer_lock:
                with open(self._wal_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                recovered = 0
                for line in lines:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    try:
                        node = UnifiedMemoryNode.from_dict(json.loads(stripped))
                    except (json.JSONDecodeError, ValueError, KeyError) as exc:
                        logger.warning("恢复文件跳过坏行: %s", exc)
                        continue
                    if any(n.id == node.id for n in self._l0_buffer):
                        continue
                    self._l0_buffer.append(node.withAgentScope(self.agent_id))
                    recovered += 1
                if recovered:
                    logger.info("崩溃恢复取回 %d 个未并入正文的节点", recovered)
        except OSError as exc:
            logger.error("崩溃恢复文件读取失败（L0 从空开始，正文不受影响）: %s", exc)

    def _convergeWal(self, writtenIds: set) -> None:
        """把已并入正文的条目从恢复文件里收敛掉，**其余一律保留**。

        DATA-P1-3 的教训：既不能无条件清空，也不能"按当前缓冲重写"——
        `_walAppend` 与缓冲 append 之间的窗口里，`store()` 追加的节点不在本次
        快照内，按缓冲重写会抹掉它唯一的磁盘记录（崩溃即永久丢失）。
        坏行同样保留，恢复侧有逐行容错。
        """
        if self._wal_path is None or not self._wal_path.exists():
            return
        with open(self._wal_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        kept: list = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                entryId = json.loads(stripped).get("id")
            except (json.JSONDecodeError, ValueError):
                kept.append(stripped)
                continue
            if entryId not in writtenIds:
                kept.append(stripped)
        with open(self._wal_path, "w", encoding="utf-8") as f:
            for line in kept:
                f.write(line + "\n")

    def _walAppend(self, node: UnifiedMemoryNode) -> None:
        """追加一条到崩溃恢复文件；超限先并进正文再收敛，不让它无界长。"""
        if self._wal_path is None:
            return
        with self._wal_lock:
            try:
                with open(self._wal_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(node.to_dict(), ensure_ascii=False) + "\n")
                size = self._wal_path.stat().st_size
            except OSError as exc:
                logger.error("崩溃恢复写入失败（节点仍在 L0，检索不受影响）: %s", exc)
                return
            if size > self._WAL_MAX_SIZE_BYTES:
                logger.warning(
                    "崩溃恢复文件已达 %.1f MB，强制并进正文库以收敛", size / 1024 / 1024
                )
                self._flushL0ToBody()

    def _flushL0ToBody(self) -> int:
        """把 L0 并进正文库（经唯一写入口）。

        M-11 的教训保留：写入失败**不清缓冲**。失败有两种形状，都得留住数据——
        写入口上抛（调用方日志兜底），或写入口把异常吞在内部只回一个 False
        （`persist_memory_batch` 的 fail-soft 语义，为召回那侧的 touch 落盘而设）。
        后者以前没人接：批次照清、恢复文件照收敛，那条节点就只剩"L0 里刚被删掉"
        这一段历史——本批把它接上（§6-211）。
        """
        with self._buffer_lock:
            if not self._l0_buffer:
                return 0
            nodes = list(self._l0_buffer)
        # 作用域章由正文库那一侧给（`memoryScope` 是唯一取法）：不带 neuser/user 的行
        # 会落在空作用域上，而读侧按生效三元组过滤——写进去就再也读不回来。
        neuserId, userId = self._memory.memoryScope()
        mems = []
        for node in nodes:
            mem = node.to_memory(self.agent_id)
            mem.neuser_id, mem.user_id = neuserId, userId
            mems.append(mem)
        if not self._memory.persist_memory_batch(mems):
            logger.warning("L0 未并入正文库，保留 %d 条待重试", len(nodes))
            return 0
        writtenIds = {node.id for node in nodes}
        with self._buffer_lock:
            self._l0_buffer = [n for n in self._l0_buffer if n.id not in writtenIds]
        with self._wal_lock:
            self._convergeWal(writtenIds)
        # 正文库与 manager 的进程内快照在这一刻是分叉的：写入口只落盘，而固化/召回那
        # 12 个调用档读的是快照 ⇒ 引擎写的行要等下次重启才进得来（§6-211）。分歧在这点
        # 制造就在这点收尾，且只走仓里已有的唯一对账口 `reload_memories()`——不在引擎侧
        # 另造一份"读盘并入"，那是第二个平行体系（教义第 6 条）。
        # 锁序是「引擎锁 → manager 的 RLock」，与上面那句写盘同向；反向不成立
        # （manager 不引引擎，判据钉着这条前提），故不会与 WAL/L0 那两把锁互咬。
        self._memory.reload_memories()
        logger.debug("L0 并入正文库 %d 条", len(nodes))
        return len(nodes)

    def store(self, node: UnifiedMemoryNode) -> str:
        """写入记忆节点：先落恢复文件，再进 L0；攒够阈值或关闭时并进正文。"""
        node.withAgentScope(self.agent_id)
        self._walAppend(node)
        with self._buffer_lock:
            self._l0_buffer.append(node)
            needFlush = len(self._l0_buffer) >= _FLUSH_THRESHOLD
        if needFlush:
            self._flushL0ToBody()
        return node.id

    def _apply_filters(self, node: UnifiedMemoryNode, filters: Dict) -> bool:
        """检查节点是否满足过滤条件，返回 True 表示应跳过"""
        if not filters:
            return False
        for key, val in filters.items():
            if val is not None:
                if key == "memory_type" and node.memory_type.value != val:
                    return True
                elif key == "category" and node.category != val:
                    return True
                # 工单 017：冷档过滤。淘汰必须可观测——只把温度调小而读侧照样返回，
                # 等于没有淘汰路径（这一格是给结晶模式用的，调用方自己带阈值）
                elif key == "min_temperature" and node.temperature < float(val):
                    return True
        return False

    def retrieve(self, query: str, limit: int = 10, filters: Dict = None) -> List[UnifiedMemoryNode]:
        """跨层检索：L0 缓冲（内存子串）+ 正文库全文（作用域口径归 MemoryManager）。"""
        with self._buffer_lock:
            l0Snapshot = list(self._l0_buffer)

        # 回声过滤装在**记账之前**：两条支路共用同一个谓词，被丢掉的行既不返回也不 +10
        # （先记账再过滤＝冷档被自己这次命中复活，与工单 017 那条同形）。
        results: List[UnifiedMemoryNode] = [
            node
            for node in l0Snapshot
            if query.lower() in node.content.lower()
            and mayEnterContext(node.category)
            and not self._apply_filters(node, filters)
        ]

        for mem in self._memory.searchMemoriesFulltext(query, limit=limit):
            node = UnifiedMemoryNode.from_memory(mem).withAgentScope(self.agent_id)
            if mayEnterContext(node.category) and not self._apply_filters(node, filters):
                results.append(node)

        # S-4: 去重(按 id)，保留温度更高的那份
        seen: Dict[str, UnifiedMemoryNode] = {}
        for node in results:
            if node.id not in seen or node.temperature > seen[node.id].temperature:
                seen[node.id] = node
        deduped = sorted(seen.values(), key=lambda n: n.temperature, reverse=True)
        top = deduped[:limit]

        # 记账只给**真回出去**的那批，顺序不能倒：先记账再过滤，被过滤掉的行也已经
        # 挨了一次 +10，冷档就被自己这次命中复活（工单 017 的淘汰因此永不成立）。
        # 库里那部分的计数由 `MemoryManager.creditRecallHits` 一处落盘；
        # 还压在 L0 的节点库里没行，touch 的值随 flush 落盘（契约 006 第 3 条）。
        bufferedIds = {node.id for node in l0Snapshot}
        for node in top:
            node.touch()
        self._memory.creditRecallHits([n.id for n in top if n.id not in bufferedIds])
        return top

    def iter_nodes(self, filters: Dict = None, limit: int = 500) -> List[UnifiedMemoryNode]:
        """只读列举节点，**不做访问记账**。

        巡检类调用方（结晶模式冷处理 017）需要遍历节点，但不能把"我在巡检"
        记成"这条被用了一次"——走 retrieve() 会 touch + 刷新 updated_at，
        于是闲置判定永远不成立，冷档也永远进不来。

        这里**不过滤上下文可见性**：巡检的对象恰恰包括永不进上下文的那一类
        （推理链回声行要被人降温度、归档掉），把它们藏起来等于让治理看不见。
        """
        with self._buffer_lock:
            buffered = list(self._l0_buffer)
        nodes = buffered + [
            UnifiedMemoryNode.from_memory(mem).withAgentScope(self.agent_id)
            for mem in self._memory.iterBodyMemories(limit=limit)
        ]
        byId: Dict[str, UnifiedMemoryNode] = {}
        for node in nodes:
            if node.id not in byId or node.temperature > byId[node.id].temperature:
                byId[node.id] = node
        return [n for n in byId.values() if not self._apply_filters(n, filters)]

    def update_temperature(self, node_id: str, delta: float) -> None:
        """更新温度：L0 命中改内存对象；正文行取回后走唯一写入口回写。

        L0 命中的节点按定义还没进正文（flush 会把它从缓冲里摘掉），旧实现那句
        同步 L1 的 UPDATE 恒 0 行，这里不再保留。
        """
        with self._buffer_lock:
            l0Hit = next((n for n in self._l0_buffer if n.id == node_id), None)
        if l0Hit is not None:
            l0Hit.temperature = max(0.0, min(100.0, l0Hit.temperature + delta))
            return
        mem = self._memory.bodyMemoryById(node_id)
        if mem is None:
            logger.debug("温度调整落空：节点 %s 不在 L0 也不在正文库", node_id)
            return
        mem.temperature = max(0.0, min(100.0, mem.temperature + delta))
        mem.updated_at = datetime.now(timezone.utc)
        self._memory.persist_memory_batch([mem])

    def get_statistics(self) -> Dict[str, Any]:
        """各层统计（内存态读数持锁取，避免与 store/flush 竞态）。"""
        with self._buffer_lock:
            l0 = len(self._l0_buffer)
        return {
            "l0_buffer": l0,
            "l1_hot": self._memory.bodyMemoryCount(),
        }

    def close(self) -> None:
        """关闭前把 L0 全部并进正文库（不再有连接要关）。"""
        self._flushL0ToBody()
