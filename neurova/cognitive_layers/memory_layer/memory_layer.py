"""
AgentMemoryLayer - Agent独立的记忆层

每个Agent拥有独立的记忆数据库和缓存。
线程安全，支持多Agent并发访问。
"""

import logging
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class AgentMemoryLayer:
    """
    Agent独立的记忆层

    每个Agent拥有独立的记忆数据库和缓存，提供完整的记忆管理功能。
    """

    def __init__(
        self,
        agent_id: str,
        db_path: str,
        neuser_id: str = "default",
        user_id: str = "default",
        config: Optional[Dict[str, Any]] = None,
    ):
        """
        初始化Agent记忆层

        Args:
            agent_id: Agent ID
            db_path: 数据库路径
            neuser_id: Neurova系统用户ID（三级隔离第2级）
            user_id: 对话用户ID（三级隔离第3级）
            config: 配置字典
        """
        self._agent_id = agent_id
        self._db_path = db_path
        self._neuser_id = neuser_id
        self._user_id = user_id
        self._config = config or {}
        self._lock = threading.RLock()

        # 记忆管理器（延迟初始化）
        self._memory_manager = None
        self._storage = None
        self._temperature_engine = None
        self._recall_engine = None
        self._working_memory = None
        self._conversation_buffer = None
        self._buffer_module = None

        # 初始化状态
        self._initialized = False
        self._shutdown = False

        logger.info("AgentMemoryLayer created: agent_id=%s, neuser_id=%s, user_id=%s", agent_id, neuser_id, user_id)

    @property
    def agent_id(self) -> str:
        """Agent ID"""
        return self._agent_id

    @property
    def db_path(self) -> str:
        """数据库路径"""
        return self._db_path

    @property
    def neuser_id(self) -> str:
        """Neurova系统用户ID"""
        return self._neuser_id

    @property
    def user_id(self) -> str:
        """对话用户ID"""
        return self._user_id

    @property
    def memory_manager(self):
        """记忆管理器（延迟初始化）"""
        if not self._initialized:
            self._init_memory_manager()
        return self._memory_manager

    @property
    def storage(self):
        """存储后端"""
        if not self._initialized:
            self._init_memory_manager()
        return self._storage

    @property
    def temperature_engine(self):
        """温度引擎"""
        if not self._initialized:
            self._init_memory_manager()
        return self._temperature_engine

    @property
    def recall_engine(self):
        """检索引擎"""
        if not self._initialized:
            self._init_memory_manager()
        return self._recall_engine

    @property
    def working_memory(self):
        """工作记忆"""
        if not self._initialized:
            self._init_memory_manager()
        return self._working_memory

    @property
    def conversation_buffer(self):
        """对话缓冲区"""
        if not self._initialized:
            self._init_memory_manager()
        return self._conversation_buffer

    @property
    def buffer_module(self):
        """缓冲模块"""
        if not self._initialized:
            self._init_memory_manager()
        return self._buffer_module

    def _init_memory_manager(self):
        """初始化记忆管理器"""
        with self._lock:
            if self._initialized:
                return

            try:
                from neurova.cognitive_layers.memory_layer.conversation_buffer import (
                    ConversationMemoryBuffer,
                    MemoryWriteQueue,
                )
                from neurova.cognitive_layers.memory_layer.manager import MemoryManager
                from neurova.cognitive_layers.memory_layer.modules.buffer_module import BufferModule
                from neurova.cognitive_layers.memory_layer.temperature import TemperatureEngine
                from neurova.cognitive_layers.memory_layer.working_memory import WorkingMemoryAugmenter

                # 确保数据库目录存在
                db_dir = Path(self._db_path).parent
                db_dir.mkdir(parents=True, exist_ok=True)

                # 创建MemoryManager
                self._memory_manager = MemoryManager(
                    self._db_path,
                    agent_id=self._agent_id,
                    neuser_id=self._neuser_id,
                    user_id=self._user_id,
                )

                # 获取存储后端
                self._storage = getattr(self._memory_manager, "storage", None)

                # 初始化温度引擎
                self._temperature_engine = TemperatureEngine()

                # 初始化检索引擎
                if self._storage:
                    from neurova.cognitive_layers.memory_layer.neurova_recall import NeurovaRecallEngine

                    self._recall_engine = NeurovaRecallEngine(
                        storage=self._storage,
                        temperature_engine=self._temperature_engine,
                        emotion_analyzer=None,
                        tkg=None,
                        vector_search=None,
                        config=self._config.get(
                            "recall_config",
                            {
                                "enable_temperature": True,
                                "enable_category": True,
                                "enable_graph": True,
                                "enable_emotion": True,
                                "enable_drill": True,
                                "drill_max_depth": 3,
                                "max_seeds": 10,
                                "max_total": 20,
                                "relevance_threshold": 0.15,
                            },
                        ),
                    )

                # 初始化工作记忆
                self._working_memory = WorkingMemoryAugmenter(
                    config={
                        "max_items": self._config.get("working_memory_max_items", 10),
                        "memory_manager": self._memory_manager,
                    }
                )

                # 初始化对话缓冲区
                self._conversation_buffer = ConversationMemoryBuffer(
                    turn_limit=self._config.get("conversation_turn_limit", 1000),
                )

                # 初始化缓冲模块
                self._buffer_module = BufferModule()
                self._buffer_module._buffer = self._conversation_buffer
                if self._storage:
                    self._buffer_module._write_queue = MemoryWriteQueue(
                        self._storage,
                        self._agent_id,
                    )

                self._initialized = True
                logger.info("AgentMemoryLayer initialized: agent_id=%s", self._agent_id)

            except Exception as e:
                import traceback

                logger.error("AgentMemoryLayer initialization failed: %s\n" f"Traceback:\n%s", e, traceback.format_exc())
                raise

    def remember(self, content: str, category: str = "general", metadata: Optional[Dict] = None) -> str:
        """
        存储记忆

        Args:
            content: 记忆内容
            category: 记忆类别
            metadata: 元数据

        Returns:
            记忆ID
        """
        if not self.memory_manager:
            raise RuntimeError("Memory manager not initialized")

        try:
            memory_id = self.memory_manager.remember(
                content=content,
                category=category,
                metadata=metadata or {},
                agent_id=self._agent_id,
                neuser_id=self._neuser_id,
                user_id=self._user_id,
            )
            logger.debug("Memory stored: %s...", memory_id[:8])
            return memory_id
        except Exception as e:
            logger.error("Failed to store memory: %s", e)
            raise

    def recall(self, query: str, limit: int = 10, **kwargs) -> List[Dict]:
        """
        检索相关记忆

        Args:
            query: 查询文本
            limit: 返回结果数量限制
            **kwargs: 其他参数

        Returns:
            相关记忆列表
        """
        if not self.memory_manager:
            return []

        try:
            memories = self.memory_manager.recall(
                query=query,
                limit=limit,
                agent_id=self._agent_id,
                neuser_id=self._neuser_id,
                user_id=self._user_id,
                **kwargs,
            )
            return memories or []
        except Exception as e:
            logger.warning("Memory recall failed: %s", e)
            return []

    def get_memory(self, memory_id: str) -> Optional[Dict]:
        """
        获取单个记忆

        Args:
            memory_id: 记忆ID

        Returns:
            记忆数据，如果不存在返回None
        """
        if not self.storage:
            return None

        try:
            return self.storage.get_memory(memory_id)
        except Exception as e:
            logger.warning("Failed to get memory %s...: %s", memory_id[:8], e)
            return None

    def update_memory(self, memory_id: str, updates: Dict[str, Any]) -> bool:
        """
        更新记忆

        Args:
            memory_id: 记忆ID
            updates: 更新字段

        Returns:
            是否更新成功
        """
        if not self.storage:
            return False

        try:
            success = self.storage.update_memory(memory_id, updates)
            if success:
                logger.debug("Memory updated: %s...", memory_id[:8])
            return success
        except Exception as e:
            logger.error("Failed to update memory %s...: %s", memory_id[:8], e)
            return False

    def delete_memory(self, memory_id: str) -> bool:
        """
        删除记忆

        Args:
            memory_id: 记忆ID

        Returns:
            是否删除成功
        """
        if not self.storage:
            return False

        try:
            success = self.storage.delete_memory(memory_id)
            if success:
                logger.debug("Memory deleted: %s...", memory_id[:8])
            return success
        except Exception as e:
            logger.error("Failed to delete memory %s...: %s", memory_id[:8], e)
            return False

    def consolidate(self, strategy: str = "default") -> Dict[str, Any]:
        """
        整合记忆

        Args:
            strategy: 整合策略

        Returns:
            整合结果统计
        """
        if not self.memory_manager:
            return {"error": "Memory manager not initialized"}

        try:
            result = self.memory_manager.consolidate(
                agent_id=self._agent_id,
                neuser_id=self._neuser_id,
                user_id=self._user_id,
                strategy=strategy,
            )
            logger.info("Memory consolidation completed: %s", result)
            return result
        except Exception as e:
            logger.error("Memory consolidation failed: %s", e)
            return {"error": str(e)}

    def run_decay_cycle(self) -> Dict[str, Any]:
        """
        运行温度衰减周期

        Returns:
            衰减结果统计
        """
        if not self.temperature_engine:
            return {"error": "Temperature engine not initialized"}

        try:
            result = self.temperature_engine.run_decay_cycle()
            logger.debug("Decay cycle completed: %s", result)
            return result
        except Exception as e:
            logger.error("Decay cycle failed: %s", e)
            return {"error": str(e)}

    def get_stats(self) -> Dict[str, Any]:
        """
        获取记忆统计信息

        Returns:
            统计信息字典
        """
        stats = {
            "agent_id": self._agent_id,
            "neuser_id": self._neuser_id,
            "user_id": self._user_id,
            "initialized": self._initialized,
            "shutdown": self._shutdown,
            "memory_manager_available": self._memory_manager is not None,
            "storage_available": self._storage is not None,
            "temperature_engine_available": self._temperature_engine is not None,
            "recall_engine_available": self._recall_engine is not None,
            "working_memory_available": self._working_memory is not None,
            "conversation_buffer_available": self._conversation_buffer is not None,
            "buffer_module_available": self._buffer_module is not None,
        }

        # 添加记忆管理器统计
        if self._memory_manager:
            try:
                memory_stats = self._memory_manager.get_stats()
                stats.update(memory_stats)
            except Exception as e:
                logger.warning("Failed to get memory manager stats: %s", e)

        return stats

    def clear_all_memories(self) -> Dict[str, Any]:
        """
        清除所有记忆

        Returns:
            清除结果统计
        """
        if not self.storage:
            return {"error": "Storage not initialized"}

        try:
            # 获取所有记忆
            all_memories = self.storage.get_recent_memories(days=365 * 100, limit=10000)
            deleted_count = 0

            for memory in all_memories:
                memory_id = memory.get("id")
                if memory_id:
                    try:
                        self.storage.delete_memory(memory_id)
                        deleted_count += 1
                    except Exception as e:
                        logger.warning("Failed to delete memory %s...: %s", memory_id[:8], e)

            logger.info("Cleared %s memories for agent %s", deleted_count, self._agent_id)
            return {"deleted_count": deleted_count}
        except Exception as e:
            logger.error("Failed to clear memories: %s", e)
            return {"error": str(e)}

    def shutdown(self):
        """关闭记忆层"""
        with self._lock:
            if self._shutdown:
                return

            self._shutdown = True

            try:
                # 关闭缓冲模块
                if self._buffer_module:
                    if hasattr(self._buffer_module, "shutdown"):
                        self._buffer_module.shutdown()

                # 关闭工作记忆
                if self._working_memory:
                    if hasattr(self._working_memory, "shutdown"):
                        self._working_memory.shutdown()

                # 关闭温度引擎
                if self._temperature_engine:
                    if hasattr(self._temperature_engine, "shutdown"):
                        self._temperature_engine.shutdown()

                # 关闭检索引擎
                if self._recall_engine:
                    if hasattr(self._recall_engine, "shutdown"):
                        self._recall_engine.shutdown()

                # 关闭记忆管理器
                if self._memory_manager:
                    if hasattr(self._memory_manager, "shutdown"):
                        self._memory_manager.shutdown()

                logger.info("AgentMemoryLayer shutdown: agent_id=%s", self._agent_id)

            except Exception as e:
                logger.error("Error during shutdown: %s", e)

    def __repr__(self) -> str:
        return f"AgentMemoryLayer(agent_id={self._agent_id}, neuser_id={self._neuser_id}, user_id={self._user_id})"

    def __del__(self):
        """析构函数，确保资源释放"""
        if not self._shutdown:
            self.shutdown()


