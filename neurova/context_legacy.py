from __future__ import annotations

"""
统一上下文注入系统 - Unified Context Injection System

核心功能:
1. 统一上下文注入标准 - 所有上下文注入走统一接口
2. reflection_log 注入 - 反思日志正确注入到系统提示
3. Token 预算管理 - 不超过 MAX_CONTEXT_TOKENS=4000
4. 高温记忆优先 - 温度>70的记忆优先注入
5. 智能压缩 - 分层压缩策略保证会话完整性

整合模块:
- ContextInjector - 检索上下文注入引擎
- ContextCompressor - 智能上下文压缩器
- ContextCache - 上下文缓存管理器
- GrowthLogManager - 反思日志管理器
- QuestionQueueManager - 问题队列管理器
"""

import datetime as dt  # 避免变量名冲突
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from neurova.cognitive_layers.meta_cognition_layer.growth_log import (
    GrowthLogManager,
    ReflectionLogStatus,
    ReflectionType,
)
from neurova.cognitive_layers.meta_cognition_layer.question_queue import (
    QuestionQueueManager,
)
from neurova.core.base_module import BaseModule

if TYPE_CHECKING:
    from neurova.cognitive_layers.memory_layer.manager import MemoryManager

logger = logging.getLogger(__name__)


class ContextPriority(Enum):
    """上下文优先级"""

    CRITICAL = 100  # 系统提示、固化记忆
    HIGH = 80  # 高温记忆、反思日志
    NORMAL = 50  # 普通记忆
    LOW = 20  # 低温记忆、归档内容


@dataclass
class TokenBudget:
    """Token 预算配置 - 增强版"""

    max_total: int = 16000
    system_prompt: int = 1500
    reflection_log: int = 1000
    memories: int = 4000
    conversation_history: int = 6000
    experience_knowledge: int = 1500
    emotion_context: int = 500

    @property
    def chinese_ratio(self) -> float:
        return 1.5

    @property
    def english_ratio(self) -> float:
        return 0.25


@dataclass
class ContextEntry:
    """上下文条目"""

    id: str
    content: str
    priority: ContextPriority
    category: str
    temperature: float = 50.0
    is_crystallized: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: dt.datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "content": self.content,
            "priority": self.priority.value,
            "category": self.category,
            "temperature": self.temperature,
            "is_crystallized": self.is_crystallized,
            "metadata": self.metadata,
            "created_at": self.created_at,
        }


@dataclass
class ContextBuildResult:
    """上下文构建结果"""

    context: List[Dict[str, str]]
    total_tokens: int
    compression_ratio: float
    reflection_count: int
    memory_count: int
    history_count: int
    stats: Dict[str, Any]


