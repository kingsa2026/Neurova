"""
认知编排器模块 - Cognition Orchestrator Module

实现 Neurova CogArch 1.0.0 架构中的认知编排器（大脑皮层）：
- CognitiveState: 认知状态数据类
- AttentionLevel: 注意力级别枚举
- MemoryType: 记忆类型枚举
- AttentionManager: 注意力管理器
- MemoryManager: 记忆管理器
- CognitionOrchestrator: 认知编排器主类

架构:
  输入 ──▶ 观察 ──▶ 回忆 ──▶ 推理 ──▶ 反思 ──▶ 巩固 ──▶ 输出
"""

import copy
import datetime
import json
import logging
import threading
import time
import typing
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


logger = logging.getLogger(__name__)


# ────── 数据模型 ──────


class AttentionLevel(Enum):
    """注意力级别"""

    LOW = "low"  # 低注意力
    MEDIUM = "medium"  # 中等注意力
    HIGH = "high"  # 高注意力
    CRITICAL = "critical"  # 关键注意力


class MemoryType(Enum):
    """记忆类型"""

    SHORT_TERM = "short_term"  # 短期记忆
    LONG_TERM = "long_term"  # 长期记忆
    WORKING = "working"  # 工作记忆
    EPISODIC = "episodic"  # 情景记忆
    SEMANTIC = "semantic"  # 语义记忆


@dataclass
class CognitiveState:
    """认知状态"""

    attention_level: AttentionLevel = AttentionLevel.MEDIUM
    active_memories: typing.List[str] = field(default_factory=list)
    current_focus: str = ""
    emotional_state: str = "neutral"
    cognitive_load: float = 0.0  # 0-1
    timestamp: datetime.datetime = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc))
    metadata: typing.Dict[str, typing.Any] = field(default_factory=dict)

    def to_dict(self) -> typing.Dict[str, typing.Any]:
        """转换为字典"""
        return {
            "attention_level": self.attention_level.value,
            "active_memories": self.active_memories,
            "current_focus": self.current_focus,
            "emotional_state": self.emotional_state,
            "cognitive_load": self.cognitive_load,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata,
        }


@dataclass
class CognitiveCycleResult:
    """认知周期结果"""

    cycle_id: str = ""
    success: bool = False
    observations: typing.List[str] = field(default_factory=list)
    recalled_memories: typing.List[str] = field(default_factory=list)
    reasoning_steps: typing.List[str] = field(default_factory=list)
    reflections: typing.List[str] = field(default_factory=list)
    consolidated_memories: typing.List[str] = field(default_factory=list)
    duration_ms: float = 0.0
    error: typing.Optional[str] = None
    timestamp: datetime.datetime = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc))

    def to_dict(self) -> typing.Dict[str, typing.Any]:
        """转换为字典"""
        return {
            "cycle_id": self.cycle_id,
            "success": self.success,
            "observations": self.observations,
            "recalled_memories": self.recalled_memories,
            "reasoning_steps": self.reasoning_steps,
            "reflections": self.reflections,
            "consolidated_memories": self.consolidated_memories,
            "duration_ms": self.duration_ms,
            "error": self.error,
            "timestamp": self.timestamp.isoformat(),
        }


# ────── 管理器 ──────


