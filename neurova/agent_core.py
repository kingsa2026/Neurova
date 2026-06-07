"""
Agent Core - Agent 核心循环
协调记忆检索、上下文构建、LLM调用、记忆存储等模块

D1 任务重构版本：
- Agent 通过 Router 接收消息，而不是绕过 Router
- 提供 process_message 统一入口，所有消息经过 Router 路由
- 保留 chat 方法用于底层对话生成
"""

import logging
import json
import time
from typing import List, Dict, Optional, Any
from datetime import datetime, UTC
from pathlib import Path

import sys

# 添加项目根目录到 sys.path (用于导入 agent.loops)
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from neurova.mem_core import MemCore
from neurova.context import ContextOrchestrator
from neurova.llm_client import LLMClient, LLMConfig
from neurova.router import MessageRouter, Message, MessageType, RouteResult
from neurova.skills.registry import SkillRegistry
from neurova.core.idle_tracker import IdleTimeTracker
from neurova.core.sleep_config_manager import SleepConfigManager
from neurova.skills.agent_skill_manager import AgentSkillManager  # will be migrated to evolution

# Neurova-Evocate: Neurova Hebb 记忆系统
try:
    from neurova.cognitive_layers.memory_layer.neuHebb_manager import NeuHebbManager
    from neurova.cognitive_layers.memory_layer.neurova_hebb import NeuHebbConfig
    NEUHEBB_AVAILABLE = True
except ImportError:
    NEUHEBB_AVAILABLE = False

# 认知图谱存储架构 — 一步到位替换
try:
    from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import CognitiveStorageEngine
    from neurova.cognitive_layers.memory_layer.unified_retriever import UnifiedRetriever
    from neurova.cognitive_layers.memory_layer.pattern_crystallizer import PatternCrystallizer
    from neurova.cognitive_layers.memory_layer.reasoning_trace_manager import ReasoningTraceManager
    COGNITIVE_GRAPH_AVAILABLE = True
except ImportError:
    COGNITIVE_GRAPH_AVAILABLE = False
    logging.warning("Cognitive Graph modules not available")

# P0: Phase 2+3 模块接线 — 序列挖掘 / 基因编程 / 生命周期 / NL合成 / DAG编排 / 工具市场
from neurova.evolution import (
    PatternMiner,
    ToolGeneticEngine,
    ToolLifecycleManager,
    NLToolSynthesizer,
)
from neurova.tool_layers import (
    ToolOrchestrator,
    ToolMarketplace,
    MarketplaceTool,
)

# P1: 提取的深度模块
from neurova.tool_executor import ToolExecutor
from neurova.post_chat_pipeline import PostChatPipeline

# P5: 对话管线（从 chat() 提取）
from neurova.agent.chat_pipeline import ChatPipeline, ChatContext

# P3: 内置工具注册器（替代 _init_file_operation_wrappers 的 15 个闭包）
from neurova.builtin_tools import BuiltinToolRegistry, get_builtin_tool_params

# Agent Loop 导入
try:
    from neurova.agent.loops.registry import find_agent_loop
    from neurova.agent.loops.base import BaseAgentLoop
    AGENT_LOOP_AVAILABLE = True
except ImportError:
    AGENT_LOOP_AVAILABLE = False
    logging.warning("Agent Loop system not available, will use legacy chat methods")

logger = logging.getLogger(__name__)


def debug_log(msg: str) -> None:
    """调试日志快捷函数"""
    logger.debug(msg)


from neurova.session_manager import get_session_manager
from neurova.core.trace_recorder import get_trajectory_recorder
from neurova.core.trace_models import TrajectoryEventType

__all__ = ["AgentConfig", "Agent"]

# ═══════════════════════════════════════════════════════════════
# Agent LLM 客户端：指定模型/路由 → 委托 MultiModelLLMClient
# ═══════════════════════════════════════════════════════════════

