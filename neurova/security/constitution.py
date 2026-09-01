"""
Neurova 宪法制度 (Constitutional System)

实现宪法核心逻辑，包括：
1. 宪法规则管理
2. 宪法评估引擎
3. 与执行流程集成
"""

from neurova.core.logger import get_logger
import time
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

logger = get_logger(__name__)


class RuleType(Enum):
    """规则类型"""

    SAFETY = "safety"  # 安全规则
    ETHICS = "ethics"  # 伦理规则
    PERFORMANCE = "performance"  # 性能规则
    COMPLIANCE = "compliance"  # 合规规则
    CUSTOM = "custom"  # 自定义规则


class RuleSeverity(Enum):
    """规则严重程度"""

    LOW = "low"  # 低
    MEDIUM = "medium"  # 中
    HIGH = "high"  # 高
    CRITICAL = "critical"  # 严重


@dataclass
class ConstitutionRule:
    """宪法规则数据模型"""

    rule_id: str
    name: str
    description: str
    rule_type: RuleType
    severity: RuleSeverity
    condition: str  # 规则条件表达式
    action: str  # 触发动作
    enabled: bool = True
    priority: int = 100
    metadata: Optional[Dict[str, Any]] = None
    created_at: Optional[float] = None
    updated_at: Optional[float] = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = time.time()
        if self.updated_at is None:
            self.updated_at = time.time()

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        result = asdict(self)
        result["rule_type"] = self.rule_type.value
        result["severity"] = self.severity.value
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ConstitutionRule":
        """从字典创建"""
        data = data.copy()
        data["rule_type"] = RuleType(data["rule_type"])
        data["severity"] = RuleSeverity(data["severity"])
        return cls(**data)


@dataclass
class ConstitutionEvaluationResult:
    """宪法评估结果数据模型"""

    is_compliant: bool
    violations: List[Dict[str, Any]]
    warnings: List[Dict[str, Any]]
    score: float  # 0.0 - 1.0
    evaluated_at: Optional[float] = None
    metadata: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        if self.evaluated_at is None:
            self.evaluated_at = time.time()

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)


