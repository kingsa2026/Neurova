from __future__ import annotations

"""
插件清单定义 - 插件元数据、依赖、版本、权限

功能:
- 语义化版本 (SemVer) 解析与比较
- 插件清单数据结构 (JSON/YAML)
- 插件权限声明
- 插件类型分类
- 清单校验与序列化
"""

from dataclasses import dataclass
import enum
import json
import re
import typing

from enum import Enum

class SemVersion:
    """
    语义化版本
    
    遵循 SemVer 2.0.0 规范：主版本号.次版本号.修订号
    """
    
    def __init__(self, version_str: str = "0.0.0"):
        """初始化版本
        
        Args:
            version_str: 版本字符串，格式为 "主版本号.次版本号.修订号"
        """
        self.major = 0
        self.minor = 0
        self.patch = 0
        self.prerelease = ""
        self.build = ""
        
        self._parse(version_str)
    
    def _parse(self, version_str: str) -> None:
        """解析版本字符串
        
        Args:
            version_str: 版本字符串
        """
        # 移除前导 'v' 或 'V'
        if version_str.startswith(('v', 'V')):
            version_str = version_str[1:]
        
        # 分离构建元数据
        if '+' in version_str:
            version_str, self.build = version_str.split('+', 1)
        
        # 分离预发布版本
        if '-' in version_str:
            version_str, self.prerelease = version_str.split('-', 1)
        
        # 解析版本号
        parts = version_str.split('.')
        if len(parts) >= 1:
            self.major = int(parts[0])
        if len(parts) >= 2:
            self.minor = int(parts[1])
        if len(parts) >= 3:
            self.patch = int(parts[2])
    
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, SemVersion):
            return NotImplemented
        return (self.major, self.minor, self.patch, self.prerelease) == \
               (other.major, other.minor, other.patch, other.prerelease)
    
    def __lt__(self, other: 'SemVersion') -> bool:
        if not isinstance(other, SemVersion):
            return NotImplemented
        
        # 比较主版本号、次版本号、修订号
        if (self.major, self.minor, self.patch) != (other.major, other.minor, other.patch):
            return (self.major, self.minor, self.patch) < (other.major, other.minor, other.patch)
        
        # 比较预发布版本
        if self.prerelease and not other.prerelease:
            return True
        if not self.prerelease and other.prerelease:
            return False
        if self.prerelease and other.prerelease:
            return self.prerelease < other.prerelease
        
        return False
    
    def __le__(self, other: 'SemVersion') -> bool:
        return self == other or self < other
    
    def __gt__(self, other: 'SemVersion') -> bool:
        return not self <= other
    
    def __ge__(self, other: 'SemVersion') -> bool:
        return not self < other
    
    def __repr__(self) -> str:
        return f"SemVersion('{self}')"
    
    def __str__(self) -> str:
        version = f"{self.major}.{self.minor}.{self.patch}"
        if self.prerelease:
            version += f"-{self.prerelease}"
        if self.build:
            version += f"+{self.build}"
        return version
    
    def to_tuple(self) -> typing.Tuple[int, int, int]:
        """转换为元组
        
        Returns:
            (主版本号, 次版本号, 修订号)
        """
        return (self.major, self.minor, self.patch)
    
    def is_compatible_with(self, other: 'SemVersion') -> bool:
        """检查是否兼容
        
        Args:
            other: 其他版本
            
        Returns:
            是否兼容（主版本号相同）
        """
        return self.major == other.major

