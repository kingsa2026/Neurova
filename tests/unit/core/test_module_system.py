"""
Module/ModuleInfo/DependencyResolver 单元测试
"""

import unittest
from unittest.mock import patch, MagicMock

from neurova.core.module_system import (
    Module, ModuleInfo, ModuleState, DependencyResolver,
    StartupResult, ModuleRegistry,
)


class TestModuleImpl(Module):
    """测试用模块实现"""

    def _on_init(self):
        pass

    def _on_start(self):
        pass


class TestModuleState(unittest.TestCase):
    """ModuleState 枚举测试"""

    def test_all_states_exist(self):
        states = [s for s in ModuleState]
        self.assertIn(ModuleState.CREATED, states)
        self.assertIn(ModuleState.INITIALIZED, states)
        self.assertIn(ModuleState.STARTING, states)
        self.assertIn(ModuleState.RUNNING, states)
        self.assertIn(ModuleState.STOPPING, states)
        self.assertIn(ModuleState.STOPPED, states)
        self.assertIn(ModuleState.ERROR, states)

    def test_state_values(self):
        self.assertEqual(ModuleState.CREATED.value, "created")
        self.assertEqual(ModuleState.ERROR.value, "error")
        self.assertEqual(ModuleState.RUNNING.value, "running")


class TestStartupResult(unittest.TestCase):
    """StartupResult 数据类测试"""

    def test_direct_init(self):
        result = StartupResult(success=True, duration=150.0)
        self.assertTrue(result.success)
        self.assertEqual(result.duration, 150.0)
        self.assertEqual(result.modules_started, [])
        self.assertEqual(result.modules_failed, [])
        self.assertEqual(result.errors, {})

    def test_defaults(self):
        result = StartupResult(success=False)
        self.assertFalse(result.success)
        self.assertEqual(result.modules_started, [])


class TestModuleInfo(unittest.TestCase):
    """ModuleInfo 数据类测试"""

    def test_direct_init(self):
        info = ModuleInfo(
            name="test",
            module_class=TestModuleImpl,
            dependencies=[],
            description="A test module",
            version="2.0",
        )
        self.assertEqual(info.name, "test")
        self.assertEqual(info.module_class, TestModuleImpl)
        self.assertEqual(info.description, "A test module")
        self.assertEqual(info.version, "2.0")
        self.assertEqual(info.state, ModuleState.CREATED)

    def test_dependencies(self):
        info = ModuleInfo(
            name="dep_test",
            module_class=TestModuleImpl,
            dependencies=["core", "db"],
        )
        self.assertEqual(info.dependencies, ["core", "db"])


class TestModule(unittest.TestCase):
    """Module 基类测试"""

    def setUp(self):
        self.config = {"key": "value"}
        self.module = TestModuleImpl(config=self.config)

    def test_init_sets_config(self):
        self.assertEqual(self.module._config, {"key": "value"})

    def test_initial_state_is_created(self):
        self.assertEqual(self.module.state, ModuleState.CREATED)

    def test_name_fallback(self):
        self.assertEqual(self.module.name, "TestModuleImpl")

    def test_initialize(self):
        result = self.module.initialize()
        self.assertTrue(result)
        self.assertEqual(self.module.state, ModuleState.INITIALIZED)

    def test_start(self):
        self.module.initialize()
        result = self.module.start()
        self.assertTrue(result)
        self.assertEqual(self.module.state, ModuleState.RUNNING)

    def test_stop(self):
        self.module.initialize()
        self.module.start()
        result = self.module.stop()
        self.assertTrue(result)
        self.assertEqual(self.module.state, ModuleState.STOPPED)

    def test_set_state(self):
        self.module._state = ModuleState.INITIALIZED
        self.assertEqual(self.module.state, ModuleState.INITIALIZED)

    def test_log_error(self):
        self.module.log_error("something failed")


class TestDependencyResolver(unittest.TestCase):
    """DependencyResolver 测试"""

    def setUp(self):
        self.resolver = DependencyResolver()
        self.modules = []

    def _make_module(self, name, deps=None):
        info = ModuleInfo(
            name=name,
            module_class=TestModuleImpl,
            dependencies=deps or [],
        )
        self.modules.append(info)
        self.resolver.register(info)
        return info

    def test_register_module(self):
        info = self._make_module("core")
        self.assertIsNotNone(info)

    def test_resolve_no_deps(self):
        self._make_module("a")
        self._make_module("b")
        order = self.resolver.resolve_order()
        self.assertEqual(len(order), 2)
        self.assertIn("a", order)
        self.assertIn("b", order)

    def test_resolve_linear_deps(self):
        self._make_module("a")
        self._make_module("b", deps=["a"])
        order = self.resolver.resolve_order()
        self.assertEqual(len(order), 2)
        self.assertLess(order.index("a"), order.index("b"))

    def test_check_dependencies(self):
        self._make_module("a", deps=["missing_dep"])
        missing = self.resolver.check_dependencies("a")
        self.assertEqual(missing, ["missing_dep"])

    def test_get_module_info(self):
        self._make_module("a")
        info = self.resolver.get_module_info("a")
        self.assertIsNotNone(info)
        self.assertEqual(info.name, "a")

    def test_get_all_modules(self):
        self._make_module("a")
        self._make_module("b")
        all_modules = self.resolver.get_all_modules()
        self.assertEqual(len(all_modules), 2)


class TestModuleRegistry(unittest.TestCase):
    """ModuleRegistry 测试"""

    def test_register_and_start_all(self):
        registry = ModuleRegistry()
        registry.register("mod_a", TestModuleImpl)
        registry.register("mod_b", TestModuleImpl, dependencies=["mod_a"])

        result = registry.start_all()
        self.assertTrue(result.success)
        self.assertIn("mod_a", result.modules_started)
        self.assertIn("mod_b", result.modules_started)

    def test_get_instance(self):
        registry = ModuleRegistry()
        registry.register("mod_a", TestModuleImpl)
        registry.create_instance("mod_a")
        instance = registry.get_instance("mod_a")
        self.assertIsNotNone(instance)


if __name__ == "__main__":
    unittest.main()
