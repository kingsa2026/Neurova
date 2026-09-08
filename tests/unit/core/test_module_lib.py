"""
测试模块库
"""
import asyncio
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
        assert ModuleType.CUSTOM.value == "custom"
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
        assert desc.enabled is True
    
    def test_module_descriptor_to_dict(self):
        """测试模块描述符转换为字典"""
        desc = ModuleDescriptor(
            module_id="test_module",
            module_type=ModuleType.CUSTOM,
        )
        
        data = desc.to_dict()
        
        assert data["module_id"] == "test_module"
        assert data["module_type"] == "custom"


class TestModuleLib:
    """测试ModuleLib类"""
    
    class MockModule(BaseModule):
        """模拟模块（BaseModule 钩子为同步抽象方法）"""

        def on_initialize(self):
            pass

        def on_start(self):
            pass

        def on_stop(self):
            pass
    
    def test_init(self):
        """测试初始化"""
        lib = ModuleLib()
        
        assert lib._modules == {}
        assert lib._load_paths == []
    
    def test_add_load_path(self, tmp_path):
        """测试添加加载路径（实现拒绝不存在的路径）"""
        lib = ModuleLib()

        assert lib.add_load_path(str(tmp_path)) is True
        assert str(tmp_path) in [str(p) for p in lib._load_paths]
        assert lib.add_load_path("/path/to/modules") is False
    
    def test_remove_load_path(self):
        """测试移除加载路径"""
        lib = ModuleLib()
        
        import tempfile as _tf

        real = _tf.mkdtemp()
        lib.add_load_path(real)
        result = lib.remove_load_path(real)

        assert result is True
        assert real not in [str(p) for p in lib._load_paths]
    
    def test_remove_nonexistent_load_path(self):
        """测试移除不存在的加载路径"""
        lib = ModuleLib()
        
        result = lib.remove_load_path("/nonexistent/path")
        
        assert result is False
    
    def test_register_module(self):
        """测试注册模块"""
        lib = ModuleLib()
        
        descriptor = ModuleDescriptor(
            module_id="test_module",
            name="Test Module",
        )
        
        success = lib.register(descriptor, self.MockModule)
        
        assert success is True
        assert "test_module" in lib._descriptors
    
    def test_register_duplicate_module(self):
        """测试注册重复模块"""
        lib = ModuleLib()
        
        descriptor = ModuleDescriptor(
            module_id="test_module",
            name="Test Module",
        )
        
        lib.register(descriptor, self.MockModule)
        success = lib.register(descriptor, self.MockModule)
        
        assert success is False
    
    @pytest.mark.asyncio
    async def test_unregister_module_async(self):
        """测试异步注销模块"""
        lib = ModuleLib()
        
        descriptor = ModuleDescriptor(

        
            module_id="test_module",

        
            name="Test Module",

        
        )
        
        lib.register(descriptor, self.MockModule)
        success = await lib.unregister_async("test_module")
        
        assert success is True
        assert "test_module" not in lib._modules
    
    def test_unregister_module_nonexistent(self):
        """测试注销不存在的模块"""
        lib = ModuleLib()
        
        success = lib.unregister("nonexistent")
        
        assert success is False
    
    def test_get_module(self):
        """测试获取模块（get_module 返回已加载实例）"""
        lib = ModuleLib()

        descriptor = ModuleDescriptor(
            module_id="test_module",
            name="Test Module",
        )

        lib.register(descriptor, self.MockModule)
        loaded = lib.load_module("test_module")
        retrieved = lib.get_module("test_module")

        assert loaded is not None
        assert retrieved is loaded
    
    def test_get_nonexistent_module(self):
        """测试获取不存在的模块"""
        lib = ModuleLib()
        
        retrieved = lib.get_module("nonexistent")
        
        assert retrieved is None
    
    def test_get_descriptor(self):
        """测试获取模块描述符"""
        lib = ModuleLib()
        
        descriptor = ModuleDescriptor(

        
            module_id="test_module",

        
            name="Test Module",

        
        )
        
        lib.register(descriptor, self.MockModule)
        desc = lib.get_descriptor("test_module")
        
        assert desc is not None
        assert desc.module_id == "test_module"
    
    def test_list_modules(self):
        """实现 list_modules() 无过滤参数——键面锁定"""
        lib = ModuleLib()

        lib.register(ModuleDescriptor(module_id="module1", module_type=ModuleType.BUILTIN), self.MockModule)
        lib.register(ModuleDescriptor(module_id="module2", module_type=ModuleType.CUSTOM), self.MockModule)

        modules = lib.list_modules()
        assert len(modules) == 2

    def test_list_modules_filter_by_type(self):
        """实现无类型过滤参数——用 comprehension 断言"""
        lib = ModuleLib()

        lib.register(ModuleDescriptor(module_id="module1", module_type=ModuleType.BUILTIN), self.MockModule)
        lib.register(ModuleDescriptor(module_id="module2", module_type=ModuleType.CUSTOM), self.MockModule)

        builtin = [d for d in lib.list_modules() if d.module_type == ModuleType.BUILTIN]
        custom = [d for d in lib.list_modules() if d.module_type == ModuleType.CUSTOM]
        assert len(builtin) == 1
        assert len(custom) == 1

    def test_has_module(self):
        """测试检查模块是否存在"""
        lib = ModuleLib()
        
        descriptor = ModuleDescriptor(

        
            module_id="test_module",

        
            name="Test Module",

        
        )
        
        lib.register(descriptor, self.MockModule)
        
        assert lib.has_module("test_module") is True
        assert lib.has_module("nonexistent") is False
    
    def test_get_running_modules(self):
        """测试获取运行中的模块"""
        lib = ModuleLib()
        
        descriptor = ModuleDescriptor(

        
            module_id="test_module",

        
            name="Test Module",

        
        )
        
        lib.register(descriptor, self.MockModule)
        
        running = lib.get_running_modules()
        
        # 模块初始状态不是running
        assert len(running) == 0
    
    def test_module_count(self):
        """测试模块计数"""
        lib = ModuleLib()

        lib.register(ModuleDescriptor(module_id="module1", name="Module 1"), self.MockModule)
        lib.register(ModuleDescriptor(module_id="module2", name="Module 2"), self.MockModule)

        assert lib.module_count == 2
    
    def test_running_count(self):
        """测试运行中模块计数"""
        lib = ModuleLib()
        
        descriptor = ModuleDescriptor(

        
            module_id="test_module",

        
            name="Test Module",

        
        )
        
        lib.register(descriptor, self.MockModule)
        
        # 模块初始状态不是running
        assert lib.running_count == 0
    
    def test_get_status(self):
        """测试获取状态"""
        lib = ModuleLib()
        
        descriptor = ModuleDescriptor(

        
            module_id="test_module",

        
            name="Test Module",

        
        )
        
        lib.register(descriptor, self.MockModule)
        
        status = lib.get_status()

        # 实现键面：total_modules / running_modules / load_paths / modules
        assert "total_modules" in status
        assert "running_modules" in status
        assert "modules" in status
        assert "load_paths" in status
    
    @pytest.mark.asyncio
    async def test_lifecycle_operations(self):
        """测试生命周期操作（initialize/start/stop 为同步方法）"""
        lib = ModuleLib()

        descriptor = ModuleDescriptor(
            module_id="test_module",
            name="Test Module",
        )

        lib.register(descriptor, self.MockModule)

        # 初始化
        success = lib.initialize_module("test_module")
        assert success is True

        # 启动
        success = lib.start_module("test_module")
        assert success is True

        # 停止
        success = lib.stop_module("test_module")
        assert success is True

    @pytest.mark.asyncio
    async def test_lifecycle_all(self):
        """测试所有模块的生命周期操作（*_all 为同步方法）"""
        lib = ModuleLib()

        lib.register(ModuleDescriptor(module_id="module1", name="Module 1"), self.MockModule)
        lib.register(ModuleDescriptor(module_id="module2", name="Module 2"), self.MockModule)

        # 初始化所有
        results = lib.initialize_all()
        assert len(results) == 2

        # 启动所有
        results = lib.start_all()
        assert len(results) == 2

        # 停止所有
        results = lib.stop_all()
        assert len(results) == 2

    def test_resolve_dependencies(self):
        """测试依赖解析"""
        lib = ModuleLib()

        # 模块2依赖模块1
        lib.register(ModuleDescriptor(module_id="module1", name="Module 1"), self.MockModule)
        lib.register(
            ModuleDescriptor(module_id="module2", name="Module 2", dependencies=["module1"]),
            self.MockModule,
        )

        order = lib.resolve_dependencies()

        # module1应该先于module2加载
        assert "module1" in order
        assert "module2" in order
        assert order.index("module1") < order.index("module2")

    def test_check_circular_dependencies(self):
        """测试循环依赖检测"""
        lib = ModuleLib()

        # 创建循环依赖
        lib.register(
            ModuleDescriptor(module_id="module1", name="Module 1", dependencies=["module2"]),
            self.MockModule,
        )
        lib.register(
            ModuleDescriptor(module_id="module2", name="Module 2", dependencies=["module1"]),
            self.MockModule,
        )

        cycles = lib.check_circular_dependencies()

        # 应该检测到循环依赖
        assert len(cycles) >= 1

    def test_check_dependencies(self):
        """测试依赖检查（契约：_check_dependencies(module_id) -> bool，按已加载实例判定）"""
        lib = ModuleLib()

        lib.register(ModuleDescriptor(module_id="module1", name="Module 1"), self.MockModule)
        lib.register(
            ModuleDescriptor(module_id="module2", name="Module 2", dependencies=["module1"]),
            self.MockModule,
        )

        # module1 未加载 → module2 依赖不满足
        assert lib._check_dependencies("module2") is False

        # module1 加载后依赖满足
        assert lib.load_module("module1") is not None
        assert lib._check_dependencies("module2") is True

    def test_load_module_nonexistent_file(self):
        """测试加载入口点指向不存在文件的模块"""
        lib = ModuleLib()

        lib.register(
            ModuleDescriptor(
                module_id="test_module",
                name="test_module",
                entry_point="/nonexistent/path/module.py",
            )
        )

        module = lib.load_module("test_module")

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