class VersionConstraint:
    """
    版本约束
    
    支持以下格式：
    - 精确版本: "1.0.0"
    - 比较运算符: ">=1.0.0", "<=2.0.0", ">1.0.0", "<2.0.0"
    - 兼容版本: "^1.2.3" (允许 1.x.x)
    - 近似版本: "~1.2.3" (允许 1.2.x)
    - 范围: ">=1.0.0,<=2.0.0"
    """
    
    def __init__(self, constraint_str: str):
        """初始化版本约束
        
        Args:
            constraint_str: 约束字符串
        """
        self.constraint_str = constraint_str
        self._parse(constraint_str)
    
    def _parse(self, constraint_str: str) -> None:
        """解析约束字符串"""
        self.constraints = []
        
        # 分割多个约束（逗号分隔）
        parts = [p.strip() for p in constraint_str.split(',')]
        
        for part in parts:
            if part.startswith('^'):
                # 兼容版本: ^1.2.3 -> >=1.2.3,<2.0.0
                version = SemVersion(part[1:])
                self.constraints.append(('>=', version))
                self.constraints.append(('<', SemVersion(f"{version.major + 1}.0.0")))
            elif part.startswith('~'):
                # 近似版本: ~1.2.3 -> >=1.2.3,<1.3.0
                version = SemVersion(part[1:])
                self.constraints.append(('>=', version))
                self.constraints.append(('<', SemVersion(f"{version.major}.{version.minor + 1}.0")))
            elif part.startswith('>='):
                self.constraints.append(('>=', SemVersion(part[2:])))
            elif part.startswith('<='):
                self.constraints.append(('<=', SemVersion(part[2:])))
            elif part.startswith('>'):
                self.constraints.append(('>', SemVersion(part[1:])))
            elif part.startswith('<'):
                self.constraints.append(('<', SemVersion(part[1:])))
            else:
                # 精确版本
                self.constraints.append(('==', SemVersion(part)))
    
    def satisfies(self, version: SemVersion) -> bool:
        """检查版本是否满足约束
        
        Args:
            version: 要检查的版本
            
        Returns:
            是否满足约束
        """
        for op, constraint_version in self.constraints:
            if op == '==':
                if version != constraint_version:
                    return False
            elif op == '>=':
                if version < constraint_version:
                    return False
            elif op == '<=':
                if version > constraint_version:
                    return False
            elif op == '>':
                if version <= constraint_version:
                    return False
            elif op == '<':
                if version >= constraint_version:
                    return False
        return True
    
    def __repr__(self) -> str:
        return f"VersionConstraint('{self.constraint_str}')"

class PluginType(str, Enum):
    """
    插件类型枚举
    """
    CORE = "core"
    SKILL = "skill"
    CHANNEL = "channel"
    TOOL = "tool"
    THEME = "theme"
    FUNCTIONAL = "functional"
    EXTENSION = "extension"

class PluginState(str, Enum):
    """
    插件状态枚举
    """
    INSTALLED = "installed"
    ENABLED = "enabled"
    DISABLED = "disabled"
    LOADED = "loaded"
    ERROR = "error"
    UPDATING = "updating"

class PluginPermission(str, Enum):
    """
    插件权限枚举
    """
    READ_EVENTS = "read:events"
    EMIT_EVENTS = "emit:events"
    HTTP_REQUEST = "http:request"
    READ_FILES = "read:files"
    WRITE_FILES = "write:files"
    EXECUTE_COMMANDS = "execute:commands"
    NETWORK_ACCESS = "network:access"
    ADMIN = "admin"