class AttentionManager:
    """
    注意力管理器

    管理认知资源的分配和注意力切换。
    """

    def __init__(self, initial_level: AttentionLevel = AttentionLevel.MEDIUM):
        """
        初始化注意力管理器

        参数:
            initial_level: 初始注意力级别
        """
        self._current_level = initial_level
        self._attention_history: typing.List[typing.Tuple[datetime.datetime, AttentionLevel]] = []
        self._switch_threshold = 0.7
        self._lock = threading.RLock()

        logger.info("AttentionManager initialized with level: %s", initial_level.value)

    def get_attention(self) -> AttentionLevel:
        """
        获取当前注意力级别

        返回:
            AttentionLevel: 注意力级别
        """
        with self._lock:
            return self._current_level

    def set_attention(self, level: AttentionLevel) -> bool:
        """
        设置注意力级别

        参数:
            level: 注意力级别

        返回:
            bool: 是否设置成功
        """
        with self._lock:
            old_level = self._current_level
            self._current_level = level
            self._attention_history.append((datetime.datetime.now(datetime.timezone.utc), level))

            # 限制历史记录
            if len(self._attention_history) > 100:
                self._attention_history = self._attention_history[-100:]

            logger.debug("Attention changed: %s → %s", old_level.value, level.value)
            return True

    def should_switch_attention(self, new_focus: str, current_focus: str, importance: float) -> bool:
        """
        是否应该切换注意力

        参数:
            new_focus: 新焦点
            current_focus: 当前焦点
            importance: 重要性 (0-1)

        返回:
            bool: 是否应该切换
        """
        with self._lock:
            # 如果当前没有焦点，直接切换
            if not current_focus:
                return True

            # 如果重要性超过阈值，切换
            if importance > self._switch_threshold:
                return True

            # 如果当前注意力级别低，更容易切换
            if self._current_level in (AttentionLevel.LOW, AttentionLevel.MEDIUM):
                return importance > 0.5

            return False


