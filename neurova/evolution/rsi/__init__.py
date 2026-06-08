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

from .recursive_ratchet_pruner import RecursiveRatchetPruner, EnhancedRatchetPruner, Candidate
from .integration_manager import RSIIntegrationManager, ParameterInfo, create_rsi_integration_manager
from .convergence_analyzer import ConvergenceAnalyzer, ConvergenceMetrics, create_convergence_analyzer
from .metrics import RSIMetrics, Alert, AlertLevel, create_rsi_metrics
from .rollback_manager import RSIRollbackManager, create_rollback_manager
from .deployment_controller import RSIDeploymentController, create_deployment_controller
from .dashboard import RSIDashboard, create_rsi_dashboard
from .orchestrator import RSIOrchestrator, create_rsi_orchestrator

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