@dataclass
class PluginManifest:
    """
    插件清单数据结构
    """
    plugin_id: str
    name: str
    version: SemVersion
    description: str = ""
    author: str = ""
    plugin_type: PluginType = PluginType.FUNCTIONAL
    
    # 依赖
    dependencies: typing.Dict[str, str] = None
    optional_dependencies: typing.Dict[str, str] = None
    neurova_min_version: str = ""
    
    # 入口
    entry_point: str = ""
    module_class: str = ""
    
    # 权限
    required_permissions: typing.List[PluginPermission] = None
    
    # 配置
    config_schema: typing.Dict[str, typing.Any] = None
    default_config: typing.Dict[str, typing.Any] = None
    
    # API 端点
    api_endpoints: typing.List[typing.Dict[str, str]] = None
    
    # 前端资源
    frontend_resources: typing.List[str] = None
    
    # 标签和元数据
    tags: typing.List[str] = None
    homepage: str = ""
    license: str = ""
    
    def __post_init__(self):
        """初始化后处理"""
        if self.dependencies is None:
            self.dependencies = {}
        if self.optional_dependencies is None:
            self.optional_dependencies = {}
        if self.required_permissions is None:
            self.required_permissions = []
        if self.config_schema is None:
            self.config_schema = {}
        if self.default_config is None:
            self.default_config = {}
        if self.api_endpoints is None:
            self.api_endpoints = []
        if self.frontend_resources is None:
            self.frontend_resources = []
        if self.tags is None:
            self.tags = []
    
    def to_dict(self) -> typing.Dict[str, typing.Any]:
        """转换为字典"""
        return {
            "plugin_id": self.plugin_id,
            "name": self.name,
            "version": str(self.version),
            "description": self.description,
            "author": self.author,
            "plugin_type": self.plugin_type.value,
            "dependencies": self.dependencies,
            "optional_dependencies": self.optional_dependencies,
            "neurova_min_version": self.neurova_min_version,
            "entry_point": self.entry_point,
            "module_class": self.module_class,
            "required_permissions": [p.value for p in self.required_permissions],
            "config_schema": self.config_schema,
            "default_config": self.default_config,
            "api_endpoints": self.api_endpoints,
            "frontend_resources": self.frontend_resources,
            "tags": self.tags,
            "homepage": self.homepage,
            "license": self.license,
        }
    
    @classmethod
    def from_dict(cls, data: typing.Dict[str, typing.Any]) -> 'PluginManifest':
        """从字典创建"""
        # 必填字段
        plugin_id = data.get("plugin_id", "")
        name = data.get("name", "")
        version_str = data.get("version", "0.0.0")
        
        # 可选字段
        description = data.get("description", "")
        author = data.get("author", "")
        plugin_type_str = data.get("plugin_type", "functional")
        
        # 枚举转换
        plugin_type = PluginType(plugin_type_str)
        
        # 权限转换
        permissions = []
        for p in data.get("required_permissions", []):
            if isinstance(p, str):
                permissions.append(PluginPermission(p))
            else:
                permissions.append(p)
        
        return cls(
            plugin_id=plugin_id,
            name=name,
            version=SemVersion(version_str),
            description=description,
            author=author,
            plugin_type=plugin_type,
            dependencies=data.get("dependencies", {}),
            optional_dependencies=data.get("optional_dependencies", {}),
            neurova_min_version=data.get("neurova_min_version", ""),
            entry_point=data.get("entry_point", ""),
            module_class=data.get("module_class", ""),
            required_permissions=permissions,
            config_schema=data.get("config_schema", {}),
            default_config=data.get("default_config", {}),
            api_endpoints=data.get("api_endpoints", []),
            frontend_resources=data.get("frontend_resources", []),
            tags=data.get("tags", []),
            homepage=data.get("homepage", ""),
            license=data.get("license", ""),
        )

def parse_manifest(data: typing.Union[str, typing.Dict[str, typing.Any]]) -> PluginManifest:
    """
    解析插件清单
    
    Args:
        data: JSON 字符串或字典
        
    Returns:
        PluginManifest 实例
        
    Raises:
        ValueError: 解析失败或缺少必填字段
    """
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError as e:
            raise ValueError(f"无效的 JSON 格式: {e}")
    
    if not isinstance(data, dict):
        raise ValueError("数据必须是 JSON 字符串或字典")
    
    # 检查必填字段
    required_fields = ["plugin_id", "name", "version"]
    missing_fields = [f for f in required_fields if f not in data]
    if missing_fields:
        raise ValueError(f"缺少必填字段: {', '.join(missing_fields)}")
    
    return PluginManifest.from_dict(data)
