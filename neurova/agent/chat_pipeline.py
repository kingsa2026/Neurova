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

from neurova.core.logger import get_logger
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from neurova.agent.crystallized_experience_manager import CrystallizedExperienceManager
from neurova.agent.memory_retrieval_chain import MemoryRetrievalChain, RetrievalContext, RetrievalStrategy
from neurova.agent.retriever_adapters import (
    CacheRetrieverAdapter,
    FallbackRetrieverAdapter,
    MoERetrieverAdapter,
    UnifiedRetrieverAdapter,
)
from neurova.agent.tool_execution_manager import ExecutionStatus, TimeoutStrategy, ToolExecutionManager

logger = get_logger(__name__)

# ── 思考程度（light/standard/deep）→ 系统提示指令 ──────────────
# 提示词方式对所有模型通用；standard 为默认行为不注入
_THINKING_DIRECTIVES: Dict[str, str] = {
    "light": "【回答模式：简洁速答】跳过冗长分析与铺垫，直接给出要点式简短回答（尽量不超过 5 句话）。不要展示思考过程，除非用户明确要求。",
    "deep": (
        "【回答模式：深度思考】请进行充分、严谨的分析后再作答：先拆解问题与约束条件，"
        "从多角度权衡取舍，必要时分步骤论证、给出依据，并主动指出风险与替代方案；"
        "输出结构化、深入、可执行的完整回答。"
    ),
}


def _thinking_directive(effort: Optional[str]) -> str:
    """思考程度 → 注入系统提示的指令文本；standard/未知/None 返回空（不注入）"""
    return _THINKING_DIRECTIVES.get((effort or "").lower(), "")


