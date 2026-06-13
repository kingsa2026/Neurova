"""
技能市场导入器

从技能市场导入和更新技能
"""

from __future__ import annotations

import datetime
import json
import logging
import threading
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ImportStatus(str, Enum):
    """导入状态"""

    PENDING = "pending"
    DOWNLOADING = "downloading"
    INSTALLING = "installing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class MarketSkill:
    """市场技能信息"""

    skill_id: str
    name: str
    version: str
    description: str
    author: str
    download_url: str
    category: str = ""
    tags: List[str] = field(default_factory=list)
    rating: float = 0.0
    downloads: int = 0
    updated_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "author": self.author,
            "download_url": self.download_url,
            "category": self.category,
            "tags": self.tags,
            "rating": self.rating,
            "downloads": self.downloads,
            "updated_at": self.updated_at,
        }


@dataclass
class ImportTask:
    """导入任务"""

    skill_id: str
    status: ImportStatus = ImportStatus.PENDING
    progress: float = 0.0
    error_message: Optional[str] = None
    started_at: Optional[datetime.datetime] = None
    completed_at: Optional[datetime.datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "status": self.status.value,
            "progress": self.progress,
            "error_message": self.error_message,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


class MarketImporter:
    """
    技能市场导入器

    支持从技能市场导入、更新和管理技能。
    """

    def __init__(self, skills_dir: Path, market_url: Optional[str] = None):
        """
        Args:
            skills_dir: 技能安装目录
            market_url: 市场API地址
        """
        self._skills_dir = Path(skills_dir)
        self._market_url = market_url or "https://api.neurova.dev/skills"
        self._lock = threading.RLock()
        self._import_tasks: Dict[str, ImportTask] = {}
        self._installed: Dict[str, str] = {}  # skill_id -> version
        self._skills_dir.mkdir(parents=True, exist_ok=True)

    def search_skills(
        self,
        query: str = "",
        category: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> List[MarketSkill]:
        """
        搜索市场技能

        Args:
            query: 搜索关键词
            category: 分类过滤
            tags: 标签过滤

        Returns:
            匹配的技能列表
        """
        # 模拟搜索结果（实际实现应调用市场API）
        logger.info("Searching skills: query='%s', category=%s, tags=%s", query, category, tags)

        # 返回示例数据
        return [
            MarketSkill(
                skill_id="web-search",
                name="Web Search",
                version="1.2.0",
                description="搜索互联网获取实时信息",
                author="Neurova Team",
                download_url=f"{self._market_url}/web-search/download",
                category="utility",
                tags=["search", "web", "information"],
                rating=4.5,
                downloads=1000,
            ),
            MarketSkill(
                skill_id="code-analysis",
                name="Code Analysis",
                version="2.0.1",
                description="分析和审查代码质量",
                author="Neurova Team",
                download_url=f"{self._market_url}/code-analysis/download",
                category="development",
                tags=["code", "analysis", "review"],
                rating=4.8,
                downloads=500,
            ),
        ]

    def import_skill(
        self,
        skill_id: str,
        version: Optional[str] = None,
        force: bool = False,
    ) -> ImportTask:
        """
        导入技能

        Args:
            skill_id: 技能ID
            version: 指定版本，默认最新
            force: 强制重新安装

        Returns:
            导入任务
        """
        with self._lock:
            # 检查是否已安装
            if not force and skill_id in self._installed:
                logger.info("Skill '%s' already installed (v%s)", skill_id, self._installed[skill_id])
                task = ImportTask(skill_id=skill_id, status=ImportStatus.COMPLETED)
                return task

            # 创建导入任务
            task = ImportTask(
                skill_id=skill_id,
                status=ImportStatus.PENDING,
                started_at=datetime.datetime.now(datetime.timezone.utc),
            )
            self._import_tasks[skill_id] = task

            # 模拟导入过程（实际实现应下载和安装）
            try:
                task.status = ImportStatus.DOWNLOADING
                task.progress = 0.3

                # 模拟下载完成
                task.status = ImportStatus.INSTALLING
                task.progress = 0.7

                # 模拟安装完成
                skill_dir = self._skills_dir / skill_id
                skill_dir.mkdir(parents=True, exist_ok=True)

                # 写入简单的 skill.json
                skill_meta = {
                    "skill_id": skill_id,
                    "version": version or "1.0.0",
                    "installed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                }
                (skill_dir / "skill.json").write_text(
                    json.dumps(skill_meta, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )

                task.status = ImportStatus.COMPLETED
                task.progress = 1.0
                task.completed_at = datetime.datetime.now(datetime.timezone.utc)
                self._installed[skill_id] = version or "1.0.0"

                logger.info("Successfully imported skill '%s'", skill_id)

            except Exception as e:
                task.status = ImportStatus.FAILED
                task.error_message = str(e)
                logger.error("Failed to import skill '%s': %s", skill_id, e)

            return task

    def get_import_status(self, skill_id: str) -> Optional[ImportTask]:
        """获取导入状态"""
        with self._lock:
            return self._import_tasks.get(skill_id)

    def list_installed(self) -> List[Dict[str, str]]:
        """列出已安装的技能"""
        with self._lock:
            return [{"skill_id": sid, "version": ver} for sid, ver in self._installed.items()]

    def uninstall_skill(self, skill_id: str) -> bool:
        """卸载技能"""
        with self._lock:
            if skill_id not in self._installed:
                return False

            skill_dir = self._skills_dir / skill_id
            if skill_dir.exists():
                import shutil

                shutil.rmtree(skill_dir)

            del self._installed[skill_id]
            logger.info("Uninstalled skill '%s'", skill_id)
            return True

    def check_updates(self) -> List[Dict[str, str]]:
        """检查技能更新"""
        updates = []
        with self._lock:
            for skill_id, current_version in self._installed.items():
                # 模拟版本检查（实际实现应调用市场API）
                updates.append(
                    {
                        "skill_id": skill_id,
                        "current_version": current_version,
                        "latest_version": current_version,  # 模拟无更新
                        "update_available": False,
                    }
                )
        return updates


# 全局单例
_market_importer: Optional[MarketImporter] = None
_importer_lock = threading.Lock()


def get_market_importer(skills_dir: Optional[Path] = None) -> MarketImporter:
    """获取全局市场导入器单例"""
    global _market_importer
    if _market_importer is None:
        with _importer_lock:
            if _market_importer is None:
                if skills_dir is None:
                    skills_dir = Path("data/skills")
                _market_importer = MarketImporter(skills_dir=skills_dir)
    return _market_importer


def reset_market_importer() -> None:
    """重置全局市场导入器（用于测试）"""
    global _market_importer
    with _importer_lock:
        _market_importer = None
