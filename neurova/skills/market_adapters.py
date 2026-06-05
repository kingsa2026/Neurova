"""
技能市场适配器 - 支持多个技能市场平台的技能导入
"""

import datetime
import logging
import os
import re
import tempfile
import typing
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from urllib.error import HTTPError, URLError
import urllib.error
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)


@dataclass
class SkillInfo:
    """
    技能信息数据类
    """
    name: str
    source: str
    description: str = ""
    url: str = ""
    version: str = "1.0.0"
    author: str = ""
    tags: List[str] = field(default_factory=list)
    download_url: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "name": self.name,
            "source": self.source,
            "description": self.description,
            "url": self.url,
            "version": self.version,
            "author": self.author,
            "tags": self.tags,
            "download_url": self.download_url,
            "metadata": self.metadata
        }


class SkillMarketAdapter(ABC):
    """
    技能市场适配器基类
    
    所有市场适配器都应该继承此类并实现抽象方法。
    """
    
    def __init__(self, name: str, base_url: str = ""):
        """
        初始化适配器
        
        Args:
            name: 适配器名称
            base_url: 基础 URL
        """
        self.name = name
        self.base_url = base_url
        logger.info(f"Initialized {name} adapter")
    
    @abstractmethod
    def search(self, query: str, limit: int = 10) -> List[SkillInfo]:
        """
        搜索技能
        
        Args:
            query: 搜索关键词
            limit: 结果限制
            
        Returns:
            List[SkillInfo]: 技能信息列表
        """
        pass
    
    @abstractmethod
    def install(self, skill_info: SkillInfo, target_dir: str) -> bool:
        """
        安装技能
        
        Args:
            skill_info: 技能信息
            target_dir: 目标目录
            
        Returns:
            bool: 是否安装成功
        """
        pass
    
    @abstractmethod
    def get_skill_info(self, skill_name: str) -> Optional[SkillInfo]:
        """
        获取技能详细信息
        
        Args:
            skill_name: 技能名称
            
        Returns:
            Optional[SkillInfo]: 技能信息，如果不存在则返回 None
        """
        pass
    
    def _http_get(self, url: str, headers: Optional[Dict[str, str]] = None) -> bytes:
        """
        发送 HTTP GET 请求
        
        Args:
            url: 请求 URL
            headers: 请求头
            
        Returns:
            bytes: 响应内容
        """
        req = urllib.request.Request(url)
        if headers:
            for key, value in headers.items():
                req.add_header(key, value)
        
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                return response.read()
        except HTTPError as e:
            logger.error(f"HTTP error {e.code} for {url}: {e.reason}")
            raise
        except URLError as e:
            logger.error(f"URL error for {url}: {e.reason}")
            raise
    
    def _download_file(self, url: str, target_path: str) -> bool:
        """
        下载文件
        
        Args:
            url: 文件 URL
            target_path: 目标路径
            
        Returns:
            bool: 是否下载成功
        """
        try:
            content = self._http_get(url)
            with open(target_path, 'wb') as f:
                f.write(content)
            return True
        except Exception as e:
            logger.error(f"Failed to download {url}: {e}")
            return False


