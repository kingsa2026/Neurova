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

import asyncio
import concurrent.futures
import hashlib
import json
import time
from neurova.core.logger import get_logger
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
import threading
from threading import RLock
from typing import Any, Dict, List, Optional

logger = get_logger(__name__)


def _parse_ts(value: Optional[str]) -> Optional[datetime]:
    """宽松解析 ISO 时间戳（记忆 created_at / 轮次消息 timestamp）。

    时区混用（naive/aware）会导致相减抛 TypeError：统一按 UTC 补齐 naive 值。
    解析失败返回 None（调用方回退为"取第一条"）。
    """
    if not value or not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


class _PersistDbStore:
    """MemoryManager 持久库（memories 表）的只读 SQL 适配器。

    MoE ExpertDrilldownRetriever 的 L0 下钻需要 store.execute(sql, params)
    返回可 fetchall 的行集；此前传入的是 JSON MemoryStorage（聊天记忆不在
    其中，L0 必然空转）。本适配器把检索统一到 recall 的主数据源 persist.db。
    """

    def __init__(self, db_path: str, agent_id: str, neuser_id: str, user_id: str):
        import sqlite3

        self._sqlite3 = sqlite3
        self._db_path = db_path
        self._agent_id = agent_id
        self._neuser_id = neuser_id
        self._user_id = user_id

    class _Rows:
        def __init__(self, rows: List[Dict[str, Any]]):
            self._rows = rows

        def fetchall(self) -> List[Dict[str, Any]]:
            return self._rows

    def execute(self, sql: str, params: Optional[Dict[str, Any]] = None) -> "_PersistDbStore._Rows":
        import re

        conn = self._sqlite3.connect(self._db_path)
        try:
            conn.row_factory = self._sqlite3.Row
            # 强制三级隔离，防止跨 agent/用户泄漏（与 MemoryManager._load_from_db 一致）
            conditions = "agent_id = :agent_id AND neuser_id = :neuser_id AND user_id = :user_id"
            scoped = sql
            if re.search(r"\bWHERE\b", scoped, re.IGNORECASE):
                scoped = re.sub(r"\bWHERE\b", f"WHERE {conditions} AND ", scoped, count=1, flags=re.IGNORECASE)
            else:
                m = re.search(r"\bORDER BY\b|\bLIMIT\b", scoped, re.IGNORECASE)
                if m:
                    scoped = scoped[: m.start()] + f"WHERE {conditions} " + scoped[m.start() :]
                else:
                    scoped = scoped.rstrip().rstrip(";") + f" WHERE {conditions}"

            all_params = {
                "agent_id": self._agent_id,
                "neuser_id": self._neuser_id,
                "user_id": self._user_id,
                **(params or {}),
            }
            rows = conn.execute(scoped, all_params).fetchall()
            return _PersistDbStore._Rows([dict(r) for r in rows])
        finally:
            conn.close()



