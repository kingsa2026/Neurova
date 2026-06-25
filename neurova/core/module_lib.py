from __future__ import annotations

"""
核心模块库 - 模块的动态加载、卸载、版本管理、依赖解析和生命周期管理

功能:
- 模块注册/注销
- 依赖关系解析
- 生命周期管理 (init/start/stop/destroy)
- 模块间通信接口
- 模块版本管理
"""

import importlib
import importlib.util
from neurova.core.logger import get_logger
import threading
import typing
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Type

# core imports
from neurova.core.logger import LogLevel
from neurova.core.module_system import Module

logger = get_logger(__name__)


# ────── 数据模型 ──────


class ModuleType(Enum):
    """模块类型"""

    CORE = "core"  # 核心模块
    PLUGIN = "plugin"  # 插件模块
    EXTENSION = "extension"  # 扩展模块
    BUILTIN = "builtin"  # 内置模块
    CUSTOM = "custom"  # 自定义模块


@dataclass
class ModuleDescriptor:
    """模块描述符"""

    module_id: str = ""
    name: str = ""
    version: str = "1.0.0"
    module_type: ModuleType = ModuleType.CUSTOM
    description: str = ""
    author: str = ""
    dependencies: typing.List[str] = field(default_factory=list)
    entry_point: str = ""
    class_name: str = ""
    config: typing.Dict[str, typing.Any] = field(default_factory=dict)
    enabled: bool = True
    auto_start: bool = True
    priority: int = 0
    metadata: typing.Dict[str, typing.Any] = field(default_factory=dict)

    def to_dict(self) -> typing.Dict[str, typing.Any]:
        """转换为字典"""
        return {
            "module_id": self.module_id,
            "name": self.name,
            "version": self.version,
            "module_type": self.module_type.value,
            "description": self.description,
            "author": self.author,
            "dependencies": self.dependencies,
            "entry_point": self.entry_point,
            "class_name": self.class_name,
            "config": self.config,
            "enabled": self.enabled,
            "auto_start": self.auto_start,
            "priority": self.priority,
            "metadata": self.metadata,
        }


# ────── 主类 ──────


