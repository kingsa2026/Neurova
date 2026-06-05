from __future__ import annotations

"""
Skill System 2.0 数据模型

定义技能系统中使用的数据类。
包括：SkillSource, SkillInfo, SkillEvolutionRecord, ExperienceRecord
"""

from dataclasses import dataclass, field
import datetime
from enum import Enum
from pathlib import Path
import typing
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
    version: str = "0.1.0"
    description: str = ""
    author: str = ""
    tags: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)

@dataclass
class Skill:
    """技能主模型"""
    id: str = ""
    name: str = ""
    version: str = "0.1.0"
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

# Alias for backward compatibility
SkillInfo = Skill
SkillSource = SkillSource
SkillEvolutionRecord = SkillExecutionLog
ExperienceRecord = SkillExecutionLog
SkillManifest = Skill
PluginEntryPoints = Dict[str, Any]
SkillRecord = Skill
