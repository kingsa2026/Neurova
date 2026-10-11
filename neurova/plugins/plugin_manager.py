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
import inspect
import json
from neurova.core.logger import get_logger
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Type

import yaml
from neurova.core.data_root import dataPath
from neurova.core.lazy_singleton import lazySingleton

logger = get_logger(__name__)


class PluginError(Exception):
    """插件操作失败——**成因是结构化字段，不被折成一个布尔**。

    原实现每条路径都是 `except Exception: return False`：调用方拿到 False 却无从知道
    是"根外路径""缺 manifest""依赖不满足"还是"构造报 TypeError"，而端点那侧只能把
    这个 False 统一画成"失败"（§6-126 那一族：把不同的故障折成同一个结论）。
    `reason` 是封闭集合，端点按它映射 HTTP 语义（见 `api/endpoints/plugin.py`）。
    布尔门面 `install_plugin` / `load_plugin` 保留给批量入口与既有调用方，
    它们只是本异常的一层薄壳（同一实现，不是第二份口径，教义第 6 条）。
    """

    def __init__(self, reason: str, detail: str = ""):
        self.reason = reason
        self.detail = detail
        super().__init__("[%s] %s" % (reason, detail))


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
            plugin_dir: 插件目录路径；未给则落**数据根下的 `plugins/`**

        落点收成数据根单点是本批的必修项：原实现默认 `Path.home()/.neurova/plugins`，
        那是 `721ef038`（"剩余数据落点全量收口到数据根——CWD 相对与第二份根归零"）
        之后又冒出来的第二条根——取回历史代码时不能把那条已注销的落点一起取回来。
        """
        self._plugin_dir = plugin_dir or dataPath("plugins")
        self._plugins: Dict[str, PluginRecord] = {}
        self._manifests: Dict[str, Dict[str, Any]] = {}
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

    def resolveInstallSource(self, plugin_source: Any) -> Path:
        """把装载源收成**插件根内的真实路径**；不合规一律 `PluginError`。

        次序是刻意的：先拒远程、再 `resolve()`（把 `..` 消化掉）、**然后**才判在不在根内——
        反过来做会让 `plugins/../../somewhere` 这种字符串看起来"在根里"。
        """
        text = str(plugin_source or "").strip()
        if not text:
            raise PluginError("empty_source", "装载源为空")
        if text.startswith(("http://", "https://", "ftp://", "git+")):
            raise PluginError(
                "remote_source", "远程下载安装未实装（P3 带供应链校验后才开，本批不静默成功）")

        root = Path(self._plugin_dir).resolve()
        candidate = Path(text).resolve()
        if not candidate.is_dir():
            raise PluginError("not_a_directory", str(candidate))
        if not candidate.is_relative_to(root):
            raise PluginError(
                "outside_root", "装载源必须在插件根 %s 内，收到的是 %s" % (root, candidate))
        return candidate

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

    def readManifestAt(self, plugin_path: Any) -> Optional[Dict[str, Any]]:
        """读一个目录里的 manifest（公开入口；`_load_manifest` 是实现）。"""
        return self._load_manifest(Path(plugin_path))

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

    def install_plugin(self, plugin_source: Any) -> PluginRecord:
        """把插件根内的一个目录登记为已安装插件，返回它的记录。

        - 源必须落在插件根内（`resolveInstallSource`），远程源直接拒——
          原实现里那条 `elif isinstance(plugin_source, str) and startswith("http")` 是
          **不可达分支**（前一个 `isinstance((str, Path))` 已经把 str 全收了），
          于是"未实现"这条声明从来没生效过，URL 只是碰巧因为路径不存在而失败。
        - 失败一律抛 `PluginError`，不再 `return False` 让调用方猜——
          原实现的宽 `except Exception: return False` 把"缺 manifest""依赖不满足""构造报错"
          全折成同一个 False（§6-126 那一族的另一例）。
        """
        plugin_path = self.resolveInstallSource(plugin_source)

        manifest = self._load_manifest(plugin_path)
        if not manifest:
            raise PluginError("no_manifest", "目录里没有可解析的 manifest：%s" % plugin_path)

        name = manifest.get("name", plugin_path.name)
        record = PluginRecord(
            name=name,
            version=str(manifest.get("version", "1.0.0")),
            description=manifest.get("description", ""),
            author=manifest.get("author", ""),
            path=str(plugin_path),
            entry_point=manifest.get("entry_point", "main.py"),
            dependencies=manifest.get("dependencies", []),
            metadata=manifest.get("metadata", {}),
            install_time=time.time(),
        )

        if not self._check_dependencies(record):
            raise PluginError(
                "unmet_dependencies", "依赖不满足：%s" % record.name)

        self._plugins[name] = record
        self._manifests[name] = manifest
        logger.info("Installed plugin: %s v%s", record.name, record.version)
        return record

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

            # 删除模块缓存（清单缓存同批清，否则残留 manifest 会让"重装"读到旧声明）
            if plugin_name in self._modules:
                del self._modules[plugin_name]
            self._manifests.pop(plugin_name, None)

            logger.info("Uninstalled plugin: %s", plugin_name)
            return True

        except Exception as e:
            logger.error("Failed to uninstall plugin %s: %s", plugin_name, e)
            return False

    def load_plugin(self, plugin_name: str) -> Any:
        """动态装载插件，返回其实例；失败抛 `PluginError`（点名成因）。

        两处必修（都是"取回历史代码时才发现真链根本走不通"的那类）：

        - 原实现 `plugin_class()` **无参构造**，而作者基类
          `BasePlugin.__init__(self, manifest)` 要求清单 ⇒ 任何按基类写的插件都 TypeError，
          被外层宽 except 折成 `False`；
        - 判"类是不是插件类"原先只看 `hasattr(attr, "__init__") and hasattr(attr, "on_enable")`，
          会把模块里 **import 进来的**别人的类也认成插件类。现按"本模块定义的 `BasePlugin` 子类"优先，
          落不到才退到"本模块定义、带生命周期方法的类"。
        """
        if plugin_name not in self._plugins:
            raise PluginError("not_installed", "插件未安装：%s" % plugin_name)

        record = self._plugins[plugin_name]

        if record.loaded:
            return self._modules[plugin_name].get("instance")

        if not record.enabled:
            raise PluginError("not_enabled", "插件未启用，不能装载：%s" % plugin_name)

        module = self._load_plugin_module(record)
        if module is None:
            raise PluginError("entry_not_loaded",
                              "入口文件装载失败：%s" % record.entry_point)

        plugin_class = self._find_module_class(module)
        if plugin_class is None:
            raise PluginError("no_plugin_class",
                              "模块里找不到插件类（不是本模块定义的 BasePlugin 子类或生命周期类）")

        try:
            instance = self._instantiate(plugin_class, plugin_name)
        except PluginError:
            raise
        except Exception as e:
            raise PluginError("instantiate_failed", "%s: %s" % (type(e).__name__, e))

        self._modules[plugin_name] = {"module": module, "instance": instance, "class": plugin_class}
        record.loaded = True
        record.load_time = time.time()
        logger.info("Loaded plugin: %s", plugin_name)
        return instance

    def _instantiate(self, plugin_class: Type, plugin_name: str) -> Any:
        """按构造签名实例化——作者基类要 manifest，普通类可以无参。"""
        try:
            params = list(inspect.signature(plugin_class.__init__).parameters.values())
        except (TypeError, ValueError):
            params = []
        takes_manifest = any(p.kind in (p.POSITIONAL_OR_KEYWORD, p.POSITIONAL_ONLY)
                             and p.default is p.empty
                             for p in params[1:])
        if not takes_manifest:
            return plugin_class()
        return plugin_class(self.manifestFor(plugin_name))

    def manifestFor(self, plugin_name: str):
        """把装进根里的那份 manifest 解析成 `PluginManifest`（唯一入口）。

        `plugin_id` 是 `parse_manifest` 的必填字段，而仓内既有示例只写 `name`——
        这里按 name 兜出一个 id，并把这件事写在唯一构造点里，而不是让每个调用方各猜一套。
        """
        from neurova.plugins.plugin_manifest import parse_manifest

        raw = dict(self._manifests.get(plugin_name) or {})
        raw.setdefault("plugin_id", plugin_name)
        raw.setdefault("name", plugin_name)
        raw.setdefault("version", "0.0.0")
        return parse_manifest(raw)

    def manifestDict(self, plugin_name: str) -> Dict[str, Any]:
        """清单原文的公开读面（端点要 `plugin_type`/声明端点这些字段，不该伸手进私有缓存）。"""
        return dict(self._manifests.get(plugin_name) or {})

    def moduleInfo(self, plugin_name: str) -> Optional[Dict[str, Any]]:
        """已装载插件的模块信息（未装载返回 None）。"""
        return self._modules.get(plugin_name)

    def dependentsOf(self, plugin_name: str) -> List[str]:
        """依赖这个插件的其它插件名（禁用/卸载的拒绝成因要用它，别读私有方法）。"""
        return self._get_dependents(plugin_name)

    def declaredEndpoints(self, plugin_name: str) -> List[Dict[str, Any]]:
        """插件在清单里声明的 API 端点（P1 只登记读数，不挂进活 app——见 `routesMounted`）。"""
        raw = self._manifests.get(plugin_name) or {}
        return list(raw.get("api_endpoints") or [])

    @staticmethod
    def routesMounted() -> tuple:
        """路由挂载状态的单点读数：P1 恒为「未挂载」并给出成因。

        这条读数存在的意义是**不让 modules 面看起来像已生效**——
        装载与"插件可注册 HTTP 路由"是两次授权，后者属 P2 的权限门。
        """
        return False, "P1 只接通动态装载；插件声明的端点未挂进运行中的 app（权限门与审计属 P2）"

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
        """挑出这个模块**自己定义的**插件类。

        原条件 `hasattr(attr, "__init__") and hasattr(attr, "on_enable")` 会连
        "被 import 进来的别人的类"一起认（`BasePlugin` 只按名字排除，换个名字排除不掉），
        于是装载的可能是依赖库里的某个类。现按"定义在本模块里"筛，`BasePlugin` 子类优先。
        """
        moduleName = getattr(module, "__name__", None)
        candidates = []
        for attr_name in dir(module):
            attr = getattr(module, attr_name, None)
            if not isinstance(attr, type):
                continue
            if moduleName is not None and getattr(attr, "__module__", None) != moduleName:
                continue
            candidates.append((attr_name, attr))

        from neurova.plugins.base_plugin import BasePlugin

        for _name, attr in candidates:
            if issubclass(attr, BasePlugin) and not inspect.isabstract(attr):
                return attr
        for _name, attr in candidates:
            if hasattr(attr, "on_enable") and hasattr(attr, "on_initialize"):
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

                # 清理模块，并把动态注册进 `sys.modules` 的那条一起摘掉：
                # 原实现只删自己的缓存，进程里仍留着 `neurova_plugin_<name>`，
                # 于是"卸载"之后旧实例与旧代码都还在（再 load 会拿到脏的那份）。
                sys.modules.pop("neurova_plugin_%s" % plugin_name, None)
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
                try:
                    self.load_plugin(plugin_name)
                except PluginError as e:
                    # 批量入口不因单个插件中断，但**必须点名是谁、为什么**——
                    # 静默 `continue` 会把"N 个装了"读成"N-1 个坏了也无痕"。
                    logger.warning("批量装载跳过 %s：%s", plugin_name, e)
                    continue
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


@lazySingleton("_global_plugin_manager")
def get_plugin_manager(plugin_dir: Optional[str] = None) -> PluginManager:
    """
    获取全局插件管理器

    Args:
        plugin_dir: 插件目录路径

    Returns:
        PluginManager: 全局插件管理器实例
    """
    return PluginManager(plugin_dir)


def reset_plugin_manager():
    """
    重置全局插件管理器 (主要用于测试)
    """
    global _global_plugin_manager
    _global_plugin_manager = None
