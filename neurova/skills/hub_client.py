from __future__ import annotations

"""
Skill Hub客户端 - 集成多源Skill安装

支持从GitHub、ClawHub、LobeHub等远程源搜索、安装和更新Skill。
Neurova Skill系统2.0架构。

主要功能:
- 从多个远程源搜索Skill
- 安装远程Skill到本地
- 更新已安装的Skill
- 列出远程可用的Skill
"""

import io
import json
import logging
import os
import re
import tarfile
import time
import zipfile
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)


class SkillSource(str, Enum):
    """技能来源枚举"""

    GITHUB = "github"
    CLAWHUB = "clawhub"
    LOBEHUB = "lobehub"
    MODELSCOPE = "modelscope"
    LOCAL = "local"


@dataclass
class RemoteSkill:
    """远程技能描述"""

    name: str
    source: SkillSource
    description: str = ""
    version: str = "0.0.0"
    author: str = ""
    url: str = ""
    download_url: str = ""
    tags: List[str] = field(default_factory=list)
    stars: int = 0
    downloads: int = 0
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "name": self.name,
            "source": self.source.value,
            "description": self.description,
            "version": self.version,
            "author": self.author,
            "url": self.url,
            "download_url": self.download_url,
            "tags": self.tags,
            "stars": self.stars,
            "downloads": self.downloads,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RemoteSkill":
        """从字典创建"""
        source = data.get("source", "github")
        if isinstance(source, str):
            source = SkillSource(source)

        return cls(
            name=data.get("name", ""),
            source=source,
            description=data.get("description", ""),
            version=data.get("version", "0.0.0"),
            author=data.get("author", ""),
            url=data.get("url", ""),
            download_url=data.get("download_url", ""),
            tags=data.get("tags", []),
            stars=data.get("stars", 0),
            downloads=data.get("downloads", 0),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
        )


# 缓存和配置函数
def _github_cache_ttl() -> int:
    """获取GitHub缓存TTL（秒）"""
    return int(os.environ.get("GITHUB_CACHE_TTL", "3600"))


def _github_cache_get(key: str) -> Optional[Any]:
    """从缓存获取数据"""
    # 这里应该实现实际的缓存逻辑
    # 暂时返回 None
    return None


def _github_cached(key: str) -> bool:
    """检查缓存是否命中"""
    return _github_cache_get(key) is not None


def _github_cache_set(key: str, value: Any, ttl: int = None) -> None:
    """设置缓存"""
    # 这里应该实现实际的缓存逻辑


def _http_timeout() -> float:
    """获取HTTP超时时间"""
    return float(os.environ.get("HTTP_TIMEOUT", "30"))


def _http_retries() -> int:
    """获取HTTP重试次数"""
    return int(os.environ.get("HTTP_RETRIES", "3"))


def _http_backoff_base() -> float:
    """获取退避基数"""
    return float(os.environ.get("HTTP_BACKOFF_BASE", "1"))


def _http_backoff_cap() -> float:
    """获取退避上限"""
    return float(os.environ.get("HTTP_BACKOFF_CAP", "60"))


def _compute_backoff_seconds(attempt: int) -> float:
    """计算退避时间"""
    import random

    base = _http_backoff_base()
    cap = _http_backoff_cap()
    backoff = min(cap, base * (2**attempt))
    return backoff + random.uniform(0, 1)


def _build_request(url: str, headers: Dict[str, str] = None) -> Request:
    """构建HTTP请求"""
    if headers is None:
        headers = {}

    # 添加默认头部
    headers.setdefault("User-Agent", "Neurova-SkillHub/1.0")
    headers.setdefault("Accept", "application/json")

    return Request(url, headers=headers)


def _http_fetch(url: str, headers: Dict[str, str] = None, timeout: float = None) -> bytes:
    """
    执行HTTP请求（带重试机制）

    Args:
        url: 请求 URL
        headers: 请求头
        timeout: 超时时间

    Returns:
        响应内容
    """
    if timeout is None:
        timeout = _http_timeout()

    retries = _http_retries()
    last_error = None

    for attempt in range(retries + 1):
        try:
            request = _build_request(url, headers)
            response = urlopen(request, timeout=timeout)
            return response.read()

        except (HTTPError, URLError) as e:
            last_error = e
            if attempt < retries:
                backoff = _compute_backoff_seconds(attempt)
                logger.warning("HTTP request failed (attempt %d), retrying in %.1fs: %s", attempt + 1, backoff, e)
                time.sleep(backoff)
            else:
                logger.error("HTTP request failed after %s attempts: %s", retries + 1, e)
                raise

    raise last_error


