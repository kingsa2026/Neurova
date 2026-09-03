"""
测试模块库
"""
import pytest
from unittest.mock import patch, MagicMock, mock_open
from neurova.core.module_lib import (
    ModuleType,
    ModuleDescriptor,
    ModuleLib,
    get_module_lib,
    reset_module_lib,
)
from neurova.core.base_module import BaseModule, ModuleState


class TestModuleType:
    """测试ModuleType枚举"""
    
    def test_module_type_members(self):
        """测试模块类型枚举成员"""
        assert ModuleType.BUILTIN.value == "builtin"
        assert ModuleType.DYNAMIC.value == "dynamic"
        assert ModuleType.PLUGIN.value == "plugin"


class TestModuleDescriptor:
    """测试ModuleDescriptor类"""
    
    def test_create_module_descriptor(self):
        """测试创建模块描述符"""
        desc = ModuleDescriptor(
            module_id="test_module",
            module_type=ModuleType.BUILTIN,
            config={"key": "value"},
        )
        
        assert desc.module_id == "test_module"
        assert desc.module_type == ModuleType.BUILTIN
        assert desc.config == {"key": "value"}
        assert desc.instance is None
    
    def test_module_descriptor_to_dict(self):
        """测试模块描述符转换为字典"""
        desc = ModuleDescriptor(
            module_id="test_module",
            module_type=ModuleType.DYNAMIC,
        )
        
        data = desc.to_dict()
        
        assert data["module_id"] == "test_module"
        assert data["type"] == "dynamic"
        assert data["state"] == "unknown"


