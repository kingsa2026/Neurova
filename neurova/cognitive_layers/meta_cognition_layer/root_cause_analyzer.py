"""
Tool Root Cause Analyzer v1.0.0 — 工具失败根因分析器

职责:
- 拦截工具执行失败，分析失败根因
- 检测系统性缺陷模式（相同工具+相同错误连续出现）
- 检查参数是否在历史成功范围内
- 生成可操作的改进建议

集成到 MetaCognition.reflect() 流程中。
"""

from __future__ import annotations

import datetime
from neurova.core.logger import get_logger
import re
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = get_logger(__name__)


class RootCauseCategory(str, Enum):
    """根因分类"""

    PARAMETER_ERROR = "parameter_error"  # 参数错误
    AUTHENTICATION = "authentication"  # 认证问题
    NETWORK = "network"  # 网络问题
    TIMEOUT = "timeout"  # 超时问题
    RATE_LIMIT = "rate_limit"  # 频率限制
    RESOURCE_NOT_FOUND = "resource_not_found"  # 资源未找到
    PERMISSION = "permission"  # 权限问题
    VALIDATION = "validation"  # 验证问题
    INTERNAL = "internal"  # 内部错误
    UNKNOWN = "unknown"  # 未知错误


@dataclass
class RootCauseHypothesis:
    """根因假设"""

    hypothesis_id: str
    category: RootCauseCategory
    description: str
    confidence: float = 0.0  # 置信度 (0-1)
    evidence: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hypothesis_id": self.hypothesis_id,
            "category": self.category.value,
            "description": self.description,
            "confidence": self.confidence,
            "evidence": self.evidence,
            "suggestions": self.suggestions,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RootCauseHypothesis":
        return cls(
            hypothesis_id=data["hypothesis_id"],
            category=RootCauseCategory(data["category"]),
            description=data["description"],
            confidence=data.get("confidence", 0.0),
            evidence=data.get("evidence", []),
            suggestions=data.get("suggestions", []),
            metadata=data.get("metadata", {}),
        )


@dataclass
class RootCauseReport:
    """根因分析报告"""

    report_id: str
    tool_name: str
    error_message: str
    timestamp: datetime.datetime
    hypotheses: List[RootCauseHypothesis] = field(default_factory=list)
    primary_hypothesis: Optional[RootCauseHypothesis] = None
    analysis_duration_ms: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "report_id": self.report_id,
            "tool_name": self.tool_name,
            "error_message": self.error_message,
            "timestamp": self.timestamp.isoformat(),
            "hypotheses": [h.to_dict() for h in self.hypotheses],
            "primary_hypothesis": self.primary_hypothesis.to_dict() if self.primary_hypothesis else None,
            "analysis_duration_ms": self.analysis_duration_ms,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RootCauseReport":
        return cls(
            report_id=data["report_id"],
            tool_name=data["tool_name"],
            error_message=data["error_message"],
            timestamp=datetime.datetime.fromisoformat(data["timestamp"]),
            hypotheses=[RootCauseHypothesis.from_dict(h) for h in data.get("hypotheses", [])],
            primary_hypothesis=(
                RootCauseHypothesis.from_dict(data["primary_hypothesis"]) if data.get("primary_hypothesis") else None
            ),
            analysis_duration_ms=data.get("analysis_duration_ms", 0.0),
            metadata=data.get("metadata", {}),
        )


@dataclass
class ToolExecutionRecord:
    """工具执行记录"""

    tool_name: str
    timestamp: datetime.datetime
    success: bool
    error_message: Optional[str] = None
    parameters: Dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "timestamp": self.timestamp.isoformat(),
            "success": self.success,
            "error_message": self.error_message,
            "parameters": self.parameters,
            "duration_ms": self.duration_ms,
            "metadata": self.metadata,
        }


