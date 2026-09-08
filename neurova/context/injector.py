from __future__ import annotations

"""
统一上下文注入器 - Unified Context Injector

核心功能:
1. 统一上下文注入标准 - 所有上下文注入走统一接口
2. reflection_log 注入 - 反思日志正确注入到系统提示
3. Token 预算管理
4. 高温记忆优先注入
5. 智能压缩 - 分层压缩策略保证会话完整性
"""

import datetime as dt
import logging
from neurova.core.logger import get_logger
import time
from collections import OrderedDict
from typing import TYPE_CHECKING, Any, Dict, List, Optional

# 导入统一的 Token 估算器
from .token_estimator import EstimationStrategy, TokenEstimator

# 批次 A：动态上下文信封（五段动态内容+分钟级时间迁出 system）
from .envelope import compress_envelope, build_envelope, build_time_block

# BaseModule 可能不可用（当 neurova.core 只有 .pyc 文件时），提供降级方案
try:
    from neurova.core.base_module import BaseModule

    _BASE_MODULE_AVAILABLE = True
except (ImportError, ModuleNotFoundError):
    _BASE_MODULE_AVAILABLE = False
    _Event = None

    class BaseModule:
        """BaseModule 降级替代品 — 提供基本的日志和事件接口"""

        MODULE_ID = ""
        MODULE_NAME = ""
        MODULE_VERSION = ""

        def __init__(self, module_id="", name="", version="", description="", dependencies=None, **kwargs):
            self._module_id = module_id
            self._module_name = name
            self._module_version = version
            # 原代码写成 _logging（下划线前缀），模块中只有 logging，
            # 一旦 BaseModule 走降级分支就会 NameError。
            self._logger = logging.getLogger(f"neurova.{module_id}" if module_id else __name__)
            self._event_handlers = {}

        def log_info(self, msg, data=None):
            self._logger.info(msg)

        def log_warning(self, msg, data=None):
            self._logger.warning(msg)

        def log_error(self, msg, data=None):
            self._logger.error(msg)

        def subscribe_event(self, event_name, handler):
            self._event_handlers.setdefault(event_name, []).append(handler)

        def emit_event(self, event_name, data=None):
            for handler in self._event_handlers.get(event_name, []):
                try:
                    handler(data)
                except Exception:
                    pass


try:
    from neurova.cognitive_layers.memory_layer.models import Memory, MemoryCategory
except (ImportError, ModuleNotFoundError):
    MemoryCategory = None
    Memory = None

try:
    from neurova.cognitive_layers.meta_cognition_layer.growth_log import (
        GrowthLogManager,
        ReflectionLogStatus,
        ReflectionType,
    )
except (ImportError, ModuleNotFoundError):
    GrowthLogManager = None
    ReflectionType = None
    ReflectionLogStatus = None

try:
    from neurova.cognitive_layers.meta_cognition_layer.question_queue import (
        QuestionEntry,
        QuestionQueueManager,
        QuestionStatus,
    )
except (ImportError, ModuleNotFoundError):
    QuestionQueueManager = None
    QuestionEntry = None
    QuestionStatus = None

from .models import ContextBuildResult, ContextEntry, TokenBudget

if TYPE_CHECKING:
    from neurova.cognitive_layers.memory_layer.manager import MemoryManager

