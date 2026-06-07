"""
技能自动改进 (AutoSkillImprover)

基于技能使用反馈自动改进已有技能:

1. 失败模式检测 — 识别技能在什么情况下失效
2. 改进建议生成 — 根据失败原因提出具体改进
3. 技能变体创建 — 生成改进后的技能变体
4. A/B 效果对比 — 追踪变体与原版的效果差异

改进策略:
- 参数调优：调整技能参数以提高成功率
- 错误处理：增强异常处理和容错能力
- 性能优化：优化执行路径和资源使用
- 功能扩展：添加缺失的功能或能力
"""

from dataclasses import dataclass, field
import datetime
import logging
import re
import time
import threading
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ────── Enums ──────

class ImprovementType(Enum):
    """改进类型"""
    PARAMETER_TUNING = "parameter_tuning"       # 参数调优
    ERROR_HANDLING = "error_handling"           # 错误处理增强
    PERFORMANCE = "performance"                 # 性能优化
    FUNCTIONALITY = "functionality"             # 功能扩展
    RELIABILITY = "reliability"                 # 可靠性提升


class FailurePattern(Enum):
    """失败模式"""
    TIMEOUT = "timeout"                         # 超时
    INVALID_INPUT = "invalid_input"            # 输入无效
    RESOURCE_ERROR = "resource_error"           # 资源错误
    DEPENDENCY_FAILURE = "dependency_failure"   # 依赖失败
    LOGIC_ERROR = "logic_error"                # 逻辑错误
    UNKNOWN = "unknown"                        # 未知错误


# ────── Data Models ──────

@dataclass
class SkillImprovement:
    """技能改进记录"""
    improvement_id: str = ""
    skill_id: str = ""
    improvement_type: ImprovementType = ImprovementType.PARAMETER_TUNING
    description: str = ""
    changes: Dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    expected_impact: float = 0.0
    created_at: datetime.datetime = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc))
    applied: bool = False
    applied_at: Optional[datetime.datetime] = None


@dataclass
class SkillVariant:
    """技能变体"""
    variant_id: str = ""
    original_skill_id: str = ""
    name: str = ""
    description: str = ""
    changes: Dict[str, Any] = field(default_factory=dict)
    success_count: int = 0
    failure_count: int = 0
    total_uses: int = 0
    avg_duration: float = 0.0
    created_at: datetime.datetime = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc))
    last_used: Optional[datetime.datetime] = None
    is_active: bool = True


@dataclass
class UsageRecord:
    """使用记录"""
    skill_id: str = ""
    variant_id: str = ""
    success: bool = False
    duration: float = 0.0
    error_message: str = ""
    input_summary: str = ""
    output_summary: str = ""
    timestamp: datetime.datetime = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc))
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class FailureAnalysis:
    """失败分析结果"""
    pattern: FailurePattern = FailurePattern.UNKNOWN
    frequency: int = 0
    examples: List[str] = field(default_factory=list)
    suggested_fix: str = ""
    confidence: float = 0.0


# ────── 主类 ──────