class UnifiedContextInjector(BaseModule):
    """
    统一上下文注入器

    职责:
    1. 整合所有上下文相关模块
    2. 实现统一的上下文注入标准
    3. 管理 Token 预算
    4. 高温记忆优先注入
    5. reflection_log 注入到系统提示
    """

    MODULE_ID = "context.unified_injector"
    MODULE_NAME = "UnifiedContextInjector"
    MODULE_VERSION = "1.0.0"

    def __init__(
        self,
        memory_manager: "MemoryManager",
        growth_log_manager: Optional[GrowthLogManager] = None,
        question_queue_manager: Optional[QuestionQueueManager] = None,
        token_budget: Optional[TokenBudget] = None,
        enable_cache: bool = True,
        enable_compression: bool = True,
        **kwargs,
    ):
        super().__init__(
            module_id=self.MODULE_ID,
            name=self.MODULE_NAME,
            version=self.MODULE_VERSION,
            description="统一上下文注入器 - 整合所有上下文注入逻辑",
            dependencies=["memory_manager"],
            **kwargs,
        )

        self._memory_manager = memory_manager
        self._growth_log_manager = growth_log_manager
        self._question_queue_manager = question_queue_manager
        self._token_budget = token_budget or TokenBudget()
        self._enable_cache = enable_cache
        self._enable_compression = enable_compression

        # 初始化智能压缩器
        if self._enable_compression:
            try:
                from neurova.context_compressor import SmartContextCompressor

                self._compressor = SmartContextCompressor()
                logger.info("SmartContextCompressor initialized")
            except Exception as e:
                logger.warning("SmartContextCompressor initialization failed: %s", e)
                self._compressor = None
        else:
            self._compressor = None

        self._cache: OrderedDict[str, ContextEntry] = OrderedDict()
        self._max_cache_entries = 100
        self._show_temperature = True
        self._show_confidence = True
        self._show_empathy = True

    async def on_initialize(self) -> None:
        """初始化钩子"""
        self.log_info("UnifiedContextInjector 初始化中...")

        self.subscribe_event("context.build", self._handle_build_request)
        self.subscribe_event("context.invalidate_cache", self._handle_cache_invalidate)
        self.subscribe_event("context.set_priority", self._handle_set_priority)

        self.log_info(
            "UnifiedContextInjector 初始化完成",
            {
                "max_total_tokens": self._token_budget.max_total,
                "enable_cache": self._enable_cache,
                "enable_compression": self._enable_compression,
            },
        )

    async def on_start(self) -> None:
        """启动钩子"""
        self.log_info("UnifiedContextInjector 启动")

    async def on_stop(self) -> None:
        """停止钩子"""
        self._flush_cache()
        self.log_info("UnifiedContextInjector 停止")

    def build_context(
        self,
        system_prompt: str,
        memories: List[Dict],
        conversation_history: List[Dict],
        user_input: str,
        agent_emotion: Optional[Dict] = None,
        include_reflection_log: bool = True,
        include_question_queue: bool = False,
        max_tokens: Optional[int] = None,
        experience: Optional[List[Dict]] = None,
    ) -> ContextBuildResult:
        """
        构建完整的上下文

        参数:
            system_prompt: 基础系统提示
            memories: 记忆列表
            conversation_history: 对话历史
            user_input: 用户输入
            agent_emotion: Agent 情感状态
            include_reflection_log: 是否包含反思日志
            include_question_queue: 是否包含问题队列
            max_tokens: 可选的最大token限制
            experience: 预检索的经验列表（Phase 4: 消除双重检索）

        返回:
            ContextBuildResult: 上下文构建结果
        """
        # 如果指定了max_tokens，使用它；否则使用预算上限
        effective_max = max_tokens if max_tokens is not None else self._token_budget.max_total

        # 动态调整各部分预算
        effective_budget = self._adjust_budget(conversation_history, memories, effective_max)

        # 临时替换预算
        original_budget = self._token_budget
        self._token_budget = effective_budget

        try:
            return self._build_context_internal(
                system_prompt,
                memories,
                conversation_history,
                user_input,
                agent_emotion,
                include_reflection_log,
                include_question_queue,
                experience,
            )
        finally:
            # 恢复原始预算
            self._token_budget = original_budget

    def _adjust_budget(self, history: List[Dict], memories: List[Dict], max_tokens: int) -> TokenBudget:
        """
        根据实际内容量动态调整Token预算

        策略：
        1. 如果内容量充足，按固定比例分配
        2. 如果总量不足，增加各部分上限
        3. 优先保证重要内容
        """
        # 计算各部分实际需求
        history_estimate = sum(self._count_tokens(m.get("content", "")) for m in history)
        memory_estimate = sum(self._count_tokens(m.get("content", "")) for m in memories)

        # 系统提示估算
        system_estimate = self._token_budget.system_prompt

        # 总需求
        total_needed = history_estimate + memory_estimate + system_estimate + 500  # 500为user_input预留

        # 如果总量充足，使用标准预算
        if total_needed <= max_tokens * 0.9:
            return self._token_budget

        # 总量不足，需要压缩
        # 计算压缩比例
        compression_ratio = (max_tokens * 0.9) / total_needed

        # 按优先级分配压缩后的预算
        # 1. 系统提示：不能压缩太多
        system_budget = max(int(self._token_budget.system_prompt * 0.8), 600)

        # 2. 记忆：中等压缩
        memory_budget = int(memory_estimate * compression_ratio) if memory_estimate > 0 else self._token_budget.memories

        # 3. 历史：主要压缩对象
        history_budget = max_tokens - system_budget - memory_budget - 500

        return TokenBudget(
            max_total=max_tokens,
            system_prompt=system_budget,
            reflection_log=self._token_budget.reflection_log,
            memories=memory_budget,
            conversation_history=history_budget,
        )

    def _build_context_internal(
        self,
        system_prompt: str,
        memories: List[Dict],
        conversation_history: List[Dict],
        user_input: str,
        agent_emotion: Optional[Dict] = None,
        include_reflection_log: bool = True,
        include_question_queue: bool = False,
        experience: Optional[List[Dict]] = None,
    ) -> ContextBuildResult:
        """
        内部上下文构建方法
        """
        start_time = time.time()


        reflection_content = ""
        if include_reflection_log and self._growth_log_manager:
            reflection_content = self._build_reflection_context()

        memory_content = self._build_memory_context(memories, user_input)

        # 构建经验上下文（Phase 4: 优先使用预检索的经验，消除双重检索）
        if experience is not None:
            experience_content = self._format_experience_from_list(experience)
        else:
            experience_content = self._build_experience_context(user_input)

        emotion_content = ""
        if agent_emotion and self._show_empathy:
            emotion_content = self._format_emotion(agent_emotion)

        system_content = self._build_system_prompt(
            base_prompt=system_prompt,
            reflection_content=reflection_content,
            memory_content=memory_content,
            emotion_content=emotion_content,
            experience_content=experience_content,
        )

        system_tokens = self._count_tokens(system_content)

        history = self._trim_history(conversation_history)
        history_tokens = sum(self._count_tokens(msg.get("content", "")) for msg in history)

        user_tokens = self._count_tokens(user_input)

        total_tokens = system_tokens + history_tokens + user_tokens

        compression_ratio = 1.0
        if total_tokens > self._token_budget.max_total and self._enable_compression:
            system_content, history, compression_ratio = self._compress_context(system_content, history, user_tokens)
            total_tokens = (
                self._count_tokens(system_content)
                + sum(self._count_tokens(msg.get("content", "")) for msg in history)
                + user_tokens
            )

        context = [{"role": "system", "content": system_content}]
        context.extend(history)
        context.append({"role": "user", "content": user_input})

        result = ContextBuildResult(
            context=context,
            total_tokens=total_tokens,
            compression_ratio=compression_ratio,
            reflection_count=1 if reflection_content else 0,
            memory_count=len(memories),
            history_count=len(history),
            stats={
                "system_tokens": system_tokens,
                "history_tokens": history_tokens,
                "user_tokens": user_tokens,
                "build_time_ms": int((time.time() - start_time) * 1000),
                "within_budget": total_tokens <= self._token_budget.max_total,
            },
        )

        self.log_info(
            "上下文构建完成",
            {
                "total_tokens": total_tokens,
                "within_budget": result.stats["within_budget"],
                "compression_ratio": compression_ratio,
            },
        )

        return result

    def _build_system_prompt(
        self,
        base_prompt: str,
        reflection_content: str = "",
        memory_content: str = "",
        emotion_content: str = "",
        experience_content: str = "",
    ) -> str:
        """构建系统提示"""
        parts = [base_prompt]

        if reflection_content:
            parts.append(f"\n## 反思日志\n{reflection_content}")

        if memory_content:
            parts.append(f"\n## 相关记忆\n{memory_content}")

        if experience_content:
            parts.append(f"\n## 相关经验\n{experience_content}")

        if emotion_content:
            parts.append(f"\n## 当前情感状态\n{emotion_content}")

        parts.append(f"\n## 当前时间\n{dt.datetime.now().strftime('%Y年%m月%d日 %H:%M')}")

        return "\n".join(parts)

    def _build_reflection_context(self) -> str:
        """构建反思日志上下文"""
        if not self._growth_log_manager:
            return ""

        try:
            logs = self._growth_log_manager.get_validated_logs(limit=3)
            if not logs:
                logs = self._growth_log_manager.get_pending_logs(limit=2)

            if not logs:
                return ""

            parts = []
            for log in logs:
                status_mark = "✓已验证" if log.status == ReflectionLogStatus.VALIDATED else "○待验证"
                parts.append(f"- [{status_mark}] {log.situation[:50]}... → {log.lesson[:30]}")

            return "\n".join(parts)

        except Exception as e:
            self.log_warning(f"构建反思日志上下文失败: {e}")
            return ""

    def _build_memory_context(self, memories: List[Dict], user_input: str = "") -> str:
        """
        构建记忆上下文 - 按分类优先级和话题相关性

        优化策略：
        1. 根据话题相关性排序
        2. 17种记忆分类优先级
        3. 按需注入，不过度填充
        """
        if not memories:
            return ""

        # 计算话题关键词
        topic_keywords = self._extract_keywords(user_input) if user_input else []

        # 按优先级和相关性排序
        scored_memories = []
        for mem in memories:
            # 基础分数：温度和固化状态
            base_score = 0
            if mem.get("is_crystallized"):
                base_score += 100  # 固化记忆最高优先级
            elif mem.get("is_important"):
                base_score += 80
            base_score += mem.get("temperature", 50) * 0.5

            # 相关性分数
            relevance_score = 0
            if topic_keywords:
                content = mem.get("content", "").lower()
                for keyword in topic_keywords:
                    if keyword.lower() in content:
                        relevance_score += 20

            # 分类优先级
            category_priority = self._get_category_priority(mem.get("category", ""))

            total_score = base_score + relevance_score + category_priority
            scored_memories.append((total_score, mem))

        # 排序
        scored_memories.sort(key=lambda x: x[0], reverse=True)

        # 构建上下文
        lines = []
        total_tokens = 0
        budget = self._token_budget.memories

        for score, mem in scored_memories:
            content = mem.get("content", "")
            mem_tokens = self._count_tokens(content)

            # 检查是否超过预算
            if total_tokens + mem_tokens > budget:
                # 尝试压缩这条记忆
                if len(lines) == 0:
                    # 第一条记忆就超预算，截断
                    truncated = content[: int(budget / self._token_budget.chinese_ratio)]
                    lines.append(f"- {truncated}... [已截断]")
                    total_tokens += self._count_tokens(lines[-1])
                break

            # 构建记忆行
            line = f"- {content}"

            # 添加标记
            if self._show_temperature:
                temp = mem.get("temperature", 50)
                if mem.get("is_crystallized"):
                    line += " 🔒"
                elif mem.get("is_important"):
                    line += f" ⭐ ({temp:.0f}°C)"
                elif temp > 70:
                    line += f" ({temp:.0f}°C)"

            # 添加分类标记
            category = mem.get("category", "")
            if category:
                category_emoji = self._get_category_emoji(category)
                line = f"{category_emoji} {line}"

            lines.append(line)
            total_tokens += mem_tokens

        return "\n".join(lines)

    def _extract_keywords(self, text: str, top_k: int = 5) -> List[str]:
        """提取关键词"""
        if not text:
            return []

        # 简单实现：提取长度>2的词
        words = []
        current = []
        for char in text:
            if "\u4e00" <= char <= "\u9fff":
                current.append(char)
                if len(current) >= 2:
                    words.append("".join(current))
                    current = current[-1:]
            else:
                current = []

        # 统计词频
        word_freq = {}
        for word in words:
            if len(word) >= 2:
                word_freq[word] = word_freq.get(word, 0) + 1

        # 返回top_k高频词
        sorted_words = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)
        return [w[0] for w in sorted_words[:top_k]]

    def _get_category_priority(self, category: str) -> float:
        """获取记忆分类的优先级"""
        priorities = {
            "profile": 50,  # 用户画像
            "task": 45,  # 任务
            "skill": 40,  # 技能
            "identity": 40,  # 身份
            "core_command": 50,  # 核心指令
            "lesson": 35,  # 教训
            "experience": 30,  # 经验
            "fact": 25,  # 事实
            "relationship": 20,  # 关系
            "emotional": 20,  # 情感
            "conversation": 15,  # 对话
            "reflection_log": 30,  # 反思
            "creative": 15,  # 创意
        }
        return priorities.get(category.lower(), 10)

    def _get_category_emoji(self, category: str) -> str:
        """获取记忆分类的emoji标记"""
        emojis = {
            "profile": "👤",
            "task": "📋",
            "skill": "🎯",
            "identity": "🆔",
            "core_command": "⚡",
            "lesson": "📝",
            "experience": "💡",
            "fact": "📚",
            "relationship": "🔗",
            "emotional": "💭",
            "conversation": "💬",
            "reflection_log": "🔄",
            "creative": "✨",
        }
        return emojis.get(category.lower(), "📌")

    def _build_experience_context(self, query: str = "") -> str:
        """构建经验上下文 - 从经验知识库中检索相关经验"""
        if not query:
            return ""

        try:
            from neurova.skills.experience_knowledge_base import ExperienceKnowledgeBase

            # 创建经验知识库实例
            ekb = ExperienceKnowledgeBase()

            # 查找相似经验
            similar = ekb.find_similar_experiences(query, top_k=3)

            if not similar:
                return ""

            parts = ["\n## 相关经验"]
            for exp in similar[:3]:  # 最多显示3条
                context_summary = exp.get("context", "")[:50]
                result_summary = exp.get("result", "")[:50]
                success_mark = "✓" if exp.get("success") else "✗"
                parts.append(f"{success_mark} {context_summary} → {result_summary}")

            return "\n".join(parts)

        except Exception as e:
            self.log_warning(f"构建经验上下文失败: {e}")
            return ""

    def _format_experience_from_list(self, experiences: List[Dict]) -> str:
        """
        从预检索的经验列表格式化经验上下文（Phase 4: 消除双重检索）。

        Args:
            experiences: 预检索的经验列表，每个字典应包含：
                - context: 经验上下文描述
                - result: 经验结果
                - success: 是否成功（布尔值）
                - 其他可选字段

        Returns:
            格式化的经验上下文字符串
        """
        if not experiences:
            return ""

        try:
            parts = []
            for exp in experiences[:3]:  # 最多显示3条
                context_summary = exp.get("context", "")[:50]
                result_summary = exp.get("result", "")[:50]
                success_mark = "✓" if exp.get("success") else "✗"
                parts.append(f"{success_mark} {context_summary} → {result_summary}")

            return "\n".join(parts)

        except Exception as e:
            self.log_warning(f"格式化经验列表失败: {e}")
            return ""

    def _format_emotion(self, emotion: Dict) -> str:
        """格式化情感状态"""
        emotions = []
        for emotion_type, intensity in emotion.items():
            if intensity > 0.3:
                emojis = {
                    "joy": "😊",
                    "sadness": "😢",
                    "anger": "😠",
                    "fear": "😨",
                    "surprise": "😲",
                    "neutral": "😐",
                    "hope": "🌟",
                }
                emoji = emojis.get(emotion_type, "")
                emotions.append(f"{emoji} {emotion_type}: {intensity * 100:.0f}%%")

        return " | ".join(emotions) if emotions else "😐 neutral"

    def _trim_history(self, history: List[Dict]) -> List[Dict]:
        """在 Token 预算内裁剪历史"""
        if not history:
            return []

        trimmed = []
        total_tokens = 0
        budget = self._token_budget.conversation_history

        for msg in reversed(history):
            msg_tokens = self._count_tokens(msg.get("content", ""))
            if total_tokens + msg_tokens <= budget:
                trimmed.insert(0, msg)
                total_tokens += msg_tokens
            else:
                if not trimmed:
                    trimmed.insert(0, msg)
                break

        return trimmed

    def _compress_context(self, system_content: str, history: List[Dict], user_tokens: int) -> tuple:
        """压缩上下文 - 使用SmartContextCompressor"""
        # 如果压缩器不可用，使用简单压缩
        if not self._compressor:
            return self._simple_compress(system_content, history, user_tokens)

        try:
            # 准备记忆列表（从system_content中提取）
            memories = []
            if "## 相关记忆" in system_content:
                memory_lines = system_content.split("## 相关记忆")[1].split("\n")
                for line in memory_lines:
                    if line.strip() and line.strip().startswith("- "):
                        memories.append({"content": line[2:].strip()})

            # 使用SmartContextCompressor
            result = self._compressor.compress_context(
                system_prompt=system_content,
                memories=memories,
                conversation_history=history,
                user_input="",  # user_input会在后面添加
                current_tokens=None,
            )

            compressed_context = result["context"]

            # 从压缩后的上下文中提取system_content和history
            if compressed_context and len(compressed_context) > 0:
                system_content = compressed_context[0].get("content", system_content)
                history = compressed_context[1:-1] if len(compressed_context) > 1 else []

            compression_ratio = result["stats"].get("compression_ratio", 1.0)

            return system_content, history, compression_ratio

        except Exception as e:
            logger.warning("Smart compression failed, using simple compression: %s", e)
            return self._simple_compress(system_content, history, user_tokens)

    def _simple_compress(self, system_content: str, history: List[Dict], user_tokens: int) -> tuple:
        """简单压缩（降级方案）"""
        available_budget = self._token_budget.max_total - user_tokens
        system_budget = min(self._token_budget.system_prompt, available_budget // 2)

        if self._count_tokens(system_content) > system_budget:
            system_content = self._truncate_text(system_content, system_budget)

        history_budget = available_budget - self._count_tokens(system_content)
        compressed_history = []
        total_tokens = 0

        for msg in reversed(history):
            msg_tokens = self._count_tokens(msg.get("content", ""))
            if total_tokens + msg_tokens <= history_budget:
                compressed_history.insert(0, msg)
                total_tokens += msg_tokens
            else:
                break

        if len(history) > len(compressed_history):
            kept_count = len(compressed_history)
            dropped_count = len(history) - kept_count
            summary_tokens = min(100, history_budget - total_tokens)
            summary_content = f"[对话摘要: 省略了{dropped_count}轮对话]"
            compressed_history.insert(0, {"role": "system", "content": summary_content[:summary_tokens]})

        ratio = (self._count_tokens(system_content) + total_tokens + user_tokens) / (self._token_budget.max_total + 1)

        return system_content, compressed_history, min(1.0, ratio)

    def _truncate_text(self, text: str, max_tokens: int) -> str:
        """截断文本到指定 token 数"""
        chars_per_token = 1.5
        max_chars = int(max_tokens * chars_per_token)

        if len(text) <= max_chars:
            return text

        return text[:max_chars] + "\n...[已截断]"

    def _count_tokens(self, text: str) -> int:
        """估算 Token 数"""
        if not text:
            return 0

        chinese_chars = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
        other_chars = len(text) - chinese_chars

        return int(chinese_chars * self._token_budget.chinese_ratio + other_chars * self._token_budget.english_ratio)

    def retrieve_memories(self, query: str, limit: int = 10, prioritize_high_temp: bool = True) -> List[Dict]:
        """检索相关记忆"""
        try:
            query_memories = self._memory_manager.recall(query=query, limit=limit)

            hot_memories = []
            crystallized = []

            try:
                all_memories = self._memory_manager.get_memories(limit=100)
                hot_memories = [
                    m for m in all_memories if not m.get("is_crystallized", False) and m.get("temperature", 50) > 70
                ][:3]
                crystallized = [m for m in all_memories if m.get("is_crystallized", False)][:5]
            except Exception:
                pass

            seen_ids = set()
            all_memories = []
            for mem in query_memories + hot_memories + crystallized:
                mem_id = mem.get("id", "")
                if mem_id and mem_id not in seen_ids:
                    seen_ids.add(mem_id)
                    all_memories.append(mem)

            if prioritize_high_temp:
                all_memories.sort(
                    key=lambda m: (m.get("is_crystallized", False), m.get("temperature", 50)), reverse=True
                )

            return all_memories[:limit]

        except Exception as e:
            self.log_error(f"检索记忆失败: {e}")
            return []

    def get_reflection_logs_for_context(
        self, focus_types: Optional[List[ReflectionType]] = None, limit: int = 5
    ) -> str:
        """获取用于上下文的反思日志"""
        if not self._growth_log_manager:
            return ""

        try:
            if focus_types:
                logs = []
                for ft in focus_types:
                    logs.extend(self._growth_log_manager.get_validated_logs(limit=limit))
                    logs.extend(self._growth_log_manager.get_pending_logs(limit=2))
                logs = logs[:limit]
            else:
                logs = self._growth_log_manager.get_validated_logs(limit=limit)
                if len(logs) < limit:
                    logs.extend(self._growth_log_manager.get_pending_logs(limit=limit - len(logs)))

            if not logs:
                return ""

            parts = ["[反思日志上下文]\n"]
            for log in logs:
                status_mark = "✓" if log.status == ReflectionLogStatus.VALIDATED else "○"
                parts.append(f"\n{status_mark} [{log.reflection_type.value}] {log.lesson}")

            return "".join(parts)

        except Exception as e:
            self.log_warning(f"获取反思日志上下文失败: {e}")
            return ""

    def get_questions_for_context(self, limit: int = 3) -> str:
        """获取待提问的问题"""
        if not self._question_queue_manager:
            return ""

        try:
            questions = self._question_queue_manager.get_pending_questions()
            if not questions:
                return ""

            parts = ["[待探索问题]\n"]
            for q in questions[:limit]:
                parts.append(f"- {q.content}")

            return "".join(parts)

        except Exception as e:
            self.log_warning(f"获取问题队列上下文失败: {e}")
            return ""

    def cache_entry(self, key: str, entry: ContextEntry) -> None:
        """缓存上下文条目"""
        if not self._enable_cache:
            return

        if key in self._cache:
            self._cache.move_to_end(key)
        else:
            if len(self._cache) >= self._max_cache_entries:
                self._cache.popitem(last=False)
            self._cache[key] = entry

    def get_cached_entry(self, key: str) -> Optional[ContextEntry]:
        """获取缓存的上下文条目"""
        if not self._enable_cache:
            return None

        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]

        return None

    def _flush_cache(self) -> None:
        """刷新缓存"""
        if self._enable_cache:
            self._cache.clear()
            self.log_info("上下文缓存已刷新")

    async def _handle_build_request(self, data: Dict[str, Any]) -> None:
        """处理上下文构建请求"""
        try:
            result = self.build_context(
                system_prompt=data.get("system_prompt", ""),
                memories=data.get("memories", []),
                conversation_history=data.get("conversation_history", []),
                user_input=data.get("user_input", ""),
                agent_emotion=data.get("agent_emotion"),
                include_reflection_log=data.get("include_reflection_log", True),
            )

            self.emit_event(
                "context.built",
                {
                    "total_tokens": result.total_tokens,
                    "within_budget": result.stats["within_budget"],
                },
            )

        except Exception as e:
            self.log_error(f"处理上下文构建请求失败: {e}")

    async def _handle_cache_invalidate(self, data: Dict[str, Any]) -> None:
        """处理缓存失效请求"""
        key = data.get("key")
        if key:
            self._cache.pop(key, None)
        else:
            self._flush_cache()

    async def _handle_set_priority(self, data: Dict[str, Any]) -> None:
        """处理设置优先级请求"""
        context_type = data.get("type")
        priority = data.get("priority")

        if context_type == "temperature":
            self._show_temperature = priority
        elif context_type == "confidence":
            self._show_confidence = priority
        elif context_type == "empathy":
            self._show_empathy = priority