def run_async_safely(coro):
    """安全地运行协程，兼容同步上下文与异步上下文。

    BE-CORE-001 修复: asyncio.run() 在运行中的事件循环内调用会抛
    RuntimeError: asyncio.run() cannot be called from a running event loop。

    - 无运行中的事件循环（同步上下文）: 直接 asyncio.run(coro)
    - 有运行中的事件循环（异步上下文）: 在新线程的新事件循环中运行，
      避免阻塞当前循环并规避 asyncio.run() 的限制

    BUG 7 修复: 协程在传入前已创建, 若 ThreadPoolExecutor 路径失败,
    协程未被 await 也未 close() → 泄漏。用 try/except 确保异常路径关闭协程。
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # 无运行中的事件循环 — 直接运行
        return asyncio.run(coro)

    # 处于运行中的事件循环内 — 独立线程 + 专用事件循环执行。
    # 注意：绝不能 run_coroutine_threadsafe(coro, 当前循环) 后在当前线程
    # 阻塞等待结果——那会让事件循环线程卡死、被调度的协程永远得不到执行
    # （自死锁）。把整个协程放到新线程的专用循环里跑，协程内部创建的
    # 所有子任务都绑定到同一个新循环，语义自洽（P2-#17 场景不混用循环）。
    def _run_in_new_loop():
        return asyncio.run(coro)

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        return executor.submit(_run_in_new_loop).result()
    except BaseException:
        # 异常路径: 协程未被消费, 显式 close 避免泄漏
        coro.close()
        raise
    finally:
        executor.shutdown(wait=False)


# 注：mem_core.Memory dataclass 已删除（Tier 4A.2 统一 dataclass）。
# 唯一 Memory dataclass 现为 neurova.cognitive_layers.memory_layer.models.Memory。
# 旧导入 `from neurova.mem_core import Memory` 的使用方已改为从 models 导入。
# 详见 docs/adr/0001-unify-memory-dataclass.md。


@dataclass
class Conversation:
    """对话数据模型

    具有类型安全和数据验证的对话数据类。
    支持向后兼容的 **kwargs 构造方式。
    """

    id: str = ""
    session_id: str = ""
    user_id: str = ""
    agent_id: str = ""
    messages: List[Dict[str, Any]] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    metadata: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        """后初始化处理，支持向后兼容的 **kwargs 构造方式"""
        # 如果没有提供 id，自动生成
        if not self.id:
            self.id = f"conversation_{int(time.time() * 1000)}"

        # 确保 messages 是列表
        if self.messages is None:
            self.messages = []

        # 确保 metadata 是字典
        if self.metadata is None:
            self.metadata = {}

    def add_message(self, role: str, content: str, metadata: Optional[Dict[str, Any]] = None):
        """添加消息"""
        message = {
            "role": role,
            "content": content,
            "timestamp": time.time(),
            "metadata": metadata or {},
        }
        self.messages.append(message)
        self.updated_at = time.time()

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "id": self.id,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "agent_id": self.agent_id,
            "messages": self.messages,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata or {},
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Conversation":
        """从字典创建 Conversation 实例"""
        return cls(
            id=data.get("id", ""),
            session_id=data.get("session_id", ""),
            user_id=data.get("user_id", ""),
            agent_id=data.get("agent_id", ""),
            messages=data.get("messages", []),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
            metadata=data.get("metadata"),
        )


def _moe_scope_key(mem_system) -> str:
    """索引状态的作用域键：记忆系统当前持久库路径"""
    try:
        return str(getattr(mem_system.memory_manager, "_persist_db_path", ""))
    except Exception:
        return ""


def _init_encoder_sync(engine) -> None:
    """在独立线程同步初始化嵌入引擎

    init_moe_router 运行在 uvicorn 事件循环线程：encode() 的懒初始化路径
    看到"循环运行中"会直接降级到 TF-IDF（维度漂移，语义效果≈0）。
    这里给异步初始化另起事件循环，就绪后 encode 才能走真模型。
    """
    import asyncio

    try:
        asyncio.run(engine.initialize())
    except Exception as e:
        logger.warning("嵌入引擎同步初始化失败（降级 TF-IDF）: %s", e)


def _moe_index_state_path(scope_key: str) -> Path:
    """MoE 索引完成状态文件（按持久库路径哈希分文件，多 agent 各管各的）"""
    hashed = hashlib.md5(scope_key.encode("utf-8")).hexdigest()[:16]
    return Path(__file__).resolve().parent.parent / "data" / f"moe_index_state_{hashed}.json"


def _moe_index_completed(index_limit: int, scope_key: str) -> bool:
    """上次索引已达上限时返回 True（新增记忆由 recall 增量路径兜底）"""
    try:
        path = _moe_index_state_path(scope_key)
        if not path.exists():
            return False
        prev = json.loads(path.read_text(encoding="utf-8"))
        return prev.get("limit") == index_limit and int(prev.get("indexed_count", 0)) >= index_limit
    except Exception:
        return False


def _save_moe_index_state(index_limit: int, vector_store, scope_key: str) -> None:
    """索引线程收尾时落盘状态（成功/失败/部分完成均记录，已记录条数）"""
    try:
        path = _moe_index_state_path(scope_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "limit": index_limit,
            "indexed_count": len(vector_store.memory_ids),
            "finished_at": datetime.now(UTC).isoformat(),
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("MoE 索引状态已保存: %s", payload)
    except Exception as e:
        logger.warning("MoE 索引状态保存失败: %s", e)


def _background_index_memories(
    vector_store,
    fetch_page,
    index_limit: int,
    batch_size: int = 500,
    batch_delay: float = 0.05,
) -> int:
    """后台渐进语义索引（daemon 线程目标函数）

    通过 fetch_page(offset, size) 按温度降序分页读取全库记忆，灌入 MoE
    向量索引，突破初始 500 条的覆盖局限。新增条数达到 index_limit 或
    数据扫尽即停止；已索引 id 由 index_memories(incremental=True) 去重跳过。

    Args:
        vector_store: MoE 向量存储
        fetch_page: (offset, size) -> List[Dict]，持久层分页读取闭包
        index_limit: 索引覆盖上限（vector_search.moe_index_limit）
        batch_size: 每批条数
        batch_delay: 批间休眠秒数（让出 CPU）

    Returns:
        实际新增索引条数
    """
    indexed_before = len(vector_store.memory_ids)
    budget = max(0, index_limit - indexed_before)
    if budget == 0:
        logger.info("MoE 后台索引: 已达上限 %s 条，跳过", index_limit)
        return 0

    offset = 0
    last_first_id = None
    total_added = 0
    while budget > 0:
        rows = fetch_page(offset, batch_size)
        if not rows:
            logger.info(
                "MoE 后台索引: 全库扫描完成，新增 %s 条，总索引 %s 条",
                total_added,
                len(vector_store.memory_ids),
            )
            break

        # 游标无进展守卫（持久层不支持 OFFSET 分页时防死循环）
        first_id = rows[0].get("id") if rows else None
        if first_id is not None and first_id == last_first_id:
            logger.warning("MoE 后台索引: 分页游标无进展，提前终止")
            break
        last_first_id = first_id

        offset += len(rows)
        memory_items = [
            {
                "id": r.get("id", ""),
                "content": r.get("content", ""),
                "metadata": {
                    "category": r.get("category", "general"),
                    "lifecycle": r.get("lifecycle_stage", "active"),
                },
            }
            for r in rows
        ][:budget]  # 批内按剩余预算精确截断，避免末批溢出上限

        before = len(vector_store.memory_ids)
        try:
            vector_store.index_memories(memory_items, incremental=True)
        except Exception as e:
            logger.warning("MoE 后台索引批次失败，跳过该批: %s", e)
            continue

        added = len(vector_store.memory_ids) - before
        total_added += added
        budget -= added
        time.sleep(batch_delay)

    logger.info(
        "MoE 后台索引结束: 新增 %s 条，总索引 %s 条（上限 %s）",
        total_added,
        len(vector_store.memory_ids),
        index_limit,
    )
    return total_added


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
        # S5 修复 (Critical #6): 保护 update_history 的 read-modify-write.
        # conversation_history 是裸 list,无锁并发修改会 lost update.
        self._history_lock = RLock()

    # ---- 属性代理（方便内部访问） ----
    @property
    def config(self):
        return self._agent.config

    @property
    def memory_manager(self):
        return getattr(self._agent, "memory_manager", None)

    @memory_manager.setter
    def memory_manager(self, value):
        self._agent.memory_manager = value

    @property
    def storage(self):
        return getattr(self._agent, "storage", None)

    @storage.setter
    def storage(self, value):
        self._agent.storage = value

    @property
    def temperature_engine(self):
        return getattr(self._agent, "temperature_engine", None)

    @temperature_engine.setter
    def temperature_engine(self, value):
        self._agent.temperature_engine = value

    @property
    def recall_engine(self):
        return getattr(self._agent, "recall_engine", None)

    @recall_engine.setter
    def recall_engine(self, value):
        self._agent.recall_engine = value

    @property
    def working_memory(self):
        return getattr(self._agent, "working_memory", None)

    @working_memory.setter
    def working_memory(self, value):
        self._agent.working_memory = value

    @property
    def conversation_buffer(self):
        return getattr(self._agent, "conversation_buffer", None)

    @conversation_buffer.setter
    def conversation_buffer(self, value):
        self._agent.conversation_buffer = value

    @property
    def buffer_module(self):
        return getattr(self._agent, "buffer_module", None)

    @buffer_module.setter
    def buffer_module(self, value):
        self._agent.buffer_module = value

    @property
    def conversation_history(self):
        return getattr(self._agent, "conversation_history", [])

    @conversation_history.setter
    def conversation_history(self, value):
        self._agent.conversation_history = value

    @property
    def evolution(self):
        return getattr(self._agent, "evolution", None)

    @property
    def session_manager(self):
        return getattr(self._agent, "session_manager", None)

    @property
    def growth_log_manager(self):
        return getattr(self._agent, "growth_log_manager", None)

    @growth_log_manager.setter
    def growth_log_manager(self, value):
        self._agent.growth_log_manager = value

    @property
    def question_queue_manager(self):
        return getattr(self._agent, "question_queue_manager", None)

    @question_queue_manager.setter
    def question_queue_manager(self, value):
        self._agent.question_queue_manager = value

    @property
    def tool_memory(self):
        return getattr(self._agent, "tool_memory", None)

    @tool_memory.setter
    def tool_memory(self, value):
        self._agent.tool_memory = value

    @property
    def muscle_memory(self):
        return getattr(self._agent, "muscle_memory", None)

    @muscle_memory.setter
    def muscle_memory(self, value):
        self._agent.muscle_memory = value

    @property
    def attachment_manager(self):
        return getattr(self._agent, "attachment_manager", None)

    @attachment_manager.setter
    def attachment_manager(self, value):
        self._agent.attachment_manager = value

    @property
    def moe_router(self):
        return getattr(self._agent, "_moe_router", None)

    # ══════════════════════════════════════════════════════════════
    # 初始化
    # ══════════════════════════════════════════════════════════════

    def init_memory_modules(self, neuser_id: str = "default", user_id: str = "default"):
        """初始化记忆系统模块

        Args:
            neuser_id: Neurova系统用户ID（三级隔离第2级）
            user_id: 对话用户ID（三级隔离第3级）
        """
        from neurova.cognitive_layers.memory_layer.conversation_buffer import ConversationMemoryBuffer, MemoryWriteQueue
        from neurova.cognitive_layers.memory_layer.manager import MemoryManager
        from neurova.cognitive_layers.memory_layer.modules.buffer_module import BufferModule
        from neurova.cognitive_layers.memory_layer.temperature import TemperatureEngine
        from neurova.cognitive_layers.memory_layer.working_memory import WorkingMemoryAugmenter
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
            self.storage = getattr(self.memory_manager, "storage", None)
            self.temperature_engine = TemperatureEngine()

            # Neurova 统一记忆检索引擎（多维融合 + 意图钻取）
            # Bug 9 修复：原构造签名 (storage=, temperature_engine=, emotion_analyzer=,
            # tkg=, vector_search=, config=) 与真实签名完全不符，会抛 TypeError。
            # 真实签名: (memory_manager, max_workers, timeout_seconds, intent_detector,
            #           intent_strategy, use_plugins, registry, fusion_mode, density_scale)
            # 所有依赖通过 memory_manager 间接访问，无需重复注入。
            if self.storage:
                from neurova.cognitive_layers.memory_layer.neurova_recall import NeurovaRecallEngine

                self.recall_engine = NeurovaRecallEngine(
                    memory_manager=self.memory_manager,
                    max_workers=4,
                    timeout_seconds=10.0,
                    use_plugins=True,
                    fusion_mode="legacy",
                )
                logger.info("Agent %s: NeurovaRecallEngine（多维融合+钻取）已启用", self.config.name)
            else:
                self.recall_engine = None
                logger.warning("Agent %s: storage 不可用，NeurovaRecallEngine 未启用", self.config.name)

            # 初始化附件管理器（Agent隔离 + 用户隔离）
            from neurova.cognitive_layers.memory_layer.attachment_manager import AttachmentManager

            self._agent.attachment_manager = AttachmentManager.from_agent_config(
                agent_id=self.config.agent_id,
                agent_workspace_path=str(self.config.workspace_path),
                db_path=db_path,
            )
            logger.info("AttachmentManager 初始化成功: %s", self.config.attachment_dir)

            # 初始化反思日志管理器
            self._agent.growth_log_manager = GrowthLogManager(
                memory_manager=self.memory_manager,
                max_logs=1000,
            )
            logger.info("Agent %s: GrowthLogManager（反思日志）已启用", self.config.name)

            # 初始化问题队列管理器
            self._agent.question_queue_manager = QuestionQueueManager(
                memory_manager=self.memory_manager,
                default_cooldown=300.0,
                max_questions=100,
            )
            logger.info("Agent %s: QuestionQueueManager（问题队列）已启用", self.config.name)

            # 初始化工作记忆
            self.working_memory = WorkingMemoryAugmenter(
                config={
                    "max_items": 10,
                    "memory_manager": self.memory_manager,
                }
            )
            logger.info("Agent %s: WorkingMemoryAugmenter（工作记忆）已启用", self.config.name)

            # 初始化对话缓冲区
            self.conversation_buffer = ConversationMemoryBuffer(
                turn_limit=1000,  # 增大默认轮次限制
            )
            logger.info("Agent %s: ConversationMemoryBuffer（对话缓冲区）已启用", self.config.name)

            # 初始化缓冲模块
            self.buffer_module = BufferModule()
            # BUG 4 修复: 不覆盖 _buffer(List[Dict] 类型契约),
            # 改为在 BufferModule 上单独持有 ConversationBuffer 引用
            self.buffer_module._conv_buffer = self.conversation_buffer

            # 始终创建 MemoryWriteQueue，传递 memory_manager 作为降级后端
            self.buffer_module._write_queue = MemoryWriteQueue(
                storage=self.storage,
                agent_id=self.config.agent_id,
                memory_manager=self.memory_manager,
            )
            logger.info("Agent %s: BufferModule（缓冲模块）已启用", self.config.name)

            # 肌肉记忆/工具记忆不在 mem_core 初始化——agent_core.init_memory 的
            # ToolMemory（正式实例，带 workspace 落盘目录 + 阈值单源）会覆盖
            # agent.tool_memory；此处曾另建一套无 storage_dir 的 MuscleMemory +
            # ToolMemoryIntegration，是永不落盘的内存孤儿（P2 清理删除）。

            logger.info(
                f"记忆系统模块初始化成功: agent_id={self.config.agent_id}, neuser_id={neuser_id}, user_id={user_id}"
            )

        except Exception as e:
            import traceback

            logger.error("记忆系统模块初始化失败: %s\n" f"完整调用栈:\n%s", e, traceback.format_exc())
            raise  # 记忆模块是 Agent 核心依赖，无法降级

    def init_moe_router(self):
        """初始化 MoE 路由器（数据源统一：persist.db，断裂 M1 修复）"""
        try:
            from neurova.cognitive_layers.memory_layer.moe_router import MoEMemoryRouter
            from neurova.cognitive_layers.memory_layer.unified_vector_store import UnifiedVectorStore

            vector_store = UnifiedVectorStore()

            # 嵌入引擎同步预热：异步初始化在事件循环线程内会被 encode 的
            # 懒加载分支绕过（降级 TF-IDF），先就绪才能走真模型语义向量。
            encoder_engine = getattr(vector_store, "_encoder", None)
            if encoder_engine is not None and not encoder_engine.is_initialized:
                asyncio_thread = threading.Thread(
                    target=_init_encoder_sync, args=(encoder_engine,), daemon=True,
                    name="embedding-engine-warmup",
                )
                asyncio_thread.start()
                asyncio_thread.join(timeout=90)

            # 专家定义对齐 memories 表真实 schema（此前 is_crystallized 列不存在，
            # L0 SQL 必然异常返回空）。category 取值来自 MemoryCategory 枚举。
            experts = {
                "conversation_episodic": {
                    "name": "对话情景记忆",
                    "category": "conversation",
                    "lifecycle_stage": "active",
                    "centroid_text": "对话记忆、日常交流、聊天记录",
                },
                "factual_knowledge": {
                    "name": "事实知识",
                    "category": "knowledge",
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

            # L0 下钻与初始索引统一指向 persist.db（recall 主数据源）
            store = self._build_moe_store()
            if store:
                try:
                    rows = store.execute(
                        "SELECT id, content, category, lifecycle_stage FROM memories "
                        "ORDER BY temperature DESC LIMIT 500"
                    ).fetchall()
                    if rows:
                        memory_items = [
                            {
                                "id": r.get("id", ""),
                                "content": r.get("content", ""),
                                "metadata": {
                                    "category": r.get("category", "general"),
                                    "lifecycle": r.get("lifecycle_stage", "active"),
                                },
                            }
                            for r in rows
                        ]
                        vector_store.index_memories(memory_items)
                        logger.info("MoE: 已从 persist.db 索引 %s 条记忆", len(memory_items))
                    else:
                        logger.info("MoE: persist.db 中没有记忆，跳过初始索引")
                except Exception as e:
                    logger.warning("MoE: 加载记忆索引失败: %s", e)

            # 激活阈值配置化（memory-settings 配置页）: threshold.default，
            # settings 默认 0.3 与历史硬编码一致。
            from neurova.cognitive_layers.memory_layer.settings_config import (
                get_memory_settings,
            )

            moe_router = MoEMemoryRouter(
                experts=experts,
                storage=store or self.storage,
                vector_store=vector_store,
                activation_threshold=float(
                    get_memory_settings().get("threshold.default", 0.3)
                ),
            )

            # 后台渐进语义索引：突破初始 500 条覆盖局限，按温度降序
            # 分批把全库记忆灌入 MoE 向量索引，直到 moe_index_limit 或全库完成。
            # daemon 线程：边索引边可查，服务退出自动结束。
            try:
                index_limit = int(
                    get_memory_settings().get("vector_search.moe_index_limit", 20000)
                )
                if store and index_limit > 500:

                    def _fetch_page(offset: int, size: int):
                        # _PersistDbStore.execute 要求命名参数 Dict，
                        # 并自动注入三级隔离 WHERE 条件
                        return store.execute(
                            "SELECT id, content, category, lifecycle_stage "
                            "FROM memories "
                            "WHERE lifecycle_stage != 'forgotten' "
                            "ORDER BY temperature DESC "
                            "LIMIT :limit OFFSET :offset",
                            {"limit": size, "offset": offset},
                        ).fetchall()

                    if _moe_index_completed(index_limit, _moe_scope_key(self)):
                        logger.info("MoE 后台语义索引已完成（上限 %s 条），跳过本次重扫", index_limit)
                    else:

                        def _index_and_save_state():
                            try:
                                _background_index_memories(vector_store, _fetch_page, index_limit)
                            finally:
                                _save_moe_index_state(index_limit, vector_store, _moe_scope_key(self))

                        indexer = threading.Thread(
                            target=_index_and_save_state,
                            daemon=True,
                            name="moe-semantic-indexer",
                        )
                        indexer.start()
                        logger.info("MoE 后台语义索引线程已启动（上限 %s 条）", index_limit)
            except Exception as e:
                logger.warning("MoE 后台索引线程启动失败: %s", e)

            # 情感语义标注接线：复用 MoE 编码器做 zero-shot 原型分类（不可用时规则兜底）
            try:
                from neurova.cognitive_layers.memory_layer.semantic_emotion import (
                    SemanticEmotionClassifier,
                )

                em_mod = getattr(self.memory_manager, "_emotion_module", None)
                if em_mod is not None and hasattr(em_mod, "set_semantic_classifier"):
                    # 仅当预训练后端接线；tfidf 词表会增长导致原型/查询向量维度漂移，
                    # 分类器内部会拒绝（返回 None）并降级规则引擎
                    if getattr(vector_store, "backend", "") in ("onnx", "fastembed", "faiss"):
                        classifier = SemanticEmotionClassifier(encoder=vector_store.encode)
                        # 预热：同步编码原型句（顺带触发嵌入引擎惰性初始化），
                        # 避免首个情感标注请求卡在模型加载上
                        classifier.analyze("今天是普通的一天，没有特别的事情发生")
                        em_mod.set_semantic_classifier(classifier)
                        logger.info(
                            "EmotionModule 语义情感分类器已接入（backend=%s）",
                            vector_store.backend,
                        )
            except Exception as e:
                logger.warning("语义情感分类器接入失败（规则引擎兜底）: %s", e)

            self._agent._moe_router = moe_router
            logger.info("MoE 路由器初始化成功")

        except Exception as e:
            logger.error("MoE 路由器初始化失败: %s", e)

    def _build_moe_store(self):
        """构建 MoE L0 下钻的存储适配器（persist.db 只读；不可用时返回 None）"""
        manager = self.memory_manager
        db_path = getattr(manager, "_persist_db_path", None) if manager else None
        if db_path and Path(db_path).exists():
            try:
                # 隔离参数以 MemoryManager 为准（与 persist 写入侧一致）
                return _PersistDbStore(
                    db_path=db_path,
                    agent_id=getattr(manager, "_agent_id", "default"),
                    neuser_id=getattr(manager, "_neuser_id", "default"),
                    user_id=getattr(manager, "_user_id", "default"),
                )
            except Exception as e:  # noqa: BLE001
                logger.warning("PersistDbStore 构建失败: %s", e)
        return None

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
            logger.warning("记忆检索失败: %s", e)
            return []

    def unified_experience_recall(self, query: str, limit: int = 5) -> List[Dict]:
        """统一经验召回

        检索与用户输入相关的历史经验记忆。经验以记忆形式统一存储，
        因此复用 MemCore.recall 的检索通道（自动刷新缓冲区并优先使用
        recall_engine / MoE 路由器）。
        """
        return self.recall(query, limit)

    def get_memories(self, limit: int = 100, offset: int = 0) -> List[Dict]:
        """获取记忆列表（用于 API 端点）

        Args:
            limit: 返回结果数量限制
            offset: 偏移量

        Returns:
            记忆列表
        """
        if not self.memory_manager:
            return []

        try:
            return self.memory_manager.get_memories(limit=limit, offset=offset)
        except Exception as e:
            logger.warning("获取记忆列表失败: %s", e)
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
                results = run_async_safely(moe.retrieve(query, limit=limit))
                if results:
                    logger.debug("MoE 检索成功: %s 条结果", len(results))
                    return results
                else:
                    logger.debug("MoE 检索无结果，降级到普通检索")
            except Exception as e:
                logger.warning("MoE 检索失败: %s，降级到普通检索", e)

        return self.retrieve_memories(query, limit=limit)

    def refresh_moe_index(self):
        """刷新 MoE 向量索引（数据源统一：从 MemoryManager/persist.db 重建）"""
        moe = self.moe_router
        if not moe or not self.memory_manager:
            return

        try:
            memories = self.memory_manager.get_all_memories()
            if memories:
                memory_items = [
                    {
                        "id": mem.get("id", ""),
                        "content": mem.get("content", ""),
                        "metadata": {
                            "category": mem.get("category", "general"),
                            "lifecycle": mem.get("lifecycle_stage", "active"),
                        },
                    }
                    for mem in memories
                ]
                moe.vector_store.index_memories(memory_items)
                # 重新初始化质心
                moe.vector_store.initialize_centroids(moe.experts)
                logger.info("MoE 向量索引已刷新: %s 条记忆", len(memory_items))
        except Exception as e:
            logger.warning("MoE 向量索引刷新失败: %s", e)

    def flush_before_retrieve(self):
        """检索前刷新缓冲区（断裂2修复）

        在 MoE 检索前，先将对话缓冲区中的未 flush 记忆写入 SQLite，
        确保当前对话中的记忆可被检索。
        """
        try:
            # 刷新对话缓冲区
            # BUG 1 修复: ConversationBuffer 只有 flush(), 不存在 flush_to_long_term_memory()。
            # flush() 返回 List[MemoryItem], 通过 MemoryWriteQueue 写入长期存储。
            if self.conversation_buffer and self.conversation_buffer.is_full():
                items = self.conversation_buffer.flush()
                if items and hasattr(self, 'memory_manager'):
                    queue = getattr(self.memory_manager, '_write_queue', None)
                    if queue:
                        queue.enqueue_batch(items)
                logger.debug("对话缓冲区已 flush")

            # 刷新写入队列
            if self.buffer_module and hasattr(self.buffer_module, "_write_queue"):
                queue = self.buffer_module._write_queue
                if queue and hasattr(queue, "flush_to_storage"):
                    # BUG 3 修复: flush_to_storage() 返回 int(written 计数),
                    # 不是 dict, 不能用 result.get("written", 0)
                    written = queue.flush_to_storage()
                    if written > 0:
                        logger.debug("写入队列已 flush: %s 条", written)
        except Exception as e:
            logger.warning("检索前 flush 失败: %s", e)

    # ══════════════════════════════════════════════════════════════
    # 对话记忆保存
    # ══════════════════════════════════════════════════════════════

    def save_conversation_memory(self, user_input: str, agent_response: str, metadata: Dict = None):
        """保存对话记忆

        同时写入 memory_manager（持久化）和 conversation_buffer（快速检索）。

        Args:
            user_input: 用户输入
            agent_response: Agent 回复
            metadata: 元数据
        """
        try:
            # 1. 写入 memory_manager（确保 API 端点可查询）
            if self.memory_manager:
                base_meta = metadata or {}
                self.memory_manager.remember(
                    content=f"用户: {user_input}",
                    memory_type="episodic",
                    category="conversation",
                    metadata={**base_meta, "sender_type": "user"},
                    origin="owner",
                )
                self.memory_manager.remember(
                    content=f"助手: {agent_response}",
                    memory_type="episodic",
                    category="conversation",
                    metadata={**base_meta, "sender_type": "agent"},
                    origin="agent",
                )

            # 2. 写入对话缓冲区（快速上下文检索）
            if self.conversation_buffer:
                self.conversation_buffer.add_user_message(user_input)
                self.conversation_buffer.add_agent_message(agent_response)

                # 如果缓冲区满了，刷新到长期记忆
                # BUG 1 修复: 调用 flush()(返回 List[MemoryItem]) 而非不存在的 flush_to_long_term_memory()
                if self.conversation_buffer.is_full():
                    items = self.conversation_buffer.flush()
                    if items and hasattr(self, 'memory_manager'):
                        queue = getattr(self.memory_manager, '_write_queue', None)
                        if queue:
                            queue.enqueue_batch(items)

            logger.debug("对话记忆已保存: user_input=%s...", user_input[:50])
        except Exception as e:
            logger.warning("对话记忆保存失败: %s", e)

    # ══════════════════════════════════════════════════════════════
    # 对话记忆清除/反馈（轮次删除、编辑覆写、点赞点踩质量闭环）
    # ══════════════════════════════════════════════════════════════

    # 点踩温度抑制量（负值；like 走 touch() 的原生 +10 强化）
    DISLIKE_TEMPERATURE_DELTA = -15.0

    def _find_round_memories(
        self,
        session_id: str,
        user_input: str,
        agent_response: str,
        approx_ts: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """按轮次内容定位记忆 dict 列表（delete_round_memories / 反馈温度共享）。

        匹配契约与 _step_save_memory 的落库格式对齐：
        content == "用户: {user_input}" / "助手: {agent_response}"，
        metadata.session_id == session_id，metadata.sender_type == user/agent。

        同内容多轮重复（如"继续"）时按 created_at 与轮次消息时间戳
        （approx_ts）的接近程度取最近一条，不误伤历史轮。
        """
        memory_manager = self.memory_manager
        if not memory_manager or not session_id:
            return []

        targets = []
        if user_input:
            targets.append(("user", f"用户: {user_input}"))
        if agent_response:
            targets.append(("agent", f"助手: {agent_response}"))
        if not targets:
            return []

        try:
            all_memories = memory_manager.get_all_memories()
        except Exception as e:
            logger.warning("轮次记忆定位失败（读取记忆失败）: %s", e)
            return []

        ref_ts = _parse_ts(approx_ts)
        matched: List[Dict[str, Any]] = []
        for sender_type, content in targets:
            candidates = [
                m for m in all_memories
                if isinstance(m, dict)
                and (m.get("metadata") or {}).get("session_id") == session_id
                and (m.get("metadata") or {}).get("sender_type") == sender_type
                and m.get("content") == content
            ]
            if not candidates:
                continue
            # created_at 与轮次时间最近者优先；无法解析时间时取第一条
            target = min(
                candidates,
                key=lambda m: abs(
                    (_parse_ts(m.get("created_at")) - ref_ts).total_seconds()
                )
                if (_parse_ts(m.get("created_at")) is not None and ref_ts is not None)
                else float("inf"),
            )
            if target.get("id"):
                matched.append(target)
        return matched

    def delete_round_memories(
        self,
        session_id: str,
        user_input: str,
        agent_response: str,
        approx_ts: Optional[str] = None,
    ) -> int:
        """删除一轮对话对应的记忆（编辑覆写/删除轮次时调用）。

        Returns:
            成功删除的记忆条数。memory_manager 不可用或异常时返回 0
            （best-effort，不阻断轮次删除主流程）。
        """
        memory_manager = self.memory_manager
        if not memory_manager or not session_id:
            return 0

        deleted_count = 0
        for target in self._find_round_memories(session_id, user_input, agent_response, approx_ts):
            memory_id = target.get("id")
            try:
                if memory_manager.forget(memory_id, soft=False):
                    deleted_count += 1
                    logger.debug("轮次记忆已删除: memory_id=%s, session_id=%s", memory_id, session_id)
            except Exception as e:
                logger.warning("轮次记忆删除失败: memory_id=%s, %s", memory_id, e)
        return deleted_count

    def apply_feedback_to_memories(
        self,
        session_id: str,
        user_input: str,
        agent_response: str,
        feedback: str,
        approx_ts: Optional[str] = None,
    ) -> int:
        """把点赞/点踩反馈作用于该轮记忆温度（反馈质量闭环）。

        - like  → update_memory_temperature（touch，+10 强化，召回概率提升）
        - dislike → update_memory(temperature=max(0, temp-15)) 抑制，加速遗忘
        - feedback 非 like/dislike（如取消反馈 None）→ 无操作

        Returns:
            成功更新温度的记忆条数（best-effort，异常不外抛）。
        """
        memory_manager = self.memory_manager
        if not memory_manager or not session_id or feedback not in ("like", "dislike"):
            return 0

        affected = 0
        for target in self._find_round_memories(session_id, user_input, agent_response, approx_ts):
            memory_id = target.get("id")
            if not memory_id:
                continue
            try:
                if feedback == "like":
                    if memory_manager.update_memory_temperature(memory_id, interaction_type="use"):
                        affected += 1
                else:
                    current = float(target.get("temperature") or 0.0)
                    new_temp = max(0.0, current + self.DISLIKE_TEMPERATURE_DELTA)
                    if memory_manager.update_memory(memory_id, temperature=new_temp):
                        affected += 1
            except Exception as e:
                logger.warning("反馈温度更新失败: memory_id=%s, %s", memory_id, e)

        if affected:
            logger.info(
                "反馈已作用于记忆温度: session=%s, feedback=%s, 条数=%s",
                session_id, feedback, affected,
            )
        return affected

    # ══════════════════════════════════════════════════════════════
    # 对话历史更新
    # ══════════════════════════════════════════════════════════════

    def update_history(self, user_input: str, agent_response: str, writer_claim=None, session_id: Optional[str] = None):
        """更新对话历史

        Args:
            user_input: 用户输入
            agent_response: Agent 回复
            writer_claim: P1-10 写入围栏凭证（可选）。显式参与——失效时跳过
                本次追加（被夺权的 run 不写陈旧历史）；None 时行为不变。
            session_id: 围栏作用域键（与 claim 时的会话键一致）。

        Notes:
            S5 修复 (Critical #6): 整体方法体由 _history_lock 保护,
            防止并发 update_history 调用的 read-modify-write 跨锁边界.
            D3 修复 (ADR 0008 候选 #6): 删除 fallback 路径,
            agent._conversation_context 是必填的 (由 Agent.init_conversation 初始化).
            未初始化时显式抛 RuntimeError,杜绝 split-brain 风险.
        """
        # P1-10 写入围栏: 参与 claim 已失效 → 拒绝追加
        if writer_claim is not None:
            try:
                from neurova.agent.history_fence import get_history_write_fence

                _fence = get_history_write_fence()
                if not _fence.check(
                    getattr(self.config, "agent_id", "unknown") if self.config else "unknown",
                    session_id or "default",
                    writer_claim,
                ):
                    _fence.record_fenced_write()
                    logger.info("对话历史更新被围栏拒绝（陈旧 writer）")
                    return
            except Exception as fence_err:  # noqa: BLE001 - 围栏故障绝不阻断主流程
                logger.debug("围栏检查异常,降级放行: %s", fence_err)

        # S5: 整个 read-modify-write 在 _history_lock 内,保证原子性
        with self._history_lock:
            ctx = getattr(self._agent, "_conversation_context", None)
            if ctx is None:
                # D3: 不再走兼容分支,显式失败要求先 init_conversation()
                raise RuntimeError(
                    "Agent 未初始化 _conversation_context;请调用 agent.init_conversation() "
                    "后再使用 update_history()。 D3 删除 fallback 路径以消除 split-brain 风险."
                )

            now_iso = datetime.now(UTC).isoformat()

            # Deep module 路径:invariant 由 ConversationContext 保证
            # 先同步现有 list 到 ctx (处理外部直接操作 list 的情况)
            current_list = getattr(self._agent, "conversation_history", [])
            # P2-2 修复: 原条件 `if current_list and ...` 在 clear_history() 把 list
            # 清空后 falsy 跳过同步, 旧 ctx 在下次 update 时复活已清空的历史。
            # 只比较长度: list 为空而 ctx 非空 = 外部已清空, 必须同步清空 ctx。
            if len(current_list) != len(ctx):
                ctx.clear()
                ctx.extend(current_list)
            ctx.append("user", user_input, metadata={"timestamp": now_iso})
            ctx.append("assistant", agent_response, metadata={"timestamp": now_iso})
            # 同步回 list (保持兼容)
            self._agent.conversation_history = ctx.to_list()

            logger.debug("对话历史已更新: 长度=%s", len(self._agent.conversation_history))

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
        writer_claim=None,
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

        agent_id = getattr(self.config, "agent_id", "unknown") if self.config else "unknown"

        return sm.add_message(
            agent_id=agent_id,
            session_id=session_id,
            user_content=user_input,
            assistant_content=reply,
            metadata=metadata,
            assistant_metadata=assistant_metadata,
            writer_claim=writer_claim,
        )

    # ══════════════════════════════════════════════════════════════
    # 记忆温度更新
    # ══════════════════════════════════════════════════════════════

    def update_memory_temperature(self, memory_id: str, interaction_type: str = "view"):
        """更新记忆温度

        委托给 MemoryManager.update_memory_temperature，由其调用 Memory.touch()
        应用 access_count++ / temperature +10 / last_accessed_at 更新。

        Args:
            memory_id: 记忆ID
            interaction_type: 交互类型（view, use, recall）
        """
        # 委托给 MemoryManager（其内部调用 Memory.touch()）
        # 不直接调用 TemperatureEngine — TemperatureEngine 没有 update_temperature 方法，
        # 仅暴露 on_access / on_decay 用于贝叶斯温度计算（由 manager.run_decay_cycle 调用）。
        memory_manager = self.memory_manager
        if memory_manager is None:
            logger.debug("跳过温度更新：memory_manager 未初始化, memory_id=%s", memory_id)
            return

        try:
            memory_manager.update_memory_temperature(
                memory_id, interaction_type=interaction_type
            )
            logger.debug("记忆温度已更新: memory_id=%s, type=%s", memory_id, interaction_type)
        except Exception as e:
            # 缩窄异常类型不可能（manager 实现可能抛多种），但记录完整堆栈以避免静默吞没
            logger.warning("记忆温度更新失败: %s", e, exc_info=True)

    # ══════════════════════════════════════════════════════════════
    # 记忆统计
    # ══════════════════════════════════════════════════════════════

    def get_memory_stats(self) -> Dict[str, Any]:
        """获取记忆统计信息

        Returns:
            统计信息字典
        """
        stats = {
            "memory_manager_available": self.memory_manager is not None,
            "storage_available": self.storage is not None,
            "temperature_engine_available": self.temperature_engine is not None,
            "recall_engine_available": self.recall_engine is not None,
            "working_memory_available": self.working_memory is not None,
            "conversation_buffer_available": self.conversation_buffer is not None,
            "buffer_module_available": self.buffer_module is not None,
            "conversation_history_length": len(self.conversation_history),
            "moe_router_available": self.moe_router is not None,
        }

        # 添加记忆管理器统计
        if self.memory_manager:
            try:
                memory_stats = self.memory_manager.get_stats()
                stats.update(memory_stats)
            except Exception as e:
                logger.warning("获取记忆管理器统计失败: %s", e)

        return stats