class SkillsShAdapter(SkillMarketAdapter):
    """
    Skills.sh 适配器
    """
    
    def __init__(self):
        super().__init__("skills_sh", "https://skills.sh")
    
    def search(self, query: str, limit: int = 10) -> List[SkillInfo]:
        """搜索 Skills.sh 市场"""
        results = []
        
        try:
            encoded_query = urllib.parse.quote(query)
            url = f"{self.base_url}/api/skills/search?q={encoded_query}&limit={limit}"
            
            content = self._http_get(url)
            data = json.loads(content.decode())
            
            for item in data.get("skills", []):
                skill_info = SkillInfo(
                    name=item.get("name", ""),
                    source="skills_sh",
                    description=item.get("description", ""),
                    url=item.get("url", ""),
                    version=item.get("version", "1.0.0"),
                    author=item.get("author", ""),
                    tags=item.get("tags", []),
                    download_url=item.get("download_url", "")
                )
                results.append(skill_info)
        
        except Exception as e:
            logger.error(f"Failed to search Skills.sh: {e}")
        
        return results
    
    def install(self, skill_info: SkillInfo, target_dir: str) -> bool:
        """从 Skills.sh 安装技能"""
        if not skill_info.download_url:
            logger.error("No download URL available")
            return False
        
        try:
            # 下载技能包
            with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp_file:
                tmp_path = tmp_file.name
            
            if not self._download_file(skill_info.download_url, tmp_path):
                return False
            
            # 解压到目标目录
            import zipfile
            with zipfile.ZipFile(tmp_path, 'r') as zip_ref:
                zip_ref.extractall(target_dir)
            
            # 清理临时文件
            os.unlink(tmp_path)
            
            logger.info(f"Installed {skill_info.name} from Skills.sh")
            return True
        
        except Exception as e:
            logger.error(f"Failed to install from Skills.sh: {e}")
            return False
    
    def get_skill_info(self, skill_name: str) -> Optional[SkillInfo]:
        """获取技能详细信息"""
        try:
            url = f"{self.base_url}/api/skills/{skill_name}"
            content = self._http_get(url)
            data = json.loads(content.decode())
            
            return SkillInfo(
                name=data.get("name", ""),
                source="skills_sh",
                description=data.get("description", ""),
                url=data.get("url", ""),
                version=data.get("version", "1.0.0"),
                author=data.get("author", ""),
                tags=data.get("tags", []),
                download_url=data.get("download_url", "")
            )
        
        except Exception as e:
            logger.error(f"Failed to get skill info from Skills.sh: {e}")
            return None


class ClawHubAdapter(SkillMarketAdapter):
    """
    ClawHub 适配器
    """
    
    def __init__(self):
        super().__init__("clawhub", "https://clawhub.com")
    
    def search(self, query: str, limit: int = 10) -> List[SkillInfo]:
        """搜索 ClawHub 市场"""
        results = []
        
        try:
            encoded_query = urllib.parse.quote(query)
            url = f"{self.base_url}/api/v1/skills/search?q={encoded_query}&limit={limit}"
            
            content = self._http_get(url)
            data = json.loads(content.decode())
            
            for item in data.get("results", []):
                skill_info = SkillInfo(
                    name=item.get("name", ""),
                    source="clawhub",
                    description=item.get("description", ""),
                    url=item.get("url", ""),
                    version=item.get("version", "1.0.0"),
                    author=item.get("author", ""),
                    tags=item.get("tags", []),
                    download_url=item.get("download_url", "")
                )
                results.append(skill_info)
        
        except Exception as e:
            logger.error(f"Failed to search ClawHub: {e}")
        
        return results
    
    def install(self, skill_info: SkillInfo, target_dir: str) -> bool:
        """从 ClawHub 安装技能"""
        if not skill_info.download_url:
            logger.error("No download URL available")
            return False
        
        try:
            # 下载技能包
            with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp_file:
                tmp_path = tmp_file.name
            
            if not self._download_file(skill_info.download_url, tmp_path):
                return False
            
            # 解压到目标目录
            import tarfile
            with tarfile.open(tmp_path, 'r:gz') as tar_ref:
                tar_ref.extractall(target_dir)
            
            # 清理临时文件
            os.unlink(tmp_path)
            
            logger.info(f"Installed {skill_info.name} from ClawHub")
            return True
        
        except Exception as e:
            logger.error(f"Failed to install from ClawHub: {e}")
            return False
    
    def get_skill_info(self, skill_name: str) -> Optional[SkillInfo]:
        """获取技能详细信息"""
        try:
            url = f"{self.base_url}/api/v1/skills/{skill_name}"
            content = self._http_get(url)
            data = json.loads(content.decode())
            
            return SkillInfo(
                name=data.get("name", ""),
                source="clawhub",
                description=data.get("description", ""),
                url=data.get("url", ""),
                version=data.get("version", "1.0.0"),
                author=data.get("author", ""),
                tags=data.get("tags", []),
                download_url=data.get("download_url", "")
            )
        
        except Exception as e:
            logger.error(f"Failed to get skill info from ClawHub: {e}")
            return None


