from __future__ import annotations

"""
插件管理器 - 插件加载/卸载/发现/依赖解析/版本控制

功能:
- 插件发现 (扫描目录)
- 插件安装/卸载
- 插件加载/卸载 (动态)
- 插件启用/禁用
- 依赖解析 (拓扑排序)
- 版本兼容性检查
- 通过核心模块库管理插件生命周期
"""

import importlib
import importlib.util
import json
import logging
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Type

import yaml

logger = logging.getLogger(__name__)


@dataclass
class PluginRecord:
    """
    插件记录数据类
    """

    name: str
    version: str = "1.0.0"
    description: str = ""
    author: str = ""
    enabled: bool = False
    loaded: bool = False
    path: str = ""
    entry_point: str = "main.py"
    dependencies: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    install_time: float = 0.0
    load_time: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "author": self.author,
            "enabled": self.enabled,
            "loaded": self.loaded,
            "path": self.path,
            "entry_point": self.entry_point,
            "dependencies": self.dependencies,
            "metadata": self.metadata,
            "install_time": self.install_time,
            "load_time": self.load_time,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PluginRecord":
        """从字典创建"""
        return cls(
            name=data.get("name", ""),
            version=data.get("version", "1.0.0"),
            description=data.get("description", ""),
            author=data.get("author", ""),
            enabled=data.get("enabled", False),
            loaded=data.get("loaded", False),
            path=data.get("path", ""),
            entry_point=data.get("entry_point", "main.py"),
            dependencies=data.get("dependencies", []),
            metadata=data.get("metadata", {}),
            install_time=data.get("install_time", 0.0),
            load_time=data.get("load_time", 0.0),
        )