class AgentLLMClient:
    """Agent 的 LLM 路由客户端
    不持有 API Key，通过 LLM 路由层（MultiModelLLMClient）传递上下文。
    指定模型 ID 或 'auto' 让路由器自动选择。
    """
    def __init__(self, model: str = 'auto', provider_id: str = ''):
        self.model = model
        self.provider_id = provider_id
        # config 用于 OpenAILoop 兼容（hasattr 检查 temperature/max_tokens 等）
        self.config = type('Config', (), {
            'temperature': 0.7, 'max_tokens': 8192,
            'top_p': 0.9, 'frequency_penalty': 0.0,
            'model': model
        })()

    def _get_client(self):
        from neurova.llm.multi_model_client import get_multi_model_client
        return get_multi_model_client()

    def chat(self, messages, **kwargs):
        return self._get_client().chat(
            messages,
            model=self.model if self.model != 'auto' else None,
            provider_id=self.provider_id or None,
            **kwargs
        )

    def chat_stream(self, messages, **kwargs):
        return self._get_client().chat_stream(
            messages,
            model=self.model if self.model != 'auto' else None,
            provider_id=self.provider_id or None,
            **kwargs
        )

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
        max_tokens: int = 8192,
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
        
        # 活水上下文池配置
        enable_context_pool: bool = True,  # 是否启用活水上下文池
        enable_auto_tagging: bool = False,  # 是否启用自动标签生成
    ):
        self.name = name
        self.agent_id = agent_id

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

        logger.debug(f"Agent.__init__() 开始: {self.config.name} (ID: {self.config.agent_id})")

        # 加载身份和性格
        logger.debug("步骤1: 加载身份和性格...")
        self._load_identity()
        debug_log("步骤1: 完成")

        # 初始化模块 - 先初始化为 None，再根据配置决定是否启用
        logger.debug("步骤2: 初始化记忆模块...")
        self.memory_manager = None
        self.storage = None
        self.temperature_engine = None

        # P2: 初始化 MemCore 深度模块（保留兼容性）
        self.memory_agent = MemCore(self)
        # P2: 初始化 ContextOrchestrator 深度模块
        self.context_orchestrator = ContextOrchestrator(
            self,
            use_pool=self.config.enable_context_pool,
            auto_tag=self.config.enable_auto_tagging
        )

        # 认知图谱存储架构 — 一步到位替换
        self.cognitive_engine = None
        self.unified_retriever = None
        self.crystallizer = None
        self.trace_manager = None

        if self.config.enable_memory:
            logger.debug("步骤2.1: 调用 _init_memory_modules()...")
            self._init_memory_modules()
            logger.debug("步骤2.1: _init_memory_modules() 完成")
            # MoE 路由器初始化（在记忆模块之后）
            try:
                self.memory_agent.init_moe_router()
                debug_log("步骤2.2: MoE 路由器初始化完成")
            except Exception as e:
                logger.warning(f"MoE 路由器初始化失败，降级到普通检索: {e}")
            
            # 初始化认知图谱存储架构
            if COGNITIVE_GRAPH_AVAILABLE:
                try:
                    debug_log("步骤2.3: 初始化认知图谱存储架构...")
                    self._init_cognitive_graph()
                    debug_log("步骤2.3: 认知图谱初始化完成")
                except Exception as e:
                    logger.warning(f"认知图谱初始化失败: {e}")
        debug_log("步骤2: 完成")

        # Phase 5: 工作记忆和对话缓冲区由 MemCore 管理
        self.working_memory: Optional[WorkingMemoryAugmenter] = None
        self.conversation_buffer: Optional[ConversationMemoryBuffer] = None
        self.buffer_module: Optional[BufferModule] = None

        debug_log("步骤3: 创建上下文构建器和 LLM 客户端...")

        # P2: 委托给 ContextOrchestrator 初始化上下文系统
        self.context_orchestrator.init_context_system()
        # 使用 LLM 路由客户端（不直接持有 API Key，通过路由层传递上下文）
        self.llm_client = AgentLLMClient(
            model=self.config.llm_config.model if hasattr(self.config, 'llm_config') else 'auto',
            provider_id=getattr(self.config, 'llm_provider', '') or '',
        )
        logger.debug("步骤3: 完成")

        # 对话历史
        self.conversation_history: List[Dict[str, str]] = []

        # 当前用户输入（供 ToolMemory 回调使用）
        self._current_user_input: Optional[str] = None

        # 轨迹记录（用于调试和回放）
        self._current_trace_id: str = ""  # 当前轨迹 ID
        self._trajectory_recorder = get_trajectory_recorder()

        # Session管理器 - 用于备份对话到文件
        self.session_manager = get_session_manager()

        # Router 集成
        self._router: Optional[MessageRouter] = None
        self._skill_registry: Optional[SkillRegistry] = None

        # 睡眠模块集成
        self.sleep_config_manager = SleepConfigManager()
        self.idle_tracker = IdleTimeTracker()

        # 技能管理器（任务拆解 + 主动技能获取）
        self.skill_manager: Optional[AgentSkillManager] = None

        # 技能打包器（自动打包）
        self.skill_packer: Optional[Any] = None  # SkillPacker type

        # ToolMemory 集成：闭环学习系统（Neurova 2.0 核心特性）
        # 工具运用 → 工具记忆 → 经验总结 → 相似问题检索 → 工具运用
        self.tool_memory: Optional[ToolMemoryIntegration] = None
        if self.memory_manager:
            from neurova.cognitive_layers.memory_layer.muscle_memory import MuscleMemory
            from neurova.cognitive_layers.memory_layer.tool_memory_integration import ToolMemoryIntegration
            # 初始化肌肉记忆层
            muscle_memory = MuscleMemory(
                agent_id=self.config.agent_id,
                storage_dir=str(self.config.workspace_path / "memory" / "muscle_memory"),
            )

            from neurova.cognitive_layers.memory_layer.tool_memory_integration import ToolMemoryIntegration
            # 初始化ToolMemoryIntegration，接入肌肉记忆
            self.tool_memory = ToolMemoryIntegration(
                memory_layer=self.memory_manager,
                muscle_memory=muscle_memory,  # 关键：传入肌肉记忆实例
                confidence_threshold=0.8,
                temperature_threshold=30.0,
            )
            logger.info(f"Agent {self.config.name}: ToolMemory（闭环学习）+ 肌肉记忆已启用")

        # Neurova 统一记忆检索引擎（多维融合 + 意图钻取）
        self.recall_engine: Optional[NeurovaRecallEngine] = None

        # Neurova-Evocate: Neurova Hebb 记忆系统（结构化推理记忆）
        self.neuHebb_manager = None
        if NEUHEBB_AVAILABLE and self.config.enable_memory:
            try:
                hebb_config = NeuHebbConfig(
                    persistence_path=str(self.config.workspace_path / "data" / "neurova_hebbs"),
                    enabled=True,
                )
                self.neuHebb_manager = NeuHebbManager(config=hebb_config)
                logger.info(f"Agent {self.config.name}: Neurova-Evocate (NeuHebbManager) 已启用")
            except Exception as e:
                logger.warning(f"Neurova-Evocate 初始化失败: {e}")

        # TTS 管理器（语音合成）
        self.tts_manager = None
        if self.config.enable_tts:
            try:
                from neurova.tts.manager import TTSManager, TTSConfig

                tts_config = TTSConfig(
                    engine=self.config.tts_engine,
                    voice=self.config.tts_voice,
                    moss_auto_download=self.config.tts_auto_download,
                    model_cache_dir=str(self.config.workspace_path / "models" / "tts"),
                )

                self.tts_manager = TTSManager(tts_config)
                logger.info(f"Agent {self.config.name}: TTS管理器已初始化 (engine={self.config.tts_engine})")

            except Exception as e:
                logger.warning(f"TTS管理器初始化失败: {e}")

        # 审批管理器（危险命令审批）
        self.approval_manager = None
        try:
            from neurova.security.approval_manager import ApprovalManager, ApprovalLevel

            self.approval_manager = ApprovalManager(
                workspace_path=str(self.config.workspace_path),
                approval_level=ApprovalLevel.SMART,  # 默认智能模式
            )
            logger.info(f"Agent {self.config.name}: 审批管理器已初始化")

        except Exception as e:
            logger.warning(f"审批管理器初始化失败: {e}")

        # ========== 认知能力、进化能力、经验总结接入 ==========

        # 1. 认知能力 (GrowthAnalyzer)
        self.growth_analyzer = None
        if self.config.enable_cognitive_capabilities and self.memory_manager:
            try:
                from neurova.cognitive_layers.growth_layer.analyzer import GrowthAnalyzer

                # GrowthAnalyzer.__init__() 只接受 storage_path 参数
                growth_storage_path = str(self.config.workspace_path / "memory" / "growth")
                self.growth_analyzer = GrowthAnalyzer(
                    storage_path=growth_storage_path,
                )
                logger.info(f"Agent {self.config.name}: 认知能力(GrowthAnalyzer)已初始化")

            except Exception as e:
                logger.warning(f"认知能力初始化失败: {e}")

        # 2. 统一进化引擎 (EvolutionOrchestrator v2.0)
        # 合并了 SkillsEvolutionEngine + ExperienceCaller + AdaptiveToolWeights
        # 提供: 工具权重自适应 + 经验反哺 + 经验检索 + 统计报告
        self.evolution = None
        if self.config.enable_evolution or self.config.enable_experience_summary:
            try:
                from neurova.evolution import EvolutionOrchestrator

                self.evolution = EvolutionOrchestrator()

                # 从 skill_registry 注册已有工具
                if self._skill_registry:
                    skill_names = [s.name for s in self._skill_registry.list_skills()]
                    self.evolution.register_tools(skill_names)

                # 将进化引擎的权重和生命周期同步到 ToolMemoryIntegration
                if hasattr(self, 'tool_memory') and self.tool_memory:
                    self.tool_memory.tool_weights = self.evolution.tool_weights
                    self.tool_memory.tool_lifecycle = self.tool_lifecycle
                    logger.info(f"Agent {self.config.name}: ToolMemoryIntegration 已同步进化引擎权重和生命周期")

                logger.info(
                    f"Agent {self.config.name}: 统一进化引擎(EvolutionOrchestrator)已初始化 "
                    f"(evolution={self.config.enable_evolution}, "
                    f"experience={self.config.enable_experience_summary})"
                )

            except Exception as e:
                logger.warning(f"统一进化引擎初始化失败: {e}")

        # 向后兼容别名 (用于 API 端点 get_skill_modules())
        self.evolution_engine = self.evolution  # type: ignore

        # ===== v1.0.0 新增: 工具路由器 + 模型适配器 =====
        # P3: 使用 BuiltinToolRegistry 替代内联的 15 个闭包
        self._builtin_tools: Optional[BuiltinToolRegistry] = None
        try:
            from neurova.computer_use import get_computer_use_manager
            computer_use = get_computer_use_manager()
            self._builtin_tools = BuiltinToolRegistry(self, computer_use)
            logger.info(f"Agent {self.config.name}: BuiltinToolRegistry 已初始化（15个工具）")
        except Exception as e:
            logger.warning(f"BuiltinToolRegistry 初始化失败: {e}")

        # ToolRouter v1.0.0 — 统一工具路由（内置 + Skill + MCP）
        self.tool_router = None
        try:
            from neurova.tool_layers import ToolRouter
            self.tool_router = ToolRouter()
            self.tool_router.set_skill_manager(self.skill_registry)

            # 注册内置工具（通过 BuiltinToolRegistry）
            if self._builtin_tools:
                self.tool_router.register_builtin_batch(self._builtin_tools.get_all_tools())
            logger.info(f"Agent {self.config.name}: ToolRouter v1.0.0 已初始化（含文件操作 + Computer Use 工具）")
        except Exception as e:
            logger.warning(f"ToolRouter 初始化失败: {e}")

        # ModelAdapter v1.0.0 — 多 LLM 自适应推理循环
        self.model_adapter = None
        try:
            from neurova.cognitive_layers.model_adapter import ModelAdapterRegistry
            # 从 config.llm_config.model 获取模型名称
            model_name = self.config.llm_config.model if self.config.llm_config else ''
            model_name = model_name or 'deepseek-v4-flash'
            self.model_adapter = ModelAdapterRegistry.get_adapter(model_name)
            logger.info(
                f"Agent {self.config.name}: 模型适配器={self.model_adapter.__class__.__name__}"
            )
        except Exception as e:
            logger.warning(f"模型适配器初始化失败: {e}")

        # ===== P0: Phase 2+3 模块初始化 =====
        # 1. PatternMiner + ToolGeneticEngine — 统一使用 EvolutionOrchestrator 的实例（避免双重实例）
        self.pattern_miner: Optional[PatternMiner] = None
        self.genetic_engine: Optional[ToolGeneticEngine] = None
        if self.evolution:
            self.pattern_miner = self.evolution.pattern_miner
            self.genetic_engine = self.evolution.genetic_engine
            logger.info(f"Agent {self.config.name}: PatternMiner + ToolGeneticEngine 从 EvolutionOrchestrator 统一获取")

        # 3. ToolLifecycleManager — 工具生命周期管理
        self.tool_lifecycle: Optional[ToolLifecycleManager] = None
        try:
            self.tool_lifecycle = ToolLifecycleManager()
            logger.info(f"Agent {self.config.name}: ToolLifecycleManager (生命周期) 已初始化")
        except Exception as e:
            logger.warning(f"ToolLifecycleManager 初始化失败: {e}")

        # 4. NLToolSynthesizer — 自然语言工具合成
        self.tool_synthesizer: Optional[NLToolSynthesizer] = None
        if self.config.enable_evolution:
            try:
                self.tool_synthesizer = NLToolSynthesizer(
                    pattern_miner=self.pattern_miner,
                )
                logger.info(f"Agent {self.config.name}: NLToolSynthesizer (NL合成) 已初始化")
            except Exception as e:
                logger.warning(f"NLToolSynthesizer 初始化失败: {e}")

        # 5. ToolOrchestrator — DAG 工具编排器
        self.tool_orchestrator: Optional[ToolOrchestrator] = None
        try:
            self.tool_orchestrator = ToolOrchestrator()
            # 注册工具执行器：委托给 tool_router + skill_registry
            async def _orchestrator_executor(tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
                # 1. 尝试 SkillRegistry
                if self._skill_registry:
                    skill = self._skill_registry.get_skill(tool_name)
                    if skill:
                        result = self._skill_registry.execute_skill(tool_name, **params)
                        if result.success:
                            return {"success": True, "data": result.data}
                        return {"success": False, "error": result.error}
                # 2. ToolRouter fallback
                if self.tool_router:
                    router_result = await self.tool_router.execute(
                        tool_name=tool_name,
                        params=params,
                        agent_id=self.config.agent_id,
                        user_id=getattr(self.config, 'user_id', 'default'),
                    )
                    if router_result and router_result.success:
                        return {"success": True, "data": router_result.result}
                    error = getattr(router_result, 'error', None) if router_result else "no result"
                    return {"success": False, "error": str(error) if error else "unknown error"}
                return {"success": False, "error": f"工具 '{tool_name}' 未找到"}
            self.tool_orchestrator.set_executor(_orchestrator_executor)
            logger.info(f"Agent {self.config.name}: ToolOrchestrator (DAG编排) 已初始化")
        except Exception as e:
            logger.warning(f"ToolOrchestrator 初始化失败: {e}")

        # 6. ToolMarketplace — 工具市场
        self.tool_marketplace: Optional[ToolMarketplace] = None
        try:
            self.tool_marketplace = ToolMarketplace()
            logger.info(f"Agent {self.config.name}: ToolMarketplace (工具市场) 已初始化")
        except Exception as e:
            logger.warning(f"ToolMarketplace 初始化失败: {e}")

        # P1: 提取的深度模块初始化
        # 7. ToolExecutor — 统一工具执行器（代理 agent_core 中的工具执行方法）
        self.tool_executor = ToolExecutor(self)

        # 8. PostChatPipeline — 对话后处理管线（代理步骤 6-9）
        self.post_chat_pipeline = PostChatPipeline(self)

        # 9. ChatPipeline — 对话流程管线（从 chat() 提取）
        self.chat_pipeline = ChatPipeline(self)

        logger.info(f"Agent {self.config.name} 初始化完成")

        # ===== 修复：从 llm_provider 加载 API Key 到 llm_config =====
        # 先确保 llm_config 不为 None
        logger.info(f"[DEBUG] llm_provider={self.config.llm_provider}, llm_config={self.config.llm_config}")
        if self.config.llm_config is None:
            self.config.llm_config = LLMConfig()
            logger.info("[DEBUG] llm_config 为 None，已创建默认 LLMConfig")

        if self.config.llm_provider:
            try:
                from neurova.llm.provider_manager import get_provider_manager
                pm = get_provider_manager()
                provider = pm.get_provider(self.config.llm_provider)
                logger.debug(f"[DEBUG] provider={provider.name if provider else None}")
                if provider and provider.api_key:
                    self.config.llm_config.api_key = provider.api_key
                    self.config.llm_config.base_url = provider.base_url
                    masked = provider.masked_api_key() if hasattr(provider, 'masked_api_key') else "***"
                    logger.info(f"已从服务商 {provider.name} 加载 API Key ({masked})")
                elif provider and not provider.api_key:
                    logger.warning(
                        f"服务商 {provider.name} 的 API Key 为空！"
                        f"请通过 UI 设置该服务商的 API Key。"
                    )
            except Exception as e:
                logger.warning(f"从 llm_provider 加载配置失败: {e}")
        else:
            logger.warning("[DEBUG] llm_provider 为空，无法加载 API Key")

        # ===== Agent Loop 初始化 (v5.0) =====
        self.loop = None
        self._init_agent_loop()

    def _init_file_operation_wrappers(self):
        """P3: 委托给 BuiltinToolRegistry（已移至 __init__ 中直接初始化）"""
        pass

    def _init_agent_loop(self):
        """
        初始化 Agent Loop (v5.0)

        根据配置的模型自动选择合适的 Loop。
        如果 Agent Loop 系统不可用，则使用传统方法。
        """
        if not AGENT_LOOP_AVAILABLE:
            logger.warning("Agent Loop system not available, using legacy chat methods")
            return

        try:
            # 获取模型名称
            model_name = self.config.llm_config.model

            # 查找合适的 Loop 类
            loop_class = find_agent_loop(model_name)

            if loop_class:
                self.loop = loop_class(self)
                logger.info(
                    f"Agent Loop initialized: {loop_class.__name__} "
                    f"(model={model_name})"
                )
            else:
                logger.warning(f"No suitable Loop found for model: {model_name}")

        except Exception as e:
            logger.warning(f"Agent Loop initialization failed: {e}")
            self.loop = None

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

        # 更新 config 中的模型名
        self.config.llm_config.model = model_name

        # 查找新模型对应的 Loop 类
        loop_class = find_agent_loop(model_name)

        if loop_class:
            old_loop_name = type(self.loop).__name__ if self.loop else "None"
            try:
                new_loop = loop_class(self)
                self.loop = new_loop
                logger.info(
                    f"Agent Loop rebuilt: {old_loop_name} → {loop_class.__name__} "
                    f"(model={model_name})"
                )
                return True
            except Exception as e:
                logger.error(
                    f"Agent Loop 实例化失败: {old_loop_name} → {loop_class.__name__}: {e}"
                )
                # 保留旧 Loop，不覆盖
                return False
        else:
            logger.warning(f"No suitable Loop found for model: {model_name}")
            return False

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
        logger.info(f"处理多模态消息: media_type={media_type}, model={model}")

        # 1. 将 media_type 映射为 LLM RequestType，使用 LLMRouter 选择模型
        try:
            from neurova.llm.llm_router import (
                select_model_for_request,
                RequestType as LLMRequestType,
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
                    logger.info(
                        f"LLMRouter 为 {media_type} 选择模型: "
                        f"{selection.provider_name}/{selection.model}"
                    )

            # 如果指定了模型且与当前不同，热切换
            if model and model != getattr(self.config.llm_config, 'model', None):
                logger.info(f"多模态路由：热切换模型到 {model}")
                self.rebuild_loop(model)

        except Exception as e:
            logger.warning(f"多模态模型选择失败，使用当前模型: {e}")

        # 2. 构建多模态上下文描述
        media_url = metadata.get("media_url", "")
        filename = metadata.get("filename", "")
        mime_type = metadata.get("mime_type", "")

        media_descriptions = {
            "image": f"[用户发送了一张图片{': ' + filename if filename else ''}]",
            "voice": f"[用户发送了一段语音消息{': ' + filename if filename else ''}]",
            "video": f"[用户发送了一个视频{': ' + filename if filename else ''}]",
            "document": f"[用户发送了一个文档{': ' + filename if filename else ''}]",
        }
        media_desc = media_descriptions.get(media_type, f"[用户发送了媒体文件: {media_type}]")

        # 3. 将媒体描述注入用户输入，调用 chat()
        enriched_input = f"{media_desc}\n{content}" if content else media_desc

        # 附加原始 metadata（含 attachment_ids 供附件管理器使用）
        chat_metadata = dict(metadata)

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
        logger.info(f"Agent {self.config.name} 已绑定 Router")

    @property
    def skill_registry(self) -> Optional[SkillRegistry]:
        """获取 Skill 注册中心"""
        return self._skill_registry

    @skill_registry.setter
    def skill_registry(self, value: SkillRegistry):
        """设置 Skill 注册中心"""
        self._skill_registry = value
        logger.info(f"Agent {self.config.name} 已绑定 SkillRegistry")

    def _load_identity(self):
        """加载 Agent 身份和性格"""
        workspace = self.config.workspace_path / "workspace" / "memory"

        # 加载 soul.md
        soul_path = workspace / "soul.md"
        if soul_path.exists():
            self.soul = soul_path.read_text(encoding="utf-8")
            logger.info(f"已加载身份文件: {soul_path}")
        else:
            self.soul = f"你是 {self.config.name}，一个友好的 AI 助手。"
            logger.warning(f"未找到身份文件，使用默认身份")

        # 加载 personality.md
        personality_path = workspace / "personality.md"
        if personality_path.exists():
            self.personality = personality_path.read_text(encoding="utf-8")
            logger.info(f"已加载性格文件: {personality_path}")
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
            if hasattr(self, 'idle_tracker') and self.idle_tracker:
                self.idle_tracker.set_sleep_consolidation(self.sleep_consolidation)
                self.idle_tracker.set_memory_manager(self.memory_manager)
            logger.info(f"Agent {self.config.name}: SleepConsolidation（睡眠整理）已初始化")
        except Exception as e:
            logger.warning(f"SleepConsolidation 初始化失败: {e}")
            self.sleep_consolidation = None

        logger.info(f"记忆系统模块初始化成功: agent_id={self.config.agent_id}, neuser_id={neuser_id}, user_id={user_id}")

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
        logger.info(f"CognitiveStorageEngine 初始化完成: {data_dir}")
        
        # 2. 初始化 UnifiedRetriever（包装旧检索器）
        moe_router = getattr(self.memory_agent, 'moe_router', None)
        recall_engine = getattr(self.memory_agent, 'recall_engine', None)
        hebb_manager = getattr(self.memory_agent, 'hebb_manager', None)
        
        self.unified_retriever = UnifiedRetriever(
            engine=self.cognitive_engine,
            moe_router=moe_router,
            recall_engine=recall_engine,
            hebb_manager=hebb_manager,
        )
        logger.info("UnifiedRetriever 初始化完成")
        
        # 3. 初始化 PatternCrystallizer
        evolution = getattr(self, 'evolution', None)
        self.crystallizer = PatternCrystallizer(
            engine=self.cognitive_engine,
            evolution_orchestrator=evolution,
        )
        logger.info("PatternCrystallizer 初始化完成")
        
        # 将 crystallizer 注入到 EvolutionOrchestrator
        if evolution and hasattr(evolution, 'crystallizer'):
            evolution.crystallizer = self.crystallizer
            logger.info("PatternCrystallizer 已注入到 EvolutionOrchestrator")
        
        # 4. 初始化 ReasoningTraceManager
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

        # 先初始化 SkillRegistry
        if not self._skill_registry:
            self._skill_registry = create_default_skills(
                memory_manager=self.memory_manager
            )

        # 注册 ToolMemory 回调：Skill 成功执行后记录到 ToolMemory
        if self.tool_memory and self._skill_registry:
            self._skill_registry.register_event_callback(
                SkillEvent.POST_EXECUTE,
                self._on_skill_post_execute,
            )
            logger.info(f"Agent {self.config.name}: ToolMemory 回调已注册（Skill成功执行时记录）")

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
            logger.info(f"Agent {self.config.name} 的 SkillManager 已初始化")

        # 初始化技能自动构建器 (AutoSkillBuilder from evolution)
        # 替换旧的 SkillPacker，统一在 evolution 模块中
        if self.config.enable_skill_packer:
            try:
                from neurova.evolution import AutoSkillBuilder

                self.skill_packer = AutoSkillBuilder(
                    min_occurrences=3,
                    min_success_rate=0.7,
                )
                logger.info(f"Agent {self.config.name}: AutoSkillBuilder 已初始化")

            except ImportError as e:
                logger.warning(f"AutoSkillBuilder 初始化失败: {e}")

        logger.info(f"Agent {self.config.name} 的 Router 已初始化")
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

            self._on_tool_executed(
                tool_name=skill.name,
                params=tool_params,
                user_input=problem_text,
                success=True,
                tool_source="skill_system",
                execution_time=result.execution_time,
            )
            logger.info(f"ToolMemory 记录成功技能执行: {skill.name}")
        except Exception as e:
            logger.warning(f"ToolMemory 记录失败: {e}")

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

        logger.info(f"Agent {self.config.name} 收到消息: {content[:50]}...")

        # 通过 Router 路由（现在是异步的）
        result = await self._router.route(message)

        logger.info(f"消息路由完成: {result.message_type.value}, success={result.success}")

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
        logger.info(f"收到用户输入: {user_input[:50]}...")
        ctx = ChatContext(
            user_input=user_input,
            stream=stream,
            save_memory=save_memory,
            session_id=session_id,
            metadata=metadata,
            enable_tts=enable_tts,
        )
        return await self.chat_pipeline.execute(ctx)

    def _execute_tool_from_memory(
        self,
        tool_memory_result: Dict[str, Any],
        user_input: str,
    ) -> Optional[Dict[str, Any]]:
        """P1: 委托给 ToolExecutor"""
        return self.tool_executor.execute_from_memory(tool_memory_result, user_input)

    async def _execute_tool_from_memory_async(
        self,
        tool_memory_result: Dict[str, Any],
        user_input: str,
    ) -> Dict[str, Any]:
        """肌肉记忆工具异步执行（支持超时控制）

        委托给 ToolExecutor.execute_from_memory_async()。

        Returns:
            {"status": "success"|"failure", "result": ..., "tool_name": ..., "error": ...}
        """
        return await self.tool_executor.execute_from_memory_async(
            tool_memory_result, user_input
        )

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
            muscle = getattr(self.tool_memory, 'muscle_memory', None) if self.tool_memory else None
            if muscle and hasattr(muscle, 'items'):
                for key, item in muscle.items.items():
                    if hasattr(item, 'tool_name') and item.tool_name == tool_name:
                        item.consecutive_success = 0
                        logger.info(f"📉 肌肉记忆降级: {tool_name} consecutive_success 重置为 0")
                        break
        except Exception as e:
            logger.debug(f"肌肉记忆降级记录跳过: {e}")

        # 2. 写入反思日志
        try:
            glog = getattr(self, 'growth_log_manager', None)
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
                logger.info(f"📝 已记录工具失败教训: {tool_name} (反思ID: {entry.id})")
        except Exception as e:
            logger.debug(f"反思日志记录跳过: {e}")

    def _on_tool_executed(
        self,
        tool_name: str,
        params: Dict[str, Any],
        user_input: str,
        success: bool,
        tool_source: str = "skill_system",
        execution_time: float = 0.0,
    ):
        """P1: 委托给 ToolExecutor"""
        self.tool_executor.on_tool_executed(
            tool_name=tool_name,
            params=params,
            user_input=user_input,
            success=success,
            tool_source=tool_source,
            execution_time=execution_time,
        )

    def _execute_skill_tool(
        self,
        skill_name: str,
        skill_params: Dict,
        user_input: str,
    ) -> Optional[Dict[str, Any]]:
        """P1: 委托给 ToolExecutor"""
        return self.tool_executor.execute_skill_tool(skill_name, skill_params, user_input)

    def _execute_cli_tool(
        self,
        tool_name: str,
        tool_params: Dict,
        user_input: str,
    ) -> Optional[Dict[str, Any]]:
        """P1: 委托给 ToolExecutor"""
        return self.tool_executor.execute_cli_tool(tool_name, tool_params, user_input)

    async def _chat_normal(
        self,
        user_input: str,
        context: List[Dict],
        save_memory: bool,
    ) -> str:
        """
        普通对话模式

        ⚠️ DEPRECATED (v5.0): 此方法已废弃，请使用 Agent Loop 系统。

        新的代码应该通过 `self.loop.predict_step()` 调用 LLM。
        此方法仅作为 Agent Loop 不可用时的 fallback。
        """
        import warnings
        warnings.warn(
            "Agent._chat_normal() is deprecated, use Agent Loop instead",
            DeprecationWarning,
            stacklevel=2
        )
        logger.warning("Using deprecated _chat_normal(), please migrate to Agent Loop")

        response = await self.llm_client.chat(context)
        # MultiModelLLMClient.chat() 返回 dict: {success, response, error, ...}
        if isinstance(response, dict):
            if response.get('success'):
                raw = response.get('response', '')
                # response 可能是字符串、LLMResponse 对象、或 dict
                if hasattr(raw, 'content'):
                    reply = raw.content
                elif isinstance(raw, dict):
                    reply = raw.get('content', raw.get('text', str(raw)))
                else:
                    reply = str(raw)
            else:
                reply = f"[LLM Error] {response.get('error', 'Unknown error')}"
        elif hasattr(response, 'content'):
            reply = response.content
        else:
            reply = str(response)

        # 更新对话历史
        self._update_history(user_input, reply)

        # 保存记忆
        if save_memory and self.memory_manager:
            self._save_conversation_memory(user_input, reply)

        # 更新记忆温度
        if self.temperature_engine:
            self._update_memory_temperature()

        return reply

    async def _chat_stream(
        self,
        user_input: str,
        context: List[Dict],
        save_memory: bool,
    ) -> str:
        """
        流式对话模式

        ⚠️ DEPRECATED (v5.0): 此方法已废弃，请使用 Agent Loop 系统。

        新的代码应该通过 `self.loop.predict_step()` 调用 LLM。
        此方法仅作为 Agent Loop 不可用时的 fallback。
        """
        import warnings
        warnings.warn(
            "Agent._chat_stream() is deprecated, use Agent Loop instead",
            DeprecationWarning,
            stacklevel=2
        )
        logger.warning("Using deprecated _chat_stream(), please migrate to Agent Loop")

        reply_parts = []

        async for chunk in self.llm_client.chat_stream(context):
            reply_parts.append(chunk)
            logger.debug(chunk)

        reply = "".join(reply_parts)

        # 更新对话历史
        self._update_history(user_input, reply)

        # 保存记忆
        if save_memory and self.memory_manager:
            self._save_conversation_memory(user_input, reply)

        # 更新记忆温度
        if self.temperature_engine:
            self._update_memory_temperature()

        return reply

    def _get_builtin_tool_params(self, tool_name: str) -> Dict[str, Any]:
        """P3: 委托给 builtin_tools 模块"""
        return get_builtin_tool_params(tool_name)

    async def _get_tools_description(self) -> str:
        """获取工具描述文本（委托给 ContextOrchestrator）"""
        return await self.context_orchestrator.get_tools_description()

    def _build_system_prompt(self, tools_desc: str = "") -> str:
        """构建系统提示（委托给 ContextOrchestrator）"""
        return self.context_orchestrator.build_system_prompt(tools_desc)

    def _update_history(self, user_input: str, reply: str):
        """更新对话历史（委托给 MemCore）"""
        self.memory_agent.update_history(user_input, reply)

    def _save_conversation_memory(self, user_input: str, reply: str):
        """保存对话记忆（委托给 MemCore）"""
        self.memory_agent.save_conversation_memory(user_input, reply)

    def _save_to_session(self, user_input: str, reply: str, session_id: str = None, metadata: Optional[Dict[str, Any]] = None, assistant_metadata: Optional[Dict[str, Any]] = None) -> str:
        """保存对话到session文件（委托给 MemCore）"""
        return self.memory_agent.save_to_session(user_input, reply, session_id, metadata, assistant_metadata)

    def _update_memory_temperature(self):
        """更新记忆温度（委托给 MemCore）"""
        try:
            # update_memory_temperature 需要 memory_id，跳过批量更新
            pass
        except Exception:
            pass

    def get_memory_stats(self) -> Dict[str, Any]:
        """获取记忆统计信息（委托给 MemCore）"""
        return self.memory_agent.get_memory_stats()

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
        """
        检测内容循环

        通过比较最近 N 次内容的相似度，判断是否陷入循环。
        使用简单的字符级相似度计算，避免复杂的 NLP 处理。

        Args:
            contents: 最近的内容列表
            threshold: 相似度阈值，超过此值认为是循环

        Returns:
            True 表示检测到循环，False 表示未检测到
        """
        if len(contents) < 2:
            return False

        # 计算相邻内容的相似度
        similarities = []
        for i in range(1, len(contents)):
            prev = contents[i-1]
            curr = contents[i]

            # 简单的字符级相似度计算
            # 使用最长公共子序列的简化版本
            similarity = self._calculate_similarity(prev, curr)
            similarities.append(similarity)

        # 如果所有相邻内容的相似度都超过阈值，认为是循环
        if similarities and all(s > threshold for s in similarities):
            return True

        # 检查是否有重复的句子或段落
        if self._has_repeated_patterns(contents):
            return True

        return False

    def _calculate_similarity(self, text1: str, text2: str) -> float:
        """
        计算两个文本的相似度

        使用简化的字符级相似度计算，基于共同字符的比例。
        """
        if not text1 or not text2:
            return 0.0

        # 转换为小写并去除标点符号
        import re
        clean1 = re.sub(r'[^\w\s]', '', text1.lower())
        clean2 = re.sub(r'[^\w\s]', '', text2.lower())

        # 计算共同字符数
        set1 = set(clean1)
        set2 = set(clean2)

        if not set1 or not set2:
            return 0.0

        intersection = len(set1.intersection(set2))
        union = len(set1.union(set2))

        return intersection / union if union > 0 else 0.0

    def _has_repeated_patterns(self, contents: List[str]) -> bool:
        """
        检测是否有重复的句子或段落模式

        将内容分割成句子，检查是否有重复的句子序列。
        """
        import re

        # 将每个内容分割成句子
        all_sentences = []
        for content in contents:
            # 简单的句子分割（按句号、问号、感叹号）
            sentences = re.split(r'[。！？.!?]', content)
            sentences = [s.strip() for s in sentences if s.strip()]
            all_sentences.extend(sentences)

        # 检查是否有重复的句子
        if len(all_sentences) > 3:
            # 检查最后几个句子是否与前面的句子重复
            recent_sentences = all_sentences[-3:]
            earlier_sentences = all_sentences[:-3]

            for recent in recent_sentences:
                if len(recent) > 20:  # 只检查长度足够的句子
                    for earlier in earlier_sentences:
                        # 计算句子相似度
                        similarity = self._calculate_similarity(recent, earlier)
                        if similarity > 0.9:  # 句子相似度阈值更高
                            return True

        return False

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
        if hasattr(self, '_tool_messages_list') and self._tool_messages_list:
            return list(self._tool_messages_list)
        return []

    async def _build_tools_for_llm(self) -> Optional[List[Dict]]:
        """聚合所有工具（委托给 ContextOrchestrator）"""
        return await self.context_orchestrator.build_tools_for_llm()

    async def _execute_text_tool_calls(self, reply: str, user_input: str) -> str:
        """P1: 解析回复中的文本工具调用并执行"""
        if not reply or not isinstance(reply, str):
            return reply
        try:
            # 尝试解析回复中的工具调用 JSON
            tool_calls = self._parse_tool_calls_from_text(reply)
            if tool_calls:
                results = await self.tool_executor.execute_text_tool_calls(tool_calls)
                if results:
                    # 将工具结果附加到回复
                    tool_summary = "\n".join(
                        f"[Tool: {r.get('name', '?')}] {json.dumps(r.get('result', r.get('error', '')), ensure_ascii=False)}"
                        for r in results if r.get('success') or r.get('error')
                    )
                    if tool_summary:
                        reply = reply + "\n\n" + tool_summary
        except Exception as e:
            logger.debug(f"文本工具调用解析跳过: {e}")
        return reply

    def _parse_tool_calls_from_text(self, text: str) -> List[Dict]:
        """从文本中解析工具调用（降级模式：LLM 不支持 function calling 时）"""
        tool_calls = []
        # 匹配 ```json ... ``` 块中的工具调用
        import re
        json_blocks = re.findall(r'```json\s*(.*?)\s*```', text, re.DOTALL)
        for block in json_blocks:
            try:
                data = json.loads(block)
                if isinstance(data, dict) and "function" in data:
                    tool_calls.append(data)
                elif isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and "function" in item:
                            tool_calls.append(item)
            except json.JSONDecodeError:
                continue
        return tool_calls

    def _set_reasoning(self, reasoning: str):
        """设置当前思考过程（由 LLM 客户端调用）"""
        self._current_reasoning = reasoning

    async def shutdown(self) -> None:
        """Agent 关闭时的清理操作

        触发睡眠整理、刷新缓冲等。
        """
        logger.info(f"Agent {self.config.name} 正在关闭...")

        # Phase 10: 触发睡眠整理
        sleep_consolidation = getattr(self, 'sleep_consolidation', None)
        if sleep_consolidation and self.memory_manager:
            try:
                # 获取所有记忆进行整理
                all_memories = self.memory_manager.recall(query="", limit=1000)
                if all_memories:
                    # 转换Dict为MemoryRecord
                    from neurova.cognitive_layers.memory_layer.sleep import MemoryRecord
                    memory_records = [MemoryRecord.from_dict(m) for m in all_memories]
                    result = sleep_consolidation.run_sleep_cycle(memories=memory_records)
                    logger.info(f"💤 睡眠整理完成: {result}")
            except Exception as e:
                logger.warning(f"睡眠整理失败: {e}")

        # 刷新对话历史缓冲（如果使用 ConversationBuffer）
        conversation_buffer = getattr(self, '_conversation_buffer', None)
        if conversation_buffer:
            try:
                await conversation_buffer.flush()
                logger.debug("对话缓冲已刷新")
            except Exception as e:
                logger.warning(f"对话缓冲刷新失败: {e}")

        logger.info(f"Agent {self.config.name} 关闭完成")

    def __repr__(self):
        return f"Agent(name='{self.config.name}', id='{self.config.agent_id}')"