class MemoryManager:
    """
    记忆管理器

    管理不同类型的记忆存储和检索。
    """

    def __init__(self):
        """初始化记忆管理器"""
        self._memories: typing.Dict[MemoryType, typing.List[typing.Dict[str, typing.Any]]] = {
            memory_type: [] for memory_type in MemoryType
        }
        self._lock = threading.RLock()

        logger.info("MemoryManager initialized")

    def add_memory(
        self, memory_type: MemoryType, content: str, metadata: typing.Optional[typing.Dict[str, typing.Any]] = None
    ) -> str:
        """
        添加记忆

        参数:
            memory_type: 记忆类型
            content: 内容
            metadata: 元数据

        返回:
            str: 记忆 ID
        """
        import uuid

        with self._lock:
            memory_id = str(uuid.uuid4())[:8]
            memory = {
                "id": memory_id,
                "content": content,
                "metadata": metadata or {},
                "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "access_count": 0,
                "last_accessed": None,
            }

            self._memories[memory_type].append(memory)
            logger.debug("Added %s memory: %s", memory_type.value, memory_id)

            return memory_id

    def retrieve_memory(
        self, query: str, memory_type: typing.Optional[MemoryType] = None, limit: int = 10
    ) -> typing.List[typing.Dict[str, typing.Any]]:
        """
        检索记忆

        参数:
            query: 查询
            memory_type: 记忆类型（可选）
            limit: 限制数量

        返回:
            List[Dict]: 记忆列表
        """
        with self._lock:
            results = []
            query_lower = query.lower()

            # 确定要搜索的记忆类型
            types_to_search = [memory_type] if memory_type else list(MemoryType)

            for mem_type in types_to_search:
                for memory in self._memories[mem_type]:
                    if query_lower in memory["content"].lower():
                        memory["access_count"] += 1
                        memory["last_accessed"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
                        results.append(memory)

            # 按访问次数排序
            results.sort(key=lambda x: x["access_count"], reverse=True)

            return results[:limit]

    def get_memories_by_type(self, memory_type: MemoryType) -> typing.List[typing.Dict[str, typing.Any]]:
        """
        按类型获取记忆

        参数:
            memory_type: 记忆类型

        返回:
            List[Dict]: 记忆列表
        """
        with self._lock:
            return self._memories[memory_type].copy()

    def clear_memories(self, memory_type: typing.Optional[MemoryType] = None) -> int:
        """
        清除记忆

        参数:
            memory_type: 记忆类型（可选，None 表示全部）

        返回:
            int: 清除的记忆数量
        """
        with self._lock:
            count = 0

            if memory_type:
                count = len(self._memories[memory_type])
                self._memories[memory_type] = []
            else:
                for mem_type in MemoryType:
                    count += len(self._memories[mem_type])
                    self._memories[mem_type] = []

            logger.info("Cleared %s memories", count)
            return count


# ────── 主类 ──────


class CognitionOrchestrator:
    """
    认知编排器

    实现认知周期：观察 → 回忆 → 推理 → 反思 → 巩固
    """

    def __init__(self, config: typing.Optional[typing.Dict[str, typing.Any]] = None):
        """
        初始化认知编排器

        参数:
            config: 配置字典
        """
        self._config = config or {}
        self._lock = threading.RLock()

        # 管理器
        self._attention_manager = AttentionManager()
        self._memory_manager = MemoryManager()

        # 状态
        self._cognitive_state = CognitiveState()
        self._cycle_count = 0

        # 依赖组件
        self._tool_memory_integration = None
        self._tool_router = None
        self._registry = None
        self._cerebellum = None
        self._brainstem = None
        self._multi_agent_manager = None

        # 元认知监控
        self._metacognition_enabled = False
        self._metacognition_monitor: typing.Optional[MetacognitionMonitor] = None

        logger.info("CognitionOrchestrator initialized")

    def set_tool_memory_integration(self, integration: typing.Any) -> None:
        """设置工具记忆集成"""
        self._tool_memory_integration = integration

    def set_tool_router(self, router: typing.Any) -> None:
        """设置工具路由器"""
        self._tool_router = router

    def update_cognitive_state(self, state: CognitiveState) -> None:
        """更新认知状态"""
        with self._lock:
            self._cognitive_state = state

    def get_cognitive_state(self) -> CognitiveState:
        """获取认知状态"""
        with self._lock:
            return copy.deepcopy(self._cognitive_state)

    def set_registry(self, registry: typing.Any) -> None:
        """设置注册表"""
        self._registry = registry

    def get_registry(self) -> typing.Any:
        """获取注册表"""
        return self._registry

    def get_attention_manager(self) -> AttentionManager:
        """获取注意力管理器"""
        return self._attention_manager

    def get_memory_manager(self) -> MemoryManager:
        """获取记忆管理器"""
        return self._memory_manager

    def select_skill_for_task(self, task: str) -> typing.Optional[typing.Any]:
        """
        为任务选择技能

        参数:
            task: 任务描述

        返回:
            Optional[Any]: 选中的技能
        """
        if not self._registry:
            return None

        # 简单的关键词匹配（实际实现可能使用更复杂的算法）
        task_lower = task.lower()
        best_skill = None
        best_score = 0

        for skill in self._registry.list_skills():
            score = 0
            if hasattr(skill, "keywords"):
                for keyword in skill.keywords:
                    if keyword.lower() in task_lower:
                        score += 1

            if score > best_score:
                best_score = score
                best_skill = skill

        return best_skill

    async def process_task(
        self, task: str, context: typing.Optional[typing.Dict[str, typing.Any]] = None
    ) -> typing.Dict[str, typing.Any]:
        """
        处理任务

        参数:
            task: 任务描述
            context: 上下文

        返回:
            Dict: 处理结果
        """
        start_time = time.time()

        try:
            # 执行认知周期
            cycle_result = await self.process_thought_cycle(task, context)

            # 选择技能
            skill = self.select_skill_for_task(task)

            duration_ms = (time.time() - start_time) * 1000

            return {
                "success": cycle_result.success,
                "task": task,
                "cycle_result": cycle_result.to_dict(),
                "selected_skill": skill.name if skill else None,
                "duration_ms": duration_ms,
            }

        except Exception as e:
            logger.error("Task processing failed: %s", e)
            return {
                "success": False,
                "task": task,
                "error": str(e),
                "duration_ms": (time.time() - start_time) * 1000,
            }

    async def process_thought_cycle(
        self, input_text: str, context: typing.Optional[typing.Dict[str, typing.Any]] = None
    ) -> CognitiveCycleResult:
        """
        处理思维周期

        参数:
            input_text: 输入文本
            context: 上下文

        返回:
            CognitiveCycleResult: 周期结果
        """
        import uuid

        start_time = time.time()
        cycle_id = str(uuid.uuid4())[:8]

        result = CognitiveCycleResult(cycle_id=cycle_id)

        try:
            # 1. 观察
            observations = await self._observe(input_text, context)
            result.observations = observations

            # 2. 回忆
            recalled = await self._recall(observations, context)
            result.recalled_memories = recalled

            # 3. 推理
            reasoning = await self._reason(observations, recalled, context)
            result.reasoning_steps = reasoning

            # 4. 发送到小脑（工具执行）
            tool_results = await self._send_to_cerebellum(reasoning, context)

            # 5. 反思
            reflections = await self._reflect(reasoning, tool_results, context)
            result.reflections = reflections

            # 6. 巩固
            consolidated = await self._consolidate(observations, reasoning, reflections, context)
            result.consolidated_memories = consolidated

            result.success = True
            result.duration_ms = (time.time() - start_time) * 1000

            # 更新周期计数
            self._cycle_count += 1

            logger.info("Thought cycle %s completed in %.1fms", cycle_id, result.duration_ms)

        except Exception as e:
            logger.error("Thought cycle failed: %s", e)
            result.success = False
            result.error = str(e)
            result.duration_ms = (time.time() - start_time) * 1000

        return result

    async def _observe(
        self, input_text: str, context: typing.Optional[typing.Dict[str, typing.Any]] = None
    ) -> typing.List[str]:
        """
        观察阶段

        参数:
            input_text: 输入文本
            context: 上下文

        返回:
            List[str]: 观察结果
        """
        observations = []

        # 提取关键信息
        words = input_text.split()
        observations.append(f"输入包含 {len(words)} 个词")

        # 检查上下文
        if context:
            observations.append(f"上下文包含 {len(context)} 个键")

        # 更新认知状态
        self._cognitive_state.current_focus = input_text[:100]
        self._cognitive_state.timestamp = datetime.datetime.now(datetime.timezone.utc)

        return observations

    async def _recall(
        self, observations: typing.List[str], context: typing.Optional[typing.Dict[str, typing.Any]] = None
    ) -> typing.List[str]:
        """
        回忆阶段

        参数:
            observations: 观察结果
            context: 上下文

        返回:
            List[str]: 回忆的记忆
        """
        recalled = []

        # 从记忆管理器检索
        for observation in observations:
            memories = self._memory_manager.retrieve_memory(observation, limit=3)
            for memory in memories:
                recalled.append(memory["content"])

        return recalled

    async def _reason(
        self,
        observations: typing.List[str],
        recalled: typing.List[str],
        context: typing.Optional[typing.Dict[str, typing.Any]] = None,
    ) -> typing.List[str]:
        """
        推理阶段

        参数:
            observations: 观察结果
            recalled: 回忆的记忆
            context: 上下文

        返回:
            List[str]: 推理步骤
        """
        reasoning = []

        # 基于观察和回忆进行推理
        reasoning.append(f"基于 {len(observations)} 个观察和 {len(recalled)} 个记忆进行推理")

        # 分析模式
        if recalled:
            reasoning.append("发现了相关记忆模式")

        # 生成结论
        reasoning.append("推理完成")

        return reasoning

    async def _send_to_cerebellum(
        self, reasoning: typing.List[str], context: typing.Optional[typing.Dict[str, typing.Any]] = None
    ) -> typing.List[str]:
        """
        发送到小脑（工具执行）

        参数:
            reasoning: 推理步骤
            context: 上下文

        返回:
            List[str]: 工具执行结果
        """
        tool_results = []

        if self._cerebellum:
            try:
                # 调用小脑执行工具
                if hasattr(self._cerebellum, "execute"):
                    result = await self._cerebellum.execute(reasoning, context)
                    tool_results.append(str(result))
            except Exception as e:
                logger.error("Cerebellum execution failed: %s", e)

        return tool_results

    async def _reflect(
        self,
        reasoning: typing.List[str],
        tool_results: typing.List[str],
        context: typing.Optional[typing.Dict[str, typing.Any]] = None,
    ) -> typing.List[str]:
        """
        反思阶段

        参数:
            reasoning: 推理步骤
            tool_results: 工具执行结果
            context: 上下文

        返回:
            List[str]: 反思结果
        """
        reflections = []

        # 评估推理过程
        reflections.append(f"推理过程包含 {len(reasoning)} 个步骤")

        # 评估工具执行
        if tool_results:
            reflections.append(f"工具执行产生 {len(tool_results)} 个结果")

        # 生成改进建议
        reflections.append("反思完成")

        return reflections

    async def _consolidate(
        self,
        observations: typing.List[str],
        reasoning: typing.List[str],
        reflections: typing.List[str],
        context: typing.Optional[typing.Dict[str, typing.Any]] = None,
    ) -> typing.List[str]:
        """
        巩固阶段

        参数:
            observations: 观察结果
            reasoning: 推理步骤
            reflections: 反思结果
            context: 上下文

        返回:
            List[str]: 巩固的记忆
        """
        consolidated = []

        # 将重要信息存入长期记忆
        for observation in observations:
            memory_id = self._memory_manager.add_memory(
                MemoryType.LONG_TERM, observation, {"type": "observation", "cycle": self._cycle_count}
            )
            consolidated.append(memory_id)

        for reflection in reflections:
            memory_id = self._memory_manager.add_memory(
                MemoryType.SEMANTIC, reflection, {"type": "reflection", "cycle": self._cycle_count}
            )
            consolidated.append(memory_id)

        return consolidated

    def enable_metacognition(self, enabled: bool = True) -> None:
        """
        启用/禁用元认知

        参数:
            enabled: 是否启用
        """
        self._metacognition_enabled = enabled

        if enabled and not self._metacognition_monitor:
            self._metacognition_monitor = MetacognitionMonitor(self)

        if self._metacognition_monitor:
            if enabled:
                self._metacognition_monitor.start_monitoring()
            else:
                self._metacognition_monitor.stop_monitoring()

    def get_metacognition_report(self) -> typing.Optional[typing.Dict[str, typing.Any]]:
        """
        获取元认知报告

        返回:
            Optional[Dict]: 元认知报告
        """
        if not self._metacognition_monitor:
            return None

        return self._metacognition_monitor.get_report()

    def save_state(self, path: typing.Union[str, Path]) -> bool:
        """
        保存状态

        参数:
            path: 保存路径

        返回:
            bool: 是否保存成功
        """
        try:
            state = {
                "cognitive_state": self._cognitive_state.to_dict(),
                "cycle_count": self._cycle_count,
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }

            with open(path, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)

            logger.info("State saved to %s", path)
            return True

        except Exception as e:
            logger.error("Failed to save state: %s", e)
            return False

    def load_state(self, path: typing.Union[str, Path]) -> bool:
        """
        加载状态

        参数:
            path: 加载路径

        返回:
            bool: 是否加载成功
        """
        try:
            with open(path, "r", encoding="utf-8") as f:
                state = json.load(f)

            # 恢复认知状态
            if "cognitive_state" in state:
                cs = state["cognitive_state"]
                self._cognitive_state = CognitiveState(
                    attention_level=AttentionLevel(cs.get("attention_level", "medium")),
                    active_memories=cs.get("active_memories", []),
                    current_focus=cs.get("current_focus", ""),
                    emotional_state=cs.get("emotional_state", "neutral"),
                    cognitive_load=cs.get("cognitive_load", 0.0),
                )

            self._cycle_count = state.get("cycle_count", 0)

            logger.info("State loaded from %s", path)
            return True

        except Exception as e:
            logger.error("Failed to load state: %s", e)
            return False

    def integrate_with_multi_agent_manager(self, manager: typing.Any) -> None:
        """
        与多代理管理器集成

        参数:
            manager: 多代理管理器
        """
        self._multi_agent_manager = manager
        logger.info("Integrated with multi-agent manager")

    def set_cerebellum(self, cerebellum: typing.Any) -> None:
        """设置小脑"""
        self._cerebellum = cerebellum

    def set_brainstem(self, brainstem: typing.Any) -> None:
        """设置脑干"""
        self._brainstem = brainstem

    def _update_integration_metadata(self, key: str, value: typing.Any) -> None:
        """更新集成元数据"""
        self._cognitive_state.metadata[key] = value


class MetacognitionMonitor:
    """
    元认知监控器

    监控认知过程，检测异常并生成报告。
    """

    def __init__(self, orchestrator: CognitionOrchestrator):
        """
        初始化元认知监控器

        参数:
            orchestrator: 认知编排器
        """
        self._orchestrator = orchestrator
        self._monitoring = False
        self._cycle_history: typing.List[typing.Dict[str, typing.Any]] = []
        self._alerts: typing.List[typing.Dict[str, typing.Any]] = []
        self._lock = threading.RLock()

        logger.info("MetacognitionMonitor initialized")

    def start_monitoring(self) -> None:
        """开始监控"""
        with self._lock:
            self._monitoring = True
            logger.info("Metacognition monitoring started")

    def stop_monitoring(self) -> None:
        """停止监控"""
        with self._lock:
            self._monitoring = False
            logger.info("Metacognition monitoring stopped")

    def record_cycle(self, cycle_result: CognitiveCycleResult) -> None:
        """
        记录周期

        参数:
            cycle_result: 周期结果
        """
        with self._lock:
            if not self._monitoring:
                return

            record = {
                "cycle_id": cycle_result.cycle_id,
                "success": cycle_result.success,
                "duration_ms": cycle_result.duration_ms,
                "timestamp": cycle_result.timestamp.isoformat(),
            }

            self._cycle_history.append(record)

            # 限制历史记录
            if len(self._cycle_history) > 100:
                self._cycle_history = self._cycle_history[-100:]

            # 检查异常
            self._check_anomalies(cycle_result)

    def _check_anomalies(self, cycle_result: CognitiveCycleResult) -> None:
        """
        检查异常

        参数:
            cycle_result: 周期结果
        """
        # 检查执行时间
        if cycle_result.duration_ms > 10000:  # 超过10秒
            self._add_alert("slow_cycle", f"Cycle {cycle_result.cycle_id} took {cycle_result.duration_ms:.1f}ms")

        # 检查失败
        if not cycle_result.success:
            self._add_alert("cycle_failed", f"Cycle {cycle_result.cycle_id} failed: {cycle_result.error}")

    def _add_alert(self, alert_type: str, message: str) -> None:
        """
        添加警报

        参数:
            alert_type: 警报类型
            message: 警报消息
        """
        alert = {
            "type": alert_type,
            "message": message,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }

        self._alerts.append(alert)
        logger.warning("Metacognition alert: %s - %s", alert_type, message)

    def get_report(self) -> typing.Dict[str, typing.Any]:
        """
        获取报告

        返回:
            Dict: 报告
        """
        with self._lock:
            total_cycles = len(self._cycle_history)
            successful_cycles = sum(1 for c in self._cycle_history if c["success"])
            avg_duration = 0.0

            if total_cycles > 0:
                avg_duration = sum(c["duration_ms"] for c in self._cycle_history) / total_cycles

            return {
                "monitoring": self._monitoring,
                "total_cycles": total_cycles,
                "successful_cycles": successful_cycles,
                "success_rate": successful_cycles / max(1, total_cycles),
                "average_duration_ms": avg_duration,
                "alerts": self._alerts[-10:],  # 最近10个警报
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }


# ────── 单例管理 ──────

_orchestrator_instance: typing.Optional[CognitionOrchestrator] = None
_instance_lock = threading.Lock()


def get_cognition_orchestrator(**kwargs) -> CognitionOrchestrator:
    """获取全局认知编排器实例"""
    global _orchestrator_instance
    if _orchestrator_instance is None:
        with _instance_lock:
            if _orchestrator_instance is None:
                _orchestrator_instance = CognitionOrchestrator(**kwargs)
    return _orchestrator_instance


def reset_cognition_orchestrator():
    """重置全局认知编排器实例"""
    global _orchestrator_instance
    with _instance_lock:
        _orchestrator_instance = None
