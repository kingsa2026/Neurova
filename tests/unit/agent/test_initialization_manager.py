"""Test InitializationManager deep module"""
import pytest
import sys
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch
from typing import Dict, Any, List, Optional

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

class TestInitializationManager:
    """Test cases for InitializationManager"""
    
    def test_register_component_without_dependencies(self):
        """Test registering a component without dependencies"""
        from neurova.agent.initialization_manager import InitializationManager
        
        manager = InitializationManager()
        
        # Register a simple component
        def init_func():
            return "component_a"
        
        manager.register("component_a", init_func)
        
        # Verify registration
        assert "component_a" in manager._components
        assert manager._components["component_a"]["initializer"] == init_func
        assert manager._components["component_a"]["deps"] == []
    
    def test_register_component_with_dependencies(self):
        """Test registering a component with dependencies"""
        from neurova.agent.initialization_manager import InitializationManager
        
        manager = InitializationManager()
        
        # Register components with dependencies
        def init_a():
            return "a"
        
        def init_b(a):
            return f"b_with_{a}"
        
        manager.register("a", init_a)
        manager.register("b", init_b, deps=["a"])
        
        # Verify dependencies
        assert manager._dependencies["b"] == ["a"]
        assert "a" in manager._dependencies.get("b", [])
    
    def test_initialize_all_no_dependencies(self):
        """Test initializing all components without dependencies"""
        from neurova.agent.initialization_manager import InitializationManager
        
        manager = InitializationManager()
        
        # Track initialization order
        init_order = []
        
        def init_a():
            init_order.append("a")
            return "a"
        
        def init_b():
            init_order.append("b")
            return "b"
        
        manager.register("a", init_a)
        manager.register("b", init_b)
        
        # Initialize all
        results = manager.initialize_all()
        
        # Verify both initialized
        assert results["a"] == "a"
        assert results["b"] == "b"
        assert len(init_order) == 2
        assert set(init_order) == {"a", "b"}
    
    def test_initialize_all_with_dependencies(self):
        """Test initializing components in dependency order"""
        from neurova.agent.initialization_manager import InitializationManager
        
        manager = InitializationManager()
        
        # Track initialization order
        init_order = []
        
        def init_a():
            init_order.append("a")
            return "a"
        
        def init_b(a):
            init_order.append("b")
            return f"b_{a}"
        
        def init_c(b):
            init_order.append("c")
            return f"c_{b}"
        
        manager.register("a", init_a)
        manager.register("b", init_b, deps=["a"])
        manager.register("c", init_c, deps=["b"])
        
        # Initialize all
        results = manager.initialize_all()
        
        # Verify initialization order
        assert init_order == ["a", "b", "c"]
        assert results["a"] == "a"
        assert results["b"] == "b_a"
        assert results["c"] == "c_b_a"
    
    def test_initialize_all_circular_dependency_detection(self):
        """Test detection of circular dependencies"""
        from neurova.agent.initialization_manager import InitializationManager
        
        manager = InitializationManager()
        
        # Create circular dependency
        def init_a(b):
            return "a"
        
        def init_b(a):
            return "b"
        
        manager.register("a", init_a, deps=["b"])
        manager.register("b", init_b, deps=["a"])
        
        # Should raise error for circular dependency
        with pytest.raises(ValueError, match="Circular dependency detected"):
            manager.initialize_all()
    
    def test_get_component_before_initialization(self):
        """Test getting component before initialization"""
        from neurova.agent.initialization_manager import InitializationManager
        
        manager = InitializationManager()
        
        def init_a():
            return "a"
        
        manager.register("a", init_a)
        
        # Should return None for uninitialized component
        assert manager.get_component("a") is None
        assert manager.get_component("nonexistent") is None
    
    def test_get_component_after_initialization(self):
        """Test getting component after initialization"""
        from neurova.agent.initialization_manager import InitializationManager
        
        manager = InitializationManager()
        
        def init_a():
            return "a"
        
        manager.register("a", init_a)
        manager.initialize_all()
        
        # Should return initialized component
        assert manager.get_component("a") == "a"
    
    def test_lazy_initialization(self):
        """Test lazy initialization of components"""
        from neurova.agent.initialization_manager import InitializationManager
        
        manager = InitializationManager(lazy=True)
        
        init_calls = []
        
        def init_a():
            init_calls.append("a")
            return "a"
        
        def init_b(a):
            init_calls.append("b")
            return f"b_{a}"
        
        manager.register("a", init_a)
        manager.register("b", init_b, deps=["a"])
        
        # Initialize only component b (should also initialize a)
        result = manager.initialize_component("b")
        
        # Verify lazy initialization
        assert result == "b_a"
        assert init_calls == ["a", "b"]
        assert manager.get_component("a") == "a"
        assert manager.get_component("b") == "b_a"
    
    def test_initialize_component_not_registered(self):
        """Test initializing a component that's not registered"""
        from neurova.agent.initialization_manager import InitializationManager
        
        manager = InitializationManager()
        
        with pytest.raises(KeyError, match="Component 'nonexistent' not registered"):
            manager.initialize_component("nonexistent")
    
    def test_initialization_error_handling(self):
        """Test error handling during initialization"""
        from neurova.agent.initialization_manager import InitializationManager
        
        manager = InitializationManager()
        
        def init_a():
            raise RuntimeError("Initialization failed")
        
        def init_b(a):
            return "b"
        
        manager.register("a", init_a)
        manager.register("b", init_b, deps=["a"])
        
        # Should propagate error
        with pytest.raises(RuntimeError, match="Initialization failed"):
            manager.initialize_all()
    
    def test_thread_safety(self):
        """Test thread safety of initialization"""
        import threading
        from neurova.agent.initialization_manager import InitializationManager
        
        manager = InitializationManager()
        
        # Track initialization from multiple threads
        results = {}
        lock = threading.Lock()
        
        def init_component(name, value):
            def init_func():
                with lock:
                    results[name] = value
                return value
            return init_func
        
        # Register components
        for i in range(5):
            manager.register(f"comp_{i}", init_component(f"comp_{i}", i))
        
        # Initialize from multiple threads
        threads = []
        for i in range(3):
            thread = threading.Thread(target=manager.initialize_all)
            threads.append(thread)
            thread.start()
        
        for thread in threads:
            thread.join()
        
        # Verify all components initialized
        assert len(results) == 5
        for i in range(5):
            assert results[f"comp_{i}"] == i

