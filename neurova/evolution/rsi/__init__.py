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

import logging

_logger = logging.getLogger(__name__)

try:
    from .recursive_ratchet_pruner import RecursiveRatchetPruner, EnhancedRatchetPruner, Candidate
except ImportError as _e:
    _logger.debug(f"rsi.recursive_ratchet_pruner 未可用: {_e}")

try:
    from .integration_manager import RSIIntegrationManager, ParameterInfo, create_rsi_integration_manager
except ImportError as _e:
    _logger.debug(f"rsi.integration_manager 未可用: {_e}")

try:
    from .convergence_analyzer import ConvergenceAnalyzer, ConvergenceMetrics, create_convergence_analyzer
except ImportError as _e:
    _logger.debug(f"rsi.convergence_analyzer 未可用: {_e}")

try:
    from .metrics import RSIMetrics, Alert, AlertLevel, create_rsi_metrics
except ImportError as _e:
    _logger.debug(f"rsi.metrics 未可用: {_e}")

try:
    from .rollback_manager import RSIRollbackManager, create_rollback_manager
except ImportError as _e:
    _logger.debug(f"rsi.rollback_manager 未可用: {_e}")

try:
    from .deployment_controller import RSIDeploymentController, create_deployment_controller
except ImportError as _e:
    _logger.debug(f"rsi.deployment_controller 未可用: {_e}")

try:
    from .dashboard import RSIDashboard, create_rsi_dashboard
except ImportError as _e:
    _logger.debug(f"rsi.dashboard 未可用: {_e}")

try:
    from .orchestrator import RSIOrchestrator, create_rsi_orchestrator
except ImportError as _e:
    _logger.debug(f"rsi.orchestrator 未可用: {_e}")

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
