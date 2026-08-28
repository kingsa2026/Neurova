from __future__ import annotations

"""
GrowthLogManager - 反思日志管理器

功能:
- 生成反思日志
- 读取反思日志（用于系统提示构建）
- 反馈验证（记录应用结果）
- 与 MemoryManager 集成
"""

from neurova.core.logger import get_logger
import time
import typing
import uuid
from dataclasses import dataclass
from enum import Enum

# cognitive_layers imports

# core imports


class ReflectionLogStatus(str, Enum):
    """反思日志状态"""

    PENDING = "pending"  # 等待应用
    APPLIED = "applied"  # 已应用
    VALIDATED = "validated"  # 已验证
    ARCHIVED = "archived"  # 已归档
    REJECTED = "rejected"  # 已拒绝


class ReflectionType(str, Enum):
    """反思类型"""

    PERFORMANCE = "performance"  # 性能反思
    ERROR = "error"  # 错误反思
    IMPROVEMENT = "improvement"  # 改进反思
    PATTERN = "pattern"  # 模式反思
    INSIGHT = "insight"  # 洞察反思
    STRATEGY = "strategy"  # 策略反思


@dataclass
class ReflectionLogEntry:
    """反思日志条目"""

    id: str = ""
    timestamp: float = 0.0
    type: ReflectionType = ReflectionType.PERFORMANCE
    status: ReflectionLogStatus = ReflectionLogStatus.PENDING
    title: str = ""
    content: str = ""
    context: typing.Dict[str, typing.Any] = None
    insights: typing.List[str] = None
    action_items: typing.List[str] = None
    confidence: float = 0.0
    applied_at: Optional[float] = None
    validated_at: Optional[float] = None
    memory_id: Optional[str] = None

    def __post_init__(self):
        if not self.id:
            self.id = str(uuid.uuid4())
        if self.timestamp == 0.0:
            self.timestamp = time.time()
        if self.context is None:
            self.context = {}
        if self.insights is None:
            self.insights = []
        if self.action_items is None:
            self.action_items = []

    def to_dict(self) -> typing.Dict[str, typing.Any]:
        """转换为字典"""
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "type": self.type.value,
            "status": self.status.value,
            "title": self.title,
            "content": self.content,
            "context": self.context,
            "insights": self.insights,
            "action_items": self.action_items,
            "confidence": self.confidence,
            "applied_at": self.applied_at,
            "validated_at": self.validated_at,
            "memory_id": self.memory_id,
        }

    @classmethod
    def from_dict(cls, data: typing.Dict[str, typing.Any]) -> "ReflectionLogEntry":
        """从字典创建"""
        return cls(
            id=data.get("id", ""),
            timestamp=data.get("timestamp", 0.0),
            type=ReflectionType(data.get("type", "performance")),
            status=ReflectionLogStatus(data.get("status", "pending")),
            title=data.get("title", ""),
            content=data.get("content", ""),
            context=data.get("context", {}),
            insights=data.get("insights", []),
            action_items=data.get("action_items", []),
            confidence=data.get("confidence", 0.0),
            applied_at=data.get("applied_at"),
            validated_at=data.get("validated_at"),
            memory_id=data.get("memory_id"),
        )