def _http_get(url: str, headers: Dict[str, str] = None, timeout: float = None) -> str:
    """
    执行HTTP GET请求，返回文本

    Args:
        url: 请求 URL
        headers: 请求头
        timeout: 超时时间

    Returns:
        响应文本
    """
    content = _http_fetch(url, headers, timeout)
    return content.decode("utf-8")


def _http_json_get(url: str, headers: Dict[str, str] = None, timeout: float = None) -> Any:
    """
    执行HTTP GET请求，返回解析后的JSON

    Args:
        url: 请求 URL
        headers: 请求头
        timeout: 超时时间

    Returns:
        解析后的 JSON 对象
    """
    text = _http_get(url, headers, timeout)
    return json.loads(text)


class SkillHubClient:
    """
    Skill Hub 客户端

    支持从多个远程源搜索、安装和更新 Skill。
    """

    def __init__(self, base_dir: str = None, config: Dict[str, Any] = None):
        """
        初始化 Skill Hub 客户端

        Args:
            base_dir: 基础目录路径
            config: 配置字典
        """
        self._base_dir = Path(base_dir) if base_dir else Path.home() / ".neurova" / "skills"
        self._config = config or {}

        # 技能源
        self._sources: Dict[str, Dict[str, Any]] = {}

        # 缓存
        self._cache: Dict[str, Any] = {}
        self._cache_ttl: Dict[str, float] = {}

        # 安装目录
        self._installed_dir = self._base_dir / "installed"
        self._installed_dir.mkdir(parents=True, exist_ok=True)

        # 注册默认源
        self._register_default_sources()

    def _register_default_sources(self) -> None:
        """注册默认技能源"""
        # GitHub 源
        self.register_source(
            name="github",
            source_type=SkillSource.GITHUB,
            config={
                "api_url": "https://api.github.com",
                "search_endpoint": "/search/repositories",
                "topics": ["neurova-skill", "neurova-plugin"],
            },
        )

        # ClawHub 源
        self.register_source(
            name="clawhub",
            source_type=SkillSource.CLAWHUB,
            config={
                "api_url": "https://clawhub.com/api",
                "search_endpoint": "/skills/search",
            },
        )

        # LobeHub 源
        self.register_source(
            name="lobehub",
            source_type=SkillSource.LOBEHUB,
            config={
                "api_url": "https://lobehub.com/api",
                "search_endpoint": "/plugins/search",
            },
        )

        logger.debug("Registered default skill sources")

    def register_source(self, name: str, source_type: SkillSource, config: Dict[str, Any]) -> None:
        """
        注册技能源

        Args:
            name: 源名称
            source_type: 源类型
            config: 源配置
        """
        self._sources[name] = {
            "type": source_type,
            "config": config,
            "enabled": True,
        }
        logger.debug("Registered skill source: %s", name)

    def search_skills(self, query: str, sources: List[str] = None, limit: int = 20) -> List[RemoteSkill]:
        """
        搜索技能

        Args:
            query: 搜索查询
            sources: 搜索源列表（None 表示所有源）
            limit: 返回结果数量限制

        Returns:
            远程技能列表
        """
        if sources is None:
            sources = list(self._sources.keys())

        all_results = []

        for source_name in sources:
            if source_name not in self._sources:
                logger.warning("Unknown source: %s", source_name)
                continue

            try:
                if source_name == "github":
                    results = self._search_github(query, limit)
                elif source_name == "clawhub":
                    results = self._search_clawhub(query, limit)
                elif source_name == "lobehub":
                    results = self._search_lobehub(query, limit)
                else:
                    logger.warning("Unsupported source: %s", source_name)
                    continue

                all_results.extend(results)

            except Exception as e:
                logger.error("Failed to search %s: %s", source_name, e)

        # 按相关性排序并限制结果数量
        all_results.sort(key=lambda x: x.stars, reverse=True)
        return all_results[:limit]

    def _search_github(self, query: str, limit: int = 20) -> List[RemoteSkill]:
        """搜索 GitHub"""
        try:
            # 构建搜索查询
            topics = self._sources["github"]["config"].get("topics", [])
            topic_query = " ".join([f"topic:{t}" for t in topics])
            search_query = f"{query} {topic_query}".strip()

            # 构建 URL
            api_url = self._sources["github"]["config"]["api_url"]
            endpoint = self._sources["github"]["config"]["search_endpoint"]
            url = f"{api_url}{endpoint}?q={quote(search_query)}&sort=stars&order=desc&per_page={limit}"

            # 添加 GitHub Token（如果有）
            headers = {}
            github_token = os.environ.get("GITHUB_TOKEN")
            if github_token:
                headers["Authorization"] = f"token {github_token}"

            # 执行搜索
            data = _http_json_get(url, headers)

            # 解析结果
            results = []
            for item in data.get("items", []):
                skill = RemoteSkill(
                    name=item.get("name", ""),
                    source=SkillSource.GITHUB,
                    description=item.get("description", ""),
                    version="latest",
                    author=item.get("owner", {}).get("login", ""),
                    url=item.get("html_url", ""),
                    download_url=item.get("html_url", "") + "/archive/main.zip",
                    tags=item.get("topics", []),
                    stars=item.get("stargazers_count", 0),
                    created_at=item.get("created_at", ""),
                    updated_at=item.get("updated_at", ""),
                )
                results.append(skill)

            return results

        except Exception as e:
            logger.error("GitHub search failed: %s", e)
            return []

    def _search_clawhub(self, query: str, limit: int = 20) -> List[RemoteSkill]:
        """搜索 ClawHub"""
        try:
            api_url = self._sources["clawhub"]["config"]["api_url"]
            endpoint = self._sources["clawhub"]["config"]["search_endpoint"]
            url = f"{api_url}{endpoint}?q={quote(query)}&limit={limit}"

            data = _http_json_get(url)

            results = []
            for item in data.get("skills", []):
                skill = RemoteSkill(
                    name=item.get("name", ""),
                    source=SkillSource.CLAWHUB,
                    description=item.get("description", ""),
                    version=item.get("version", "0.0.0"),
                    author=item.get("author", ""),
                    url=item.get("url", ""),
                    download_url=item.get("download_url", ""),
                    tags=item.get("tags", []),
                    downloads=item.get("downloads", 0),
                )
                results.append(skill)

            return results

        except Exception as e:
            logger.error("ClawHub search failed: %s", e)
            return []

    def _search_lobehub(self, query: str, limit: int = 20) -> List[RemoteSkill]:
        """搜索 LobeHub"""
        try:
            api_url = self._sources["lobehub"]["config"]["api_url"]
            endpoint = self._sources["lobehub"]["config"]["search_endpoint"]
            url = f"{api_url}{endpoint}?q={quote(query)}&limit={limit}"

            data = _http_json_get(url)

            results = []
            for item in data.get("plugins", []):
                skill = RemoteSkill(
                    name=item.get("name", ""),
                    source=SkillSource.LOBEHUB,
                    description=item.get("description", ""),
                    version=item.get("version", "0.0.0"),
                    author=item.get("author", ""),
                    url=item.get("homepage", ""),
                    download_url=item.get("download_url", ""),
                    tags=item.get("tags", []),
                    downloads=item.get("downloads", 0),
                )
                results.append(skill)

            return results

        except Exception as e:
            logger.error("LobeHub search failed: %s", e)
            return []

    def install_skill(self, skill: RemoteSkill) -> bool:
        """
        安装技能

        Args:
            skill: 远程技能

        Returns:
            是否安装成功
        """
        try:
            if skill.source == SkillSource.GITHUB:
                return self._install_from_github(skill)
            elif skill.source == SkillSource.CLAWHUB:
                return self._install_from_clawhub(skill)
            elif skill.source == SkillSource.LOBEHUB:
                return self._install_from_lobehub(skill)
            else:
                logger.error("Unsupported source for installation: %s", skill.source)
                return False

        except Exception as e:
            logger.error("Failed to install skill %s: %s", skill.name, e)
            return False

    def _install_from_github(self, skill: RemoteSkill) -> bool:
        """从 GitHub 安装技能"""
        try:
            # 下载技能包
            download_url = skill.download_url
            if not download_url:
                download_url = f"{skill.url}/archive/main.zip"

            # 下载并解压
            skill_dir = self._download_and_extract_skill(download_url, skill.name)

            # 解析技能配置
            self._parse_skill_md(skill_dir)

            logger.info("Installed skill %s from GitHub", skill.name)
            return True

        except Exception as e:
            logger.error("Failed to install from GitHub: %s", e)
            return False

    def _install_from_clawhub(self, skill: RemoteSkill) -> bool:
        """从 ClawHub 安装技能"""
        try:
            # 下载技能包
            download_url = skill.download_url
            if not download_url:
                logger.error("No download URL available")
                return False

            # 下载并解压
            self._download_and_extract_skill(download_url, skill.name)

            logger.info("Installed skill %s from ClawHub", skill.name)
            return True

        except Exception as e:
            logger.error("Failed to install from ClawHub: %s", e)
            return False

    def _install_from_lobehub(self, skill: RemoteSkill) -> bool:
        """从 LobeHub 安装技能"""
        try:
            # 下载技能包
            download_url = skill.download_url
            if not download_url:
                logger.error("No download URL available")
                return False

            # 下载并解压
            self._download_and_extract_skill(download_url, skill.name)

            logger.info("Installed skill %s from LobeHub", skill.name)
            return True

        except Exception as e:
            logger.error("Failed to install from LobeHub: %s", e)
            return False

    def _download_and_extract_skill(self, url: str, skill_name: str) -> Path:
        """
        下载并解压技能包

        Args:
            url: 下载 URL
            skill_name: 技能名称

        Returns:
            技能目录路径
        """
        # 下载文件
        content = _http_fetch(url)

        # 创建技能目录
        skill_dir = self._installed_dir / skill_name
        skill_dir.mkdir(parents=True, exist_ok=True)

        # 判断文件类型并解压
        if url.endswith(".zip"):
            # ZIP 文件
            with zipfile.ZipFile(io.BytesIO(content)) as zf:
                zf.extractall(skill_dir)
        elif url.endswith(".tar.gz") or url.endswith(".tgz"):
            # TAR.GZ 文件
            with tarfile.open(fileobj=io.BytesIO(content), mode="r:gz") as tf:
                tf.extractall(skill_dir)
        else:
            # 直接保存
            with open(skill_dir / "skill.py", "wb") as f:
                f.write(content)

        return skill_dir

    def _parse_skill_md(self, skill_dir: Path) -> Dict[str, Any]:
        """
        解析技能配置

        Args:
            skill_dir: 技能目录

        Returns:
            技能配置字典
        """
        # 查找配置文件
        config_files = ["skill.md", "manifest.json", "manifest.yaml", "manifest.yml"]

        for config_file in config_files:
            config_path = skill_dir / config_file
            if config_path.exists():
                try:
                    with open(config_path, "r", encoding="utf-8") as f:
                        if config_file.endswith(".json"):
                            return json.load(f)
                        elif config_file.endswith((".yaml", ".yml")):
                            import yaml

                            return yaml.safe_load(f)
                        else:
                            # 解析 Markdown 配置
                            return self._parse_markdown_config(f.read())
                except Exception as e:
                    logger.warning("Failed to parse %s: %s", config_file, e)

        return {}

    def _parse_markdown_config(self, content: str) -> Dict[str, Any]:
        """解析 Markdown 配置"""
        config = {}

        # 提取 YAML front matter
        match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
        if match:
            try:
                import yaml

                config = yaml.safe_load(match.group(1))
            except:
                pass

        return config

    def get_skill_latest_version(self, skill: RemoteSkill) -> str:
        """
        获取技能最新版本

        Args:
            skill: 远程技能

        Returns:
            最新版本号
        """
        try:
            if skill.source == SkillSource.GITHUB:
                return self._get_github_skill_version(skill)
            elif skill.source == SkillSource.CLAWHUB:
                return self._get_clawhub_skill_version(skill)
            elif skill.source == SkillSource.LOBEHUB:
                return self._get_lobehub_skill_version(skill)
            else:
                logger.error("Unsupported source for version check: %s", skill.source)
                return skill.version

        except Exception as e:
            logger.error("Failed to get latest version: %s", e)
            return skill.version

    def _get_github_skill_version(self, skill: RemoteSkill) -> str:
        """获取 GitHub 技能版本"""
        try:
            # 获取最新 release
            url = f"https://api.github.com/repos/{skill.author}/{skill.name}/releases/latest"
            headers = {}
            github_token = os.environ.get("GITHUB_TOKEN")
            if github_token:
                headers["Authorization"] = f"token {github_token}"

            data = _http_json_get(url, headers)
            return data.get("tag_name", skill.version)

        except Exception as e:
            logger.warning("Failed to get GitHub version: %s", e)
            return skill.version

    def _get_clawhub_skill_version(self, skill: RemoteSkill) -> str:
        """获取 ClawHub 技能版本"""
        try:
            url = f"{self._sources['clawhub']['config']['api_url']}/skills/{skill.name}/version"
            data = _http_json_get(url)
            return data.get("version", skill.version)
        except Exception as e:
            logger.warning("Failed to get ClawHub version: %s", e)
            return skill.version

    def _get_lobehub_skill_version(self, skill: RemoteSkill) -> str:
        """获取 LobeHub 技能版本"""
        try:
            url = f"{self._sources['lobehub']['config']['api_url']}/plugins/{skill.name}/version"
            data = _http_json_get(url)
            return data.get("version", skill.version)
        except Exception as e:
            logger.warning("Failed to get LobeHub version: %s", e)
            return skill.version

    def update_skill(self, skill: RemoteSkill) -> bool:
        """
        更新技能

        Args:
            skill: 远程技能

        Returns:
            是否更新成功
        """
        try:
            # 检查是否有新版本
            latest_version = self.get_skill_latest_version(skill)
            if latest_version == skill.version:
                logger.info("Skill %s is already up to date", skill.name)
                return True

            # 重新安装
            return self.install_skill(skill)

        except Exception as e:
            logger.error("Failed to update skill %s: %s", skill.name, e)
            return False

    def list_remote_skills(self, source: str = None, limit: int = 50) -> List[RemoteSkill]:
        """
        列出远程技能

        Args:
            source: 技能源（None 表示所有源）
            limit: 返回数量限制

        Returns:
            远程技能列表
        """
        if source:
            sources = [source]
        else:
            sources = list(self._sources.keys())

        all_skills = []

        for source_name in sources:
            try:
                if source_name == "github":
                    skills = self._list_github_skills(limit)
                elif source_name == "clawhub":
                    skills = self._list_clawhub_skills(limit)
                elif source_name == "lobehub":
                    skills = self._list_lobehub_skills(limit)
                else:
                    continue

                all_skills.extend(skills)

            except Exception as e:
                logger.error("Failed to list skills from %s: %s", source_name, e)

        return all_skills[:limit]

    def _list_github_skills(self, limit: int = 50) -> List[RemoteSkill]:
        """列出 GitHub 技能"""
        try:
            topics = self._sources["github"]["config"].get("topics", [])
            topic_query = " ".join([f"topic:{t}" for t in topics])

            api_url = self._sources["github"]["config"]["api_url"]
            endpoint = self._sources["github"]["config"]["search_endpoint"]
            url = f"{api_url}{endpoint}?q={quote(topic_query)}&sort=stars&order=desc&per_page={limit}"

            headers = {}
            github_token = os.environ.get("GITHUB_TOKEN")
            if github_token:
                headers["Authorization"] = f"token {github_token}"

            data = _http_json_get(url, headers)

            skills = []
            for item in data.get("items", []):
                skill = RemoteSkill(
                    name=item.get("name", ""),
                    source=SkillSource.GITHUB,
                    description=item.get("description", ""),
                    version="latest",
                    author=item.get("owner", {}).get("login", ""),
                    url=item.get("html_url", ""),
                    tags=item.get("topics", []),
                    stars=item.get("stargazers_count", 0),
                    created_at=item.get("created_at", ""),
                    updated_at=item.get("updated_at", ""),
                )
                skills.append(skill)

            return skills

        except Exception as e:
            logger.error("Failed to list GitHub skills: %s", e)
            return []

    def _list_clawhub_skills(self, limit: int = 50) -> List[RemoteSkill]:
        """列出 ClawHub 技能"""
        try:
            api_url = self._sources["clawhub"]["config"]["api_url"]
            url = f"{api_url}/skills?limit={limit}"

            data = _http_json_get(url)

            skills = []
            for item in data.get("skills", []):
                skill = RemoteSkill(
                    name=item.get("name", ""),
                    source=SkillSource.CLAWHUB,
                    description=item.get("description", ""),
                    version=item.get("version", "0.0.0"),
                    author=item.get("author", ""),
                    url=item.get("url", ""),
                    tags=item.get("tags", []),
                    downloads=item.get("downloads", 0),
                )
                skills.append(skill)

            return skills

        except Exception as e:
            logger.error("Failed to list ClawHub skills: %s", e)
            return []

    def _list_lobehub_skills(self, limit: int = 50) -> List[RemoteSkill]:
        """列出 LobeHub 技能"""
        try:
            api_url = self._sources["lobehub"]["config"]["api_url"]
            url = f"{api_url}/plugins?limit={limit}"

            data = _http_json_get(url)

            skills = []
            for item in data.get("plugins", []):
                skill = RemoteSkill(
                    name=item.get("name", ""),
                    source=SkillSource.LOBEHUB,
                    description=item.get("description", ""),
                    version=item.get("version", "0.0.0"),
                    author=item.get("author", ""),
                    url=item.get("homepage", ""),
                    tags=item.get("tags", []),
                    downloads=item.get("downloads", 0),
                )
                skills.append(skill)

            return skills

        except Exception as e:
            logger.error("Failed to list LobeHub skills: %s", e)
            return []