class ConstitutionEvaluationEngine:
    """宪法评估引擎"""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        初始化宪法评估引擎

        Args:
            config: 配置信息
        """
        self.config = config or {}
        self.rules: Dict[str, ConstitutionRule] = {}
        self._initialize_default_rules()

        logger.info("ConstitutionEvaluationEngine initialized")

    def _initialize_default_rules(self):
        """初始化默认规则"""
        default_rules = [
            ConstitutionRule(
                rule_id="safety_001",
                name="禁止有害内容",
                description="禁止生成有害、暴力、色情或违法内容",
                rule_type=RuleType.SAFETY,
                severity=RuleSeverity.CRITICAL,
                condition="content.contains_harmful",
                action="block",
                enabled=True,
                priority=1,
            ),
            ConstitutionRule(
                rule_id="ethics_001",
                name="尊重隐私",
                description="不得收集、存储或泄露用户个人隐私信息",
                rule_type=RuleType.ETHICS,
                severity=RuleSeverity.HIGH,
                condition="data.contains_pii",
                action="warn",
                enabled=True,
                priority=2,
            ),
            ConstitutionRule(
                rule_id="ethics_002",
                name="公平对待",
                description="不得基于种族、性别、年龄等因素歧视用户",
                rule_type=RuleType.ETHICS,
                severity=RuleSeverity.HIGH,
                condition="content.contains_discrimination",
                action="block",
                enabled=True,
                priority=3,
            ),
            ConstitutionRule(
                rule_id="performance_001",
                name="响应时间",
                description="响应时间不得超过30秒",
                rule_type=RuleType.PERFORMANCE,
                severity=RuleSeverity.MEDIUM,
                condition="response.time > 30",
                action="warn",
                enabled=True,
                priority=10,
            ),
            ConstitutionRule(
                rule_id="compliance_001",
                name="遵守法律",
                description="必须遵守当地法律法规",
                rule_type=RuleType.COMPLIANCE,
                severity=RuleSeverity.CRITICAL,
                condition="action.illegal",
                action="block",
                enabled=True,
                priority=1,
            ),
        ]

        for rule in default_rules:
            self.rules[rule.rule_id] = rule

        logger.info("Initialized %d default constitution rules", len(default_rules))

    def update_constitution(self, rules_data: List[Dict[str, Any]]):
        """
        更新宪法规则

        Args:
            rules_data: 规则数据列表
        """
        try:
            for rule_data in rules_data:
                rule = ConstitutionRule.from_dict(rule_data)
                self.rules[rule.rule_id] = rule

            logger.info("Updated constitution with %d rules", len(rules_data))

        except Exception as e:
            logger.error("Failed to update constitution: %s", e)
            raise

    def add_rule(self, rule: ConstitutionRule):
        """
        添加规则

        Args:
            rule: 宪法规则
        """
        self.rules[rule.rule_id] = rule
        logger.info("Added constitution rule: %s", rule.rule_id)

    def remove_rule(self, rule_id: str) -> bool:
        """
        移除规则

        Args:
            rule_id: 规则ID

        Returns:
            是否成功移除
        """
        if rule_id in self.rules:
            del self.rules[rule_id]
            logger.info("Removed constitution rule: %s", rule_id)
            return True
        return False

    def get_enabled_rules(self) -> List[ConstitutionRule]:
        """
        获取启用的规则

        Returns:
            启用的规则列表
        """
        return [rule for rule in self.rules.values() if rule.enabled]

    def evaluate(self, context: Dict[str, Any]) -> ConstitutionEvaluationResult:
        """
        评估上下文是否符合宪法

        Args:
            context: 评估上下文

        Returns:
            评估结果
        """
        violations = []
        warnings = []

        try:
            # 获取启用的规则并按优先级排序
            enabled_rules = self.get_enabled_rules()
            enabled_rules.sort(key=lambda r: r.priority)

            for rule in enabled_rules:
                violation = self._check_rule_violation(rule, context)
                if violation:
                    if rule.severity in [RuleSeverity.CRITICAL, RuleSeverity.HIGH]:
                        violations.append(violation)
                    else:
                        warnings.append(violation)

            # 计算合规分数
            total_rules = len(enabled_rules)
            violated_rules = len(violations) + len(warnings)
            score = 1.0 - (violated_rules / total_rules) if total_rules > 0 else 1.0

            is_compliant = len(violations) == 0

            result = ConstitutionEvaluationResult(
                is_compliant=is_compliant,
                violations=violations,
                warnings=warnings,
                score=score,
                metadata={"total_rules": total_rules, "evaluated_rules": total_rules, "violated_rules": violated_rules},
            )

            logger.info(
                "Constitution evaluation: compliant=%s, score=%.2f, violations=%d, warnings=%d",
                is_compliant,
                score,
                len(violations),
                len(warnings),
            )

            return result

        except Exception as e:
            logger.error("Failed to evaluate constitution: %s", e)
            # 返回一个安全的默认结果
            return ConstitutionEvaluationResult(
                is_compliant=False, violations=[{"rule_id": "error", "message": str(e)}], warnings=[], score=0.0
            )

    def _check_rule_violation(self, rule: ConstitutionRule, context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        检查规则违反情况

        Args:
            rule: 宪法规则
            context: 评估上下文

        Returns:
            违反信息，如果没有违反则返回None
        """
        try:
            # 这里应该实现实际的规则检查逻辑
            # 简化版本：基于条件表达式进行检查
            rule.condition

            # 检查安全规则
            if rule.rule_type == RuleType.SAFETY:
                content = context.get("content", "")
                if isinstance(content, str):
                    # 简单的关键词检查
                    harmful_keywords = ["暴力", "色情", "违法", "恐怖", "自杀"]
                    for keyword in harmful_keywords:
                        if keyword in content:
                            return {
                                "rule_id": rule.rule_id,
                                "rule_name": rule.name,
                                "severity": rule.severity.value,
                                "message": f"内容包含有害关键词: {keyword}",
                                "action": rule.action,
                            }

            # 检查伦理规则
            elif rule.rule_type == RuleType.ETHICS:
                content = context.get("content", "")
                if isinstance(content, str):
                    # 检查歧视性内容
                    discrimination_keywords = ["种族歧视", "性别歧视", "年龄歧视"]
                    for keyword in discrimination_keywords:
                        if keyword in content:
                            return {
                                "rule_id": rule.rule_id,
                                "rule_name": rule.name,
                                "severity": rule.severity.value,
                                "message": f"内容包含歧视性关键词: {keyword}",
                                "action": rule.action,
                            }

            # 检查性能规则
            elif rule.rule_type == RuleType.PERFORMANCE:
                response_time = context.get("response_time", 0)
                if response_time > 30:
                    return {
                        "rule_id": rule.rule_id,
                        "rule_name": rule.name,
                        "severity": rule.severity.value,
                        "message": f"响应时间超过30秒: {response_time}秒",
                        "action": rule.action,
                    }

            return None

        except Exception as e:
            logger.error("Failed to check rule violation for %s: %s", rule.rule_id, e)
            return {
                "rule_id": rule.rule_id,
                "rule_name": rule.name,
                "severity": "error",
                "message": f"规则检查失败: {str(e)}",
                "action": "warn",
            }

    def evaluate_tool_call(self, tool_name: str, tool_params: Dict[str, Any]) -> ConstitutionEvaluationResult:
        """
        评估工具调用是否符合宪法

        Args:
            tool_name: 工具名称
            tool_params: 工具参数

        Returns:
            评估结果
        """
        context = {"type": "tool_call", "tool_name": tool_name, "tool_params": tool_params, "content": str(tool_params)}

        return self.evaluate(context)

    def get_constitution_data(self) -> Dict[str, Any]:
        """
        获取宪法数据

        Returns:
            宪法数据字典
        """
        return {
            "rules": [rule.to_dict() for rule in self.rules.values()],
            "total_rules": len(self.rules),
            "enabled_rules": len(self.get_enabled_rules()),
            "updated_at": time.time(),
        }


# 全局实例
_constitution_engine: Optional[ConstitutionEvaluationEngine] = None
_constitution_engine_lock = __import__('threading').Lock()


def get_constitution_engine() -> ConstitutionEvaluationEngine:
    """
    获取宪法评估引擎实例（单例模式）

    Returns:
        ConstitutionEvaluationEngine实例
    """
    global _constitution_engine
    if _constitution_engine is None:
        with _constitution_engine_lock:
            if _constitution_engine is None:
                _constitution_engine = ConstitutionEvaluationEngine()
    return _constitution_engine


def reset_constitution_engine():
    """
    重置宪法评估引擎实例（用于测试）
    """
    global _constitution_engine
    _constitution_engine = None