class TestInitializationManagerIntegration:
    """Integration tests for InitializationManager"""
    
    def test_agent_initialization_integration(self):
        """Test IntegrationManager with Agent-like initialization"""
        from neurova.agent.initialization_manager import InitializationManager
        
        manager = InitializationManager()
        
        # Simulate Agent components
        components_initialized = []
        
        def init_memory_manager():
            components_initialized.append("memory_manager")
            return Mock(name="MemoryManager")
        
        def init_evolution(memory_manager):
            components_initialized.append("evolution")
            return Mock(name="EvolutionOrchestrator")
        
        def init_voice_bridge(memory_manager, evolution):
            components_initialized.append("voice_bridge")
            return Mock(name="VoiceMemoryBridge")
        
        def init_tool_executor(memory_manager):
            components_initialized.append("tool_executor")
            return Mock(name="ToolExecutor")
        
        # Register components with dependencies
        manager.register("memory_manager", init_memory_manager)
        manager.register("evolution", init_evolution, deps=["memory_manager"])
        manager.register("voice_bridge", init_voice_bridge, deps=["memory_manager", "evolution"])
        manager.register("tool_executor", init_tool_executor, deps=["memory_manager"])
        
        # Initialize all
        results = manager.initialize_all()
        
        # Verify initialization order
        assert components_initialized == [
            "memory_manager",  # No deps
            "evolution",       # Depends on memory_manager
            "tool_executor",   # Depends on memory_manager
            "voice_bridge"     # Depends on memory_manager and evolution
        ]
        
        # Verify all components available
        assert manager.get_component("memory_manager") is not None
        assert manager.get_component("evolution") is not None
        assert manager.get_component("voice_bridge") is not None
        assert manager.get_component("tool_executor") is not None

if __name__ == "__main__":
    # Run tests manually
    test = TestInitializationManager()
    
    print("Running tests...")
    test.test_register_component_without_dependencies()
    print("✅ test_register_component_without_dependencies")
    
    test.test_register_component_with_dependencies()
    print("✅ test_register_component_with_dependencies")
    
    test.test_initialize_all_no_dependencies()
    print("✅ test_initialize_all_no_dependencies")
    
    test.test_initialize_all_with_dependencies()
    print("✅ test_initialize_all_with_dependencies")
    
    test.test_initialize_all_circular_dependency_detection()
    print("✅ test_initialize_all_circular_dependency_detection")
    
    test.test_get_component_before_initialization()
    print("✅ test_get_component_before_initialization")
    
    test.test_get_component_after_initialization()
    print("✅ test_get_component_after_initialization")
    
    test.test_lazy_initialization()
    print("✅ test_lazy_initialization")
    
    test.test_initialize_component_not_registered()
    print("✅ test_initialize_component_not_registered")
    
    test.test_initialization_error_handling()
    print("✅ test_initialization_error_handling")
    
    test.test_thread_safety()
    print("✅ test_thread_safety")
    
    # Integration test
    integration_test = TestInitializationManagerIntegration()
    integration_test.test_agent_initialization_integration()
    print("✅ test_agent_initialization_integration")
    
    print("\n✅ All tests passed!")