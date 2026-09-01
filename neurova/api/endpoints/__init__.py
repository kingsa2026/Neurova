# neurova.api.endpoints 包
# 从各端点模块统一导出

from neurova.core.logger import get_logger
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter

logger = get_logger(__name__)

# 创建顶层 router
router = APIRouter()
evolution_router = APIRouter()
rag_router = APIRouter()

# ACP 消息协议路由（真实实现，见 acp_api.py）
from neurova.api.endpoints.acp_api import router as acp_router  # noqa: E402

# 全局状态（由 app.py 初始化时设置）
_app_state: Optional[Dict[str, Any]] = None


def set_app_state(state: Dict[str, Any]) -> None:
    global _app_state
    _app_state = state


def get_app_state() -> Optional[Dict[str, Any]]:
    """获取全局应用状态"""
    return _app_state


def get_startup_manager():
    """获取启动管理器"""
    if _app_state:
        return _app_state.get("startup_manager")
    from neurova.core.startup_manager import get_startup_manager as _get

    return _get()


def get_health_checker():
    """获取健康检查器"""
    if _app_state:
        return _app_state.get("health_checker")
    from neurova.core.health_checker import get_health_checker as _get

    return _get()


def get_llm_client():
    """获取 LLM 客户端"""
    if _app_state:
        return _app_state.get("llm_client")
    return None


def get_provider_manager():
    """获取 LLM Provider 管理器"""
    if _app_state:
        return _app_state.get("provider_manager")
    return None


def get_agent_instance(agent_id: str = "default"):
    """获取 Agent 实例"""
    if _app_state:
        agents = _app_state.get("agents", {})
        # 如果 agent_id 为空，使用默认 agent
        if not agent_id:
            agent_id = "default"
        return agents.get(agent_id)
    return None


def init_default_user():
    """初始化默认用户"""
    try:
        from neurova.api.auth import _load_or_create_secret_key

        _load_or_create_secret_key()
    except Exception as e:
        logger.warning("Failed to init default user: %s", e)


def load_agents_config():
    """加载 Agent 配置"""
    config_path = Path("agents.json")
    if config_path.exists():
        try:
            import json

            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning("Failed to load agents config: %s", e)
    return {}


def startup_version_check():
    """版本检查"""
    import sys

    python_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    logger.info("Python version: %s", python_version)
    if sys.version_info < (3, 10):
        logger.warning("Python 3.10+ recommended, current: %s", python_version)


def create_database_check():
    """创建数据库检查"""

    def check_database():
        try:
            from neurova.core.database import _get_db_conn

            conn = _get_db_conn()
            conn.execute("SELECT 1")
            return True, "Database OK"
        except Exception as e:
            return False, str(e)

    return check_database


def create_llm_check():
    """创建 LLM 检查"""

    def check_llm():
        try:
            if _app_state and _app_state.get("llm_client"):
                return True, "LLM client available"
            return False, "LLM client not initialized"
        except Exception as e:
            return False, str(e)

    return check_llm


def create_memory_check():
    """创建记忆系统检查"""

    def check_memory():
        try:
            if _app_state and _app_state.get("agents"):
                return True, "Memory system available"
            return False, "Memory system not initialized"
        except Exception as e:
            return False, str(e)

    return check_memory


def create_service_check():
    """创建服务检查"""

    def check_service():
        try:
            if _app_state and _app_state.get("startup_manager"):
                sm = _app_state["startup_manager"]
                if sm.is_started:
                    return True, "Service running"
                return False, "Service not started"
            return False, "Startup manager not available"
        except Exception as e:
            return False, str(e)

    return check_service


def setup_middleware(app):
    """设置中间件"""
    from neurova.api.middleware import setup_middleware as _setup

    _setup(app)