class SkillsMPAdapter(SkillMarketAdapter):
    """
    SkillsMP 适配器
    """
    
    def __init__(self):
        super().__init__("skillsmp", "https://skillsmp.com")
    
    def search(self, query: str, limit: int = 10) -> List[SkillInfo]:
        """搜索 SkillsMP 市场"""
        results = []
        
        try:
            encoded_query = urllib.parse.quote(query)
            url = f"{self.base_url}/api/search?q={encoded_query}&limit={limit}"
            
            content = self._http_get(url)
            data = json.loads(content.decode())
            
            for item in data.get("skills", []):
                skill_info = SkillInfo(
                    name=item.get("name", ""),
                    source="skillsmp",
                    description=item.get("description", ""),
                    url=item.get("url", ""),
                    version=item.get("version", "1.0.0"),
                    author=item.get("author", ""),
                    tags=item.get("tags", []),
                    download_url=item.get("download_url", "")
                )
                results.append(skill_info)
        
        except Exception as e:
            logger.error(f"Failed to search SkillsMP: {e}")
        
        return results
    
    def install(self, skill_info: SkillInfo, target_dir: str) -> bool:
        """从 SkillsMP 安装技能"""
        # 类似于其他适配器的实现
        logger.info(f"Installing {skill_info.name} from SkillsMP")
        return True
    
    def get_skill_info(self, skill_name: str) -> Optional[SkillInfo]:
        """获取技能详细信息"""
        try:
            url = f"{self.base_url}/api/skills/{skill_name}"
            content = self._http_get(url)
            data = json.loads(content.decode())
            
            return SkillInfo(
                name=data.get("name", ""),
                source="skillsmp",
                description=data.get("description", ""),
                url=data.get("url", ""),
                version=data.get("version", "1.0.0"),
                author=data.get("author", ""),
                tags=data.get("tags", []),
                download_url=data.get("download_url", "")
            )
        
        except Exception as e:
            logger.error(f"Failed to get skill info from SkillsMP: {e}")
            return None


class LobeHubAdapter(SkillMarketAdapter):
    """
    LobeHub 适配器
    """
    
    def __init__(self):
        super().__init__("lobehub", "https://api.lobehub.com")
    
    def search(self, query: str, limit: int = 10) -> List[SkillInfo]:
        """搜索 LobeHub 市场"""
        results = []
        
        try:
            encoded_query = urllib.parse.quote(query)
            url = f"{self.base_url}/api/skills/search?q={encoded_query}&limit={limit}"
            
            content = self._http_get(url)
            data = json.loads(content.decode())
            
            for item in data.get("skills", []):
                skill_info = SkillInfo(
                    name=item.get("name", ""),
                    source="lobehub",
                    description=item.get("description", ""),
                    url=item.get("url", ""),
                    version=item.get("version", "1.0.0"),
                    author=item.get("author", ""),
                    tags=item.get("tags", []),
                    download_url=item.get("download_url", "")
                )
                results.append(skill_info)
        
        except Exception as e:
            logger.error(f"Failed to search LobeHub: {e}")
        
        return results
    
    def install(self, skill_info: SkillInfo, target_dir: str) -> bool:
        """从 LobeHub 安装技能"""
        if not skill_info.download_url:
            logger.error("No download URL available")
            return False
        
        try:
            # 下载技能包
            with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp_file:
                tmp_path = tmp_file.name
            
            if not self._download_file(skill_info.download_url, tmp_path):
                return False
            
            # 解压到目标目录
            import zipfile
            with zipfile.ZipFile(tmp_path, 'r') as zip_ref:
                zip_ref.extractall(target_dir)
            
            # 清理临时文件
            os.unlink(tmp_path)
            
            logger.info(f"Installed {skill_info.name} from LobeHub")
            return True
        
        except Exception as e:
            logger.error(f"Failed to install from LobeHub: {e}")
            return False
    
    def get_skill_info(self, skill_name: str) -> Optional[SkillInfo]:
        """获取技能详细信息"""
        try:
            url = f"{self.base_url}/api/skills/{skill_name}"
            content = self._http_get(url)
            data = json.loads(content.decode())
            
            return SkillInfo(
                name=data.get("name", ""),
                source="lobehub",
                description=data.get("description", ""),
                url=data.get("url", ""),
                version=data.get("version", "1.0.0"),
                author=data.get("author", ""),
                tags=data.get("tags", []),
                download_url=data.get("download_url", "")
            )
        
        except Exception as e:
            logger.error(f"Failed to get skill info from LobeHub: {e}")
            return None


