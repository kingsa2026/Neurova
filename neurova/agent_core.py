"""
Agent Core - Agent 核心循环
协调记忆检索、上下文构建、LLM调用、记忆存储等模块

D1 任务重构版本：
- Agent 通过 Router 接收消息，而不是绕过 Router
- 提供 process_message 统一入口，所有消息经过 Router 路由
- 保留 chat 方法用于底层对话生成
"""

from neurova.core.logger import get_logger
from pathlib import Path
from typing import Any, Dict, List, Optional

# BE-CORE-003 修复: 下方 except 分支使用 logging.warning()，需导入 logging
import logging

from neurova.context import ContextOrchestrator
from neurova.core.idle_tracker import IdleTimeTracker
from neurova.core.sleep_config_manager import SleepConfigManager
from neurova.llm_client import LLMConfig
from neurova.mem_core import MemCore
from neurova.router import MessageRouter, RouteResult
from neurova.skills.agent_skill_manager import AgentSkillManager  # will be migrated to evolution
from neurova.skills.registry import SkillRegistry

# Neurova-Evocate: Neurova Hebb 记忆系统
try:
    from neurova.cognitive_layers.memory_layer.neuHebb_manager import NeuHebbManager
    from neurova.cognitive_layers.memory_layer.neurova_hebb import NeuHebbConfig

    NEUHEBB_AVAILABLE = True
except ImportError:
    NEUHEBB_AVAILABLE = False

# 温度引擎
try:
    from neurova.cognitive_layers.memory_layer.temperature import TemperatureEngine

    TEMPERATURE_ENGINE_AVAILABLE = True
except ImportError:
    TEMPERATURE_ENGINE_AVAILABLE = False
    logging.warning("TemperatureEngine not available")

# 认知图谱存储架构 — 一步到位替换
try:
    from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import CognitiveStorageEngine
    from neurova.cognitive_layers.memory_layer.pattern_crystallizer import PatternCrystallizer
    from neurova.cognitive_layers.memory_layer.reasoning_trace_manager import ReasoningTraceManager
    from neurova.cognitive_layers.memory_layer.unified_retriever import UnifiedRetriever

    COGNITIVE_GRAPH_AVAILABLE = True
except ImportError:
    COGNITIVE_GRAPH_AVAILABLE = False
    logging.warning("Cognitive Graph modules not available")

# P5: 对话管线（从 chat() 提取）
from neurova.agent.chat_pipeline import ChatContext, ChatPipeline

# LoopManager 深度模块
from neurova.agent.loop_manager import LoopManager

# P3: 内置工具注册器（替代 _init_file_operation_wrappers 的 15 个闭包）
from neurova.builtin_tools import BuiltinToolRegistry

# P0: Phase 2+3 模块接线 — 序列挖掘 / 基因编程 / 生命周期 / NL合成 / DAG编排 / 工具市场
from neurova.evolution import (
    NLToolSynthesizer,
    ToolLifecycleManager,
)
from neurova.post_chat_pipeline import PostChatPipeline

# P1: 提取的深度模块
from neurova.tool_executor import ToolExecutor
from neurova.tool_layers import (
    ToolMarketplace,
    ToolOrchestrator,
)

# Agent Loop 导入
try:
    pass

    AGENT_LOOP_AVAILABLE = True
except ImportError:
    AGENT_LOOP_AVAILABLE = False
    logging.warning("Agent Loop system not available, will use legacy chat methods")

logger = get_logger(__name__)


def debug_log(msg: str) -> None:
    """调试日志快捷函数"""
    logger.debug(msg)


from neurova.core.trace_recorder import get_trajectory_recorder
from neurova.session_manager import get_session_manager
from neurova.agent_loop_detection import calculate_similarity, detect_content_loop, has_repeated_patterns
from neurova.agent_shutdown import shutdown_agent

__all__ = ["AgentConfig", "Agent"]

# ═══════════════════════════════════════════════════════════════
# Agent LLM 客户端：指定模型/路由 → 委托 MultiModelLLMClient
# ═══════════════════════════════════════════════════════════════


class AgentLLMClient:
    """Agent 的 LLM 路由客户端
    不持有 API Key，通过 LLM 路由层（MultiModelLLMClient）传递上下文。
    指定模型 ID 或 'auto' 让路由器自动选择。
    """

    def __init__(self, model: str = "auto", provider_id: str = "", llm_config=None):
        self.model = model
        self.provider_id = provider_id
        # 使用真实的 LLMConfig，而非硬编码值
        # OpenAILoop 通过 hasattr 检查 temperature/max_tokens 等
        if llm_config is not None:
            self.config = llm_config
        else:
            # 向后兼容：没有传入 llm_config 时使用默认值
            from neurova.llm_client import LLMConfig
            self.config = LLMConfig(model=model)

    def _get_client(self):
        from neurova.llm.multi_model_client import get_multi_model_client

        return get_multi_model_client()

    async def chat(self, messages, **kwargs):
        result = await self._get_client().chat(
            messages, model=self.model if self.model != "auto" else None, provider_id=self.provider_id or None, **kwargs
        )
        # MultiModelLLMClient.chat() 返回 dict {"success": bool, "response": LLMResponse, ...}
        # OpenAILoop 等调用方期望直接得到 LLMResponse 对象，需要解包
        if isinstance(result, dict):
            if result.get("success"):
                return result.get("response", result)
            else:
                # 失败时返回一个包含错误信息的简单对象
                from neurova.llm_client import LLMResponse
                return LLMResponse(content=f"[LLM Error] {result.get('error', 'Unknown error')}")
        return result

    async def chat_stream(self, messages, **kwargs):
        async for chunk in self._get_client().chat_stream(
            messages, model=self.model if self.model != "auto" else None, provider_id=self.provider_id or None, **kwargs
        ):
            yield chunk

    def get_stats(self):
        return self._get_client().get_stats()


