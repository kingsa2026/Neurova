"""
MemCore — 神经感知记忆核心模块

作为记忆检索系统的神经感知层，负责：
- 神经元节点初始化 (init_memory_modules, init_moe_router)
- 记忆检索 (retrieve_memories, moe_retrieve)
- 对话记忆保存 (save_conversation_memory)
- 对话历史更新 (update_history)
- 记忆温度更新 (update_memory_temperature)
- 记忆统计 (get_memory_stats)

神经隐喻:
- 神经感知层: 像大脑皮层一样整合来自不同脑区的信息
- 神经元节点: MoE路由器和专家检索器作为功能特化的处理单元
- 突触连接: 向量门控网络实现选择性激活
- 树突输入: L0-L3检索路径进行渐进式信号处理
- 轴突输出: 结果处理器生成最终注入文本

设计原则：
- 深度模块：小接口，深实现（像神经元的复杂内部结构）
- 依赖注入：通过 agent_ref 访问 Agent 实例的属性（像神经元的输入连接）
- 可独立测试：不依赖 Agent 类的完整初始化（像离体神经元实验）
- 封装认知层：Agent 只需导入 MemCore，无需直接导入认知层模块
"""

import logging
import asyncio
from datetime import datetime, UTC
from pathlib import Path
from typing import List, Dict, Optional, Any

logger = logging.getLogger(__name__)


