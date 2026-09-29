# neurova.api.endpoints 包
# 从各端点模块统一导出

import threading

from neurova.core.logger import get_logger
from typing import Any, Dict, Optional

logger = get_logger(__name__)

# 挂载事实唯一的落点：`endpoint_modules` 注册表（见 register_endpoint_routers）。
# 历史上这里另有三个模块级空 APIRouter（router / evolution_router / rag_router），
# 被 app.py 挂成 /api、/api/evolution、/api/rag —— 对外声称三个前缀可用、实际全 404。
# 已删除：空 router 不是「待接线」，是「不存在却对外可见」。

# 全局状态（由 app.py 初始化时设置）
_app_state: Optional[Dict[str, Any]] = None

# 默认 agent 身份的初值——全仓只此一处字面量，`_app_state["default_agent_id"]`
# 一旦被人改写（`switch_agent`），后续每一次未指名的解析都跟着走那份状态。
DEFAULT_AGENT_ID = "default"


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


def get_agent_instance(agent_id: str = ""):
    """按 agent_id 取实例；**未指名时按"当前默认 agent"解析，不写死字面量**。

    默认位是运行期可变的（`POST /v1/agents/{agent_id}/switch` 就在改它），所以这里
    经 `defaultAgentId()` 取，而不是把 `"default"` 当成事实。历史上解析侧写死
    字面量、写侧另写一个键名且全仓无人读，于是"切换默认 Agent"回 200 而无人执行。
    """
    if _app_state:
        agents = _app_state.get("agents", {})
        return agents.get(agent_id or defaultAgentId())
    return None


def defaultAgentId() -> str:
    """当前默认 agent 的身份——唯一读点。未设置过时用初值 `DEFAULT_AGENT_ID`。"""
    if _app_state:
        return _app_state.get("default_agent_id") or DEFAULT_AGENT_ID
    return DEFAULT_AGENT_ID


def setDefaultAgentId(agentId: str) -> None:
    """当前默认 agent 的身份——唯一写点。

    写入口与 `defaultAgentId()` 同处一模块：键名字面量一旦散到第二个模块，就会出现
    "一边写 default_agent_id、一边读硬编码 default"这种两半各自成立、合起来失效的形态。
    """
    _app_state["default_agent_id"] = agentId


def init_default_user():
    """初始化默认用户"""
    try:
        from neurova.api.auth import _load_or_create_secret_key

        _load_or_create_secret_key()
    except Exception as e:
        logger.warning("Failed to init default user: %s", e)


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
            # 用上下文管理器：旧写法调 deprecated 旧接口取连接后从不归还，
            # 每次健康检查漏一条池连接 —— 漏满 max_connections 后
            # get_connection 会阻塞至 timeout（历史"健康检查卡 30s"根因）。
            from neurova.core.database import database_connection

            with database_connection() as conn:
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


#: 端点模块装载失败面：`(模块路径, 失败原因)`。注册表是全量硬清单，
#: 任何一行装载失败都意味着该前缀整体不可达——必须可被读取，不能只活在日志里。
_registration_failures: list = []
_registration_failure_lock = threading.Lock()


def _recordRegistrationFailure(modulePath: str, error: BaseException) -> None:
    """记录一次装载失败：写失败面 + ERROR 级日志（含模块名，排障者能直接定位）。"""
    reason = f"{type(error).__name__}: {error}"
    with _registration_failure_lock:
        _registration_failures.append((modulePath, reason))
    logger.error("端点模块装载失败 %s：%s", modulePath, reason)


def registrationFailures() -> list:
    """当前失败面副本（`(模块路径, 原因)`）——启动自检与守卫的唯一读取口。"""
    with _registration_failure_lock:
        return list(_registration_failures)


def resetRegistrationFailures() -> None:
    """清空失败面（进程内自检与测试用；不改变已发生的失败语义）。"""
    with _registration_failure_lock:
        _registration_failures.clear()


