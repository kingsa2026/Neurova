"""Memory storage layer — thread-safe JSON-backed record store.

Provides CRUD, tag/type/owner queries, batch operations, persistence,
and a module-level singleton factory.
"""

from __future__ import annotations

import datetime
import json
from neurova.core.logger import get_logger
import threading
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = get_logger(__name__)


def _new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex}" if prefix else uuid.uuid4().hex


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


@dataclass
class MemoryRecord:
    id: str
    content: str
    memory_type: str
    owner: str
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    importance: float = 0.0
    access_count: int = 0
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)
    # 三层隔离字段
    agent_id: str = "default"
    neuser_id: str = "default"
    user_id: str = "default"
    shared: bool = False  # 跨 agent 共享开关（旧模式）
    share_group_ids: List[str] = field(default_factory=list)  # 共享组ID列表（新模式）

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_memory(self):
        """转换为 models.Memory（领域模型）

        Tier 4A.3：量纲映射
        - importance: 0+ → 0-100（乘 100，clamp 到 [0, 100]）
        - temperature: MemoryRecord 无此字段 → 默认 100.0
        - created_at/updated_at: ISO 字符串 → datetime
        """
        from datetime import datetime, timezone

        from neurova.cognitive_layers.memory_layer.models import (
            Memory,
            MemoryType,
        )

        def _safe_enum(val, default):
            if isinstance(val, MemoryType):
                return val
            try:
                return MemoryType(val)
            except (ValueError, KeyError):
                return default

        def _parse_dt(val):
            if isinstance(val, datetime):
                return val
            if isinstance(val, str):
                try:
                    return datetime.fromisoformat(val)
                except ValueError:
                    return datetime.now(timezone.utc)
            return datetime.now(timezone.utc)

        return Memory(
            id=self.id,
            content=self.content,
            memory_type=_safe_enum(self.memory_type, MemoryType.SEMANTIC),
            importance=min(100.0, max(0.0, float(self.importance) * 100.0)),
            metadata=dict(self.metadata) if self.metadata else {},
            agent_id=self.agent_id,
            neuser_id=self.neuser_id,
            user_id=self.user_id,
            shared=self.shared,
            share_group_ids=list(self.share_group_ids) if self.share_group_ids else [],
            access_count=self.access_count,
            created_at=_parse_dt(self.created_at),
            updated_at=_parse_dt(self.updated_at),
        )

    @classmethod
    def from_memory(cls, mem) -> "MemoryRecord":
        """从 models.Memory 构造（量纲反向映射）

        Tier 4A.3：
        - importance: 0-100 → 0+（除 100）
        - tags: 从 metadata.tags 提取（若有）
        - owner: 从 metadata.owner 提取（默认 'default'）
        """
        return cls(
            id=mem.id,
            content=mem.content,
            memory_type=mem.memory_type.value if hasattr(mem.memory_type, "value") else str(mem.memory_type),
            owner=(mem.metadata or {}).get("owner", "default"),
            tags=list((mem.metadata or {}).get("tags", [])),
            metadata=dict(mem.metadata) if mem.metadata else {},
            importance=float(mem.importance) / 100.0,
            access_count=mem.access_count,
            created_at=mem.created_at.isoformat() if hasattr(mem.created_at, "isoformat") else _now_iso(),
            updated_at=mem.updated_at.isoformat() if hasattr(mem.updated_at, "isoformat") else _now_iso(),
            agent_id=mem.agent_id,
            neuser_id=mem.neuser_id,
            user_id=mem.user_id,
            shared=mem.shared,
            share_group_ids=list(mem.share_group_ids) if mem.share_group_ids else [],
        )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MemoryRecord":
        known = {
            "id",
            "content",
            "memory_type",
            "owner",
            "tags",
            "metadata",
            "importance",
            "access_count",
            "created_at",
            "updated_at",
            "agent_id",
            "neuser_id",
            "user_id",
            "shared",
            "share_group_ids",
        }
        kwargs: Dict[str, Any] = {k: v for k, v in data.items() if k in known}
        if "tags" in kwargs and kwargs["tags"] is None:
            kwargs["tags"] = []
        if "metadata" in kwargs and kwargs["metadata"] is None:
            kwargs["metadata"] = {}
        if "share_group_ids" in kwargs and kwargs["share_group_ids"] is None:
            kwargs["share_group_ids"] = []
        return cls(**kwargs)


