"""
Cost Budget Management System

Purpose: Real-time budget monitoring, alert thresholds, and automated notifications

Components:
- Budget configuration (hourly, daily, monthly)
- Real-time budget tracking
- Alert threshold management
- Notification system integration
"""

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import Dict, List, Optional, Union
from datetime import datetime, timedelta
import threading


# ============================================================================
# Enums
# ============================================================================

class AlertLevel(Enum):
    """Alert severity levels"""
    INFO = "info"           # 50% usage
    WARNING = "warning"     # 75% usage  
    CRITICAL = "critical"   # 90% usage
    EXCEEDED = "exceeded"   # 100%+ usage
    RECOVERED = "recovered" # 回落到回退线以下（回落语义，不参与越线触发）


class BudgetScope(Enum):
    """Budget scope dimensions"""
    HOURLY = "hourly"
    DAILY = "daily"
    MONTHLY = "monthly"
    AGENT = "agent"
    PROVIDER = "provider"
    MODEL = "model"


class AlertChannel(Enum):
    """Notification channels"""
    LOG = "log"
    WEBHOOK = "webhook"
    EMAIL = "email"
    SLACK = "slack"
    DISCORD = "discord"


# ============================================================================
# Configuration Data Classes
# ============================================================================

@dataclass
class BudgetConfig:
    """Budget configuration"""
    scope: BudgetScope
    identifier: str  # agent_id, provider, model, etc.
    amount: Decimal
    period_start: datetime
    period_end: datetime
    auto_reset: bool = True
    
    def is_active(self, now: Optional[datetime] = None) -> bool:
        """Check if budget is currently active"""
        if now is None:
            now = datetime.now()
        return self.period_start <= now <= self.period_end


@dataclass
class AlertConfig:
    """Alert threshold configuration"""
    level: AlertLevel
    percentage: Decimal  # 用量百分数，0~100 制（与 get_usage_percentage 同尺度）
    enabled: bool = True
    channels: List[AlertChannel] = field(default_factory=list)
    message_template: Optional[str] = None
    
    def should_trigger(self, usage_percentage: Decimal) -> bool:
        """Check if this alert should trigger at current usage"""
        return usage_percentage >= self.percentage


# Default alert thresholds
#
# 阈值口径与 `get_usage_percentage()` 的输出**同一尺度**：0~100 的百分数。
# 该尺度是权威（`is_over_budget` 的 `>= 100.00`、API 响应字段、前端 `>= 75`
# 与既有断言都按它读），阈值表此前写成 0~1 制是唯一的例外 —— 后果是首次记账
# 就把 INFO/WARNING/CRITICAL/EXCEEDED 全档触发（1% 用量也报"超支"）。
DEFAULT_ALERT_THRESHOLDS = [
    AlertConfig(
        level=AlertLevel.INFO,
        percentage=Decimal("50.00"),
        enabled=True,
        channels=[AlertChannel.LOG],
        message_template="Budget usage at {percentage}% - informational"
    ),
    AlertConfig(
        level=AlertLevel.WARNING,
        percentage=Decimal("75.00"),
        enabled=True,
        channels=[AlertChannel.LOG, AlertChannel.SLACK],
        message_template="⚠️ Budget usage at {percentage}% - warning"
    ),
    AlertConfig(
        level=AlertLevel.CRITICAL,
        percentage=Decimal("90.00"),
        enabled=True,
        channels=[AlertChannel.LOG, AlertChannel.SLACK, AlertChannel.EMAIL],
        message_template="🔴 CRITICAL: Budget usage at {percentage}% - immediate attention required"
    ),
    AlertConfig(
        level=AlertLevel.EXCEEDED,
        percentage=Decimal("100.00"),
        enabled=True,
        channels=[AlertChannel.LOG, AlertChannel.SLACK, AlertChannel.EMAIL],
        message_template="🚨 BUDGET EXCEEDED: Usage at {percentage}% - throttling enabled"
    ),
    AlertConfig(
        level=AlertLevel.RECOVERED,
        percentage=Decimal("80.00"),
        enabled=True,
        channels=[AlertChannel.LOG],
        message_template="✅ Budget recovered to {percentage}% - normal operations resumed"
    ),
]


# ============================================================================
# Core Budget Manager
# ============================================================================

def asBudgetAmount(value) -> Decimal:
    """把成本域的值换算成账本域的 Decimal（**唯一**换算点）。

    成本域是 float（价格表与 `cost_store` 的 `REAL` 列），账本域做 Decimal
    算术。换算走 `Decimal(str(value))` 而非 `Decimal(value)`：后者会把
    float 的二进制误差原样带进金额（`Decimal(0.1)` 有 55 位小数），
    而账本要的是用户看到的那一位小数。

    落点在 `BudgetManager.record_usage`（`+=` 的发生处），故凡能记进账本的
    路径都经它一次；两处各转一份正是"一处在转、一处没转"的来由。
    """
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


