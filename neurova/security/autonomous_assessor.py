"""
自主技能安全评估器 (Autonomous Skill Security Assessor)

实现自主技能安全评估，包括：
1. 技能行为分析
2. 风险评估
3. 自主安全评分
4. 与 SkillScanner 集成
"""

from neurova.core.logger import get_logger
import time
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

logger = get_logger(__name__)


class RiskLevel(Enum):
    """风险等级"""

    LOW = "low"  # 低风险
    MEDIUM = "medium"  # 中风险
    HIGH = "high"  # 高风险
    CRITICAL = "critical"  # 严重风险


class AssessmentStatus(Enum):
    """评估状态"""

    PENDING = "pending"  # 待评估
    IN_PROGRESS = "in_progress"  # 评估中
    COMPLETED = "completed"  # 已完成
    FAILED = "failed"  # 评估失败


@dataclass
class SecurityScore:
    """安全评分数据模型"""

    overall_score: float  # 0.0 - 100.0
    behavior_score: float
    code_quality_score: float
    risk_score: float
    compliance_score: float
    details: Optional[Dict[str, Any]] = None
    evaluated_at: Optional[float] = None

    def __post_init__(self):
        if self.evaluated_at is None:
            self.evaluated_at = time.time()

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)


@dataclass
class RiskAssessment:
    """风险评估数据模型"""

    risk_level: RiskLevel
    risk_score: float  # 0.0 - 100.0
    risk_factors: List[Dict[str, Any]]
    mitigation_suggestions: List[str]
    assessed_at: Optional[float] = None
    metadata: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        if self.assessed_at is None:
            self.assessed_at = time.time()

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        result = asdict(self)
        result["risk_level"] = self.risk_level.value
        return result


@dataclass
class SkillAssessmentResult:
    """技能评估结果数据模型"""

    skill_id: str
    skill_name: str
    status: AssessmentStatus
    security_score: Optional[SecurityScore]
    risk_assessment: Optional[RiskAssessment]
    assessment_time: float
    errors: List[str]
    warnings: List[str]
    metadata: Optional[Dict[str, Any]] = None
    assessed_at: Optional[float] = None

    def __post_init__(self):
        if self.assessed_at is None:
            self.assessed_at = time.time()

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        result = asdict(self)
        result["status"] = self.status.value
        if self.security_score:
            result["security_score"] = self.security_score.to_dict()
        if self.risk_assessment:
            result["risk_assessment"] = self.risk_assessment.to_dict()
        return result