@dataclass
class MemoryIndex:
    by_type: Dict[str, List[str]] = field(default_factory=dict)
    by_owner: Dict[str, List[str]] = field(default_factory=dict)
    by_tag: Dict[str, List[str]] = field(default_factory=dict)
    # 三层隔离索引
    by_agent: Dict[str, List[str]] = field(default_factory=dict)
    by_neuser: Dict[str, List[str]] = field(default_factory=dict)
    by_user: Dict[str, List[str]] = field(default_factory=dict)
    by_isolation_key: Dict[str, List[str]] = field(default_factory=dict)

    def add(self, record: "MemoryRecord") -> None:
        self.by_type.setdefault(record.memory_type, [])
        if record.id not in self.by_type[record.memory_type]:
            self.by_type[record.memory_type].append(record.id)
        self.by_owner.setdefault(record.owner, [])
        if record.id not in self.by_owner[record.owner]:
            self.by_owner[record.owner].append(record.id)
        for tag in record.tags:
            self.by_tag.setdefault(tag, [])
            if record.id not in self.by_tag[tag]:
                self.by_tag[tag].append(record.id)

        # 三层隔离索引
        self.by_agent.setdefault(record.agent_id, [])
        if record.id not in self.by_agent[record.agent_id]:
            self.by_agent[record.agent_id].append(record.id)

        self.by_neuser.setdefault(record.neuser_id, [])
        if record.id not in self.by_neuser[record.neuser_id]:
            self.by_neuser[record.neuser_id].append(record.id)

        self.by_user.setdefault(record.user_id, [])
        if record.id not in self.by_user[record.user_id]:
            self.by_user[record.user_id].append(record.id)

        # 组合隔离键
        isolation_key = f"{record.agent_id}:{record.neuser_id}:{record.user_id}"
        self.by_isolation_key.setdefault(isolation_key, [])
        if record.id not in self.by_isolation_key[isolation_key]:
            self.by_isolation_key[isolation_key].append(record.id)

    def remove(self, record: "MemoryRecord") -> None:
        for bucket in (self.by_type, self.by_owner):
            key = record.memory_type if bucket is self.by_type else record.owner
            ids = bucket.get(key)
            if ids and record.id in ids:
                ids.remove(record.id)
            if ids is not None and not ids:
                bucket.pop(key, None)
        for tag in list(record.tags):
            ids = self.by_tag.get(tag)
            if ids and record.id in ids:
                ids.remove(record.id)
            if ids is not None and not ids:
                self.by_tag.pop(tag, None)

        # 三层隔离索引清理
        for bucket, key in [
            (self.by_agent, record.agent_id),
            (self.by_neuser, record.neuser_id),
            (self.by_user, record.user_id),
        ]:
            ids = bucket.get(key)
            if ids and record.id in ids:
                ids.remove(record.id)
            if ids is not None and not ids:
                bucket.pop(key, None)

        # 组合隔离键清理
        isolation_key = f"{record.agent_id}:{record.neuser_id}:{record.user_id}"
        ids = self.by_isolation_key.get(isolation_key)
        if ids and record.id in ids:
            ids.remove(record.id)
        if ids is not None and not ids:
            self.by_isolation_key.pop(isolation_key, None)

    def clear(self) -> None:
        self.by_type.clear()
        self.by_owner.clear()
        self.by_tag.clear()
        self.by_agent.clear()
        self.by_neuser.clear()
        self.by_user.clear()
        self.by_isolation_key.clear()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "by_type": self.by_type,
            "by_owner": self.by_owner,
            "by_tag": self.by_tag,
            "by_agent": self.by_agent,
            "by_neuser": self.by_neuser,
            "by_user": self.by_user,
            "by_isolation_key": self.by_isolation_key,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MemoryIndex":
        idx = cls()
        idx.by_type.update(data.get("by_type", {}) or {})
        idx.by_owner.update(data.get("by_owner", {}) or {})
        idx.by_tag.update(data.get("by_tag", {}) or {})
        idx.by_agent.update(data.get("by_agent", {}) or {})
        idx.by_neuser.update(data.get("by_neuser", {}) or {})
        idx.by_user.update(data.get("by_user", {}) or {})
        idx.by_isolation_key.update(data.get("by_isolation_key", {}) or {})
        return idx