@dataclass
class ChatContext:
    """对话上下文，贯穿整个管线"""

    user_input: str
    stream: bool = False
    save_memory: bool = True
    session_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    enable_tts: bool = False
    # [蜂群流式] 可选事件发射器 (event_type, data) -> None：
    # 流式路径每收到 content/reasoning chunk 时回调，供 SwarmManager
    # 转发 SUBAGENT_CHUNK 事件；不影响聚合返回值
    event_emitter: Optional[Callable] = None

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
    caller_provided_history: bool = False

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
        # 初始化 ToolExecutionManager（深度模块）
        self._tool_execution_manager = ToolExecutionManager()
        # 初始化 MemoryRetrievalChain（深度模块）
        self._memory_retrieval_chain = MemoryRetrievalChain()
        self._init_memory_retrieval_chain()
        # 初始化 CrystallizedExperienceManager（深度模块）
        # Bug 4 修复: 注入 memory_manager(有 recall() 方法) 而非 memory_agent(MemCore,无 recall)
        # Bug 5 修复: 传入 agent_id/user_id 用于缓存键隔离,防止跨用户污染
        self._crystallized_experience_manager = CrystallizedExperienceManager(
            crystallizer=self.crystallizer,
            memory_manager=getattr(self._agent, "memory_manager", None),
            agent_id=getattr(self.config, "agent_id", None),
            user_id=getattr(self.config, "user_id", None),
        )
        logger.debug(
            "ChatPipeline initialized with ToolExecutionManager, MemoryRetrievalChain, and CrystallizedExperienceManager"
        )

    def _init_memory_retrieval_chain(self):
        """初始化记忆检索责任链"""
        # 添加检索器（按优先级排序）

        # 1. UnifiedRetriever（最高优先级）
        if self.unified_retriever:
            adapter = UnifiedRetrieverAdapter(self.unified_retriever)
            self._memory_retrieval_chain.add_retriever(adapter)
            logger.debug("Added UnifiedRetrieverAdapter to retrieval chain")

        # 2. MoERetriever（中等优先级）
        if hasattr(self._agent, "memory_agent") and self._agent.memory_agent:
            moe_router = getattr(self._agent.memory_agent, "moe_router", None)
            if moe_router:
                adapter = MoERetrieverAdapter(moe_router)
                self._memory_retrieval_chain.add_retriever(adapter)
                logger.debug("Added MoERetrieverAdapter to retrieval chain")

        # 3. CacheRetriever（低优先级）
        cache_adapter = CacheRetrieverAdapter()
        self._memory_retrieval_chain.add_retriever(cache_adapter)
        logger.debug("Added CacheRetrieverAdapter to retrieval chain")

        # 4. FallbackRetriever（最低优先级）
        if hasattr(self._agent, "memory_agent") and self._agent.memory_agent:
            adapter = FallbackRetrieverAdapter(self._agent.memory_agent)
            self._memory_retrieval_chain.add_retriever(adapter)
            logger.debug("Added FallbackRetrieverAdapter to retrieval chain")

        logger.info(
            f"MemoryRetrievalChain initialized with {len(self._memory_retrieval_chain.get_retrievers())} retrievers"
        )

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
        return getattr(self._agent, "tool_memory", None)

    @property
    def skill_manager(self):
        return getattr(self._agent, "skill_manager", None)

    @property
    def tool_synthesizer(self):
        return getattr(self._agent, "tool_synthesizer", None)

    @property
    def unified_retriever(self):
        return getattr(self._agent, "unified_retriever", None)

    @property
    def crystallizer(self):
        return getattr(self._agent, "crystallizer", None)

    @property
    def crystallized_experience_manager(self):
        return self._crystallized_experience_manager

    @property
    def trace_manager(self):
        return getattr(self._agent, "trace_manager", None)

    @property
    def neuHebb_manager(self):
        return getattr(self._agent, "neuHebb_manager", None)

    @property
    def loop(self):
        return getattr(self._agent, "loop", None)

    @property
    def llm_client(self):
        return getattr(self._agent, "llm_client", None)

    @property
    def tool_executor(self):
        return getattr(self._agent, "tool_executor", None)

    @property
    def tool_execution_manager(self):
        """工具执行管理器（深度模块）"""
        return self._tool_execution_manager

    @property
    def memory_retrieval_chain(self):
        """记忆检索责任链（深度模块）"""
        return self._memory_retrieval_chain

    @property
    def post_chat_pipeline(self):
        return getattr(self._agent, "post_chat_pipeline", None)

    @property
    def idle_tracker(self):
        return getattr(self._agent, "idle_tracker", None)

    @property
    def session_manager(self):
        return getattr(self._agent, "session_manager", None)

    @property
    def _trajectory_recorder(self):
        return getattr(self._agent, "_trajectory_recorder", None)

    @property
    def session_sync_manager(self):
        """获取 SessionSyncManager（延迟导入）"""
        try:
            from neurova.sync.session_sync_manager import get_session_sync_manager

            return get_session_sync_manager()
        except Exception as e:
            logger.debug("SessionSyncManager 导入失败: %s", e)
            return None

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

        # Step 0.7 (R-3): 附件注入——在 build_context 之前并入 user_input，
        # 否则 LLM 拿到的是构建上下文时的旧输入（附件内容永远进不了模型）。
        await self._step_inject_attachments(ctx)

        # Step 1: 检索与上下文构建
        await self._step_retrieve_and_build_context(ctx)
        # 图像切片在此挂到 context（text 已在注入时并入 user_input）
        self._flush_vision_attachments(ctx)

        # Step 2: Evocate 注入
        self._step_evocate_injection(ctx)

        # Step 3: LLM 调用（含自动续写）
        await self._step_llm_call(ctx)

        # Step 4: 后处理
        await self._step_post_processing(ctx)

        # Step 5: 广播最终回复到 SessionSyncManager
        await self._sync_final_reply(ctx)

        return ctx.result

    async def _sync_final_reply(self, ctx: ChatContext):
        """广播最终回复到 SessionSyncManager"""
        if not ctx.reply:
            return

        from neurova.sync.session_sync_manager import EventType as _ET

        await self._sync_event(
            ctx,
            _ET.AGENT_REPLY,
            {
                "content": ctx.reply,
                "reasoning": getattr(self._agent, "_current_reasoning", None),
                "tool_messages": self._collect_tool_messages(),
                "metadata": ctx.metadata,
            },
        )

    async def _sync_event(self, ctx: ChatContext, event_type: Any, payload: Dict[str, Any]):
        """通用事件广播方法"""
        sync_manager = self.session_sync_manager
        if not sync_manager:
            return

        try:
            from neurova.sync.session_sync_manager import SessionEvent

            # S2 修复 (Critical #2/#3 split-brain): 用 register_or_create_session
            # 注册 ctx.session_id (而非 create_session 生成新 ID),保证文件层
            # (SessionManager) 与内存层 (SessionSyncManager) session_id 收敛.
            session_id = ctx.session_id or "default"
            user_id = (ctx.metadata or {}).get("user_id", "anonymous")
            sync_manager.register_or_create_session(
                session_id=session_id,
                user_id=user_id,
                agent_id=self.config.agent_id,
                metadata={"source": "chat_pipeline"},
            )

            # 创建事件
            event = SessionEvent(event_type=event_type, session_id=session_id, source_channel="agent", payload=payload)

            # 广播事件
            await sync_manager.broadcast_event(session_id, event)

        except Exception as e:
            # WARN #2 修复: 升级 debug → warning + exc_info=True.
            # 原 logger.debug 吞掉异常,丢失堆栈,运维无法定位广播失败根因.
            # 事件同步失败非致命 (不影响主对话流程),但应可观测.
            logger.warning("SessionSyncManager event sync failed: %s", e, exc_info=True)

    # ══════════════════════════════════════════════════════════════
    # Step 0: 初始化 Agent 状态
    # ══════════════════════════════════════════════════════════════

    def _init_agent_state(self, ctx: ChatContext):
        """初始化 Agent 的临时状态"""
        self._agent._current_reasoning = None
        self._agent._tool_messages_list = []
        self._agent._current_user_input = ctx.user_input
        # session_id 透传给工具层（蜂群工具派生子 Agent 时广播事件用）
        self._agent._current_session_id = ctx.session_id
        # [蜂群流式] event_emitter 允许经 metadata 透传（Agent.chat 未显式
        # 传参时）， SwarmManager 以 metadata 携带发射器，此处提取到 ctx
        if ctx.event_emitter is None and isinstance(ctx.metadata, dict):
            candidate = ctx.metadata.get("event_emitter")
            if callable(candidate):
                ctx.event_emitter = candidate

    # ══════════════════════════════════════════════════════════════
    # Step 0: 活动追踪 + 轨迹记录
    # ══════════════════════════════════════════════════════════════

    async def _step_activity_tracking(self, ctx: ChatContext):
        """记录活动、会话恢复、轨迹启动"""
        # 递增对话轮次
        if not hasattr(self._agent, "_turn_count"):
            self._agent._turn_count = 0
        self._agent._turn_count += 1

        # 会话历史恢复
        # 当调用方通过 metadata.history 提供了对话历史时，跳过 session_manager 恢复
        # 因为调用方的历史是权威来源，session_manager 可能包含过期/重复数据
        caller_provided_history = (
            ctx.metadata
            and isinstance(ctx.metadata, dict)
            and "history" in ctx.metadata
        )
        if ctx.session_id and not caller_provided_history:
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
            if record and hasattr(record, "messages") and len(record.messages) > 0:
                saved_messages = [{"role": msg.role, "content": msg.content} for msg in record.messages]
                if len(saved_messages) > len(self._agent.conversation_history):
                    self._agent.conversation_history = saved_messages
                    logger.info("从 session %s 恢复了 %s 条对话历史", ctx.session_id, len(saved_messages))

            ctx.session_context = self.session_manager.get_recent_context(
                agent_id=self.config.agent_id,
                session_id=ctx.session_id,
                max_messages=20,
            )
        except Exception as e:
            logger.warning("恢复 session %s 失败: %s", ctx.session_id, e)

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
            logger.warning("ToolMemory 检查失败: %s", e)

    async def _auto_execute_tool(self, ctx: ChatContext):
        """自动执行肌肉记忆工具（使用 ToolExecutionManager 深度模块）"""
        tool_name = ctx.tool_memory_result.get("tool_name")
        confidence = ctx.tool_memory_result.get("confidence", 0)

        # P-D 修复（docs/tool-memory-muscle-analysis.md）：移除原 0.7 硬门。
        # 决策阈值已由 check_tool_memory 的 dynamic_threshold 单源裁定
        # （RSI 可调）；此处再设 0.7 会形成调参死区（RSI 把阈值调到 0.7
        # 以下时本门仍然拦截，闭环失效）。
        logger.info("自动执行工具: %s (使用 ToolExecutionManager)", tool_name)

        try:
            # 通过 ToolExecutionManager 执行工具
            execution_context = await self.tool_execution_manager.execute(
                tool_name=tool_name,
                params=ctx.tool_memory_result.get("params", {}),
                user_input=ctx.user_input,
                executor=self.tool_executor,
                timeout=5.0,  # 默认5秒超时
                strategy=TimeoutStrategy.STRICT,
                max_retries=3,
                metadata={
                    "source": "muscle_memory",
                    "confidence": confidence,
                    "session_id": ctx.session_id,
                },
                callback=self._on_tool_execution_status_change,
            )

            # 检查执行结果
            if execution_context.status == ExecutionStatus.COMPLETED:
                ctx.auto_execute_result = execution_context.result
                exec_status = ctx.auto_execute_result.get("status") if ctx.auto_execute_result else None
                if exec_status == "success":
                    logger.info("工具自动执行成功: %s", tool_name)
                    ctx.tool_decision = "auto_executed"
                elif exec_status == "failure":
                    error_msg = ctx.auto_execute_result.get("error", "未知错误")
                    logger.warning("工具自动执行失败: %s, 错误: %s", tool_name, error_msg)
                    ctx.tool_decision = "failed"
                    await self._record_tool_failure(tool_name, ctx.user_input, error_msg)
            elif execution_context.status == ExecutionStatus.TIMEOUT:
                logger.warning("工具自动执行超时: %s (>%ss)", tool_name, execution_context.timeout)
                ctx.tool_decision = "timeout"
                ctx.auto_execute_result = None
            elif execution_context.status == ExecutionStatus.CANCELLED:
                logger.warning("工具自动执行被取消: %s", tool_name)
                ctx.tool_decision = "cancelled"
                ctx.auto_execute_result = None
            elif execution_context.status == ExecutionStatus.FAILED:
                error_msg = execution_context.error or "未知错误"
                logger.warning("工具自动执行失败: %s, 错误: %s", tool_name, error_msg)
                ctx.tool_decision = "failed"
                ctx.auto_execute_result = {"status": "failure", "error": error_msg}
                await self._record_tool_failure(tool_name, ctx.user_input, error_msg)
            else:
                logger.warning("工具自动执行未知状态: %s, 状态: %s", tool_name, execution_context.status)
                ctx.tool_decision = "failed"
                ctx.auto_execute_result = None

        except Exception as e:
            logger.error("工具自动执行异常: %s, 错误: %s", tool_name, e)
            ctx.tool_decision = "failed"
            ctx.auto_execute_result = {"status": "failure", "error": str(e)}

    def _on_tool_execution_status_change(self, event):
        """工具执行状态变更回调"""
        logger.debug("工具执行状态变更: %s %s -> %s", event.context_id, event.old_status.value, event.new_status.value)
        # 可以在这里添加状态变更日志、指标收集等

    async def _record_tool_failure(self, tool_name: str, user_input: str, error_msg: str):
        """记录工具失败教训"""
        try:
            if hasattr(self._agent, "_record_tool_failure_lesson"):
                await self._agent._record_tool_failure_lesson(tool_name, user_input, error_msg)
        except Exception as e:
            logger.warning(f"记录工具失败教训时出错: {tool_name}, 错误: {e}", exc_info=True)

    async def _check_skill_acquisition(self, ctx: ChatContext):
        """主动技能获取检查

        ADR 0012 修复:
        - 正确 await analyze_task（async def）
        - 对齐返回字段：skills_needed / auto_acquire
        - except 用 logger.exception 记录完整 traceback，非静默吞掉
        """
        if not self.skill_manager or not self.skill_manager.auto_acquire:
            return

        try:
            result = await self.skill_manager.analyze_task(ctx.user_input)
            if not result:
                return

            skills_needed = result.get("skills_needed", [])
            auto_acquire = result.get("auto_acquire", False)

            if auto_acquire and skills_needed:
                acquired = [r.get("skill_name") for r in skills_needed if isinstance(r, dict) and r.get("success")]
                if acquired:
                    logger.info("主动技能获取: 成功安装 %s 个技能 %s", len(acquired), acquired)
                else:
                    logger.info("需要技能: %s，但未在市场中找到", [r.get("skill_name") for r in skills_needed if isinstance(r, dict)])
                    # [BUGFIX] 市场未命中时，不应仅记录日志后放弃：回退到 NL 合成自主创建。
                    # 此前 `_check_nl_synthesis` 被 `skill_manager.auto_acquire` 互斥屏蔽，
                    # 导致「查询到所需技能结构但市场无此技能」时既不获取、也不合成——agent
                    # 永远无法自主创建工具/技能。这里用 force=True 显式绕过该守卫。
                    await self._check_nl_synthesis(ctx, force=True)
        except Exception:
            logger.exception("主动技能获取检查失败")

    async def _check_nl_synthesis(self, ctx: ChatContext, force: bool = False):
        """NL 工具合成检查

        Args:
            ctx: 对话上下文
            force: 为 True 时忽略 auto_acquire 互斥守卫，用于「主动技能获取未命中」
                时的自主创建回退（见 `_check_skill_acquisition`）。
        """
        if not self.tool_synthesizer:
            return
        if not force and self.skill_manager and self.skill_manager.auto_acquire:
            return

        try:
            action_keywords = [
                "帮我",
                "读取",
                "写入",
                "搜索",
                "下载",
                "转换",
                "生成",
                "read",
                "write",
                "search",
                "download",
                "convert",
                "generate",
            ]
            if not any(kw in ctx.user_input.lower() for kw in action_keywords):
                return

            skill_registry = getattr(self._agent, "_skill_registry", None)
            has_tool = False
            # Bug A-1 修复 [HIGH]: 原代码 `kw in s.name.lower() for kw in ctx.user_input.lower().split()`
            # 有两个问题:
            # 1. CJK tokenization: split() 对中文不分词，"搜索用户数据" 整段一个词，
            #    "搜索用户数据" in "search_tool" 永远 False
            # 2. 方向反了: 应检查 skill 的关键词是否在 user_input 中，而非反过来
            #    （skill name 通常是英文如 "search_tool"，user_input 通常是中文如 "搜索用户数据"）
            # 修复: 双向匹配——英文 token 保留原方向（user_input 词在 skill 文本中），
            #       CJK 关键词反向匹配（skill 文本中的中文词在 user_input 中），
            #       与 N-10 修复方式一致（子串匹配）。
            # 注意: 用 `is not None` 而非真值检查——SkillRegistry 定义了 __len__，
            # 空注册表时 bool(registry)==False（与 N-1 同一根因）。
            if skill_registry is not None:
                user_input_lower = ctx.user_input.lower()
                has_tool = any(
                    self._skill_keywords_match_input(s, user_input_lower)
                    for s in skill_registry.list_skills()
                )

            if not has_tool:
                # Bug T-1 修复: synthesize 签名是 (description, context=None)，
                # 原代码传 author_id 不存在该参数 → TypeError 被外层 except 吞掉，NL 合成永远失败
                synth_result = self.tool_synthesizer.synthesize(
                    description=ctx.user_input,
                    context={"author_id": self.config.agent_id},
                )
                # Bug T-2 修复: ToolSynthesisResult 无 stage/tool/confidence 字段，
                # 它们在 synthesized_tool 上；且 SynthesisStage.COMPLETED.value == "completed"（小写）
                if synth_result and synth_result.success and synth_result.synthesized_tool:
                    tool = synth_result.synthesized_tool
                    if tool.stage.value == "completed":
                        logger.info(
                            "NL工具合成: %s (置信度=%.2f)",
                            tool.name,
                            tool.confidence,
                        )
                        # Bug N-1 修复 [CRITICAL]: 原代码合成成功后只 log，从不注册。
                        # 导致每次相同请求都重新合成，且合成出的工具永远无法被 agent
                        # 发现和调用——整个 NL 合成管线是死代码。
                        # 修复: 将 SynthesizedTool 转为 Skill manifest 并注册到
                        # skill_registry，使后续轮次可通过 list_skills/get_skill 发现。
                        # 注意: 用 `is not None` 而非真值检查——SkillRegistry 定义了
                        # __len__，空注册表时 bool(registry)==False，会导致空注册表时
                        # 跳过注册（恰好是最需要注册的场景）。
                        if skill_registry is not None:
                            self._register_synthesized_tool(skill_registry, tool)
        except Exception:
            logger.exception("NL工具合成检查失败")

    def _skill_keywords_match_input(self, skill, user_input_lower: str) -> bool:
        """检查 skill 的关键词是否出现在 user_input 中（兼容 CJK）。

        Bug A-1: 原代码 `kw in s.name.lower() for kw in ctx.user_input.lower().split()`
        方向反了且 CJK 不分词。本方法实现双向匹配：

        1. 英文 token 匹配（保留原方向）: user_input 中的英文词出现在 skill 文本中
        2. CJK 关键词匹配（反向）: skill 文本中的中文关键词出现在 user_input 中

        Args:
            skill: Skill manifest 对象（含 name/description）
            user_input_lower: 已小写的用户输入

        Returns:
            bool: 是否匹配
        """
        import re

        # 收集 skill 的文本字段
        texts = []
        if skill.name:
            texts.append(skill.name.lower())
        if skill.description:
            texts.append(skill.description.lower())
        skill_text = " ".join(texts)

        # 1. 英文 token 匹配（原逻辑: user_input 的英文词在 skill 文本中）
        for kw in user_input_lower.split():
            if kw and len(kw) >= 3 and re.search(r"[a-z]", kw) and kw in skill_text:
                return True

        # 2. CJK 关键词双向子串匹配（与 N-10 修复方式一致）
        #    从 skill_text 中找中文关键词，检查是否在 user_input 中
        cjk_keywords = [
            "搜索", "查找", "查询", "读取", "写入", "处理", "分析",
            "生成", "获取", "创建", "下载", "转换", "文件", "数据",
            "图片", "文本", "网页", "数据库", "接口", "任务", "用户",
        ]
        for kw in cjk_keywords:
            if kw in skill_text and kw in user_input_lower:
                return True

        return False

    def _register_synthesized_tool(self, skill_registry, synthesized_tool):
        """将合成的工具注册到 skill_registry。

        Bug N-1: 将 SynthesizedTool 转为 Skill manifest 并注册，使后续轮次
        可通过 list_skills/get_skill 发现已合成的工具，避免重复合成。

        Args:
            skill_registry: SkillRegistry 实例
            synthesized_tool: SynthesizedTool 实例
        """
        from pathlib import Path

        from neurova.skills.models import Skill, SkillSource

        manifest = Skill(
            id=synthesized_tool.tool_id or synthesized_tool.name,
            name=synthesized_tool.name,
            description=synthesized_tool.description,
            source=SkillSource.LOCAL,
            config={
                "parameters_schema": synthesized_tool.parameters_schema,
                "tool_sequence": synthesized_tool.tool_sequence,
                "confidence": synthesized_tool.confidence,
                "category": synthesized_tool.category,
                "synthesized": True,
            },
        )
        # 合成工具无文件路径，用哨兵路径标记
        sentinel_path = Path("<synthesized>") / manifest.id
        if skill_registry.register_skill(manifest, sentinel_path):
            logger.info("已注册合成工具到 skill_registry: %s", manifest.id)
        else:
            logger.debug("合成工具 %s 已存在，跳过注册", manifest.id)

    # ══════════════════════════════════════════════════════════════
    # Step 1.5 (R-3): 附件注入
    # ══════════════════════════════════════════════════════════════

    async def _step_inject_attachments(self, ctx: ChatContext):
        """把附件内容注入对话上下文（R-3 附件多模态）。

        契约:
        - metadata.attachments（console attach_files 注入）逐项读取磁盘内容
        - 文本/文档（txt/md/rst/code/docx/xlsx/pptx/pdf/csv）抽取文本并入
          ctx.user_input（"用户上传了文件 X 内容如下"段落）
        - 图像 → 转为 OpenAI content list（多模态 LLM 直接接收）
        - 音频/视频/解析失败 → 降级为文件名提示，不中断对话

        无 attachments 时零副作用；文件读取失败不抛异常（附件问题不拖垮聊天）。
        """
        if not isinstance(ctx.metadata, dict):
            return
        attachments = ctx.metadata.get("attachments")
        if not isinstance(attachments, list) or not attachments:
            return

        enriched, vision_parts = self._inject_attachments_into_input(
            ctx.user_input or "", attachments
        )
        ctx.user_input = enriched
        # 附件注入在 build_context 之前：文本已进入 user_input，构建上下文时
        # 会被送入 LLM；图像切片由 build_context 之后的 _apply_vision_attachments
        # 挂到 context 最后一条 user 消息（此处 ctx.context 尚未构建，推迟处理）。
        self._pending_vision_parts = vision_parts

        logger.info(
            "[附件注入] %d 个附件处理完成, vision_parts=%d",
            len(attachments),
            len(vision_parts),
        )

    def _flush_vision_attachments(self, ctx: ChatContext):
        """build_context 之后调用：把保存的图像切片挂到 context 最后一条 user 消息。"""
        vision_parts = getattr(self, "_pending_vision_parts", None)
        if vision_parts:
            self._apply_vision_attachments(ctx, vision_parts)
            self._pending_vision_parts = None

    def _read_attachment_bytes(self, file_id: str) -> Optional[bytes]:
        """按 file_id 读取附件字节（测试可 monkeypatch）"""
        try:
            from neurova.api.endpoints import files_api

            return files_api.get_attachment_bytes(file_id)
        except Exception:
            return None

    def _inject_attachments_into_input(
        self, user_input: str, attachments: List[Dict]
    ) -> Tuple[str, List[Dict]]:
        """把附件并入用户文本；图像切片单独收集为 vision content parts。"""
        from neurova.attachment_parser import extract_attachment_text

        parts: List[str] = []
        if user_input:
            parts.append(user_input)
        vision_parts: List[Dict] = []

        for att in attachments:
            filename = att.get("filename") or "附件"
            file_type = att.get("file_type") or "file"
            mime = att.get("mime_type") or "application/octet-stream"
            file_id = att.get("file_id") or ""

            try:
                data = self._read_attachment_bytes(file_id)
            except Exception:
                data = None

            if file_type == "image" and data:
                import base64

                b64 = base64.b64encode(data).decode("ascii")
                vision_parts.append(
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}
                )
                parts.append(f"[用户上传了图片: {filename}, 请结合图片回答]")
                continue

            text, status = extract_attachment_text(data, filename, file_type)
            if text:
                parts.append(
                    f"[用户上传了文件 {filename}，以下为该文件的完整内容（请直接使用，无需调用工具读取）]\n{text}"
                )
            else:
                parts.append(f"[用户上传了文件 {filename}（{file_type}），无法解析文本内容]")
                if status not in ("unsupported_format", "empty_file"):
                    logger.debug("[附件注入] %s 未抽取文本: %s", filename, status)

        return "\n\n".join(parts), vision_parts

    def _apply_vision_attachments(self, ctx: ChatContext, vision_parts: List[Dict]):
        """把图像切片应用到 ctx.context 最后一条 user 消息（OpenAI 多模态格式）。

        R-3 修复: 全量扫描找最后一条 user 消息（context 末尾可能是 system/记忆
        等非 user 角色，仅查 [-1] 会漏挂，导致模型收不到图像）。
        """
        if not ctx.context:
            return
        target = None
        for msg in reversed(ctx.context):
            if isinstance(msg, dict) and msg.get("role") == "user":
                target = msg
                break
        if target is None:
            return
        target["content"] = [{"type": "text", "text": target.get("content", "") or ""}, *vision_parts]

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
        # 从 metadata 中提取语音上下文和调用方对话历史
        voice_context = None
        caller_history = None
        if ctx.metadata and isinstance(ctx.metadata, dict):
            voice_context = ctx.metadata.get("voice_context")
            caller_history = ctx.metadata.get("history")

        # 优先使用调用方传入的完整对话历史（包含 user+assistant）
        if caller_history is not None:
            ctx.session_context = caller_history
            ctx.caller_provided_history = True

        logger.info(
            "[CHAT_TRACE] session_context msgs=%d, user_input=%s",
            len(ctx.session_context) if ctx.session_context else 0,
            ctx.user_input[:50],
        )

        ctx.context = await self.context_orchestrator.build_context(
            user_input=ctx.user_input,
            tool_memory_result=ctx.tool_memory_result,
            auto_execute_result=ctx.auto_execute_result,
            tool_decision=ctx.tool_decision,
            experience_items=ctx.experience_items,
            relevant_memories=ctx.relevant_memories,
            crystallized_patterns=ctx.crystallized_patterns,
            session_context=ctx.session_context,
            voice_context=voice_context,
        )

    async def _retrieve_memories(self, ctx: ChatContext):
        """统一检索（使用 MemoryRetrievalChain 深度模块）"""
        # Bug C-2 修复：ChatContext 无 user_id 字段，应从 metadata 取值
        # 对比同文件 line 283 正确写法: (ctx.metadata or {}).get("user_id", "anonymous")
        user_id = (ctx.metadata or {}).get("user_id", "anonymous")

        # 创建检索上下文
        retrieval_context = RetrievalContext(
            query=ctx.user_input,
            limit=10,
            user_id=user_id,
            session_id=ctx.session_id,
            strategy=RetrievalStrategy.CHAIN,  # 责任链策略（按优先级降级）
            min_quality=0.3,  # 最低质量要求
            metadata={
                "session_id": ctx.session_id,
                "trace_id": ctx.trace_id,
            },
        )

        # 使用 MemoryRetrievalChain 执行检索
        result = await self.memory_retrieval_chain.retrieve(retrieval_context)

        # 提取记忆内容
        ctx.relevant_memories = result.memories

        # 记录检索统计
        logger.info(
            f"Memory retrieval completed: source={result.source}, quality={result.quality_level.value}, memories={len(result.memories)}"
        )

        # 记录到追踪系统
        if ctx.trace_id and self.trace_manager:
            self.trace_manager.add_step(
                ctx.trace_id,
                "retrieve",
                ctx.user_input,
                f"找到 {len(ctx.relevant_memories)} 条记忆 (质量: {result.quality_level.value})",
            )

    async def _retrieve_crystallized_patterns(self, ctx: ChatContext):
        """结晶经验检索（使用 CrystallizedExperienceManager 深度模块）"""
        if not self.crystallized_experience_manager:
            return

        # 使用 CrystallizedExperienceManager 检索（支持重试、降级、缓存）
        result = await self.crystallized_experience_manager.retrieve(
            query=ctx.user_input,
            limit=3,
            use_cache=True,
            fallback_to_memory=True,
        )

        # 转换结果格式
        if result.experiences:
            ctx.crystallized_patterns = [
                {
                    "id": exp.id,
                    "content": exp.content,
                    "method": exp.method,
                    "confidence": exp.confidence,
                    "score": exp.score,
                    "source": exp.source,
                }
                for exp in result.experiences
            ]

        # 记录检索统计
        logger.info(
            f"Crystallized experience retrieval completed: "
            f"status={result.status.value}, source={result.source}, "
            f"experiences={len(result.experiences)}, latency={result.latency_ms:.1f}ms"
        )

        # 记录到追踪系统
        if ctx.trace_id and self.trace_manager:
            self.trace_manager.add_step(
                ctx.trace_id,
                "crystallize",
                ctx.user_input,
                f"检索到 {len(ctx.crystallized_patterns)} 条结晶经验 (状态: {result.status.value})",
            )

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
            logger.warning("Neurova Hebb 检索失败: %s", e)

    # ══════════════════════════════════════════════════════════════
    # Step 3: LLM 调用（含自动续写）
    # ══════════════════════════════════════════════════════════════

    def _apply_thinking_effort(self, ctx: ChatContext):
        """按 metadata.thinking_effort（light/standard/deep）注入回答深度指令。

        采用提示词方式而非原生 reasoning 参数：对所有模型通用，
        且避免不支持的 API 因未知参数报 400。
        """
        effort = ""
        if isinstance(ctx.metadata, dict):
            effort = str(ctx.metadata.get("thinking_effort") or "").lower()
        directive = _thinking_directive(effort)
        if not directive:
            return
        target = None
        for msg in ctx.context:
            if isinstance(msg, dict) and msg.get("role") == "system":
                target = msg
                break
        if target is None:
            ctx.context.insert(0, {"role": "system", "content": directive})
        else:
            existing = str(target.get("content") or "")
            if "【回答模式" in existing:
                # 已有思考模式标记时原位替换，避免多轮累积
                import re

                target["content"] = re.sub(r"【回答模式[^\n]*】[^\n]*", directive, existing, count=1)
            else:
                target["content"] = f"{existing}\n\n{directive}".strip()

    async def _step_llm_call(self, ctx: ChatContext):
        """Agent Loop 调用 + 自动续写"""
        self._apply_thinking_effort(ctx)
        tools_for_llm = await self.context_orchestrator.build_tools_for_llm()

        # 移除已自动执行的工具
        if ctx.tool_decision == "auto_executed" and ctx.auto_execute_result and tools_for_llm:
            executed_tool = ctx.auto_execute_result.get("tool_name", "")
            original_count = len(tools_for_llm)
            tools_for_llm = [t for t in tools_for_llm if t.get("function", {}).get("name", "") != executed_tool]
            if len(tools_for_llm) < original_count:
                logger.info("已从工具列表移除已执行工具: %s", executed_tool)

        # 广播 AGENT_THINKING 事件
        try:
            from neurova.sync.session_sync_manager import EventType

            await self._sync_event(
                ctx,
                EventType.AGENT_THINKING,
                {
                    "stage": "llm_call",
                    "tools_count": len(tools_for_llm) if tools_for_llm else 0,
                },
            )
        except ImportError:
            logger.debug("EventType 导入失败，跳过事件广播")

        if self.loop:
            ctx.reply = await self._call_agent_loop(ctx, tools_for_llm)
        else:
            ctx.reply = await self._call_legacy(ctx)

        # 解析并执行文本中的工具调用
        ctx.reply = await self.tool_executor.execute_text_tool_calls(ctx.reply, ctx.user_input)

        # 广播工具调用结果
        tool_messages = self._collect_tool_messages()
        if tool_messages:
            try:
                from neurova.sync.session_sync_manager import EventType

                await self._sync_event(
                    ctx,
                    EventType.AGENT_TOOL_RESULT,
                    {
                        "tool_messages": tool_messages,
                    },
                )
            except ImportError:
                logger.debug("EventType 导入失败，跳过事件广播")

    async def _call_agent_loop(self, ctx: ChatContext, tools_for_llm: Optional[List]) -> str:
        """通过 Agent Loop 调用 LLM"""
        try:
            if ctx.stream:
                return await self._call_loop_stream(ctx, tools_for_llm)
            else:
                return await self._call_loop_normal(ctx, tools_for_llm)
        except Exception as e:
            # LLM 供应商错误（限流/认证/连接/token 超限）必须直接上抛：
            # 静默 fallback 到 legacy 会掩盖真实原因（实测缺陷：限流被转译成
            # 无关的 TypeError，用户拿到空回复）。legacy 仅供 Loop 自身实现
            # 错误时兜底。
            from neurova.llm_client import LLMError

            if isinstance(e, LLMError) or self._is_api_config_error(e):
                logger.error("Agent Loop LLM 供应商错误，不 fallback: %s", e)
                raise
            # Loop 实现错误 fallback 到 legacy（记录原因，禁止静默）
            logger.warning("Agent Loop failed (%s: %s), falling back to legacy", type(e).__name__, e)
            return await self._call_legacy(ctx)

    async def _call_loop_stream(self, ctx: ChatContext, tools_for_llm: Optional[List]) -> str:
        """流式调用 Agent Loop。

        Bug N-6 修复: 原 else 分支 `reply_parts.append(str(event))` 把所有非
        content 事件（reasoning/tool_call/tool_result/done）的字典字符串表示
        拼入回复，污染最终文本，导致 execute_text_tool_calls 在污染文本上跑正则。

        修复: 仅 content 事件的 data 进入回复；其他事件是元数据（思考过程、
        工具调用、工具结果、完成信号），不属于回复文本，跳过即可。done 事件的
        reply 字段是完整回复的快照，可作为空回复时的兜底。

        C1 修复: 原生 function-calling 模式的 tool_call/tool_result 事件原先被
        完全丢弃，导致 _collect_tool_messages() 在原生模式下返回空、
        AGENT_TOOL_RESULT 事件不携带工具消息。现将这两类事件接入
        _tool_messages_list（与文本模式工具调用写入同一列表），保持 N-6 修复
        （不入回复文本）不变。
        """
        reply_parts = []
        # C1: 捕获原生 function-calling 的工具事件，循环后合并到 _tool_messages_list
        native_tool_events: List[Dict] = []
        # Bug V2-6 修复:predict_step 是 async def,返回 coroutine。
        # 原代码 `gen = self.loop.predict_step(...)` 缺 await,对 coroutine
        # 迭代会抛 TypeError: 'coroutine' object is not async iterable。
        gen = await self.loop.predict_step(messages=ctx.context, tools=tools_for_llm, stream=True)
        emitter = ctx.event_emitter
        async for event in gen:
            if not isinstance(event, dict):
                continue
            etype = event.get("type")
            if etype == "content":
                reply_parts.append(event.get("data", ""))
                # [蜂群流式] 转发 chunk 给事件发射器（如 SwarmManager）
                if emitter is not None:
                    try:
                        emitter("content", event.get("data", ""))
                    except Exception as e:  # noqa: BLE001 - 发射失败不影响主流程
                        logger.debug("event_emitter 回调失败: %s", e)
            elif etype == "done":
                # done 事件携带完整回复快照，仅在未累积到 content 时兜底
                if not reply_parts and event.get("reply"):
                    reply_parts.append(event["reply"])
            elif etype == "reasoning":
                # [蜂群流式] reasoning chunk 同样转发
                if emitter is not None:
                    try:
                        emitter("reasoning", event.get("data", ""))
                    except Exception as e:  # noqa: BLE001
                        logger.debug("event_emitter 回调失败: %s", e)
            elif etype in ("tool_call", "tool_result"):
                # C1: 原生 function-calling 元数据，接入工具消息列表
                native_tool_events.append(event)
                # [真流式] 仅当调用方显式开启 emit_tool_events（console SSE 桥接）
                # 时才转发工具事件；默认关闭——该通道同时服务蜂群子 Agent
                # 逐 token 流，需保持纯文本契约（见 test_chat_stream_events）
                if (
                    emitter is not None
                    and isinstance(ctx.metadata, dict)
                    and ctx.metadata.get("emit_tool_events")
                ):
                    try:
                        emitter(etype, event.get("data"))
                    except Exception as e:  # noqa: BLE001 - 发射失败不影响主流程
                        logger.debug("event_emitter 转发 %s 失败: %s", etype, e)
            # reasoning 等其他元数据事件不入回复
        # C1: 合并原生工具事件到 _tool_messages_list，供 _collect_tool_messages() 读取
        if native_tool_events:
            tool_list = getattr(self._agent, "_tool_messages_list", None)
            if tool_list is None:
                tool_list = []
                self._agent._tool_messages_list = tool_list
            tool_list.extend(native_tool_events)
            logger.debug("原生模式捕获 %d 个工具事件", len(native_tool_events))
        return "".join(reply_parts)

    async def _call_loop_normal(self, ctx: ChatContext, tools_for_llm: Optional[List]) -> str:
        """非流式调用 Agent Loop（含自动续写）"""
        response = await self.loop.predict_step(messages=ctx.context, tools=tools_for_llm, stream=False)
        reply = response.content if response else ""

        # 捕获思考过程
        if response and hasattr(response, "reasoning_content") and response.reasoning_content:
            self._agent._current_reasoning = response.reasoning_content

        # 自动续写
        reply = await self._auto_continue(ctx, response, reply, tools_for_llm)

        return reply

    async def _auto_continue(self, ctx: ChatContext, response, reply: str, tools_for_llm: Optional[List]) -> str:
        """截断自动续写逻辑"""
        MAX_CONTINUE_ROUNDS = 100
        MAX_TOTAL_CHARS = getattr(self.llm_client.config, "max_tokens", 8192) * 10
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
        ctx_snapshot = list(ctx.context)

        while (
            response
            and getattr(response, "finish_reason", "") == "length"
            and not getattr(response, "tool_calls", None)
            and continue_round < MAX_CONTINUE_ROUNDS
            and len(reply) < MAX_TOTAL_CHARS
        ):

            continue_round += 1
            tail_text = (response.content or "")[-TAIL_CONTEXT_CHARS:].strip()

            if tail_text:
                full_hint = f"{hint}\n\n<previous-tail>\n{tail_text}\n</previous-tail>"
            else:
                full_hint = hint

            ctx_snapshot.append({"role": "assistant", "content": response.content})
            ctx_snapshot.append({"role": "user", "content": full_hint})

            _tools = tools_for_llm if continue_round == 1 else None

            # Bug A-5 修复: 删除死代码——while 条件 (line 938) 已保证
            # `not getattr(response, "tool_calls", None)`，此处的
            # `if _tools and getattr(response, "tool_calls", None):` 永远 False。

            logger.info("截断续写第 %s 轮 (tools=%s, 已输出 %s 字符)", continue_round, 'on' if _tools else 'off', len(reply))

            response = await self.loop.predict_step(messages=ctx_snapshot, tools=_tools, stream=False)
            new_content = getattr(response, "content", "") if response else ""

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

            # Bug A-5 修复: 删除死代码——while 条件 (line 938) 已保证
            # `not getattr(response, "tool_calls", None)`，如果新 response 有
            # tool_calls，下一轮 while 条件会 False 退出循环，此处的
            # `_tools = None` 不会影响任何后续行为。

            reply += new_content

        return reply

    def _build_continue_hint(self, user_input: str, reply: str) -> str:
        """构建自适应续写提示（中英文）"""
        sample = (user_input or "") + (reply or "")
        cjk = sum(1 for c in sample if "\u4e00" <= c <= "\u9fff")
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
        """传统 fallback — 直接通过 llm_client 调用 LLM

        注意: 此方法仅在 Agent Loop 不可用时使用。
        历史更新和记忆保存由 _step_post_processing() 统一处理，
        此处不再重复。
        """
        if ctx.stream:
            return await self._call_legacy_stream(ctx)
        else:
            return await self._call_legacy_normal(ctx)

    async def _call_legacy_normal(self, ctx: ChatContext) -> str:
        """非流式 fallback"""
        response = await self.llm_client.chat(ctx.context)
        if isinstance(response, dict):
            if response.get("success"):
                raw = response.get("response", "")
                if hasattr(raw, "content"):
                    reply = raw.content
                elif isinstance(raw, dict):
                    reply = raw.get("content", raw.get("text", str(raw)))
                else:
                    reply = str(raw)
            else:
                reply = f"[LLM Error] {response.get('error', 'Unknown error')}"
        elif hasattr(response, "content"):
            reply = response.content
        else:
            reply = str(response)
        return reply

    async def _call_legacy_stream(self, ctx: ChatContext) -> str:
        """流式 fallback

        chat_stream 产出 LLMResponse 对象（与 _predict_stream 同契约）：
        content 字段进入回复并向 emitter 转发；错误 dict 以原始信息抛
        RuntimeError——不得把对象当字符串 join 掩盖真实 LLM 错误。
        """
        reply_parts = []
        emitter = ctx.event_emitter
        async for chunk in self.llm_client.chat_stream(ctx.context):
            if isinstance(chunk, dict):
                if chunk.get("error"):
                    raise RuntimeError(f"LLM 流式调用失败: {chunk['error']}")
                continue
            content = getattr(chunk, "content", "") or ""
            if content:
                reply_parts.append(content)
                if emitter is not None:
                    try:
                        emitter("content", content)
                    except Exception as e:  # noqa: BLE001 - 转发失败不影响主流程
                        logger.debug("legacy 流式 emitter 转发失败: %s", e)
        return "".join(reply_parts)

    @staticmethod
    def _is_api_config_error(exc: Exception) -> bool:
        """判断是否为 API 配置类错误（不应 fallback）"""
        try:
            from openai import AuthenticationError, BadRequestError

            if isinstance(exc, (BadRequestError, AuthenticationError)):
                return True
        except ImportError:
            pass
        status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
        return status in (400, 401, 403)

    # ══════════════════════════════════════════════════════════════
    # Step 4: 后处理
    # ══════════════════════════════════════════════════════════════

    async def _step_post_processing(self, ctx: ChatContext):
        """对话历史更新、轨迹记录、PostChatPipeline"""
        if not ctx.caller_provided_history:
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
                logger.warning("推理链记录失败: %s", e)

        # 结晶器观察
        if self.crystallizer:
            last_tool = getattr(self._agent, "_last_tool_used", None)
            if last_tool:
                try:
                    self.crystallizer.observe(tool_name=last_tool, context=ctx.user_input, success=True)
                except Exception as e:
                    logger.warning("结晶器观察失败: %s", e)

        # PostChatPipeline - 优先使用 PipelineExecutor
        # Bug #5+11: 提取 _run_post_chat_pipeline 辅助方法，消除 fallback 代码重复
        # Bug #5: 检查 post_chat_pipeline 是否为 None，避免 AttributeError
        post_result = await self._run_post_chat_pipeline(ctx)

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
            "reasoning": getattr(self._agent, "_current_reasoning", None),
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

    async def _run_post_chat_pipeline(self, ctx: ChatContext) -> Dict[str, Any]:
        """Bug #5+11: 提取的 post_chat_pipeline 调用辅助方法

        优先使用 PipelineExecutor，失败时 fallback 到 post_chat_pipeline。
        Bug #5: 检查 post_chat_pipeline 是否为 None，避免 AttributeError。
        Bug #11: 消除 fallback 代码重复。
        """
        pipeline_executor = getattr(self._agent, "pipeline_executor", None)
        if pipeline_executor:
            try:
                from neurova.pipeline_executor import PipelineRequest

                request = PipelineRequest(
                    user_input=ctx.user_input,
                    reply=ctx.reply,
                    session_id=ctx.session_id,
                    save_memory=ctx.save_memory,
                    enable_tts=ctx.enable_tts,
                    metadata=ctx.metadata or {},
                )
                response = await pipeline_executor.execute(request)
                # 转换为旧格式以保持兼容性
                return {
                    "actual_session_id": response.session_id,
                    "audio_path": response.audio_url,
                    "audio_data": response.metadata.get("audio_data"),
                    "cognitive_score": response.cognitive_score,
                    "proactive_question": response.metadata.get("proactive_question"),
                }
            except Exception as e:
                logger.warning("PipelineExecutor 执行失败，fallback 到 post_chat_pipeline: %s", e)

        # Bug #5: 检查 post_chat_pipeline 是否为 None，避免 AttributeError
        if self.post_chat_pipeline is None:
            raise RuntimeError(
                "post_chat_pipeline is not initialized — cannot execute post-chat processing. "
                "Either initialize Agent.post_chat_pipeline or configure pipeline_executor."
            )

        return await self.post_chat_pipeline.process(
            user_input=ctx.user_input,
            reply=ctx.reply,
            session_id=ctx.session_id,
            save_memory=ctx.save_memory,
            enable_tts=ctx.enable_tts,
            metadata=ctx.metadata,
        )

    def _collect_tool_messages(self) -> List[Dict]:
        """收集工具调用消息"""
        return getattr(self._agent, "_tool_messages_list", []) or []