class TestModuleLib:
    """测试ModuleLib类"""
    
    class MockModule(BaseModule):
        """模拟模块"""
        
        async def on_initialize(self):
            pass
        
        async def on_start(self):
            pass
        
        async def on_stop(self):
            pass
    
    def test_init(self):
        """测试初始化"""
        lib = ModuleLib()
        
        assert lib._modules == {}
        assert lib._load_paths == []
    
    def test_add_load_path(self):
        """测试添加加载路径"""
        lib = ModuleLib()
        
        lib.add_load_path("/path/to/modules")
        
        assert "/path/to/modules" in [str(p) for p in lib._load_paths]
    
    def test_remove_load_path(self):
        """测试移除加载路径"""
        lib = ModuleLib()
        
        lib.add_load_path("/path/to/modules")
        result = lib.remove_load_path("/path/to/modules")
        
        assert result is True
        assert "/path/to/modules" not in [str(p) for p in lib._load_paths]
    
    def test_remove_nonexistent_load_path(self):
        """测试移除不存在的加载路径"""
        lib = ModuleLib()
        
        result = lib.remove_load_path("/nonexistent/path")
        
        assert result is False
    
    def test_register_module(self):
        """测试注册模块"""
        lib = ModuleLib()
        
        module = self.MockModule(
            module_id="test_module",
            name="Test Module",
        )
        
        success = lib.register(module)
        
        assert success is True
        assert "test_module" in lib._modules
    
    def test_register_duplicate_module(self):
        """测试注册重复模块"""
        lib = ModuleLib()
        
        module = self.MockModule(
            module_id="test_module",
            name="Test Module",
        )
        
        lib.register(module)
        success = lib.register(module)
        
        assert success is False
    
    @pytest.mark.asyncio
    async def test_unregister_module_async(self):
        """测试异步注销模块"""
        lib = ModuleLib()
        
        module = self.MockModule(
            module_id="test_module",
            name="Test Module",
        )
        
        lib.register(module)
        success = await lib.unregister_async("test_module")
        
        assert success is True
        assert "test_module" not in lib._modules
    
    def test_unregister_module_nonexistent(self):
        """测试注销不存在的模块"""
        lib = ModuleLib()
        
        success = lib.unregister("nonexistent")
        
        assert success is False
    
    def test_get_module(self):
        """测试获取模块"""
        lib = ModuleLib()
        
        module = self.MockModule(
            module_id="test_module",
            name="Test Module",
        )
        
        lib.register(module)
        retrieved = lib.get_module("test_module")
        
        assert retrieved is module
    
    def test_get_nonexistent_module(self):
        """测试获取不存在的模块"""
        lib = ModuleLib()
        
        retrieved = lib.get_module("nonexistent")
        
        assert retrieved is None
    
    def test_get_descriptor(self):
        """测试获取模块描述符"""
        lib = ModuleLib()
        
        module = self.MockModule(
            module_id="test_module",
            name="Test Module",
        )
        
        lib.register(module)
        desc = lib.get_descriptor("test_module")
        
        assert desc is not None
        assert desc.module_id == "test_module"
    
    def test_list_modules(self):
        """测试列出模块"""
        lib = ModuleLib()
        
        module1 = self.MockModule(
            module_id="module1",
            name="Module 1",
        )
        module2 = self.MockModule(
            module_id="module2",
            name="Module 2",
        )
        
        lib.register(module1, ModuleType.BUILTIN)
        lib.register(module2, ModuleType.DYNAMIC)
        
        modules = lib.list_modules()
        
        assert len(modules) == 2
    
    def test_list_modules_filter_by_type(self):
        """测试按类型过滤模块"""
        lib = ModuleLib()
        
        module1 = self.MockModule(
            module_id="module1",
            name="Module 1",
        )
        module2 = self.MockModule(
            module_id="module2",
            name="Module 2",
        )
        
        lib.register(module1, ModuleType.BUILTIN)
        lib.register(module2, ModuleType.DYNAMIC)
        
        builtin_modules = lib.list_modules(ModuleType.BUILTIN)
        dynamic_modules = lib.list_modules(ModuleType.DYNAMIC)
        
        assert len(builtin_modules) == 1
        assert len(dynamic_modules) == 1
    
    def test_has_module(self):
        """测试检查模块是否存在"""
        lib = ModuleLib()
        
        module = self.MockModule(
            module_id="test_module",
            name="Test Module",
        )
        
        lib.register(module)
        
        assert lib.has_module("test_module") is True
        assert lib.has_module("nonexistent") is False
    
    def test_get_running_modules(self):
        """测试获取运行中的模块"""
        lib = ModuleLib()
        
        module = self.MockModule(
            module_id="test_module",
            name="Test Module",
        )
        
        lib.register(module)
        
        running = lib.get_running_modules()
        
        # 模块初始状态不是running
        assert len(running) == 0
    
    def test_module_count(self):
        """测试模块计数"""
        lib = ModuleLib()
        
        module1 = self.MockModule(
            module_id="module1",
            name="Module 1",
        )
        module2 = self.MockModule(
            module_id="module2",
            name="Module 2",
        )
        
        lib.register(module1)
        lib.register(module2)
        
        assert lib.module_count == 2
    
    def test_running_count(self):
        """测试运行中模块计数"""
        lib = ModuleLib()
        
        module = self.MockModule(
            module_id="test_module",
            name="Test Module",
        )
        
        lib.register(module)
        
        # 模块初始状态不是running
        assert lib.running_count == 0
    
    def test_get_status(self):
        """测试获取状态"""
        lib = ModuleLib()
        
        module = self.MockModule(
            module_id="test_module",
            name="Test Module",
        )
        
        lib.register(module)
        
        status = lib.get_status()
        
        assert "total_modules" in status
        assert "running_modules" in status
        assert "modules" in status
        assert "circular_dependencies" in status
    
    @pytest.mark.asyncio
    async def test_lifecycle_operations(self):
        """测试生命周期操作"""
        lib = ModuleLib()
        
        module = self.MockModule(
            module_id="test_module",
            name="Test Module",
        )
        
        lib.register(module)
        
        # 初始化
        success = await lib.initialize_module("test_module")
        assert success is True
        
        # 启动
        success = await lib.start_module("test_module")
        assert success is True
        
        # 停止
        success = await lib.stop_module("test_module")
        assert success is True
    
    @pytest.mark.asyncio
    async def test_lifecycle_all(self):
        """测试所有模块的生命周期操作"""
        lib = ModuleLib()
        
        module1 = self.MockModule(
            module_id="module1",
            name="Module 1",
        )
        module2 = self.MockModule(
            module_id="module2",
            name="Module 2",
        )
        
        lib.register(module1)
        lib.register(module2)
        
        # 初始化所有
        results = await lib.initialize_all()
        assert len(results) == 2
        
        # 启动所有
        results = await lib.start_all()
        assert len(results) == 2
        
        # 停止所有
        results = await lib.stop_all()
        assert len(results) == 2
    
    def test_resolve_dependencies(self):
        """测试依赖解析"""
        lib = ModuleLib()
        
        # 模块2依赖模块1
        module1 = self.MockModule(
            module_id="module1",
            name="Module 1",
        )
        module2 = self.MockModule(
            module_id="module2",
            name="Module 2",
            dependencies=["module1"],
        )
        
        lib.register(module1)
        lib.register(module2)
        
        order = lib.resolve_dependencies("module2")
        
        # module1应该先于module2加载
        assert "module1" in order
        assert "module2" in order
        assert order.index("module1") < order.index("module2")
    
    def test_check_circular_dependencies(self):
        """测试循环依赖检测"""
        lib = ModuleLib()
        
        # 创建循环依赖
        module1 = self.MockModule(
            module_id="module1",
            name="Module 1",
            dependencies=["module2"],
        )
        module2 = self.MockModule(
            module_id="module2",
            name="Module 2",
            dependencies=["module1"],
        )
        
        lib.register(module1)
        lib.register(module2)
        
        cycles = lib.check_circular_dependencies()
        
        # 应该检测到循环依赖
        assert len(cycles) >= 1
    
    def test_check_dependencies(self):
        """测试依赖检查"""
        lib = ModuleLib()
        
        module = self.MockModule(
            module_id="module1",
            name="Module 1",
        )
        
        lib.register(module)
        
        missing = lib._check_dependencies(["module1", "module2"])
        
        assert "module2" in missing
    
    def test_load_module_nonexistent_file(self):
        """测试加载不存在的文件"""
        lib = ModuleLib()
        
        module = lib.load_module(
            module_id="test_module",
            file_path="/nonexistent/path/module.py",
        )
        
        assert module is None


class TestGlobalFunctions:
    """测试全局函数"""
    
    def test_get_module_lib(self):
        """测试获取模块库实例"""
        lib1 = get_module_lib()
        lib2 = get_module_lib()
        
        assert lib1 is lib2
    
    def test_reset_module_lib(self):
        """测试重置模块库"""
        lib1 = get_module_lib()
        
        reset_module_lib()
        
        lib2 = get_module_lib()
        
        assert lib1 is not lib2

