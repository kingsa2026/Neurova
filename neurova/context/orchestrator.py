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
from typing import Any, Dict, List, Optional
import datetime

from .builder import ContextBuilder
from .injector import UnifiedContextInjector
from .models import TokenBudget
from .recovery import assign_turn_ids

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

    def __init__(
        self,
        agent_ref,
        use_pool: bool = True,
        auto_tag: bool = False,
        session_id: str = None,
    ):
        self._agent = agent_ref
        self.use_pool = use_pool
        self.auto_tag = auto_tag
        # 根因 C 修复: 持有 session_id 标识, 让 session 隔离在 pool/chunk 级别都生效
        self._session_id = session_id
        # P1-1④ ack 集：最近一次 build_context 视图内的池 chunk hash
        self._last_view_hashes: set = set()

        # 修2（2026-09-09）：对话窗口 token 预算压缩（zcode 式）
        # _window_summarizer: async (dropped_msgs, previous_summary) -> Optional[str]
        # _window_compaction_cache: session_id -> {"summary", "covered_hashes"}
        #   （已摘要覆盖的消息 hash，跨轮增量摘要不重复调 LLM）
        self._window_summarizer = None
        self._window_compaction_cache: dict = {}
        # 增量防抖阈值（类级常量语义）：距上次摘要新追加消息数 ≤ 此值时复用缓存摘要
        self._DELTA_RESUMMARY_MSGS = 4
        # 本轮刚折叠消息的 hash 集（当轮 draw 防召回；下轮起正常参与语义召回）
        self._last_folded_hashes: set = set()
        self._last_archived_window_hashes: set = set()

        # 初始化 ContextPool（如果启用）
        if use_pool:
            from neurova.context_pool import ContextPool

            # 动态获取 Token 预算
            model_name = getattr(agent_ref.config, "llm_model", "gpt-4")
            max_tokens = ContextPool.get_token_budget_for_model(model_name)

            # P1-1③ 接线：驱逐台账持久层（WAL+FTS5，按 agent 分库）+
            # 摘要压缩器（经 agent.llm_client.chat 桥接真 LLM）
            _ledger_db = None
            _summarizer = None
            try:
                from neurova.context.eviction_ledger_db import EvictionLedgerDB

                _agent_id = getattr(agent_ref, "agent_id", "default")
                _ledger_db = EvictionLedgerDB(
                    db_path=f"data/context_ledger/{_agent_id}.db",
                    user_id=getattr(agent_ref, "user_id", "default"),
                    agent_id=_agent_id,
                )
            except Exception as e:
                logger.warning("驱逐台账初始化失败（回退内存台账）: %s", e)

            try:
                from neurova.context.summarizing_compressor import SummarizingCompressor

                async def _llm_digest_call(prompt: str) -> str:
                    """摘要 LLM 桥：MultiModelLLMClient.chat 的 dict 契约提取 content"""
                    response = await agent_ref.llm_client.chat(
                        [{"role": "user", "content": prompt}],
                        model=getattr(agent_ref.config, "llm_model", None),
                    )
                    if isinstance(response, dict):
                        return str(response.get("content") or "")
                    return str(getattr(response, "content", "") or "")

                _summarizer = SummarizingCompressor(llm_call=_llm_digest_call, timeout_s=60)
            except Exception as e:
                logger.warning("摘要压缩器初始化失败（摘要回写停用）: %s", e)

            self.context_pool = ContextPool(
                user_id=getattr(agent_ref, "user_id", "default"),
                agent_id=getattr(agent_ref, "agent_id", "default"),
                session_id=session_id,
                ledger_db=_ledger_db,
                summarizer=_summarizer,
                max_tokens=max_tokens,
                auto_tag=auto_tag,
                ttl_seconds=0,  # [无损归档] 池是永久归档，TTL 不门禁调取（永不丢失）
            )
            logger.info(
                "ContextPool 初始化完成（无损归档模式），模型: %s，Token 预算: %s, session_id: %s",
                model_name, max_tokens, session_id,
            )
        else:
            self.context_pool = None

    def set_session_id(self, session_id: str) -> None:
        """根因 C 修复: 运行时切换 session_id（用于跨 session 调取）

        RES-P2-4：切换时裁剪 _window_compaction_cache——该缓存按 session_id
        记账（每会话一条摘要+hash 集合）且此前永不清理，Agent 长期服务多
        会话时随历史会话数无界增长。摘要可随时按未覆盖消息重建（零丢失），
        只保留当前会话条目即可。
        """
        self._session_id = session_id
        if self.context_pool is not None:
            self.context_pool.session_id = session_id
        cache = self._window_compaction_cache
        if len(cache) > 1:
            keep_key = session_id or "_"
            kept = cache.pop(keep_key, None)
            cache.clear()
            if kept is not None:
                cache[keep_key] = kept

    @property
    def session_id(self) -> Optional[str]:
        return self._session_id

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

    def _analyze_user_emotion(self, user_input: str) -> Optional[Dict[str, Any]]:
        """分析用户情感并更新长期情感状态机

        根因修复（三处断链）:
        1. 原实现 analyze() 未传 update_state=True → EmotionHubEngine 的 17 情感
           状态机从不累积，长期情感倾向永远为空；
        2. EmotionAnalyzer() 用默认 agent_id="default" → 多 agent 情感状态互相污染；
        3. 返回的分数字典没有 "label" 键，注入点 get("label", "neutral") 恒为 neutral。
        P1-D: 状态流统一经由 EmotionConductionManager（此前零调用骨架），
        使其统计/历史/共情融合能力在主流程中真实生效。
        """
        try:
            from neurova.cognitive_layers.emotion_context_layer.emotion_conduction import (
                get_emotion_conduction_manager,
            )

            agent_id = str(getattr(getattr(self._agent, "config", None), "agent_id", "default") or "default")
            manager = get_emotion_conduction_manager(agent_id)

            # 补课 7：注入 EmotionModule 语义分析器（主分析源收敛，消除
            # hub 关键词表"好"字效应）；memory_manager 缺失自动走 hub 兜底
            memory_manager = getattr(self._agent, "memory_manager", None)
            emotion_module = getattr(memory_manager, "emotion_module", None) if memory_manager else None
            if emotion_module is not None:
                manager.set_emotion_module(emotion_module)

            turn_scores = manager.analyze_text_emotion(user_input)
            if turn_scores:
                manager.update_emotional_state(turn_scores)

            # 本轮主导情感（argmax 分数）
            turn_label = max(turn_scores.items(), key=lambda kv: kv[1])[0] if turn_scores else "neutral"
            turn_intensity = float(turn_scores.get(turn_label, 0.0)) if turn_scores else 0.0

            if not turn_scores:
                # 无情感关键词：仅当长期状态机已有倾向时才注入（纯中性且无历史
                # 时返回 None，避免每轮注入噪音——与旧注入频度契约兼容）
                dominant = manager.get_dominant_emotion()
                if not dominant:
                    return None
                style = manager.apply_emotion_to_style()
                return {
                    "label": "neutral",
                    "intensity": 0.0,
                    "scores": {},
                    "long_term_dominant": dominant,
                    "tone": style.get("tone", "neutral"),
                }

            # 长期状态（状态机已随 update 更新）
            dominant = manager.get_dominant_emotion()
            style = manager.apply_emotion_to_style()

            return {
                "label": turn_label or "neutral",
                "intensity": turn_intensity,
                "scores": turn_scores,
                "long_term_dominant": dominant,
                "tone": style.get("tone", "neutral"),
            }
        except Exception as e:
            logger.debug("情感分析跳过: %s", e)
            return None

    def _collect_pending_questions(self, limit: int = 2) -> list:
        """收集待探索问题注入上下文（注入即 mark_asked 进入冷却，防止重复打扰）

        根因修复: QuestionQueueManager 此前零调用——生成的永无出口。
        """
        qm = getattr(self._agent, "question_queue_manager", None)
        if not qm:
            return []
        items = []
        try:
            for q in qm.get_pending_questions()[:limit]:
                items.append({"id": q.id, "content": q.content})
                qm.mark_asked(q.id)
        except Exception as e:
            logger.debug("收集待探索问题跳过: %s", e)
        return items

    def _apply_tool_lifecycle(self, tools: Optional[List[Dict]]) -> Optional[List[Dict]]:
        """应用工具生命周期过滤与权重排序（委托 EvolutionOrchestrator.on_before_tool_selection）

        根因修复: on_before_tool_selection 此前零生产调用——归档/冻结工具永远
        出现在 LLM 工具列表中，降级工具不加权。
        """
        if not tools:
            return tools
        try:
            evolution = getattr(self._agent, "evolution", None)
            hook = getattr(evolution, "on_before_tool_selection", None)
            if not hook:
                return tools

            names = [t["function"]["name"] for t in tools if isinstance(t, dict) and t.get("function", {}).get("name")]
            result = hook(available_tools=names)
            if not isinstance(result, dict):
                return tools

            filtered = set(result.get("filtered", []) or [])
            ranking = [n for n in (result.get("ranking", []) or []) if n not in filtered]
            if not ranking:
                return tools

            by_name = {
                t["function"]["name"]: t
                for t in tools
                if isinstance(t, dict) and t.get("function", {}).get("name")
            }
            ordered = [by_name[n] for n in ranking if n in by_name]
            # ranking 未覆盖的工具（如新增）保持相对顺序追加在尾部（按名字判断过滤）
            covered = set(by_name)
            ordered.extend(
                t
                for t in tools
                if isinstance(t, dict)
                and t.get("function", {}).get("name")
                and t["function"]["name"] not in covered
                and t["function"]["name"] not in filtered
            )
            return ordered if ordered else tools
        except Exception as e:
            logger.debug("工具生命周期过滤跳过: %s", e)
            return tools

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
                show_empathy=getattr(self._agent.config, "show_empathy", True),
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
        # P2-11（OpenOcta 启发 SnapshotForSession）：优先消费会话身份快照
        # （ChatPipeline 每轮经 session_snapshot 冻结，同会话内身份写入
        # 不改变当前 prompt，下次会话生效）；未装配快照时活值兜底（零行为
        # 变化）。
        frozen = getattr(self._agent, "_frozen_identity_snapshot", None)
        if isinstance(frozen, dict) and frozen.get("soul"):
            system_instructions = [frozen["soul"]]
            if frozen.get("personality"):
                system_instructions.append(frozen["personality"])
            if frozen.get("constitution"):
                system_instructions.append(frozen["constitution"])
        else:
            system_instructions = [self.soul]
            if self.personality:
                system_instructions.append(self.personality)
            if self.config.constitution:
                system_instructions.append(self.config.constitution)

        # Bug T-1 修复:注入当前时间上下文(避免 LLM 误用训练截止日期回答时间问题)
        # build_context 是 chat_pipeline 实际调用的路径(build_system_prompt 只是工具方法,未被调用),
        # 所以必须在此处注入时间,否则 LLM 看不到真实当前时间。
        system_instructions.append(self._build_current_time_section())

        # 批次 C：恒定规则段（工具使用方法论/环境块/记忆写入规则）——除日期
        # 外全部恒定，system 会话内字节稳定；动态内容走 envelope（injector）
        from neurova.context.rules_sections import build_all_sections

        system_instructions.append(
            build_all_sections(workspace_path=str(getattr(self.config, "workspace_path", "") or ""))
        )

        # 使用配置的行为规则
        developer_instructions = list(self.config.behavior_rules)
        if tools_desc:
            developer_instructions.append(tools_desc)

        # Phase 2.5: 分析用户输入的情感状态（并更新长期情感状态机）
        agent_emotion = self._analyze_user_emotion(user_input)

        # Phase 2.8: 收集反思日志
        reflection_logs: list = []
        if self.growth_log_manager:
            try:
                validated = self.growth_log_manager.get_validated_logs(limit=3)
                pending = self.growth_log_manager.get_pending_logs(limit=2)
                # 根因修复: ReflectionLogEntry 的真实字段是 content/type（此前读
                # l.lesson/l.reflection_type 不存在 → AttributeError 被吞 → 永远为空）
                reflection_logs = [
                    {
                        "lesson": (l.insights[0] if l.insights else l.content) or l.title,
                        "reflection_type": l.type.value,
                        "status": l.status.value,
                    }
                    for l in validated + pending
                ]
            except Exception as e:
                logger.debug("反思日志获取跳过: %s", e)

        # Phase 3: 构建 ContextInput → ContextCollector → 候选池
        # session_context 包含完整的 user+assistant 历史（优先使用）
        # conversation_history 只有 user 消息且不更新（仅作 fallback）
        # P1-7（OpenOcta 启发 toolTurnRepair）：repair 配对完整性
        # 审计⑦：repair 必须在视图重建（剥 tool_calls）之后——先 repair 会在
        # tool_calls 在场时判"配对完整"保留 role:"tool"，随后重建剥掉
        # tool_calls → 孤儿 tool 消息直发 LLM（provider 400）。
        # 顺序：先重建 → repair 兜剥字段的残留 → 发模型。
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
            # ════════════════════════════════════════════════════════
            # 归档层（无损活水）：把可复用的上下文沉淀进池
            # 池 = 永久归档（不 clear、不驱逐、不裁剪），视图按需调取。
            # 目标：① 省 token（无关归档不进视图）② 永不丢失 ③ 缓存命中
            # ════════════════════════════════════════════════════════

            # 归档对话轮次（老轮次可被后续语义召回 → 对话永不丢失）
            # P1-1①：写入侧打标 + tool 结果以 TOOL_CALL 源归档（带 pairs_with）
            self._archive_conversation_to_pool(conversation_context)

            # 归档记忆
            for memory in relevant_memories or []:
                if isinstance(memory, dict):
                    content = memory.get("content", str(memory))
                else:
                    content = str(memory)
                self.context_pool.add_context(ContextInput(source=ContextSource.MEMORY, content=content, priority=70))

            # 归档经验（D1 收敛：与结晶产物按内容键去重，结晶优先）
            for tag, content, prio in dedupe_experience_sources(experience_items, crystallized_patterns):
                self.context_pool.add_context(
                    ContextInput(source=ContextSource.EXPERIENCE, content=f"{tag}{content}", priority=prio)
                )

            # 归档反思日志（持久教训，可被语义召回）
            for log in reflection_logs:
                self.context_pool.add_context(
                    ContextInput(source=ContextSource.REFLECTION, content=log.get("lesson", str(log)), priority=60)
                )

            # ════════════════════════════════════════════════════════
            # 视图层（按需调取 + 稳定前缀）
            # 顺序设计（缓存友好）：
            #   [固定 system 前缀] → [对话窗口 append-only] →
            #   [语义调取块] → [本轮瞬态] → [当前输入]
            # 调取块变化只影响尾部，不破坏前缀缓存。
            # ════════════════════════════════════════════════════════

            # 1. 固定 system 前缀（每轮字节级一致 → 前缀缓存命中）
            context: List[Dict] = []
            for instruction in system_instructions:
                context.append({"role": "system", "content": instruction})
            for instruction in developer_instructions:
                context.append({"role": "system", "content": instruction})

            # 2. 对话窗口（原始时序，append-only）
            # 修2（2026-09-09）：token 预算压缩——折叠发生在归档之后，
            # 被折叠消息原文已入池、可经 [历史回忆] 语义召回（零丢失）。
            # 审计⑦：视图重建剥 tool_calls/tool_call_id（只保留 role+content），
            # 先重建后 repair——残留 role:"tool" 此处转 user 注记，协议合法
            window_budget = self._compute_window_budget(
                system_instructions, developer_instructions, tools_desc
            )
            window_msgs = await self._apply_window_budget(conversation_context, window_budget)
            # microcompact（Anthropic context editing 对齐，2026-09-10）：
            # 保留最近 3 个工具结果原文，更早的替换为占位指针（池归档无损、
            # 可凭 [历史回忆] 召回）。工具输出通常占窗口大头，先清它比折叠
            # 对话文本收益最大且不破坏轮次结构。
            try:
                window_msgs = self._clear_old_tool_results(window_msgs)
            except Exception as e:  # noqa: BLE001 - 清除失败不阻断
                logger.debug("工具结果占位清除跳过: %s", e)
            try:
                from neurova.context.recovery import repair_tool_turns

                window_msgs = repair_tool_turns(window_msgs)
            except Exception as e:  # noqa: BLE001 - 修复故障不阻断上下文构建
                logger.debug("tool-turn 修复跳过: %s", e)
            for msg in window_msgs:
                context.append({"role": msg.get("role", "user"), "content": msg["content"]})

            # 3. 本轮检索产物直接注入（不经抽屉门槛——它们由上游检索链按当前
            #    查询专门检索，是"本轮相关"的定义本身；同时已归档供未来召回）
            window_hashes = {
                ContextInput.compute_hash(ContextSource.CONVERSATION, msg["content"])
                for msg in window_msgs
            }
            injected_hashes = set(window_hashes)
            # 本轮刚折叠的消息当轮不召回（freshness 高分会立即命中，折叠白做）；
            # 下轮起窗口已滑走，恢复正常语义召回（连续性闭环）
            injected_hashes |= getattr(self, "_last_folded_hashes", set()) or set()
            for memory in relevant_memories or []:
                content = memory.get("content", str(memory)) if isinstance(memory, dict) else str(memory)
                injected_hashes.add(ContextInput.compute_hash(ContextSource.MEMORY, content))
                context.append({"role": "system", "content": f"[记忆] {content}"})
            for experience in experience_items or []:
                content = experience.get("content", str(experience)) if isinstance(experience, dict) else str(experience)
                injected_hashes.add(ContextInput.compute_hash(ContextSource.EXPERIENCE, content))
                context.append({"role": "system", "content": f"[经验] {content}"})
            for pattern in crystallized_patterns or []:
                content = pattern.get("content", str(pattern)) if isinstance(pattern, dict) else str(pattern)
                crystallized_content = f"[结晶经验] {content}"
                injected_hashes.add(ContextInput.compute_hash(ContextSource.EXPERIENCE, crystallized_content))
                context.append({"role": "system", "content": f"[经验] {crystallized_content}"})
            for log in reflection_logs:
                lesson = log.get("lesson", str(log))
                injected_hashes.add(ContextInput.compute_hash(ContextSource.REFLECTION, lesson))
                context.append({"role": "system", "content": f"[反思] {lesson}"})
            for question in self._collect_pending_questions():
                context.append({"role": "system", "content": f"[待探索问题] {question['content']}"})

            # 4. 跨轮语义调取块：从归档池按当前输入召回**历史**相关内容
            #    排除已注入条目（窗口 + 本轮产物），只召回往轮归档
            # 审验闭环（2026-09-10）：draw 侧预算与窗口剩余空间联动——
            # 否则窗口折叠省下的 token 会被 draw 召回加倍吃回（实测
            # prompt 65920：draw 29 条归档撑爆）。固定前缀不占 draw 预算
            # （drawer 是池归档的独立额度）。
            try:
                from neurova.context.window_compactor import estimate_window_tokens

                remaining = max(1000, window_budget - estimate_window_tokens(window_msgs))
                drawer = getattr(self.context_pool, "_drawer", None)
                if drawer is not None:
                    drawer.max_tokens = remaining
            except Exception as e:  # noqa: BLE001 - 预算联动失败不阻断召回
                logger.debug("draw 预算联动跳过: %s", e)
            drawn_contexts = self.context_pool.draw(need=user_input)
            logger.debug("ContextPool.draw() 调取 %s 条归档", len(drawn_contexts))
            for ctx in drawn_contexts:
                if ctx.hash and ctx.hash in injected_hashes:
                    continue  # 已在窗口或本轮产物中，跳过避免重复
                if ctx.source == ContextSource.CONVERSATION:
                    role_label = "助手" if (ctx.metadata or {}).get("role") == "assistant" else "用户"
                    context.append({"role": "system", "content": f"[历史回忆] {role_label}: {ctx.content}"})
                elif ctx.source == ContextSource.MEMORY:
                    context.append({"role": "system", "content": f"[记忆] {ctx.content}"})
                elif ctx.source == ContextSource.EXPERIENCE:
                    context.append({"role": "system", "content": f"[经验] {ctx.content}"})
                elif ctx.source == ContextSource.REFLECTION:
                    context.append({"role": "system", "content": f"[反思] {ctx.content}"})
                else:
                    # 兜底：其他归档来源保持 system 角色
                    context.append({"role": "system", "content": ctx.content})

            # P1-1④：记录本视图覆盖的池 chunk hash（模型请求成功后 ack 确认已读）
            self._last_view_hashes = {
                c.hash for c in drawn_contexts if getattr(c, "hash", None)
            }

            # 4. 本轮瞬态上下文（不入池归档，紧贴当前输入）
            # Bug C-3 修复：工具执行状态注入（仅当有实际工具结果时）
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
                    context.append({"role": "system", "content": "[工具记忆] " + " | ".join(tool_lines)})

            # 情感状态（本轮瞬态 + 长期倾向/回复基调）
            if agent_emotion:
                emotion_line = f"[情感] 用户情感: {agent_emotion.get('label', 'neutral')} (强度 {agent_emotion.get('intensity', 0.0):.2f})"
                if agent_emotion.get("long_term_dominant"):
                    emotion_line += f"；长期情感倾向: {agent_emotion['long_term_dominant']}"
                if agent_emotion.get("tone") and agent_emotion.get("tone") != "neutral":
                    emotion_line += f"；建议回复基调: {agent_emotion['tone']}"
                context.append({"role": "system", "content": emotion_line})

            # 语音上下文（每轮瞬态）
            if voice_context:
                try:
                    content_parts = []
                    if voice_context.get("text"):
                        content_parts.append(f"语音识别文本: {voice_context['text']}")
                    if voice_context.get("confidence", 0) > 0:
                        content_parts.append(f"识别置信度: {voice_context['confidence']:.2f}")
                    emotion = voice_context.get("emotion")
                    if emotion and emotion.get("primary_emotion") != "neutral":
                        content_parts.append(
                            f"语音情感: {emotion['primary_emotion']} " f"(置信度: {emotion.get('confidence', 0):.2f})"
                        )
                    if content_parts:
                        context.append({"role": "system", "content": "\n".join(content_parts)})
                except Exception as e:
                    logger.debug("语音上下文注入跳过: %s", e)

            # 5. 当前用户输入最后追加，确保是 LLM 看到的最后一条 user 消息
            # 审计②（批次 A 接入主链）：动态注入内容（记忆/经验/反思/情感已由
            # 上方 system 注入位承载）+ 分钟级时间以瞬态信封挂末条 user 消息——
            # 此前 pool 分支完全绕过 UnifiedContextInjector，信封化（F1 前缀
            # 缓存/免疫句）在默认配置下从未生效
            from neurova.context.envelope import build_envelope, build_time_block

            _env = build_envelope({"time": build_time_block()})
            context.append(
                {"role": "user", "content": f"{_env}\n\n{user_input}" if _env else user_input}
            )

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

        # 添加经验（D1 收敛：与结晶产物按内容键去重，结晶优先）
        for tag, content, prio in dedupe_experience_sources(experience_items, crystallized_patterns):
            candidate_pool.append(
                ContextInput(source=ContextSource.EXPERIENCE, content=f"{tag}{content}", priority=prio)
            )

        # 添加情感状态
        if agent_emotion:
            candidate_pool.append(
                ContextInput(
                    source=ContextSource.EMOTION,
                    content=f"用户情感: {agent_emotion.get('label', 'neutral')} (强度 {agent_emotion.get('intensity', 0.0):.2f})",
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
            # 审计⑬：SYSTEM_INSTRUCTION 已并入上面的 system 消息、USER_INPUT
            # 由末条信封消息承载——候选池里这两类原样重发会造成双份
            for item in candidate_pool:
                if getattr(item, "source", None) in (
                    ContextSource.SYSTEM_INSTRUCTION,
                    ContextSource.USER_INPUT,
                ):
                    continue
                content = getattr(item, "content", None)
                if content:
                    fallback.append({"role": "user", "content": str(content)})
            # 批次 A：降级路径与主路径同构——候选内容以瞬态信封挂末条 user
            # 消息（免疫句/缓存语义一致），不再散落为多条裸 user 消息
            from neurova.context.envelope import (
                build_envelope as _build_envelope,
                build_time_block as _build_time_block,
            )

            _memory_lines = [
                str(item.content)
                for item in candidate_pool
                if getattr(item, "content", None) and "MEMORY" in str(getattr(item, "source", ""))
            ]
            _env = _build_envelope(
                {"memories": "\n".join(_memory_lines), "time": _build_time_block()}
                if _memory_lines
                else {"time": _build_time_block()}
            )
            fallback.append({"role": "user", "content": f"{_env}\n\n{user_input}" if _env else user_input})
            return fallback

        context = self.context_builder.build_from_pool(
            candidate_pool,
            token_budget=TokenBudget(max_total=16000),
            conversation_history=None,
            user_input=user_input,
        )

        # Phase 4: 压缩上下文（如果需要）
        context = self.context_builder.compress_if_needed(context)

        # 审计⑦：发模型前最后一刻修复 tool 配对（injector 路径同样可能
        # 收到被剥离 tool_calls 的会话历史）
        try:
            from neurova.context.recovery import repair_tool_turns

            context = repair_tool_turns(context)
        except Exception as e:  # noqa: BLE001 - 修复故障不阻断上下文构建
            logger.debug("tool-turn 修复跳过: %s", e)

        return context

    def _archive_conversation_to_pool(self, conversation_context: List[Dict[str, Any]]) -> None:
        """P1-1① 写入侧归档：对话轮次打标 + tool 结果以 TOOL_CALL 源入池。

        - user 消息开新轮（assign_turn_ids → turn_N）
        - role=tool 的消息以 TOOL_CALL 源归档并写 pairs_with=当前轮——
          配对完整性校验（pool.draw 出口 validate_pairing）的锚点；
          视图选取产生的孤儿会在出口被剔除，池内归档不受影响
        """
        # 局部导入（与 build_context 同模式，避免模块级循环依赖）
        from neurova.context_pool import ContextInput, ContextSource

        archived_hashes: set = set()
        for msg, turn_id in assign_turn_ids(conversation_context):
            role = (msg or {}).get("role", "user")
            if role == "tool":
                content = msg.get("content", "")
                archived_hashes.add(ContextInput.compute_hash(ContextSource.TOOL_CALL, content))
                self.context_pool.add_context(
                    ContextInput(
                        source=ContextSource.TOOL_CALL,
                        content=content,
                        priority=60,
                        metadata={
                            "role": "tool",
                            "turn_id": turn_id,
                            "pairs_with": turn_id,
                            "tool_call_id": msg.get("tool_call_id"),
                        },
                    )
                )
            else:
                content = msg.get("content", "")
                archived_hashes.add(ContextInput.compute_hash(ContextSource.CONVERSATION, content))
                self.context_pool.add_context(
                    ContextInput(
                        source=ContextSource.CONVERSATION,
                        content=content,
                        priority=60,
                        metadata={"role": role, "turn_id": turn_id},
                    )
                )
        # 修2：暴露本轮归档的窗口 hash 集（窗口折叠发生在归档之后——零丢失判据）
        self._last_archived_window_hashes = archived_hashes

    # microcompact 保留窗口：最近 N 个工具结果保留原文，更早的占位替换
    _TOOL_RESULT_KEEP_RECENT = 3
    _TOOL_RESULT_PLACEHOLDER = "[工具输出已清除（原文已归档，可检索回忆）]"

    def _clear_old_tool_results(self, window_msgs: list) -> list:
        """microcompact（Anthropic context editing 对齐）：老工具结果占位清除。

        只在窗口 token 超过 8k 时启用（短对话不做无谓替换）；保留最近
        _TOOL_RESULT_KEEP_RECENT 个工具结果原文，更早的替换为占位指针。
        原文已由 _archive_conversation_to_pool 无损归档，召回不受影响。
        """
        from neurova.context.window_compactor import estimate_window_tokens

        if estimate_window_tokens(window_msgs) <= 8000:
            return window_msgs

        tool_positions = [
            i for i, m in enumerate(window_msgs) if (m or {}).get("role") == "tool"
        ]
        if len(tool_positions) <= self._TOOL_RESULT_KEEP_RECENT:
            return window_msgs

        cutoff = tool_positions[-self._TOOL_RESULT_KEEP_RECENT]
        cleared = list(window_msgs)
        for i in tool_positions:
            if i < cutoff:
                content = str(cleared[i].get("content", "") or "")
                if len(content) >= 80:  # 极短结果（如状态码）保留原文
                    cleared[i] = {**cleared[i], "content": self._TOOL_RESULT_PLACEHOLDER}
        return cleared

    # ══════════════════════════════════════════════════════════════
    # 修2（2026-09-09）：对话窗口 token 预算 + 自动压缩（zcode 式）
    # ══════════════════════════════════════════════════════════════

    def _resolve_window_token_budget(self) -> int:
        """窗口 token 预算：显式覆盖（_window_token_budget，测试/运维用）优先，
        否则模型元数据预算（get_token_budget_for_model）。

        窗口只是 prompt 的一部分（system 前缀/工具 schema/记忆注入共享），
        取池预算的 60% 作为窗口份额，钳位 [3000, 100000]。
        """
        override = getattr(self, "_window_token_budget", None)
        if override:
            return max(1000, int(override))
        try:
            from neurova.context_pool import ContextPool

            model_name = str(getattr(self.config, "llm_model", "") or "gpt-4")
            pool_budget = ContextPool.get_token_budget_for_model(model_name)
        except Exception:  # noqa: BLE001 - 预算查询失败不阻断
            pool_budget = 16000
        return max(3000, min(int(pool_budget * 0.6), 100000))

    def _compute_window_budget(
        self,
        system_instructions: list,
        developer_instructions: list,
        tools_desc: str,
    ) -> int:
        """预算再扣减：本轮固开头部（system 前缀/工具描述/记忆注入位）占多少，
        窗口份额同步收窄，防止「窗口按满额预算装配后总 prompt 仍超」。
        """
        from neurova.context.token_estimator import estimate_tokens

        try:
            # tools_desc 已含于 developer_instructions（build_context 装配处
            # append），不重复加算——双计会把窗口预算压得过小
            overhead = 0
            for instruction in list(system_instructions or []) + list(developer_instructions or []):
                overhead += estimate_tokens(str(instruction))
            return max(1000, self._resolve_window_token_budget() - overhead)
        except Exception:  # noqa: BLE001
            return self._resolve_window_token_budget()

    def _build_window_summarizer(self):
        """摘要桥（懒构建）：池已有 summarizer 时复用其 LLM 通道。"""
        if self._window_summarizer is not None:
            return self._window_summarizer

        async def _summarize(dropped_msgs, previous_summary=""):
            pool = self.context_pool
            summarizer = getattr(pool, "_summarizer", None) if pool else None
            if summarizer is None:
                return None
            from neurova.context_pool import ContextInput, ContextSource

            chunks = [
                ContextInput(
                    source=ContextSource.CONVERSATION,
                    content=(m or {}).get("content", ""),
                    priority=60,
                    metadata={"role": (m or {}).get("role", "user")},
                )
                for m in dropped_msgs or []
            ]
            return await summarizer.summarize(chunks, previous_summary=previous_summary)

        self._window_summarizer = _summarize
        return self._window_summarizer

    async def _apply_window_budget(
        self,
        conversation_context: list,
        budget_tokens: int,
    ) -> list:
        """窗口预算裁剪：未超预算原样返回；超预算折叠老消息为摘要行 + 尾部窗口。

        - 跨轮增量：已摘要覆盖的消息 hash 记入 _window_compaction_cache，
          后续折叠只对新落入折叠区的消息做增量摘要（previous_summary 传递）。
        - 归档先行：本方法在 _archive_conversation_to_pool 之后调用，
          折叠只影响视图，原文零丢失。
        """
        from neurova.context.window_compactor import compact_window, estimate_window_tokens

        msgs = [
            {"role": (m or {}).get("role", "user"), "content": (m or {}).get("content", "")}
            for m in (conversation_context or [])
            if isinstance(m, dict) and (m or {}).get("content")
        ]
        if not msgs or estimate_window_tokens(msgs) <= budget_tokens:
            return [
                {"role": (m or {}).get("role", "user"), "content": (m or {}).get("content", "")}
                for m in (conversation_context or [])
                if isinstance(m, dict) and (m or {}).get("content")
            ]

        cache = self._window_compaction_cache.setdefault(
            self.session_id or "_", {"summary": "", "covered": set()}
        )
        # 增量防抖：距上次成功摘要新追加的消息数 ≤ 阈值时复用缓存摘要
        # （省一轮摘要 LLM——实测摘要链路 30s+，每轮重调不可接受）。
        # 未覆盖的消息仍归档在池中，零丢失。
        last_count = cache.get("last_count", 0)
        delta_msgs = (len(msgs) - last_count) if last_count else len(msgs)
        reuse_summary = bool(cache.get("summary")) and delta_msgs <= self._DELTA_RESUMMARY_MSGS
        summarize = None if reuse_summary else self._build_window_summarizer()

        compaction = await compact_window(
            msgs,
            budget_tokens,
            summarize=summarize,
            previous_summary=cache.get("summary", ""),
        )
        if compaction is None:
            self._last_folded_hashes = set()
            return msgs

        # 本轮被折叠消息 hash 集（build_context 据此当轮防召回——刚折叠即召回
        # 会让折叠白做；下轮起窗口滑走、恢复正常语义召回）
        kept_contents = {m.get("content", "") for m in compaction.window}
        from neurova.context_pool import ContextInput as _CI, ContextSource as _CS

        self._last_folded_hashes = {
            _CI.compute_hash(_CS.CONVERSATION, m.get("content", ""))
            for m in msgs
            if m.get("content", "") not in kept_contents
        }

        # 更新跨轮缓存（摘要失败时保留旧摘要，下次重试增量）
        if compaction.summary:
            cache["summary"] = compaction.summary
            cache["last_count"] = len(msgs)
            from neurova.context_pool import ContextInput, ContextSource

            # 标记本轮仍被折叠的消息为已覆盖（凡未出现在新窗口的）
            kept_set = {m["content"] for m in compaction.window}
            for m in msgs:
                if m["content"] not in kept_set:
                    cache["covered"].add(
                        ContextInput.compute_hash(ContextSource.CONVERSATION, m["content"])
                    )

        window = compaction.window
        if compaction.compacted_count > 0 and not compaction.summary:
            # 摘要器缺失/失败：注入静态折叠桩（或沿用既有摘要），不静默丢上下文
            existing = cache.get("summary", "")
            stub = (
                f"[早期对话摘要] {existing}"
                if existing
                else (
                    f"[早期对话摘要] （早期 {compaction.compacted_count} 条消息已折叠以控制上下文预算；"
                    "如需细节请让我检索历史记忆。）"
                )
            )
            window = [{"role": "system", "content": stub}] + window

        logger.info(
            "[WINDOW_COMPACT] 窗口超预算折叠: %d msgs → %d（折叠 %d 条, token %d → %d, LLM摘要=%s）",
            len(msgs),
            len(window),
            compaction.compacted_count,
            compaction.tokens_before,
            compaction.tokens_after,
            bool(compaction.summary),
        )
        return window

    async def manual_compact(self, conversation_history: list) -> dict:
        """/compact 手动压缩：无视预算水位强制折叠当前会话窗口。

        与 _apply_window_budget 共用折叠/摘要桥和跨轮缓存——手动压缩
        生成的摘要直接进 _window_compaction_cache，后续轮次超预算折叠
        时携带同一摘要（zcode 语义：压缩后窗口立即变小且不重复摘要）。

        Returns:
            {compacted, folded, kept, tokens_before, tokens_after,
             summary_generated, reason?}
        """
        from neurova.context.window_compactor import compact_window, estimate_window_tokens

        msgs = [
            {"role": (m or {}).get("role", "user"), "content": (m or {}).get("content", "")}
            for m in (conversation_history or [])
            if isinstance(m, dict) and (m or {}).get("content")
        ]
        if not msgs:
            return {"compacted": False, "reason": "empty_history", "folded": 0, "kept": 0,
                    "tokens_before": 0, "tokens_after": 0, "summary_generated": False}

        tokens_before = estimate_window_tokens(msgs)
        # 强制折叠：预算取窗口默认份额的一半（手动压缩意图明确=尽快瘦身）。
        # 与 auto 路径同源（_resolve_window_token_budget → _window_token_budget
        # 覆盖生效），保证测试/运维显式预算下两路结论一致
        budget = max(1500, self._resolve_window_token_budget() // 2)
        cache = self._window_compaction_cache.setdefault(
            self.session_id or "_", {"summary": "", "covered": set()}
        )

        compaction = await compact_window(
            msgs,
            budget,
            summarize=self._build_window_summarizer(),
            previous_summary=cache.get("summary", ""),
        )
        logger.info(
            "[WINDOW_COMPACT] /compact 决策: msgs=%d estimate=%d budget=%d resolved=%d -> compacted=%s",
            len(msgs), tokens_before, budget, self._resolve_window_token_budget(),
            bool(compaction),
        )
        if compaction is None:
            return {"compacted": False, "reason": "under_budget", "folded": 0, "kept": len(msgs),
                    "tokens_before": tokens_before, "tokens_after": tokens_before,
                    "summary_generated": False}

        if compaction.summary:
            cache["summary"] = compaction.summary
            cache["last_count"] = len(msgs)
            from neurova.context_pool import ContextInput, ContextSource

            kept_set = {m["content"] for m in compaction.window}
            for m in msgs:
                if m["content"] not in kept_set:
                    cache["covered"].add(
                        ContextInput.compute_hash(ContextSource.CONVERSATION, m["content"])
                    )
        elif cache.get("summary"):
            # 无新摘要但旧摘要存在：保留（后续轮次仍携带）
            pass

        logger.info(
            "[WINDOW_COMPACT] /compact 手动压缩: 折叠 %d 条, token %d → %d, LLM摘要=%s",
            compaction.compacted_count, compaction.tokens_before,
            compaction.tokens_after, bool(compaction.summary),
        )
        return {
            "compacted": True,
            "folded": compaction.compacted_count,
            "kept": len(compaction.window),
            "tokens_before": compaction.tokens_before,
            "tokens_after": compaction.tokens_after,
            "summary_generated": bool(compaction.summary),
        }

    # ══════════════════════════════════════════════════════════════
    # 系统提示构建
    # ══════════════════════════════════════════════════════════════

    def mark_last_view_seen(self) -> int:
        """P1-1④ ack 集：确认最近一次视图内的池 chunk 已被模型成功读过。

        由 chat_pipeline 在 LLM 请求成功后调用；pool 侧据此做分层剪枝
        （未读 TOOL_CALL 优先入视图，已读的作为折叠候选）。
        """
        try:
            pool = getattr(self, "context_pool", None)
            if pool is None or not self._last_view_hashes:
                return 0
            return pool.mark_hashes_seen(self._last_view_hashes)
        except Exception:
            logger.debug("视图已读确认失败（忽略）", exc_info=True)
            return 0

    def get_ledger_db(self):
        """P1-1③：暴露驱逐台账持久层（GC 定时任务/诊断用）；未启用返回 None。"""
        pool = getattr(self, "context_pool", None)
        return getattr(pool, "_ledger_db", None) if pool else None

    def build_system_prompt(self, tools_desc: str = "") -> str:
        """构建系统提示（Phase 6.5: 统一行为规则配置）。

        使用配置的行为规则，确保 build_system_prompt() 和 chat() 中的
        developer_instructions 保持一致。

        Bug T-1 修复:在 prompt 末尾注入当前时间上下文,避免 LLM 误用训练截止日期。
        批次 C：与 build_context 主链同步追加恒定规则段（双路径一致）。
        """
        parts = [self.soul]

        if self.personality:
            parts.append("\n\n## 性格特征\n" + self.personality)

        # 添加宪法/行为准则
        if self.config.constitution:
            parts.append("\n\n## 行为准则（宪法）\n" + self.config.constitution)

        from neurova.context.rules_sections import build_all_sections

        parts.append(
            "\n\n"
            + build_all_sections(workspace_path=str(getattr(self.config, "workspace_path", "") or ""))
        )

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
            时区:Asia/Shanghai (UTC+08:00)
            季节:秋;临近节日:国庆节(20天内)   ← 时间感知 hint，可缺省

        说明:
        - 日期用中文格式(YYYY年MM月DD日)+ 星期,便于 LLM 回答"今天星期几"。
        - [缓存稳定] 只保留日期精度,不再注入 时:分:秒——本段位于 system 固定
          前缀中,秒级时刻会使上下文前缀每秒变化,LLM prompt 缓存命中率归零。
          日期精度在一天之内保持前缀字节级稳定,且足以纠正训练截止日期误用。
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

        # 时间感知 hint（季节/临近节日）：日级粒度，随日期字节稳定，可安全
        # 进入 system 固定前缀；经 envelope 单源取用，异常/为空不渲染该行。
        try:
            from neurova.context.envelope import build_system_time_hint

            time_hint = str(build_system_time_hint() or "")
        except Exception:  # noqa: BLE001 - hint 缺失不阻断时间段
            time_hint = ""
        hint_line = f"{time_hint}\n" if time_hint else ""

        return (
            f"\n\n## 当前时间\n"
            f"当前日期:{date_str} {weekday_zh}\n"
            f"时区:{tz_name} (UTC{tz_offset_str})\n"
            f"{hint_line}"
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
        """获取工具描述文本，注入 system prompt。

        A1 单源化（工具面审计）：渲染消费 build_tools_for_llm 的同一份已筛选
        清单（生命周期过滤+可见性门控后的结果），条目数与 tools 参数严格一致。
        A4 预算：清单渲染走 render_tools_description（18000 字符预算降级）。

        注意：这里只列工具清单与使用策略，**不教任何调用语法**——
        原生 function calling 由 tools 参数承载；文本格式教学收敛在
        get_tool_call_format_hint()，仅供 provider 不支持原生 FC 的降级路径。
        （历史上无条件教 `[TOOL_CALL:]` 文本格式与原生 tools 双通道冲突，
        是弱模型不调用工具的首要根因）
        """
        try:
            tools = await self.build_tools_for_llm()
            if not tools:
                return ""
            return render_tools_description(tools)
        except Exception as e:
            logger.warning("构建工具描述失败: %s", e)
            return ""

    async def _apply_visibility_gate(self, tools: Optional[List[Dict]]) -> Optional[List[Dict]]:
        """A2 可见性门控（env 门控，默认关）：DEGRADED 工具从 LLM 工具面隐藏。

        与 _apply_tool_lifecycle（排序+archived/frozen 过滤）串联：
        build_tools_for_llm → _apply_tool_lifecycle → _apply_visibility_gate。
        默认零行为变化；NEUROVA_HIDE_DEGRADED_TOOLS=1 时隐藏（不删除——
        生命周期状态可恢复，恢复后自动重新可见）。
        """
        import os

        if not tools or os.environ.get("NEUROVA_HIDE_DEGRADED_TOOLS") != "1":
            return tools
        try:
            evolution = getattr(self._agent, "evolution", None)
            lifecycle = getattr(evolution, "tool_lifecycle", None)
            get_state = getattr(lifecycle, "get_state", None)
            if not callable(get_state):
                return tools
            kept = []
            for t in tools:
                name = t.get("function", {}).get("name", "")
                try:
                    state = get_state(name)
                    state_value = getattr(state, "value", None) or str(state or "")
                except Exception:
                    state_value = "active"
                if state_value == "degraded":
                    continue
                kept.append(t)
            if len(kept) != len(tools):
                logger.info("可见性门控: 隐藏 %s 个 DEGRADED 工具", len(tools) - len(kept))
            return kept if kept else tools
        except Exception as e:
            logger.debug("可见性门控跳过: %s", e)
            return tools

    async def build_tools_for_llm(self) -> Optional[List[Dict]]:
        """聚合所有工具为 OpenAI function call schema（内置 + Skill + MCP + 插件）。

        实例方法：委托给底层 `_build_tools_for_llm` 实现，保持 `self` 注入，
        使 agent_core / chat_pipeline / context_facade 等调用方通过实例正常访问。
        管道顺序：聚合 → 生命周期过滤/排序 → 可见性门控（A2）→ Tool Search 压缩（A6）。
        """
        tools = self._apply_tool_lifecycle(await _build_tools_for_llm(self))
        tools = await self._apply_visibility_gate(tools)
        return self._apply_tool_search_compaction(tools)

    def _apply_tool_search_compaction(self, tools):
        """A6 Tool Search（P2）：env 门控 + 规模阈值触发目录压缩。

        NEUROVA_TOOL_SEARCH=1 且（隐藏候选数 >= NEUROVA_TOOL_SEARCH_MIN_CATALOG，
        默认 40）时激活：直连工具（NEUROVA_TOOL_SEARCH_DIRECT 逗号清单，含默认
        核心集）+ 三个控制工具保持模型可见，其余参数 schema 移出 prompt；能力
        目录（name+description，18000 字符预算）注入清单尾部供 tool_search 检索。
        """
        import os as _os

        if not tools or _os.environ.get("NEUROVA_TOOL_SEARCH") != "1":
            return tools
        try:
            from neurova.context.tool_search import (
                apply_tool_search_compaction as _compact,
                render_directory,
            )

            direct = [
                n.strip()
                for n in _os.environ.get(
                    "NEUROVA_TOOL_SEARCH_DIRECT",
                    "memory_search,voice_memory_search,web_search,file_read,file_write,"
                    "file_edit,computer_shell,run_code,spawn_subagent,planning",
                ).split(",")
                if n.strip()
            ]
            try:
                min_catalog = int(_os.environ.get("NEUROVA_TOOL_SEARCH_MIN_CATALOG", "40"))
            except ValueError:
                min_catalog = 40

            hidden_candidates = [
                t["function"]["name"]
                for t in tools
                if t.get("function", {}).get("name") not in set(direct)
                and t.get("function", {}).get("name") not in ("tool_search", "tool_describe", "tool_call")
            ]
            compacted = _compact(tools, direct, min_catalog=min_catalog)
            if compacted is None:
                return tools

            from neurova.context.tool_search import build_catalog, get_active_catalog, get_directory_budget

            catalog_entries = [e for e in get_active_catalog()]
            directory = render_directory(catalog_entries, max_chars=get_directory_budget())
            _nl = chr(10)
            directory_block = (
                _nl + _nl + "## 隐藏工具目录（schema 未加载）" + _nl
                + "以下工具可用 tool_search 检索、tool_describe 取参数 schema、tool_call 调用："
                + _nl + directory + _nl
            )
            # 目录以一个伪 schema 条目挂进 tools 参数（description 承载目录文本，
            # 不产生可执行入口——真调用走 tool_call）
            compacted.append(
                {
                    "type": "function",
                    "function": {
                        "name": "tool_search_directory",
                        "description": f"Hidden tool catalog. {directory_block}",
                        "parameters": {"type": "object", "properties": {}, "required": []},
                    },
                }
            )
            return compacted
        except Exception as e:
            logger.warning("Tool Search 压缩跳过: %s", e)
            return tools


def dedupe_experience_sources(experiences, crystallized_patterns):
    """D1 经验注入收敛：普通经验与结晶产物按内容键去重（结晶优先保留）。

    此前两条注入管线（EKB 经验 / PatternCrystallizer 产物）互不感知，
    同一条经验会以 70/80 两个优先级重复进池。key = 内容去空白前 100 字符。
    Returns: List[(tag, content, priority)]
    """
    import re as _re

    def _key(c: str) -> str:
        return _re.sub(r"[\s]+", "", str(c))[:100]

    seen = set()
    out = []
    # 结晶产物先入（同内容时按优先级保留结晶副本）
    pairs = [(("[结晶经验] ", p, 80)) for p in (crystallized_patterns or [])] + [
        (("", e, 70)) for e in (experiences or [])
    ]
    for tag, item, prio in pairs:
        content = item.get("content", str(item)) if isinstance(item, dict) else str(item)
        k = _key(content)
        if k in seen:
            continue
        seen.add(k)
        out.append((tag, content, prio))
    return out


def get_tool_call_format_hint() -> str:
    """文本模式专用的调用格式教学（provider 不支持原生 function calling 时的降级通道）。

    只允许出现在降级后的请求里；原生 FC 请求注入本提示会与 tools 参数
    形成双通道指令冲突，诱导模型放弃 tool_calls 机制。
    """
    return (
        "\n\n## 工具调用方式\n"
        "当前接口不支持函数调用，请用文本格式发起工具调用：\n"
        "`[TOOL_CALL:工具名(参数=值, ...)]`\n"
        "示例：`[TOOL_CALL:web_search(query=\"今日新闻\")]`\n"
    )


def render_tools_description(tools: List[Dict], max_chars: Optional[int] = None) -> str:
    """渲染工具清单 markdown（A4 预算降级，模块级纯函数便于测试）。

    预算默认 18000 字符（env NEUROVA_TOOL_PROMPT_BUDGET_CHARS 可覆盖），
    对齐 OC directory 模式量级。超预算降级序：
    1. 丢参数段（保留 name+完整 description）
    2. 截断 description（400→160→80 字符）
    3. 极限预算仍保留全部工具名条目（不删条目，防工具"消失"）
    """
    import os as _os

    if max_chars is None:
        try:
            max_chars = int(_os.environ.get("NEUROVA_TOOL_PROMPT_BUDGET_CHARS", "18000"))
        except ValueError:
            max_chars = 18000

    header = (
        "\n\n## 可用工具\n"
        "⚠️ **工具使用策略**：\n"
        "- 你具备真实工具能力。需要实时信息、文件读写、屏幕/浏览器操作等能力时，"
        "必须主动调用对应工具完成，不要回复\"我做不到/无法获取\"\n"
        "- 调用前确认参数完整；调用失败时阅读错误信息，修正参数重试或改用其他工具\n"
        "- 简单闲聊无需调用工具\n"
        "- `memory_search` 和 `voice_memory_search` 仅检索本 Agent 自身的历史记忆，"
        "不能搜互联网；实时信息请用 `weather` / `web_search`\n"
        "- `computer_shell` 可执行本地命令，注意安全性和权限\n"
    )

    def _line(t, with_params=True, desc_limit=None):
        fn = t["function"]
        desc = fn.get("description", "") or ""
        if desc_limit is not None and len(desc) > desc_limit:
            desc = desc[:desc_limit] + "…"
        params_desc = ""
        if with_params:
            params = fn.get("parameters", {}).get("properties", {})
            required = fn.get("parameters", {}).get("required", [])
            if params:
                param_list = [f"{k}{'(必填)' if k in required else ''}" for k in params]
                params_desc = f" — 参数: {', '.join(param_list)}"
        return f"- **{fn['name']}**: {desc}{params_desc}"

    def _join(lines):
        return "\n".join([header] + lines)

    # A6 闭环审计修复：目录伪条目只在 tools 参数承载（description 即目录文本），
    # markdown 渲染跳过——否则目录双份注入，且预算截断会毁掉目录显示
    budget_tools = [t for t in tools if t.get("function", {}).get("name") != "tool_search_directory"]
    if not budget_tools:
        budget_tools = tools

    lines = [_line(t) for t in budget_tools]
    if len(_join(lines)) <= max_chars:
        return _join(lines)

    # 降级 1：丢参数段
    lines = [_line(t, with_params=False) for t in budget_tools]
    if len(_join(lines)) <= max_chars:
        return _join(lines)

    # 降级 2：截断 description
    for limit in (400, 160, 80, 40):
        lines = [_line(t, with_params=False, desc_limit=limit) for t in budget_tools]
        if len(_join(lines)) <= max_chars:
            return _join(lines)

    # 极限：硬截断整体，保证所有工具名可见（附截断说明）
    text = _join(lines)
    if len(text) > max_chars:
        text = text[:max_chars] + f"\n\n⚠️ 工具清单过长已截断（{len(tools)} 个工具，预算 {max_chars} 字符）"
    return text


async def _build_tools_for_llm(self) -> Optional[List[Dict]]:
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
                # tool_router 可能返回三种形态：已序列化的 OpenAI schema dict、
                # 普通 dict 工具、或带 to_openai_format 的对象，需兼容处理。
                if isinstance(t, dict) and isinstance(t.get("function"), dict) and t["function"].get("name"):
                    # 已是 OpenAI function call schema，直接采用（避免二次包装/误覆盖）
                    tools.append(t)
                    continue
                if isinstance(t, dict):
                    tool_name = t.get("name", "") or ""
                    tool_desc = t.get("description", "") or f"工具: {tool_name}"
                    builtin_params = get_builtin_tool_params(tool_name)
                elif hasattr(t, "to_openai_format"):
                    tools.append(t.to_openai_format())
                    continue
                else:
                    tool_name = getattr(t, "name", "") or ""
                    tool_desc = getattr(t, "description", "") or f"工具: {tool_name}"
                    builtin_params = get_builtin_tool_params(tool_name)
                builtin_params = builtin_params or {}
                tools.append(
                    {
                        "type": "function",
                        "function": {
                            "name": tool_name,
                            "description": tool_desc or builtin_params.get("description", f"工具: {tool_name}"),
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
                # B2（工具面审计）：config.model_invocable=False 的技能不进模型工具面
                # （人肉/API 仍可调用——SkillRegistry 与执行路径不受影响）
                if isinstance(getattr(skill, "config", None), dict) and skill.config.get("model_invocable") is False:
                    continue
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
                # 同名合并以"参数定义更完整者"为准：
                # 历史上无条件用技能 schema 覆盖，导致 web_search 等内置工具
                # 的完整参数被空参 proxy 抹掉（模型看不到怎么传参）
                existing_idx = next((i for i, t in enumerate(tools) if t["function"]["name"] == skill_name), -1)
                if existing_idx >= 0:
                    existing = tools[existing_idx]
                    new_props = (schema.get("function", {}).get("parameters", {}) or {}).get("properties", {}) or {}
                    old_props = (existing.get("function", {}).get("parameters", {}) or {}).get("properties", {}) or {}
                    tools[existing_idx] = schema if len(new_props) > len(old_props) else existing
                else:
                    tools.append(schema)
        except Exception:
            logger.exception("从 SkillRegistry 获取工具失败")

    # 3.5 workflow_as_tool（P1-3）：已发布工作流注册为 agent 工具
    # （DAG start 节点 fields 天然自带输入校验；失败静默跳过——可选增强）
    try:
        from neurova.api.endpoints.neurflow_api import _get_storage
        from neurova.collaboration.neurflow.workflow_as_tool import list_published_workflows_as_tools

        wf_tools = list_published_workflows_as_tools(_get_storage())
        existing_names = {t["function"]["name"] for t in tools}
        for wt in wf_tools:
            if wt["name"] not in existing_names:
                tools.append({
                    "type": "function",
                    "function": {
                        "name": wt["name"],
                        "description": wt["description"],
                        "parameters": wt["parameters"],
                    },
                })
    except Exception as e:
        logger.debug("workflow_as_tool 工具注入失败（跳过）: %s", e)

    # 过滤掉格式不正确的工具（某些 provider 要求 tools 中每个元素都必须有 function 字段）
    valid_tools = []
    for t in tools:
        if isinstance(t, dict) and "function" in t and isinstance(t["function"], dict) and "name" in t["function"]:
            valid_tools.append(t)
        else:
            logger.warning("跳过格式不正确的工具: %s", t)
    tools = valid_tools

    # Schema 消毒：provider（尤其国产 OpenAI 兼容端）对 parameters 校验严格，
    # 缺 type/properties 常触发 400 → 触发降级路径整轮丢失工具
    for t in tools:
        params = t["function"].setdefault("parameters", {})
        if not isinstance(params, dict):
            params = {}
            t["function"]["parameters"] = params
        params.setdefault("type", "object")
        props = params.setdefault("properties", {})
        if not isinstance(props, dict):
            params["properties"] = {}

    if tools:
        logger.info("🔧 为 LLM 提供 %s 个工具: %s", len(tools), [t['function']['name'] for t in tools])
    return tools if tools else None