class GrowthLogManager:
    """
    反思日志管理器

    负责生成、存储、读取和验证反思日志。
    与 MemoryManager 集成，将反思日志存储为特殊类型的记忆。
    """

    def __init__(self, memory_manager=None, max_logs: int = 1000):
        """初始化反思日志管理器

        Args:
            memory_manager: 记忆管理器实例
            max_logs: 最大日志数量
        """
        self.memory_manager = memory_manager
        self.max_logs = max_logs
        self._cache: typing.Dict[str, ReflectionLogEntry] = {}
        self._logger = get_logger(__name__)
        self._initialized = False

    async def on_initialize(self) -> None:
        """初始化回调"""
        await self._load_existing_logs()
        self._initialized = True
        self._logger.info("GrowthLogManager 初始化完成")

    async def on_start(self) -> None:
        """启动回调"""
        self._logger.info("GrowthLogManager 启动")

    async def on_stop(self) -> None:
        """停止回调"""
        await self._save_all_logs()
        self._logger.info("GrowthLogManager 停止")

    async def _load_existing_logs(self) -> None:
        """加载现有日志"""
        if not self.memory_manager:
            return

        try:
            # 从记忆管理器加载反思日志
            memories = await self.memory_manager.search_memories(memory_type="reflection", limit=self.max_logs)

            for memory in memories:
                entry = self._parse_memory_to_entry(memory)
                if entry:
                    self._add_to_cache(entry)

            self._logger.info("加载了 %s 条反思日志", len(self._cache))
        except Exception as e:
            self._logger.error("加载反思日志失败: %s", e)

    def _parse_memory_to_entry(self, memory) -> Optional[ReflectionLogEntry]:
        """将记忆转换为反思日志条目

        Args:
            memory: 记忆对象

        Returns:
            反思日志条目，如果解析失败则返回 None
        """
        try:
            # 假设记忆有 metadata 字段存储反思日志数据
            if hasattr(memory, "metadata") and memory.metadata:
                entry_data = memory.metadata.get("reflection_log")
                if entry_data:
                    entry = ReflectionLogEntry.from_dict(entry_data)
                    entry.memory_id = memory.id
                    return entry
        except Exception as e:
            self._logger.error("解析记忆到反思日志失败: %s", e)
        return None

    def _add_to_cache(self, entry: ReflectionLogEntry) -> None:
        """添加到缓存

        Args:
            entry: 反思日志条目
        """
        self._cache[entry.id] = entry

        # 如果缓存超过最大数量，移除最旧的
        if len(self._cache) > self.max_logs:
            oldest_id = min(self._cache.keys(), key=lambda x: self._cache[x].timestamp)
            del self._cache[oldest_id]

    async def _save_all_logs(self) -> None:
        """保存所有日志"""
        if not self.memory_manager:
            return

        try:
            for entry in self._cache.values():
                await self._save_entry(entry)
            self._logger.info("保存了 %s 条反思日志", len(self._cache))
        except Exception as e:
            self._logger.error("保存反思日志失败: %s", e)

    async def _save_entry(self, entry: ReflectionLogEntry) -> None:
        """保存单个条目

        Args:
            entry: 反思日志条目
        """
        if not self.memory_manager:
            return

        try:
            # 将反思日志存储为记忆
            memory_data = {
                "type": "reflection",
                "content": entry.content,
                "metadata": {"reflection_log": entry.to_dict()},
            }

            if entry.memory_id:
                # 更新现有记忆
                await self.memory_manager.update_memory(entry.memory_id, memory_data)
            else:
                # 创建新记忆
                memory_id = await self.memory_manager.remember(
                    content=entry.content, memory_type="reflection", metadata=memory_data["metadata"]
                )
                entry.memory_id = memory_id
        except Exception as e:
            self._logger.error("保存反思日志条目失败: %s", e)

    async def _handle_generate_request(self, data: typing.Dict[str, typing.Any]) -> typing.Dict[str, typing.Any]:
        """处理生成请求

        Args:
            data: 请求数据

        Returns:
            响应数据
        """
        try:
            entry = await self.generate_log(
                type=ReflectionType(data.get("type", "performance")),
                title=data.get("title", ""),
                content=data.get("content", ""),
                context=data.get("context", {}),
                insights=data.get("insights", []),
                action_items=data.get("action_items", []),
                confidence=data.get("confidence", 0.0),
            )
            return {"success": True, "entry": entry.to_dict()}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _handle_validation_request(self, data: typing.Dict[str, typing.Any]) -> typing.Dict[str, typing.Any]:
        """处理验证请求

        Args:
            data: 请求数据

        Returns:
            响应数据
        """
        try:
            entry_id = data.get("entry_id")
            validation_result = data.get("validation_result", {})

            success = await self.validate_application(entry_id, validation_result)
            return {"success": success}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _handle_apply_request(self, data: typing.Dict[str, typing.Any]) -> typing.Dict[str, typing.Any]:
        """处理应用请求

        Args:
            data: 请求数据

        Returns:
            响应数据
        """
        try:
            entry_id = data.get("entry_id")
            success = await self.mark_as_applied(entry_id)
            return {"success": success}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def generate_log(
        self,
        type: ReflectionType,
        title: str,
        content: str,
        context: typing.Dict[str, typing.Any] = None,
        insights: typing.List[str] = None,
        action_items: typing.List[str] = None,
        confidence: float = 0.0,
    ) -> ReflectionLogEntry:
        """生成反思日志

        Args:
            type: 反思类型
            title: 标题
            content: 内容
            context: 上下文
            insights: 洞察
            action_items: 行动项
            confidence: 置信度

        Returns:
            反思日志条目
        """
        entry = ReflectionLogEntry(
            type=type,
            title=title,
            content=content,
            context=context or {},
            insights=insights or [],
            action_items=action_items or [],
            confidence=confidence,
        )

        self._add_to_cache(entry)
        await self._save_entry(entry)

        self._logger.info("生成反思日志: %s - %s", entry.id, title)
        return entry

    def read_logs(
        self, type: Optional[ReflectionType] = None, status: Optional[ReflectionLogStatus] = None, limit: int = 50
    ) -> typing.List[ReflectionLogEntry]:
        """读取反思日志

        Args:
            type: 反思类型过滤
            status: 状态过滤
            limit: 返回数量限制

        Returns:
            反思日志列表
        """
        entries = list(self._cache.values())

        if type:
            entries = [e for e in entries if e.type == type]

        if status:
            entries = [e for e in entries if e.status == status]

        # 按时间戳降序排序
        entries.sort(key=lambda x: x.timestamp, reverse=True)

        return entries[:limit]

    async def read_for_context(self, limit: int = 10) -> str:
        """读取用于上下文的反思日志

        Args:
            limit: 返回数量限制

        Returns:
            格式化的反思日志文本
        """
        entries = self.read_logs(status=ReflectionLogStatus.VALIDATED, limit=limit)

        if not entries:
            return ""

        context_parts = ["## 反思日志\n"]
        for entry in entries:
            context_parts.append(f"### {entry.title}")
            context_parts.append(f"**类型**: {entry.type.value}")
            context_parts.append(f"**置信度**: {entry.confidence:.2f}")
            context_parts.append(f"**内容**: {entry.content}")

            if entry.insights:
                context_parts.append("**洞察**:")
                for insight in entry.insights:
                    context_parts.append(f"- {insight}")

            if entry.action_items:
                context_parts.append("**行动项**:")
                for item in entry.action_items:
                    context_parts.append(f"- {item}")

            context_parts.append("")

        return "\n".join(context_parts)

    async def mark_as_applied(self, entry_id: str) -> bool:
        """标记为已应用

        Args:
            entry_id: 条目ID

        Returns:
            是否成功
        """
        if entry_id not in self._cache:
            return False

        entry = self._cache[entry_id]
        entry.status = ReflectionLogStatus.APPLIED
        entry.applied_at = time.time()

        await self._save_entry(entry)
        self._logger.info("标记反思日志为已应用: %s", entry_id)
        return True

    async def validate_application(self, entry_id: str, validation_result: typing.Dict[str, typing.Any]) -> bool:
        """验证应用结果

        Args:
            entry_id: 条目ID
            validation_result: 验证结果

        Returns:
            是否成功
        """
        if entry_id not in self._cache:
            return False

        entry = self._cache[entry_id]
        entry.status = ReflectionLogStatus.VALIDATED
        entry.validated_at = time.time()
        entry.context["validation_result"] = validation_result

        await self._save_entry(entry)
        self._logger.info("验证反思日志应用: %s", entry_id)
        return True

    async def archive_old_logs(self, max_age_days: float = 30.0) -> int:
        """归档旧日志

        Args:
            max_age_days: 最大保留天数

        Returns:
            归档的日志数量
        """
        cutoff_time = time.time() - (max_age_days * 24 * 3600)
        archived_count = 0

        for entry in list(self._cache.values()):
            if entry.timestamp < cutoff_time and entry.status != ReflectionLogStatus.ARCHIVED:
                entry.status = ReflectionLogStatus.ARCHIVED
                await self._save_entry(entry)
                archived_count += 1

        if archived_count > 0:
            self._logger.info("归档了 %s 条旧反思日志", archived_count)

        return archived_count

    async def get_statistics(self) -> typing.Dict[str, typing.Any]:
        """获取统计信息

        Returns:
            统计信息字典
        """
        entries = list(self._cache.values())

        stats = {
            "total": len(entries),
            "by_type": {},
            "by_status": {},
            "average_confidence": 0.0,
        }

        for entry in entries:
            # 按类型统计
            type_name = entry.type.value
            stats["by_type"][type_name] = stats["by_type"].get(type_name, 0) + 1

            # 按状态统计
            status_name = entry.status.value
            stats["by_status"][status_name] = stats["by_status"].get(status_name, 0) + 1

        # 计算平均置信度
        if entries:
            total_confidence = sum(entry.confidence for entry in entries)
            stats["average_confidence"] = total_confidence / len(entries)

        return stats

    def get_pending_logs(self, limit: int = 50) -> typing.List[ReflectionLogEntry]:
        """获取待处理的日志

        Args:
            limit: 返回数量限制

        Returns:
            待处理的日志列表
        """
        return self.read_logs(status=ReflectionLogStatus.PENDING, limit=limit)

    def get_validated_logs(self, limit: int = 50) -> typing.List[ReflectionLogEntry]:
        """获取已验证的日志

        Args:
            limit: 返回数量限制

        Returns:
            已验证的日志列表
        """
        return self.read_logs(status=ReflectionLogStatus.VALIDATED, limit=limit)