class BudgetManager:
    """Real-time budget monitoring and alerting"""
    
    def __init__(self):
        self._lock = threading.RLock()
        self._budgets: Dict[str, BudgetConfig] = {}
        self._alert_configs: List[AlertConfig] = DEFAULT_ALERT_THRESHOLDS.copy()
        self._usage_cache: Dict[str, Decimal] = {}
        self._last_alerted: Dict[str, Dict[AlertLevel, datetime]] = {}
        
    def register_budget(self, config: BudgetConfig):
        """Register a new budget"""
        with self._lock:
            key = f"{config.scope.value}:{config.identifier}"
            self._budgets[key] = config
            self._usage_cache[key] = Decimal("0.00")
            
    def unregister_budget(self, scope: BudgetScope, identifier: str):
        """Remove a budget"""
        with self._lock:
            key = f"{scope.value}:{identifier}"
            if key in self._budgets:
                del self._budgets[key]
                
    def record_usage(self, scope: BudgetScope, identifier: str, amount: Union[Decimal, float]):
        """把一次用量记进账本。

        `amount` 接受成本域的原始值（float 或 Decimal）—— 归一是本方法的
        职责，因为它才是 `+=` 的发生处。只在某个调用方归一的话，直接调
        本方法的路径（以及将来新增的调用方）会重新撞上
        `Decimal += float`（账本记不下任何用量，且被 fail-open 静默兜住）。
        """
        with self._lock:
            key = f"{scope.value}:{identifier}"
            
            if key not in self._usage_cache:
                self._usage_cache[key] = Decimal("0.00")
                
            self._usage_cache[key] += asBudgetAmount(amount)
            
            # Check alerts after recording
            self._check_alerts(scope, identifier)
            
    def get_usage(self, scope: BudgetScope, identifier: str) -> Decimal:
        """Get current usage for a budget"""
        with self._lock:
            key = f"{scope.value}:{identifier}"
            return self._usage_cache.get(key, Decimal("0.00"))
            
    def get_remaining(self, scope: BudgetScope, identifier: str) -> Decimal:
        """Get remaining budget amount"""
        with self._lock:
            key = f"{scope.value}:{identifier}"
            budget = self._budgets.get(key)
            
            if not budget:
                return Decimal("0.00")
                
            usage = self._usage_cache.get(key, Decimal("0.00"))
            remaining = budget.amount - usage
            
            return max(remaining, Decimal("0.00"))
            
    def get_usage_percentage(self, scope: BudgetScope, identifier: str) -> Decimal:
        """Get usage as percentage of budget"""
        with self._lock:
            key = f"{scope.value}:{identifier}"
            budget = self._budgets.get(key)
            
            if not budget or budget.amount == 0:
                return Decimal("0.00")
                
            usage = self._usage_cache.get(key, Decimal("0.00"))
            percentage = (usage / budget.amount) * Decimal("100")
            
            return percentage.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            
    def _check_alerts(self, scope: BudgetScope, identifier: str):
        """Check if any alerts should be triggered"""
        with self._lock:
            key = f"{scope.value}:{identifier}"
            percentage = self.get_usage_percentage(scope, identifier)
            
            # Initialize last alerted dict if needed
            if key not in self._last_alerted:
                self._last_alerted[key] = {}
                
            for alert_config in self._alert_configs:
                if not alert_config.enabled:
                    continue

                # RECOVERED 是**回落**语义，不是"越过阈值"语义，故不能走
                # should_trigger —— 那条路上 `percentage >= 阈值` 恒成立时
                # 反而会报出"已恢复到 125000%"（实测）。
                # 它只在越过回退线**向下**时发一次，并清掉 EXCEEDED 状态。
                if alert_config.level == AlertLevel.RECOVERED:
                    if (
                        AlertLevel.EXCEEDED in self._last_alerted[key]
                        and percentage < alert_config.percentage
                    ):
                        self._send_alert(alert_config, scope, identifier, percentage)
                        del self._last_alerted[key][AlertLevel.EXCEEDED]
                    continue

                # Check if alert should trigger
                if alert_config.should_trigger(percentage):
                    # Check if we already alerted at this level recently
                    last_alerted = self._last_alerted[key].get(alert_config.level)

                    if last_alerted is None:
                        # Never alerted before - send alert
                        self._send_alert(alert_config, scope, identifier, percentage)
                        self._last_alerted[key][alert_config.level] = datetime.now()

    def _send_alert(self, config: AlertConfig, scope: BudgetScope, 
                   identifier: str, percentage: Decimal):
        """Send alert through configured channels"""
        message = config.message_template.format(percentage=percentage)
        
        for channel in config.channels:
            try:
                if channel == AlertChannel.LOG:
                    self._log_alert(config.level, message)
                elif channel == AlertChannel.SLACK:
                    self._slack_alert(message)
                elif channel == AlertChannel.EMAIL:
                    self._email_alert(scope, identifier, percentage)
                # Add more channel implementations as needed
            except Exception as e:
                # Don't let alert failures break the system
                print(f"Failed to send alert via {channel}: {e}")
                
    def _log_alert(self, level: AlertLevel, message: str):
        """Log alert to application logs"""
        from neurova.core.logger import get_logger
        logger = get_logger(__name__)
        
        if level == AlertLevel.INFO:
            logger.info(message)
        elif level == AlertLevel.WARNING:
            logger.warning(message)
        elif level in [AlertLevel.CRITICAL, AlertLevel.EXCEEDED]:
            logger.error(message)
        elif level == AlertLevel.RECOVERED:
            logger.info(message)
            
    def _slack_alert(self, message: str):
        """Send alert to Slack"""
        # TODO: Implement Slack webhook integration
        pass
        
    def _email_alert(self, scope: BudgetScope, identifier: str, percentage: Decimal):
        """Send email alert"""
        # TODO: Implement email notification
        pass
        
    def is_over_budget(self, scope: BudgetScope, identifier: str) -> bool:
        """Check if budget is exceeded"""
        with self._lock:
            percentage = self.get_usage_percentage(scope, identifier)
            return percentage >= Decimal("100.00")
            
    def throttle_if_needed(self, scope: BudgetScope, identifier: str) -> bool:
        """
        Throttle requests if budget exceeded.
        Returns True if throttling is active.
        """
        if self.is_over_budget(scope, identifier):
            # Log throttling action
            self._log_alert(
                AlertLevel.EXCEEDED,
                f"Throttling requests for {scope.value}:{identifier} - budget exceeded"
            )
            return True
        return False