class AutonomousSkillSecurityAssessor:
    """自主技能安全评估器"""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        初始化自主技能安全评估器

        Args:
            config: 配置信息
        """
        self.config = config or {}
        self.assessment_history: List[SkillAssessmentResult] = []
        self.max_history_size = self.config.get("max_history_size", 1000)

        # 风险权重配置
        self.risk_weights = {
            "behavior": 0.3,
            "code_quality": 0.25,
            "dependencies": 0.2,
            "permissions": 0.15,
            "complexity": 0.1,
        }

        logger.info("AutonomousSkillSecurityAssessor initialized")

    def assess_skill(self, skill_data: Dict[str, Any]) -> SkillAssessmentResult:
        """
        评估技能安全性

        Args:
            skill_data: 技能数据

        Returns:
            评估结果
        """
        start_time = time.time()
        skill_id = skill_data.get("id", "unknown")
        skill_name = skill_data.get("name", "unknown")
        errors = []
        warnings = []

        try:
            # 分析行为
            behavior_analysis = self._analyze_behavior(skill_data)

            # 评估代码质量
            code_quality = self._assess_code_quality(skill_data)

            # 评估风险
            risk_assessment = self._assess_risk(skill_data, behavior_analysis)

            # 计算总体评分
            security_score = self._calculate_overall_score(behavior_analysis, code_quality, risk_assessment)

            # 创建评估结果
            result = SkillAssessmentResult(
                skill_id=skill_id,
                skill_name=skill_name,
                status=AssessmentStatus.COMPLETED,
                security_score=security_score,
                risk_assessment=risk_assessment,
                assessment_time=time.time() - start_time,
                errors=errors,
                warnings=warnings,
                metadata={"behavior_analysis": behavior_analysis, "code_quality": code_quality},
            )

            # 保存到历史记录
            self._save_to_history(result)

            logger.info(
                "Skill assessment completed for %s: score=%.2f, risk=%s",
                skill_name,
                security_score.overall_score,
                risk_assessment.risk_level.value,
            )

            return result

        except Exception as e:
            logger.error("Failed to assess skill %s: %s", skill_name, e)
            errors.append(str(e))

            return SkillAssessmentResult(
                skill_id=skill_id,
                skill_name=skill_name,
                status=AssessmentStatus.FAILED,
                security_score=None,
                risk_assessment=None,
                assessment_time=time.time() - start_time,
                errors=errors,
                warnings=warnings,
            )

    def _analyze_behavior(self, skill_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        分析技能行为

        Args:
            skill_data: 技能数据

        Returns:
            行为分析结果
        """
        analysis = {
            "file_operations": False,
            "network_access": False,
            "system_calls": False,
            "data_access": False,
            "external_dependencies": False,
            "risk_score": 0.0,
            "details": [],
        }

        try:
            # 检查技能代码中的危险行为
            code = skill_data.get("code", "")
            if isinstance(code, str):
                # 检查文件操作
                file_patterns = ["open(", "os.path", "pathlib", "shutil", "file"]
                for pattern in file_patterns:
                    if pattern in code:
                        analysis["file_operations"] = True
                        analysis["details"].append(f"检测到文件操作: {pattern}")
                        break

                # 检查网络访问
                network_patterns = ["requests.", "urllib", "http.", "socket.", "aiohttp"]
                for pattern in network_patterns:
                    if pattern in code:
                        analysis["network_access"] = True
                        analysis["details"].append(f"检测到网络访问: {pattern}")
                        break

                # 检查系统调用
                system_patterns = ["subprocess", "os.system", "os.popen", "ctypes"]
                for pattern in system_patterns:
                    if pattern in code:
                        analysis["system_calls"] = True
                        analysis["details"].append(f"检测到系统调用: {pattern}")
                        break

                # 检查数据访问
                data_patterns = ["sqlite3", "pymysql", "psycopg2", "mongodb"]
                for pattern in data_patterns:
                    if pattern in code:
                        analysis["data_access"] = True
                        analysis["details"].append(f"检测到数据访问: {pattern}")
                        break

            # 检查依赖
            dependencies = skill_data.get("dependencies", [])
            if dependencies:
                analysis["external_dependencies"] = True
                analysis["details"].append(f"外部依赖数量: {len(dependencies)}")

            # 计算行为风险分数
            risk_factors = 0
            if analysis["file_operations"]:
                risk_factors += 1
            if analysis["network_access"]:
                risk_factors += 2
            if analysis["system_calls"]:
                risk_factors += 3
            if analysis["data_access"]:
                risk_factors += 1
            if analysis["external_dependencies"]:
                risk_factors += 1

            analysis["risk_score"] = min(100.0, risk_factors * 15.0)

            return analysis

        except Exception as e:
            logger.error("Failed to analyze behavior: %s", e)
            analysis["details"].append(f"行为分析失败: {str(e)}")
            return analysis

    def _assess_code_quality(self, skill_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        评估代码质量

        Args:
            skill_data: 技能数据

        Returns:
            代码质量评估结果
        """
        quality = {"score": 100.0, "issues": [], "metrics": {}}

        try:
            code = skill_data.get("code", "")
            if not isinstance(code, str):
                quality["issues"].append("代码为空或格式不正确")
                quality["score"] = 0.0
                return quality

            # 检查代码长度
            lines = code.split("\n")
            quality["metrics"]["total_lines"] = len(lines)

            if len(lines) > 1000:
                quality["issues"].append("代码过长，可能难以维护")
                quality["score"] -= 10.0

            # 检查函数数量
            function_count = code.count("def ")
            quality["metrics"]["function_count"] = function_count

            if function_count > 50:
                quality["issues"].append("函数数量过多，可能过于复杂")
                quality["score"] -= 15.0

            # 检查注释比例
            comment_lines = sum(1 for line in lines if line.strip().startswith("#"))
            comment_ratio = comment_lines / len(lines) if lines else 0
            quality["metrics"]["comment_ratio"] = comment_ratio

            if comment_ratio < 0.1:
                quality["issues"].append("注释比例过低")
                quality["score"] -= 10.0

            # 检查异常处理
            try_count = code.count("try:")
            except_count = code.count("except")
            quality["metrics"]["try_count"] = try_count
            quality["metrics"]["except_count"] = except_count

            if try_count > 0 and except_count == 0:
                quality["issues"].append("有try块但没有except块")
                quality["score"] -= 20.0

            # 确保分数在合理范围内
            quality["score"] = max(0.0, min(100.0, quality["score"]))

            return quality

        except Exception as e:
            logger.error("Failed to assess code quality: %s", e)
            quality["issues"].append(f"代码质量评估失败: {str(e)}")
            quality["score"] = 0.0
            return quality

    def _assess_risk(self, skill_data: Dict[str, Any], behavior_analysis: Dict[str, Any]) -> RiskAssessment:
        """
        评估风险

        Args:
            skill_data: 技能数据
            behavior_analysis: 行为分析结果

        Returns:
            风险评估结果
        """
        try:
            risk_factors = []
            mitigation_suggestions = []

            # 基于行为分析的风险
            if behavior_analysis.get("file_operations"):
                risk_factors.append({"factor": "file_operations", "level": "medium", "description": "技能包含文件操作"})
                mitigation_suggestions.append("限制文件访问范围，使用沙箱环境")

            if behavior_analysis.get("network_access"):
                risk_factors.append({"factor": "network_access", "level": "high", "description": "技能包含网络访问"})
                mitigation_suggestions.append("限制网络访问，使用代理或白名单")

            if behavior_analysis.get("system_calls"):
                risk_factors.append({"factor": "system_calls", "level": "critical", "description": "技能包含系统调用"})
                mitigation_suggestions.append("禁止系统调用或使用容器隔离")

            if behavior_analysis.get("data_access"):
                risk_factors.append({"factor": "data_access", "level": "medium", "description": "技能包含数据访问"})
                mitigation_suggestions.append("使用最小权限原则，限制数据访问范围")

            # 计算风险分数
            risk_score = behavior_analysis.get("risk_score", 0.0)

            # 确定风险等级
            if risk_score >= 80:
                risk_level = RiskLevel.CRITICAL
            elif risk_score >= 60:
                risk_level = RiskLevel.HIGH
            elif risk_score >= 40:
                risk_level = RiskLevel.MEDIUM
            else:
                risk_level = RiskLevel.LOW

            return RiskAssessment(
                risk_level=risk_level,
                risk_score=risk_score,
                risk_factors=risk_factors,
                mitigation_suggestions=mitigation_suggestions,
                metadata={"behavior_analysis": behavior_analysis},
            )

        except Exception as e:
            logger.error("Failed to assess risk: %s", e)
            return RiskAssessment(
                risk_level=RiskLevel.CRITICAL,
                risk_score=100.0,
                risk_factors=[
                    {"factor": "assessment_error", "level": "critical", "description": f"风险评估失败: {str(e)}"}
                ],
                mitigation_suggestions=["修复评估器错误后重新评估"],
            )

    def _calculate_overall_score(
        self, behavior_analysis: Dict[str, Any], code_quality: Dict[str, Any], risk_assessment: RiskAssessment
    ) -> SecurityScore:
        """
        计算总体安全评分

        Args:
            behavior_analysis: 行为分析结果
            code_quality: 代码质量评估结果
            risk_assessment: 风险评估结果

        Returns:
            安全评分
        """
        try:
            # 行为分数（越低越好）
            behavior_score = 100.0 - behavior_analysis.get("risk_score", 0.0)

            # 代码质量分数
            code_quality_score = code_quality.get("score", 0.0)

            # 风险分数（越低越好）
            risk_score = 100.0 - risk_assessment.risk_score

            # 合规分数（基于风险等级）
            risk_level = risk_assessment.risk_level
            if risk_level == RiskLevel.LOW:
                compliance_score = 100.0
            elif risk_level == RiskLevel.MEDIUM:
                compliance_score = 75.0
            elif risk_level == RiskLevel.HIGH:
                compliance_score = 50.0
            else:  # CRITICAL
                compliance_score = 25.0

            # 计算总体分数
            overall_score = (
                behavior_score * self.risk_weights["behavior"]
                + code_quality_score * self.risk_weights["code_quality"]
                + risk_score * self.risk_weights["dependencies"]
                + compliance_score * self.risk_weights["permissions"]
            )

            return SecurityScore(
                overall_score=overall_score,
                behavior_score=behavior_score,
                code_quality_score=code_quality_score,
                risk_score=risk_score,
                compliance_score=compliance_score,
                details={"weights": self.risk_weights, "risk_level": risk_assessment.risk_level.value},
            )

        except Exception as e:
            logger.error("Failed to calculate overall score: %s", e)
            return SecurityScore(
                overall_score=0.0,
                behavior_score=0.0,
                code_quality_score=0.0,
                risk_score=0.0,
                compliance_score=0.0,
                details={"error": str(e)},
            )

    def _risk_level_to_score(self, risk_level: RiskLevel) -> float:
        """
        将风险等级转换为分数

        Args:
            risk_level: 风险等级

        Returns:
            风险分数
        """
        mapping = {RiskLevel.LOW: 25.0, RiskLevel.MEDIUM: 50.0, RiskLevel.HIGH: 75.0, RiskLevel.CRITICAL: 100.0}
        return mapping.get(risk_level, 50.0)

    def _save_to_history(self, result: SkillAssessmentResult):
        """
        保存评估结果到历史记录

        Args:
            result: 评估结果
        """
        self.assessment_history.append(result)

        # 限制历史记录大小
        if len(self.assessment_history) > self.max_history_size:
            self.assessment_history = self.assessment_history[-self.max_history_size :]

    def get_assessment_history(self, skill_id: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        """
        获取评估历史

        Args:
            skill_id: 技能ID（可选）
            limit: 返回数量限制

        Returns:
            评估历史列表
        """
        try:
            history = self.assessment_history

            if skill_id:
                history = [r for r in history if r.skill_id == skill_id]

            # 按时间倒序排序
            history.sort(key=lambda r: r.assessed_at or 0, reverse=True)

            return [result.to_dict() for result in history[:limit]]

        except Exception as e:
            logger.error("Failed to get assessment history: %s", e)
            return []

    def clear_history(self):
        """清除评估历史"""
        self.assessment_history.clear()
        logger.info("Assessment history cleared")


# 全局实例
_assessor: Optional[AutonomousSkillSecurityAssessor] = None


def get_autonomous_assessor() -> AutonomousSkillSecurityAssessor:
    """
    获取自主技能安全评估器实例（单例模式）

    Returns:
        AutonomousSkillSecurityAssessor实例
    """
    global _assessor
    if _assessor is None:
        _assessor = AutonomousSkillSecurityAssessor()
    return _assessor


def reset_autonomous_assessor():
    """
    重置自主技能安全评估器实例（用于测试）
    """
    global _assessor
    _assessor = None
