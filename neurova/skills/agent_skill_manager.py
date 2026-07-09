"""
Agent 技能管理器

为 Agent 提供任务拆解、技能需求分析和主动获取能力。
"""

from pathlib import Path

from neurova.core.logger import get_logger
from typing import Any, Dict, List, Optional

logger = get_logger(__name__)


class AgentSkillManager:
    """
    Agent 技能管理器

    为 Agent 提供任务拆解、技能需求分析和主动获取能力。

    Attributes:
        agent_id: Agent ID
        skill_registry: 技能注册表
        auto_acquire: 是否自动获取技能
    """

    def __init__(
        self,
        agent_id: str,
        skill_registry=None,
        auto_acquire: bool = True,
    ):
        """
        初始化 AgentSkillManager

        Args:
            agent_id: Agent ID
            skill_registry: 技能注册表实例
            auto_acquire: 是否自动获取缺失的技能
        """
        self.agent_id = agent_id
        self.skill_registry = skill_registry
        self.auto_acquire = auto_acquire

        # P0-B1 修复：每个子模块独立初始化，避免单个失败导致整体崩溃
        # 之前：一个 ImportError 会让 decomposer/searcher/importer/analyzer 全部变 None
        self.decomposer = self._init_decomposer()
        self.searcher = self._init_searcher()
        self.importer = self._init_importer()
        self.analyzer = self._init_analyzer()

    def _init_decomposer(self):
        """独立初始化 TaskDecomposer"""
        try:
            from neurova.skills.task_decomposer import TaskDecomposer
            return TaskDecomposer()
        except Exception as e:
            logger.warning("Could not initialize TaskDecomposer: %s", e)
            return None

    def _init_searcher(self):
        """独立初始化 SkillMarketSearcher"""
        try:
            from neurova.skills.market_searcher import SkillMarketSearcher
            return SkillMarketSearcher()
        except Exception as e:
            logger.warning("Could not initialize SkillMarketSearcher: %s", e)
            return None

    def _init_importer(self):
        """独立初始化 MarketImporter

        P0-B1 修复：原代码 import SkillMarketImporter（类名错误，实际是 MarketImporter）
        导致 ImportError，进而让整个 try 块的所有模块都变 None。
        """
        try:
            from neurova.skills.market_importer import MarketImporter
            # MarketImporter 需要 skills_dir 参数；使用默认目录
            return MarketImporter(skills_dir=Path(".agents/skills"))
        except Exception as e:
            logger.warning("Could not initialize MarketImporter: %s", e)
            return None

    def _init_analyzer(self):
        """独立初始化 SkillNeedAnalyzer

        P0-B1 修复：原代码 SkillNeedAnalyzer(skill_registry=skill_registry) 抛 TypeError
        （SkillNeedAnalyzer.__init__ 只接受 config，不接受 skill_registry）
        """
        try:
            from neurova.skills.skill_need_analyzer import SkillNeedAnalyzer
            # SkillNeedAnalyzer 只接受 config 参数（不含 skill_registry）
            return SkillNeedAnalyzer()
        except Exception as e:
            logger.warning("Could not initialize SkillNeedAnalyzer: %s", e)
            return None

    async def analyze_task(
        self,
        task: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        分析任务并获取技能建议

        Args:
            task: 任务描述
            context: 上下文信息

        Returns:
            包含任务分析结果的字典
        """
        logger.info("Agent %s analyzing task: %s...", self.agent_id, task[:50])

        if not self.analyzer:
            return {
                "success": False,
                "error": "Skill analyzer not available",
                "skills_needed": [],
            }

        # P0-B2 修复：SkillNeedAnalyzer.analyze_and_acquire 是同步函数
        # 原签名：def analyze_and_acquire(self, request: str) -> List[SkillAcquisitionResult]
        # 适配为 AgentSkillManager 期望的 dict 格式
        try:
            acquisition_results = self.analyzer.analyze_and_acquire(request=task)
            skills_needed = [
                {
                    "skill_name": r.skill_name,
                    "success": r.success,
                    "source": r.source,
                    "version": r.version,
                    "error": r.error,
                }
                for r in acquisition_results
            ]
            analysis = {
                "success": any(r.success for r in acquisition_results) if acquisition_results else True,
                "skills_needed": skills_needed,
                "auto_acquire": self.auto_acquire,
            }
        except Exception as e:
            logger.error("analyze_and_acquire failed: %s", e, exc_info=True)
            analysis = {
                "success": False,
                "error": str(e),
                "skills_needed": [],
            }

        logger.info("Task analysis completed, found %s skills needed", len(analysis.get('skills_needed', [])))
        return analysis

    async def suggest_skills_for_task(
        self,
        task: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        为任务建议技能

        Args:
            task: 任务描述
            context: 上下文信息

        Returns:
            建议的技能列表
        """
        logger.info("Agent %s suggesting skills for task: %s...", self.agent_id, task[:50])

        if not self.analyzer:
            return []

        # P0-B2 修复：SkillNeedAnalyzer.suggest_skills 是同步函数
        # 原签名：def suggest_skills(self, request: str, max_suggestions: int = 5) -> List[Dict[str, Any]]
        try:
            suggestions = self.analyzer.suggest_skills(request=task)
        except Exception as e:
            logger.error("suggest_skills failed: %s", e, exc_info=True)
            suggestions = []

        logger.info("Suggested %s skills", len(suggestions))
        return suggestions

    async def search_skill_in_markets(
        self,
        skill_name: str,
        markets: Optional[List[str]] = None,
        limit_per_market: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        在市场中搜索技能

        Args:
            skill_name: 技能名称
            markets: 市场列表
            limit_per_market: 每个市场的结果限制

        Returns:
            搜索结果列表
        """
        logger.info("Agent %s searching for skill: %s", self.agent_id, skill_name)

        if not self.searcher:
            return []

        results = await self.searcher.search_all_markets(
            query=skill_name,
            markets=markets,
            limit_per_market=limit_per_market,
        )

        logger.info("Found %s results for skill: %s", len(results), skill_name)
        return results

    async def acquire_skill(
        self,
        skill_name: str,
        market: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        获取技能

        Args:
            skill_name: 技能名称
            market: 市场名称

        Returns:
            获取结果
        """
        logger.info("Agent %s acquiring skill: %s", self.agent_id, skill_name)

        if not self.searcher or not self.importer:
            return {
                "success": False,
                "error": "Market modules not available",
            }

        # 搜索技能
        if market:
            results = await self.searcher.search_market(
                market=market,
                query=skill_name,
                limit=1,
            )
        else:
            results = await self.searcher.search_all_markets(
                query=skill_name,
                limit_per_market=1,
            )

        if not results:
            logger.warning("Skill %s not found in any market", skill_name)
            return {
                "success": False,
                "error": f"Skill {skill_name} not found",
            }

        # 获取第一个结果
        skill_info = results[0]

        # 导入技能
        import_result = await self.importer.import_from_market(
            market=skill_info.get("market", "unknown"),
            skill_id=skill_info.get("id", ""),
            skill_data=skill_info,
        )

        logger.info("Skill %s acquired successfully", skill_name)
        return {
            "success": True,
            "skill_name": skill_name,
            "import_result": import_result,
        }

    def get_skill_status(self) -> Dict[str, Any]:
        """获取技能状态"""
        if not self.skill_registry:
            return {
                "agent_id": self.agent_id,
                "skills": [],
                "auto_acquire": self.auto_acquire,
            }

        skills = []
        for skill in self.skill_registry.list_skills():
            skills.append(
                {
                    "name": skill.name,
                    "status": skill.status,
                    "version": skill.version,
                }
            )

        return {
            "agent_id": self.agent_id,
            "skills": skills,
            "auto_acquire": self.auto_acquire,
            "available_markets": self.searcher.list_markets() if self.searcher else [],
        }


__all__ = ["AgentSkillManager"]