class AgentConfig:
    """Agent 配置"""

    def __init__(
        self,
        name: str = "忆灵",
        agent_id: str = "yi_ling",
        workspace_path: str = "",
        db_path: str = "",
        llm_api_key: str = "",
        llm_base_url: str = "https://api.openai.com/v1",
        llm_model: str = "gpt-4",
        llm_temperature: float = 0.7,
        max_tokens: int = 0,  # 0 = 自动适配（查 model_limits 注册表）
        enable_memory: bool = True,
        enable_streaming: bool = False,
        enable_active_skill_acquisition: bool = False,  # 主动技能获取
        llm_provider: str = "",  # LLM 服务商 ID
        enable_skill_packer: bool = False,  # 自动打包技能
        enable_cognitive_capabilities: bool = True,  # 认知能力
        enable_evolution: bool = True,  # 进化能力
        enable_experience_summary: bool = True,  # 经验总结
        # 个性和宪法配置
        personality: str = "",  # 个性设定
        constitution: str = "",  # 行为准则（宪法）
        behavior_rules: List[str] = None,  # 动态行为规则列表
        # TTS 配置
        enable_tts: bool = False,  # 是否启用 TTS
        tts_engine: str = "mock",  # TTS 引擎类型 (edge/moss_nano/mock)
        tts_voice: str = "mock",  # 音色名称
        tts_auto_download: bool = True,  # 是否自动下载模型
        # ASR 配置
        enable_asr: bool = False,  # 是否启用 ASR
        asr_engine: str = "mock",  # ASR 引擎类型 (funasr/whisper/mock)
        asr_voice: str = "zh",  # 语言
        asr_auto_download: bool = True,  # 是否自动下载模型
        # 活水上下文池配置
        enable_context_pool: bool = True,  # 是否启用活水上下文池
        enable_auto_tagging: bool = False,  # 是否启用自动标签生成
        # 所有权配置
        owner_user_id: Optional[str] = None,  # 创建者用户 ID
    ):
        self.name = name
        self.agent_id = agent_id
        self.owner_user_id = owner_user_id

        # 工作目录路径 - 必须由调用者提供，不使用硬编码
        if not workspace_path:
            raise ValueError(
                "workspace_path is required for Agent. "
                "Please provide a custom workspace directory for the agent. "
                f"Example: AgentConfig(name='{name}', agent_id='{agent_id}', workspace_path='/path/to/agent/workspace')"
            )

        self.workspace_path = Path(workspace_path)

        # 数据库路径配置 - 优先使用Agent工作目录下的memory文件夹
        if db_path:
            self.db_path = db_path
        else:
            # 标准路径：workspace/memory/memory.db
            agent_memory_dir = self.workspace_path / "memory"
            agent_memory_dir.mkdir(parents=True, exist_ok=True)
            self.db_path = str(agent_memory_dir / "memory.db")

        # 附件存储路径 - 标准路径：workspace/memory/attachments/
        self.attachment_dir = str(self.workspace_path / "memory" / "attachments")

        # LLM 服务商 ID（用于路由到指定服务商）
        self.llm_provider = llm_provider

        # max_tokens=0 表示自动适配
        if not max_tokens:
            from neurova.llm.model_limits import get_model_max_tokens
            max_tokens = get_model_max_tokens(llm_model)

        self.llm_config = LLMConfig(
            api_key=llm_api_key,
            base_url=llm_base_url,
            model=llm_model,
            temperature=llm_temperature,
            max_tokens=max_tokens,
            stream=enable_streaming,
        )

        self.enable_memory = enable_memory
        self.enable_streaming = enable_streaming
        self.enable_active_skill_acquisition = enable_active_skill_acquisition  # 主动技能获取
        self.enable_skill_packer = enable_skill_packer  # 自动打包技能

        # 认知能力配置
        self.enable_cognitive_capabilities = enable_cognitive_capabilities
        self.enable_evolution = enable_evolution
        self.enable_experience_summary = enable_experience_summary

        # TTS 配置
        self.enable_tts = enable_tts
        self.tts_engine = tts_engine
        self.tts_voice = tts_voice
        self.tts_auto_download = tts_auto_download

        # ASR 配置
        self.enable_asr = enable_asr
        self.asr_engine = asr_engine
        self.asr_voice = asr_voice
        self.asr_auto_download = asr_auto_download

        # 活水上下文池配置
        self.enable_context_pool = enable_context_pool
        self.enable_auto_tagging = enable_auto_tagging

        # 个性和宪法配置
        self.personality = personality
        self.constitution = constitution

        # 动态行为规则（Phase 6.5: 统一行为规则配置）
        self.behavior_rules = behavior_rules or [
            "- 始终使用中文交流",
            "- 保持温和、友善的语气",
            "- 根据记忆提供个性化的回答",
            "- 如果不确定，诚实地表达不确定性",
            "- 如果发现用户的问题需要搜索或文件操作，使用 [TOOL_CALL:工具名(参数)] 格式调用工具",
        ]


class _NullSystem:
    """空系统占位符 — 当闭环系统不可用时用作 fallback"""

    def get_feedback(self):
        return {}