#: 端点模块注册表 —— **挂载事实的唯一落点**（`app.py` 的旁路已删除）。
#: 提为模块级常量（而不再藏在函数体内），使启动自检、健康检查与守卫能读同一份表，
#: 而不是各自再抄一遍（教义第 6 条：不新造平行体系）。
ENDPOINT_MODULES = [
    ("neurova.api.endpoints.health", "/v1/health", "Health API"),
    ("neurova.api.endpoints.home", "/v1", "Home API"),
    ("neurova.api.endpoints.chat", "/v1/chat", "Chat API"),
    ("neurova.api.endpoints.plans", "/v1/plans", "Plans API"),
    ("neurova.api.endpoints.agent", "/v1/agents", "Agent API"),
    ("neurova.api.endpoints.agent_package", "/v1/agents", "Agent Package API"),
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
    ("neurova.api.endpoints.studio_api", "/v1/studio", "Studio API"),
    ("neurova.api.endpoints.image", "/v1/image", "Image API"),
    ("neurova.api.endpoints.media", "/v1/media", "Media API"),
    ("neurova.api.endpoints.knowledge", "/v1/knowledge", "Knowledge API"),
    ("neurova.api.endpoints.growth", "/v1/growth", "Growth API"),
    ("neurova.api.endpoints.sleep", "/v1/sleep", "Sleep API"),
    ("neurova.api.endpoints.runtime", "/v1/runtime", "Runtime API"),
    ("neurova.api.endpoints.scheduler", "/v1/scheduler", "Scheduler API"),
    ("neurova.api.endpoints.trace", "/v1/trace", "Trace API"),
    ("neurova.api.endpoints.channels", "/v1/channel-adapters", "Channel Adapters API"),
    ("neurova.api.endpoints.channel_config", "/v1", "Channel Config API"),
    ("neurova.api.endpoints.notifications", "/v1/notifications", "Notifications API"),
    ("neurova.api.endpoints.audit", "/v1/audit", "Audit API"),
    ("neurova.api.endpoints.workspace_files", "/v1/workspace", "Workspace Files API"),
    ("neurova.api.endpoints.firewall", "/v1/firewall", "Firewall API"),
    ("neurova.api.endpoints.governance", "/v1/governance", "Governance API"),
    ("neurova.api.endpoints.analytics", "/v1/analytics", "Analytics API"),
    ("neurova.api.endpoints.collaboration_api", "/v1/collaboration", "Collaboration API"),
    ("neurova.api.endpoints.collaboration_room_api", "/v1/collaboration", "Collaboration Room API"),
    ("neurova.api.endpoints.groups_api", "/v1/groups", "Groups API"),
    ("neurova.api.endpoints.teams_api", "/v1/teams", "Teams API"),
    ("neurova.api.endpoints.tasks_api", "/v1/tasks", "Tasks API"),
    ("neurova.api.endpoints.projects_api", "/v1/projects", "Projects API"),
    ("neurova.api.endpoints.rules_api", "/v1/rules", "Rules API"),
    ("neurova.api.endpoints.webhooks", "/v1/webhooks", "Webhooks API"),
    ("neurova.api.endpoints.enhanced_users_api", "/v1/enhanced-users", "Enhanced Users API"),
    ("neurova.api.endpoints.user_group_api", "/v1/user-groups", "User Groups API"),
    ("neurova.api.endpoints.files_api", "/v1/files", "Files API"),
    ("neurova.api.endpoints.artifacts_api", "/v1/artifacts", "Artifacts API"),
    ("neurova.api.endpoints.tool_schema", "/v1/tools", "Tool Schema API"),
    ("neurova.api.endpoints.tool_layers", "/v1/tool-layers", "Tool Layers API"),
    ("neurova.api.endpoints.skill_pool_api", "/v1/skill-pool", "Skill Pool API"),
    ("neurova.api.endpoints.skill_version_api", "/v1/skill-versions", "Skill Version API"),
    ("neurova.api.endpoints.text_evolution_api", "/v1/evolution", "Text Evolution API"),
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
    ("neurova.api.endpoints.mcp_server_api", "/v1/mcp", "Neurova MCP Server Face"),
    ("neurova.api.endpoints.negative_screen_settings", "/v1/negative-screen", "Negative Screen Settings API"),
    ("neurova.api.endpoints.memory_settings_api", "/v1/memory-settings", "Memory Settings API"),
    # neuron / coordination_api / acp_api 的挂载前缀由模块自述 `APIRouter(prefix=...)`
    # 提供（表内留空），避免与自述前缀各叠一次拼出 /api/neuron/neuron 这类重复段。
    ("neurova.api.endpoints.neuron", "", "NEURON System API"),
    ("neurova.api.endpoints.coordination_api", "", "Multi-Agent Coordination API"),
    ("neurova.api.endpoints.acp_api", "/acp", "ACP 消息协议 API"),
    # 此前由 app.py 旁路挂在 /api 下（缺 /v1），而前端 axios baseURL=/api/v1 →
    # 真实页面 CostDashboardPage.vue 的请求必 404。并入注册表即回到全库统一的
    # /api/v1 挂载层，旁路副本同步删除。
    ("neurova.api.endpoints.budget_api", "/v1", "Budget API"),
    ("neurova.api.endpoints.cost_rollup_api", "/v1", "Cost Rollup API"),
    # 以下两行的接线属「未挂载端点模块」名单的收口（Issue #68）：
    #   computer_api ― `/computers/*` 计算节点管理面。此前未挂载的**根因是身份是假的**
    #     （8 处 `Depends(lambda: "current_user")` 硬编码身份）+ 唯一消费方
    #     `api/computer.ts` 是 React 原型（`main.ts` 从不加载、`package.json` 无 react）。
    #     本批两处同批收口：身份改真实 JWT `get_current_user`，
    #     前端 `api/computer.ts` 回归唯一 axios 实例并按 `/api/v1` 请求。
    #   phase3_api ― 小脑路由 / outbox / 成本告警的运维面。三类运行态在生产链路
    #     另有主线消费方（`agent/model_selector.py`、`agent/turn_coordinator.py`），
    #     此前零挂载且零鉴权；本批补身份闸口（破坏性动作另加管理员闸）后接线。
    ("neurova.api.endpoints.computer_api", "/v1", "Computer API"),
    ("neurova.api.endpoints.phase3_api", "/v1", "Phase 3 Intelligence API"),
]