class MemoryStorage:
    """Thread-safe JSON-backed memory store."""

    DEFAULT_FILENAME = "memories.json"

    def __init__(self, storage_dir: str) -> None:
        self._dir = Path(storage_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path = self._dir / self.DEFAULT_FILENAME
        self._records: Dict[str, MemoryRecord] = {}
        self._index = MemoryIndex()
        self._lock = threading.RLock()
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Failed to read memory store %s: %s", self._path, exc)
            return
        records_raw = raw.get("records", {}) if isinstance(raw, dict) else {}
        if not isinstance(records_raw, dict):
            return
        self._records.clear()
        self._index.clear()
        for mid, payload in records_raw.items():
            if not isinstance(payload, dict):
                continue
            payload = dict(payload)
            payload.setdefault("id", mid)
            try:
                rec = MemoryRecord.from_dict(payload)
            except TypeError as exc:
                # Bug 18 修复: 原代码 except TypeError: continue 静默吞,
                # 数据损坏无任何诊断。改为 warning 日志后跳过。
                logger.warning(
                    "跳过损坏的 memory 记录 %s: %s (payload keys=%s)",
                    mid, exc, list(payload.keys()),
                )
                continue
            self._records[rec.id] = rec
            self._index.add(rec)

    def _save(self) -> None:
        payload = {
            "version": 1,
            "saved_at": _now_iso(),
            "records": {mid: rec.to_dict() for mid, rec in self._records.items()},
            "index": self._index.to_dict(),
        }
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        try:
            tmp.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            tmp.replace(self._path)
        except OSError as exc:
            logger.warning("Failed to persist memory store %s: %s", self._path, exc)

    def count(self) -> int:
        with self._lock:
            return len(self._records)

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            total = len(self._records)
            by_type: Dict[str, int] = {}
            by_owner: Dict[str, int] = {}
            tag_counter: Dict[str, int] = {}
            access_total = 0
            for rec in self._records.values():
                by_type[rec.memory_type] = by_type.get(rec.memory_type, 0) + 1
                by_owner[rec.owner] = by_owner.get(rec.owner, 0) + 1
                access_total += rec.access_count
                for tag in rec.tags:
                    tag_counter[tag] = tag_counter.get(tag, 0) + 1
            return {
                "total": total,
                "by_type": by_type,
                "by_owner": by_owner,
                "by_tag": tag_counter,
                "access_total": access_total,
                "storage_dir": str(self._dir),
                "path": str(self._path),
            }

    def save(
        self,
        content: str,
        memory_type: str,
        owner: str = "default",
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        importance: float = 0.0,
        isolation_context: Optional["IsolationContext"] = None,
    ) -> str:
        with self._lock:
            mid = _new_id("mem_")
            now = _now_iso()

            # 从隔离上下文获取隔离字段
            agent_id = isolation_context.agent_id if isolation_context else "default"
            neuser_id = isolation_context.neuser_id if isolation_context else "default"
            user_id = isolation_context.user_id if isolation_context else "default"
            shared = isolation_context.shared if isolation_context else False
            share_group_ids = list(isolation_context.share_group_ids) if isolation_context else []

            rec = MemoryRecord(
                id=mid,
                content=content,
                memory_type=memory_type,
                owner=owner,
                tags=list(tags) if tags else [],
                metadata=dict(metadata) if metadata else {},
                importance=float(importance) if importance else 0.0,
                access_count=0,
                created_at=now,
                updated_at=now,
                agent_id=agent_id,
                neuser_id=neuser_id,
                user_id=user_id,
                shared=shared,
                share_group_ids=share_group_ids,
            )
            self._records[mid] = rec
            self._index.add(rec)
            self._save()
            return mid

    def get(self, memory_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            rec = self._records.get(memory_id)
            return rec.to_dict() if rec else None

    def delete(self, memory_id: str) -> bool:
        with self._lock:
            rec = self._records.pop(memory_id, None)
            if rec is None:
                return False
            self._index.remove(rec)
            self._save()
            return True

    def update_memory(self, memory_id: str, **fields: Any) -> bool:
        with self._lock:
            rec = self._records.get(memory_id)
            if rec is None:
                return False
            self._index.remove(rec)
            for key, value in fields.items():
                if key == "tags" and value is not None:
                    rec.tags = list(value)
                elif key == "metadata" and value is not None:
                    rec.metadata = dict(value)
                elif hasattr(rec, key):
                    setattr(rec, key, value)
            rec.updated_at = _now_iso()
            self._index.add(rec)
            self._save()
            return True

    def increment_access(self, memory_id: str) -> bool:
        with self._lock:
            rec = self._records.get(memory_id)
            if rec is None:
                return False
            rec.access_count += 1
            rec.updated_at = _now_iso()
            self._save()
            return True

    def query(
        self,
        memory_type: Optional[str] = None,
        owner: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        tags: Optional[List[str]] = None,
        limit: Optional[int] = None,
        isolation_context: Optional["IsolationContext"] = None,
    ) -> List[Dict[str, Any]]:
        with self._lock:
            results: List[MemoryRecord] = []
            for rec in self._records.values():
                # 三层隔离过滤
                if isolation_context is not None:
                    # agent_id 隔离：共享记忆跳过 agent 检查
                    if not isolation_context.shared and not rec.shared:
                        if rec.agent_id != isolation_context.agent_id:
                            # 检查共享组：如果请求者和记忆在同一共享组，允许访问
                            if not self._in_same_share_group(isolation_context, rec):
                                continue
                    elif rec.shared:
                        # 共享记忆可以被任何 agent 访问
                        pass
                    else:
                        # isolation_context.shared=True，但记忆不共享，仍检查 agent_id
                        if rec.agent_id != isolation_context.agent_id:
                            # 检查共享组
                            if not self._in_same_share_group(isolation_context, rec):
                                continue

                    # neuser_id 和 user_id 始终检查
                    if isolation_context.neuser_id != "default" and rec.neuser_id != isolation_context.neuser_id:
                        continue
                    if isolation_context.user_id != "default" and rec.user_id != isolation_context.user_id:
                        continue

                if memory_type is not None and rec.memory_type != memory_type:
                    continue
                if owner is not None and rec.owner != owner:
                    continue
                # Bug 19 修复: 原代码 rec.created_at < start_time 是字符串比较,
                # ISO 8601 不同时区表示的相同时刻字符串不同, 导致时区敏感比较错误。
                # 现用 datetime.fromisoformat() 解析为 aware datetime 后比较。
                if start_time is not None:
                    try:
                        rec_dt = datetime.datetime.fromisoformat(rec.created_at)
                        start_dt = datetime.datetime.fromisoformat(start_time)
                        if rec_dt < start_dt:
                            continue
                    except (ValueError, TypeError):
                        # 解析失败回退到字符串比较 (与原行为兼容)
                        if rec.created_at < start_time:
                            continue
                if end_time is not None:
                    try:
                        rec_dt = datetime.datetime.fromisoformat(rec.created_at)
                        end_dt = datetime.datetime.fromisoformat(end_time)
                        if rec_dt > end_dt:
                            continue
                    except (ValueError, TypeError):
                        if rec.created_at > end_time:
                            continue
                if tags is not None:
                    if not any(t in rec.tags for t in tags):
                        continue
                results.append(rec)
            results.sort(key=lambda r: r.created_at)
            if limit is not None and limit >= 0:
                results = results[:limit]
            return [r.to_dict() for r in results]

    def list_by_tags(self, tags: List[str], match_all: bool = False) -> List[Dict[str, Any]]:
        with self._lock:
            if not tags:
                return []
            if match_all:
                wanted = set(tags)
                candidates = [r for r in self._records.values() if wanted.issubset(set(r.tags))]
            else:
                wanted = set(tags)
                candidates = [r for r in self._records.values() if wanted.intersection(r.tags)]
            candidates.sort(key=lambda r: r.created_at)
            return [r.to_dict() for r in candidates]

    def batch_save(
        self,
        payloads: List[Dict[str, Any]],
        isolation_context: Optional["IsolationContext"] = None,
    ) -> List[str]:
        """批量保存记忆

        Bug 15 修复: 增加 isolation_context 参数, 写入 MemoryRecord 时
        填充 agent_id/neuser_id/user_id, 否则默认 "default" 导致跨用户污染。
        """
        with self._lock:
            ids: List[str] = []
            # Bug 15 修复: 从隔离上下文获取三层隔离字段
            agent_id = isolation_context.agent_id if isolation_context else "default"
            neuser_id = isolation_context.neuser_id if isolation_context else "default"
            user_id = isolation_context.user_id if isolation_context else "default"
            shared = isolation_context.shared if isolation_context else False
            share_group_ids = list(isolation_context.share_group_ids) if isolation_context else []
            for payload in payloads:
                mid = _new_id("mem_")
                now = _now_iso()
                tags = payload.get("tags") or []
                metadata = payload.get("metadata") or {}
                rec = MemoryRecord(
                    id=mid,
                    content=str(payload.get("content", "")),
                    memory_type=str(payload.get("memory_type", "episodic")),
                    owner=str(payload.get("owner", "")),
                    tags=list(tags),
                    metadata=dict(metadata),
                    importance=float(payload.get("importance", 0.0) or 0.0),
                    access_count=int(payload.get("access_count", 0) or 0),
                    created_at=payload.get("created_at") or now,
                    updated_at=payload.get("updated_at") or now,
                    agent_id=agent_id,
                    neuser_id=neuser_id,
                    user_id=user_id,
                    shared=shared,
                    share_group_ids=share_group_ids,
                )
                self._records[mid] = rec
                self._index.add(rec)
                ids.append(mid)
            if ids:
                self._save()
            return ids

    def batch_delete(self, memory_ids: List[str]) -> int:
        with self._lock:
            removed = 0
            for mid in memory_ids:
                rec = self._records.pop(mid, None)
                if rec is not None:
                    self._index.remove(rec)
                    removed += 1
            if removed:
                self._save()
            return removed

    def list_all(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [rec.to_dict() for rec in self._records.values()]

    def get_recent_memories(
        self,
        days: Optional[int] = None,
        limit: int = 100,
        agent_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """获取最近 N 天的记忆（按 created_at DESC 排序）

        Bug 10 修复：补全 8 处调用方所需的 get_recent_memories 方法。

        Args:
            days: 时间窗口（天），None 表示不限制
            limit: 返回上限
            agent_id/user_id: 三层隔离过滤（None 表示不过滤）

        Returns:
            List[Dict]: 记忆字典列表
        """
        cutoff_iso = None
        if days is not None:
            cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)
            cutoff_iso = cutoff.isoformat()

        with self._lock:
            records = list(self._records.values())

        filtered = []
        for r in records:
            if cutoff_iso and r.created_at < cutoff_iso:
                continue
            if agent_id is not None and r.agent_id != agent_id:
                continue
            if user_id is not None and r.user_id != user_id:
                continue
            filtered.append(r)

        filtered.sort(key=lambda r: r.created_at, reverse=True)
        return [r.to_dict() for r in filtered[:limit]]

    def delete_memory(self, memory_id: str) -> bool:
        """删除单条记忆

        Bug 10 修复：补全 8 处调用方所需的 delete_memory 方法。
        Bug 17 修复：委托到 delete 消除重复代码, 保持单一实现源。

        Returns:
            True 如果删除成功，False 如果记忆不存在
        """
        return self.delete(memory_id)

    def clear(self) -> int:
        with self._lock:
            count = len(self._records)
            self._records.clear()
            self._index.clear()
            if count:
                self._save()
            return count

    def _in_same_share_group(self, isolation_context: "IsolationContext", rec: MemoryRecord) -> bool:
        """检查请求者和记忆记录是否在同一共享组中"""
        try:
            from .share_group import get_share_group_manager

            manager = get_share_group_manager()

            # 获取请求者的 agent_id
            requester_agent = isolation_context.agent_id
            record_agent = rec.agent_id

            # 如果任一 agent_id 为空或 default，不共享
            if not requester_agent or requester_agent == "default":
                return False
            if not record_agent or record_agent == "default":
                return False

            # 如果请求者和记录的 agent_id 相同，允许访问
            if requester_agent == record_agent:
                return True

            # 检查是否在同一共享组
            return manager.are_agents_shared(requester_agent, record_agent)
        except Exception as e:
            logger.warning("Share group check failed: %s", e)
            return False

    def storage_path(self) -> str:
        return str(self._path)


_singleton: Optional[MemoryStorage] = None
_singleton_lock = threading.Lock()
_DEFAULT_DIR = "./data/memory_layer"


def get_memory_storage() -> MemoryStorage:
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            target = Path(_DEFAULT_DIR)
            target.mkdir(parents=True, exist_ok=True)
            _singleton = MemoryStorage(str(target))
    return _singleton