def create_unified_context_injector(
    memory_manager: "MemoryManager",
    growth_log_manager: Optional[GrowthLogManager] = None,
    question_queue_manager: Optional[QuestionQueueManager] = None,
    max_tokens: int = 16000,
    **kwargs,
) -> UnifiedContextInjector:
    """
    创建统一上下文注入器工厂函数

    参数:
        memory_manager: 记忆管理器
        growth_log_manager: 反思日志管理器
        question_queue_manager: 问题队列管理器
        max_tokens: 最大 token 数
        **kwargs: 其他配置参数

    返回:
        UnifiedContextInjector 实例
    """
    token_budget = TokenBudget(max_total=max_tokens)

    return UnifiedContextInjector(
        memory_manager=memory_manager,
        growth_log_manager=growth_log_manager,
        question_queue_manager=question_queue_manager,
        token_budget=token_budget,
        **kwargs,
    )


class ContextBuilder:
    """
    上下文构建器 - 兼容旧接口

    Phase 6 简化：当 UnifiedContextInjector 可用时，ContextBuilder 成为纯代理。
    所有重复方法已移除，统一委托给 injector。
    """

    MAX_CONTEXT_TOKENS = 16000  # 与 UnifiedContextInjector 保持一致

    def __init__(self, config: Dict = None, unified_injector: Optional[UnifiedContextInjector] = None):
        self.config = config or {}
        self._unified_injector = unified_injector

        if not self._unified_injector:
            logger.warning("ContextBuilder: UnifiedContextInjector 未提供，使用降级模式")

    def build_context(
        self,
        system_prompt: str,
        memories: List[Dict],
        conversation_history: List[Dict],
        user_input: str,
        agent_emotion: Optional[Dict] = None,
        experience: Optional[List[Dict]] = None,
    ) -> List[Dict]:
        """
        构建完整上下文。

        Phase 6: 统一委托给 UnifiedContextInjector。
        """
        if self._unified_injector:
            result = self._unified_injector.build_context(
                system_prompt=system_prompt,
                memories=memories,
                conversation_history=conversation_history,
                user_input=user_input,
                agent_emotion=agent_emotion,
                experience=experience,
            )
            return result.context

        # 降级模式：直接使用 injector 的静态方法
        return self._fallback_build_context(system_prompt, memories, conversation_history, user_input, agent_emotion)

    def build_from_pool(
        self,
        candidate_pool: list,
        token_budget: Optional[TokenBudget] = None,
        conversation_history: Optional[List[Dict]] = None,
        user_input: str = "",
    ) -> List[Dict]:
        """
        从候选池构建上下文（Phase 3 新增接口）。

        流水线: candidate_pool → classify → summarize → select → format

        Phase 6: 统一委托给 UnifiedContextInjector。
        """
        from neurova.context_pool import ContextPoolUtils, ContextSource

        if self._unified_injector:
            # 有 injector 时：从候选池提取信息，委托给 injector
            system_prompt = self._extract_from_pool(candidate_pool, ContextSource.SYSTEM_INSTRUCTION)
            developer_instr = self._extract_from_pool(candidate_pool, ContextSource.DEVELOPER_INSTRUCTION)
            if developer_instr:
                system_prompt += "\n\n## 行为规则\n" + developer_instr

            memories = self._extract_memory_dicts_from_pool(candidate_pool)
            emotion = self._extract_emotion_from_pool(candidate_pool)
            experience = self._extract_experience_dicts_from_pool(candidate_pool)

            result = self._unified_injector.build_context(
                system_prompt=system_prompt,
                memories=memories,
                conversation_history=conversation_history or [],
                user_input=user_input,
                agent_emotion=emotion,
                experience=experience,
            )
            return result.context

        # 降级模式：从候选池直接构建
        budget = token_budget or TokenBudget(max_total=self.MAX_CONTEXT_TOKENS)

        # 按优先级排序
        sorted_pool = ContextPoolUtils.sort_by_priority(candidate_pool)

        # 分离 system 内容和 history
        system_parts: list[str] = []
        history_items: list[str] = []

        for item in sorted_pool:
            if item.source in (
                ContextSource.SYSTEM_INSTRUCTION,
                ContextSource.DEVELOPER_INSTRUCTION,
                ContextSource.MEMORY,
                ContextSource.EXPERIENCE,
                ContextSource.REFLECTION_LOG,
                ContextSource.EMOTION,
                ContextSource.TOOL_MEMORY,
                ContextSource.RUNTIME_METADATA,
            ):
                section_name = self._source_to_section_name(item.source)
                system_parts.append(f"\n## {section_name}\n{item.content}")
            elif item.source == ContextSource.CONVERSATION_HISTORY:
                history_items.append(item.content)

        system_content = "\n".join(system_parts)
        if not system_content:
            system_content = "You are a helpful assistant."

        context = [{"role": "system", "content": system_content}]
        # 对话历史
        if conversation_history:
            context.extend(conversation_history)
        else:
            for i, content in enumerate(history_items):
                role = "user" if i % 2 == 0 else "assistant"
                context.append({"role": role, "content": content})
        context.append({"role": "user", "content": user_input})

        return context

    def _extract_from_pool(self, pool: list, source) -> str:
        """从候选池中提取指定来源的内容，拼接为字符串"""
        parts = []
        for item in pool:
            if item.source == source:
                parts.append(item.content)
        return "\n\n".join(parts)

    def _extract_memory_dicts_from_pool(self, pool: list) -> List[Dict]:
        """从候选池中提取记忆条目，还原为 dict 格式"""
        from neurova.context_pool import ContextSource

        memories = []
        for item in pool:
            if item.source == ContextSource.MEMORY:
                memories.append(
                    {
                        "content": item.content,
                        "temperature": item.metadata.get("temperature", 50),
                        "is_crystallized": item.metadata.get("is_crystallized", False),
                        "is_important": item.metadata.get("is_important", False),
                        "category": item.metadata.get("category", ""),
                    }
                )
        return memories

    def _extract_emotion_from_pool(self, pool: list) -> Optional[Dict]:
        """从候选池中提取情感状态"""
        from neurova.context_pool import ContextSource

        for item in pool:
            if item.source == ContextSource.EMOTION:
                return {
                    "label": item.metadata.get("label", "neutral"),
                    "intensity": item.metadata.get("intensity", 0),
                }
        return None

    def _extract_experience_dicts_from_pool(self, pool: list) -> List[Dict]:
        """从候选池中提取经验条目，还原为 dict 格式"""
        from neurova.context_pool import ContextSource

        experiences = []
        for item in pool:
            if item.source == ContextSource.EXPERIENCE:
                experiences.append(
                    {
                        "context": item.content[:100],  # 使用内容作为上下文摘要
                        "result": item.metadata.get("result", ""),
                        "success": item.metadata.get("success", True),
                        "lesson": item.metadata.get("lesson", ""),
                        "confidence": item.metadata.get("confidence", 1.0),
                    }
                )
        return experiences

    @staticmethod
    def _source_to_section_name(source) -> str:
        """将 ContextSource 映射为 section 标题"""
        from neurova.context_pool import ContextSource

        mapping = {
            ContextSource.SYSTEM_INSTRUCTION: "系统指令",
            ContextSource.DEVELOPER_INSTRUCTION: "行为规则",
            ContextSource.MEMORY: "相关记忆",
            ContextSource.EXPERIENCE: "相关经验",
            ContextSource.REFLECTION_LOG: "反思日志",
            ContextSource.EMOTION: "当前情感状态",
            ContextSource.TOOL_MEMORY: "工具记忆",
            ContextSource.RUNTIME_METADATA: "运行时信息",
        }
        return mapping.get(source, source.value)

    def _fallback_build_context(
        self,
        system_prompt: str,
        memories: List[Dict],
        conversation_history: List[Dict],
        user_input: str,
        agent_emotion: Optional[Dict] = None,
    ) -> List[Dict]:
        """
        降级模式：无 injector 时的简单上下文构建。

        注意：这是临时降级方案，生产环境应确保 injector 可用。
        """
        from neurova.context import TokenBudget, UnifiedContextInjector

        # 创建临时 injector
        temp_injector = UnifiedContextInjector(
            memory_manager=None, token_budget=TokenBudget(max_total=self.MAX_CONTEXT_TOKENS)  # 无记忆管理器
        )

        result = temp_injector.build_context(
            system_prompt=system_prompt,
            memories=memories,
            conversation_history=conversation_history,
            user_input=user_input,
            agent_emotion=agent_emotion,
        )
        return result.context

    def _fallback_compress(self, context: List[Dict]) -> List[Dict]:
        """
        降级模式：简单压缩。

        注意：这是临时降级方案，生产环境应确保 injector 可用。
        """
        from neurova.context import TokenBudget, UnifiedContextInjector

        # 创建临时 injector
        temp_injector = UnifiedContextInjector(
            memory_manager=None, token_budget=TokenBudget(max_total=self.MAX_CONTEXT_TOKENS)
        )

        # 计算总 tokens
        total_tokens = sum(temp_injector._count_tokens(msg.get("content", "")) for msg in context)

        if total_tokens <= self.MAX_CONTEXT_TOKENS:
            return context

        # 需要压缩：使用 injector 的压缩逻辑
        system_msg = context[0]
        user_msg = context[-1]
        history = context[1:-1]

        # 简单截断历史
        trimmed_history = temp_injector._trim_history(history)

        return [system_msg] + trimmed_history + [user_msg]

    # ══════════════════════════════════════════════════════════════
    # 新接口：深度模块设计
    # ══════════════════════════════════════════════════════════════

    def build_context_v2(
        self,
        user_input: str,
        session: Optional[Dict] = None,
        options: Optional[Dict] = None,
    ) -> List[Dict]:
        """
        深度模块接口：简化上下文构建

        参数:
            user_input: 用户输入（必需）
            session: 会话信息（可选）
                - conversation_history: 对话历史
                - user_id: 用户ID
                - agent_id: Agent ID
                - metadata: 其他元数据
            options: 配置选项（可选）
                - include_reflection_log: 是否包含反思日志（默认True）
                - include_question_queue: 是否包含问题队列（默认False）
                - max_tokens: 最大token数
                - tool_memory_result: 工具记忆结果
                - experience_items: 经验项目
                - system_prompt: 自定义系统提示

        返回:
            List[Dict]: 上下文消息列表

        设计原则:
        - 最小参数：只需 user_input
        - 会话封装：session 包含所有上下文信息
        - 内部自治：自动检索记忆、分析情感、管理token
        """
        # 解析参数
        session = session or {}
        options = options or {}

        # 提取会话信息
        conversation_history = session.get("conversation_history", [])
        user_id = session.get("user_id")
        session.get("agent_id")
        metadata = session.get("metadata", {})

        # 提取选项
        include_reflection_log = options.get("include_reflection_log", True)
        include_question_queue = options.get("include_question_queue", False)
        max_tokens = options.get("max_tokens")
        tool_memory_result = options.get("tool_memory_result")
        experience_items = options.get("experience_items")
        system_prompt = options.get("system_prompt", self._get_default_system_prompt())

        # 自动检索记忆
        memories = self._auto_retrieve_memories(user_input, user_id)

        # 自动分析情感
        agent_emotion = self._analyze_emotion(user_input, metadata)

        # 合并工具记忆
        if tool_memory_result:
            memories = self._merge_tool_memory(memories, tool_memory_result)

        # 调用内部实现
        if self._unified_injector:
            result = self._unified_injector.build_context(
                system_prompt=system_prompt,
                memories=memories,
                conversation_history=conversation_history,
                user_input=user_input,
                agent_emotion=agent_emotion,
                include_reflection_log=include_reflection_log,
                include_question_queue=include_question_queue,
                max_tokens=max_tokens,
                experience=experience_items,
            )
            return result.context

        # 降级模式
        return self._fallback_build_context(system_prompt, memories, conversation_history, user_input, agent_emotion)

    def _get_default_system_prompt(self) -> str:
        """获取默认系统提示"""
        return "你是一个友好的AI助手，能够帮助用户解决各种问题。"

    def _auto_retrieve_memories(self, user_input: str, user_id: Optional[str] = None) -> List[Dict]:
        """自动检索相关记忆"""
        if not self._unified_injector or not self._unified_injector._memory_manager:
            return []

        try:
            # 使用记忆管理器检索相关记忆
            memory_manager = self._unified_injector._memory_manager
            memories = memory_manager.retrieve_memories(
                query=user_input,
                user_id=user_id,
                limit=10,
            )
            return memories or []
        except Exception as e:
            logger.warning("自动记忆检索失败: %s", e)
            return []

    def _analyze_emotion(self, user_input: str, metadata: Dict) -> Optional[Dict]:
        """分析用户情感"""
        # 简单的情感分析逻辑
        # 实际实现可以使用更复杂的情感分析模型
        emotion_keywords = {
            "joy": ["开心", "高兴", "快乐", "喜欢", "好"],
            "sadness": ["难过", "伤心", "失望", "不好"],
            "anger": ["生气", "愤怒", "讨厌", "烦"],
            "neutral": ["你好", "请问", "怎么", "什么"],
        }

        user_input_lower = user_input.lower()

        for emotion_type, keywords in emotion_keywords.items():
            for keyword in keywords:
                if keyword in user_input_lower:
                    # 返回符合 _format_emotion 期望的格式
                    return {emotion_type: 0.7}

        return None

    def _merge_tool_memory(self, memories: List[Dict], tool_memory_result: Dict) -> List[Dict]:
        """合并工具记忆到记忆列表"""
        if not tool_memory_result:
            return memories

        # 提取工具记忆
        tool_memories = tool_memory_result.get("memories", [])
        if not tool_memories:
            return memories

        # 合并并去重
        merged = memories.copy()
        for tool_mem in tool_memories:
            # 检查是否已存在
            if not any(m.get("content") == tool_mem.get("content") for m in merged):
                merged.append(tool_mem)

        return merged