class ModuleLib:
    """
    核心模块库

    管理模块的加载、卸载、生命周期和依赖关系。
    """

    def __init__(self, config: typing.Optional[typing.Dict[str, typing.Any]] = None):
        """
        初始化模块库

        参数:
            config: 配置字典
        """
        self._config = config or {}
        self._lock = threading.RLock()

        # 模块存储
        self._modules: typing.Dict[str, Module] = {}
        self._descriptors: typing.Dict[str, ModuleDescriptor] = {}

        # 加载路径
        self._load_paths: typing.List[Path] = []
        self._builtin_path: typing.Optional[Path] = None

        # 依赖图
        self._dependency_graph: typing.Dict[str, typing.List[str]] = {}

        # 状态
        self._initialized = False
        self._started = False

        logger.info("ModuleLib initialized")

    def add_load_path(self, path: typing.Union[str, Path]) -> bool:
        """
        添加模块加载路径

        参数:
            path: 路径

        返回:
            bool: 是否添加成功
        """
        with self._lock:
            path_obj = Path(path) if isinstance(path, str) else path

            if not path_obj.exists():
                logger.warning("Load path does not exist: %s", path_obj)
                return False

            if path_obj not in self._load_paths:
                self._load_paths.append(path_obj)
                logger.info("Added load path: %s", path_obj)

            return True

    def remove_load_path(self, path: typing.Union[str, Path]) -> bool:
        """
        移除模块加载路径

        参数:
            path: 路径

        返回:
            bool: 是否移除成功
        """
        with self._lock:
            path_obj = Path(path) if isinstance(path, str) else path

            if path_obj in self._load_paths:
                self._load_paths.remove(path_obj)
                logger.info("Removed load path: %s", path_obj)
                return True

            return False

    def register(self, descriptor: ModuleDescriptor, module_class: typing.Optional[Type[Module]] = None) -> bool:
        """
        注册模块

        参数:
            descriptor: 模块描述符
            module_class: 模块类（可选）

        返回:
            bool: 是否注册成功
        """
        with self._lock:
            module_id = descriptor.module_id

            if module_id in self._descriptors:
                logger.warning("Module already registered: %s", module_id)
                return False

            self._descriptors[module_id] = descriptor

            # 更新依赖图
            self._dependency_graph[module_id] = descriptor.dependencies.copy()

            logger.info("Registered module: %s", module_id)
            return True

    def unregister_async(self, module_id: str) -> typing.Coroutine:
        """
        异步注销模块

        参数:
            module_id: 模块 ID

        返回:
            Coroutine: 异步协程
        """

        async def _unregister():
            return self.unregister(module_id)

        return _unregister()

    def unregister(self, module_id: str) -> bool:
        """
        注销模块

        参数:
            module_id: 模块 ID

        返回:
            bool: 是否注销成功
        """
        with self._lock:
            if module_id not in self._descriptors:
                return False

            # 检查依赖
            dependents = self._get_dependents(module_id)
            if dependents:
                logger.warning("Cannot unregister %s: depended by %s", module_id, dependents)
                return False

            # 停止并销毁模块
            if module_id in self._modules:
                self.stop_module(module_id)
                self.destroy_module(module_id)
                del self._modules[module_id]

            del self._descriptors[module_id]
            if module_id in self._dependency_graph:
                del self._dependency_graph[module_id]

            logger.info("Unregistered module: %s", module_id)
            return True

    def load_module(self, module_id: str) -> typing.Optional[Module]:
        """
        加载模块

        参数:
            module_id: 模块 ID

        返回:
            Optional[Module]: 模块实例
        """
        with self._lock:
            if module_id in self._modules:
                return self._modules[module_id]

            descriptor = self._descriptors.get(module_id)
            if not descriptor:
                logger.error("Module descriptor not found: %s", module_id)
                return None

            # 查找模块类
            module_class = self._find_module_class(descriptor)
            if not module_class:
                logger.error("Module class not found: %s", descriptor.class_name)
                return None

            # 创建模块实例
            try:
                module = module_class(descriptor.config)
                self._modules[module_id] = module
                logger.info("Loaded module: %s", module_id)
                return module
            except Exception as e:
                logger.error("Failed to load module %s: %s", module_id, e)
                return None

    def load_builtin(self, module_id: str) -> typing.Optional[Module]:
        """
        加载内置模块

        参数:
            module_id: 模块 ID

        返回:
            Optional[Module]: 模块实例
        """
        descriptor = self._descriptors.get(module_id)
        if not descriptor or descriptor.module_type != ModuleType.BUILTIN:
            logger.error("Not a builtin module: %s", module_id)
            return None

        return self.load_module(module_id)

    def _find_module_class(self, descriptor: ModuleDescriptor) -> typing.Optional[Type[Module]]:
        """
        查找模块类

        参数:
            descriptor: 模块描述符

        返回:
            Optional[Type[Module]]: 模块类
        """
        # 尝试从入口点加载
        if descriptor.entry_point:
            try:
                spec = importlib.util.spec_from_file_location(descriptor.name, descriptor.entry_point)
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    return getattr(module, descriptor.class_name, None)
            except Exception as e:
                logger.error("Failed to load from entry point: %s", e)

        # 尝试从加载路径查找
        for load_path in self._load_paths:
            module_file = load_path / f"{descriptor.name}.py"
            if module_file.exists():
                try:
                    spec = importlib.util.spec_from_file_location(descriptor.name, str(module_file))
                    if spec and spec.loader:
                        module = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(module)
                        return getattr(module, descriptor.class_name, None)
                except Exception as e:
                    logger.error("Failed to load from path: %s", e)

        return None

    def _check_dependencies(self, module_id: str) -> bool:
        """
        检查依赖

        参数:
            module_id: 模块 ID

        返回:
            bool: 依赖是否满足
        """
        descriptor = self._descriptors.get(module_id)
        if not descriptor:
            return False

        for dep_id in descriptor.dependencies:
            if dep_id not in self._modules:
                logger.error("Missing dependency: %s", dep_id)
                return False

        return True

    def initialize_module(self, module_id: str) -> bool:
        """
        初始化模块

        参数:
            module_id: 模块 ID

        返回:
            bool: 是否初始化成功
        """
        module = self._modules.get(module_id)
        if not module:
            module = self.load_module(module_id)
            if not module:
                return False

        if not self._check_dependencies(module_id):
            return False

        try:
            if hasattr(module, "initialize"):
                module.initialize()
            logger.info("Initialized module: %s", module_id)
            return True
        except Exception as e:
            logger.error("Failed to initialize module %s: %s", module_id, e)
            return False

    def start_module(self, module_id: str) -> bool:
        """
        启动模块

        参数:
            module_id: 模块 ID

        返回:
            bool: 是否启动成功
        """
        module = self._modules.get(module_id)
        if not module:
            return False

        try:
            if hasattr(module, "start"):
                module.start()
            logger.info("Started module: %s", module_id)
            return True
        except Exception as e:
            logger.error("Failed to start module %s: %s", module_id, e)
            return False

    def stop_module(self, module_id: str) -> bool:
        """
        停止模块

        参数:
            module_id: 模块 ID

        返回:
            bool: 是否停止成功
        """
        module = self._modules.get(module_id)
        if not module:
            return False

        try:
            if hasattr(module, "stop"):
                module.stop()
            logger.info("Stopped module: %s", module_id)
            return True
        except Exception as e:
            logger.error("Failed to stop module %s: %s", module_id, e)
            return False

    def destroy_module(self, module_id: str) -> bool:
        """
        销毁模块

        参数:
            module_id: 模块 ID

        返回:
            bool: 是否销毁成功
        """
        module = self._modules.get(module_id)
        if not module:
            return False

        try:
            if hasattr(module, "destroy"):
                module.destroy()
            logger.info("Destroyed module: %s", module_id)
            return True
        except Exception as e:
            logger.error("Failed to destroy module %s: %s", module_id, e)
            return False

    def initialize_all(self) -> typing.Dict[str, bool]:
        """
        初始化所有模块

        返回:
            Dict[str, bool]: 初始化结果
        """
        results = {}
        for module_id in self._dependency_graph:
            results[module_id] = self.initialize_module(module_id)
        return results

    def start_all(self) -> typing.Dict[str, bool]:
        """
        启动所有模块

        返回:
            Dict[str, bool]: 启动结果
        """
        results = {}
        for module_id in self._dependency_graph:
            results[module_id] = self.start_module(module_id)
        return results

    def stop_all(self) -> typing.Dict[str, bool]:
        """
        停止所有模块

        返回:
            Dict[str, bool]: 停止结果
        """
        results = {}
        for module_id in reversed(list(self._dependency_graph.keys())):
            results[module_id] = self.stop_module(module_id)
        return results

    def destroy_all(self) -> typing.Dict[str, bool]:
        """
        销毁所有模块

        返回:
            Dict[str, bool]: 销毁结果
        """
        results = {}
        for module_id in reversed(list(self._dependency_graph.keys())):
            results[module_id] = self.destroy_module(module_id)
        return results

    def resolve_dependencies(self) -> typing.List[str]:
        """
        解析依赖顺序

        返回:
            List[str]: 模块 ID 列表（拓扑排序）
        """
        # 拓扑排序
        visited = set()
        result = []

        def dfs(node: str):
            if node in visited:
                return
            visited.add(node)
            for dep in self._dependency_graph.get(node, []):
                dfs(dep)
            result.append(node)

        for node in self._dependency_graph:
            dfs(node)

        return result

    def check_circular_dependencies(self) -> typing.List[typing.List[str]]:
        """
        检查循环依赖

        返回:
            List[List[str]]: 循环依赖列表
        """
        cycles = []
        visited = set()
        path = []

        def dfs(node: str):
            if node in path:
                cycle_start = path.index(node)
                cycles.append(path[cycle_start:] + [node])
                return

            if node in visited:
                return

            path.append(node)
            for dep in self._dependency_graph.get(node, []):
                dfs(dep)
            path.pop()
            visited.add(node)

        for node in self._dependency_graph:
            dfs(node)

        return cycles

    def get_module(self, module_id: str) -> typing.Optional[Module]:
        """
        获取模块实例

        参数:
            module_id: 模块 ID

        返回:
            Optional[Module]: 模块实例
        """
        return self._modules.get(module_id)

    def get_descriptor(self, module_id: str) -> typing.Optional[ModuleDescriptor]:
        """
        获取模块描述符

        参数:
            module_id: 模块 ID

        返回:
            Optional[ModuleDescriptor]: 模块描述符
        """
        return self._descriptors.get(module_id)

    def list_modules(self) -> typing.List[ModuleDescriptor]:
        """
        列出所有模块

        返回:
            List[ModuleDescriptor]: 模块描述符列表
        """
        return list(self._descriptors.values())

    def has_module(self, module_id: str) -> bool:
        """
        检查模块是否存在

        参数:
            module_id: 模块 ID

        返回:
            bool: 是否存在
        """
        return module_id in self._descriptors

    def get_running_modules(self) -> typing.List[str]:
        """
        获取运行中的模块

        返回:
            List[str]: 模块 ID 列表
        """
        running = []
        for module_id, module in self._modules.items():
            if hasattr(module, "is_running") and module.is_running:
                running.append(module_id)
        return running

    def get_module_api(self, module_id: str) -> typing.Optional[typing.Dict[str, typing.Any]]:
        """
        获取模块 API

        参数:
            module_id: 模块 ID

        返回:
            Optional[Dict]: 模块 API
        """
        module = self._modules.get(module_id)
        if not module:
            return None

        if hasattr(module, "get_api"):
            return module.get_api()

        return None

    def _log(self, level: LogLevel, message: str, module_id: str = ""):
        """日志记录"""
        if module_id:
            logger.log(level.value, f"[{module_id}] {message}")
        else:
            logger.log(level.value, message)

    @property
    def module_count(self) -> int:
        """模块数量"""
        return len(self._descriptors)

    @property
    def running_count(self) -> int:
        """运行中模块数量"""
        return len(self.get_running_modules())

    def get_status(self) -> typing.Dict[str, typing.Any]:
        """
        获取状态

        返回:
            Dict: 状态信息
        """
        return {
            "total_modules": self.module_count,
            "running_modules": self.running_count,
            "load_paths": [str(p) for p in self._load_paths],
            "modules": {
                module_id: {
                    "descriptor": desc.to_dict(),
                    "loaded": module_id in self._modules,
                    "running": module_id in self.get_running_modules(),
                }
                for module_id, desc in self._descriptors.items()
            },
        }


# ────── 单例管理 ──────

_lib_instance: typing.Optional[ModuleLib] = None
_instance_lock = threading.Lock()


def get_module_lib(**kwargs) -> ModuleLib:
    """获取全局模块库"""
    global _lib_instance
    if _lib_instance is None:
        with _instance_lock:
            if _lib_instance is None:
                _lib_instance = ModuleLib(**kwargs)
    return _lib_instance


def reset_module_lib():
    """重置全局模块库 (主要用于测试)"""
    global _lib_instance
    with _instance_lock:
        if _lib_instance:
            _lib_instance.destroy_all()
        _lib_instance = None
