from __future__ import annotations

"""
Skill System 2.0 数据模型

定义技能系统中使用的数据类。
包括：SkillSource, SkillInfo, SkillEvolutionRecord, ExperienceRecord
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional


class SkillSource(Enum):
    """技能来源"""

    LOCAL = "local"
    MARKETPLACE = "marketplace"
    BUILTIN = "builtin"


@dataclass
class SkillMetadata:
    """技能元数据"""

    name: str = ""
    version: str = "1.0.0"
    description: str = ""
    author: str = ""
    tags: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)


@dataclass
class Skill:
    """技能主模型"""

    id: str = ""
    name: str = ""
    version: str = "1.0.0"
    description: str = ""
    author: str = ""
    source: SkillSource = SkillSource.LOCAL
    enabled: bool = True
    metadata: Optional[SkillMetadata] = None
    config: Dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""


@dataclass
class SkillVersion:
    """技能版本"""

    version: str = ""
    changelog: str = ""
    created_at: str = ""


@dataclass
class SkillDependency:
    """技能依赖"""

    name: str = ""
    version_range: str = ""


@dataclass
class SkillParameter:
    """技能参数"""

    name: str = ""
    type: str = "string"
    required: bool = False
    default: Any = None
    description: str = ""


@dataclass
class SkillOutput:
    """技能输出"""

    name: str = ""
    type: str = "string"
    description: str = ""


@dataclass
class SkillRequirement:
    """技能需求"""

    capability: str = ""
    min_version: str = ""


@dataclass
class SkillConflict:
    """技能冲突"""

    skill_name: str = ""
    reason: str = ""


@dataclass
class SkillRecommendation:
    """技能推荐"""

    skill_name: str = ""
    score: float = 0.0
    reason: str = ""


@dataclass
class SkillExecutionResult:
    """技能执行结果"""

    success: bool = False
    output: Any = None
    error: str = ""
    duration: float = 0.0


@dataclass
class SkillSearchResult:
    """技能搜索结果"""

    skills: List[Skill] = field(default_factory=list)
    total: int = 0
    page: int = 1


@dataclass
class SkillInstallResult:
    """技能安装结果"""

    success: bool = False
    skill: Optional[Skill] = None
    error: str = ""


@dataclass
class SkillMarketResult:
    """技能市场结果"""

    skills: List[Skill] = field(default_factory=list)
    total: int = 0


@dataclass
class SkillUpdateResult:
    """技能更新结果"""

    success: bool = False
    skill: Optional[Skill] = None
    error: str = ""


@dataclass
class SkillUninstallResult:
    """技能卸载结果"""

    success: bool = False
    error: str = ""


@dataclass
class SkillEnableResult:
    """技能启用结果"""

    success: bool = False
    error: str = ""


@dataclass
class SkillDisableResult:
    """技能禁用结果"""

    success: bool = False
    error: str = ""


@dataclass
class SkillVerifyResult:
    """技能验证结果"""

    valid: bool = False
    errors: List[str] = field(default_factory=list)


@dataclass
class SkillPublishResult:
    """技能发布结果"""

    success: bool = False
    error: str = ""


@dataclass
class SkillDependencyResult:
    """技能依赖解析结果"""

    resolved: bool = False
    missing: List[str] = field(default_factory=list)


@dataclass
class SkillConflictResult:
    """技能冲突检测结果"""

    conflicts: List[SkillConflict] = field(default_factory=list)


@dataclass
class SkillRecommendationResult:
    """技能推荐结果"""

    recommendations: List[SkillRecommendation] = field(default_factory=list)


@dataclass
class SkillExecutionLog:
    """技能执行日志"""

    skill_id: str = ""
    start_time: str = ""
    end_time: str = ""
    success: bool = False
    output: str = ""
    error: str = ""


@dataclass
class SkillMarketplaceStats:
    """技能市场统计"""

    total_skills: int = 0
    total_downloads: int = 0
    total_authors: int = 0


@dataclass
class SkillSearchStats:
    """技能搜索统计"""

    total_queries: int = 0
    avg_results: float = 0.0


@dataclass
class SkillInstallStats:
    """技能安装统计"""

    total_installed: int = 0
    success_rate: float = 0.0


@dataclass
class SkillUpdateStats:
    """技能更新统计"""

    total_updates: int = 0
    success_rate: float = 0.0


@dataclass
class SkillUninstallStats:
    """技能卸载统计"""

    total_uninstalled: int = 0
    success_rate: float = 0.0


@dataclass
class SkillEnableStats:
    """技能启用统计"""

    total_enabled: int = 0


@dataclass
class SkillDisableStats:
    """技能禁用统计"""

    total_disabled: int = 0


@dataclass
class SkillVerifyStats:
    """技能验证统计"""

    total_verified: int = 0
    success_rate: float = 0.0


@dataclass
class SkillPublishStats:
    """技能发布统计"""

    total_published: int = 0
    success_rate: float = 0.0


@dataclass
class SkillDependencyStats:
    """技能依赖统计"""

    total_resolved: int = 0
    total_missing: int = 0


@dataclass
class SkillConflictStats:
    """技能冲突统计"""

    total_conflicts: int = 0
    resolved: int = 0


@dataclass
class SkillRecommendationStats:
    """技能推荐统计"""

    total_recommendations: int = 0
    avg_score: float = 0.0


@dataclass
class SkillExecutionStats:
    """技能执行统计"""

    total_executions: int = 0
    success_rate: float = 0.0
    avg_duration: float = 0.0


@dataclass
class ExperienceRecord:
    """经验记录

    2.0 契约（来源：tests/test_experience_knowledge_base.py + 设计文档
    docs/dev_progress/module_designs/experience_knowledge_base.md）：
    - skill_name: 关联的技能名
    - context: 调用上下文 (通常含 user_input/topic)
    - result: 技能输出结果 (失败时可为 None)
    - success: 是否成功
    - timestamp: ISO 字符串
    - feedback: 用户/系统反馈
    """

    skill_name: str = ""
    context: Dict[str, Any] = field(default_factory=dict)
    result: Optional[Dict[str, Any]] = None
    success: bool = False
    timestamp: str = ""
    feedback: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "skill_name": self.skill_name,
            "context": dict(self.context) if self.context else {},
            "result": dict(self.result) if self.result else None,
            "success": self.success,
            "timestamp": self.timestamp,
            "feedback": self.feedback,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExperienceRecord":
        return cls(
            skill_name=data.get("skill_name", ""),
            context=dict(data.get("context", {})) if data.get("context") else {},
            result=dict(data.get("result")) if data.get("result") else None,
            success=bool(data.get("success", False)),
            timestamp=data.get("timestamp", ""),
            feedback=data.get("feedback", ""),
        )


# Alias for backward compatibility
SkillInfo = Skill
SkillSource = SkillSource
SkillEvolutionRecord = SkillExecutionLog
SkillManifest = Skill
PluginEntryPoints = Dict[str, Any]
SkillRecord = Skill


# Meta-skill 集成数据模型


class OptimizationGoal(Enum):
    """优化目标"""

    CLARITY = "clarity"
    SPECIFICITY = "specificity"
    CONCISENESS = "conciseness"
    COMPLETENESS = "completeness"
    PERFORMANCE = "performance"
    SECURITY = "security"


class ChainStatus(Enum):
    """技能链状态"""

    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepStatus(Enum):
    """步骤状态"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class SkillGenerationResult:
    """技能生成结果"""

    success: bool = False
    skill_code: str = ""
    skill_config: Dict[str, Any] = field(default_factory=dict)
    skill_name: str = ""
    error: str = ""
    warnings: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SkillRefinementResult:
    """技能优化结果"""

    success: bool = False
    improved: bool = False
    original_skill_id: str = ""
    refined_code: str = ""
    changes: List[str] = field(default_factory=list)
    error: str = ""