class Memory:
    """记忆数据模型（pyc骨架恢复占位）"""
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class Conversation:
    """对话数据模型（pyc骨架恢复占位）"""
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class MemCore:
    """深度记忆核心模块

    封装 Agent 的所有记忆相关操作，提供小接口、深实现。

    通过 agent_ref 访问 Agent 实例的：
    - config, memory_manager, storage, temperature_engine
    - recall_engine, attachment_manager, growth_log_manager
    - question_queue_manager, conflict_detector, version_control
    - proactive_question_manager, working_memory
    - conversation_buffer, buffer_module, session_manager
    - evolution, tool_memory
    """

    def __init__(self, agent_ref):
        self._agent = agent_ref

    # ---- 属性代理（方便内部访问） ----
    @property
    def config(self):
        return self._agent.config

    @property
    def memory_manager(self):
        return getattr(self._agent, 'memory_manager', None)

    @memory_manager.setter
    def memory_manager(self, value):
        self._agent.memory_manager = value

    @property
    def storage(self):
        return getattr(self._agent, 'storage', None)

    @storage.setter
    def storage(self, value):
        self._agent.storage = value

    @property
    def temperature_engine(self):
        return getattr(self._agent, 'temperature_engine', None)

    @temperature_engine.setter
    def temperature_engine(self, value):
        self._agent.temperature_engine = value

    @property
    def recall_engine(self):
        return getattr(self._agent, 'recall_engine', None)

    @recall_engine.setter
    def recall_engine(self, value):
        self._agent.recall_engine = value

    @property
    def working_memory(self):
        return getattr(self._agent, 'working_memory', None)

    @working_memory.setter
    def working_memory(self, value):
        self._agent.working_memory = value

    @property
    def conversation_buffer(self):
        return getattr(self._agent, 'conversation_buffer', None)

    @conversation_buffer.setter
    def conversation_buffer(self, value):
        self._agent.conversation_buffer = value

    @property
    def buffer_module(self):
        return getattr(self._agent, 'buffer_module', None)

    @buffer_module.setter
    def buffer_module(self, value):
        self._agent.buffer_module = value

    @property
    def conversation_history(self):
        return getattr(self._agent, 'conversation_history', [])

    @conversation_history.setter
    def conversation_history(self, value):
        self._agent.conversation_history = value

    @property
    def evolution(self):
        return getattr(self._agent, 'evolution', None)

    @property
    def session_manager(self):
        return getattr(self._agent, 'session_manager', None)

    @property
    def growth_log_manager(self):
        return getattr(self._agent, 'growth_log_manager', None)

    @growth_log_manager.setter
    def growth_log_manager(self, value):
        self._agent.growth_log_manager = value

    @property
    def question_queue_manager(self):
        return getattr(self._agent, 'question_queue_manager', None)

    @question_queue_manager.setter
    def question_queue_manager(self, value):
        self._agent.question_queue_manager = value

    @property
    def tool_memory(self):
        return getattr(self._agent, 'tool_memory', None)

    @tool_memory.setter
    def tool_memory(self, value):
        self._agent.tool_memory = value

    @property
    def muscle_memory(self):
        return getattr(self._agent, 'muscle_memory', None)

    @muscle_memory.setter
    def muscle_memory(self, value):
        self._agent.muscle_memory = value

    @property
    def attachment_manager(self):
        return getattr(self._agent, 'attachment_manager', None)

    @attachment_manager.setter
    def attachment_manager(self, value):
        self._agent.attachment_manager = value

    @property
    def moe_router(self):
        return getattr(self._agent, '_moe_router', None)

    # ══════════════════════════════════════════════════════════════
    # 初始化
    # ══════════════════════════════════════════════════════════════

    def init_memory_modules(self, neuser_id: str = "default", user_id: str = "default"):
        """初始化记忆系统模块

        Args:
            neuser_id: Neurova系统用户ID（三级隔离第2级）
            user_id: 对话用户ID（三级隔离第3级）
        """
        from neurova.cognitive_layers.memory_layer.manager import MemoryManager
        from neurova.cognitive_layers.memory_layer.temperature import TemperatureEngine
        from neurova.cognitive_layers.memory_layer.working_memory import WorkingMemoryAugmenter
        from neurova.cognitive_layers.memory_layer.conversation_buffer import ConversationMemoryBuffer, MemoryWriteQueue
        from neurova.cognitive_layers.memory_layer.modules.buffer_module import BufferModule
        from neurova.cognitive_layers.meta_cognition_layer.growth_log import GrowthLogManager
        from neurova.cognitive_layers.meta_cognition_layer.question_queue import QuestionQueueManager

        db_path = self.config.db_path

        # 确保数据库目录存在
        db_dir = Path(db_path).parent
        db_dir.mkdir(parents=True, exist_ok=True)

        try:
            # 创建MemoryManager时传递三级隔离参数
            self.memory_manager = MemoryManager(
                db_path,
                agent_id=self.config.agent_id,
                neuser_id=neuser_id,
                user_id=user_id,
            )
            self.storage = getattr(self.memory_manager, 'storage', None)
            self.temperature_engine = TemperatureEngine()

            # Neurova 统一记忆检索引擎（多维融合 + 意图钻取）
            if self.storage:
                from neurova.cognitive_layers.memory_layer.neurova_recall import NeurovaRecallEngine
                self.recall_engine = NeurovaRecallEngine(
                    storage=self.storage,
                    temperature_engine=self.temperature_engine,
                    emotion_analyzer=None,
                    tkg=None,
                    vector_search=None,
                    config={
                        "enable_temperature": True,
                        "enable_category": True,
                        "enable_graph": True,
                        "enable_emotion": True,
                        "enable_drill": True,
                        "drill_max_depth": 3,
                        "max_seeds": 10,
                        "max_total": 20,
                        "relevance_threshold": 0.15,
                    }
                )
                logger.info(f"Agent {self.config.name}: NeurovaRecallEngine（多维融合+钻取）已启用")

            # 初始化附件管理器（Agent隔离 + 用户隔离）
            from neurova.cognitive_layers.memory_layer.attachment_manager import AttachmentManager
            self._agent.attachment_manager = AttachmentManager.from_agent_config(
                agent_id=self.config.agent_id,
                agent_workspace_path=str(self.config.workspace_path),
                db_path=db_path,
            )
            logger.info(f"AttachmentManager 初始化成功: {self.config.attachment_dir}")

            # 初始化反思日志管理器
            self._agent.growth_log_manager = GrowthLogManager(
                memory_manager=self.memory_manager,
                max_logs=1000,
            )
            logger.info(f"Agent {self.config.name}: GrowthLogManager（反思日志）已启用")

            # 初始化问题队列管理器
            self._agent.question_queue_manager = QuestionQueueManager(
                memory_manager=self.memory_manager,
                default_cooldown=300.0,
                max_questions=100,
            )
            logger.info(f"Agent {self.config.name}: QuestionQueueManager（问题队列）已启用")

            # 初始化工作记忆
            self.working_memory = WorkingMemoryAugmenter(
                config={
                    "max_items": 10,
                    "memory_manager": self.memory_manager,
                }
            )
            logger.info(f"Agent {self.config.name}: WorkingMemoryAugmenter（工作记忆）已启用")

            # 初始化对话缓冲区
            self.conversation_buffer = ConversationMemoryBuffer(
                turn_limit=1000,  # 增大默认轮次限制
            )
            logger.info(f"Agent {self.config.name}: ConversationMemoryBuffer（对话缓冲区）已启用")

            # 初始化缓冲模块
            self.buffer_module = BufferModule()
            # 将对话缓冲区和写入队列注入到缓冲模块
            self.buffer_module._buffer = self.conversation_buffer
            from neurova.cognitive_layers.memory_layer.conversation_buffer import MemoryWriteQueue
            self.buffer_module._write_queue = MemoryWriteQueue(
                self.storage,
                self.config.agent_id,
            ) if self.storage else None
            logger.info(f"Agent {self.config.name}: BufferModule（缓冲模块）已启用")

            # 初始化肌肉记忆
            from neurova.cognitive_layers.memory_layer.muscle_memory import MuscleMemory
            self._agent.muscle_memory = MuscleMemory(
                agent_id=self.config.agent_id,
            )
            logger.info(f"Agent {self.config.name}: MuscleMemory（肌肉记忆）已启用")

            # 初始化工具记忆集成
            from neurova.cognitive_layers.memory_layer.tool_memory_integration import ToolMemoryIntegration
            self._agent.tool_memory = ToolMemoryIntegration(
                memory_layer=self.memory_manager,
            )
            logger.info(f"Agent {self.config.name}: ToolMemoryIntegration（工具记忆）已启用")

            logger.info(f"记忆系统模块初始化成功: agent_id={self.config.agent_id}, neuser_id={neuser_id}, user_id={user_id}")

        except Exception as e:
            import traceback
            logger.error(
                f"记忆系统模块初始化失败: {e}\n"
                f"完整调用栈:\n{traceback.format_exc()}"
            )
            raise  # 记忆模块是 Agent 核心依赖，无法降级

    def init_moe_router(self):
        """初始化 MoE 路由器"""
        try:
            from neurova.cognitive_layers.memory_layer.unified_vector_store import UnifiedVectorStore
            from neurova.cognitive_layers.memory_layer.moe_router import MoEMemoryRouter

            vector_store = UnifiedVectorStore()

            if self.storage:
                try:
                    memories = self.storage.get_recent_memories(limit=500)
                    if memories:
                        memory_items = []
                        for mem in memories:
                            memory_items.append({
                                'id': mem.get('id', ''),
                                'content': mem.get('content', ''),
                                'metadata': {
                                    'category': mem.get('category', 'unknown'),
                                    'lifecycle': mem.get('lifecycle', 'active'),
                                    'is_crystallized': mem.get('is_crystallized', False),
                                }
                            })
                        vector_store.index_memories(memory_items)
                        logger.info(f"MoE: 已索引 {len(memory_items)} 条记忆到向量存储")
                    else:
                        logger.info("MoE: 数据库中没有记忆，跳过索引")
                except Exception as e:
                    logger.warning(f"MoE: 加载记忆失败: {e}")

            experts = {
                "conversation_episodic": {
                    "name": "对话情景记忆",
                    "category": "conversation",
                    "lifecycle_stage": "active",
                    "centroid_text": "对话记忆、日常交流、聊天记录",
                },
                "factual_knowledge": {
                    "name": "事实知识",
                    "category": "fact",
                    "is_crystallized": True,
                    "centroid_text": "事实知识、常识、固化信息",
                },
                "tool_muscle": {
                    "name": "工具肌肉记忆",
                    "category": "tool_usage",
                    "centroid_text": "工具使用、命令执行、操作经验",
                },
                "experience_lesson": {
                    "name": "经验教训",
                    "category": "experience",
                    "centroid_text": "经验教训、最佳实践、失败案例",
                },
            }

            moe_router = MoEMemoryRouter(
                experts=experts,
                storage=self.storage,
                vector_store=vector_store,
            )

            self._agent._moe_router = moe_router
            logger.info("MoE 路由器初始化成功")

        except Exception as e:
            logger.error(f"MoE 路由器初始化失败: {e}")

    # ══════════════════════════════════════════════════════════════
    # 记忆检索
    # ══════════════════════════════════════════════════════════════

    def retrieve_memories(self, query: str, limit: int = 10) -> List[Dict]:
        """检索相关记忆

        Args:
            query: 查询文本
            limit: 返回结果数量限制

        Returns:
            相关记忆列表
        """
        if not self.memory_manager:
            return []

        try:
            # 使用记忆管理器检索
            memories = self.memory_manager.recall(
                query=query,
                limit=limit,
            )
            return memories or []
        except Exception as e:
            logger.warning(f"记忆检索失败: {e}")
            return []

    def moe_retrieve(self, query: str, limit: int = 10) -> List[Dict]:
        """MoE 路由检索

        优先使用 MoE 路由器，如果未初始化或检索失败则降级到普通检索。
        检索前自动刷新缓冲区，确保当前对话记忆可被检索。
        """
        # 检索前刷新缓冲区（断裂2修复）
        self.flush_before_retrieve()

        moe = self.moe_router
        if moe:
            try:
                results = asyncio.run(moe.retrieve(query, limit=limit))
                if results:
                    logger.debug(f"MoE 检索成功: {len(results)} 条结果")
                    return results
                else:
                    logger.debug("MoE 检索无结果，降级到普通检索")
            except Exception as e:
                logger.warning(f"MoE 检索失败: {e}，降级到普通检索")

        return self.retrieve_memories(query, limit=limit)

    def refresh_moe_index(self):
        """刷新 MoE 向量索引（断裂1修复）

        从 SQLite 重新加载最近记忆到向量存储，
        确保新写入的记忆对 MoE 向量路由可见。
        """
        moe = self.moe_router
        if not moe or not self.storage:
            return

        try:
            memories = self.storage.get_recent_memories(days=365, limit=500)
            if memories:
                memory_items = []
                for mem in memories:
                    memory_items.append({
                        'id': mem.get('id', ''),
                        'content': mem.get('content', ''),
                        'metadata': {
                            'category': mem.get('category', 'unknown'),
                            'lifecycle': mem.get('lifecycle', 'active'),
                            'is_crystallized': mem.get('is_crystallized', False),
                        }
                    })
                moe.vector_store.index_memories(memory_items)
                # 重新初始化质心
                moe.vector_store.initialize_centroids(moe.experts)
                logger.info(f"MoE 向量索引已刷新: {len(memory_items)} 条记忆")
        except Exception as e:
            logger.warning(f"MoE 向量索引刷新失败: {e}")

    def flush_before_retrieve(self):
        """检索前刷新缓冲区（断裂2修复）

        在 MoE 检索前，先将对话缓冲区中的未 flush 记忆写入 SQLite，
        确保当前对话中的记忆可被检索。
        """
        try:
            # 刷新对话缓冲区
            if self.conversation_buffer and self.conversation_buffer.is_full():
                self.conversation_buffer.flush_to_long_term_memory()
                logger.debug("对话缓冲区已 flush")

            # 刷新写入队列
            if self.buffer_module and hasattr(self.buffer_module, '_write_queue'):
                queue = self.buffer_module._write_queue
                if queue and hasattr(queue, 'flush_to_storage'):
                    result = queue.flush_to_storage()
                    if result.get('written', 0) > 0:
                        logger.debug(f"写入队列已 flush: {result['written']} 条")
        except Exception as e:
            logger.warning(f"检索前 flush 失败: {e}")

    # ══════════════════════════════════════════════════════════════
    # 对话记忆保存
    # ══════════════════════════════════════════════════════════════

    def save_conversation_memory(self, user_input: str, agent_response: str, metadata: Dict = None):
        """保存对话记忆

        Args:
            user_input: 用户输入
            agent_response: Agent 回复
            metadata: 元数据
        """
        if not self.conversation_buffer:
            return

        try:
            # 添加到对话缓冲区
            self.conversation_buffer.add_user_message(user_input)
            self.conversation_buffer.add_agent_message(agent_response)

            # 如果缓冲区满了，刷新到长期记忆
            if self.conversation_buffer.is_full():
                self.conversation_buffer.flush_to_long_term_memory()

            logger.debug(f"对话记忆已保存: user_input={user_input[:50]}...")
        except Exception as e:
            logger.warning(f"对话记忆保存失败: {e}")

    # ══════════════════════════════════════════════════════════════
    # 对话历史更新
    # ══════════════════════════════════════════════════════════════

    def update_history(self, user_input: str, agent_response: str):
        """更新对话历史

        Args:
            user_input: 用户输入
            agent_response: Agent 回复
        """
        try:
            # 添加到对话历史
            self.conversation_history.append({
                'role': 'user',
                'content': user_input,
                'timestamp': datetime.now(UTC).isoformat(),
            })
            self.conversation_history.append({
                'role': 'assistant',
                'content': agent_response,
                'timestamp': datetime.now(UTC).isoformat(),
            })

            # 限制历史长度
            max_history = 100
            if len(self.conversation_history) > max_history:
                self.conversation_history = self.conversation_history[-max_history:]

            logger.debug(f"对话历史已更新: 长度={len(self.conversation_history)}")
        except Exception as e:
            logger.warning(f"对话历史更新失败: {e}")

    # ══════════════════════════════════════════════════════════════
    # Session 文件保存（B5 闭环修复：GAP-3）
    # ══════════════════════════════════════════════════════════════

    def save_to_session(
        self,
        user_input: str,
        reply: str,
        session_id: Optional[str] = None,
        metadata: Optional[Dict] = None,
        assistant_metadata: Optional[Dict] = None,
    ) -> str:
        """保存对话到 session 文件，委托给 SessionManager.add_message()。

        GAP-3 修复：此前 agent_core._save_to_session() 调用
        self.memory_agent.save_to_session() 但 MemCore 没有此方法，
        导致每次调用 AttributeError 被 try/except 静默吞掉，
        session 文件从不写入。

        Args:
            user_input: 用户输入
            reply: Agent 回复
            session_id: 会话 ID（None 时自动生成）
            metadata: 用户消息元数据
            assistant_metadata: 助理消息元数据

        Returns:
            session 文件标识符: "agent_id_session_id_date"
        """
        sm = self.session_manager
        if not sm:
            logger.warning("SessionManager 不可用，跳过 session 保存")
            return session_id or ""

        # 自动生成 session_id
        if not session_id:
            from uuid import uuid4
            session_id = f"auto-{uuid4().hex[:12]}"

        agent_id = getattr(self.config, 'agent_id', 'unknown') if self.config else 'unknown'

        return sm.add_message(
            agent_id=agent_id,
            session_id=session_id,
            user_content=user_input,
            assistant_content=reply,
            metadata=metadata,
        )

    # ══════════════════════════════════════════════════════════════
    # 记忆温度更新
    # ══════════════════════════════════════════════════════════════

    def update_memory_temperature(self, memory_id: str, interaction_type: str = "view"):
        """更新记忆温度

        Args:
            memory_id: 记忆ID
            interaction_type: 交互类型（view, use, recall）
        """
        if not self.temperature_engine:
            return

        try:
            # 更新温度
            self.temperature_engine.update_temperature(
                memory_id=memory_id,
                interaction_type=interaction_type,
            )
            logger.debug(f"记忆温度已更新: memory_id={memory_id}, type={interaction_type}")
        except Exception as e:
            logger.warning(f"记忆温度更新失败: {e}")

    # ══════════════════════════════════════════════════════════════
    # 记忆统计
    # ══════════════════════════════════════════════════════════════

    def get_memory_stats(self) -> Dict[str, Any]:
        """获取记忆统计信息

        Returns:
            统计信息字典
        """
        stats = {
            'memory_manager_available': self.memory_manager is not None,
            'storage_available': self.storage is not None,
            'temperature_engine_available': self.temperature_engine is not None,
            'recall_engine_available': self.recall_engine is not None,
            'working_memory_available': self.working_memory is not None,
            'conversation_buffer_available': self.conversation_buffer is not None,
            'buffer_module_available': self.buffer_module is not None,
            'conversation_history_length': len(self.conversation_history),
            'moe_router_available': self.moe_router is not None,
        }

        # 添加记忆管理器统计
        if self.memory_manager:
            try:
                memory_stats = self.memory_manager.get_stats()
                stats.update(memory_stats)
            except Exception as e:
                logger.warning(f"获取记忆管理器统计失败: {e}")

        return stats