class SubSystemContainer:
    """Agent 子系统容器 — 分组管理初始化逻辑

    将 Agent.__init__ 中 427 行的初始化代码按功能域分组：
    - memory: 记忆模块、温度引擎、认知图谱
    - context: 上下文构建、LLM 客户端
    - conversation: 对话历史、轨迹记录
    - management: 会话管理、路由、技能
    - voice: TTS、ASR、语音管线
    - tools: 工具路由、执行器、编排器
    - evolution: 进化引擎、经验总结
    - cognition: 认知能力、NeuHebb
    - pipeline: 后处理管线、对话管线
    - loop: 循环管理器

    设计原则：所有属性存储在 agent 上（保持向后兼容），container 仅负责初始化逻辑。
    """

    def __init__(self, agent):
        self.agent = agent
        self.config = agent.config

    def init_all(self):
        """按依赖顺序初始化所有子系统

        使用 InitializationManager 进行拓扑排序, 自动解析依赖关系。
        依赖图见 _build_dependency_graph()。
        """
        order = self._compute_initialization_order()

        # 子系统名 → init 方法映射
        init_methods = {
            "memory": self.init_memory,
            "context": self.init_context,
            "conversation": self.init_conversation,
            "management": self.init_management,
            "voice": self.init_voice,
            "security": self.init_security,
            "cognition": self.init_cognition,
            "evolution": self.init_evolution,
            "tools": self.init_tools,
            "pipeline": self.init_pipeline,
            "loop": self.init_loop,
            "api_keys": self._load_api_keys,
        }

        for name in order:
            method = init_methods.get(name)
            if method:
                method()

    def _build_dependency_graph(self) -> Dict[str, List[str]]:
        """返回子系统依赖图 (基于实际代码分析)

        每个子系统声明其初始化依赖的其他子系统。
        InitializationManager 使用此图进行拓扑排序。

        依赖关系来源 (代码级证据):
          - context: 调用 context_orchestrator.init_context_system() (memory 中设置)
          - voice: 使用 a.memory_manager 和 a.evolution (evolution_orchestrator)
          - cognition: 使用 a.memory_manager
          - evolution: 使用 a.tool_memory (memory) 和 a._skill_registry (management)
          - tools: 使用 a.memory_manager 和 a._skill_registry (management)
          - pipeline: PostChatPipeline/ChatPipeline 需要 memory/context/tools
          - loop: LoopManager 需要 agent 已完全初始化 (pipeline)
        """
        return {
            "memory": [],
            "context": ["memory"],
            "conversation": [],
            "management": [],
            "voice": ["memory", "evolution"],
            "security": [],
            "cognition": ["memory"],
            "evolution": ["memory", "management"],
            "tools": ["memory", "management"],
            "pipeline": ["memory", "context", "tools"],
            "loop": ["pipeline"],
            "api_keys": [],
        }

    def _compute_initialization_order(self) -> List[str]:
        """使用 InitializationManager 计算初始化顺序

        Returns:
            按依赖顺序排列的子系统名列表

        Raises:
            ValueError: 如果检测到循环依赖
        """
        from neurova.agent.initialization_manager import InitializationManager

        im = InitializationManager()
        for name, deps in self._build_dependency_graph().items():
            im.register(name, lambda: None, deps=deps)
        return im.get_initialization_order()

    def init_memory(self):
        """初始化记忆模块"""
        a = self.agent
        c = self.config

        a.memory_manager = None
        a.storage = None
        a.temperature_engine = TemperatureEngine() if TEMPERATURE_ENGINE_AVAILABLE else None
        a.memory_agent = MemCore(a)
        a.context_orchestrator = ContextOrchestrator(a, use_pool=c.enable_context_pool, auto_tag=c.enable_auto_tagging)

        a.cognitive_engine = None
        a.unified_retriever = None
        a.crystallizer = None
        a.trace_manager = None

        if c.enable_memory:
            a._init_memory_modules()
            try:
                a.memory_agent.init_moe_router()
            except Exception as e:
                logger.warning("MoE 路由器初始化失败: %s", e)

            if COGNITIVE_GRAPH_AVAILABLE:
                try:
                    a._init_cognitive_graph()
                except Exception as e:
                    logger.warning("认知图谱初始化失败: %s", e)

        # ToolMemory（闭环学习）
        a.tool_memory = None
        if a.memory_manager:
            try:
                from neurova.cognitive_layers.memory_layer.muscle_memory import MuscleMemory
                from neurova.cognitive_layers.memory_layer.tool_memory_integration import ToolMemoryIntegration

                muscle_memory = MuscleMemory(
                    agent_id=c.agent_id,
                    storage_dir=str(c.workspace_path / "memory" / "muscle_memory"),
                )
                a.tool_memory = ToolMemoryIntegration(
                    memory_layer=a.memory_manager,
                    muscle_memory=muscle_memory,
                    confidence_threshold=0.8,
                    temperature_threshold=30.0,
                )
            except Exception as e:
                logger.warning("ToolMemory 初始化失败: %s", e)

    def init_context(self):
        """初始化上下文系统"""
        a = self.agent
        c = self.config

        a.context_orchestrator.init_context_system()
        a.llm_client = AgentLLMClient(
            model=c.llm_config.model if hasattr(c, "llm_config") and c.llm_config else "auto",
            provider_id=getattr(c, "llm_provider", "") or "",
            llm_config=c.llm_config if hasattr(c, "llm_config") else None,
        )

    def init_conversation(self):
        """初始化对话状态"""
        a = self.agent
        a.conversation_history = []
        a._current_user_input = None
        a._current_trace_id = ""
        a._trajectory_recorder = get_trajectory_recorder()

    def init_management(self):
        """初始化会话管理、路由、技能"""
        a = self.agent
        a.session_manager = get_session_manager()
        a._router = None
        a._skill_registry = None
        a.sleep_config_manager = SleepConfigManager()
        a.idle_tracker = IdleTimeTracker()
        a.skill_manager = None
        a.skill_packer = None

    def init_voice(self):
        """初始化语音模块"""
        a = self.agent
        c = self.config

        a.tts_manager = None
        if c.enable_tts:
            try:
                from neurova.tts.manager import TTSConfig, TTSManager

                tts_config = TTSConfig(
                    engine=c.tts_engine,
                    voice=c.tts_voice,
                    auto_download=c.tts_auto_download,
                    model_path=str(c.workspace_path / "models" / "tts" / "moss-nano"),
                    tokenizer_path=str(c.workspace_path / "models" / "tts" / "moss-tokenizer"),
                )
                a.tts_manager = TTSManager(tts_config)
            except Exception as e:
                logger.warning("TTS管理器初始化失败: %s", e)

        a.asr_manager = None
        if c.enable_asr:
            try:
                from neurova.asr.manager import ASRConfig, ASRManager

                asr_config = ASRConfig(
                    engine=c.asr_engine,
                    voice=c.asr_voice,
                    model_path=str(c.workspace_path / "models" / "asr"),
                    auto_download=c.asr_auto_download,
                )
                a.asr_manager = ASRManager(asr_config)
            except Exception as e:
                logger.warning("ASR管理器初始化失败: %s", e)

        a.voice_pipeline = None
        if c.enable_tts or c.enable_asr:
            try:
                from neurova.voice_pipeline import get_voice_pipeline

                a.voice_pipeline = get_voice_pipeline()
            except Exception:
                pass

        a.voice_memory_bridge = None
        if (c.enable_tts or c.enable_asr) and a.memory_manager:
            try:
                from neurova.voice_memory_bridge import VoiceMemoryBridge, VoiceMemoryConfig

                voice_config = VoiceMemoryConfig(
                    enable_asr_memory=c.enable_asr,
                    enable_tts_stats=c.enable_tts,
                    enable_emotion_analysis=True,
                    min_confidence_threshold=0.5,
                )
                a.voice_memory_bridge = VoiceMemoryBridge(
                    config=voice_config,
                    memory_manager=a.memory_manager,
                    emotion_module=getattr(a.memory_manager, "_emotion_module", None),
                    evolution_orchestrator=a.evolution,
                )
            except Exception as e:
                logger.warning("语音记忆桥接器初始化失败: %s", e)

    def init_security(self):
        """初始化安全模块"""
        a = self.agent
        a.approval_manager = None
        try:
            from neurova.security.approval_manager import ApprovalLevel, ApprovalManager

            a.approval_manager = ApprovalManager(
                workspace_path=str(a.config.workspace_path),
                approval_level=ApprovalLevel.SMART,
            )
        except Exception as e:
            logger.warning("审批管理器初始化失败: %s", e)

    def init_cognition(self):
        """初始化认知能力"""
        a = self.agent
        c = self.config

        a.growth_analyzer = None
        if c.enable_cognitive_capabilities and a.memory_manager:
            try:
                from neurova.cognitive_layers.growth_layer.analyzer import GrowthAnalyzer

                a.growth_analyzer = GrowthAnalyzer(
                    storage_path=str(c.workspace_path / "memory" / "growth"),
                )
            except Exception as e:
                logger.warning("认知能力初始化失败: %s", e)

        a.neuHebb_manager = None
        if NEUHEBB_AVAILABLE and c.enable_memory:
            try:
                hebb_config = NeuHebbConfig(
                    persistence_path=str(c.workspace_path / "data" / "neurova_hebbs"),
                    enabled=True,
                )
                a.neuHebb_manager = NeuHebbManager(config=hebb_config)
            except Exception as e:
                logger.warning("Neurova-Evocate 初始化失败: %s", e)

    def init_evolution(self):
        """初始化进化引擎"""
        a = self.agent
        c = self.config

        a.evolution = None
        if c.enable_evolution or c.enable_experience_summary:
            try:
                from neurova.evolution import EvolutionOrchestrator

                a.evolution = EvolutionOrchestrator()
                if a._skill_registry:
                    skill_names = [s.name for s in a._skill_registry.list_skills()]
                    a.evolution.register_tools(skill_names)
            except Exception as e:
                logger.warning("统一进化引擎初始化失败: %s", e)

        a.evolution_engine = a.evolution  # 向后兼容别名
        a.pattern_miner = None
        a.genetic_engine = None
        if a.evolution:
            a.pattern_miner = a.evolution.pattern_miner
            a.genetic_engine = a.evolution.genetic_engine

        a.tool_lifecycle = None
        try:
            a.tool_lifecycle = ToolLifecycleManager()
        except Exception as e:
            logger.warning("ToolLifecycleManager 初始化失败: %s", e)

        if a.tool_memory and a.evolution:
            a.tool_memory.tool_weights = a.evolution.tool_weights
            a.tool_memory.tool_lifecycle = a.tool_lifecycle

        a.tool_synthesizer = None
        if c.enable_evolution:
            try:
                a.tool_synthesizer = NLToolSynthesizer(pattern_miner=a.pattern_miner)
            except Exception as e:
                logger.warning("NLToolSynthesizer 初始化失败: %s", e)

    def init_tools(self):
        """初始化工具系统"""
        a = self.agent

        a._builtin_tools = None
        try:
            from neurova.computer_use import get_computer_use_manager

            computer_use = get_computer_use_manager()
            a._builtin_tools = BuiltinToolRegistry()
            logger.info("Agent %s: BuiltinToolRegistry 初始化成功", a.config.name)
        except Exception as e:
            logger.warning("BuiltinToolRegistry 初始化失败: %s", e)

        # [BUGFIX] 提前初始化 SkillRegistry，避免 ToolRouter 获得 None
        if a._skill_registry is None:
            try:
                from neurova.skill_system import create_default_skills
                a._skill_registry = create_default_skills(memory_manager=a.memory_manager)
                logger.info("Agent %s: SkillRegistry 在 init_tools 中提前初始化", a.config.name)
            except Exception as _e:
                logger.warning("init_tools 中提前初始化 SkillRegistry 失败: %s", _e)
                a._skill_registry = None  # 显式设置为 None 以便后续检测

        a.tool_router = None
        try:
            from neurova.tool_layers import ToolRouter

            a.tool_router = ToolRouter()
            a.tool_router.set_skill_manager(a.skill_registry)
            if a._builtin_tools:
                tools_dict = {t.name: t for t in a._builtin_tools.list_tools()}
                a.tool_router.register_builtin_batch(tools_dict)
        except Exception as e:
            logger.warning("ToolRouter 初始化失败: %s", e)

        a.model_adapter = None
        try:
            from neurova.cognitive_layers.model_adapter import ModelAdapterRegistry

            model_name = a.config.llm_config.model if a.config.llm_config else ""
            model_name = model_name or "deepseek-v4-flash"
            a.model_adapter = ModelAdapterRegistry.get_adapter(model_name)
        except Exception as e:
            logger.warning("模型适配器初始化失败: %s", e)

        a.tool_orchestrator = None
        try:
            a.tool_orchestrator = ToolOrchestrator()

            async def _orchestrator_executor(tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
                if a._skill_registry:
                    skill = a._skill_registry.get_skill(tool_name)
                    if skill:
                        result = await a._skill_registry.execute_skill(tool_name, params)
                        if result.success:
                            return {"success": True, "data": result.data}
                        return {"success": False, "error": result.error}
                if a.tool_router:
                    router_result = await a.tool_router.execute(
                        tool_name=tool_name,
                        params=params,
                        agent_id=a.config.agent_id,
                        user_id=getattr(a.config, "user_id", "default"),
                    )
                    if router_result and router_result.success:
                        return {"success": True, "data": router_result.result}
                    error = getattr(router_result, "error", None) if router_result else "no result"
                    return {"success": False, "error": str(error) if error else "unknown error"}
                return {"success": False, "error": f"工具 '{tool_name}' 未找到"}

            a.tool_orchestrator.set_executor(_orchestrator_executor)
        except Exception as e:
            logger.warning("ToolOrchestrator 初始化失败: %s", e)

        a.tool_marketplace = None
        try:
            a.tool_marketplace = ToolMarketplace()
        except Exception as e:
            logger.warning("ToolMarketplace 初始化失败: %s", e)

        a.tool_executor = ToolExecutor(a)

        # [BUGFIX] 将 ToolExecutor 引用注入 ToolRouter，使内置工具可执行
        if a.tool_router and a.tool_executor:
            a.tool_router.set_tool_executor(a.tool_executor)

    def init_pipeline(self):
        """初始化管线"""
        a = self.agent
        a.post_chat_pipeline = PostChatPipeline(a)

        a.neurflow_executor = None
        try:
            from neurova.collaboration.neurflow.execution_engine import get_workflow_executor

            a.neurflow_executor = get_workflow_executor()
        except ImportError:
            pass

        a.chat_pipeline = ChatPipeline(a)

    def init_loop(self):
        """初始化循环管理器"""
        a = self.agent
        a.loop_manager = LoopManager(a)
        a.loop_manager.initialize_sync()
        a.loop = a.loop_manager.get_loop()

    def _load_api_keys(self):
        """从服务商加载 API Key（Agent 配置优先，仅填充空值）"""
        c = self.config
        if c.llm_config is None:
            c.llm_config = LLMConfig()
        if c.llm_provider:
            try:
                from neurova.llm.provider_manager import get_provider_manager

                pm = get_provider_manager()
                provider = pm.get_provider(c.llm_provider)
                if provider:
                    # 优先级: Agent > Provider > System
                    # 仅在 agent 未显式设置时才从 provider 填充
                    if not c.llm_config.api_key and provider.api_key:
                        c.llm_config.api_key = provider.api_key
                        logger.debug("从 provider '%s' 填充 api_key", c.llm_provider)
                    if c.llm_config.base_url == "https://api.openai.com/v1" and provider.base_url:
                        c.llm_config.base_url = provider.base_url
                        logger.debug("从 provider '%s' 填充 base_url", c.llm_provider)
            except Exception as e:
                logger.warning("从 llm_provider 加载配置失败: %s", e)


class Agent:
    """
    Agent 核心

    职责:
    1. 接收用户输入（通过 Router）
    2. 检索相关记忆
    3. 构建上下文
    4. 调用 LLM 生成回复
    5. 存储新记忆
    6. 更新记忆温度

    集成方式:
    - 所有消息通过 Router 路由，不直接调用 chat
    - Router 识别消息类型后分发给 Skill/记忆/对话处理器
    - 普通对话才由 Agent 的 chat 方法处理
    """

    def __init__(self, config: Optional[AgentConfig] = None, **kwargs):

        self.config = config or AgentConfig(**kwargs)

        logger.debug("Agent.__init__() 开始: %s (ID: %s)", self.config.name, self.config.agent_id)

        # 加载身份和性格
        self._load_identity()

        # 初始化所有子系统（通过 SubSystemContainer 分组管理）
        self._subsystems = SubSystemContainer(self)
        self._subsystems.init_all()

        logger.info("Agent %s 初始化完成", self.config.name)

    def rebuild_loop(self, model_name: str) -> bool:
        """
        重建 Agent Loop（模型热切换时调用）

        当模型切换后，需要重新选择合适的 Loop 类型，
        因为不同模型可能需要不同的 Loop（如 OpenAI vs Anthropic）。

        参数:
            model_name: 新的模型名称

        返回:
            True 表示重建成功，False 表示失败
        """
        if not AGENT_LOOP_AVAILABLE:
            logger.warning("Agent Loop 系统不可用，无法重建")
            return False

        # 委托给 LoopManager
        result = self.loop_manager.rebuild(model_name)
        # 同步 self.loop 引用
        self.loop = self.loop_manager.get_loop()
        return result

    async def process_multimodal(
        self,
        content: str,
        media_type: str,
        model: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        处理多模态消息（图片、音频、视频、文档）

        由 Router 的 _route_multimedia_message 调用。
        根据 media_type 使用 LLMRouter 选择合适的模型，
        然后将媒体信息注入上下文并调用 chat()。

        Args:
            content: 用户文本内容
            media_type: 媒体类型 (image/voice/video/document)
            model: 指定模型名（可选，为空则由 LLMRouter 自动选择）
            metadata: 消息元数据（含 media_url, filename, mime_type 等）

        Returns:
            str: Agent 回复文本
        """
        metadata = metadata or {}
        logger.info("处理多模态消息: media_type=%s, model=%s", media_type, model)

        # 1. 将 media_type 映射为 LLM RequestType，使用 LLMRouter 选择模型
        try:
            from neurova.llm.llm_router import RequestType as LLMRequestType
            from neurova.llm.llm_router import (
                select_model_for_request,
            )

            media_to_request_type = {
                "image": LLMRequestType.IMAGE_UNDERSTANDING,
                "voice": LLMRequestType.AUDIO_UNDERSTANDING,
                "video": LLMRequestType.VIDEO_GENERATION,  # 视频理解暂用同类型
                "document": LLMRequestType.CHAT,  # 文档走普通聊天
            }
            request_type = media_to_request_type.get(media_type, LLMRequestType.CHAT)

            # 使用 LLMRouter 选择最佳模型（如果未指定）
            if not model:
                selection = select_model_for_request(request_type)
                if selection:
                    model = selection.model
                    logger.info("LLMRouter 为 %s 选择模型: " f"%s/%s", media_type, selection.provider_name, selection.model)

            # 如果指定了模型且与当前不同，热切换
            if model and model != getattr(self.config.llm_config, "model", None):
                logger.info("多模态路由：热切换模型到 %s", model)
                self.rebuild_loop(model)

        except Exception as e:
            logger.warning("多模态模型选择失败，使用当前模型: %s", e)

        # 2. 构建多模态上下文描述
        metadata.get("media_url", "")
        filename = metadata.get("filename", "")
        metadata.get("mime_type", "")
        audio_bytes = metadata.get("audio_bytes")  # 语音消息可能包含音频数据

        media_descriptions = {
            "image": f"[用户发送了一张图片{': ' + filename if filename else ''}]",
            "voice": f"[用户发送了一段语音消息{': ' + filename if filename else ''}]",
            "video": f"[用户发送了一个视频{': ' + filename if filename else ''}]",
            "document": f"[用户发送了一个文档{': ' + filename if filename else ''}]",
        }
        media_desc = media_descriptions.get(media_type, f"[用户发送了媒体文件: {media_type}]")

        # 语音消息：通过统一语音管线处理（ASR→情感→上下文→记忆）
        voice_context = None
        if media_type == "voice" and audio_bytes:
            if self.voice_pipeline:
                try:
                    user_id = getattr(self.config, "user_id", "default")
                    agent_id = getattr(self.config, "agent_id", "default")
                    pipeline_result = await self.voice_pipeline.process_asr(
                        audio_data=audio_bytes,
                        user_id=user_id,
                        agent_id=agent_id,
                        **{k: v for k, v in (metadata or {}).items() if k not in ("audio_bytes",)},
                    )
                    if pipeline_result.text:
                        transcribed_text = pipeline_result.text
                        logger.info("ASR 转写结果: %s...", transcribed_text[:100])
                        media_desc = f"[语音识别结果: {transcribed_text}]"
                        # 构建语音上下文供后续 metadata 注入
                        voice_context = {
                            "text": transcribed_text,
                            "confidence": pipeline_result.confidence,
                            "language": pipeline_result.language,
                            "engine": pipeline_result.engine,
                            "duration_ms": pipeline_result.duration_ms,
                            "emotion": pipeline_result.emotion,
                            "audio_metadata": {
                                "filename": metadata.get("filename", "") if metadata else "",
                                "mime_type": metadata.get("mime_type", "") if metadata else "",
                                "file_size": len(audio_bytes),
                            },
                        }
                    elif pipeline_result.error:
                        logger.warning("语音管线 ASR 失败: %s", pipeline_result.error)
                except Exception as e:
                    logger.warning("统一语音管线处理失败: %s", e)
            elif self.asr_manager:
                # 降级：直接调用 ASR 引擎（无管线集成）
                try:
                    asr_result = await self.asr_manager.transcribe(audio_bytes)
                    if asr_result and "text" in asr_result:
                        transcribed_text = asr_result["text"]
                        logger.info("ASR 转写结果（降级模式）: %s...", transcribed_text[:100])
                        media_desc = f"[语音识别结果: {transcribed_text}]"
                        voice_context = {
                            "text": transcribed_text,
                            "confidence": asr_result.get("confidence", 0.0),
                            "language": asr_result.get("language", "zh"),
                            "engine": asr_result.get("engine", "unknown"),
                            "duration_ms": asr_result.get("duration_ms", 0),
                        }
                except Exception as e:
                    logger.warning("ASR 转写失败（降级模式）: %s", e)

        # 3. 将媒体描述注入用户输入，调用 chat()
        enriched_input = f"{media_desc}\n{content}" if content else media_desc

        # 附加原始 metadata（含 attachment_ids 供附件管理器使用）
        chat_metadata = dict(metadata)

        # 如果有语音上下文，添加到 metadata
        if voice_context:
            chat_metadata["voice_context"] = voice_context

        response = await self.chat(
            enriched_input,
            metadata=chat_metadata if chat_metadata else None,
        )

        # chat() 返回 dict，提取文本
        if isinstance(response, dict):
            return response.get("text", str(response))
        return str(response)

    @property
    def router(self) -> Optional[MessageRouter]:
        """获取 Router 实例"""
        return self._router

    @router.setter
    def router(self, value: MessageRouter):
        """设置 Router 实例"""
        self._router = value
        logger.info("Agent %s 已绑定 Router", self.config.name)

    @property
    def skill_registry(self) -> Optional[SkillRegistry]:
        """获取 Skill 注册中心"""
        return self._skill_registry

    @skill_registry.setter
    def skill_registry(self, value: SkillRegistry):
        """设置 Skill 注册中心"""
        self._skill_registry = value
        logger.info("Agent %s 已绑定 SkillRegistry", self.config.name)

    def _load_identity(self):
        """加载 Agent 身份和性格"""
        workspace = self.config.workspace_path / "workspace" / "memory"

        # 加载 soul.md
        soul_path = workspace / "soul.md"
        if soul_path.exists():
            self.soul = soul_path.read_text(encoding="utf-8")
            logger.info("已加载身份文件: %s", soul_path)
        else:
            self.soul = f"你是 {self.config.name}，一个友好的 AI 助手。"
            logger.warning(f"未找到身份文件，使用默认身份")

        # 加载 personality.md
        personality_path = workspace / "personality.md"
        if personality_path.exists():
            self.personality = personality_path.read_text(encoding="utf-8")
            logger.info("已加载性格文件: %s", personality_path)
        else:
            self.personality = ""

    def _init_memory_modules(self, neuser_id: str = "default", user_id: str = "default"):
        """初始化记忆系统模块（委托给 MemCore）

        Args:
            neuser_id: Neurova系统用户ID（三级隔离第2级）
            user_id: 对话用户ID（三级隔离第3级）
        """
        self.memory_agent.init_memory_modules(neuser_id=neuser_id, user_id=user_id)

        # Phase 10: 初始化睡眠整理引擎（不启动，仅在 shutdown 时触发）
        try:
            from neurova.cognitive_layers.memory_layer.sleep import SleepConsolidation

            self.sleep_consolidation = SleepConsolidation(
                memory_manager=self.memory_manager,
                storage=self.storage,
            )
            # 连接 IdleTimeTracker 和 SleepConsolidation
            if hasattr(self, "idle_tracker") and self.idle_tracker:
                self.idle_tracker.set_sleep_consolidation(self.sleep_consolidation)
                self.idle_tracker.set_memory_manager(self.memory_manager)
            logger.info("Agent %s: SleepConsolidation（睡眠整理）已初始化", self.config.name)
        except Exception as e:
            logger.warning("SleepConsolidation 初始化失败: %s", e)
            self.sleep_consolidation = None

        logger.info(
            f"记忆系统模块初始化成功: agent_id={self.config.agent_id}, neuser_id={neuser_id}, user_id={user_id}"
        )

    def _init_cognitive_graph(self):
        """初始化认知图谱存储架构"""
        # 创建数据目录
        data_dir = Path(f"data/{self.config.agent_id}")
        data_dir.mkdir(parents=True, exist_ok=True)

        # 1. 初始化 CognitiveStorageEngine
        self.cognitive_engine = CognitiveStorageEngine(
            agent_id=self.config.agent_id,
            data_dir=str(data_dir),
        )
        logger.info("CognitiveStorageEngine 初始化完成: %s", data_dir)

        # 2. 初始化 UnifiedRetriever（包装旧检索器）
        moe_router = getattr(self.memory_agent, "moe_router", None)
        recall_engine = getattr(self.memory_agent, "recall_engine", None)
        hebb_manager = getattr(self.memory_agent, "hebb_manager", None)

        self.unified_retriever = UnifiedRetriever(
            engine=self.cognitive_engine,
            moe_router=moe_router,
            recall_engine=recall_engine,
            hebb_manager=hebb_manager,
        )
        logger.info("UnifiedRetriever 初始化完成")

        # 3. 初始化 PatternCrystallizer
        evolution = getattr(self, "evolution", None)
        self.crystallizer = PatternCrystallizer(
            engine=self.cognitive_engine,
            evolution_orchestrator=evolution,
        )
        logger.info("PatternCrystallizer 初始化完成")

        # 将 crystallizer 注入到 EvolutionOrchestrator
        if evolution and hasattr(evolution, "crystallizer"):
            evolution.crystallizer = self.crystallizer
            logger.info("PatternCrystallizer 已注入到 EvolutionOrchestrator")

        # 4. 初始化 RSI（递归自我改进）编排器
        self.rsi_orchestrator = None
        try:
            from neurova.evolution.rsi.orchestrator import RSIOrchestrator

            # 获取四大闭环系统
            sleep_system = getattr(self, "sleep_consolidation", None)
            emotion_system = getattr(self.memory_manager, "_emotion_module", None) if self.memory_manager else None
            experience_system = getattr(evolution, "experience_feedback", None) if evolution else None
            tool_memory_system = getattr(self, "tool_memory", None)

            # 只有当至少一个闭环系统可用时才初始化 RSI
            available_systems = [
                s for s in [sleep_system, emotion_system, experience_system, tool_memory_system] if s is not None
            ]
            if available_systems:
                self.rsi_orchestrator = RSIOrchestrator(
                    sleep_system=sleep_system or _NullSystem(),
                    emotion_system=emotion_system or _NullSystem(),
                    experience_system=experience_system or _NullSystem(),
                    tool_memory_system=tool_memory_system or _NullSystem(),
                )
                logger.info("Agent %s: RSI 编排器已初始化 (%s/4 闭环系统可用)", self.config.name, len(available_systems))
            else:
                logger.info("Agent %s: RSI 未初始化（无可用闭环系统）", self.config.name)
        except Exception as e:
            logger.warning("Agent %s: RSI 初始化失败: %s", self.config.name, e)

        # 5. 初始化 ReasoningTraceManager
        self.trace_manager = ReasoningTraceManager(
            engine=self.cognitive_engine,
        )
        logger.info("ReasoningTraceManager 初始化完成")

    def init_router(self) -> MessageRouter:
        """
        初始化 Router 并注入依赖

        这会创建默认的 Router，并注入:
        - Agent 自身（用于聊天处理）
        - SkillRegistry（用于 Skill 执行）
        - MemoryManager（用于记忆操作）
        """
        from neurova.router import create_default_router

        # 先初始化 SkillRegistry（只在尚未初始化时创建，避免 init_tools 已创建的被覆盖）
        if not self._skill_registry:
            self._skill_registry = create_default_skills(memory_manager=self.memory_manager)
            logger.info("Agent %s: SkillRegistry 在 _init_router 中初始化", self.config.name)
        else:
            logger.info("Agent %s: SkillRegistry 已存在，跳过重复初始化", self.config.name)

        # 注册 ToolMemory 回调：Skill 成功执行后记录到 ToolMemory
        if self.tool_memory and self._skill_registry:
            self._skill_registry.register_event_callback(
                SkillEvent.POST_EXECUTE,
                self._on_skill_post_execute,
            )
            logger.info("Agent %s: ToolMemory 回调已注册（Skill成功执行时记录）", self.config.name)

        # 创建 Router 并注入所有依赖
        self._router = create_default_router(
            agent=self,
            skill_registry=self._skill_registry,
            memory_manager=self.memory_manager,
        )

        # 初始化技能管理器（如果启用主动技能获取）
        if self.config.enable_active_skill_acquisition:
            self.skill_manager = AgentSkillManager(
                agent_id=self.config.agent_id,
                skill_registry=self._skill_registry,
                auto_acquire=True,
            )
            logger.info("Agent %s 的 SkillManager 已初始化", self.config.name)

        # 初始化技能自动构建器 (AutoSkillBuilder from evolution)
        # 替换旧的 SkillPacker，统一在 evolution 模块中
        if self.config.enable_skill_packer:
            try:
                from neurova.evolution import AutoSkillBuilder

                self.skill_packer = AutoSkillBuilder(
                    min_occurrences=3,
                    min_success_rate=0.7,
                )
                logger.info("Agent %s: AutoSkillBuilder 已初始化", self.config.name)

            except ImportError as e:
                logger.warning("AutoSkillBuilder 初始化失败: %s", e)

        logger.info("Agent %s 的 Router 已初始化", self.config.name)
        return self._router

    def _on_skill_post_execute(self, skill, result, **kwargs):
        """
        Skill 成功执行后，记录到 ToolMemory（闭环学习）

        通过 SkillRegistry 的 POST_EXECUTE 事件触发，
        仅在 result.success == True 时记录。
        """
        if not self.tool_memory or not result or not result.success:
            return

        try:
            # 从 result.metadata 获取原始 skill 参数
            tool_params = result.metadata.get("skill_kwargs", {})
            problem_text = self._current_user_input or f"执行 {skill.name}"

            self.tool_executor.on_tool_executed(
                tool_name=skill.name,
                params=tool_params,
                user_input=problem_text,
                success=True,
                tool_source="skill_system",
                execution_time=result.execution_time,
            )
            logger.info("ToolMemory 记录成功技能执行: %s", skill.name)
        except Exception as e:
            logger.warning("ToolMemory 记录失败: %s", e)

    async def process_message(self, content: str, sender: str = "user") -> RouteResult:
        """
        处理消息的统一入口 - 通过 Router 接收消息

        这是 D1 集成的核心方法：
        1. 创建 Message 对象
        2. 通过 Router 路由
        3. 返回 RouteResult

        所有外部调用都应该使用此方法，而不是直接调用 chat

        参数:
        content: 消息内容
        sender: 发送者

        返回:
        RouteResult 路由结果
        """
        if not self._router:
            # 如果 Router 未初始化，自动初始化
            self.init_router()

        # 创建消息对象
        message = self._router.create_message(content=content, sender=sender)

        # 附加引用以便命令处理器访问
        message.metadata["agent"] = self
        message.metadata["router"] = self._router
        message.metadata["skill_registry"] = self._skill_registry

        logger.info("Agent %s 收到消息: %s...", self.config.name, content[:50])

        # 通过 Router 路由（现在是异步的）
        result = await self._router.route(message)

        logger.info("消息路由完成: %s, success=%s", result.message_type.value, result.success)

        return result

    async def chat(
        self,
        user_input: str,
        stream: bool = False,
        save_memory: bool = True,
        session_id: str = None,
        metadata: Optional[Dict[str, Any]] = None,
        enable_tts: bool = None,
    ) -> Dict[str, Any]:
        """
        与用户对话（底层方法，由 Router 调用）

        P5 重构：委托给 ChatPipeline，将 ~580 行逻辑拆分为独立可测试的步骤。

        参数:
        user_input: 用户输入
        stream: 是否流式输出
        save_memory: 是否保存对话记忆
        session_id: 会话ID（用于session备份）
        metadata: 附加元数据（如 attachment_ids）
        enable_tts: 是否启用TTS（覆盖配置，None表示使用配置）

        返回:
        包含文本回复和音频路径的字典:
        {
            "text": "文本回复",
            "audio_path": "音频文件路径（如果有）",
            "audio_data": b"音频数据（如果有）",
        }
        """
        logger.info("收到用户输入: %s...", user_input[:50])
        ctx = ChatContext(
            user_input=user_input,
            stream=stream,
            save_memory=save_memory,
            session_id=session_id,
            metadata=metadata,
            enable_tts=enable_tts,
        )
        return await self.chat_pipeline.execute(ctx)

    async def _record_tool_failure_lesson(
        self,
        tool_name: str,
        user_input: str,
        error_msg: str,
    ) -> None:
        """记录工具执行失败的教训 — 反思日志 + 肌肉记忆降级

        1. 重置肌肉记忆的 consecutive_success 为 0（触发自动降级）
        2. 写入反思日志（growth_log_manager）
        """
        # 1. 重置肌肉记忆的连续成功计数（触发自动降级）
        try:
            muscle = getattr(self.tool_memory, "muscle_memory", None) if self.tool_memory else None
            if muscle and hasattr(muscle, "items"):
                for key, item in muscle.items.items():
                    if hasattr(item, "tool_name") and item.tool_name == tool_name:
                        item.consecutive_success = 0
                        logger.info("📉 肌肉记忆降级: %s consecutive_success 重置为 0", tool_name)
                        break
        except Exception as e:
            logger.debug("肌肉记忆降级记录跳过: %s", e)

        # 2. 写入反思日志
        try:
            glog = getattr(self, "growth_log_manager", None)
            if glog:
                from neurova.cognitive_layers.meta_cognition_layer.growth_log import ReflectionType

                entry = await glog.generate_log(
                    type=ReflectionType.ERROR,
                    title=f"工具失败: {tool_name}",
                    content=(
                        f"工具「{tool_name}」肌肉记忆自动执行失败: {error_msg}。"
                        f"用户输入: {user_input[:200]}。"
                        f"下次遇到类似输入时应降低自动执行置信度。"
                    ),
                    context={
                        "tool_name": tool_name,
                        "error_msg": error_msg,
                        "user_input": user_input[:200],
                        "trigger": "tool_failure",
                    },
                    insights=[f"工具 {tool_name} 执行失败"],
                    action_items=["降低自动执行置信度"],
                    confidence=0.7,
                )
                logger.info("📝 已记录工具失败教训: %s (反思ID: %s)", tool_name, entry.id)
        except Exception as e:
            logger.debug("反思日志记录跳过: %s", e)

    def _save_to_session(
        self,
        user_input: str,
        reply: str,
        session_id: str = None,
        metadata: Optional[Dict[str, Any]] = None,
        assistant_metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """保存对话到session文件（委托给 MemCore）"""
        return self.memory_agent.save_to_session(user_input, reply, session_id, metadata, assistant_metadata)

    def _update_memory_temperature(self):
        """更新记忆温度（批量衰减）"""
        try:
            if not self.memory_manager:
                logger.debug("memory_manager 未初始化，跳过温度更新")
                return

            # 使用 MemoryManager.run_decay_cycle() 批量衰减所有记忆温度
            # 衰减参数：hours=1.0 表示每小时衰减一次，rate=1.0 使用默认衰减率
            count = self.memory_manager.run_decay_cycle(hours=1.0, rate=1.0)
            if count > 0:
                logger.debug("记忆温度已更新: %s 条记忆", count)
        except Exception as e:
            logger.warning("记忆温度更新失败: %s", e)

    def get_llm_stats(self) -> Dict[str, Any]:
        """获取 LLM 统计信息"""
        return self.llm_client.get_stats()

    def clear_history(self):
        """清空对话历史"""
        self.conversation_history = []
        logger.info("对话历史已清空")

    def get_integration_info(self) -> Dict[str, Any]:
        """获取集成信息（用于调试和测试）"""
        return {
            "agent_name": self.config.name,
            "router_initialized": self._router is not None,
            "skill_registry_initialized": self._skill_registry is not None,
            "memory_manager_initialized": self.memory_manager is not None,
            "skill_count": len(self._skill_registry.skills) if self._skill_registry else 0,
            "conversation_history_length": len(self.conversation_history),
        }

    def _detect_content_loop(self, contents: List[str], threshold: float = 0.8) -> bool:
        """检测内容循环（委托给 agent_loop_detection 模块）"""
        return detect_content_loop(contents, threshold)

    def _calculate_similarity(self, text1: str, text2: str) -> float:
        """计算两个文本的相似度（委托给 agent_loop_detection 模块）"""
        return calculate_similarity(text1, text2)

    def _has_repeated_patterns(self, contents: List[str]) -> bool:
        """检测是否有重复的句子或段落模式（委托给 agent_loop_detection 模块）"""
        return has_repeated_patterns(contents)

    def _collect_tool_messages(self) -> List[Dict[str, Any]]:
        """
        收集工具调用和执行的消息（用于前端展示）

        返回:
            工具消息列表，每个消息包含:
            - type: "tool_call" | "tool_result"
            - tool_name: 工具名称
            - params/result: 参数/结果
            - timestamp: 时间戳
        """
        if hasattr(self, "_tool_messages_list") and self._tool_messages_list:
            return list(self._tool_messages_list)
        return []

    async def _build_tools_for_llm(self) -> Optional[List[Dict]]:
        """聚合所有工具（委托给 ContextOrchestrator）"""
        return await self.context_orchestrator.build_tools_for_llm()

    async def _execute_text_tool_calls(self, reply: str, user_input: str) -> str:
        """解析回复中的文本工具调用并执行（委托给 ToolExecutor 多策略解析器）

        ⚠️ DEPRECATED: 此方法已废弃，请直接使用 tool_executor.execute_text_tool_calls()。
        """
        import warnings

        warnings.warn(
            "Agent._execute_text_tool_calls() is deprecated, use ToolExecutor directly",
            DeprecationWarning,
            stacklevel=2,
        )
        if not reply or not isinstance(reply, str):
            return reply
        try:
            return await self.tool_executor.execute_text_tool_calls(reply, user_input)
        except Exception as e:
            logger.debug("文本工具调用解析跳过: %s", e)
        return reply

    def _set_reasoning(self, reasoning: str):
        """设置当前思考过程（由 LLM 客户端调用）"""
        self._current_reasoning = reasoning

    async def shutdown(self) -> None:
        """Agent 关闭时的清理操作（委托给 agent_shutdown 模块）"""
        await shutdown_agent(self)

    def __repr__(self):
        return f"Agent(name='{self.config.name}', id='{self.config.agent_id}')"
