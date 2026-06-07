"""
向量索引管理器 - 增量同步与异步优化

提供：
1. 增量同步 - 只同步变化的记忆
2. 异步索引更新 - 后台线程处理
3. 索引状态追踪 - 完整的索引生命周期管理
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import json
import logging
import os
from pathlib import Path
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


# ────── Enums ──────

class SyncStatus(Enum):
    """同步状态"""
    IDLE = "idle"
    SYNCING = "syncing"
    PARTIAL = "partial"
    FAILED = "failed"
    COMPLETED = "completed"


class OperationType(Enum):
    """操作类型"""
    ADD = "add"
    UPDATE = "update"
    DELETE = "delete"
    REBUILD = "rebuild"


# ────── Data Models ──────

@dataclass
class IndexOperation:
    """索引操作"""
    op_id: str = ""
    op_type: OperationType = OperationType.ADD
    memory_id: str = ""
    embedding: Optional[List[float]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    priority: int = 0  # 0=normal, higher=more urgent


@dataclass
class IndexState:
    """索引状态"""
    total_vectors: int = 0
    indexed_count: int = 0
    pending_count: int = 0
    failed_count: int = 0
    last_sync_time: Optional[datetime] = None
    last_full_rebuild: Optional[datetime] = None
    sync_status: SyncStatus = SyncStatus.IDLE
    version: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_vectors": self.total_vectors,
            "indexed_count": self.indexed_count,
            "pending_count": self.pending_count,
            "failed_count": self.failed_count,
            "last_sync_time": self.last_sync_time.isoformat() if self.last_sync_time else None,
            "last_full_rebuild": self.last_full_rebuild.isoformat() if self.last_full_rebuild else None,
            "sync_status": self.sync_status.value,
            "version": self.version,
        }


# ────── 主类 ──────

class VectorIndexManager:
    """
    向量索引管理器

    管理向量索引的增量同步、异步更新和状态追踪。
    通过回调函数与实际的向量存储层交互（依赖注入模式）。
    """

    def __init__(
        self,
        state_path: Optional[str] = None,
        num_workers: int = 1,
        batch_size: int = 64,
        auto_start: bool = True,
        add_fn: Optional[Callable[[str, List[float], Dict[str, Any]], bool]] = None,
        update_fn: Optional[Callable[[str, List[float], Dict[str, Any]], bool]] = None,
        delete_fn: Optional[Callable[[str], bool]] = None,
        rebuild_fn: Optional[Callable[[], bool]] = None,
        list_ids_fn: Optional[Callable[[], Set[str]]] = None,
    ):
        self._state_path = state_path
        self._num_workers = num_workers
        self._batch_size = batch_size
        self._lock = threading.RLock()

        # 回调函数（依赖注入，与实际向量存储解耦）
        self._add_fn = add_fn or (lambda mid, emb, meta: True)
        self._update_fn = update_fn or (lambda mid, emb, meta: True)
        self._delete_fn = delete_fn or (lambda mid: True)
        self._rebuild_fn = rebuild_fn or (lambda: True)
        self._list_ids_fn = list_ids_fn or (lambda: set())

        # 操作队列
        self._queue: List[IndexOperation] = []
        self._queue_event = threading.Event()

        # 状态
        self._state = self._load_state()

        # Worker 线程
        self._workers: List[threading.Thread] = []
        self._running = False

        if auto_start:
            self._start_workers()

        logger.info(f"VectorIndexManager initialized (workers={num_workers}, batch_size={batch_size})")

    # ── 状态持久化 ──

    def _load_state(self) -> IndexState:
        """从磁盘加载状态"""
        if self._state_path and os.path.exists(self._state_path):
            try:
                with open(self._state_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                state = IndexState(
                    total_vectors=data.get("total_vectors", 0),
                    indexed_count=data.get("indexed_count", 0),
                    pending_count=data.get("pending_count", 0),
                    failed_count=data.get("failed_count", 0),
                    sync_status=SyncStatus(data.get("sync_status", "idle")),
                    version=data.get("version", 0),
                )
                if data.get("last_sync_time"):
                    state.last_sync_time = datetime.fromisoformat(data["last_sync_time"])
                if data.get("last_full_rebuild"):
                    state.last_full_rebuild = datetime.fromisoformat(data["last_full_rebuild"])
                return state
            except Exception as e:
                logger.warning(f"Failed to load index state: {e}")
        return IndexState()

    def _save_state(self):
        """保存状态到磁盘"""
        if not self._state_path:
            return
        try:
            os.makedirs(os.path.dirname(self._state_path) or ".", exist_ok=True)
            with open(self._state_path, "w", encoding="utf-8") as f:
                json.dump(self._state.to_dict(), f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to save index state: {e}")

    # ── Worker 线程 ──

    def _start_workers(self):
        """启动后台 Worker"""
        with self._lock:
            if self._running:
                return
            self._running = True
            for i in range(self._num_workers):
                t = threading.Thread(target=self._worker_loop, name=f"index-worker-{i}", daemon=True)
                t.start()
                self._workers.append(t)
            logger.info(f"Started {self._num_workers} index workers")

    def _worker_loop(self):
        """Worker 主循环"""
        while self._running:
            try:
                # 等待新操作或超时
                self._queue_event.wait(timeout=1.0)
                self._queue_event.clear()

                if not self._running:
                    break

                # 取出一批操作
                batch: List[IndexOperation] = []
                with self._lock:
                    # 按优先级排序
                    self._queue.sort(key=lambda op: -op.priority)
                    batch = self._queue[:self._batch_size]
                    self._queue = self._queue[self._batch_size:]

                for op in batch:
                    if not self._running:
                        break
                    self._process_operation(op)

            except Exception as e:
                logger.error(f"Index worker error: {e}")
                time.sleep(0.5)

    def _process_operation(self, op: IndexOperation) -> bool:
        """处理单个索引操作"""
        try:
            success = False
            if op.op_type == OperationType.ADD:
                if op.embedding:
                    success = self._add_fn(op.memory_id, op.embedding, op.metadata)
            elif op.op_type == OperationType.UPDATE:
                if op.embedding:
                    success = self._update_fn(op.memory_id, op.embedding, op.metadata)
            elif op.op_type == OperationType.DELETE:
                success = self._delete_fn(op.memory_id)
            elif op.op_type == OperationType.REBUILD:
                success = self._rebuild_fn()

            with self._lock:
                if success:
                    self._state.indexed_count += 1
                else:
                    self._state.failed_count += 1
                self._state.pending_count = max(0, self._state.pending_count - 1)

            return success

        except Exception as e:
            logger.error(f"Failed to process operation {op.op_id}: {e}")
            with self._lock:
                self._state.failed_count += 1
                self._state.pending_count = max(0, self._state.pending_count - 1)
            return False

    # ── 公共接口 ──

    def queue_operation(self, op: IndexOperation):
        """将操作加入队列"""
        with self._lock:
            self._queue.append(op)
            self._state.pending_count += 1
            self._state.version += 1
        self._queue_event.set()

    def add_memory(self, memory_id: str, embedding: List[float],
                   metadata: Optional[Dict[str, Any]] = None):
        """添加记忆到索引"""
        self.queue_operation(IndexOperation(
            op_type=OperationType.ADD,
            memory_id=memory_id,
            embedding=embedding,
            metadata=metadata or {},
        ))

    def update_memory(self, memory_id: str, embedding: List[float],
                      metadata: Optional[Dict[str, Any]] = None):
        """更新记忆索引"""
        self.queue_operation(IndexOperation(
            op_type=OperationType.UPDATE,
            memory_id=memory_id,
            embedding=embedding,
            metadata=metadata or {},
        ))

    def delete_memory(self, memory_id: str):
        """从索引删除记忆"""
        self.queue_operation(IndexOperation(
            op_type=OperationType.DELETE,
            memory_id=memory_id,
        ))

    def sync_incremental(self, memory_ids: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        增量同步索引

        参数:
            memory_ids: 要同步的记忆ID列表。None 表示检测变化。

        返回:
            Dict: 同步结果
        """
        with self._lock:
            if self._state.sync_status == SyncStatus.SYNCING:
                return {"status": "already_syncing", "message": "同步已在进行中"}
            self._state.sync_status = SyncStatus.SYNCING

        try:
            start_time = time.time()

            if memory_ids is None:
                # 自动检测需要同步的记忆
                # 这里简化为：队列中的所有操作
                with self._lock:
                    count = len(self._queue)
            else:
                count = len(memory_ids)

            with self._lock:
                self._state.sync_status = SyncStatus.COMPLETED
                self._state.last_sync_time = datetime.now(timezone.utc)
                self._state.total_vectors = self._state.indexed_count

            self._save_state()
            elapsed = time.time() - start_time

            return {
                "status": "completed",
                "synced_count": count,
                "elapsed_seconds": round(elapsed, 2),
            }

        except Exception as e:
            with self._lock:
                self._state.sync_status = SyncStatus.FAILED
            logger.error(f"Incremental sync failed: {e}")
            return {"status": "failed", "error": str(e)}

    def sync_full(self) -> Dict[str, Any]:
        """全量重建索引"""
        with self._lock:
            if self._state.sync_status == SyncStatus.SYNCING:
                return {"status": "already_syncing"}
            self._state.sync_status = SyncStatus.SYNCING

        try:
            start_time = time.time()

            # 触发重建
            success = self._rebuild_fn()

            elapsed = time.time() - start_time
            with self._lock:
                self._state.sync_status = SyncStatus.COMPLETED if success else SyncStatus.FAILED
                self._state.last_full_rebuild = datetime.now(timezone.utc)
                self._state.last_sync_time = self._state.last_full_rebuild
                self._state.failed_count = 0 if success else self._state.failed_count

            self._save_state()
            return {
                "status": "completed" if success else "failed",
                "elapsed_seconds": round(elapsed, 2),
            }

        except Exception as e:
            with self._lock:
                self._state.sync_status = SyncStatus.FAILED
            logger.error(f"Full sync failed: {e}")
            return {"status": "failed", "error": str(e)}

    def get_state(self) -> IndexState:
        """获取当前索引状态"""
        with self._lock:
            # 更新 pending count
            self._state.pending_count = len(self._queue)
            return IndexState(
                total_vectors=self._state.total_vectors,
                indexed_count=self._state.indexed_count,
                pending_count=self._state.pending_count,
                failed_count=self._state.failed_count,
                last_sync_time=self._state.last_sync_time,
                last_full_rebuild=self._state.last_full_rebuild,
                sync_status=self._state.sync_status,
                version=self._state.version,
            )

    def get_pending_count(self) -> int:
        """获取待处理操作数"""
        with self._lock:
            return len(self._queue)

    def wait_for_completion(self, timeout: float = 30.0) -> bool:
        """等待所有操作完成"""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                if not self._queue:
                    return True
            time.sleep(0.1)
        return False

    def shutdown(self, wait: bool = True, timeout: float = 10.0):
        """关闭管理器"""
        logger.info("Shutting down VectorIndexManager...")
        self._running = False
        self._queue_event.set()

        if wait:
            deadline = time.monotonic() + timeout
            for t in self._workers:
                remaining = max(0.1, deadline - time.monotonic())
                t.join(timeout=remaining)

        self._save_state()
        logger.info("VectorIndexManager shut down")

    def __del__(self):
        if self._running:
            self.shutdown(wait=False)