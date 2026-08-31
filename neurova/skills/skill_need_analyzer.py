from __future__ import annotations

"""
Skill Need Analyzer - 技能需求分析器 (v2)

分析 Agent 的技能需求，并从技能市场主动获取所需技能。
实现 Neurova CogArch 1.0.0 的 Agent 主动学习能力。

v2 契约（tests/unit/skills/test_skill_need_analyzer.py）:
- 构造器依赖注入: decomposer / searcher / importer / auto_install（缺省时
  惰性构建真实实现，保持 SkillNeedAnalyzer() 无参兼容）;
- analyze_and_acquire 返回 dict（required_skills / missing_skills /
  success_count / fail_count / results）;
- _calculate_similarity(a, b) 纯字符串相似度; _select_best_match(skill_name, results);
- suggest_skills 输出含 skill_name / sources / already_installed。

兼容别名: task_decomposer ↔ decomposer、market_searcher ↔ searcher
（agent_skill_manager 等旧消费方按旧属性名访问）。
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

    market/url/install_path 为 v2 字段；source 为市场来源（与 market 语义
    分工：source=来源市场标识，market=市场展示名）。
    """

    skill_name: str
    success: bool = False
    source: str = ""
    market: str = ""
    url: str = ""
    install_path: str = ""
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
            "market": self.market,
            "url": self.url,
            "install_path": self.install_path,
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

    # 相似度阈值（v2: 低于该值视为无合适匹配）
    SIMILARITY_THRESHOLD = 0.5

    # 最大获取尝试次数
    MAX_ACQUIRE_ATTEMPTS = 3

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        decomposer: Optional[Any] = None,
        searcher: Optional[Any] = None,
        importer: Optional[Any] = None,
        auto_install: Optional[bool] = None,
        skill_registry: Optional[Any] = None,
    ):
        """
        Args:
            config: 配置字典（缺省依赖构建时使用）
            decomposer: TaskDecomposer 实例（DI；缺省惰性构建）
            searcher: SkillMarketSearcher 实例（DI；缺省惰性构建）
            importer: 市场导入器实例（DI；缺省用 SkillService 兜底安装）
            auto_install: 是否自动安装缺失技能；None 时取 config.auto_install（默认 True）
            skill_registry: Agent 技能注册表（可选，用于已安装判定）
        """
        self.config = config or {}
        self.decomposer = decomposer if decomposer is not None else TaskDecomposer(config=self.config)
        self.task_decomposer = self.decomposer  # 兼容别名

        cache_dir = self.config.get("cache_dir") if isinstance(self.config, dict) else None
        self.searcher = searcher if searcher is not None else SkillMarketSearcher(cache_dir=cache_dir)
        self.market_searcher = self.searcher  # 兼容别名

        self.importer = importer
        self.auto_install = (
            auto_install if auto_install is not None else bool(self.config.get("auto_install", True))
        )
        self.skill_registry = skill_registry

        # 已安装技能缓存
        self._installed_skills: Dict[str, Skill] = {}

        # 已安装状态缓存（按 skill_id 索引，避免重复检查）
        self._installed_cache: Dict[str, bool] = {}

        # 获取历史
        self._acquisition_history: List[SkillAcquisitionResult] = []

        # AGENTS.md 规定：threading.RLock 用于共享状态
        self._lock = threading.RLock()

        # ADR 0012: SkillService（真实安装/加载）——惰性构建，避免无参构造时碰磁盘
        self.skill_service: Optional[Any] = None

        logger.info("SkillNeedAnalyzer initialized (auto_install=%s)", self.auto_install)

    def _get_skill_service(self) -> Optional[Any]:
        """惰性获取 SkillService（首个安装/查询动作时构建）"""
        if self.skill_service is None:
            try:
                from neurova.skills.skill_service import SkillService

                agent_id = (
                    self.config.get("agent_id", "default")
                    if isinstance(self.config, dict)
                    else "default"
                )
                self.skill_service = SkillService(agent_id=agent_id)
            except Exception as e:  # noqa: BLE001
                logger.warning("Could not initialize SkillService: %s", e)
        return self.skill_service

    # ── 已安装判定 ──

    def _registry_installed_names(self) -> set:
        """从 skill_registry 收集已安装技能名（仅内存态，不碰磁盘）"""
        names: set = set()
        registry = getattr(self, "skill_registry", None)
        if registry is not None:
            try:
                for s in registry.list_skills() or []:
                    name = s.get("name") if isinstance(s, dict) else getattr(s, "name", None)
                    if name:
                        names.add(str(name))
            except Exception as e:  # noqa: BLE001
                logger.warning("list installed skills from registry failed: %s", e)
        with self._lock:
            names.update(self._installed_skills.keys())
        return names

    def _installed_names(self) -> set:
        """已安装技能名集合（registry + 内存缓存；供 suggest 判定）"""
        return self._registry_installed_names()

    def _is_skill_installed(self, skill_id: str) -> bool:
        """检查技能是否已安装 — registry 缓存 + SkillService 磁盘清单"""
        with self._lock:
            if skill_id in self._installed_skills:
                return True
            if self._installed_cache.get(skill_id):
                return True
        if skill_id in self._registry_installed_names():
            return True

        service = self._get_skill_service()
        if not service:
            return False
        try:
            if hasattr(service, "is_installed") and callable(getattr(service, "is_installed")):
                return bool(service.is_installed(skill_id))
            installed = service.list_skills()
            for skill in installed or []:
                if isinstance(skill, dict):
                    if skill.get("skill_id") == skill_id or skill.get("id") == skill_id or skill.get("name") == skill_id:
                        return True
                else:
                    for attr in ("skill_id", "id", "name"):
                        if getattr(skill, attr, None) == skill_id:
                            return True
        except Exception as e:  # noqa: BLE001
            logger.warning("Failed to check skill installation via SkillService: %s", e)
        return False

    # ── 主流程 ──

    def analyze_and_acquire(self, request: str) -> Dict[str, Any]:
        """
        分析并获取技能

        Args:
            request: 用户请求

        Returns:
            Dict: {required_skills, missing_skills, results, success_count,
                   fail_count, can_execute}
            results 为 SkillAcquisitionResult 列表（保持类型契约）。
        """
        with self._lock:
            decomposition = self.decomposer.decompose(request)
            required_skills = self._collect_required_skills(decomposition)

            missing_skills = [s for s in required_skills if not self._is_skill_installed(s)]

            results: List[SkillAcquisitionResult] = []
            success_count = 0
            fail_count = 0
            for skill_name in missing_skills:
                try:
                    result = self._acquire_skill(skill_name, request)
                except Exception as e:  # noqa: BLE001
                    logger.error("Failed to acquire skill %s: %s", skill_name, e)
                    result = SkillAcquisitionResult(skill_name=skill_name, success=False, error=str(e))
                results.append(result)
                if result.success:
                    success_count += 1
                else:
                    fail_count += 1

            self._acquisition_history.extend(results)
            return {
                "required_skills": required_skills,
                "missing_skills": missing_skills,
                "results": results,
                "success_count": success_count,
                "fail_count": fail_count,
                "can_execute": len(missing_skills) == 0,
            }

    @staticmethod
    def _collect_required_skills(decomposition: Any) -> List[str]:
        """从拆解结果聚合所需技能（subtasks[].required_skills + 顶层，去重保序）"""
        required: List[str] = []
        for st in getattr(decomposition, "subtasks", None) or []:
            for sk in getattr(st, "required_skills", None) or []:
                if sk and sk not in required:
                    required.append(sk)
        for sk in getattr(decomposition, "required_skills", None) or []:
            if sk and sk not in required:
                required.append(sk)
        return required

    def _acquire_skill(self, skill_name: str, context: str) -> SkillAcquisitionResult:
        """获取单个缺失技能：搜索 → 选优 → 安装（auto_install=False 只搜不装）"""
        search_results = self.searcher.search_all_markets(skill_name)

        if not search_results:
            return SkillAcquisitionResult(
                skill_name=skill_name, success=False, error="No matching skills found in markets"
            )

        best_match = self._select_best_match(skill_name, search_results)

        if not best_match:
            return SkillAcquisitionResult(skill_name=skill_name, success=False, error="No suitable match found")

        if not self.auto_install:
            return SkillAcquisitionResult(
                skill_name=best_match.skill_name,
                success=False,
                source=best_match.market,
                market=best_match.market,
                url=best_match.url,
                version=best_match.version,
                message="Auto-install disabled; skill found but not installed",
            )

        install_info = {
            "id": best_match.skill_name,
            "name": best_match.skill_name,
            "source": best_match.market,
            "source_url": best_match.url,
            "url": best_match.url,
            "version": best_match.version,
            "description": best_match.description,
        }
        install_result = self._install_skill(best_match.skill_name, install_info)

        success = bool(install_result.get("success", False)) if isinstance(install_result, dict) else False
        if success:
            with self._lock:
                self._installed_skills[best_match.skill_name] = Skill(
                    name=best_match.skill_name,
                    description=best_match.description,
                    version=best_match.version,
                )
            return SkillAcquisitionResult(
                skill_name=best_match.skill_name,
                success=True,
                source=best_match.market,
                market=best_match.market,
                url=best_match.url,
                install_path=str(install_result.get("install_path", "")) if isinstance(install_result, dict) else "",
                version=best_match.version,
                message=f"Successfully installed from {best_match.market}",
            )
        return SkillAcquisitionResult(
            skill_name=best_match.skill_name,
            success=False,
            source=best_match.market,
            market=best_match.market,
            url=best_match.url,
            version=best_match.version,
            error=install_result.get("error", "Installation failed") if isinstance(install_result, dict) else "Installation failed",
        )

    # ── 匹配 ──

    def _select_best_match(self, skill_name: str, search_results: List[SearchResult]) -> Optional[SearchResult]:
        """按 _calculate_similarity 选最佳匹配；低于阈值返回 None"""
        if not search_results:
            return None

        best: Optional[SearchResult] = None
        best_score = -1.0
        for result in search_results:
            score = self._calculate_similarity(skill_name, result.skill_name)
            if score > best_score:
                best, best_score = result, score

        if best is not None and best_score >= self.SIMILARITY_THRESHOLD:
            return best
        return None

    def _calculate_similarity(self, a: str, b: str) -> float:
        """字符串相似度 (0-1)：归一化后 相等=1.0 / 包含=0.8 / 词元重叠按比例"""
        na = self._normalize(a)
        nb = self._normalize(b)
        if not na or not nb:
            return 0.0
        if na == nb:
            return 1.0
        if na in nb or nb in na:
            return 0.8
        ta, tb = set(na.split()), set(nb.split())
        if not ta or not tb:
            return 0.0
        overlap = len(ta & tb) / len(ta | tb)
        return round(overlap * 0.6, 4)

    @staticmethod
    def _normalize(text: str) -> str:
        """归一化：小写 + 连字符/下划线归一为空格"""
        return str(text or "").lower().replace("-", " ").replace("_", " ").strip()

    # ── 安装 ──

    def _install_skill(self, skill_name: str, skill_info: Dict[str, Any]) -> Dict[str, Any]:
        """安装技能 — DI importer 优先，兜底 SkillService（真实 zip 解压 + importlib 加载）"""
        source_url = skill_info.get("source_url") or skill_info.get("url", "")
        skill_id = skill_info.get("id") or skill_info.get("name") or skill_name

        if self.importer is not None:
            try:
                result = self.importer.install_skill(skill_info)
                if isinstance(result, dict):
                    with self._lock:
                        self._installed_cache[skill_id] = bool(result.get("success", False))
                    return result
                return {"success": False, "error": "importer returned non-dict result"}
            except Exception as e:  # noqa: BLE001
                logger.exception("DI importer failed to install skill %s: %s", skill_name, e)
                return {"success": False, "error": str(e)}

        service = self._get_skill_service()
        if not service:
            logger.warning("SkillService 不可用，无法安装 %s", skill_name)
            return {"success": False, "error": "SkillService not available"}

        try:
            result = service.install_skill(
                skill_path=source_url,
                skill_id=skill_id,
            )
            with self._lock:
                if isinstance(result, dict):
                    self._installed_cache[skill_id] = bool(result.get("success", False))
            return result if isinstance(result, dict) else {"success": bool(result)}
        except Exception as e:  # noqa: BLE001
            logger.exception("Failed to install skill %s: %s", skill_name, e)
            return {"success": False, "error": str(e)}

    # ── 建议 ──

    def suggest_skills(self, request: str, max_suggestions: int = 5) -> List[Dict[str, Any]]:
        """
        建议技能

        Returns:
            List[Dict]: {skill_name, already_installed, sources: [{skill_name,
                        market, url, version, description, similarity}]}
        """
        suggestions: List[Dict[str, Any]] = []

        decomposition = self.decomposer.decompose(request)
        required_skills = self._collect_required_skills(decomposition)

        installed = self._installed_names()

        for skill_name in required_skills[:max_suggestions]:
            if skill_name in installed:
                suggestions.append(
                    {
                        "skill_name": skill_name,
                        "already_installed": True,
                        "sources": [],
                    }
                )
                continue

            search_results = self.searcher.search_all_markets(skill_name)
            sources = []
            for result in search_results:
                similarity = self._calculate_similarity(skill_name, result.skill_name)
                sources.append(
                    {
                        "skill_name": result.skill_name,
                        "market": result.market,
                        "url": result.url,
                        "version": result.version,
                        "description": result.description,
                        "similarity": similarity,
                    }
                )
            suggestions.append(
                {
                    "skill_name": skill_name,
                    "already_installed": False,
                    "sources": sources,
                }
            )

        return suggestions[:max_suggestions]

    def get_acquisition_history(self) -> List[Dict[str, Any]]:
        """获取获取历史"""
        with self._lock:
            return [result.to_dict() for result in self._acquisition_history]

    def clear_history(self):
        """清除获取历史"""
        with self._lock:
            self._acquisition_history.clear()
        logger.info("Acquisition history cleared")

    def get_installed_skills(self) -> List[str]:
        """获取已安装技能列表"""
        with self._lock:
            return list(self._installed_skills.keys())

    def refresh_installed_skills(self):
        """刷新已安装技能缓存"""
        with self._lock:
            self._installed_skills.clear()
            self._installed_cache.clear()
        logger.info("Installed skills cache refreshed")
