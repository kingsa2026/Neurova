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

import logging
from typing import List, Dict, Optional, Any

from .models import TokenBudget
from .builder import ContextBuilder
from .injector import UnifiedContextInjector

logger = logging.getLogger(__name__)

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
            model_name = getattr(agent_ref.config, 'llm_model', 'gpt-4')
            max_tokens = ContextPool.get_token_budget_for_model(model_name)
            
            self.context_pool = ContextPool(
                user_id=getattr(agent_ref, 'user_id', 'default'),
                agent_id=getattr(agent_ref, 'agent_id', 'default'),
                max_tokens=max_tokens,
                auto_tag=auto_tag
            )
            logger.info(f"ContextPool 初始化完成，模型: {model_name}，Token 预算: {max_tokens}")
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
        return self._agent._skill_registry

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
        return getattr(self._agent, 'growth_log_manager', None)

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
                question_queue_manager=getattr(self._agent, 'question_queue_manager', None),
                token_budget=TokenBudget(max_total=16000),
                enable_cache=True,
                enable_compression=True,
            )
            logger.info(f"Agent {self.config.name}: UnifiedContextInjector 已启用 (16K tokens)")

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

        Returns:
            上下文消息列表，可直接传给 LLM
        """
        from neurova.context_pool import ContextInput, ContextCollector, ContextSource
        from datetime import datetime

        # Phase 2: 构建系统提示
        tools_desc = await self.get_tools_description()
        system_instructions = [self.soul]
        if self.personality:
            system_instructions.append(self.personality)
        if self.config.constitution:
            system_instructions.append(self.config.constitution)

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
            if agent_emotion and agent_emotion.get('label') != 'neutral':
                logger.debug(f"用户情感分析: {agent_emotion.get('label')} (强度: {agent_emotion.get('intensity', 0):.2f})")
        except Exception as e:
            logger.debug(f"情感分析跳过: {e}")

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
                logger.debug(f"反思日志获取跳过: {e}")

        # Phase 3: 构建 ContextInput → ContextCollector → 候选池
        # 合并 conversation_history + session_context（B3修复）
        conversation_context = list(
            {"role": m["role"], "content": m["content"]}
            for m in (self.conversation_history or [])
        )
        if session_context:
            # session_context 添加到历史末尾（更新近的对话）
            conversation_context.extend(session_context)

        # 构建工具记忆上下文（包含执行状态）
        tool_memory_context = dict(tool_memory_result) if tool_memory_result else {}
        if auto_execute_result:
            tool_memory_context["auto_execute_result"] = auto_execute_result
        tool_memory_context["tool_decision"] = tool_decision

        # 如果启用 ContextPool，将上下文添加到 ContextPool
        if self.use_pool and self.context_pool:
            # 添加系统指令
            for instruction in system_instructions:
                self.context_pool.add_context(ContextInput(
                    source=ContextSource.SYSTEM_INSTRUCTION,
                    content=instruction,
                    priority=100
                ))
            
            # 添加开发者指令
            for instruction in developer_instructions:
                self.context_pool.add_context(ContextInput(
                    source=ContextSource.DEVELOPER_INSTRUCTION,
                    content=instruction,
                    priority=90
                ))
            
            # 添加用户输入
            self.context_pool.add_context(ContextInput(
                source=ContextSource.USER_INPUT,
                content=user_input,
                priority=90
            ))
            
            # 添加对话历史
            for msg in conversation_context:
                self.context_pool.add_context(ContextInput(
                    source=ContextSource.CONVERSATION,
                    content=msg["content"],
                    priority=60
                ))
            
            # 添加记忆
            for memory in relevant_memories or []:
                if isinstance(memory, dict):
                    content = memory.get("content", str(memory))
                else:
                    content = str(memory)
                self.context_pool.add_context(ContextInput(
                    source=ContextSource.MEMORY,
                    content=content,
                    priority=70
                ))
            
            # 添加经验
            for experience in experience_items or []:
                if isinstance(experience, dict):
                    content = experience.get("content", str(experience))
                else:
                    content = str(experience)
                self.context_pool.add_context(ContextInput(
                    source=ContextSource.EXPERIENCE,
                    content=content,
                    priority=70
                ))
            
            # 添加结晶经验（认知图谱 PatternCrystallizer 产物）
            for pattern in crystallized_patterns or []:
                if isinstance(pattern, dict):
                    content = pattern.get("content", str(pattern))
                else:
                    content = str(pattern)
                self.context_pool.add_context(ContextInput(
                    source=ContextSource.EXPERIENCE,
                    content=f"[结晶经验] {content}",
                    priority=80,  # 结晶经验优先级高于普通经验
                ))
            
            # 添加情感状态
            if agent_emotion:
                self.context_pool.add_context(ContextInput(
                    source=ContextSource.EMOTION,
                    content=f"用户情感: {agent_emotion.get('label', 'neutral')}",
                    priority=50
                ))
            
            # 添加反思日志
            for log in reflection_logs:
                self.context_pool.add_context(ContextInput(
                    source=ContextSource.REFLECTION,
                    content=log.get("lesson", str(log)),
                    priority=60
                ))
            
            # 使用 ContextPool.draw() 获取相关上下文
            drawn_contexts = self.context_pool.draw(need=user_input)
            logger.debug(f"ContextPool.draw() 完成，共 {len(drawn_contexts)} 个上下文")
            
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
                    context.append({"role": "user", "content": ctx.content})
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
            candidate_pool.append(ContextInput(
                source=ContextSource.SYSTEM_INSTRUCTION,
                content=instruction,
                priority=100
            ))
        
        # 添加开发者指令
        for instruction in developer_instructions:
            candidate_pool.append(ContextInput(
                source=ContextSource.DEVELOPER_INSTRUCTION,
                content=instruction,
                priority=90
            ))
        
        # 添加用户输入
        candidate_pool.append(ContextInput(
            source=ContextSource.USER_INPUT,
            content=user_input,
            priority=90
        ))
        
        # 添加对话历史
        for msg in conversation_context:
            candidate_pool.append(ContextInput(
                source=ContextSource.CONVERSATION,
                content=msg["content"],
                priority=60
            ))
        
        # 添加记忆
        for memory in relevant_memories or []:
            if isinstance(memory, dict):
                content = memory.get("content", str(memory))
                metadata = {k: v for k, v in memory.items() if k != "content"}
            else:
                content = str(memory)
                metadata = {}
            candidate_pool.append(ContextInput(
                source=ContextSource.MEMORY,
                content=content,
                priority=70,
                metadata=metadata
            ))
        
        # 添加经验
        for experience in experience_items or []:
            if isinstance(experience, dict):
                content = experience.get("content", str(experience))
            else:
                content = str(experience)
            candidate_pool.append(ContextInput(
                source=ContextSource.EXPERIENCE,
                content=content,
                priority=70
            ))
        
        # 添加结晶经验（认知图谱 PatternCrystallizer 产物）
        for pattern in crystallized_patterns or []:
            if isinstance(pattern, dict):
                content = pattern.get("content", str(pattern))
            else:
                content = str(pattern)
            candidate_pool.append(ContextInput(
                source=ContextSource.EXPERIENCE,
                content=f"[结晶经验] {content}",
                priority=80,  # 结晶经验优先级高于普通经验
            ))
        
        # 添加情感状态
        if agent_emotion:
            candidate_pool.append(ContextInput(
                source=ContextSource.EMOTION,
                content=f"用户情感: {agent_emotion.get('label', 'neutral')}",
                priority=50,
                metadata=agent_emotion
            ))
        
        # 添加反思日志
        for log in reflection_logs:
            candidate_pool.append(ContextInput(
                source=ContextSource.REFLECTION,
                content=log.get("lesson", str(log)),
                priority=60,
                metadata=log
            ))
        
        logger.debug(f"候选池构建完成，共 {len(candidate_pool)} 个候选项")

        # Phase 3.5: 从候选池构建上下文
        context = self.context_builder.build_from_pool(
            candidate_pool,
            token_budget=TokenBudget(max_total=16000),
            conversation_history=self.conversation_history,
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

        return "\n".join(parts)

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
            for t in tools:
                fn = t['function']
                params_desc = ""
                params = fn.get('parameters', {}).get('properties', {})
                required = fn.get('parameters', {}).get('required', [])
                if params:
                    param_list = [f"{k}{'(必填)' if k in required else ''}" for k in params]
                    params_desc = f" — 参数: {', '.join(param_list)}"
                lines.append(f"- **{fn['name']}**: {fn['description']}{params_desc}")
            return "\n".join(lines)
        except Exception as e:
            logger.warning(f"构建工具描述失败: {e}")
            return ""

    async def build_tools_for_llm(self) -> Optional[List[Dict]]:
        """聚合所有工具为 OpenAI function call schema（内置 + Skill + MCP + 插件）"""
        from neurova.builtin_tools import get_builtin_tool_params

        tools = []
        user_id = getattr(self.config, 'user_id', 'default')
        logger.info(f"[TOOLS] 开始聚合工具, user_id={user_id}, has_tool_router={self.tool_router is not None}, has_skill_registry={self.skill_registry is not None}")

        # 1. ToolRouter 聚合所有工具（含 MCP）
        if self.tool_router:
            try:
                all_tools = await self.tool_router.get_all_tools(
                    agent_id=self.config.agent_id,
                    user_id=user_id,
                )
                logger.info(f"[TOOLS] ToolRouter 返回 {len(all_tools)} 个工具: {[t.name for t in all_tools]}")
                for t in all_tools:
                    if hasattr(t, 'to_openai_format'):
                        tools.append(t.to_openai_format())
                    else:
                        # 为内置工具生成参数 schema
                        builtin_params = get_builtin_tool_params(t.name)
                        tools.append({
                            "type": "function",
                            "function": {
                                "name": t.name,
                                "description": t.description or builtin_params.get("description", f"工具: {t.name}"),
                                "parameters": builtin_params.get("parameters", {"type": "object", "properties": {}, "required": []})
                            }
                        })
            except Exception as e:
                logger.warning(f"从 ToolRouter 获取工具列表失败: {e}")

        # 2. Skill Registry 工具 — 用实际参数 schema 替换 ToolRouter 的占位符
        if self.skill_registry:
            try:
                for skill_name, skill in self.skill_registry.skills.items():
                    # 尝试用 OpenAI Schema Adapter 生成带参数的 schema
                    try:
                        from neurova.skill_system.compat import OpenAISchemaAdapter
                        schema = OpenAISchemaAdapter.skill_to_tool_schema(skill)
                    except ImportError:
                        # Fallback：用 _get_parameters() 构建
                        params_info = skill._get_parameters() if hasattr(skill, '_get_parameters') else {}
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
                                "parameters": {"type": "object", "properties": props, "required": required}
                            }
                        }
                    # 替换 ToolRouter 生成的同名工具（参数更完整）
                    existing_idx = next((i for i, t in enumerate(tools) if t['function']['name'] == skill_name), -1)
                    if existing_idx >= 0:
                        tools[existing_idx] = schema
                    else:
                        tools.append(schema)
            except Exception as e:
                logger.warning(f"从 SkillRegistry 获取工具失败: {e}")

        # 过滤掉格式不正确的工具（某些 provider 要求 tools 中每个元素都必须有 function 字段）
        valid_tools = []
        for t in tools:
            if isinstance(t, dict) and "function" in t and isinstance(t["function"], dict) and "name" in t["function"]:
                valid_tools.append(t)
            else:
                logger.warning(f"跳过格式不正确的工具: {t}")
        tools = valid_tools

        if tools:
            logger.info(f"🔧 为 LLM 提供 {len(tools)} 个工具: {[t['function']['name'] for t in tools]}")
        return tools if tools else None
