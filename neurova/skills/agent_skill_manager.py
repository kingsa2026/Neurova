"""
Agent 技能管理器

为 Agent 提供任务拆解、技能需求分析和主动获取能力。
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


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

        # 初始化子模块（占位符实现）
        try:
            from neurova.skills.market_importer import SkillMarketImporter
            from neurova.skills.market_searcher import SkillMarketSearcher
            from neurova.skills.skill_need_analyzer import SkillNeedAnalyzer
            from neurova.skills.task_decomposer import TaskDecomposer

            self.decomposer = TaskDecomposer()
            self.searcher = SkillMarketSearcher()
            self.importer = SkillMarketImporter()
            self.analyzer = SkillNeedAnalyzer(skill_registry=skill_registry)
        except ImportError as e:
            logger.warning("Could not initialize skill modules: %s", e)
            self.decomposer = None
            self.searcher = None
            self.importer = None
            self.analyzer = None

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

        # 分析技能需求
        analysis = await self.analyzer.analyze_and_acquire(
            task=task,
            context=context,
            auto_acquire=self.auto_acquire,
        )

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

        suggestions = await self.analyzer.suggest_skills(
            task=task,
            context=context,
        )

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
