
"""
测试服务管理器模块
"""
import pytest
import asyncio
from unittest.mock import Mock, MagicMock, patch, AsyncMock

from neurova.core.service_manager import (
    ServiceManager,
    ServiceDescriptor,
)


class MockService:
    """模拟服务类"""

    def __init__(self, config=None):
        self.config = config
        self.started = False
        self.stopped = False

    async def start(self):
        self.started = True

    async def stop(self):
        self.stopped = True


class MockServiceWithInit:
    """带 init 的模拟服务类"""

    def __init__(self, config=None):
        self.config = config

    def post_init(self):
        pass

    async def start(self):
        pass

    async def stop(self):
        pass


class TestServiceDescriptor:
    """测试服务描述符"""

    def test_create_descriptor(self):
        """测试创建描述符"""
        desc = ServiceDescriptor(
            name="test-service",
            service_class=MockService,
            dependencies=["dep1"],
            priority=50
        )
        assert desc.name == "test-service"
        assert desc.service_class == MockService
        assert desc.dependencies == ["dep1"]
        assert desc.priority == 50

    def test_descriptor_defaults(self):
        """测试默认值"""
        desc = ServiceDescriptor(
            name="test-service",
            service_class=MockService,
        )
        assert desc.priority == 0
        assert desc.reusable is False
        assert desc.lazy is True
        assert desc.dependencies == []

    def test_to_dict(self):
        """测试转换为字典"""
        desc = ServiceDescriptor(
            name="test-service",
            service_class=MockService,
        )
        data = desc.to_dict()
        assert data["name"] == "test-service"
        assert data["service_class"] == "MockService"


class TestServiceManager:
    """测试服务管理器"""

    @pytest.fixture
    def service_manager(self):
        """创建服务管理器实例"""
        return ServiceManager()

    def test_create_manager(self, service_manager):
        """测试创建服务管理器"""
        assert service_manager is not None

    def test_register_service(self, service_manager):
        """测试注册服务"""
        desc = ServiceDescriptor(
            name="test-service",
            service_class=MockService
        )
        service_manager.register(desc)
        assert "test-service" in service_manager._services

    def test_register_overwrites(self, service_manager):
        """测试重复注册服务（覆盖）"""
        desc1 = ServiceDescriptor(
            name="test-service",
            service_class=MockService
        )
        desc2 = ServiceDescriptor(
            name="test-service",
            service_class=MockServiceWithInit
        )
        service_manager.register(desc1)
        service_manager.register(desc2)
        assert service_manager._services["test-service"].service_class == MockServiceWithInit

    def test_get_service(self, service_manager):
        """测试获取服务"""
        desc = ServiceDescriptor(
            name="test-service",
            service_class=MockService
        )
        service_manager.register(desc)
        service_manager._instances["test-service"] = MockService()
        service = service_manager.get_service("test-service")
        assert service is not None

    def test_get_service_nonexistent(self, service_manager):
        """测试获取不存在的服务"""
        service = service_manager.get_service("nonexistent")
        assert service is None

    def test_is_running(self, service_manager):
        """测试检查服务是否运行"""
        desc = ServiceDescriptor(
            name="test-service",
            service_class=MockService
        )
        service_manager.register(desc)
        assert service_manager.is_running("test-service") is False

    def test_get_status(self, service_manager):
        """测试获取状态"""
        desc = ServiceDescriptor(
            name="test-service",
            service_class=MockService
        )
        service_manager.register(desc)
        status = service_manager.get_status()
        assert "total_services" in status
        assert "running_services" in status
        assert status["total_services"] == 1

    def test_set_reusable(self, service_manager):
        """测试设置可重用性"""
        desc = ServiceDescriptor(
            name="test-service",
            service_class=MockService
        )
        service_manager.register(desc)
        service_manager.set_reusable("test-service", True)
        assert service_manager._services["test-service"].reusable is True

    def test_get_reusable_services(self, service_manager):
        """测试获取可重用服务列表"""
        desc1 = ServiceDescriptor(
            name="service1",
            service_class=MockService,
            reusable=True,
        )
        desc2 = ServiceDescriptor(
            name="service2",
            service_class=MockService,
            reusable=False,
        )
        service_manager.register(desc1)
        service_manager.register(desc2)
        reusable = service_manager.get_reusable_services()
        assert "service1" in reusable
        assert "service2" not in reusable

    @pytest.mark.asyncio
    async def test_start_all(self, service_manager):
        """测试启动所有服务"""
        desc1 = ServiceDescriptor(
            name="service1",
            service_class=MockService,
            priority=1
        )
        desc2 = ServiceDescriptor(
            name="service2",
            service_class=MockService,
            priority=2
        )
        service_manager.register(desc1)
        service_manager.register(desc2)
        await service_manager.start_all()
        assert service_manager.is_running("service1") is True
        assert service_manager.is_running("service2") is True

    @pytest.mark.asyncio
    async def test_stop_all(self, service_manager):
        """测试停止所有服务"""
        desc1 = ServiceDescriptor(
            name="service1",
            service_class=MockService,
            priority=1,
        )
        desc2 = ServiceDescriptor(
            name="service2",
            service_class=MockService,
            priority=2,
        )
        service_manager.register(desc1)
        service_manager.register(desc2)
        await service_manager.start_all()
        await service_manager.stop_all()
        assert service_manager.is_running("service1") is False
        assert service_manager.is_running("service2") is False

    @pytest.mark.asyncio
    async def test_start_all_with_dependencies(self, service_manager):
        """测试按依赖顺序启动"""
        desc1 = ServiceDescriptor(
            name="core",
            service_class=MockService,
            priority=2,
        )
        desc2 = ServiceDescriptor(
            name="app",
            service_class=MockService,
            priority=1,
            dependencies=["core"],
        )
        service_manager.register(desc1)
        service_manager.register(desc2)
        await service_manager.start_all()
        assert service_manager.is_running("core") is True
        assert service_manager.is_running("app") is True

    def test_start_service_with_post_init(self, service_manager):
        """测试带 post_init 的服务"""
        desc = ServiceDescriptor(
            name="service-with-init",
            service_class=MockServiceWithInit,
        )
        service_manager.register(desc)
        assert "service-with-init" in service_manager._services