@dataclass
class SkillValidationResult:
    """技能验证结果"""

    valid: bool = False
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)
    complexity_score: float = 0.0
    security_score: float = 0.0


@dataclass
class ProjectAnalysisResult:
    """项目分析结果"""

    project_path: str = ""
    files: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    main_function: str = ""
    complexity_score: float = 0.0
    entry_points: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExtractedSkill:
    """提取的技能"""

    skill_name: str = ""
    code: str = ""
    config: Dict[str, Any] = field(default_factory=dict)
    dependencies: List[str] = field(default_factory=list)
    entry_point: str = ""
    parameters: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SkillPackage:
    """技能包"""

    success: bool = False
    skill_path: Optional[Path] = None
    skill_name: str = ""
    version: str = "1.0.0"
    error: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SkillChainStep:
    """技能链步骤"""

    step_id: str = ""
    skill_id: str = ""
    input_mapping: Dict[str, str] = field(default_factory=dict)
    output_mapping: Dict[str, str] = field(default_factory=dict)
    condition: Optional[str] = None
    timeout: float = 30.0
    retry_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SkillChain:
    """技能链"""

    chain_id: str = ""
    name: str = ""
    description: str = ""
    steps: List[SkillChainStep] = field(default_factory=list)
    variables: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class StepExecutionResult:
    """步骤执行结果"""

    step_id: str = ""
    skill_id: str = ""
    status: StepStatus = StepStatus.PENDING
    input_data: Dict[str, Any] = field(default_factory=dict)
    output_data: Dict[str, Any] = field(default_factory=dict)
    error: str = ""
    duration: float = 0.0
    retries: int = 0


@dataclass
class ChainExecutionResult:
    """技能链执行结果"""

    chain_id: str = ""
    status: ChainStatus = ChainStatus.PENDING
    success: bool = False
    results: List[StepExecutionResult] = field(default_factory=list)
    final_output: Dict[str, Any] = field(default_factory=dict)
    error: str = ""
    total_duration: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ChainStatusInfo:
    """技能链状态信息"""

    chain_id: str = ""
    status: ChainStatus = ChainStatus.PENDING
    progress: float = 0.0
    current_step: int = 0
    total_steps: int = 0
    started_at: Optional[str] = None
    estimated_remaining: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PromptAnalysis:
    """提示词分析结果"""

    clarity_score: float = 0.0
    specificity_score: float = 0.0
    completeness_score: float = 0.0
    conciseness_score: float = 0.0
    overall_score: float = 0.0
    suggestions: List[str] = field(default_factory=list)
    issues: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class OptimizedPrompt:
    """优化后的提示词"""

    success: bool = False
    original_prompt: str = ""
    optimized_prompt: str = ""
    improvements: List[str] = field(default_factory=list)
    score_before: float = 0.0
    score_after: float = 0.0
    optimization_type: OptimizationGoal = OptimizationGoal.CLARITY
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class VariantTestResults:
    """变体测试结果"""

    variants: List[str] = field(default_factory=list)
    variant_scores: List[float] = field(default_factory=list)
    best_variant_index: int = 0
    best_variant: str = ""
    test_cases: List[Dict[str, Any]] = field(default_factory=list)
    detailed_results: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