class PluginManager:
    """
    插件管理器

    管理插件的完整生命周期：发现、安装、加载、启用、禁用、卸载。
    """

    def __init__(self, plugin_dir: Optional[str] = None):
        """
        初始化插件管理器

        Args:
            plugin_dir: 插件目录路径
        """
        self._plugin_dir = plugin_dir or str(Path.home() / ".neurova" / "plugins")
        self._plugins: Dict[str, PluginRecord] = {}
        self._modules: Dict[str, Any] = {}
        self._lifecycle_manager = None

        # 确保插件目录存在
        Path(self._plugin_dir).mkdir(parents=True, exist_ok=True)

        logger.info("PluginManager initialized with plugin dir: %s", self._plugin_dir)

    @property
    def plugin_dir(self) -> str:
        """获取插件目录"""
        return self._plugin_dir

    def set_plugin_dir(self, plugin_dir: str):
        """
        设置插件目录

        Args:
            plugin_dir: 插件目录路径
        """
        self._plugin_dir = plugin_dir
        Path(plugin_dir).mkdir(parents=True, exist_ok=True)
        logger.info("Plugin directory set to: %s", plugin_dir)

    def discover_plugins(self) -> List[PluginRecord]:
        """
        发现插件

        Returns:
            List[PluginRecord]: 发现的插件列表
        """
        discovered = []
        plugin_dir = Path(self._plugin_dir)

        if not plugin_dir.exists():
            logger.warning("Plugin directory does not exist: %s", plugin_dir)
            return discovered

        for item in plugin_dir.iterdir():
            if item.is_dir():
                # 检查是否有 manifest 文件
                manifest = self._load_manifest(item)
                if manifest:
                    try:
                        record = PluginRecord(
                            name=manifest.get("name", item.name),
                            version=manifest.get("version", "1.0.0"),
                            description=manifest.get("description", ""),
                            author=manifest.get("author", ""),
                            path=str(item),
                            entry_point=manifest.get("entry_point", "main.py"),
                            dependencies=manifest.get("dependencies", []),
                            metadata=manifest.get("metadata", {}),
                        )
                        discovered.append(record)
                    except Exception as e:
                        logger.error("Failed to load plugin manifest from %s: %s", item, e)

        logger.info("Discovered %s plugins", len(discovered))
        return discovered

    def _load_manifest(self, plugin_path: Path) -> Optional[Dict[str, Any]]:
        """
        加载插件清单

        Args:
            plugin_path: 插件路径

        Returns:
            Optional[Dict[str, Any]]: 清单数据
        """
        # 尝试加载 manifest.json
        manifest_json = plugin_path / "manifest.json"
        if manifest_json.exists():
            try:
                with open(manifest_json, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error("Failed to load manifest.json from %s: %s", plugin_path, e)

        # 尝试加载 manifest.yaml
        manifest_yaml = plugin_path / "manifest.yaml"
        if manifest_yaml.exists():
            try:
                with open(manifest_yaml, "r", encoding="utf-8") as f:
                    return yaml.safe_load(f)
            except Exception as e:
                logger.error("Failed to load manifest.yaml from %s: %s", plugin_path, e)

        # 尝试加载 plugin.json
        plugin_json = plugin_path / "plugin.json"
        if plugin_json.exists():
            try:
                with open(plugin_json, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error("Failed to load plugin.json from %s: %s", plugin_path, e)

        return None

    def install_plugin(self, plugin_source: Any) -> bool:
        """
        安装插件

        Args:
            plugin_source: 插件源（路径或 URL）

        Returns:
            bool: 是否安装成功
        """
        try:
            # 如果是路径
            if isinstance(plugin_source, (str, Path)):
                plugin_path = Path(plugin_source)

                if not plugin_path.exists():
                    logger.error("Plugin source does not exist: %s", plugin_path)
                    return False

                if not plugin_path.is_dir():
                    logger.error("Plugin source is not a directory: %s", plugin_path)
                    return False

                # 加载清单
                manifest = self._load_manifest(plugin_path)
                if not manifest:
                    logger.error("No manifest found in %s", plugin_path)
                    return False

                # 创建插件记录
                record = PluginRecord(
                    name=manifest.get("name", plugin_path.name),
                    version=manifest.get("version", "1.0.0"),
                    description=manifest.get("description", ""),
                    author=manifest.get("author", ""),
                    path=str(plugin_path),
                    entry_point=manifest.get("entry_point", "main.py"),
                    dependencies=manifest.get("dependencies", []),
                    metadata=manifest.get("metadata", {}),
                    install_time=time.time(),
                )

                # 检查依赖
                if not self._check_dependencies(record):
                    logger.error("Dependencies not satisfied for plugin %s", record.name)
                    return False

                # 添加到插件列表
                self._plugins[record.name] = record
                logger.info("Installed plugin: %s v%s", record.name, record.version)

                return True

            # 如果是 URL（简化实现）
            elif isinstance(plugin_source, str) and plugin_source.startswith(("http://", "https://")):
                logger.warning("URL installation not yet implemented")
                return False

            else:
                logger.error("Invalid plugin source: %s", plugin_source)
                return False

        except Exception as e:
            logger.error("Failed to install plugin: %s", e)
            return False

    def uninstall_plugin(self, plugin_name: str) -> bool:
        """
        卸载插件

        Args:
            plugin_name: 插件名称

        Returns:
            bool: 是否卸载成功
        """
        if plugin_name not in self._plugins:
            logger.error("Plugin not found: %s", plugin_name)
            return False

        try:
            # 先禁用和卸载
            if self._plugins[plugin_name].enabled:
                self.disable_plugin(plugin_name)

            if self._plugins[plugin_name].loaded:
                self.unload_plugin(plugin_name)

            # 删除插件记录
            del self._plugins[plugin_name]

            # 删除模块缓存
            if plugin_name in self._modules:
                del self._modules[plugin_name]

            logger.info("Uninstalled plugin: %s", plugin_name)
            return True

        except Exception as e:
            logger.error("Failed to uninstall plugin %s: %s", plugin_name, e)
            return False

    def load_plugin(self, plugin_name: str) -> bool:
        """
        加载插件

        Args:
            plugin_name: 插件名称

        Returns:
            bool: 是否加载成功
        """
        if plugin_name not in self._plugins:
            logger.error("Plugin not found: %s", plugin_name)
            return False

        record = self._plugins[plugin_name]

        if record.loaded:
            logger.warning("Plugin already loaded: %s", plugin_name)
            return True

        if not record.enabled:
            logger.error("Plugin is not enabled: %s", plugin_name)
            return False

        try:
            # 加载插件模块
            module = self._load_plugin_module(record)
            if module is None:
                return False

            # 查找插件类
            plugin_class = self._find_module_class(module)
            if plugin_class is None:
                logger.error("No plugin class found in %s", plugin_name)
                return False

            # 实例化插件
            plugin_instance = plugin_class()

            # 存储模块和实例
            self._modules[plugin_name] = {"module": module, "instance": plugin_instance, "class": plugin_class}

            # 更新记录
            record.loaded = True
            record.load_time = time.time()

            logger.info("Loaded plugin: %s", plugin_name)
            return True

        except Exception as e:
            logger.error("Failed to load plugin %s: %s", plugin_name, e)
            return False

    def _load_plugin_module(self, record: PluginRecord) -> Optional[Any]:
        """
        加载插件模块

        Args:
            record: 插件记录

        Returns:
            Optional[Any]: 加载的模块
        """
        try:
            plugin_path = Path(record.path)
            entry_point = plugin_path / record.entry_point

            if not entry_point.exists():
                logger.error("Entry point not found: %s", entry_point)
                return None

            # 动态导入模块
            spec = importlib.util.spec_from_file_location(f"neurova_plugin_{record.name}", str(entry_point))
            if spec is None or spec.loader is None:
                logger.error("Failed to create module spec for %s", record.name)
                return None

            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)

            return module

        except Exception as e:
            logger.error("Failed to load plugin module %s: %s", record.name, e)
            return None

    def _find_module_class(self, module: Any) -> Optional[Type]:
        """
        查找模块中的插件类

        Args:
            module: 模块

        Returns:
            Optional[Type]: 插件类
        """
        # 查找继承自 BasePlugin 的类
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if (
                isinstance(attr, type)
                and attr_name != "BasePlugin"
                and hasattr(attr, "__init__")
                and hasattr(attr, "on_enable")
            ):
                return attr

        return None

    def unload_plugin(self, plugin_name: str) -> bool:
        """
        卸载插件

        Args:
            plugin_name: 插件名称

        Returns:
            bool: 是否卸载成功
        """
        if plugin_name not in self._plugins:
            logger.error("Plugin not found: %s", plugin_name)
            return False

        record = self._plugins[plugin_name]

        if not record.loaded:
            logger.warning("Plugin not loaded: %s", plugin_name)
            return True

        try:
            # 获取插件实例
            if plugin_name in self._modules:
                instance = self._modules[plugin_name].get("instance")
                if instance and hasattr(instance, "on_disable"):
                    instance.on_disable()

                # 清理模块
                del self._modules[plugin_name]

            # 更新记录
            record.loaded = False

            logger.info("Unloaded plugin: %s", plugin_name)
            return True

        except Exception as e:
            logger.error("Failed to unload plugin %s: %s", plugin_name, e)
            return False

    def enable_plugin(self, plugin_name: str) -> bool:
        """
        启用插件

        Args:
            plugin_name: 插件名称

        Returns:
            bool: 是否启用成功
        """
        if plugin_name not in self._plugins:
            logger.error("Plugin not found: %s", plugin_name)
            return False

        record = self._plugins[plugin_name]

        if record.enabled:
            logger.warning("Plugin already enabled: %s", plugin_name)
            return True

        try:
            # 检查依赖
            if not self._check_dependencies(record):
                logger.error("Dependencies not satisfied for plugin %s", plugin_name)
                return False

            # 启用插件
            record.enabled = True

            # 如果已加载，调用 on_enable
            if record.loaded and plugin_name in self._modules:
                instance = self._modules[plugin_name].get("instance")
                if instance and hasattr(instance, "on_enable"):
                    instance.on_enable()

            logger.info("Enabled plugin: %s", plugin_name)
            return True

        except Exception as e:
            logger.error("Failed to enable plugin %s: %s", plugin_name, e)
            return False

    def disable_plugin(self, plugin_name: str) -> bool:
        """
        禁用插件

        Args:
            plugin_name: 插件名称

        Returns:
            bool: 是否禁用成功
        """
        if plugin_name not in self._plugins:
            logger.error("Plugin not found: %s", plugin_name)
            return False

        record = self._plugins[plugin_name]

        if not record.enabled:
            logger.warning("Plugin already disabled: %s", plugin_name)
            return True

        try:
            # 检查是否有其他插件依赖此插件
            dependents = self._get_dependents(plugin_name)
            if dependents:
                logger.error("Cannot disable plugin %s: other plugins depend on it: %s", plugin_name, dependents)
                return False

            # 禁用插件
            record.enabled = False

            # 如果已加载，调用 on_disable
            if record.loaded and plugin_name in self._modules:
                instance = self._modules[plugin_name].get("instance")
                if instance and hasattr(instance, "on_disable"):
                    instance.on_disable()

            logger.info("Disabled plugin: %s", plugin_name)
            return True

        except Exception as e:
            logger.error("Failed to disable plugin %s: %s", plugin_name, e)
            return False

    def _check_dependencies(self, record: PluginRecord) -> bool:
        """
        检查插件依赖

        Args:
            record: 插件记录

        Returns:
            bool: 依赖是否满足
        """
        for dep_name in record.dependencies:
            if dep_name not in self._plugins:
                logger.error("Dependency not found: %s", dep_name)
                return False

            dep_record = self._plugins[dep_name]
            if not dep_record.enabled:
                logger.error("Dependency not enabled: %s", dep_name)
                return False

        return True

    def _get_dependents(self, plugin_name: str) -> List[str]:
        """
        获取依赖于指定插件的插件列表

        Args:
            plugin_name: 插件名称

        Returns:
            List[str]: 依赖插件列表
        """
        dependents = []

        for name, record in self._plugins.items():
            if plugin_name in record.dependencies:
                dependents.append(name)

        return dependents

    def resolve_load_order(self) -> List[str]:
        """
        解析插件加载顺序（拓扑排序）

        Returns:
            List[str]: 按依赖关系排序的插件名称列表
        """
        # 构建依赖图
        graph: Dict[str, List[str]] = {}
        for name, record in self._plugins.items():
            graph[name] = record.dependencies.copy()

        # 拓扑排序
        visited = set()
        order = []

        def visit(name: str):
            if name in visited:
                return
            visited.add(name)

            # 先访问依赖
            for dep in graph.get(name, []):
                visit(dep)

            order.append(name)

        for name in graph:
            visit(name)

        return order

    def load_all(self) -> int:
        """
        加载所有已启用的插件

        Returns:
            int: 成功加载的插件数量
        """
        loaded_count = 0

        # 按依赖顺序加载
        load_order = self.resolve_load_order()

        for plugin_name in load_order:
            record = self._plugins.get(plugin_name)
            if record and record.enabled and not record.loaded:
                if self.load_plugin(plugin_name):
                    loaded_count += 1

        logger.info("Loaded %s plugins", loaded_count)
        return loaded_count

    def enable_all(self) -> int:
        """
        启用所有插件

        Returns:
            int: 成功启用的插件数量
        """
        enabled_count = 0

        for plugin_name in list(self._plugins.keys()):
            if not self._plugins[plugin_name].enabled:
                if self.enable_plugin(plugin_name):
                    enabled_count += 1

        logger.info("Enabled %s plugins", enabled_count)
        return enabled_count

    def disable_all(self) -> int:
        """
        禁用所有插件

        Returns:
            int: 成功禁用的插件数量
        """
        disabled_count = 0

        for plugin_name in list(self._plugins.keys()):
            if self._plugins[plugin_name].enabled:
                if self.disable_plugin(plugin_name):
                    disabled_count += 1

        logger.info("Disabled %s plugins", disabled_count)
        return disabled_count

    def unload_all(self) -> int:
        """
        卸载所有插件

        Returns:
            int: 成功卸载的插件数量
        """
        unloaded_count = 0

        for plugin_name in list(self._plugins.keys()):
            if self._plugins[plugin_name].loaded:
                if self.unload_plugin(plugin_name):
                    unloaded_count += 1

        logger.info("Unloaded %s plugins", unloaded_count)
        return unloaded_count

    def uninstall_all(self) -> int:
        """
        卸载所有插件

        Returns:
            int: 成功卸载的插件数量
        """
        uninstalled_count = 0

        for plugin_name in list(self._plugins.keys()):
            if self.uninstall_plugin(plugin_name):
                uninstalled_count += 1

        logger.info("Uninstalled %s plugins", uninstalled_count)
        return uninstalled_count

    def get_plugin(self, plugin_name: str) -> Optional[PluginRecord]:
        """
        获取插件记录

        Args:
            plugin_name: 插件名称

        Returns:
            Optional[PluginRecord]: 插件记录
        """
        return self._plugins.get(plugin_name)

    def get_module(self, plugin_name: str) -> Optional[Any]:
        """
        获取插件模块

        Args:
            plugin_name: 插件名称

        Returns:
            Optional[Any]: 插件模块
        """
        module_info = self._modules.get(plugin_name)
        if module_info:
            return module_info.get("instance")
        return None

    def list_plugins(self) -> List[PluginRecord]:
        """
        列出所有插件

        Returns:
            List[PluginRecord]: 插件记录列表
        """
        return list(self._plugins.values())

    def has_plugin(self, plugin_name: str) -> bool:
        """
        检查插件是否存在

        Args:
            plugin_name: 插件名称

        Returns:
            bool: 是否存在
        """
        return plugin_name in self._plugins

    def get_enabled_plugins(self) -> List[PluginRecord]:
        """
        获取已启用的插件

        Returns:
            List[PluginRecord]: 已启用的插件列表
        """
        return [record for record in self._plugins.values() if record.enabled]

    def get_status(self) -> Dict[str, Any]:
        """
        获取插件状态

        Returns:
            Dict[str, Any]: 状态字典
        """
        status = {}
        for name, record in self._plugins.items():
            status[name] = {
                "enabled": record.enabled,
                "loaded": record.loaded,
                "version": record.version,
                "description": record.description,
            }
        return status

    def _log(self, level: str, message: str):
        """
        记录日志

        Args:
            level: 日志级别
            message: 日志消息
        """
        if level == "info":
            logger.info(message)
        elif level == "warning":
            logger.warning(message)
        elif level == "error":
            logger.error(message)
        elif level == "debug":
            logger.debug(message)


# 全局插件管理器实例
_global_plugin_manager: Optional[PluginManager] = None


def get_plugin_manager(plugin_dir: Optional[str] = None) -> PluginManager:
    """
    获取全局插件管理器

    Args:
        plugin_dir: 插件目录路径

    Returns:
        PluginManager: 全局插件管理器实例
    """
    global _global_plugin_manager
    if _global_plugin_manager is None:
        _global_plugin_manager = PluginManager(plugin_dir)
    return _global_plugin_manager


def reset_plugin_manager():
    """
    重置全局插件管理器 (主要用于测试)
    """
    global _global_plugin_manager
    _global_plugin_manager = None
