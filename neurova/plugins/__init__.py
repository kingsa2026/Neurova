"""
Neurova Plugin System

插件系统提供动态加载和卸载功能
"""

# plugins imports
from neurova.plugins.base_plugin import (
    APIEndpoint,
    BasePlugin,
)

# 导出主要类
from neurova.plugins.plugin_manifest import (
    PluginManifest,
    PluginPermission,
    PluginState,
    PluginType,
    SemVersion,
    VersionConstraint,
    parse_manifest,
)

__all__ = [
    "SemVersion",
    "VersionConstraint",
    "PluginType",
    "PluginState",
    "PluginPermission",
    "PluginManifest",
    "parse_manifest",
    "BasePlugin",
    "APIEndpoint",
]
