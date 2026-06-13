from __future__ import annotations

"""
ServiceManager - Unified service management for Neurova
"""

import asyncio
import threading
import typing
from dataclasses import dataclass, field

from neurova.core.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ServiceDescriptor:
    """服务描述符"""

    name: str
    service_class: type
    priority: int = 0  # 优先级，数字越小优先级越高
    reusable: bool = False  # 是否可重用
    dependencies: typing.List[str] = field(default_factory=list)
    config: typing.Dict[str, typing.Any] = field(default_factory=dict)
    lazy: bool = True  # 是否延迟初始化

    def to_dict(self) -> typing.Dict[str, typing.Any]:
        """转换为字典"""
        return {
            "name": self.name,
            "service_class": self.service_class.__name__,
            "priority": self.priority,
            "reusable": self.reusable,
            "dependencies": self.dependencies,
            "config": self.config,
            "lazy": self.lazy,
        }


class ServiceManager:
    """
    服务管理器

    管理服务的注册、启动、停止和依赖解析。
    """

    def __init__(self, config: typing.Dict[str, typing.Any] = None):
        """
        初始化服务管理器

        Args:
            config: 配置字典
        """
        self._config = config or {}
        self._lock = threading.RLock()

        # 服务注册表
        self._services: typing.Dict[str, ServiceDescriptor] = {}

        # 服务实例缓存
        self._instances: typing.Dict[str, typing.Any] = {}

        # 服务状态
        self._running: typing.Dict[str, bool] = {}

        # 初始化顺序
        self._init_order: typing.List[str] = []

        logger.info("ServiceManager 初始化完成")

    def register(self, descriptor: ServiceDescriptor) -> None:
        """
        注册服务

        Args:
            descriptor: 服务描述符
        """
        with self._lock:
            if descriptor.name in self._services:
                logger.warning("服务已存在，将覆盖: %s", descriptor.name)

            self._services[descriptor.name] = descriptor
            self._running[descriptor.name] = False

            logger.debug("注册服务: %s", descriptor.name)

    def set_reusable(self, service_name: str, reusable: bool = True) -> None:
        """
        设置服务可重用性

        Args:
            service_name: 服务名称
            reusable: 是否可重用
        """
        with self._lock:
            if service_name in self._services:
                self._services[service_name].reusable = reusable
                logger.debug("服务 %s 可重用性设置为: %s", service_name, reusable)

    def get_reusable_services(self) -> typing.List[str]:
        """
        获取可重用服务列表

        Returns:
            可重用服务名称列表
        """
        with self._lock:
            return [name for name, desc in self._services.items() if desc.reusable]

    def _group_by_priority(self) -> typing.Dict[int, typing.List[str]]:
        """
        按优先级分组

        Returns:
            按优先级分组的服务字典
        """
        groups: typing.Dict[int, typing.List[str]] = {}

        for name, descriptor in self._services.items():
            priority = descriptor.priority
            if priority not in groups:
                groups[priority] = []
            groups[priority].append(name)

        return groups

    async def start_all(self) -> None:
        """启动所有服务"""
        with self._lock:
            # 计算初始化顺序
            self._calculate_init_order()

            # 按顺序启动服务
            for service_name in self._init_order:
                await self._start_service(service_name)

            logger.info("所有服务已启动，共 %s 个", len(self._init_order))

    async def _start_service(self, service_name: str) -> None:
        """
        启动单个服务

        Args:
            service_name: 服务名称
        """
        if service_name not in self._services:
            logger.error("服务不存在: %s", service_name)
            return

        if self._running.get(service_name, False):
            logger.debug("服务已在运行: %s", service_name)
            return

        self._services[service_name]

        try:
            # 获取或创建服务实例
            instance = self._get_or_create_service(service_name)

            # 运行 post_init
            await self._run_post_init(instance)

            # 运行 start 方法
            await self._run_start_method(instance)

            # 标记为运行中
            self._running[service_name] = True

            logger.info("服务已启动: %s", service_name)

        except Exception as e:
            logger.error("启动服务失败 %s: %s", service_name, e)
            raise

    def _get_or_create_service(self, service_name: str) -> typing.Any:
        """
        获取或创建服务实例

        Args:
            service_name: 服务名称

        Returns:
            服务实例
        """
        if service_name in self._instances:
            return self._instances[service_name]

        descriptor = self._services[service_name]

        # 创建实例
        try:
            instance = descriptor.service_class(descriptor.config)
            self._instances[service_name] = instance

            logger.debug("创建服务实例: %s", service_name)
            return instance

        except Exception as e:
            logger.error("创建服务实例失败 %s: %s", service_name, e)
            raise

    async def _run_post_init(self, instance: typing.Any) -> None:
        """
        运行 post_init 方法

        Args:
            instance: 服务实例
        """
        if hasattr(instance, "post_init"):
            try:
                if asyncio.iscoroutinefunction(instance.post_init):
                    await instance.post_init()
                else:
                    instance.post_init()
            except Exception as e:
                logger.error("运行 post_init 失败: %s", e)

    async def _run_start_method(self, instance: typing.Any) -> None:
        """
        运行 start 方法

        Args:
            instance: 服务实例
        """
        if hasattr(instance, "start"):
            try:
                if asyncio.iscoroutinefunction(instance.start):
                    await instance.start()
                else:
                    instance.start()
            except Exception as e:
                logger.error("运行 start 方法失败: %s", e)

    def _calculate_init_order(self) -> None:
        """计算初始化顺序（拓扑排序）"""
        # 构建依赖图
        graph: typing.Dict[str, typing.List[str]] = {}
        for name, descriptor in self._services.items():
            graph[name] = descriptor.dependencies.copy()

        # 拓扑排序
        visited = set()
        temp_visited = set()
        order = []

        def dfs(node: str) -> None:
            if node in temp_visited:
                raise ValueError(f"检测到循环依赖: {node}")
            if node in visited:
                return

            temp_visited.add(node)

            for dependency in graph.get(node, []):
                if dependency in graph:
                    dfs(dependency)

            temp_visited.remove(node)
            visited.add(node)
            order.append(node)

        for node in graph:
            if node not in visited:
                dfs(node)

        self._init_order = order

    async def stop_all(self) -> None:
        """停止所有服务"""
        with self._lock:
            # 反向顺序停止
            for service_name in reversed(self._init_order):
                await self._stop_service(service_name)

            logger.info("所有服务已停止")

    async def _stop_service(self, service_name: str) -> None:
        """
        停止单个服务

        Args:
            service_name: 服务名称
        """
        if not self._running.get(service_name, False):
            return

        if service_name not in self._instances:
            return

        instance = self._instances[service_name]

        try:
            # 运行 stop 方法
            if hasattr(instance, "stop"):
                if asyncio.iscoroutinefunction(instance.stop):
                    await instance.stop()
                else:
                    instance.stop()

            # 标记为已停止
            self._running[service_name] = False

            # 如果不是可重用服务，删除实例
            if not self._services[service_name].reusable:
                del self._instances[service_name]

            logger.info("服务已停止: %s", service_name)

        except Exception as e:
            logger.error("停止服务失败 %s: %s", service_name, e)

    def get_service(self, service_name: str) -> typing.Optional[typing.Any]:
        """
        获取服务实例

        Args:
            service_name: 服务名称

        Returns:
            服务实例，不存在返回 None
        """
        with self._lock:
            return self._instances.get(service_name)

    def is_running(self, service_name: str) -> bool:
        """
        检查服务是否运行中

        Args:
            service_name: 服务名称

        Returns:
            是否运行中
        """
        with self._lock:
            return self._running.get(service_name, False)

    def get_status(self) -> typing.Dict[str, typing.Any]:
        """
        获取服务管理器状态

        Returns:
            状态字典
        """
        with self._lock:
            return {
                "total_services": len(self._services),
                "running_services": sum(1 for r in self._running.values() if r),
                "services": {
                    name: {
                        "descriptor": desc.to_dict(),
                        "running": self._running.get(name, False),
                        "has_instance": name in self._instances,
                    }
                    for name, desc in self._services.items()
                },
                "init_order": self._init_order,
            }
