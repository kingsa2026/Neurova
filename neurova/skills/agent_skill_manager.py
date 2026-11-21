"""
Agent 技能管理器

为 Agent 提供任务拆解、技能需求分析和主动获取能力。
"""

import asyncio

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
        self_model_provider=None,
    ):
        """
        初始化 AgentSkillManager

        Args:
            agent_id: Agent ID
            skill_registry: 技能注册表实例
            auto_acquire: 是否自动获取缺失的技能
            self_model_provider: 惰性取 MemoryManager.assessTaskCapabilities 的 callable
                （可选；透传给 SkillNeedAnalyzer 做任务能力自评）
        """
        self.self_model_provider = self_model_provider
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
        """初始化 SkillHubClient（真实 HTTP 下载/安装/更新）

        ADR 0012: 用 SkillHubClient 替换 stub MarketImporter。
        SkillHubClient 是唯一能从 GitHub/ClawHub/LobeHub 真实下载安装的深度 Module。

        同时把实例赋给 self.importer，便于 __new__ + _init_importer() 单步初始化测试。
        """
        try:
            from neurova.skills.hub_client import SkillHubClient
            self.importer = SkillHubClient()
            return self.importer
        except Exception as e:
            logger.warning("Could not initialize SkillHubClient: %s", e)
            self.importer = None
            return None

    def _init_analyzer(self):
        """独立初始化 SkillNeedAnalyzer

        P0-B1 修复：原代码 SkillNeedAnalyzer(skill_registry=skill_registry) 抛 TypeError
        （SkillNeedAnalyzer.__init__ 只接受 config，不接受 skill_registry）
        """
        try:
            from neurova.skills.skill_need_analyzer import SkillNeedAnalyzer
            # SkillNeedAnalyzer 只接受 config 参数（不含 skill_registry）
            return SkillNeedAnalyzer(self_model_provider=self.self_model_provider)
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

        # analyze_and_acquire v2 返回 dict（含 results: List[SkillAcquisitionResult]）；
        # 兼容旧 list 返回形态
        try:
            # P1-17: analyze_and_acquire 是同步重活（decompose + 市场聚合搜索
            # MARKET_SEARCH_AGGREGATE_SECONDS=18 + hub_client 退避重试），
            # 直调会把聊天主链的事件循环卡 18s+——整链下沉工作线程
            # （消费点 chat_pipeline._check_skill_acquisition 在主循环上 await）。
            acquisition = await asyncio.to_thread(self.analyzer.analyze_and_acquire, request=task)
            if isinstance(acquisition, dict):
                acquisition_results = acquisition.get("results", [])
            else:
                acquisition_results = acquisition
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

    def search_skill(
        self,
        skill_name: str,
        markets: Optional[List[str]] = None,
        limit_per_market: int = 5,
    ) -> List[Dict[str, Any]]:
        """搜索技能 — 同步调用下游 searcher

        ADR 0012 修复:
        - 下游 market searcher 的批量搜索方法是同步的（改为同步调用）
        - 真实签名: search_all_markets(query, limit) — 无 markets/limit_per_market 参数
        - markets 参数保留为兼容签名（实际由 searcher 内部已注册源决定）
        """
        logger.info("Agent %s searching for skill: %s", self.agent_id, skill_name)

        if not self.searcher:
            return []

        results = self.searcher.search_all_markets(skill_name, limit=limit_per_market)

        logger.info("Found %s results for skill: %s", len(results), skill_name)
        return results

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