class AutoSkillImprover:
    """
    技能自动改进器

    基于使用反馈自动分析失败模式、生成改进建议、创建变体并进行 A/B 测试。
    """

    def __init__(self, min_records_for_analysis: int = 10,
                 failure_threshold: float = 0.3,
                 max_variants_per_skill: int = 5):
        """
        初始化技能改进器

        参数:
            min_records_for_analysis: 触发分析的最小记录数
            failure_threshold: 触发改进的失败率阈值
            max_variants_per_skill: 每个技能的最大变体数
        """
        self._min_records = min_records_for_analysis
        self._failure_threshold = failure_threshold
        self._max_variants = max_variants_per_skill
        self._lock = threading.RLock()

        # 使用记录
        self._usage_records: Dict[str, List[UsageRecord]] = {}  # skill_id -> records

        # 改进历史
        self._improvements: Dict[str, List[SkillImprovement]] = {}  # skill_id -> improvements

        # 变体追踪
        self._variants: Dict[str, List[SkillVariant]] = {}  # skill_id -> variants

        logger.info("AutoSkillImprover initialized")

    def record_usage(self, skill_id: str, success: bool, duration: float = 0.0,
                    error_message: str = "", input_summary: str = "",
                    output_summary: str = "", variant_id: str = "",
                    metadata: Optional[Dict[str, Any]] = None):
        """
        记录技能使用

        参数:
            skill_id: 技能ID
            success: 是否成功
            duration: 执行时长
            error_message: 错误信息
            input_summary: 输入摘要
            output_summary: 输出摘要
            variant_id: 变体ID（空表示原版）
            metadata: 元数据
        """
        with self._lock:
            record = UsageRecord(
                skill_id=skill_id,
                variant_id=variant_id,
                success=success,
                duration=duration,
                error_message=error_message,
                input_summary=input_summary,
                output_summary=output_summary,
                metadata=metadata or {},
            )

            if skill_id not in self._usage_records:
                self._usage_records[skill_id] = []
            self._usage_records[skill_id].append(record)

            # 更新变体统计
            if variant_id:
                self._update_variant_stats(variant_id, success, duration)

    def _update_variant_stats(self, variant_id: str, success: bool, duration: float):
        """更新变体统计"""
        for variants in self._variants.values():
            for variant in variants:
                if variant.variant_id == variant_id:
                    variant.total_uses += 1
                    if success:
                        variant.success_count += 1
                    else:
                        variant.failure_count += 1
                    # 更新平均时长
                    variant.avg_duration = (
                        (variant.avg_duration * (variant.total_uses - 1) + duration)
                        / variant.total_uses
                    )
                    variant.last_used = datetime.datetime.now(datetime.timezone.utc)
                    return

    def get_usage_history(self, skill_id: str, limit: int = 100) -> List[UsageRecord]:
        """获取使用历史"""
        with self._lock:
            records = self._usage_records.get(skill_id, [])
            return records[-limit:]

    def propose_improvements(self, skill_id: str) -> List[SkillImprovement]:
        """
        为技能提出改进建议

        参数:
            skill_id: 技能ID

        返回:
            List[SkillImprovement]: 改进建议列表
        """
        with self._lock:
            records = self._usage_records.get(skill_id, [])
            if len(records) < self._min_records:
                return []

            # 分析失败模式
            failure_analysis = self._analyze_failure_pattern(skill_id)

            # 生成改进建议
            improvements = []
            for analysis in failure_analysis:
                if analysis.confidence < 0.5:
                    continue

                improvement = self._generate_improvement(skill_id, analysis)
                if improvement:
                    improvements.append(improvement)

            # 存储改进建议
            self._improvements.setdefault(skill_id, []).extend(improvements)

            return improvements

    def _analyze_failure_pattern(self, skill_id: str) -> List[FailureAnalysis]:
        """分析失败模式"""
        records = self._usage_records.get(skill_id, [])
        failed_records = [r for r in records if not r.success]

        if not failed_records:
            return []

        # 按错误消息分组
        error_groups: Dict[str, List[UsageRecord]] = {}
        for record in failed_records:
            error_key = self._classify_error(record.error_message)
            error_groups.setdefault(error_key, []).append(record)

        analyses = []
        for error_key, group in error_groups.items():
            analysis = FailureAnalysis(
                pattern=FailurePattern(error_key),
                frequency=len(group),
                examples=[r.error_message for r in group[:3]],
                confidence=min(1.0, len(group) / max(1, len(failed_records))),
            )

            # 生成修复建议
            analysis.suggested_fix = self._suggest_fix(analysis.pattern, group)

            analyses.append(analysis)

        # 按频率排序
        analyses.sort(key=lambda a: a.frequency, reverse=True)

        return analyses

    def _classify_error(self, error_message: str) -> str:
        """分类错误消息"""
        error_lower = error_message.lower()

        if "timeout" in error_lower or "超时" in error_lower:
            return FailurePattern.TIMEOUT.value
        elif "invalid" in error_lower or "无效" in error_lower or "validation" in error_lower:
            return FailurePattern.INVALID_INPUT.value
        elif "resource" in error_lower or "资源" in error_lower or "memory" in error_lower:
            return FailurePattern.RESOURCE_ERROR.value
        elif "dependency" in error_lower or "依赖" in error_lower or "import" in error_lower:
            return FailurePattern.DEPENDENCY_FAILURE.value
        else:
            return FailurePattern.UNKNOWN.value

    def _suggest_fix(self, pattern: FailurePattern,
                    records: List[UsageRecord]) -> str:
        """生成修复建议"""
        suggestions = {
            FailurePattern.TIMEOUT: "增加超时时间或优化执行路径",
            FailurePattern.INVALID_INPUT: "添加输入验证和预处理",
            FailurePattern.RESOURCE_ERROR: "添加资源检查和清理逻辑",
            FailurePattern.DEPENDENCY_FAILURE: "添加依赖检查和降级策略",
            FailurePattern.LOGIC_ERROR: "检查核心逻辑和边界条件",
            FailurePattern.UNKNOWN: "添加详细日志以便进一步分析",
        }
        return suggestions.get(pattern, "需要进一步分析")

    def _generate_improvement(self, skill_id: str,
                             analysis: FailureAnalysis) -> Optional[SkillImprovement]:
        """根据分析生成改进建议"""
        improvement_type = {
            FailurePattern.TIMEOUT: ImprovementType.PERFORMANCE,
            FailurePattern.INVALID_INPUT: ImprovementType.ERROR_HANDLING,
            FailurePattern.RESOURCE_ERROR: ImprovementType.RELIABILITY,
            FailurePattern.DEPENDENCY_FAILURE: ImprovementType.RELIABILITY,
            FailurePattern.LOGIC_ERROR: ImprovementType.FUNCTIONALITY,
        }.get(analysis.pattern, ImprovementType.ERROR_HANDLING)

        return SkillImprovement(
            improvement_id=f"imp_{skill_id}_{int(time.time())}",
            skill_id=skill_id,
            improvement_type=improvement_type,
            description=f"针对 {analysis.pattern.value} 模式的改进",
            changes={"suggested_fix": analysis.suggested_fix},
            reason=f"检测到 {analysis.frequency} 次 {analysis.pattern.value} 错误",
            expected_impact=min(1.0, analysis.frequency / 10.0),
        )

    def create_variant(self, skill_id: str, name: str,
                      changes: Dict[str, Any],
                      description: str = "") -> SkillVariant:
        """
        创建技能变体

        参数:
            skill_id: 原始技能ID
            name: 变体名称
            changes: 变更内容
            description: 描述

        返回:
            SkillVariant: 创建的变体
        """
        with self._lock:
            # 检查变体数量限制
            existing = self._variants.get(skill_id, [])
            if len(existing) >= self._max_variants:
                # 移除表现最差的变体
                existing.sort(key=lambda v: v.success_count / max(1, v.total_uses))
                existing.pop(0)

            variant = SkillVariant(
                variant_id=f"var_{skill_id}_{int(time.time())}",
                original_skill_id=skill_id,
                name=name,
                description=description,
                changes=changes,
            )

            self._variants.setdefault(skill_id, []).append(variant)

            logger.info(f"Created variant {variant.variant_id} for skill {skill_id}")
            return variant

    def get_improvement_history(self, skill_id: str) -> List[SkillImprovement]:
        """获取改进历史"""
        with self._lock:
            return self._improvements.get(skill_id, [])

    def get_skill_stats(self, skill_id: str) -> Dict[str, Any]:
        """获取技能统计信息"""
        with self._lock:
            records = self._usage_records.get(skill_id, [])
            if not records:
                return {"skill_id": skill_id, "total_uses": 0}

            total = len(records)
            successes = sum(1 for r in records if r.success)
            failures = total - successes
            avg_duration = sum(r.duration for r in records) / total

            # 变体统计
            variants = self._variants.get(skill_id, [])
            variant_stats = []
            for v in variants:
                variant_stats.append({
                    "variant_id": v.variant_id,
                    "name": v.name,
                    "success_rate": v.success_count / max(1, v.total_uses),
                    "total_uses": v.total_uses,
                    "avg_duration": v.avg_duration,
                })

            return {
                "skill_id": skill_id,
                "total_uses": total,
                "success_count": successes,
                "failure_count": failures,
                "success_rate": successes / total,
                "avg_duration": round(avg_duration, 3),
                "improvements_proposed": len(self._improvements.get(skill_id, [])),
                "variants": len(variants),
                "variant_details": variant_stats,
            }

    def get_variant_comparison(self, skill_id: str) -> Dict[str, Any]:
        """
        获取变体对比数据

        返回原版和各变体的效果对比
        """
        with self._lock:
            records = self._usage_records.get(skill_id, [])
            variants = self._variants.get(skill_id, [])

            # 原版统计
            original_records = [r for r in records if not r.variant_id]
            original_stats = {
                "name": "original",
                "total_uses": len(original_records),
                "success_rate": sum(1 for r in original_records if r.success) / max(1, len(original_records)),
                "avg_duration": sum(r.duration for r in original_records) / max(1, len(original_records)),
            }

            # 变体统计
            variant_stats = []
            for v in variants:
                variant_records = [r for r in records if r.variant_id == v.variant_id]
                variant_stats.append({
                    "variant_id": v.variant_id,
                    "name": v.name,
                    "total_uses": len(variant_records),
                    "success_rate": v.success_count / max(1, v.total_uses),
                    "avg_duration": v.avg_duration,
                })

            return {
                "skill_id": skill_id,
                "original": original_stats,
                "variants": variant_stats,
            }

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典"""
        with self._lock:
            return {
                "usage_records": {
                    skill_id: [
                        {
                            "skill_id": r.skill_id,
                            "variant_id": r.variant_id,
                            "success": r.success,
                            "duration": r.duration,
                            "error_message": r.error_message,
                            "timestamp": r.timestamp.isoformat(),
                        }
                        for r in records
                    ]
                    for skill_id, records in self._usage_records.items()
                },
                "improvements": {
                    skill_id: [
                        {
                            "improvement_id": i.improvement_id,
                            "skill_id": i.skill_id,
                            "improvement_type": i.improvement_type.value,
                            "description": i.description,
                            "applied": i.applied,
                        }
                        for i in imps
                    ]
                    for skill_id, imps in self._improvements.items()
                },
                "variants": {
                    skill_id: [
                        {
                            "variant_id": v.variant_id,
                            "original_skill_id": v.original_skill_id,
                            "name": v.name,
                            "success_count": v.success_count,
                            "failure_count": v.failure_count,
                            "total_uses": v.total_uses,
                        }
                        for v in variants
                    ]
                    for skill_id, variants in self._variants.items()
                },
            }


# ────── 单例管理 ──────

_improver_instance: Optional[AutoSkillImprover] = None
_instance_lock = threading.Lock()


def get_skill_improver(**kwargs) -> AutoSkillImprover:
    """获取技能改进器单例"""
    global _improver_instance
    if _improver_instance is None:
        with _instance_lock:
            if _improver_instance is None:
                _improver_instance = AutoSkillImprover(**kwargs)
    return _improver_instance


def reset_skill_improver():
    """重置技能改进器单例"""
    global _improver_instance
    with _instance_lock:
        _improver_instance = None