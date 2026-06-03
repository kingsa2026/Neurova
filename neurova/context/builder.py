from __future__ import annotations

"""
上下文构建器 - Context Builder

提供统一的上下文构建接口，兼容旧版 API。
当 UnifiedContextInjector 可用时，ContextBuilder 成为纯代理。
"""

import logging
from typing import Any, Dict, List, Optional

from .models import TokenBudget
from .injector import UnifiedContextInjector

logger = logging.getLogger(__name__)

class ContextBuilder:
    """
    上下文构建器 - 兼容旧接口

    Phase 6 简化：当 UnifiedContextInjector 可用时，ContextBuilder 成为纯代理。
    所有重复方法已移除，统一委托给 injector。
    """

    MAX_CONTEXT_TOKENS = 16000  # 与 UnifiedContextInjector 保持一致

    def __init__(
        self,
        config: Dict = None,
        unified_injector: Optional[UnifiedContextInjector] = None
    ):
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
        return self._fallback_build_context(
            system_prompt, memories, conversation_history, user_input, agent_emotion
        )

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

        context = [{'role': 'system', 'content': system_content}]
        # 对话历史
        if conversation_history:
            context.extend(conversation_history)
        else:
            for i, content in enumerate(history_items):
                role = "user" if i % 2 == 0 else "assistant"
                context.append({'role': role, 'content': content})
        context.append({'role': 'user', 'content': user_input})

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
                memories.append({
                    "content": item.content,
                    "temperature": item.metadata.get("temperature", 50),
                    "is_crystallized": item.metadata.get("is_crystallized", False),
                    "is_important": item.metadata.get("is_important", False),
                    "category": item.metadata.get("category", ""),
                })
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
                experiences.append({
                    "context": item.content[:100],  # 使用内容作为上下文摘要
                    "result": item.metadata.get("result", ""),
                    "success": item.metadata.get("success", True),
                    "lesson": item.metadata.get("lesson", ""),
                    "confidence": item.metadata.get("confidence", 1.0),
                })
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
        # 创建临时 injector
        temp_injector = UnifiedContextInjector(
            memory_manager=None,  # 无记忆管理器
            token_budget=TokenBudget(max_total=self.MAX_CONTEXT_TOKENS)
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
        # 创建临时 injector
        temp_injector = UnifiedContextInjector(
            memory_manager=None,
            token_budget=TokenBudget(max_total=self.MAX_CONTEXT_TOKENS)
        )

        # 计算总 tokens
        total_tokens = sum(
            temp_injector._count_tokens(msg.get('content', ''))
            for msg in context
        )

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
        conversation_history = session.get('conversation_history', [])
        user_id = session.get('user_id')
        agent_id = session.get('agent_id')
        metadata = session.get('metadata', {})

        # 提取选项
        include_reflection_log = options.get('include_reflection_log', True)
        include_question_queue = options.get('include_question_queue', False)
        max_tokens = options.get('max_tokens')
        tool_memory_result = options.get('tool_memory_result')
        experience_items = options.get('experience_items')
        system_prompt = options.get('system_prompt', self._get_default_system_prompt())

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
        return self._fallback_build_context(
            system_prompt, memories, conversation_history, user_input, agent_emotion
        )

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
            logger.warning(f"自动记忆检索失败: {e}")
            return []

    def _analyze_emotion(self, user_input: str, metadata: Dict) -> Optional[Dict]:
        """分析用户情感"""
        # 简单的情感分析逻辑
        # 实际实现可以使用更复杂的情感分析模型
        emotion_keywords = {
            'joy': ['开心', '高兴', '快乐', '喜欢', '好'],
            'sadness': ['难过', '伤心', '失望', '不好'],
            'anger': ['生气', '愤怒', '讨厌', '烦'],
            'neutral': ['你好', '请问', '怎么', '什么'],
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
        tool_memories = tool_memory_result.get('memories', [])
        if not tool_memories:
            return memories

        # 合并并去重
        merged = memories.copy()
        for tool_mem in tool_memories:
            # 检查是否已存在
            if not any(m.get('content') == tool_mem.get('content') for m in merged):
                merged.append(tool_mem)

        return merged
