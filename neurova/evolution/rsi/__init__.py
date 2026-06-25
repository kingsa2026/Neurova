"""
递归自我进化（RSI）模块

实现递归自我改进的核心机制，包括：
- 递归棘轮剪枝器
- RSI集成管理器
- 收敛性分析器
- RSI监控指标
- RSI回滚管理器
- RSI部署控制器
- RSI仪表盘
"""

from neurova.core.logger import get_logger
_logger = get_logger(__name__)

try:
    from .recursive_ratchet_pruner import Candidate, EnhancedRatchetPruner, RecursiveRatchetPruner
except ImportError as _e:
    _logger.debug("rsi.recursive_ratchet_pruner 未可用: %s", _e)

try:
    from .integration_manager import ParameterInfo, RSIIntegrationManager, create_rsi_integration_manager
except ImportError as _e:
    _logger.debug("rsi.integration_manager 未可用: %s", _e)

try:
    from .convergence_analyzer import ConvergenceAnalyzer, ConvergenceMetrics, create_convergence_analyzer
except ImportError as _e:
    _logger.debug("rsi.convergence_analyzer 未可用: %s", _e)

try:
    from .metrics import Alert, AlertLevel, RSIMetrics, create_rsi_metrics
except ImportError as _e:
    _logger.debug("rsi.metrics 未可用: %s", _e)

try:
    from .rollback_manager import RSIRollbackManager, create_rollback_manager
except ImportError as _e:
    _logger.debug("rsi.rollback_manager 未可用: %s", _e)

try:
    from .deployment_controller import RSIDeploymentController, create_deployment_controller
except ImportError as _e:
    _logger.debug("rsi.deployment_controller 未可用: %s", _e)

try:
    from .dashboard import RSIDashboard, create_rsi_dashboard
except ImportError as _e:
    _logger.debug("rsi.dashboard 未可用: %s", _e)

try:
    from .orchestrator import RSIOrchestrator, create_rsi_orchestrator
except ImportError as _e:
    _logger.debug("rsi.orchestrator 未可用: %s", _e)

__all__ = [
    "RecursiveRatchetPruner",
    "EnhancedRatchetPruner",
    "Candidate",
    "RSIIntegrationManager",
    "ParameterInfo",
    "create_rsi_integration_manager",
    "ConvergenceAnalyzer",
    "ConvergenceMetrics",
    "create_convergence_analyzer",
    "RSIMetrics",
    "Alert",
    "AlertLevel",
    "create_rsi_metrics",
    "RSIRollbackManager",
    "create_rollback_manager",
    "RSIDeploymentController",
    "create_deployment_controller",
    "RSIDashboard",
    "create_rsi_dashboard",
    "RSIOrchestrator",
    "create_rsi_orchestrator",
]
