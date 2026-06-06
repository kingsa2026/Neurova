"""
ChatPipeline — 对话流程管线

从 Agent.chat() 提取的深度模块（Phase 5 重构）。

将 chat() 的 ~580 行拆分为独立可测试的步骤：
1. Pre-LLM 检查（ToolMemory、技能获取、NL合成）
2. 检索与上下文构建（UnifiedRetriever、结晶经验、ContextOrchestrator）
3. Evocate 注入（Neurova Hebb）
4. LLM 调用（Agent Loop + 自动续写）
5. 后处理（文本工具调用、历史更新、轨迹记录）

设计原则：
- 深度模块：小接口，深实现
- 依赖注入：通过 agent_ref 访问 Agent 实例的属性
- 可独立测试：不依赖 Agent 类的完整初始化
"""

import logging
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any

logger = logging.getLogger(__name__)


@dataclass
class ChatContext:
    """对话上下文，贯穿整个管线"""
    user_input: str
    stream: bool = False
    save_memory: bool = True
    session_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    enable_tts: Optional[bool] = None

    # 中间状态
    tool_memory_result: Optional[Dict] = None
    tool_decision: str = "do_not_execute"
    auto_execute_result: Optional[Dict] = None
    session_context: Optional[List[Dict]] = None
    relevant_memories: List = field(default_factory=list)
    experience_items: List = field(default_factory=list)
    crystallized_patterns: List = field(default_factory=list)
    context: List[Dict] = field(default_factory=list)
    trace_id: Optional[str] = None
    reply: Optional[str] = None

    # 结果
    result: Optional[Dict] = None


