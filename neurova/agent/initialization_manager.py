"""
InitializationManager - Deep module for managing component initialization order

Automatically resolves dependencies between components and initializes them
in the correct order. Prevents initialization order bugs like the one fixed
in EvolutionOrchestrator.

Interface:
- register(name, initializer, deps=None): Register component with dependencies
- initialize_all() -> Dict[str, Any]: Initialize all components in dependency order
- get_component(name) -> Any: Get initialized component
- initialize_component(name) -> Any: Initialize specific component (lazy mode)

Benefits:
- Locality: All initialization logic in one place
- Leverage: Prevents ordering bugs automatically
- Testability: Clear dependency graph
"""

import threading
from collections import defaultdict, deque
from typing import Any, Callable, Dict, List, Optional, Set


class InitializationManager:
    """Manages component initialization with dependency resolution.

    Deep module: small interface, deep implementation

    Features:
    - Automatic dependency resolution via topological sort
    - Circular dependency detection
    - Lazy initialization support
    - Thread-safe operations
    - Error handling with component context
    """

    def __init__(self, lazy: bool = False):
        """
        Initialize the manager.

        Args:
            lazy: If True, components are initialized on-demand via initialize_component()
                  If False, all components are initialized via initialize_all()
        """
        self._lazy = lazy
        self._components: Dict[str, Dict[str, Any]] = {}
        self._dependencies: Dict[str, List[str]] = defaultdict(list)
        self._initialized: Dict[str, Any] = {}
        self._initializing: Set[str] = set()  # For circular dependency detection
        self._lock = threading.RLock()

    def register(
        self,
        name: str,
        initializer: Callable[..., Any],
        deps: Optional[List[str]] = None,
    ) -> None:
        """Register a component with its initializer and dependencies.

        Args:
            name: Unique component name
            initializer: Callable that returns the component instance
            deps: List of component names this component depends on

        Raises:
            ValueError: If component name is already registered
        """
        with self._lock:
            if name in self._components:
                raise ValueError(f"Component '{name}' is already registered")

            self._components[name] = {
                "initializer": initializer,
                "deps": deps or [],
            }
            self._dependencies[name] = deps or []

    def initialize_all(self) -> Dict[str, Any]:
        """Initialize all registered components in dependency order.

        Uses topological sort to determine initialization order.
        Detects circular dependencies and raises ValueError.

        Returns:
            Dict mapping component names to their initialized instances

        Raises:
            ValueError: If circular dependency is detected
            RuntimeError: If initialization fails for any component
        """
        with self._lock:
            # Reset initialization state
            self._initialized.clear()
            self._initializing.clear()

            # Get topological order
            init_order = self._topological_sort()

            # Initialize components in order
            results = {}
            for name in init_order:
                results[name] = self._initialize_component(name)

            return results

    def get_component(self, name: str) -> Optional[Any]:
        """Get an initialized component by name.

        Args:
            name: Component name

        Returns:
            Initialized component instance, or None if not initialized
        """
        return self._initialized.get(name)

    def initialize_component(self, name: str) -> Any:
        """Initialize a specific component and its dependencies.

        Useful for lazy initialization mode.

        Args:
            name: Component name to initialize

        Returns:
            Initialized component instance

        Raises:
            KeyError: If component is not registered
            RuntimeError: If initialization fails
        """
        if name not in self._components:
            raise KeyError(f"Component '{name}' not registered")

        return self._initialize_component(name)

    def _initialize_component(self, name: str) -> Any:
        """Internal method to initialize a component.

        Args:
            name: Component name

        Returns:
            Initialized component instance

        Raises:
            RuntimeError: If initialization fails or circular dependency detected
        """
        # Return cached if already initialized
        if name in self._initialized:
            return self._initialized[name]

        # Check for circular dependency
        if name in self._initializing:
            cycle = list(self._initializing) + [name]
            raise ValueError(f"Circular dependency detected: {' -> '.join(cycle)}")

        # Mark as initializing
        self._initializing.add(name)

        try:
            # Initialize dependencies first
            component_info = self._components[name]
            dep_results = {}

            for dep_name in component_info["deps"]:
                if dep_name not in self._components:
                    raise RuntimeError(f"Dependency '{dep_name}' of component '{name}' is not registered")
                dep_results[dep_name] = self._initialize_component(dep_name)

            # Call initializer with dependencies as kwargs
            initializer = component_info["initializer"]

            # Prepare arguments: inject dependencies by name
            import inspect

            sig = inspect.signature(initializer)
            kwargs = {}

            for param_name, param in sig.parameters.items():
                if param_name in dep_results:
                    kwargs[param_name] = dep_results[param_name]
                elif param.default is not inspect.Parameter.empty:
                    # Use default value if provided
                    continue
                else:
                    # Try to pass as positional if no default
                    if param_name in dep_results:
                        kwargs[param_name] = dep_results[param_name]

            # Call initializer
            try:
                instance = initializer(**kwargs)
            except TypeError as e:
                # If keyword injection fails, try positional
                try:
                    positional_args = [dep_results[dep] for dep in component_info["deps"]]
                    instance = initializer(*positional_args)
                except Exception:
                    raise RuntimeError(f"Failed to initialize component '{name}': {e}")

            # Cache result
            self._initialized[name] = instance
            return instance

        except Exception as e:
            raise RuntimeError(f"Failed to initialize component '{name}': {e}")
        finally:
            # Remove from initializing set
            self._initializing.discard(name)

    def _topological_sort(self) -> List[str]:
        """Perform topological sort on component dependencies.

        Returns:
            List of component names in initialization order

        Raises:
            ValueError: If circular dependency is detected
        """
        # Build adjacency list and in-degree count
        graph = defaultdict(list)
        in_degree = defaultdict(int)

        # Initialize in-degree for all components
        for name in self._components:
            in_degree[name] = 0

        # Build graph
        for name, info in self._components.items():
            for dep in info["deps"]:
                graph[dep].append(name)
                in_degree[name] += 1

        # Kahn's algorithm for topological sort
        queue = deque([name for name, degree in in_degree.items() if degree == 0])
        result = []

        while queue:
            # Sort for deterministic order
            current = sorted(queue)[0]
            queue.remove(current)
            result.append(current)

            # Reduce in-degree for dependents
            for neighbor in graph[current]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        # Check for circular dependencies
        if len(result) != len(self._components):
            # Find components in cycle
            remaining = set(self._components.keys()) - set(result)
            list(remaining)

            # Try to find the actual cycle
            cycle_path = self._find_cycle(remaining)
            raise ValueError(f"Circular dependency detected involving: {cycle_path}")

        return result

    def _find_cycle(self, nodes: Set[str]) -> List[str]:
        """Find a cycle in the dependency graph.

        Args:
            nodes: Set of nodes that are part of cycles

        Returns:
            List of node names forming a cycle
        """
        # Simple DFS to find a cycle
        visited = set()
        path = []

        def dfs(node):
            if node in visited:
                # Found cycle
                cycle_start = path.index(node)
                return path[cycle_start:] + [node]

            visited.add(node)
            path.append(node)

            for dep in self._dependencies.get(node, []):
                if dep in nodes:
                    result = dfs(dep)
                    if result:
                        return result

            path.pop()
            visited.discard(node)
            return None

        for node in nodes:
            result = dfs(node)
            if result:
                return result

        return list(nodes)  # Fallback

    def clear(self) -> None:
        """Clear all registered components and initialized instances."""
        with self._lock:
            self._components.clear()
            self._dependencies.clear()
            self._initialized.clear()
            self._initializing.clear()

    def get_initialization_order(self) -> List[str]:
        """Get the initialization order without actually initializing.

        Returns:
            List of component names in initialization order
        """
        return self._topological_sort()

    def get_dependency_graph(self) -> Dict[str, List[str]]:
        """Get the dependency graph.

        Returns:
            Dict mapping component names to their dependencies
        """
        return dict(self._dependencies)

    def get_statistics(self) -> Dict[str, Any]:
        """Get initialization statistics.

        Returns:
            Dict with statistics about registered and initialized components
        """
        return {
            "registered_components": len(self._components),
            "initialized_components": len(self._initialized),
            "components_with_deps": sum(1 for deps in self._dependencies.values() if deps),
            "max_dependency_depth": self._max_dependency_depth(),
            "has_cycles": self._has_cycles(),
        }

    def _max_dependency_depth(self) -> int:
        """Calculate maximum dependency depth."""
        depth_cache = {}

        def get_depth(name):
            if name in depth_cache:
                return depth_cache[name]

            deps = self._dependencies.get(name, [])
            if not deps:
                depth_cache[name] = 0
                return 0

            max_dep_depth = max(get_depth(dep) for dep in deps)
            depth_cache[name] = max_dep_depth + 1
            return max_dep_depth + 1

        return max((get_depth(name) for name in self._components), default=0)

    def _has_cycles(self) -> bool:
        """Check if the dependency graph has cycles."""
        try:
            self._topological_sort()
            return False
        except ValueError:
            return True


# Factory function
def create_initialization_manager(lazy: bool = False) -> InitializationManager:
    """Create an InitializationManager instance.

    Args:
        lazy: If True, enable lazy initialization

    Returns:
        InitializationManager instance
    """
    return InitializationManager(lazy=lazy)


# Default singleton
_default_manager: Optional[InitializationManager] = None


def get_initialization_manager(lazy: bool = False) -> InitializationManager:
    """Get or create the default InitializationManager.

    Args:
        lazy: If True, enable lazy initialization

    Returns:
        InitializationManager instance
    """
    global _default_manager
    if _default_manager is None:
        _default_manager = InitializationManager(lazy=lazy)
    return _default_manager


def reset_initialization_manager() -> None:
    """Reset the default InitializationManager."""
    global _default_manager
    _default_manager = None
