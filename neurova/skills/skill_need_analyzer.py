from __future__ import annotations

"""
Skill Need Analyzer - 技能需求分析器

分析 Agent 的技能需求，并从技能市场主动获取所需技能。
实现 Neurova CogArch 1.0.0 的 Agent 主动学习能力。
"""

from neurova.core.logger import get_logger
from dataclasses import dataclass, field
import threading
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
        # P0-B1 修复：SkillMarketSearcher.__init__ 只接受 cache_dir，不接受 config
        # 只从 config 中提取相关字段（cache_dir），避免 TypeError
        cache_dir = self.config.get("cache_dir") if isinstance(self.config, dict) else None
        self.task_decomposer = TaskDecomposer(config=config)
        self.market_searcher = SkillMarketSearcher(cache_dir=cache_dir)

        # 已安装技能缓存
        self._installed_skills: Dict[str, Skill] = {}

        # 已安装状态缓存（按 skill_id 索引，避免重复检查）
        self._installed_cache: Dict[str, bool] = {}

        # 获取历史
        self._acquisition_history: List[SkillAcquisitionResult] = []

        # AGENTS.md 规定：threading.RLock 用于共享状态
        # 保护 _installed_skills / _installed_cache / _acquisition_history 在并发分析下的原子性
        # 对照：pool_service.py:70, market_importer.py:100, evolution_engine.py:99
        self._lock = threading.RLock()

        # ADR 0012: 注入 SkillService（真实安装/加载）
        # SkillService.__init__ 需要 agent_id；从 config 读取或用默认值
        try:
            from neurova.skills.skill_service import SkillService

            agent_id = (
                self.config.get("agent_id", "default")
                if isinstance(self.config, dict)
                else "default"
            )
            self.skill_service = SkillService(agent_id=agent_id)
        except Exception as e:
            logger.warning("Could not initialize SkillService: %s", e)
            self.skill_service = None

        logger.info("SkillNeedAnalyzer initialized")

    def analyze_and_acquire(self, request: str) -> List[SkillAcquisitionResult]:
        """
        分析并获取技能

        Args:
            request: 用户请求

        Returns:
            List[SkillAcquisitionResult]: 获取结果列表
        """
        # AGENTS.md: 共享状态受 RLock 保护，整块加锁保证 _acquisition_history 原子更新
        # RLock 可重入，_find_missing_skills / _acquire_skill 内部再次加锁不会死锁
        with self._lock:
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

    def _is_skill_installed(self, skill_id: str) -> bool:
        """检查技能是否已安装 — 委托 SkillService

        ADR 0012: 替换"永远返回 False"的 stub。
        - 优先查内存缓存 _installed_cache / _installed_skills
        - 优先调用 SkillService.is_installed（若存在）
        - 否则回退到 SkillService.list_skills 查找
        """
        # 1. 查内存缓存（_installed_skills 按 name 索引，_installed_cache 按 skill_id 索引）
        # AGENTS.md: 读共享缓存加锁，避免与并发写入冲突
        with self._lock:
            if skill_id in self._installed_skills:
                return True
            if hasattr(self, "_installed_cache") and self._installed_cache.get(skill_id):
                return True

        # 2. 委托 SkillService 真实检查（IO 操作不持锁）
        if not self.skill_service:
            return False

        try:
            # 优先使用 is_installed 方法（语义最清晰）
            if hasattr(self.skill_service, "is_installed") and callable(
                getattr(self.skill_service, "is_installed")
            ):
                return bool(self.skill_service.is_installed(skill_id))

            # 回退：遍历 list_skills 结果查找匹配 skill_id / id / name
            installed = self.skill_service.list_skills()
            for skill in installed or []:
                if isinstance(skill, dict):
                    if (
                        skill.get("skill_id") == skill_id
                        or skill.get("id") == skill_id
                        or skill.get("name") == skill_id
                    ):
                        return True
                else:
                    # 对象形式
                    for attr in ("skill_id", "id", "name"):
                        if getattr(skill, attr, None) == skill_id:
                            return True
        except Exception as e:
            logger.warning("Failed to check skill installation via SkillService: %s", e)

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

        # 尝试安装 — ADR 0012: 委托 SkillService（经 _install_skill 新签名）
        install_info = {
            "id": best_match.name,
            "name": best_match.name,
            "source": best_match.source,
            "source_url": best_match.url,
            "url": best_match.url,
            "version": best_match.version,
            "description": best_match.description,
        }
        install_result = self._install_skill(best_match.name, install_info)

        # 转回 SkillAcquisitionResult 以保持 _acquire_skill 返回类型契约
        success = bool(install_result.get("success", False)) if isinstance(install_result, dict) else False
        if success:
            # 同步更新内存缓存（AGENTS.md: 写 _installed_skills 加锁）
            with self._lock:
                self._installed_skills[best_match.name] = Skill(
                    name=best_match.name,
                    description=best_match.description,
                    version=best_match.version,
                )
            return SkillAcquisitionResult(
                skill_name=best_match.name,
                success=True,
                source=best_match.source,
                version=best_match.version,
                message=f"Successfully installed from {best_match.source}",
            )
        return SkillAcquisitionResult(
            skill_name=best_match.name,
            success=False,
            source=best_match.source,
            version=best_match.version,
            error=install_result.get("error", "Installation failed") if isinstance(install_result, dict) else "Installation failed",
        )

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

    def _install_skill(self, skill_name: str, skill_info: Dict[str, Any]) -> Dict[str, Any]:
        """安装技能 — 委托 SkillService（真实 zip 解压 + importlib 加载）

        ADR 0012: 替换 stub time.sleep 实现。
        - 调用 SkillService.install_skill 真实安装
        - 缓存已安装状态到 _installed_cache

        Args:
            skill_name: 技能名称
            skill_info: 技能信息 dict（含 source_url/url/id 等）

        Returns:
            Dict[str, Any]: 安装结果，含 success / skill_id / error
        """
        if not self.skill_service:
            logger.warning("SkillService 不可用，无法安装 %s", skill_name)
            return {"success": False, "error": "SkillService not available"}

        source_url = skill_info.get("source_url") or skill_info.get("url", "")
        skill_id = skill_info.get("id") or skill_info.get("name") or skill_name

        try:
            result = self.skill_service.install_skill(
                skill_path=source_url,
                skill_id=skill_id,
            )
            # 缓存已安装状态（AGENTS.md: 写 _installed_cache 加锁；install_skill 已返回，不持锁做 IO）
            with self._lock:
                if hasattr(self, "_installed_cache") and isinstance(result, dict):
                    self._installed_cache[skill_id] = bool(result.get("success", False))
            return result if isinstance(result, dict) else {"success": bool(result)}
        except Exception as e:
            logger.exception("Failed to install skill %s: %s", skill_name, e)
            return {"success": False, "error": str(e)}

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
        # AGENTS.md: 读 _acquisition_history 加锁
        with self._lock:
            return [result.to_dict() for result in self._acquisition_history]

    def clear_history(self):
        """清除获取历史"""
        # AGENTS.md: 写 _acquisition_history 加锁
        with self._lock:
            self._acquisition_history.clear()
        logger.info("Acquisition history cleared")

    def get_installed_skills(self) -> List[str]:
        """
        获取已安装技能列表

        Returns:
            List[str]: 技能名称列表
        """
        # AGENTS.md: 读 _installed_skills 加锁
        with self._lock:
            return list(self._installed_skills.keys())

    def refresh_installed_skills(self):
        """刷新已安装技能缓存"""
        # 这里应该扫描实际的技能安装目录
        # 简化实现，清空缓存
        # AGENTS.md: 写 _installed_skills 加锁
        with self._lock:
            self._installed_skills.clear()
        logger.info("Installed skills cache refreshed")