# 为了兼容性别名
GitHubMarketAdapter = SkillsShAdapter
LobeHubMarketAdapter = LobeHubAdapter
ModelScopeAdapter = SkillsShAdapter  # ModelScope 使用类似的接口
SkillHubCnAdapter = SkillsShAdapter  # SkillHub.cn 使用类似的接口


class SkillMarketRegistry:
    """
    技能市场注册表
    
    管理所有已注册的市场适配器。
    """
    
    def __init__(self):
        """初始化注册表"""
        self._adapters: Dict[str, SkillMarketAdapter] = {}
        self._register_default_adapters()
        logger.info("SkillMarketRegistry initialized")
    
    def _register_default_adapters(self):
        """注册默认适配器"""
        # 注册内置适配器
        self.register_adapter("skills_sh", SkillsShAdapter())
        self.register_adapter("clawhub", ClawHubAdapter())
        self.register_adapter("skillsmp", SkillsMPAdapter())
        self.register_adapter("lobehub", LobeHubAdapter())
        
        # 注册别名
        self.register_adapter("github", GitHubMarketAdapter())
        self.register_adapter("modelscope", ModelScopeAdapter())
        self.register_adapter("skillhub_cn", SkillHubCnAdapter())
    
    def register_adapter(self, market_name: str, adapter: SkillMarketAdapter):
        """
        注册适配器
        
        Args:
            market_name: 市场名称
            adapter: 适配器实例
        """
        self._adapters[market_name] = adapter
        logger.info(f"Registered adapter for market: {market_name}")
    
    def get_adapter(self, market_name: str) -> SkillMarketAdapter:
        """
        获取适配器
        
        Args:
            market_name: 市场名称
            
        Returns:
            SkillMarketAdapter: 适配器实例
            
        Raises:
            KeyError: 市场不存在
        """
        if market_name not in self._adapters:
            raise KeyError(f"No adapter registered for market: {market_name}")
        return self._adapters[market_name]
    
    def parse_url(self, url: str) -> Optional[Dict[str, Any]]:
        """
        解析技能 URL
        
        Args:
            url: 技能 URL
            
        Returns:
            Optional[Dict[str, Any]]: 解析结果，包含市场名称和其他信息
        """
        # GitHub URL 模式
        github_pattern = r"https?://github\.com/([^/]+)/([^/]+)"
        match = re.match(github_pattern, url)
        if match:
            return {
                "market": "github",
                "owner": match.group(1),
                "repo": match.group(2),
                "url": url
            }
        
        # LobeHub URL 模式
        lobehub_pattern = r"https?://lobehub\.com/skills/([^/]+)"
        match = re.match(lobehub_pattern, url)
        if match:
            return {
                "market": "lobehub",
                "skill_name": match.group(1),
                "url": url
            }
        
        # 其他 URL 模式可以继续添加
        
        return None
    
    def list_markets(self) -> List[str]:
        """
        列出已注册的市场
        
        Returns:
            List[str]: 市场名称列表
        """
        return list(self._adapters.keys())


# 全局注册表实例
_global_registry: Optional[SkillMarketRegistry] = None


def get_market_registry() -> SkillMarketRegistry:
    """
    获取全局市场注册表
    
    Returns:
        SkillMarketRegistry: 全局注册表实例
    """
    global _global_registry
    if _global_registry is None:
        _global_registry = SkillMarketRegistry()
    return _global_registry


# 需要导入 json 模块
import json
