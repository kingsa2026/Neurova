"""
技能市场导入器

从技能市场导入和更新技能
"""

from __future__ import annotations

import datetime
import json
from neurova.core.logger import get_logger
import threading
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional
from neurova.core.data_root import get_data_root

logger = get_logger(__name__)

# 内置技能包资产目录（随包分发的离线技能 zip）
BUILTIN_BUNDLE_DIR = Path(__file__).resolve().parent / "market_bundles"


def read_builtin_bundle(name: str) -> Optional[bytes]:
    """读取随包内置技能 zip; 只接受裸文件名（防路径逃逸）, 缺失返回 None"""
    if not name or Path(name).name != name:
        return None
    try:
        return (BUILTIN_BUNDLE_DIR / name).read_bytes()
    except OSError:
        return None


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
    source: str = "local"  # 条目来源: local / aliyun / xfyun

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

    def __init__(self, skills_dir: Path):
        """
        Args:
            skills_dir: 技能安装目录

        这里过去还挂着一个「市场 API 地址」参数，它唯一的读者是「条目没地址就凭空拼
        一个」那句，而拼出来的域名从不存在（连注册源白名单都进不去）。那句摘掉之后
        这个属性就是写口无人读的断点，参数与属性一起退役。
        """
        self._skills_dir = Path(skills_dir)
        self._lock = threading.RLock()
        self._import_tasks: Dict[str, ImportTask] = {}
        self._installed: Dict[str, str] = {}  # skill_id -> version
        self._skills_dir.mkdir(parents=True, exist_ok=True)
        # 「装过什么」必须有读者（§6-188）：写侧一直在写 `<缓存根>/<id>/skill.json`，而读侧
        # 只有这本内存账 ⇒ 重启后市场页说没装、幂等补链分支永不触发、卸载面也认不出它。
        self._restoreInstalledFromDisk()

    def _restoreInstalledFromDisk(self) -> None:
        """从 `<缓存根>/*/skill.json` 重建已装账（只读，不改盘上任何东西）。

        键取**目录名**而不是文件里自报的 `skill_id`——`uninstall_skill` 删的就是这个目录，
        两者不同源时（复制/改名目录）会读出幽灵条目或删不掉。读不懂的记账件**出声跳过**：
        不把"我读不懂"读成"没装"，也不顺手覆盖别人的坏文件（那是毁证据）。
        """
        for metaPath in sorted(self._skills_dir.glob("*/skill.json")):
            try:
                with open(metaPath, "r", encoding="utf-8") as f:
                    meta = json.load(f)
            except (OSError, ValueError) as e:
                logger.warning("市场安装记账件读不懂，本次不采信也不改写 %s: %s", metaPath, e)
                continue
            if not isinstance(meta, dict):
                logger.warning("市场安装记账件不是对象，本次不采信: %s", metaPath)
                continue
            # 版本缺省如实标 unknown：force/升级判定会拿这枚值比，替它编一个就是假账
            self._installed[metaPath.parent.name] = str(meta.get("version") or "unknown")

    def search_skills(
        self,
        query: str = "",
        category: Optional[str] = None,
        tags: Optional[List[str]] = None,
        source: Optional[str] = None,
    ) -> List[MarketSkill]:
        """
        搜索市场技能

        数据源: 市场 Catalog(market_store) —— 管理端上架/更新/下架同源,
        首次访问以默认清单初始化(种子: web-search / code-analysis)。

        Args:
            query: 搜索关键词
            category: 分类过滤
            tags: 标签过滤
            source: 来源过滤 (local / aliyun / xfyun); None 不过滤

        Returns:
            匹配的技能列表
        """
        logger.info("Searching skills: query='%s', category=%s, tags=%s, source=%s", query, category, tags, source)

        try:
            from neurova.skills.market_store import get_market_store

            items = get_market_store().list_all()
        except Exception as e:  # noqa: BLE001 — catalog 不可用时降级空列表
            logger.warning("market catalog unavailable: %s", e)
            return []

        q = (query or "").strip().lower()
        result: List[MarketSkill] = []
        for item in items:
            if source:
                item_source = item.get("source") or "local"
                if item_source != source:
                    continue
            if q and q not in (item.get("name", "") + " " + item.get("description", "")).lower():
                continue
            if category and item.get("category") != category:
                continue
            if tags:
                item_tags = set(item.get("tags") or [])
                if not set(tags).issubset(item_tags):
                    continue
            result.append(
                MarketSkill(
                    skill_id=item.get("skill_id", ""),
                    name=item.get("name", item.get("skill_id", "")),
                    version=item.get("version", "1.0.0"),
                    description=item.get("description", ""),
                    author=item.get("author", ""),
                    # 没地址就是没地址：拼一个不存在的域名既骗人，又让安装闸的输入
                    # 永远"看着有来源"。
                    download_url=item.get("download_url", ""),
                    category=item.get("category", "general"),
                    tags=list(item.get("tags") or []),
                    rating=float(item.get("rating", 0.0)),
                    downloads=int(item.get("downloads", 0)),
                    updated_at=item.get("updated_at"),
                    source=item.get("source", "local"),
                )
            )
        return result

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

            try:
                task.status = ImportStatus.DOWNLOADING
                task.progress = 0.3

                # P0-4 安装时声明校验：catalog entry 携带的 permissions 在落盘
                # 前过安装门（fail-closed）；远端 zip 场景 permissions 取自
                # entry 元数据（SKILL.md frontmatter 由 hub_client 链路负责）
                entry = self._lookup_catalog_entry(skill_id)
                perm_raw = (entry or {}).get("permissions")
                if perm_raw is not None:
                    from neurova.skills.skill_install_gate import validate_permissions_for_install

                    perm_verdict = validate_permissions_for_install(perm_raw)
                    if perm_verdict.get("blocked"):
                        task.status = ImportStatus.FAILED
                        task.error_message = "权限声明校验失败: " + "; ".join(perm_verdict.get("errors", []))
                        logger.error(
                            "Skill '%s' rejected by permissions gate: %s",
                            skill_id,
                            task.error_message,
                        )
                        return task

                # 内置技能包条目: 从包内 market_bundles 资产离线解压（零网络）,
                # 资产缺失 FAIL 不静默模拟; 远端市场源条目: 真实下载 zip 并
                # 安全解压到 skills_dir/{skill_id}（SKILL.md 格式技能包;
                # 本地种子条目仍走原模拟链路）
                bundle_name = (entry or {}).get("bundle_zip")
                download_url = (entry or {}).get("download_url") or ""
                if bundle_name:
                    task.status = ImportStatus.INSTALLING
                    task.progress = 0.7
                    payload = read_builtin_bundle(str(bundle_name))
                    if payload is None:
                        task.status = ImportStatus.FAILED
                        task.error_message = f"builtin bundle missing: {bundle_name}"
                        logger.error("Failed to import skill '%s': %s", skill_id, task.error_message)
                        return task
                    dest = self._skills_dir / skill_id
                    if dest.exists():
                        import shutil

                        shutil.rmtree(dest, ignore_errors=True)
                    from neurova.skills import market_sources

                    refusal = market_sources.extractRemoteSkillZipRefusal(skill_id, payload, dest)
                    if refusal:
                        task.status = ImportStatus.FAILED
                        # 原因原样带进回执：折成一句 "failed" 会让人去改一个没坏的包（§6-259）
                        task.error_message = f"extract builtin bundle {bundle_name} failed: {refusal}"
                        logger.error("Failed to import skill '%s': %s", skill_id, task.error_message)
                        return task
                elif download_url:
                    from neurova.skills import market_sources

                    if market_sources.is_remote_market_url(download_url):
                        task.status = ImportStatus.INSTALLING
                        task.progress = 0.7
                        dest = self._skills_dir / skill_id
                        if dest.exists():
                            import shutil

                            shutil.rmtree(dest, ignore_errors=True)
                        refusal = market_sources.downloadAndExtractRefusal(skill_id, download_url, dest)
                        if refusal:
                            task.status = ImportStatus.FAILED
                            task.error_message = f"download/extract skill from {download_url} failed: {refusal}"
                            logger.error("Failed to import skill '%s': remote download failed", skill_id)
                            return task

                # 三条取件腿（内置包／已注册远端源／代码侧执行体映射）全不成立时，下面
                # 两步写出来的就只有账本：装"成功"了，目录里什么都没有，读面只能把它
                # 标灰。本机 code-analysis 的空壳、以及管理端任何一条不填可取件地址的
                # 上架，走的都是这条尾巴。
                if self.artifactSourceKind(skill_id) is None:
                    task.status = ImportStatus.FAILED
                    task.error_message = (
                        "无可取件地址：条目既无内置技能包（bundle_zip），download_url 也不属"
                        "已注册远端源，且没有代码侧执行体映射——拒绝落一具只会让技能页标灰的空壳")
                    logger.error("Refused zero-byte install for '%s'", skill_id)
                    return task

                task.status = ImportStatus.INSTALLING
                task.progress = 0.7

                skill_dir = self._skills_dir / skill_id
                skill_dir.mkdir(parents=True, exist_ok=True)

                # 写入安装元数据（远端技能 zip 内文件已就位，再补 skill.json）
                installed_version = version or (entry or {}).get("version") or "1.0.0"
                skill_meta = {
                    "skill_id": skill_id,
                    "version": installed_version,
                    "installed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                }
                # P0-4：通过校验的权限声明随 skill.json 持久化。
                # ⚠ 这只是一份**安装留底**，不是运行时读取源——全仓对该文件零读者
                # （§6-177 逐条复算：两处写侧 + 摘要排除清单里那一行常量）。运行时
                # 权限裁决读的是技能账本条目，别照着这句话接读侧。
                if perm_raw is not None:
                    from neurova.skills.permissions import SkillPermissions

                    skill_meta["permissions"] = SkillPermissions.from_dict(perm_raw).to_dict()
                (skill_dir / "skill.json").write_text(
                    json.dumps(skill_meta, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )

                task.status = ImportStatus.COMPLETED
                task.progress = 1.0
                task.completed_at = datetime.datetime.now(datetime.timezone.utc)
                self._installed[skill_id] = installed_version

                logger.info("Successfully imported skill '%s'", skill_id)

            except Exception as e:
                task.status = ImportStatus.FAILED
                task.error_message = str(e)
                logger.error("Failed to import skill '%s': %s", skill_id, e)

            return task

    def _lookup_catalog_entry(self, skill_id: str) -> Optional[Dict[str, Any]]:
        """从市场 catalog 精确查找条目（拿 download_url/version）"""
        try:
            from neurova.skills.market_store import get_market_store

            return get_market_store().get(skill_id)
        except Exception as e:  # noqa: BLE001 — catalog 不可用仍可走旧模拟链路
            logger.warning("market catalog lookup failed for %s: %s", skill_id, e)
            return None

    def artifactSourceKind(self, skill_id: str) -> Optional[str]:
        """这一条靠哪条腿取到字节：`bundle`／`remote`／`mapped`；三条全无 ⇒ None。

        单点在这里，是因为咽喉（该不该装作安装成功）与端点（该回 4xx 还是 500）问的是
        同一个问题；两处各写一份，就会出现"端点以为有来源、咽喉悄悄落了空壳"的分裂读数。
        """
        entry = self._lookup_catalog_entry(skill_id) or {}
        if entry.get("bundle_zip"):
            return "bundle"
        url = str(entry.get("download_url") or "")
        if url:
            from neurova.skills import market_sources

            if market_sources.is_remote_market_url(url):
                return "remote"
        from neurova.skills.market_registry import hasExecutorMapping

        return "mapped" if hasExecutorMapping(skill_id) else None

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
                    skills_dir = get_data_root() / "skills"
                _market_importer = MarketImporter(skills_dir=skills_dir)
    return _market_importer


def reset_market_importer() -> None:
    """重置全局市场导入器（用于测试）"""
    global _market_importer
    with _importer_lock:
        _market_importer = None
