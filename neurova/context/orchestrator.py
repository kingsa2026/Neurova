"""
ContextOrchestrator — 统一上下文构建模块

从 agent/context_orchestrator.py 提取，负责：
- 上下文系统初始化 (init_context_system)
- 上下文构建 (build_context) — Phase 2-5
- 系统提示构建 (build_system_prompt)
- 工具描述构建 (get_tools_description)
- 工具列表构建 (build_tools_for_llm)

设计原则：
- 深度模块：小接口，深实现
- 依赖注入：通过 agent_ref 访问 Agent 实例的属性
- 可独立测试：不依赖 Agent 类的完整初始化
"""

from neurova.core.logger import get_logger
from typing import Dict, List, Optional
import datetime

from .builder import ContextBuilder
from .injector import UnifiedContextInjector
from .models import TokenBudget

logger = get_logger(__name__)


class ContextOrchestrator:
    """统一上下文构建模块

    封装 Agent 的所有上下文构建相关操作，提供小接口、深实现。

    通过 agent_ref 访问 Agent 实例的：
    - config, memory_manager, storage
    - context_builder, llm_client
    - tool_router, _skill_registry
    - soul, personality
    - conversation_history
    - growth_log_manager, recall_engine
    """

    def __init__(self, agent_ref, use_pool: bool = True, auto_tag: bool = False):
        self._agent = agent_ref
        self.use_pool = use_pool
        self.auto_tag = auto_tag

        # 初始化 ContextPool（如果启用）
        if use_pool:
            from neurova.context_pool import ContextPool

            # 动态获取 Token 预算
            model_name = getattr(agent_ref.config, "llm_model", "gpt-4")
            max_tokens = ContextPool.get_token_budget_for_model(model_name)

            self.context_pool = ContextPool(
                user_id=getattr(agent_ref, "user_id", "default"),
                agent_id=getattr(agent_ref, "agent_id", "default"),
                max_tokens=max_tokens,
                auto_tag=auto_tag,
            )
            logger.info("ContextPool 初始化完成，模型: %s，Token 预算: %s", model_name, max_tokens)
        else:
            self.context_pool = None

    # ---- 属性代理（方便内部访问） ----
    @property
    def config(self):
        return self._agent.config

    @property
    def memory_manager(self):
        return self._agent.memory_manager

    @property
    def context_builder(self):
        return self._agent.context_builder

    @property
    def tool_router(self):
        return self._agent.tool_router

    @property
    def skill_registry(self):
        # Bug C-6 修复：用 getattr 保护，避免未设置 _skill_registry 的 Agent 抛 AttributeError
        # 对比 line 99 growth_log_manager 已用 getattr，此处保持一致
        return getattr(self._agent, "_skill_registry", None)

    @property
    def soul(self):
        return self._agent.soul

    @property
    def personality(self):
        return self._agent.personality

    @property
    def conversation_history(self):
        return self._agent.conversation_history

    @property
    def growth_log_manager(self):
        return getattr(self._agent, "growth_log_manager", None)

    # ══════════════════════════════════════════════════════════════
    # 初始化
    # ══════════════════════════════════════════════════════════════

    def init_context_system(self):
        """初始化上下文系统（UnifiedContextInjector + ContextBuilder）

        在 Agent.__init__() 中调用，创建上下文构建器和统一注入器。
        """
        # 创建统一上下文注入器（如果记忆模块可用）
        unified_injector = None
        if self.memory_manager:
            unified_injector = UnifiedContextInjector(
                memory_manager=self.memory_manager,
                growth_log_manager=self.growth_log_manager,
                question_queue_manager=getattr(self._agent, "question_queue_manager", None),
                token_budget=TokenBudget(max_total=16000),
                enable_cache=True,
                enable_compression=True,
            )
            logger.info("Agent %s: UnifiedContextInjector 已启用 (16K tokens)", self.config.name)

        # 创建上下文构建器（如果有 unified_injector 则使用增强模式）
        self._agent.context_builder = ContextBuilder(
            config={},
            unified_injector=unified_injector,
        )

    # ══════════════════════════════════════════════════════════════
    # 上下文构建
    # ══════════════════════════════════════════════════════════════

    async def build_context(
        self,
        user_input: str,
        tool_memory_result: Optional[Dict] = None,
        auto_execute_result: Optional[Dict] = None,
        tool_decision: str = "do_not_execute",
        experience_items: Optional[list] = None,
        relevant_memories: Optional[list] = None,
        session_context: Optional[list] = None,
        crystallized_patterns: Optional[list] = None,
        voice_context: Optional[Dict] = None,
    ) -> List[Dict]:
        """构建完整的 LLM 上下文（Phase 2-5）

        Args:
            user_input: 用户输入
            tool_memory_result: ToolMemory 检索结果（Phase 0）
            auto_execute_result: 肌肉记忆自动执行结果（含 status/result/error）
            tool_decision: 工具决策状态（auto_executed/timeout/failed/suggest/do_not_execute）
            experience_items: 经验检索结果（Phase 0.5）
            relevant_memories: 记忆检索结果（Phase 1）
            session_context: Session 文件提取的最近对话上下文（B3修复）
            crystallized_patterns: 结晶经验检索结果（认知图谱 PatternCrystallizer）
            voice_context: 语音上下文（ASR 元数据、情感分析等）

        Returns:
            上下文消息列表，可直接传给 LLM
        """

        from neurova.context_pool import ContextInput, ContextSource

        # 构建工具描述
        tools_desc = await self.get_tools_description()
        
        # Phase 2: 构建系统提示
        system_instructions = [self.soul]
        if self.personality:
            system_instructions.append(self.personality)
        if self.config.constitution:
            system_instructions.append(self.config.constitution)

        # Bug T-1 修复:注入当前时间上下文(避免 LLM 误用训练截止日期回答时间问题)
        # build_context 是 chat_pipeline 实际调用的路径(build_system_prompt 只是工具方法,未被调用),
        # 所以必须在此处注入时间,否则 LLM 看不到真实当前时间。
        system_instructions.append(self._build_current_time_section())

        # 使用配置的行为规则
        developer_instructions = list(self.config.behavior_rules)
        if tools_desc:
            developer_instructions.append(tools_desc)

        # Phase 2.5: 分析用户输入的情感状态
        agent_emotion = None
        try:
            from neurova.cognitive_layers.emotion_context_layer.emotion import EmotionAnalyzer

            emotion_analyzer = EmotionAnalyzer()
            agent_emotion = emotion_analyzer.analyze(user_input)
            if agent_emotion and agent_emotion.get("label") != "neutral":
                logger.debug(
                    f"用户情感分析: {agent_emotion.get('label')} (强度: {agent_emotion.get('intensity', 0):.2f})"
                )
        except Exception as e:
            logger.debug("情感分析跳过: %s", e)

        # Phase 2.8: 收集反思日志
        reflection_logs: list = []
        if self.growth_log_manager:
            try:
                validated = self.growth_log_manager.get_validated_logs(limit=3)
                pending = self.growth_log_manager.get_pending_logs(limit=2)
                reflection_logs = [
                    {"lesson": l.lesson, "reflection_type": l.reflection_type.value, "status": l.status.value}
                    for l in validated + pending
                ]
            except Exception as e:
                logger.debug("反思日志获取跳过: %s", e)

        # Phase 3: 构建 ContextInput → ContextCollector → 候选池
        # session_context 包含完整的 user+assistant 历史（优先使用）
        # conversation_history 只有 user 消息且不更新（仅作 fallback）
        if session_context is not None:
            conversation_context = list(session_context)
        else:
            conversation_context = list(
                {"role": m["role"], "content": m["content"]} for m in (self.conversation_history or [])
            )

        logger.info(
            "[CTX_TRACE] conversation_context=%d msgs, session_context_provided=%s",
            len(conversation_context),
            bool(session_context),
        )

        # 构建工具记忆上下文（包含执行状态）
        tool_memory_context = dict(tool_memory_result) if tool_memory_result else {}
        if auto_execute_result:
            tool_memory_context["auto_execute_result"] = auto_execute_result
        tool_memory_context["tool_decision"] = tool_decision

        if self.use_pool and self.context_pool:
            self.context_pool.clear()
            # 添加系统指令
            for instruction in system_instructions:
                self.context_pool.add_context(
                    ContextInput(source=ContextSource.SYSTEM_INSTRUCTION, content=instruction, priority=100)
                )

            # 添加开发者指令
            for instruction in developer_instructions:
                self.context_pool.add_context(
                    ContextInput(source=ContextSource.DEVELOPER_INSTRUCTION, content=instruction, priority=90)
                )

            # 添加用户输入
            self.context_pool.add_context(
                ContextInput(source=ContextSource.USER_INPUT, content=user_input, priority=90)
            )

            # Bug C-3 修复：注入 tool_memory_context（含执行状态 + 自动执行结果）
            # 旧代码构建了 tool_memory_context 但从未 add_context，LLM 看不到工具执行状态
            # 仅当有实际工具结果或自动执行结果时才注入（tool_decision="do_not_execute" 是默认值，不触发）
            if tool_memory_result or auto_execute_result:
                import json as _json

                tool_lines = []
                if tool_memory_result:
                    if isinstance(tool_memory_result, dict):
                        if tool_memory_result.get("tool_name"):
                            tool_lines.append(f"工具: {tool_memory_result['tool_name']}")
                        if tool_memory_result.get("result"):
                            tool_lines.append(f"结果: {tool_memory_result['result']}")
                    else:
                        tool_lines.append(f"工具记忆: {tool_memory_result}")
                if auto_execute_result:
                    if isinstance(auto_execute_result, dict):
                        tool_lines.append(f"自动执行: {_json.dumps(auto_execute_result, ensure_ascii=False)}")
                    else:
                        tool_lines.append(f"自动执行: {auto_execute_result}")
                if tool_memory_context.get("tool_decision") and tool_memory_context["tool_decision"] != "do_not_execute":
                    tool_lines.append(f"决策: {tool_memory_context['tool_decision']}")
                if tool_lines:
                    tool_content = "[工具记忆] " + " | ".join(tool_lines)
                    self.context_pool.add_context(
                        ContextInput(
                            source=ContextSource.TOOL_CALL,
                            content=tool_content,
                            priority=85,  # 高于 memory(70)，低于 user_input(90)
                        )
                    )

            # 添加对话历史（保留 role 信息）
            for msg in conversation_context:
                self.context_pool.add_context(
                    ContextInput(
                        source=ContextSource.CONVERSATION,
                        content=msg["content"],
                        priority=60,
                        metadata={"role": msg.get("role", "user")},
                    )
                )

            # 添加记忆
            for memory in relevant_memories or []:
                if isinstance(memory, dict):
                    content = memory.get("content", str(memory))
                else:
                    content = str(memory)
                self.context_pool.add_context(ContextInput(source=ContextSource.MEMORY, content=content, priority=70))

            # 添加经验
            for experience in experience_items or []:
                if isinstance(experience, dict):
                    content = experience.get("content", str(experience))
                else:
                    content = str(experience)
                self.context_pool.add_context(
                    ContextInput(source=ContextSource.EXPERIENCE, content=content, priority=70)
                )

            # 添加结晶经验（认知图谱 PatternCrystallizer 产物）
            for pattern in crystallized_patterns or []:
                if isinstance(pattern, dict):
                    content = pattern.get("content", str(pattern))
                else:
                    content = str(pattern)
                self.context_pool.add_context(
                    ContextInput(
                        source=ContextSource.EXPERIENCE,
                        content=f"[结晶经验] {content}",
                        priority=80,  # 结晶经验优先级高于普通经验
                    )
                )

            # 添加情感状态
            if agent_emotion:
                self.context_pool.add_context(
                    ContextInput(
                        source=ContextSource.EMOTION,
                        content=f"用户情感: {agent_emotion.get('label', 'neutral')}",
                        priority=50,
                    )
                )

            # 添加语音上下文
            if voice_context:
                try:
                    from neurova.voice_context_module import VoiceContextModule

                    voice_module = VoiceContextModule()
                    voice_module.inject_metadata(self.context_pool, voice_context)
                except Exception as e:
                    logger.debug("语音上下文注入跳过: %s", e)

            # 添加反思日志
            for log in reflection_logs:
                self.context_pool.add_context(
                    ContextInput(source=ContextSource.REFLECTION, content=log.get("lesson", str(log)), priority=60)
                )

            # 使用 ContextPool.draw() 获取相关上下文
            drawn_contexts = self.context_pool.draw(need=user_input)
            logger.debug("ContextPool.draw() 完成，共 %s 个上下文", len(drawn_contexts))

            # 将 drawn_contexts 转换为消息格式
            context = []
            for ctx in drawn_contexts:
                if ctx.source == ContextSource.SYSTEM_INSTRUCTION:
                    context.append({"role": "system", "content": ctx.content})
                elif ctx.source == ContextSource.DEVELOPER_INSTRUCTION:
                    context.append({"role": "system", "content": ctx.content})
                elif ctx.source == ContextSource.USER_INPUT:
                    context.append({"role": "user", "content": ctx.content})
                elif ctx.source == ContextSource.CONVERSATION:
                    role = ctx.metadata.get("role", "user") if ctx.metadata else "user"
                    context.append({"role": role, "content": ctx.content})
                elif ctx.source == ContextSource.MEMORY:
                    context.append({"role": "system", "content": f"[记忆] {ctx.content}"})
                elif ctx.source == ContextSource.EXPERIENCE:
                    context.append({"role": "system", "content": f"[经验] {ctx.content}"})
                elif ctx.source == ContextSource.EMOTION:
                    context.append({"role": "system", "content": f"[情感] {ctx.content}"})
                elif ctx.source == ContextSource.REFLECTION:
                    context.append({"role": "system", "content": f"[反思] {ctx.content}"})
                else:
                    context.append({"role": "system", "content": ctx.content})

            return context

        # 如果未启用 ContextPool，使用原有方法
        # 将所有上下文转换为 ContextInput 对象列表
        candidate_pool = []

        # 添加系统指令
        for instruction in system_instructions:
            candidate_pool.append(
                ContextInput(source=ContextSource.SYSTEM_INSTRUCTION, content=instruction, priority=100)
            )

        # 添加开发者指令
        for instruction in developer_instructions:
            candidate_pool.append(
                ContextInput(source=ContextSource.DEVELOPER_INSTRUCTION, content=instruction, priority=90)
            )

        # 添加用户输入
        candidate_pool.append(ContextInput(source=ContextSource.USER_INPUT, content=user_input, priority=90))

        # 添加对话历史（保留 role 信息）
        for msg in conversation_context:
            candidate_pool.append(
                ContextInput(
                    source=ContextSource.CONVERSATION,
                    content=msg["content"],
                    priority=60,
                    metadata={"role": msg.get("role", "user")},
                )
            )

        # 添加记忆
        for memory in relevant_memories or []:
            if isinstance(memory, dict):
                content = memory.get("content", str(memory))
                metadata = {k: v for k, v in memory.items() if k != "content"}
            else:
                content = str(memory)
                metadata = {}
            candidate_pool.append(
                ContextInput(source=ContextSource.MEMORY, content=content, priority=70, metadata=metadata)
            )

        # 添加经验
        for experience in experience_items or []:
            if isinstance(experience, dict):
                content = experience.get("content", str(experience))
            else:
                content = str(experience)
            candidate_pool.append(ContextInput(source=ContextSource.EXPERIENCE, content=content, priority=70))

        # 添加结晶经验（认知图谱 PatternCrystallizer 产物）
        for pattern in crystallized_patterns or []:
            if isinstance(pattern, dict):
                content = pattern.get("content", str(pattern))
            else:
                content = str(pattern)
            candidate_pool.append(
                ContextInput(
                    source=ContextSource.EXPERIENCE,
                    content=f"[结晶经验] {content}",
                    priority=80,  # 结晶经验优先级高于普通经验
                )
            )

        # 添加情感状态
        if agent_emotion:
            candidate_pool.append(
                ContextInput(
                    source=ContextSource.EMOTION,
                    content=f"用户情感: {agent_emotion.get('label', 'neutral')}",
                    priority=50,
                    metadata=agent_emotion,
                )
            )

        # 添加语音上下文
        if voice_context:
            try:
                from neurova.voice_context_module import VoiceContextModule

                voice_module = VoiceContextModule()
                # 将语音上下文转换为 ContextInput 并添加到候选池
                content_parts = []
                if voice_context.get("text"):
                    content_parts.append(f"语音识别文本: {voice_context['text']}")
                if voice_context.get("confidence", 0) > 0:
                    content_parts.append(f"识别置信度: {voice_context['confidence']:.2f}")
                if voice_context.get("language"):
                    content_parts.append(f"语言: {voice_context['language']}")
                if voice_context.get("engine"):
                    content_parts.append(f"识别引擎: {voice_context['engine']}")

                emotion = voice_context.get("emotion")
                if emotion and emotion.get("primary_emotion") != "neutral":
                    content_parts.append(
                        f"语音情感: {emotion['primary_emotion']} " f"(置信度: {emotion.get('confidence', 0):.2f})"
                    )

                if content_parts:
                    candidate_pool.append(
                        ContextInput(
                            source=ContextSource.MULTIMODAL,
                            content="\n".join(content_parts),
                            priority=70,
                            metadata={"type": "voice_context"},
                        )
                    )
            except Exception as e:
                logger.debug("语音上下文注入跳过: %s", e)

        # 添加反思日志
        for log in reflection_logs:
            candidate_pool.append(
                ContextInput(
                    source=ContextSource.REFLECTION, content=log.get("lesson", str(log)), priority=60, metadata=log
                )
            )

        logger.debug("候选池构建完成，共 %s 个候选项", len(candidate_pool))

        # Phase 3.5: 从候选池构建上下文
        if not hasattr(self._agent, "context_builder") or self._agent.context_builder is None:
            logger.warning("context_builder 不可用，降级为简单上下文构建（保留已收集的候选上下文，避免丢失记忆/对话）")
            # Bug T-1 修复:降级路径也注入当前时间(避免 LLM 误用训练截止日期)
            # 根因修复（P2-#16）: 降级路径原先直接丢弃已构建的 candidate_pool，
            # 导致记忆/对话上下文全部丢失。此处保留候选上下文，仅丢失优先级压缩。
            fallback = [{"role": "system", "content": "\n\n".join(system_instructions)}]
            for item in candidate_pool:
                content = getattr(item, "content", None)
                if content:
                    fallback.append({"role": "user", "content": str(content)})
            fallback.append({"role": "user", "content": user_input})
            return fallback

        context = self.context_builder.build_from_pool(
            candidate_pool,
            token_budget=TokenBudget(max_total=16000),
            conversation_history=None,
            user_input=user_input,
        )

        # Phase 4: 压缩上下文（如果需要）
        context = self.context_builder.compress_if_needed(context)

        return context

    # ══════════════════════════════════════════════════════════════
    # 系统提示构建
    # ══════════════════════════════════════════════════════════════

    def build_system_prompt(self, tools_desc: str = "") -> str:
        """构建系统提示（Phase 6.5: 统一行为规则配置）。

        使用配置的行为规则，确保 build_system_prompt() 和 chat() 中的
        developer_instructions 保持一致。

        Bug T-1 修复:在 prompt 末尾注入当前时间上下文,避免 LLM 误用训练截止日期。
        """
        parts = [self.soul]

        if self.personality:
            parts.append("\n\n## 性格特征\n" + self.personality)

        # 添加宪法/行为准则
        if self.config.constitution:
            parts.append("\n\n## 行为准则（宪法）\n" + self.config.constitution)

        # 使用配置的行为规则
        if self.config.behavior_rules:
            parts.append("\n\n## 行为规则\n")
            parts.extend(self.config.behavior_rules)

        if tools_desc:
            parts.append("\n\n## 可用工具\n" + tools_desc)

        # Bug T-1 修复:注入当前时间上下文(避免 LLM 误用训练截止日期回答时间问题)
        # 动态读取系统时间,每次调用 build_system_prompt 都反映当前时刻。
        parts.append(self._build_current_time_section())

        return "\n".join(parts)

    def _build_current_time_section(self) -> str:
        """构建当前时间上下文段(供 build_system_prompt 调用)。

        格式:
            ## 当前时间
            当前日期:2026年6月28日 星期日
            当前时刻:17:42:18
            时区:Asia/Shanghai (UTC+08:00)

        说明:
        - 日期用中文格式(YYYY年MM月DD日)+ 星期,便于 LLM 回答"今天星期几"。
        - 时刻用 24 小时制,便于 LLM 回答"现在几点"。
        - 时区用 IANA 名称 + UTC 偏移,避免 LLM 误判时区。
        - 此段在 build_system_prompt 末尾,不影响既有 soul/personality/constitution 段。
        """
        now = datetime.datetime.now()
        today = now.date()
        weekdays_zh = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
        weekday_zh = weekdays_zh[today.weekday()]

        # 获取本地时区(优先用 zoneinfo,回退到本地时间)
        try:
            from zoneinfo import ZoneInfo
            local_tz = ZoneInfo(self._get_local_timezone_name())
            tz_offset = local_tz.utcoffset(now)
            tz_name = str(local_tz)
        except Exception:
            # 回退:用系统本地时区偏移
            tz_offset = now.utcoffset() if now.utcoffset() else datetime.timedelta(0)
            tz_name = "Local"

        # 格式化 UTC 偏移为 +08:00 形式
        total_seconds = int(tz_offset.total_seconds())
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        tz_offset_str = f"{'+' if hours >= 0 else '-'}{abs(hours):02d}:{minutes:02d}"

        date_str = f"{today.year}年{today.month}月{today.day}日"
        time_str = now.strftime("%H:%M:%S")

        return (
            f"\n\n## 当前时间\n"
            f"当前日期:{date_str} {weekday_zh}\n"
            f"当前时刻:{time_str}\n"
            f"时区:{tz_name} (UTC{tz_offset_str})\n"
            f"提示:以上是系统注入的真实当前时间,请基于此时间回答用户的时间相关问题,"
            f"不要使用训练数据中的截止日期。"
        )

    def _get_local_timezone_name(self) -> str:
        """获取本地时区 IANA 名称(供 _build_current_time_section 使用)。

        优先级:
        1. 环境变量 TZ(用户显式设置)
        2. Windows 注册表 / /etc/localtime 软链(系统默认)
        3. 回退到 Asia/Shanghai(中国用户默认)
        """
        import os

        # 1. 环境变量
        env_tz = os.environ.get("TZ")
        if env_tz:
            return env_tz

        # 2. 尝试从系统获取
        try:
            import time as _time
            # time.tzname 返回 (标准时区名, 夏令时时区名),如 ('中国标准时间', '中国夏令时')
            # 这些不是 IANA 名称,但我们可以映射常见情况
            tzname = _time.tzname[0] if _time.tzname else ""
            if "China" in tzname or "中国" in tzname or "PRC" in tzname:
                return "Asia/Shanghai"
            if "Tokyo" in tzname or "Japan" in tzname or "日本" in tzname:
                return "Asia/Tokyo"
            if "Seoul" in tzname or "Korea" in tzname or "韩国" in tzname:
                return "Asia/Seoul"
            # 其他情况:用 UTC 偏移推断
            offset_sec = -_time.timezone if not _time.daylight else -_time.altzone
            offset_hours = offset_sec / 3600
            if offset_hours == 8:
                return "Asia/Shanghai"
            if offset_hours == 9:
                return "Asia/Tokyo"
            if offset_hours == 0:
                return "UTC"
            if offset_hours == -5:
                return "America/New_York"
            if offset_hours == -8:
                return "America/Los_Angeles"
        except Exception:
            pass

        # 3. 回退到中国默认时区(本项目主要用户群体)
        return "Asia/Shanghai"

    # ══════════════════════════════════════════════════════════════
    # 工具构建
    # ══════════════════════════════════════════════════════════════

    async def get_tools_description(self) -> str:
        """获取工具描述文本，用于注入 system prompt（API 不支持 function calling 时的降级）"""
        try:
            tools = await self.build_tools_for_llm()
            if not tools:
                return ""
            lines = ["\n\n## 可用工具\n你可以调用以下工具来完成任务。调用格式：\n`[TOOL_CALL:工具名(参数=值, ...)]`\n"]
            lines.append("⚠️ **工具使用原则**：\n"
                         "- `memory_search` 和 `voice_memory_search` 仅用于检索本Agent自身存储的历史记忆，不能搜索互联网\n"
                         "- 需要实时信息（天气、新闻、股价等）时，请使用 `weather` 或 `web_search` 工具获取，不要用记忆搜索工具查实时信息\n"
                         "- `weather` 工具可查实时天气（支持中文城市名，如'许昌'）；`web_search` 工具可查新闻、股价等实时网络信息\n"
                         "- `computer_shell` 可执行本地命令，但注意安全性和权限\n")
            for t in tools:
                fn = t["function"]
                params_desc = ""
                params = fn.get("parameters", {}).get("properties", {})
                required = fn.get("parameters", {}).get("required", [])
                if params:
                    param_list = [f"{k}{'(必填)' if k in required else ''}" for k in params]
                    params_desc = f" — 参数: {', '.join(param_list)}"
                lines.append(f"- **{fn['name']}**: {fn['description']}{params_desc}")
            return "\n".join(lines)
        except Exception as e:
            logger.warning("构建工具描述失败: %s", e)
            return ""

    async def build_tools_for_llm(self) -> Optional[List[Dict]]:
        """聚合所有工具为 OpenAI function call schema（内置 + Skill + MCP + 插件）"""
        from neurova.builtin_tools import get_builtin_tool_params

        tools = []
        user_id = getattr(self.config, "user_id", "default")
        logger.info(
            f"[TOOLS] 开始聚合工具, user_id={user_id}, has_tool_router={self.tool_router is not None}, has_skill_registry={self.skill_registry is not None}"
        )

        # 1. ToolRouter 聚合所有工具（含 MCP）
        if self.tool_router:
            try:
                all_tools = self.tool_router.get_all_tools(
                    agent_id=self.config.agent_id,
                    user_id=user_id,
                )
                tool_list = list(all_tools.values()) if isinstance(all_tools, dict) else list(all_tools)
                logger.info("[TOOLS] ToolRouter 返回 %s 个工具: %s", len(tool_list), [getattr(t, "name", str(t)) for t in tool_list])
                for t in tool_list:
                    if hasattr(t, "to_openai_format"):
                        tools.append(t.to_openai_format())
                    else:
                        tool_name = getattr(t, "name", str(t))
                        tool_desc = getattr(t, "description", f"工具: {tool_name}")
                        builtin_params = get_builtin_tool_params(tool_name)
                        tools.append(
                            {
                                "type": "function",
                                "function": {
                                    "name": tool_name,
                                    "description": tool_desc
                                    or builtin_params.get("description", f"工具: {tool_name}"),
                                    "parameters": builtin_params.get(
                                        "parameters", {"type": "object", "properties": {}, "required": []}
                                    ),
                                },
                            }
                        )
            except Exception:
                logger.exception("从 ToolRouter 获取工具列表失败")

        # 2. Skill Registry 工具 — 用实际参数 schema 替换 ToolRouter 的占位符
        if self.skill_registry:
            try:
                from neurova.skill_system.compat import unpack_skill  # H2 fix: 解包 class B 的 tuple

                for skill_name, raw_skill in self.skill_registry.skills.items():
                    skill = unpack_skill(raw_skill)  # H2 fix: 类 B 返回 (Skill, Path) 元组，需解包
                    # 尝试用 OpenAI Schema Adapter 生成带参数的 schema
                    try:
                        from neurova.skill_system.compat import OpenAISchemaAdapter

                        schema = OpenAISchemaAdapter.skill_to_tool_schema(skill)
                    except ImportError:
                        # Fallback：用 _get_parameters() 构建
                        params_info = skill._get_parameters() if hasattr(skill, "_get_parameters") else {}
                        props = {}
                        required = []
                        for pname, pinfo in params_info.items():
                            props[pname] = {"type": pinfo.get("type", "string"), "description": pname}
                            if pinfo.get("required"):
                                required.append(pname)
                        schema = {
                            "type": "function",
                            "function": {
                                "name": skill.name,
                                "description": skill.description,
                                "parameters": {"type": "object", "properties": props, "required": required},
                            },
                        }
                    # 替换 ToolRouter 生成的同名工具（参数更完整）
                    existing_idx = next((i for i, t in enumerate(tools) if t["function"]["name"] == skill_name), -1)
                    if existing_idx >= 0:
                        tools[existing_idx] = schema
                    else:
                        tools.append(schema)
            except Exception:
                logger.exception("从 SkillRegistry 获取工具失败")

        # 过滤掉格式不正确的工具（某些 provider 要求 tools 中每个元素都必须有 function 字段）
        valid_tools = []
        for t in tools:
            if isinstance(t, dict) and "function" in t and isinstance(t["function"], dict) and "name" in t["function"]:
                valid_tools.append(t)
            else:
                logger.warning("跳过格式不正确的工具: %s", t)
        tools = valid_tools

        if tools:
            logger.info("🔧 为 LLM 提供 %s 个工具: %s", len(tools), [t['function']['name'] for t in tools])
        return tools if tools else None