# ============================================================================
# Budget Service (High-level API)
# ============================================================================

class BudgetService:
    """High-level budget service with database integration"""
    
    def __init__(self):
        self.manager = BudgetManager()
        self._initialized = False
        
    def initialize(self):
        """Initialize budget system from database"""
        if self._initialized:
            return
            
        # TODO: Load budgets from llm_budgets table
        # for row in db.query("SELECT * FROM llm_budgets WHERE active = true"):
        #     config = BudgetConfig(
        #         scope=BudgetScope(row['scope']),
        #         identifier=row['identifier'],
        #         amount=Decimal(str(row['amount'])),
        #         period_start=row['period_start'],
        #         period_end=row['period_end'],
        #     )
        #     self.manager.register_budget(config)
            
        self._initialized = True
        
    def record_llm_call_cost(
        self,
        agent_id: str,
        provider: str,
        model: str,
        cost: Union[Decimal, float],
        turn_id: Optional[str] = None
    ):
        """
        Record LLM call cost and check budgets.
        
        This should be called by @track_llm_call decorator after each LLM call.

        `cost` 接受成本域的原始值（float 或 Decimal）：归一由账本入口
        `BudgetManager.record_usage`（`+=` 的发生处）承担，本方法不重复转一次。
        """
        # Record against agent hourly budget
        self.manager.record_usage(BudgetScope.HOURLY, agent_id, cost)
        
        # Record against provider budget
        self.manager.record_usage(BudgetScope.PROVIDER, provider, cost)
        
        # Record against model budget
        self.manager.record_usage(BudgetScope.MODEL, model, cost)
        
        # TODO: Also record against custom budgets from database
        
    def get_agent_budget_status(self, agent_id: str) -> Dict:
        """Get budget status for an agent"""
        hourly_usage = self.manager.get_usage(BudgetScope.HOURLY, agent_id)
        hourly_remaining = self.manager.get_remaining(BudgetScope.HOURLY, agent_id)
        hourly_percentage = self.manager.get_usage_percentage(BudgetScope.HOURLY, agent_id)
        
        return {
            "agent_id": agent_id,
            "hourly": {
                "usage": float(hourly_usage),
                "remaining": float(hourly_remaining),
                "percentage": float(hourly_percentage),
                "is_over_budget": self.manager.is_over_budget(BudgetScope.HOURLY, agent_id),
            }
        }
        
    def get_all_budget_statuses(self) -> Dict:
        """Get budget status for all registered budgets"""
        statuses = {}
        
        for key in self.manager._usage_cache.keys():
            scope_str, identifier = key.split(":", 1)
            scope = BudgetScope(scope_str)
            
            statuses[key] = {
                "scope": scope.value,
                "identifier": identifier,
                "usage": float(self.manager.get_usage(scope, identifier)),
                "remaining": float(self.manager.get_remaining(scope, identifier)),
                "percentage": float(self.manager.get_usage_percentage(scope, identifier)),
                "is_over_budget": self.manager.is_over_budget(scope, identifier),
            }
            
        return statuses


# Global budget service instance
_budget_service: Optional[BudgetService] = None


def get_budget_service() -> BudgetService:
    """Get global budget service instance"""
    global _budget_service
    if _budget_service is None:
        _budget_service = BudgetService()
        _budget_service.initialize()
    return _budget_service


def reset_budget_service():
    """Reset budget service (for testing)"""
    global _budget_service
    _budget_service = None
