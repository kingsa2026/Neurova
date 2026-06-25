from __future__ import annotations

"""
Skill Need Analyzer - 技能需求分析器

分析 Agent 的技能需求，并从技能市场主动获取所需技能。
实现 Neurova CogArch 1.0.0 的 Agent 主动学习能力。
"""

from neurova.core.logger import get_logger
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from neurova.skills.market_searcher import SearchResult, SkillMarketSearcher
from neurova.skills.models import Skill
from neurova.skills.task_decomposer import TaskDecomposer

logger = get_logger(__name__)


@dataclass
class SkillAcquisitionResult:
    """
    技能获取结果数据类
    """

    skill_name: str
    success: bool = False
    source: str = ""
    version: str = "1.0.0"
    message: str = ""
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "skill_name": self.skill_name,
            "success": self.success,
            "source": self.source,
            "version": self.version,
            "message": self.message,
            "error": self.error,
            "metadata": self.metadata,
        }


class SkillNeedAnalyzer:
    """
    技能需求分析器

    分析用户请求，识别所需技能，并从技能市场获取。
    实现 Agent 的主动学习能力。
    """

    # 相似度阈值
    SIMILARITY_THRESHOLD = 0.6

    # 最大获取尝试次数
    MAX_ACQUIRE_ATTEMPTS = 3

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        初始化技能需求分析器

        Args:
            config: 配置字典
        """
        self.config = config or {}

        # 初始化组件
        self.task_decomposer = TaskDecomposer(config=config)
        self.market_searcher = SkillMarketSearcher(config=config)

        # 已安装技能缓存
        self._installed_skills: Dict[str, Skill] = {}

        # 获取历史
        self._acquisition_history: List[SkillAcquisitionResult] = []

        logger.info("SkillNeedAnalyzer initialized")

    def analyze_and_acquire(self, request: str) -> List[SkillAcquisitionResult]:
        """
        分析并获取技能

        Args:
            request: 用户请求

        Returns:
            List[SkillAcquisitionResult]: 获取结果列表
        """
        results = []

        # 1. 分析技能需求
        required_skills = self.task_decomposer.analyze_skill_needs(request)

        # 2. 检查哪些技能已安装
        missing_skills = self._find_missing_skills(required_skills)

        # 3. 为缺失的技能尝试获取
        for skill_name in missing_skills:
            try:
                result = self._acquire_skill(skill_name, request)
                results.append(result)
            except Exception as e:
                logger.error("Failed to acquire skill %s: %s", skill_name, e)
                results.append(SkillAcquisitionResult(skill_name=skill_name, success=False, error=str(e)))

        # 记录获取历史
        self._acquisition_history.extend(results)

        return results

    def _find_missing_skills(self, required_skills: List[str]) -> List[str]:
        """
        查找缺失的技能

        Args:
            required_skills: 所需技能列表

        Returns:
            List[str]: 缺失的技能列表
        """
        missing = []

        for skill_name in required_skills:
            # 检查是否已安装
            if not self._is_skill_installed(skill_name):
                missing.append(skill_name)

        return missing

    def _is_skill_installed(self, skill_name: str) -> bool:
        """
        检查技能是否已安装

        Args:
            skill_name: 技能名称

        Returns:
            bool: 是否已安装
        """
        # 检查缓存
        if skill_name in self._installed_skills:
            return True

        # 这里应该检查实际的技能安装目录
        # 简化实现，假设未安装
        return False

    def _acquire_skill(self, skill_name: str, context: str) -> SkillAcquisitionResult:
        """
        获取技能

        Args:
            skill_name: 技能名称
            context: 上下文（用户请求）

        Returns:
            SkillAcquisitionResult: 获取结果
        """
        # 搜索技能
        search_results = self.market_searcher.search_all_markets(skill_name)

        if not search_results:
            return SkillAcquisitionResult(
                skill_name=skill_name, success=False, error="No matching skills found in markets"
            )

        # 选择最佳匹配
        best_match = self._select_best_match(search_results, skill_name, context)

        if not best_match:
            return SkillAcquisitionResult(skill_name=skill_name, success=False, error="No suitable match found")

        # 尝试安装
        return self._install_skill(best_match)

    def _select_best_match(
        self, search_results: List[SearchResult], skill_name: str, context: str
    ) -> Optional[SearchResult]:
        """
        选择最佳匹配

        Args:
            search_results: 搜索结果列表
            skill_name: 技能名称
            context: 上下文

        Returns:
            Optional[SearchResult]: 最佳匹配结果
        """
        if not search_results:
            return None

        # 计算每个结果的匹配分数
        scored_results = []
        for result in search_results:
            score = self._calculate_similarity(result, skill_name, context)
            scored_results.append((score, result))

        # 按分数排序
        scored_results.sort(key=lambda x: x[0], reverse=True)

        # 返回最高分的结果（如果超过阈值）
        best_score, best_result = scored_results[0]

        if best_score >= self.SIMILARITY_THRESHOLD:
            return best_result

        return None

    def _calculate_similarity(self, result: SearchResult, skill_name: str, context: str) -> float:
        """
        计算相似度

        Args:
            result: 搜索结果
            skill_name: 技能名称
            context: 上下文

        Returns:
            float: 相似度分数 (0-1)
        """
        score = 0.0

        # 名称匹配
        if skill_name.lower() in result.name.lower():
            score += 0.4
        elif result.name.lower() in skill_name.lower():
            score += 0.3

        # 描述匹配
        if skill_name.lower() in result.description.lower():
            score += 0.2

        # 标签匹配
        for tag in result.tags:
            if skill_name.lower() in tag.lower():
                score += 0.1
                break

        # 来源可信度
        source_trust = {
            "github": 0.2,
            "lobehub": 0.2,
            "modelscope": 0.15,
            "skillhub_cn": 0.15,
        }
        score += source_trust.get(result.source, 0.1)

        # 星数加分（归一化）
        if result.stars > 0:
            score += min(result.stars / 10000, 0.1)

        return min(score, 1.0)

    def _install_skill(self, search_result: SearchResult) -> SkillAcquisitionResult:
        """
        安装技能

        Args:
            search_result: 搜索结果

        Returns:
            SkillAcquisitionResult: 安装结果
        """
        try:
            # 这里应该调用实际的技能安装逻辑
            # 简化实现，模拟安装成功

            logger.info("Installing skill: %s from %s", search_result.name, search_result.source)

            # 模拟安装延迟
            import time

            time.sleep(0.1)

            # 添加到已安装技能缓存
            self._installed_skills[search_result.name] = Skill(
                name=search_result.name, description=search_result.description, version=search_result.version
            )

            return SkillAcquisitionResult(
                skill_name=search_result.name,
                success=True,
                source=search_result.source,
                version=search_result.version,
                message=f"Successfully installed from {search_result.source}",
            )

        except Exception as e:
            logger.error("Failed to install skill %s: %s", search_result.name, e)
            return SkillAcquisitionResult(
                skill_name=search_result.name, success=False, source=search_result.source, error=str(e)
            )

    def suggest_skills(self, request: str, max_suggestions: int = 5) -> List[Dict[str, Any]]:
        """
        建议技能

        Args:
            request: 用户请求
            max_suggestions: 最大建议数量

        Returns:
            List[Dict[str, Any]]: 建议列表
        """
        suggestions = []

        # 分析技能需求
        required_skills = self.task_decomposer.analyze_skill_needs(request)

        # 搜索每个技能
        for skill_name in required_skills[:max_suggestions]:
            search_results = self.market_searcher.search_market("github", skill_name, limit=3)

            for result in search_results:
                similarity = self._calculate_similarity(result, skill_name, request)

                if similarity >= self.SIMILARITY_THRESHOLD:
                    suggestions.append(
                        {
                            "skill_name": skill_name,
                            "market_name": result.name,
                            "source": result.source,
                            "description": result.description,
                            "similarity": similarity,
                            "url": result.url,
                            "version": result.version,
                        }
                    )

        # 按相似度排序
        suggestions.sort(key=lambda x: x["similarity"], reverse=True)

        return suggestions[:max_suggestions]

    def get_acquisition_history(self) -> List[Dict[str, Any]]:
        """
        获取获取历史

        Returns:
            List[Dict[str, Any]]: 获取历史列表
        """
        return [result.to_dict() for result in self._acquisition_history]

    def clear_history(self):
        """清除获取历史"""
        self._acquisition_history.clear()
        logger.info("Acquisition history cleared")

    def get_installed_skills(self) -> List[str]:
        """
        获取已安装技能列表

        Returns:
            List[str]: 技能名称列表
        """
        return list(self._installed_skills.keys())

    def refresh_installed_skills(self):
        """刷新已安装技能缓存"""
        # 这里应该扫描实际的技能安装目录
        # 简化实现，清空缓存
        self._installed_skills.clear()
        logger.info("Installed skills cache refreshed")
