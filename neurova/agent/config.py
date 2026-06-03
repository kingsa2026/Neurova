"""
Agent 配置模块

从 agent_core.py 提取，包含：
- AgentConfig: Agent 配置类
- AgentLLMClient: Agent LLM 客户端包装
"""

import logging
from pathlib import Path
from typing import List, Dict, Optional, Any

from neurova.llm_client import LLMClient, LLMConfig

logger = logging.getLogger(__name__)


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