class ChatPipeline:
    """对话流程管线

    通过 agent_ref 访问 Agent 实例的：
    - config, memory_agent, context_orchestrator
    - tool_memory, skill_manager, tool_synthesizer
    - unified_retriever, crystallizer, trace_manager, neuHebb_manager
    - loop, llm_client, tool_executor
    - post_chat_pipeline, _trajectory_recorder, idle_tracker
    - _current_reasoning, _tool_messages_list
    """

    def __init__(self, agent_ref):
        self._agent = agent_ref

    # ---- 属性代理 ----
    @property
    def config(self):
        return self._agent.config

    @property
    def memory_agent(self):
        return self._agent.memory_agent

    @property
    def context_orchestrator(self):
        return self._agent.context_orchestrator

    @property
    def tool_memory(self):
        return getattr(self._agent, 'tool_memory', None)

    @property
    def skill_manager(self):
        return getattr(self._agent, 'skill_manager', None)

    @property
    def tool_synthesizer(self):
        return getattr(self._agent, 'tool_synthesizer', None)

    @property
    def unified_retriever(self):
        return getattr(self._agent, 'unified_retriever', None)

    @property
    def crystallizer(self):
        return getattr(self._agent, 'crystallizer', None)

    @property
    def trace_manager(self):
        return getattr(self._agent, 'trace_manager', None)

    @property
    def neuHebb_manager(self):
        return getattr(self._agent, 'neuHebb_manager', None)

    @property
    def loop(self):
        return getattr(self._agent, 'loop', None)

    @property
    def llm_client(self):
        return getattr(self._agent, 'llm_client', None)

    @property
    def tool_executor(self):
        return getattr(self._agent, 'tool_executor', None)

    @property
    def post_chat_pipeline(self):
        return getattr(self._agent, 'post_chat_pipeline', None)

    @property
    def idle_tracker(self):
        return getattr(self._agent, 'idle_tracker', None)

    @property
    def session_manager(self):
        return getattr(self._agent, 'session_manager', None)

    @property
    def _trajectory_recorder(self):
        return getattr(self._agent, '_trajectory_recorder', None)

    # ══════════════════════════════════════════════════════════════
    # 主入口
    # ══════════════════════════════════════════════════════════════

    async def execute(self, ctx: ChatContext) -> Dict[str, Any]:
        """执行完整的对话管线"""
        self._init_agent_state(ctx)

        # Step 0: 记录活动 + 轨迹
        await self._step_activity_tracking(ctx)

        # Step 0.5: Pre-LLM 检查
        await self._step_pre_llm_checks(ctx)

        # Step 1: 检索与上下文构建
        await self._step_retrieve_and_build_context(ctx)

        # Step 2: Evocate 注入
        self._step_evocate_injection(ctx)

        # Step 3: LLM 调用（含自动续写）
        await self._step_llm_call(ctx)

        # Step 4: 后处理
        await self._step_post_processing(ctx)

        return ctx.result

    # ══════════════════════════════════════════════════════════════
    # Step 0: 初始化 Agent 状态
    # ══════════════════════════════════════════════════════════════

    def _init_agent_state(self, ctx: ChatContext):
        """初始化 Agent 的临时状态"""
        self._agent._current_reasoning = None
        self._agent._tool_messages_list = []
        self._agent._current_user_input = ctx.user_input

    # ══════════════════════════════════════════════════════════════
    # Step 0: 活动追踪 + 轨迹记录
    # ══════════════════════════════════════════════════════════════

    async def _step_activity_tracking(self, ctx: ChatContext):
        """记录活动、会话恢复、轨迹启动"""
        # 递增对话轮次
        if not hasattr(self._agent, '_turn_count'):
            self._agent._turn_count = 0
        self._agent._turn_count += 1

        # 会话历史恢复
        if ctx.session_id:
            await self._restore_session_history(ctx)

        # 轨迹记录启动
        if self._trajectory_recorder:
            ctx.trace_id = self._trajectory_recorder.start_trace(
                session_id=ctx.session_id or "default",
                agent_id=self.config.agent_id,
                user_id=(ctx.metadata or {}).get("user_id", "anonymous"),
                metadata=ctx.metadata,
            )
            self._trajectory_recorder.record_event(
                trace_id=ctx.trace_id,
                event_type="user_input",
                data={"user_input": ctx.user_input[:500]},
            )

        # 记录活动，重置空闲计时
        if self.idle_tracker:
            self.idle_tracker.record_activity()

    async def _restore_session_history(self, ctx: ChatContext):
        """从 session 恢复对话历史"""
        try:
            record = self.session_manager.get_session(
                agent_id=self.config.agent_id,
                session_id=ctx.session_id,
            )
            if record and hasattr(record, 'messages') and len(record.messages) > 0:
                saved_messages = [
                    {"role": msg.role, "content": msg.content}
                    for msg in record.messages
                ]
                if len(saved_messages) > len(self._agent.conversation_history):
                    self._agent.conversation_history = saved_messages
                    logger.info(f"从 session {ctx.session_id} 恢复了 {len(saved_messages)} 条对话历史")

            ctx.session_context = self.session_manager.get_recent_context(
                agent_id=self.config.agent_id,
                session_id=ctx.session_id,
                max_messages=20,
            )
        except Exception as e:
            logger.warning(f"恢复 session {ctx.session_id} 失败: {e}")

    # ══════════════════════════════════════════════════════════════
    # Step 0.5: Pre-LLM 检查
    # ══════════════════════════════════════════════════════════════

    async def _step_pre_llm_checks(self, ctx: ChatContext):
        """ToolMemory 检查、技能获取、NL 合成"""
        await self._check_tool_memory(ctx)
        await self._check_skill_acquisition(ctx)
        await self._check_nl_synthesis(ctx)

    async def _check_tool_memory(self, ctx: ChatContext):
        """ToolMemory 条件反射式工具记忆检查"""
        if not self.tool_memory:
            return

        try:
            ctx.tool_memory_result, ctx.tool_decision = self.tool_memory.check_tool_memory(ctx.user_input)
            if not ctx.tool_memory_result:
                return

            logger.info(
                f"ToolMemory 命中: {ctx.tool_memory_result.get('tool_name')} "
                f"(置信度={ctx.tool_memory_result.get('confidence', 0):.2f}, "
                f"决策={ctx.tool_decision})"
            )

            if ctx.tool_decision == "auto_execute":
                await self._auto_execute_tool(ctx)

        except Exception as e:
            logger.warning(f"ToolMemory 检查失败: {e}")

    async def _auto_execute_tool(self, ctx: ChatContext):
        """自动执行肌肉记忆工具"""
        import asyncio as _asyncio

        tool_name = ctx.tool_memory_result.get('tool_name')
        confidence = ctx.tool_memory_result.get('confidence', 0)

        if confidence < 0.7:
            logger.info(f"工具 {tool_name} 置信度 {confidence:.2f} < 0.7，转为建议模式")
            ctx.tool_decision = "suggest"
            return

        MUSCLE_TIMEOUT = 5.0
        logger.info(f"自动执行工具: {tool_name} (超时={MUSCLE_TIMEOUT}s)")

        try:
            ctx.auto_execute_result = await _asyncio.wait_for(
                self.tool_executor.execute_from_memory_async(ctx.tool_memory_result, ctx.user_input),
                timeout=MUSCLE_TIMEOUT,
            )
            exec_status = ctx.auto_execute_result.get("status")
            if exec_status == "success":
                logger.info(f"工具自动执行成功: {tool_name}")
                ctx.tool_decision = "auto_executed"
            elif exec_status == "failure":
                error_msg = ctx.auto_execute_result.get("error", "未知错误")
                logger.warning(f"工具自动执行失败: {tool_name}, 错误: {error_msg}")
                ctx.tool_decision = "failed"
                await self._record_tool_failure(tool_name, ctx.user_input, error_msg)
        except _asyncio.TimeoutError:
            logger.warning(f"工具自动执行超时: {tool_name} (>{MUSCLE_TIMEOUT}s)")
            ctx.tool_decision = "timeout"
            ctx.auto_execute_result = None

    async def _record_tool_failure(self, tool_name: str, user_input: str, error_msg: str):
        """记录工具失败教训"""
        try:
            if hasattr(self._agent, '_record_tool_failure_lesson'):
                await self._agent._record_tool_failure_lesson(tool_name, user_input, error_msg)
        except Exception:
            pass

    async def _check_skill_acquisition(self, ctx: ChatContext):
        """主动技能获取检查"""
        if not self.skill_manager or not self.skill_manager.auto_acquire:
            return

        try:
            result = self.skill_manager.analyze_task(ctx.user_input)
            if result:
                sc = result.get("success_count", 0)
                if sc > 0:
                    acquired = [r.get("skill_name") for r in result.get("acquisition_results", []) if r.get("success")]
                    logger.info(f"主动技能获取: 成功安装 {sc} 个技能 {acquired}")
                elif result.get("missing_skills"):
                    logger.info(f"需要技能: {result['missing_skills']}，但未在市场中找到")
        except Exception as e:
            logger.warning(f"主动技能获取检查失败: {e}")

    async def _check_nl_synthesis(self, ctx: ChatContext):
        """NL 工具合成检查"""
        if not self.tool_synthesizer:
            return
        if self.skill_manager and self.skill_manager.auto_acquire:
            return

        try:
            action_keywords = ["帮我", "读取", "写入", "搜索", "下载", "转换", "生成",
                               "read", "write", "search", "download", "convert", "generate"]
            if not any(kw in ctx.user_input.lower() for kw in action_keywords):
                return

            skill_registry = getattr(self._agent, '_skill_registry', None)
            has_tool = False
            if skill_registry:
                has_tool = any(
                    skill_registry.get_skill(s.name)
                    for s in skill_registry.list_skills()
                    if any(kw in s.name.lower() for kw in ctx.user_input.lower().split())
                )

            if not has_tool:
                synth_result = self.tool_synthesizer.synthesize(
                    description=ctx.user_input,
                    author_id=self.config.agent_id,
                )
                if synth_result and synth_result.stage.value == "COMPLETED":
                    logger.info(
                        f"NL工具合成: {synth_result.tool.name} "
                        f"(置信度={synth_result.confidence:.2f})"
                    )
        except Exception as e:
            logger.warning(f"NL工具合成检查失败: {e}")

    # ══════════════════════════════════════════════════════════════
    # Step 1: 检索与上下文构建
    # ══════════════════════════════════════════════════════════════

    async def _step_retrieve_and_build_context(self, ctx: ChatContext):
        """统一检索 + 结晶经验 + 上下文构建"""
        # 启动推理链
        if self.trace_manager:
            ctx.trace_id = self.trace_manager.start_trace(ctx.user_input)

        # 统一检索
        await self._retrieve_memories(ctx)

        # 结晶经验检索
        await self._retrieve_crystallized_patterns(ctx)

        # 上下文构建（委托给 ContextOrchestrator）
        ctx.context = await self.context_orchestrator.build_context(
            user_input=ctx.user_input,
            tool_memory_result=ctx.tool_memory_result,
            auto_execute_result=ctx.auto_execute_result,
            tool_decision=ctx.tool_decision,
            experience_items=ctx.experience_items,
            relevant_memories=ctx.relevant_memories,
            crystallized_patterns=ctx.crystallized_patterns,
            session_context=ctx.session_context,
        )

    async def _retrieve_memories(self, ctx: ChatContext):
        """统一检索（UnifiedRetriever 或 MoE 降级）"""
        if self.unified_retriever:
            ctx.relevant_memories = self.unified_retriever.retrieve(
                ctx.user_input, limit=10, include_patterns=True
            )
            if ctx.trace_id and self.trace_manager:
                self.trace_manager.add_step(
                    ctx.trace_id, "retrieve",
                    ctx.user_input, f"找到 {len(ctx.relevant_memories)} 条记忆"
                )
        else:
            ctx.relevant_memories = self.memory_agent.moe_retrieve(ctx.user_input)

    async def _retrieve_crystallized_patterns(self, ctx: ChatContext):
        """结晶经验检索"""
        if not self.crystallizer:
            return

        try:
            ctx.crystallized_patterns = self.crystallizer.retrieve(ctx.user_input, limit=3)
            if ctx.trace_id and self.trace_manager:
                self.trace_manager.add_step(
                    ctx.trace_id, "crystallize",
                    ctx.user_input, f"检索到 {len(ctx.crystallized_patterns)} 条结晶经验"
                )
        except Exception as e:
            logger.warning(f"结晶经验检索失败: {e}")

    # ══════════════════════════════════════════════════════════════
    # Step 2: Evocate 注入
    # ══════════════════════════════════════════════════════════════

    def _step_evocate_injection(self, ctx: ChatContext):
        """Neurova-Evocate: 检索相关 Neurova Hebb 注入上下文"""
        if not self.neuHebb_manager:
            return

        try:
            neurova_hebbs = self.neuHebb_manager.retrieve_neurova_hebb(ctx.user_input)
            if neurova_hebbs:
                hebb_texts = [
                    f"[Retrieved Knowledge] {h.content} "
                    f"(source: {h.source}, confidence: {h.verification_score:.2f})"
                    for h in neurova_hebbs
                ]
                hebb_context = "\n".join(hebb_texts)
                for msg in ctx.context:
                    if msg.get("role") == "system":
                        msg["content"] += f"\n\n## Retrieved Knowledge (Neurova Hebb)\n{hebb_context}"
                        break
        except Exception as e:
            logger.warning(f"Neurova Hebb 检索失败: {e}")

    # ══════════════════════════════════════════════════════════════
    # Step 3: LLM 调用（含自动续写）
    # ══════════════════════════════════════════════════════════════

    async def _step_llm_call(self, ctx: ChatContext):
        """Agent Loop 调用 + 自动续写"""
        tools_for_llm = await self.context_orchestrator.build_tools_for_llm()

        # 移除已自动执行的工具
        if ctx.tool_decision == "auto_executed" and ctx.auto_execute_result and tools_for_llm:
            executed_tool = ctx.auto_execute_result.get("tool_name", "")
            original_count = len(tools_for_llm)
            tools_for_llm = [
                t for t in tools_for_llm
                if t.get("function", {}).get("name", "") != executed_tool
            ]
            if len(tools_for_llm) < original_count:
                logger.info(f"已从工具列表移除已执行工具: {executed_tool}")

        if self.loop:
            ctx.reply = await self._call_agent_loop(ctx, tools_for_llm)
        else:
            ctx.reply = await self._call_legacy(ctx)

        # 解析并执行文本中的工具调用
        ctx.reply = await self.tool_executor.execute_text_tool_calls(ctx.reply, ctx.user_input)

    async def _call_agent_loop(self, ctx: ChatContext, tools_for_llm: Optional[List]) -> str:
        """通过 Agent Loop 调用 LLM"""
        try:
            if ctx.stream:
                return await self._call_loop_stream(ctx, tools_for_llm)
            else:
                return await self._call_loop_normal(ctx, tools_for_llm)
        except Exception as e:
            # API 配置错误不 fallback
            if self._is_api_config_error(e):
                logger.error(f"Agent Loop API 配置错误: {e}")
                raise
            # Loop 特定错误 fallback 到 legacy
            logger.warning(f"Agent Loop failed: {e}, falling back to legacy")
            return await self._call_legacy(ctx)

    async def _call_loop_stream(self, ctx: ChatContext, tools_for_llm: Optional[List]) -> str:
        """流式调用 Agent Loop"""
        reply_parts = []
        gen = self.loop.predict_step(messages=ctx.context, tools=tools_for_llm, stream=True)
        async for event in gen:
            if isinstance(event, dict) and event.get("type") == "content":
                reply_parts.append(event.get("data", ""))
            else:
                reply_parts.append(str(event))
        return "".join(reply_parts)

    async def _call_loop_normal(self, ctx: ChatContext, tools_for_llm: Optional[List]) -> str:
        """非流式调用 Agent Loop（含自动续写）"""
        response = await self.loop.predict_step(
            messages=ctx.context, tools=tools_for_llm, stream=False
        )
        reply = response.content if response else ""

        # 捕获思考过程
        if response and hasattr(response, 'reasoning_content') and response.reasoning_content:
            self._agent._current_reasoning = response.reasoning_content

        # 自动续写
        reply = await self._auto_continue(ctx, response, reply, tools_for_llm)

        return reply

    async def _auto_continue(
        self, ctx: ChatContext, response, reply: str, tools_for_llm: Optional[List]
    ) -> str:
        """截断自动续写逻辑"""
        MAX_CONTINUE_ROUNDS = 100
        MAX_TOTAL_CHARS = getattr(self.llm_client.config, 'max_tokens', 8192) * 10
        OVERLAP_CHECK_LEN = 200
        OVERLAP_THRESHOLD = 0.6
        MIN_CONTINUE_LEN = 10
        TAIL_CONTEXT_CHARS = 800
        SIMILARITY_WINDOW = 3
        SIMILARITY_THRESHOLD = 0.8
        MAX_TOOL_CALL_ROUNDS = 5

        # 语言检测
        hint = self._build_continue_hint(ctx.user_input, reply)

        continue_round = 0
        recent_contents = []
        tool_call_rounds = 0

        while (response
               and getattr(response, 'finish_reason', '') == 'length'
               and not getattr(response, 'tool_calls', None)
               and continue_round < MAX_CONTINUE_ROUNDS
               and len(reply) < MAX_TOTAL_CHARS):

            continue_round += 1
            tail_text = (response.content or '')[-TAIL_CONTEXT_CHARS:].strip()

            if tail_text:
                full_hint = f"{hint}\n\n<previous-tail>\n{tail_text}\n</previous-tail>"
            else:
                full_hint = hint

            ctx.context.append({"role": "assistant", "content": response.content})
            ctx.context.append({"role": "user", "content": full_hint})

            _tools = tools_for_llm if continue_round == 1 else None

            if _tools and getattr(response, 'tool_calls', None):
                tool_call_rounds += 1
                if tool_call_rounds >= MAX_TOOL_CALL_ROUNDS:
                    _tools = None

            logger.info(f"截断续写第 {continue_round} 轮 (tools={'on' if _tools else 'off'}, 已输出 {len(reply)} 字符)")

            response = await self.loop.predict_step(
                messages=ctx.context, tools=_tools, stream=False
            )
            new_content = getattr(response, 'content', '') if response else ''

            # 护栏 A: 续写过短
            if not new_content or len(new_content.strip()) < MIN_CONTINUE_LEN:
                break

            # 护栏 B: 重叠检测
            prev_tail = reply[-OVERLAP_CHECK_LEN:] if len(reply) >= OVERLAP_CHECK_LEN else reply
            new_head = new_content[:OVERLAP_CHECK_LEN]
            if prev_tail and new_head:
                overlap_chars = sum(1 for a, b in zip(prev_tail, new_head) if a == b)
                if overlap_chars / max(len(prev_tail), 1) > OVERLAP_THRESHOLD:
                    break

            # 护栏 C: 语义循环检测
            recent_contents.append(new_content[:500])
            if len(recent_contents) > SIMILARITY_WINDOW:
                recent_contents.pop(0)
            if len(recent_contents) >= SIMILARITY_WINDOW:
                if self._agent._detect_content_loop(recent_contents, SIMILARITY_THRESHOLD):
                    break

            # 护栏 D: 工具调用循环
            if getattr(response, 'tool_calls', None):
                tool_call_rounds += 1
                if tool_call_rounds >= MAX_TOOL_CALL_ROUNDS:
                    _tools = None

            reply += new_content

        return reply

    def _build_continue_hint(self, user_input: str, reply: str) -> str:
        """构建自适应续写提示（中英文）"""
        sample = (user_input or '') + (reply or '')
        cjk = sum(1 for c in sample if '\u4e00' <= c <= '\u9fff')
        is_cjk = cjk > len(sample) * 0.15 if sample else False

        if is_cjk:
            return (
                "<system-hint>上轮回复因长度限制被截断。"
                "请结合下文 <previous-tail> 片段判断："
                "若仍需执行操作则立刻调用工具；"
                "若仅为文本未写完，从截断处直接接续，不要重复已说内容。"
                "</system-hint>"
            )
        else:
            return (
                "<system-hint>Previous reply was truncated due to length limit. "
                "Review <previous-tail> below and decide: "
                "if tools are still needed, call them now; "
                "if only text remains, continue from cutoff, do NOT repeat."
                "</system-hint>"
            )

    async def _call_legacy(self, ctx: ChatContext) -> str:
        """传统方法 fallback"""
        if ctx.stream:
            return await self._agent._chat_stream(ctx.user_input, ctx.context, ctx.save_memory)
        else:
            return await self._agent._chat_normal(ctx.user_input, ctx.context, ctx.save_memory)

    @staticmethod
    def _is_api_config_error(exc: Exception) -> bool:
        """判断是否为 API 配置类错误（不应 fallback）"""
        try:
            from openai import BadRequestError, AuthenticationError
            if isinstance(exc, (BadRequestError, AuthenticationError)):
                return True
        except ImportError:
            pass
        status = getattr(exc, 'status_code', None) or getattr(exc, 'code', None)
        return status in (400, 401, 403)

    # ══════════════════════════════════════════════════════════════
    # Step 4: 后处理
    # ══════════════════════════════════════════════════════════════

    async def _step_post_processing(self, ctx: ChatContext):
        """对话历史更新、轨迹记录、PostChatPipeline"""
        # 更新对话历史
        self.memory_agent.update_history(ctx.user_input, ctx.reply)

        # 记录 LLM 调用事件
        if self._trajectory_recorder and ctx.trace_id:
            self._trajectory_recorder.record_event(
                trace_id=ctx.trace_id,
                event_type="llm_call_end",
                data={
                    "reply_length": len(ctx.reply) if ctx.reply else 0,
                    "model": self.config.llm_config.model,
                },
            )

        # 推理链记录
        if ctx.trace_id and self.trace_manager:
            try:
                total_tokens = len(ctx.user_input) + len(ctx.reply) if ctx.reply else len(ctx.user_input)
                self.trace_manager.finish_trace(ctx.trace_id, ctx.reply or "", total_tokens=total_tokens)
            except Exception as e:
                logger.warning(f"推理链记录失败: {e}")

        # 结晶器观察
        if self.crystallizer:
            last_tool = getattr(self._agent, '_last_tool_used', None)
            if last_tool:
                try:
                    self.crystallizer.observe(tool_name=last_tool, context=ctx.user_input, success=True)
                except Exception as e:
                    logger.warning(f"结晶器观察失败: {e}")

        # PostChatPipeline
        post_result = await self.post_chat_pipeline.process(
            user_input=ctx.user_input,
            reply=ctx.reply,
            session_id=ctx.session_id,
            save_memory=ctx.save_memory,
            enable_tts=ctx.enable_tts,
            metadata=ctx.metadata,
        )

        # 组装结果
        ctx.result = {
            "text": ctx.reply,
            "audio_path": post_result.get("audio_path"),
            "audio_data": post_result.get("audio_data"),
            "cognitive_score": post_result.get("cognitive_score"),
            "evolution_triggered": False,
            "experience_used": len(ctx.experience_items) > 0,
            "experience_count": len(ctx.experience_items),
            "session_id": post_result.get("actual_session_id"),
            "reasoning": getattr(self._agent, '_current_reasoning', None),
            "tool_messages": self._collect_tool_messages(),
            "proactive_question": post_result.get("proactive_question"),
        }

        # 结束轨迹
        if self._trajectory_recorder and ctx.trace_id:
            self._trajectory_recorder.record_event(
                trace_id=ctx.trace_id,
                event_type="output_end",
                data={"result": ctx.result},
            )
            self._trajectory_recorder.end_trace(ctx.trace_id)

    def _collect_tool_messages(self) -> List[Dict]:
        """收集工具调用消息"""
        return getattr(self._agent, '_tool_messages_list', []) or []