def register_endpoint_routers(app) -> None:
    """
    注册所有端点路由

    尝试导入并注册每个端点模块的 router。
    失败的模块会被跳过（graceful degradation）。
    """
    import importlib

    # 端点模块列表
    endpoint_modules = [
        ("neurova.api.endpoints.health", "/v1/health", "Health API"),
        ("neurova.api.endpoints.home", "/v1", "Home API"),
        ("neurova.api.endpoints.chat", "/v1/chat", "Chat API"),
        ("neurova.api.endpoints.agent", "/v1/agents", "Agent API"),
        ("neurova.api.endpoints.auth", "/v1/auth", "Auth API"),
        ("neurova.api.endpoints.memory", "/v1/memory", "Memory API"),
        ("neurova.api.endpoints.model", "/v1/models", "Model API"),
        ("neurova.api.endpoints.provider", "/v1/providers", "Provider API"),
        ("neurova.api.endpoints.skill", "/v1/skills", "Skill API"),
        ("neurova.api.endpoints.settings", "", "Settings API"),
        ("neurova.api.endpoints.logs", "/v1/logs", "Logs API"),
        ("neurova.api.endpoints.stats", "/v1/stats", "Stats API"),
        ("neurova.api.endpoints.monitor", "/v1/monitor", "Monitor API"),
        ("neurova.api.endpoints.generation", "/v1/generation", "Generation API"),
        ("neurova.api.endpoints.image", "/v1/image", "Image API"),
        ("neurova.api.endpoints.media", "/v1/media", "Media API"),
        ("neurova.api.endpoints.knowledge", "/v1/knowledge", "Knowledge API"),
        ("neurova.api.endpoints.growth", "/v1/growth", "Growth API"),
        ("neurova.api.endpoints.sleep", "/v1/sleep", "Sleep API"),
        ("neurova.api.endpoints.runtime", "/v1/runtime", "Runtime API"),
        ("neurova.api.endpoints.scheduler", "/v1/scheduler", "Scheduler API"),
        ("neurova.api.endpoints.trace", "/v1/trace", "Trace API"),
        ("neurova.api.endpoints.channel", "/v1/channels", "Channel API"),
        ("neurova.api.endpoints.channels", "/v1/channel-adapters", "Channel Adapters API"),
        ("neurova.api.endpoints.channel_config", "/v1", "Channel Config API"),
        ("neurova.api.endpoints.notifications", "/v1/notifications", "Notifications API"),
        ("neurova.api.endpoints.audit", "/v1/audit", "Audit API"),
        ("neurova.api.endpoints.firewall", "/v1/firewall", "Firewall API"),
        ("neurova.api.endpoints.governance", "/v1/governance", "Governance API"),
        ("neurova.api.endpoints.analytics", "/v1/analytics", "Analytics API"),
        ("neurova.api.endpoints.collaboration_api", "/v1/collaboration", "Collaboration API"),
        ("neurova.api.endpoints.groups_api", "/v1/groups", "Groups API"),
        ("neurova.api.endpoints.teams_api", "/v1/teams", "Teams API"),
        ("neurova.api.endpoints.tasks_api", "/v1/tasks", "Tasks API"),
        ("neurova.api.endpoints.projects_api", "/v1/projects", "Projects API"),
        ("neurova.api.endpoints.rules_api", "/v1/rules", "Rules API"),
        ("neurova.api.endpoints.webhooks", "/v1/webhooks", "Webhooks API"),
        ("neurova.api.endpoints.enhanced_users_api", "/v1/enhanced-users", "Enhanced Users API"),
        ("neurova.api.endpoints.user_group_api", "/v1/user-groups", "User Groups API"),
        ("neurova.api.endpoints.files_api", "/v1/files", "Files API"),
        ("neurova.api.endpoints.file_flows_api", "/v1/file-flows", "File Flows API"),
        ("neurova.api.endpoints.tool_schema", "/v1/tools", "Tool Schema API"),
        ("neurova.api.endpoints.tool_layers", "/v1/tool-layers", "Tool Layers API"),
        ("neurova.api.endpoints.skill_pool_api", "/v1/skill-pool", "Skill Pool API"),
        ("neurova.api.endpoints.skill_version_api", "/v1/skill-versions", "Skill Version API"),
        ("neurova.api.endpoints.benchmark", "/v1/benchmark", "Benchmark API"),
        ("neurova.api.endpoints.console", "/v1/console", "Console API"),
        ("neurova.api.endpoints.backup_api", "/v1/backups", "Backup API"),
        ("neurova.api.endpoints.plugin", "/v1/plugins", "Plugin API"),
        ("neurova.api.endpoints.marketplace", "/v1/marketplace", "Marketplace API"),
        ("neurova.api.endpoints.sandbox", "/v1/sandbox", "Sandbox API"),
        ("neurova.api.endpoints.builder", "/v1/builder", "Builder API"),
        ("neurova.api.endpoints.computer", "/v1/computer", "Computer API"),
        ("neurova.api.endpoints.shared_config", "/v1/shared-config", "Shared Config API"),
        ("neurova.api.endpoints.openplatform_keys", "/v1/openplatform", "Open Platform API"),
        ("neurova.api.endpoints.model_adapter", "/v1/model-adapter", "Model Adapter API"),
        ("neurova.api.endpoints.context", "/v1/context", "Context API"),
        ("neurova.api.endpoints.context_pool_settings", "/v1/context-pool", "Context Pool Settings API"),
        ("neurova.api.endpoints.metacognition_api", "/v1/metacognition", "Metacognition API"),
        ("neurova.api.endpoints.experience_knowledge_api", "/v1/experience", "Experience API"),
        ("neurova.api.endpoints.knowledge_graph_api", "/v1/knowledge-graph", "Knowledge Graph API"),
        ("neurova.api.endpoints.knowledge_integration", "/v1/knowledge-integration", "Knowledge Integration API"),
        ("neurova.api.endpoints.semantic_search_api", "/v1/semantic-search", "Semantic Search API"),
        (
            "neurova.api.endpoints.enhanced_memory_search_api",
            "/v1/enhanced-memory-search",
            "Enhanced Memory Search API",
        ),
        ("neurova.api.endpoints.memory_timeline_api", "/v1/memory-timeline", "Memory Timeline API"),
        ("neurova.api.endpoints.synonym_api", "/v1/synonyms", "Synonym API"),
        ("neurova.api.endpoints.agent_enhancement", "/v1/agent-enhancement", "Agent Enhancement API"),
        ("neurova.api.endpoints.agent_communication_api", "/v1/agent-communication", "Agent Communication API"),
        ("neurova.api.endpoints.logs_api", "/v1/logs-api", "Logs API v2"),
        ("neurova.api.endpoints.mobile_pairing", "/v1/mobile", "Mobile Pairing API"),
        ("neurova.api.endpoints.memory_enhancement", "/v1/memory-enhancement", "Memory Enhancement API"),
        ("neurova.api.endpoints.channel_sharing", "/v1/channel-sharing", "Channel Sharing API"),
        ("neurova.api.endpoints.audio", "/v1/audio", "Audio API"),
        ("neurova.api.endpoints.memory_share_groups", "/v1", "Memory Share Groups API"),
        ("neurova.api.endpoints.session_sync", "/v1/sync", "Session Sync API"),
        ("neurova.api.endpoints.neurflow_api", "/v1/neurflow", "Neurflow Workflow API"),
        ("neurova.api.endpoints.negative_screen_settings", "/v1/negative-screen", "Negative Screen Settings API"),
        ("neurova.api.endpoints.memory_settings_api", "/v1/memory-settings", "Memory Settings API"),
        ("neurova.api.endpoints.neuron", "", "NEURON System API"),
    ]

    registered = 0
    for module_path, prefix, description in endpoint_modules:
        try:
            module = importlib.import_module(module_path)
            if hasattr(module, "router"):
                app.include_router(module.router, prefix="/api" + prefix, tags=[description])
                registered += 1
                logger.debug("Registered router: %s (%s)", prefix, description)
            elif hasattr(module, "endpoints"):
                # 某些模块直接定义 endpoints
                registered += 1
                logger.debug("Registered module: %s (%s)", module_path, description)
        except ImportError as e:
            logger.debug("Skipping %s: %s", module_path, e)
        except Exception as e:
            logger.warning("Failed to register %s: %s", module_path, e)

    logger.info("Registered %s/%s endpoint routers", registered, len(endpoint_modules))
