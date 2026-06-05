"""
Neurova Plugin System

插件系统提供动态加载和卸载功能
"""

# plugins imports
import neurova.plugins.base_plugin
import neurova.plugins.plugin_manifest

# 导出主要类
from neurova.plugins.plugin_manifest import (
    SemVersion,
    VersionConstraint,
    PluginType,
    PluginState,
    PluginPermission,
    PluginManifest,
    parse_manifest,
)

from neurova.plugins.base_plugin import (
    BasePlugin,
    APIEndpoint,
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