class ToolRootCauseAnalyzer:
    """工具失败根因分析器

    分析工具执行失败的根因，提供改进建议。
    """

    def __init__(
        self,
        max_history_size: int = 1000,
        pattern_detection_threshold: int = 3,
        similarity_threshold: float = 0.7,
    ):
        """初始化根因分析器

        Args:
            max_history_size: 最大历史记录数
            pattern_detection_threshold: 模式检测阈值
            similarity_threshold: 相似度阈值
        """
        self._max_history_size = max_history_size
        self._pattern_detection_threshold = pattern_detection_threshold
        self._similarity_threshold = similarity_threshold

        # 执行历史
        self._execution_history: deque[ToolExecutionRecord] = deque(maxlen=max_history_size)

        # 工具统计
        self._tool_stats: Dict[str, Dict[str, Any]] = defaultdict(
            lambda: {
                "total_executions": 0,
                "success_count": 0,
                "failure_count": 0,
                "recent_failures": deque(maxlen=10),
                "common_errors": defaultdict(int),
            }
        )

        # 分析报告
        self._reports: List[RootCauseReport] = []

        # 错误模式
        self._error_patterns: Dict[str, List[str]] = {
            "parameter_error": [
                r"invalid.*parameter",
                r"missing.*required.*argument",
                r"type.*error",
                r"value.*error",
                r"unexpected.*keyword",
            ],
            "authentication": [
                r"authentication.*failed",
                r"invalid.*token",
                r"expired.*token",
                r"unauthorized",
                r"access.*denied",
            ],
            "network": [
                r"connection.*refused",
                r"timeout",
                r"network.*error",
                r"dns.*resolution.*failed",
                r"ssl.*error",
            ],
            "timeout": [
                r"timeout",
                r"timed.*out",
                r"deadline.*exceeded",
            ],
            "rate_limit": [
                r"rate.*limit",
                r"too.*many.*requests",
                r"throttled",
            ],
            "resource_not_found": [
                r"not.*found",
                r"does.*not.*exist",
                r"resource.*not.*found",
            ],
            "permission": [
                r"permission.*denied",
                r"forbidden",
                r"access.*denied",
            ],
            "validation": [
                r"validation.*failed",
                r"invalid.*format",
                r"schema.*error",
            ],
            "internal": [
                r"internal.*server.*error",
                r"internal.*error",
                r"unexpected.*error",
            ],
        }

        # 线程安全
        self._lock = threading.RLock()

        # 统计信息
        self._stats = {
            "total_analyses": 0,
            "patterns_detected": 0,
            "reports_generated": 0,
        }

        logger.info("ToolRootCauseAnalyzer 初始化完成")

    def record_execution(
        self,
        tool_name: str,
        success: bool,
        error_message: Optional[str] = None,
        parameters: Optional[Dict[str, Any]] = None,
        duration_ms: float = 0.0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """记录工具执行

        Args:
            tool_name: 工具名称
            success: 是否成功
            error_message: 错误信息
            parameters: 执行参数
            duration_ms: 执行时长（毫秒）
            metadata: 附加元数据
        """
        with self._lock:
            # 创建执行记录
            record = ToolExecutionRecord(
                tool_name=tool_name,
                timestamp=datetime.datetime.now(datetime.timezone.utc),
                success=success,
                error_message=error_message,
                parameters=parameters or {},
                duration_ms=duration_ms,
                metadata=metadata or {},
            )

            # 添加到历史
            self._execution_history.append(record)

            # 更新工具统计
            stats = self._tool_stats[tool_name]
            stats["total_executions"] += 1

            if success:
                stats["success_count"] += 1
            else:
                stats["failure_count"] += 1

                # 记录失败信息
                if error_message:
                    stats["recent_failures"].append(
                        {
                            "timestamp": record.timestamp,
                            "error": error_message,
                            "parameters": parameters,
                        }
                    )

                    # 统计常见错误
                    error_type = self._extract_error_type(error_message)
                    stats["common_errors"][error_type] += 1

    def analyze_tool_failure(
        self,
        tool_name: str,
        error_message: str,
        parameters: Optional[Dict[str, Any]] = None,
    ) -> RootCauseReport:
        """分析工具失败

        Args:
            tool_name: 工具名称
            error_message: 错误信息
            parameters: 执行参数

        Returns:
            根因分析报告
        """
        start_time = time.time()

        with self._lock:
            try:
                # 生成报告ID
                report_id = f"rca_{tool_name}_{int(time.time() * 1000)}"

                # 分析错误类型
                error_type = self._extract_error_type(error_message)

                # 生成假设
                hypotheses = self._generate_hypotheses(tool_name, error_message, error_type, parameters)

                # 检测系统性模式
                pattern_hypotheses = self._detect_systemic_patterns(tool_name, error_message, parameters)
                hypotheses.extend(pattern_hypotheses)

                # 选择主要假设
                primary_hypothesis = None
                if hypotheses:
                    # 按置信度排序
                    hypotheses.sort(key=lambda h: h.confidence, reverse=True)
                    primary_hypothesis = hypotheses[0]

                # 创建报告
                report = RootCauseReport(
                    report_id=report_id,
                    tool_name=tool_name,
                    error_message=error_message,
                    timestamp=datetime.datetime.now(datetime.timezone.utc),
                    hypotheses=hypotheses,
                    primary_hypothesis=primary_hypothesis,
                    analysis_duration_ms=(time.time() - start_time) * 1000,
                    metadata={
                        "error_type": error_type,
                        "parameters": parameters,
                    },
                )

                # 保存报告
                self._reports.append(report)
                if len(self._reports) > 100:  # 保留最近100个报告
                    self._reports = self._reports[-100:]

                # 更新统计
                self._stats["total_analyses"] += 1
                self._stats["reports_generated"] += 1

                logger.info("根因分析完成: %s", report_id)
                return report
            except Exception as e:
                logger.error("根因分析失败: %s", e)

                # 返回错误报告
                return RootCauseReport(
                    report_id=f"rca_error_{int(time.time() * 1000)}",
                    tool_name=tool_name,
                    error_message=error_message,
                    timestamp=datetime.datetime.now(datetime.timezone.utc),
                    analysis_duration_ms=(time.time() - start_time) * 1000,
                    metadata={"analysis_error": str(e)},
                )

    def _extract_error_type(self, error_message: str) -> str:
        """提取错误类型

        Args:
            error_message: 错误信息

        Returns:
            错误类型
        """
        error_lower = error_message.lower()

        for error_type, patterns in self._error_patterns.items():
            for pattern in patterns:
                if re.search(pattern, error_lower):
                    return error_type

        return "unknown"

    def _generate_hypotheses(
        self,
        tool_name: str,
        error_message: str,
        error_type: str,
        parameters: Optional[Dict[str, Any]] = None,
    ) -> List[RootCauseHypothesis]:
        """生成假设

        Args:
            tool_name: 工具名称
            error_message: 错误信息
            error_type: 错误类型
            parameters: 执行参数

        Returns:
            假设列表
        """
        hypotheses = []

        # 基于错误类型的假设
        if error_type == "parameter_error":
            hypotheses.append(
                RootCauseHypothesis(
                    hypothesis_id=f"param_{int(time.time())}",
                    category=RootCauseCategory.PARAMETER_ERROR,
                    description=f"参数错误: {error_message}",
                    confidence=0.8,
                    evidence=[f"错误信息: {error_message}"],
                    suggestions=self._generate_suggestion(error_type, tool_name),
                )
            )
        elif error_type == "authentication":
            hypotheses.append(
                RootCauseHypothesis(
                    hypothesis_id=f"auth_{int(time.time())}",
                    category=RootCauseCategory.AUTHENTICATION,
                    description=f"认证问题: {error_message}",
                    confidence=0.9,
                    evidence=[f"错误信息: {error_message}"],
                    suggestions=self._generate_suggestion(error_type, tool_name),
                )
            )
        elif error_type == "network":
            hypotheses.append(
                RootCauseHypothesis(
                    hypothesis_id=f"network_{int(time.time())}",
                    category=RootCauseCategory.NETWORK,
                    description=f"网络问题: {error_message}",
                    confidence=0.7,
                    evidence=[f"错误信息: {error_message}"],
                    suggestions=self._generate_suggestion(error_type, tool_name),
                )
            )
        elif error_type == "timeout":
            hypotheses.append(
                RootCauseHypothesis(
                    hypothesis_id=f"timeout_{int(time.time())}",
                    category=RootCauseCategory.TIMEOUT,
                    description=f"超时问题: {error_message}",
                    confidence=0.8,
                    evidence=[f"错误信息: {error_message}"],
                    suggestions=self._generate_suggestion(error_type, tool_name),
                )
            )
        elif error_type == "rate_limit":
            hypotheses.append(
                RootCauseHypothesis(
                    hypothesis_id=f"rate_{int(time.time())}",
                    category=RootCauseCategory.RATE_LIMIT,
                    description=f"频率限制: {error_message}",
                    confidence=0.9,
                    evidence=[f"错误信息: {error_message}"],
                    suggestions=self._generate_suggestion(error_type, tool_name),
                )
            )
        elif error_type == "resource_not_found":
            hypotheses.append(
                RootCauseHypothesis(
                    hypothesis_id=f"notfound_{int(time.time())}",
                    category=RootCauseCategory.RESOURCE_NOT_FOUND,
                    description=f"资源未找到: {error_message}",
                    confidence=0.8,
                    evidence=[f"错误信息: {error_message}"],
                    suggestions=self._generate_suggestion(error_type, tool_name),
                )
            )
        elif error_type == "permission":
            hypotheses.append(
                RootCauseHypothesis(
                    hypothesis_id=f"perm_{int(time.time())}",
                    category=RootCauseCategory.PERMISSION,
                    description=f"权限问题: {error_message}",
                    confidence=0.8,
                    evidence=[f"错误信息: {error_message}"],
                    suggestions=self._generate_suggestion(error_type, tool_name),
                )
            )
        elif error_type == "validation":
            hypotheses.append(
                RootCauseHypothesis(
                    hypothesis_id=f"valid_{int(time.time())}",
                    category=RootCauseCategory.VALIDATION,
                    description=f"验证问题: {error_message}",
                    confidence=0.7,
                    evidence=[f"错误信息: {error_message}"],
                    suggestions=self._generate_suggestion(error_type, tool_name),
                )
            )
        elif error_type == "internal":
            hypotheses.append(
                RootCauseHypothesis(
                    hypothesis_id=f"internal_{int(time.time())}",
                    category=RootCauseCategory.INTERNAL,
                    description=f"内部错误: {error_message}",
                    confidence=0.6,
                    evidence=[f"错误信息: {error_message}"],
                    suggestions=self._generate_suggestion(error_type, tool_name),
                )
            )
        else:
            hypotheses.append(
                RootCauseHypothesis(
                    hypothesis_id=f"unknown_{int(time.time())}",
                    category=RootCauseCategory.UNKNOWN,
                    description=f"未知错误: {error_message}",
                    confidence=0.5,
                    evidence=[f"错误信息: {error_message}"],
                    suggestions=self._generate_suggestion(error_type, tool_name),
                )
            )

        return hypotheses

    def _detect_systemic_patterns(
        self,
        tool_name: str,
        error_message: str,
        parameters: Optional[Dict[str, Any]] = None,
    ) -> List[RootCauseHypothesis]:
        """检测系统性模式

        Args:
            tool_name: 工具名称
            error_message: 错误信息

        Returns:
            假设列表
        """
        hypotheses = []

        # 获取工具统计
        stats = self._tool_stats[tool_name]
        recent_failures = stats["recent_failures"]

        # 检测连续失败模式
        if len(recent_failures) >= self._pattern_detection_threshold:
            # 检查最近的失败是否相似
            similar_failures = 0
            for failure in recent_failures:
                if self._is_similar_error(error_message, failure["error"]):
                    similar_failures += 1

            if similar_failures >= self._pattern_detection_threshold:
                hypotheses.append(
                    RootCauseHypothesis(
                        hypothesis_id=f"pattern_{tool_name}_{int(time.time())}",
                        category=RootCauseCategory.INTERNAL,
                        description=f"检测到系统性缺陷模式: {tool_name} 连续 {similar_failures} 次出现相似错误",
                        confidence=0.9,
                        evidence=[
                            f"连续 {similar_failures} 次相似错误",
                            f"最近错误: {error_message}",
                        ],
                        suggestions=[
                            f"建议检查 {tool_name} 的实现",
                            f"建议检查参数验证逻辑",
                            f"建议添加错误处理和重试机制",
                        ],
                    )
                )

        # 检测参数范围问题
        if parameters:
            param_hypothesis = self._check_parameter_range(tool_name, parameters)
            if param_hypothesis:
                hypotheses.append(param_hypothesis)

        return hypotheses

    def _is_similar_error(self, error1: str, error2: str) -> bool:
        """判断错误是否相似

        Args:
            error1: 错误1
            error2: 错误2

        Returns:
            是否相似
        """
        # 简单的相似度判断
        error1_lower = error1.lower()
        error2_lower = error2.lower()

        # 提取关键部分
        keywords1 = set(re.findall(r"\w+", error1_lower))
        keywords2 = set(re.findall(r"\w+", error2_lower))

        if not keywords1 or not keywords2:
            return False

        # 计算Jaccard相似度
        intersection = len(keywords1 & keywords2)
        union = len(keywords1 | keywords2)

        similarity = intersection / union if union > 0 else 0.0

        return similarity >= self._similarity_threshold

    def _check_parameter_range(
        self,
        tool_name: str,
        parameters: Dict[str, Any],
    ) -> Optional[RootCauseHypothesis]:
        """检查参数范围

        Args:
            tool_name: 工具名称
            parameters: 参数

        Returns:
            假设（如果有）
        """
        # 获取历史成功的参数
        successful_params = []
        for record in self._execution_history:
            if record.tool_name == tool_name and record.success:
                successful_params.append(record.parameters)

        if not successful_params:
            return None

        # 检查参数是否在历史成功范围内
        for param_name, param_value in parameters.items():
            # 获取历史值
            historical_values = [p.get(param_name) for p in successful_params if param_name in p]

            if historical_values:
                # 检查类型一致性
                if historical_values and type(param_value) != type(historical_values[0]):
                    return RootCauseHypothesis(
                        hypothesis_id=f"param_range_{tool_name}_{param_name}_{int(time.time())}",
                        category=RootCauseCategory.PARAMETER_ERROR,
                        description=f"参数 '{param_name}' 类型不匹配",
                        confidence=0.7,
                        evidence=[
                            f"当前类型: {type(param_value).__name__}",
                            f"历史类型: {type(historical_values[0]).__name__}",
                        ],
                        suggestions=[
                            f"检查参数 '{param_name}' 的类型",
                            f"历史成功值: {historical_values[:3]}",
                        ],
                    )

        return None

    def _generate_suggestion(self, error_type: str, tool_name: str) -> List[str]:
        """生成建议

        Args:
            error_type: 错误类型
            tool_name: 工具名称

        Returns:
            建议列表
        """
        suggestions = []

        if error_type == "parameter_error":
            suggestions.extend(
                [
                    f"检查 {tool_name} 的参数格式",
                    "验证必需参数是否提供",
                    "检查参数类型是否正确",
                ]
            )
        elif error_type == "authentication":
            suggestions.extend(
                [
                    "检查认证凭据是否有效",
                    "检查token是否过期",
                    "重新获取认证凭据",
                ]
            )
        elif error_type == "network":
            suggestions.extend(
                [
                    "检查网络连接",
                    "检查目标服务是否可用",
                    "稍后重试",
                ]
            )
        elif error_type == "timeout":
            suggestions.extend(
                [
                    "增加超时时间",
                    "减少请求负载",
                    "检查网络延迟",
                ]
            )
        elif error_type == "rate_limit":
            suggestions.extend(
                [
                    "降低请求频率",
                    "实现指数退避重试",
                    "检查API配额",
                ]
            )
        elif error_type == "resource_not_found":
            suggestions.extend(
                [
                    "检查资源ID是否正确",
                    "检查资源是否存在",
                    "检查访问权限",
                ]
            )
        elif error_type == "permission":
            suggestions.extend(
                [
                    "检查权限配置",
                    "确认有权访问该资源",
                    "联系管理员获取权限",
                ]
            )
        elif error_type == "validation":
            suggestions.extend(
                [
                    "检查输入数据格式",
                    "验证数据是否符合schema",
                    "检查必填字段",
                ]
            )
        elif error_type == "internal":
            suggestions.extend(
                [
                    "稍后重试",
                    "检查服务状态",
                    "联系技术支持",
                ]
            )
        else:
            suggestions.extend(
                [
                    "检查错误详情",
                    "查看系统日志",
                    "联系技术支持",
                ]
            )

        return suggestions

    def get_failure_stats(self, tool_name: Optional[str] = None) -> Dict[str, Any]:
        """获取失败统计

        Args:
            tool_name: 工具名称（可选）

        Returns:
            统计信息
        """
        with self._lock:
            if tool_name:
                stats = self._tool_stats[tool_name]
                total = stats["total_executions"]
                success_rate = stats["success_count"] / total if total > 0 else 0.0

                return {
                    "tool_name": tool_name,
                    "total_executions": total,
                    "success_count": stats["success_count"],
                    "failure_count": stats["failure_count"],
                    "success_rate": success_rate,
                    "common_errors": dict(stats["common_errors"]),
                }
            else:
                # 返回所有工具的统计
                all_stats = {}
                for name, stats in self._tool_stats.items():
                    total = stats["total_executions"]
                    success_rate = stats["success_count"] / total if total > 0 else 0.0

                    all_stats[name] = {
                        "total_executions": total,
                        "success_count": stats["success_count"],
                        "failure_count": stats["failure_count"],
                        "success_rate": success_rate,
                    }

                return all_stats

    def get_recent_failures(
        self,
        tool_name: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """获取最近失败

        Args:
            tool_name: 工具名称（可选）
            limit: 返回数量限制

        Returns:
            失败记录列表
        """
        with self._lock:
            failures = []

            for record in self._execution_history:
                if not record.success:
                    if tool_name is None or record.tool_name == tool_name:
                        failures.append(record.to_dict())

            return failures[-limit:]

    def get_tool_health(self, tool_name: str) -> Dict[str, Any]:
        """获取工具健康状态

        Args:
            tool_name: 工具名称

        Returns:
            健康状态
        """
        with self._lock:
            stats = self._tool_stats[tool_name]
            total = stats["total_executions"]

            if total == 0:
                return {
                    "tool_name": tool_name,
                    "status": "unknown",
                    "message": "没有执行记录",
                }

            success_rate = stats["success_count"] / total

            # 确定健康状态
            if success_rate >= 0.9:
                status = "healthy"
                message = "工具运行正常"
            elif success_rate >= 0.7:
                status = "warning"
                message = "工具成功率较低"
            elif success_rate >= 0.5:
                status = "degraded"
                message = "工具性能下降"
            else:
                status = "unhealthy"
                message = "工具存在严重问题"

            return {
                "tool_name": tool_name,
                "status": status,
                "success_rate": success_rate,
                "total_executions": total,
                "failure_count": stats["failure_count"],
                "common_errors": dict(stats["common_errors"]),
                "message": message,
            }

    def get_degraded_tools(self, threshold: float = 0.7) -> List[Dict[str, Any]]:
        """获取性能下降的工具

        Args:
            threshold: 成功率阈值

        Returns:
            工具列表
        """
        with self._lock:
            degraded = []

            for tool_name, stats in self._tool_stats.items():
                total = stats["total_executions"]
                if total >= 5:  # 至少5次执行
                    success_rate = stats["success_count"] / total
                    if success_rate < threshold:
                        degraded.append(
                            {
                                "tool_name": tool_name,
                                "success_rate": success_rate,
                                "failure_count": stats["failure_count"],
                                "common_errors": dict(stats["common_errors"]),
                            }
                        )

            return degraded

    def get_reports(self, limit: int = 50) -> List[RootCauseReport]:
        """获取分析报告

        Args:
            limit: 返回数量限制

        Returns:
            报告列表
        """
        with self._lock:
            return self._reports[-limit:]

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息

        Returns:
            统计信息字典
        """
        with self._lock:
            return {
                **self._stats,
                "total_tools": len(self._tool_stats),
                "history_size": len(self._execution_history),
                "reports_count": len(self._reports),
            }

    def reset(self) -> None:
        """重置分析器"""
        with self._lock:
            self._execution_history.clear()
            self._tool_stats.clear()
            self._reports.clear()

            self._stats = {
                "total_analyses": 0,
                "patterns_detected": 0,
                "reports_generated": 0,
            }

            logger.info("ToolRootCauseAnalyzer 已重置")


# 全局实例管理
_root_cause_analyzer: Optional[ToolRootCauseAnalyzer] = None
_root_cause_analyzer_lock = threading.Lock()


def get_root_cause_analyzer() -> ToolRootCauseAnalyzer:
    """获取根因分析器单例

    Returns:
        根因分析器实例
    """
    global _root_cause_analyzer

    with _root_cause_analyzer_lock:
        if _root_cause_analyzer is None:
            _root_cause_analyzer = ToolRootCauseAnalyzer()
        return _root_cause_analyzer


def reset_root_cause_analyzer() -> None:
    """重置根因分析器单例"""
    global _root_cause_analyzer

    with _root_cause_analyzer_lock:
        if _root_cause_analyzer is not None:
            _root_cause_analyzer.reset()
            _root_cause_analyzer = None