logger = get_logger(__name__)


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
        # V3 自模型：教训注入的 agent 归属（kwargs 可选；未设置则不注入）
        self._metacog_agent_id = kwargs.pop("metacog_agent_id", None)
        self._token_budget = token_budget or TokenBudget()
        self._enable_cache = enable_cache
        self._enable_compression = enable_compression

        # 初始化统一的 Token 估算器
        self._token_estimator = TokenEstimator(EstimationStrategy.BALANCED)

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
        # F6：从 agent config 读取（缺省 True 保持行为不变）；运行时仍可经
        # context.set_priority 事件调整（_handle_set_priority）
        self._show_empathy = bool(kwargs.pop("show_empathy", True))

    async def on_initialize(self) -> None:
        """初始化钩子"""
        self.log_info("UnifiedContextInjector 初始化中...")

        self.subscribe_event("context.build", self._handle_build_request)
        self.subscribe_event("context.invalidate_cache", self._handle_cache_invalidate)
        self.subscribe_event("context.set_priority", self._handle_set_priority)

        self.log_info(
            "UnifiedContextInjector 初始化完成 "
            f"(max_total_tokens={self._token_budget.max_total}, "
            f"enable_cache={self._enable_cache}, enable_compression={self._enable_compression})"
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

        # 2. 记忆：按比例缩放，但设下限——
        #    遗留①：小占比记忆（如 9 tokens vs 48000 历史）被比例缩水到
        #    自身 token 以下，_build_memory_context 把记忆截成碎屑，截出
        #    的量被历史预算吞掉（纯损毁零收益）。下限 = max(自身估算,
        #    max_tokens/10)：小记忆保自身，大记忆保 10% 窗口。
        memory_own_estimate = memory_estimate if memory_estimate > 0 else self._token_budget.memories
        memory_budget = max(
            int(memory_own_estimate * compression_ratio),
            min(memory_own_estimate, max_tokens // 10),
        )

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

        # V3 自模型：结构化教训（agent_id 经 kwargs 注入；缺省跳过——零行为变化）
        metacog_content = ""
        if getattr(self, "_metacog_agent_id", None):
            metacog_content = self._build_metacog_lessons(self._metacog_agent_id)

        memory_content = self._build_memory_context(memories, user_input)

        # 构建经验上下文（Phase 4: 优先使用预检索的经验，消除双重检索）
        # 断链修复（闭环审计 2026-09-04）：主链路恒传 []（非 None），`is not None`
        # 判定使 EKB 查询成为不可达分支——EKB 每轮写入却永不复用（写了没人读）。
        # 空列表/None 均回退按需查 EKB；非空列表（池预检索命中）维持跳过二次查询。
        if experience:
            experience_content = self._format_experience_from_list(experience)
        else:
            experience_content = self._build_experience_context(user_input)

        emotion_content = ""
        if agent_emotion and self._show_empathy:
            emotion_content = self._format_emotion(agent_emotion)

        # 批次 A（docs/04-plans/2026-09-07-提示词与工具面升级实施方案.md）：
        # 五段动态内容 + 分钟级时间不再拼进 system 消息，改为瞬态信封挂在末条
        # user 消息上——system 会话内字节级稳定（前缀缓存硬判据），且免疫句
        # 声明注入内容非用户话语、其中指令不执行。system 侧日期级时间由
        # orchestrator 负责（原 injector 每轮 H:M 时间段是缓存击穿源，已迁出）。
        envelope = build_envelope(
            {
                "memories": memory_content,
                "lessons": metacog_content,
                "experience": experience_content,
                "reflection": reflection_content,
                "emotion": emotion_content,
                "time": self._build_envelope_time_block(),
            }
        )

        system_content = system_prompt

        system_tokens = self._count_tokens(system_content)

        history = self._trim_history(conversation_history)
        history_tokens = sum(self._count_tokens(msg.get("content", "")) for msg in history)

        user_content = f"{envelope}\n\n{user_input}" if envelope else user_input
        # 审计④：压缩预算按"裸 user 输入"计算——user_tokens 若含旧信封，
        # _compress_context 的 _budget_after 再扣一次信封 → 双计导致过度压缩
        user_bare_tokens = self._count_tokens(user_input)
        user_tokens = self._count_tokens(user_content)

        total_tokens = system_tokens + history_tokens + user_tokens

        compression_ratio = 1.0
        if total_tokens > self._token_budget.max_total and self._enable_compression:
            envelope, history, compression_ratio = self._compress_context(
                envelope, history, user_bare_tokens, system_tokens
            )
            user_content = f"{envelope}\n\n{user_input}" if envelope else user_input
            total_tokens = (
                self._count_tokens(system_content)
                + sum(self._count_tokens(msg.get("content", "")) for msg in history)
                + self._count_tokens(user_content)
            )

        context = [{"role": "system", "content": system_content}]
        context.extend(history)
        context.append({"role": "user", "content": user_content})

        logger.info(
            "[LLM_TRACE] Final context: %d msgs (system=1, history=%d, user=1), total_tokens=%d",
            len(context),
            len(history),
            total_tokens,
        )

        result = ContextBuildResult(
            context=context,
            total_tokens=total_tokens,
            compression_ratio=compression_ratio,
            reflection_count=1 if reflection_content else 0,
            memory_count=len(memories),
            history_count=len(history),
            envelope_tokens=self._count_tokens(envelope),
            stats={
                "system_tokens": system_tokens,
                "history_tokens": history_tokens,
                "user_tokens": user_tokens,
                "envelope_tokens": self._count_tokens(envelope),
                "build_time_ms": int((time.time() - start_time) * 1000),
                "within_budget": total_tokens <= self._token_budget.max_total,
            },
        )

        self.log_info(
            "上下文构建完成 "
            f"(total_tokens={total_tokens}, within_budget={result.stats['within_budget']}, "
            f"compression_ratio={compression_ratio})"
        )

        return result

    def _build_envelope_time_block(self) -> str:
        """信封 <time> 块（批次 A）：委托模块级 build_time_block（单源，
        orchestrator pool 主链共用）。"""
        return build_time_block()

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
                # 根因修复: ReflectionLogEntry 的真实字段是 title/content/insights，
                # 此前读 log.situation/log.lesson（不存在）→ AttributeError 被 except
                # 吞掉，反思上下文永远是空字符串。
                lesson = (log.insights[0] if log.insights else log.content) or log.title
                parts.append(f"- [{status_mark}] {log.title[:50]} → {lesson[:60]}")

            return "\n".join(parts)

        except Exception as e:
            self.log_warning(f"构建反思日志上下文失败: {e}")
            return ""

    def _build_metacog_lessons(self, agent_id: str, limit: int = 3) -> str:
        """构建元认知教训上下文（活跃 avoid_tool/discount/review 教训，全确定性）"""
        try:
            from neurova.cognitive_layers.meta_cognition_layer.ledger import get_meta_ledger

            result = get_meta_ledger(agent_id).list_records(
                agent_id=agent_id, page=1, size=20, kind="lesson"
            )
            parts = []
            import datetime as _dt

            now_iso = _dt.datetime.now(_dt.timezone.utc).isoformat()
            for it in result["items"]:
                meta = it.get("metadata") or {}
                expires_at = meta.get("expires_at")
                if expires_at and expires_at < now_iso:
                    continue
                parts.append(f"- [{meta.get('operator', '?')}] {meta.get('text', '')[:100]}")
                if len(parts) >= limit:
                    break
            return "\n".join(parts)
        except Exception as e:
            self.log_debug(f"元认知教训注入跳过: {e}")
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
            from neurova.skills.experience_knowledge_base import (
                get_experience_knowledge_base,
            )

            # 单例复用（复审残余点 B）：每次构建新建连接是连接 churn
            ekb = get_experience_knowledge_base()

            # 查找相似经验（2.0 契约：skill_name=None 跨技能，context 为 dict）
            # P0-3：检索按 agent 隔离——身份与存储同源（memory_manager 归属 agent）
            # F12 修复：原引用 self.memory_manager（属性不存在，实际是
            # _memory_manager）→ AttributeError 被 except 吞掉 → EKB 经验注入
            # 在生产环境恒空（test_ekb_injection_fallback 4 失败的根因）
            _mm_agent = str(getattr(self._memory_manager, "agent_id", "") or "") or None
            similar = ekb.find_similar_experiences(
                skill_name=None,
                context={"user_input": query},
                limit=3,
                agent_id=_mm_agent,
            )

            if not similar:
                return ""

            # F11 修复：不再自带 "## 相关经验" 段头——内容经信封 <experience> 块
            # 包装（旧实现段头+_build_system_prompt 段头叠加成双标题）
            parts = []
            for exp in similar[:3]:  # 最多显示3条
                # 2.0: context 是 dict，从中提取 user_input 作为摘要
                ctx = exp.get("context") or {}
                if isinstance(ctx, dict):
                    context_summary = str(ctx.get("user_input", ""))[:50]
                else:
                    context_summary = str(ctx)[:50]
                # 2.0: result 是 dict 或 None
                # 契约对齐（闭环审计 2026-09-04）：写入端 post_chat 存的是
                # result["reply_excerpt"]，此处只读 output 曾使注入摘要恒空串
                result_data = exp.get("result")
                if isinstance(result_data, dict):
                    result_summary = str(
                        result_data.get("reply_excerpt")
                        or result_data.get("output")
                        or ""
                    )[:50]
                else:
                    result_summary = str(result_data or "")[:50]
                # success 在 2.0 中是 int 0/1
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
                emotions.append(f"{emoji} {emotion_type}: {intensity * 100:.0f}%")

        return " | ".join(emotions) if emotions else "😐 neutral"

    def _trim_history(self, history: List[Dict]) -> List[Dict]:
        """在 Token 预算内裁剪历史

        OpenClaw 启发 P0-8：分割点不得切进工具块。assistant(tool_calls) 与
        其紧随的 tool 结果段视为一个配对单元——预算装不下整个单元时整体
        舍弃（分割点移动到块边界之前继续装填），绝不产出孤儿 tool 结果/
        悬空调用。普通消息维持旧语义：装不下即终止（首条兜底保留）。
        """
        if not history:
            return []

        from neurova.context.recovery import _is_tool_result, _opens_tool_block

        trimmed: List[Dict] = []
        total_tokens = 0
        budget = self._token_budget.conversation_history

        i = len(history) - 1
        while i >= 0:
            msg = history[i]

            # 工具块单元：连续 tool 结果段 + 其 assistant(tool_calls) 块头
            if _is_tool_result(msg):
                j = i
                while j >= 0 and _is_tool_result(history[j]):
                    j -= 1
                has_header = j >= 0 and _opens_tool_block(history[j])
                unit = [history[k] for k in range(i, j, -1)]
                unit_tokens = sum(self._count_tokens(m.get("content", "")) for m in unit)
                if has_header:
                    unit.insert(0, history[j])
                    unit_tokens += self._count_tokens(history[j].get("content", ""))
                if total_tokens + unit_tokens <= budget:
                    trimmed[0:0] = unit  # 整块按序插入，保持 块头→结果 顺序
                    total_tokens += unit_tokens
                    i = (j - 1) if has_header else j
                    continue
                # 装不下整块 → 整块舍弃，分割点移到块之前继续（不终止）
                i = (j - 1) if has_header else (i - 1)
                continue

            # 普通消息：旧语义（装不下则首条兜底并终止）
            msg_tokens = self._count_tokens(msg.get("content", ""))
            if total_tokens + msg_tokens <= budget:
                trimmed.insert(0, msg)
                total_tokens += msg_tokens
            else:
                if not trimmed:
                    trimmed.insert(0, msg)
                break
            i -= 1

        return trimmed

    def _compress_context(
        self, envelope: str, history: List[Dict], user_tokens: int, system_tokens: int = 0
    ) -> tuple:
        """压缩上下文（批次 A 重设计）：压缩对象=信封+历史，system 只读不动。

        F5 修复：旧实现按 "## 相关记忆" 字符串切 system_content、降级路径对
        整个 system 硬截断——信封化后 system 恒为稳定 base，压缩改为对信封
        做确定性块淘汰（compress_envelope）。
        核验轮修复③：原借道 SmartContextCompressor 的调用与其真实签名
        （compress_context(messages, memories, system_prompt, target_tokens)
        → 元组）双不符，TypeError 被 except 吞掉 → 压缩器在生产从未生效、
        信封被整包丢弃。改为确定性历史淘汰：最老轮先弃，保留轮次摘要标记，
        压缩行为不再依赖压缩器是否可用。
        """
        try:
            compression_ratio = 1.0

            def _budget_after(hist: List[Dict]) -> int:
                return (
                    self._token_budget.max_total
                    - system_tokens
                    - sum(self._count_tokens(m.get("content", "")) for m in hist)
                    - user_tokens
                )

            # 1) 历史确定性淘汰（最老轮先弃）：预算不足以容纳"信封+历史"时，
            #    逐条弃最旧，直到预算容纳信封或历史耗尽（不变式：退出时
            #    system+历史+信封+user ≤ max_total，或历史已空）
            envelope_budget = _budget_after(history)
            if envelope_budget < self._count_tokens(envelope):
                remaining = list(history)
                while remaining and _budget_after(remaining) < self._count_tokens(envelope):
                    remaining = remaining[1:]  # 弃最旧一条
                dropped = len(history) - len(remaining)
                if dropped > 0:
                    summary = {"role": "system", "content": f"[对话摘要: 省略了{dropped}条较早消息]"}
                    history = [summary] + remaining
                compression_ratio = len(history) / max(1, len(history) + dropped)

            # 2) 信封确定性淘汰（块级→行级），落预算
            envelope_budget = _budget_after(history)
            envelope = compress_envelope(
                envelope, budget_tokens=max(0, envelope_budget), count_tokens=self._count_tokens
            )

            return envelope, history, compression_ratio

        except Exception as e:
            logger.warning("Envelope compression failed, dropping envelope: %s", e)
            return "", history, 1.0

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

        # 使用统一的 Token 估算器
        return self._token_estimator.estimate(text)

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
                # 根因修复: 真实字段是 type/content（原 reflection_type/lesson 不存在）
                parts.append(f"\n{status_mark} [{log.type.value}] {log.content}")

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