def register_endpoint_routers(app) -> int:
    """注册所有端点路由，返回成功装载的行数。

    逐行装载 `ENDPOINT_MODULES` 并挂载。任何一行失败都会被**显式记录**
    （ERROR 日志 + `registrationFailures()` 失败面），不再静默降级——
    注册表是全量硬清单，一行失败即该前缀整体不可达，必须启动期可见。
    """
    import importlib

    registered = 0
    for module_path, prefix, description in ENDPOINT_MODULES:
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
        except Exception as e:
            # 此前这里按 `ImportError → logger.debug` 处理：DEBUG 在默认级别下不输出，
            # 于是「某个注册表模块炸了、该前缀整体 404」在启动期完全不可见——
            # 正是教义第 2 条点名的「把失败改写成看不见」。现一律以 ERROR 记录并
            # 记进可读取的失败面（健康检查 / 启动自检 / 守卫共用）。
            _recordRegistrationFailure(module_path, e)

    if registrationFailures():
        logger.error(
            "端点注册表未全量装载：%s/%s 成功；失败 %s 项 —— %s",
            registered,
            len(ENDPOINT_MODULES),
            len(registrationFailures()),
            "；".join(f"{name}: {reason}" for name, reason in registrationFailures()),
        )
    logger.info("Registered %s/%s endpoint routers", registered, len(ENDPOINT_MODULES))
    return registered