# 全局单例管理
_agent_memory_layers: Dict[str, AgentMemoryLayer] = {}
_layers_lock = threading.Lock()


def get_agent_memory_layer(
    agent_id: str,
    db_path: str,
    neuser_id: str = "default",
    user_id: str = "default",
    config: Optional[Dict[str, Any]] = None,
) -> AgentMemoryLayer:
    """
    获取Agent记忆层单例

    Args:
        agent_id: Agent ID
        db_path: 数据库路径
        neuser_id: Neurova系统用户ID
        user_id: 对话用户ID
        config: 配置字典

    Returns:
        AgentMemoryLayer实例
    """
    key = f"{agent_id}:{neuser_id}:{user_id}"

    with _layers_lock:
        if key not in _agent_memory_layers:
            _agent_memory_layers[key] = AgentMemoryLayer(
                agent_id=agent_id,
                db_path=db_path,
                neuser_id=neuser_id,
                user_id=user_id,
                config=config,
            )
        return _agent_memory_layers[key]


def reset_agent_memory_layer(agent_id: str, neuser_id: str = "default", user_id: str = "default") -> None:
    """
    重置Agent记忆层（用于测试）

    Args:
        agent_id: Agent ID
        neuser_id: Neurova系统用户ID
        user_id: 对话用户ID
    """
    key = f"{agent_id}:{neuser_id}:{user_id}"

    with _layers_lock:
        if key in _agent_memory_layers:
            layer = _agent_memory_layers.pop(key)
            layer.shutdown()


def reset_all_agent_memory_layers() -> None:
    """重置所有Agent记忆层（用于测试）"""
    with _layers_lock:
        for layer in _agent_memory_layers.values():
            layer.shutdown()
        _agent_memory_layers.clear()
