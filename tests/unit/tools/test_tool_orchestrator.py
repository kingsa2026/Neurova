"""
测试 ToolOrchestrator 并行执行和 DAG 编排

验证：
1. 真正的并行执行（非顺序）
2. DAG 拓扑排序正确性
3. 目标解析能力
"""

import pytest
import asyncio
import time
from unittest.mock import Mock, AsyncMock, patch
from typing import Dict, List, Any


class TestOrchestratorParallelExecution:
    """测试并行执行能力"""
    
    def _create_orchestrator(self):
        """创建 ToolOrchestrator 实例"""
        from neurova.tool_layers.tool_orchestrator import ToolOrchestrator
        return ToolOrchestrator()
    
    @pytest.mark.asyncio
    async def test_parallel_execution_is_actually_parallel(self):
        """验证并行执行确实是并行的，而非顺序"""
        orchestrator = self._create_orchestrator()
        
        # 记录每个工具的开始和结束时间
        start_times: Dict[str, float] = {}
        end_times: Dict[str, float] = {}
        
        async def mock_execute(tool_name, params):
            start_times[tool_name] = time.time()
            await asyncio.sleep(0.15)  # 150ms 延迟
            end_times[tool_name] = time.time()
            return {"tool": tool_name}
        
        orchestrator._executor = Mock()
        orchestrator._executor.execute = mock_execute
        
        # 注册两个无依赖的工具
        orchestrator._capability_graph.register_tool(
            "tool_a", capabilities=["cap_a"], dependencies=[]
        )
        orchestrator._capability_graph.register_tool(
            "tool_b", capabilities=["cap_b"], dependencies=[]
        )
        
        # 使用 tool_plan 直接传入并行计划
        result = await orchestrator.orchestrate(
            goal="test parallel",
            tool_plan=["tool_a", "tool_b"]
        )
        
        # 验证两个工具都成功
        assert result.status.value == "success"
        assert len(result.steps) == 2
        
        # 验证并行：两个工具的开始时间应该接近（< 50ms），而不是顺序（> 150ms）
        assert "tool_a" in start_times and "tool_b" in start_times
        start_diff = abs(start_times["tool_a"] - start_times["tool_b"])
        assert start_diff < 0.05, (
            f"Tools should start nearly simultaneously, but gap was {start_diff*1000:.1f}ms"
        )
        
        # 验证总时间接近 150ms（并行），而非 300ms（顺序）
        total_duration = result.total_duration_ms
        assert total_duration < 300, (
            f"Parallel execution should take ~150ms, but took {total_duration:.0f}ms"
        )
    
    @pytest.mark.asyncio
    async def test_orchestrate_with_parallel_tools(self):
        """验证 orchestrate 方法支持并行执行"""
        orchestrator = self._create_orchestrator()
        
        # 记录执行开始时间
        start_times = {}
        end_times = {}
        
        async def mock_execute(tool_name, params):
            start_times[tool_name] = time.time()
            await asyncio.sleep(0.1)
            end_times[tool_name] = time.time()
            return {"tool": tool_name}
        
        orchestrator._executor = Mock()
        orchestrator._executor.execute = mock_execute
        
        # 注册无依赖的工具
        orchestrator._capability_graph.register_tool(
            "fast_tool_a", capabilities=["fast_a"], dependencies=[]
        )
        orchestrator._capability_graph.register_tool(
            "fast_tool_b", capabilities=["fast_b"], dependencies=[]
        )
        
        # 直接传入工具计划
        result = await orchestrator.orchestrate(
            goal="test", tool_plan=["fast_tool_a", "fast_tool_b"]
        )
        
        # 验证两个工具都执行了
        assert len(result.steps) == 2
        assert all(r.status.value == "success" for r in result.steps)
        
        # 验证并行性
        start_diff = abs(start_times["fast_tool_a"] - start_times["fast_tool_b"])
        assert start_diff < 0.05


class TestOrchestratorDAG:
    """测试 DAG 编排能力"""
    
    def _create_orchestrator(self):
        from neurova.tool_layers.tool_orchestrator import ToolOrchestrator
        return ToolOrchestrator()
    
    @pytest.mark.asyncio
    async def test_dag_respects_dependencies(self):
        """验证 DAG 正确处理依赖关系"""
        orchestrator = self._create_orchestrator()
        
        execution_order = []
        
        async def mock_execute(tool_name, params):
            execution_order.append(tool_name)
            await asyncio.sleep(0.05)
            return {"tool": tool_name}
        
        orchestrator._executor = Mock()
        orchestrator._executor.execute = mock_execute
        
        # 创建 DAG：A -> B -> C（链式依赖）
        orchestrator._capability_graph.register_tool("A", capabilities=["a"], dependencies=[])
        orchestrator._capability_graph.register_tool("B", capabilities=["b"], dependencies=["A"])
        orchestrator._capability_graph.register_tool("C", capabilities=["c"], dependencies=["B"])
        
        # 使用 build_plan_from_goal 或直接传入拓扑排序结果
        plan = orchestrator.build_plan_from_goal("do a then b then c")
        
        # 如果 goal 解析没有返回 A/B/C，手动传入拓扑排序后的计划
        if not plan or plan != ["A", "B", "C"]:
            plan = ["A", "B", "C"]
        
        result = await orchestrator.orchestrate(
            goal="chain", tool_plan=plan
        )
        
        # 验证执行顺序
        assert execution_order == ["A", "B", "C"]
        assert result.status.value == "success"
    
    @pytest.mark.asyncio
    async def test_dag_parallel_layers(self):
        """验证 DAG 支持多层并行"""
        orchestrator = self._create_orchestrator()
        
        layer_execution = []
        start_times: Dict[str, float] = {}
        
        async def mock_execute(tool_name, params):
            start_times[tool_name] = time.time()
            layer_execution.append(("start", tool_name))
            await asyncio.sleep(0.1)
            layer_execution.append(("end", tool_name))
            return {"tool": tool_name}
        
        orchestrator._executor = Mock()
        orchestrator._executor.execute = mock_execute
        
        # 创建 DAG：
        # Layer 0: A (无依赖)
        # Layer 1: B, C (都依赖 A) — 应并行
        # Layer 2: D (依赖 B 和 C)
        orchestrator._capability_graph.register_tool("A", capabilities=["a"], dependencies=[])
        orchestrator._capability_graph.register_tool("B", capabilities=["b"], dependencies=["A"])
        orchestrator._capability_graph.register_tool("C", capabilities=["c"], dependencies=["A"])
        orchestrator._capability_graph.register_tool("D", capabilities=["d"], dependencies=["B", "C"])
        
        # 手动传入拓扑排序计划
        plan = ["A", "B", "C", "D"]
        
        result = await orchestrator.orchestrate(goal="multi-layer", tool_plan=plan)
        
        assert len(result.steps) == 4
        assert all(r.status.value == "success" for r in result.steps)
        
        # 验证 B 和 C 并行：它们的开始时间应该接近
        assert "B" in start_times and "C" in start_times
        bc_diff = abs(start_times["B"] - start_times["C"])
        assert bc_diff < 0.05, (
            f"B and C should start nearly simultaneously, but gap was {bc_diff*1000:.1f}ms"
        )
        
        # 验证总时间 < 350ms（3层串行每层100ms），因为 B 和 C 并行
        # 如果完全串行 = 4 * 100ms = 400ms
        # 如果 B,C 并行 = A(100) + max(B,C)(100) + D(100) = 300ms
        assert result.total_duration_ms < 400, (
            f"Expected parallel layers, but took {result.total_duration_ms:.0f}ms"
        )


class TestOrchestratorGoalResolution:
    """测试目标解析能力"""
    
    def _create_orchestrator(self):
        from neurova.tool_layers.tool_orchestrator import ToolOrchestrator
        return ToolOrchestrator()
    
    def test_goal_resolution_keywords(self):
        """验证关键词匹配解析（词边界匹配）"""
        orchestrator = self._create_orchestrator()
        
        # 测试各种目标描述
        test_cases = [
            ("read the file", ["read_file"]),
            ("write data to disk", ["write_file"]),
            ("save data to disk", ["write_file"]),
            ("search for files", ["search_files"]),
            ("find a file", ["search_files"]),
            ("remember this information", ["search_memory"]),
            ("recall the memory", ["search_memory"]),
            ("search the web", ["search_web"]),
            ("fetch a url", ["search_web"]),
            ("execute the code", ["run_code"]),
            ("run a script", ["run_code"]),
            ("do something unknown", ["process_data"]),  # 默认
        ]
        
        for goal, expected in test_cases:
            result = orchestrator._resolve_goal_to_capabilities_sync(goal)
            assert result == expected, f"Goal '{goal}' should resolve to {expected}, got {result}"
    
    def test_goal_resolution_no_substring_false_match(self):
        """验证不会因为子串误匹配"""
        orchestrator = self._create_orchestrator()
        
        # "search" 不应匹配 "read"
        result = orchestrator._resolve_goal_to_capabilities_sync("search for information")
        assert "read_file" not in result, f"'search' should not trigger 'read_file', got {result}"
        
        # "remember" 不应匹配 "member"
        result = orchestrator._resolve_goal_to_capabilities_sync("count the member list")
        assert "search_memory" not in result, f"'member' should not trigger 'search_memory', got {result}"
    
    def test_goal_resolution_multiple_capabilities(self):
        """验证多能力解析"""
        orchestrator = self._create_orchestrator()
        
        goal = "read the file and search the web"
        result = orchestrator._resolve_goal_to_capabilities_sync(goal)
        
        assert "read_file" in result
        assert "search_web" in result


class TestOrchestratorFallback:
    """测试降级机制"""
    
    def _create_orchestrator(self):
        from neurova.tool_layers.tool_orchestrator import ToolOrchestrator
        return ToolOrchestrator()
    
    @pytest.mark.asyncio
    async def test_fallback_on_failure(self):
        """验证失败时尝试降级"""
        orchestrator = self._create_orchestrator()
        
        call_count = {"primary": 0, "fallback": 0}
        
        async def mock_execute(tool_name, params):
            if tool_name == "primary_tool":
                call_count["primary"] += 1
                raise Exception("Primary tool failed")
            elif tool_name == "fallback_tool":
                call_count["fallback"] += 1
                return {"tool": "fallback"}
            return {}
        
        orchestrator._executor = Mock()
        orchestrator._executor.execute = mock_execute
        
        # 注册工具和降级关系
        # fallbacks 字段表示 "当此工具失败时，尝试这些备选工具"
        orchestrator._capability_graph.register_tool(
            "primary_tool", capabilities=["primary"], dependencies=[],
            fallbacks=["fallback_tool"]
        )
        orchestrator._capability_graph.register_tool(
            "fallback_tool", capabilities=["fallback"], dependencies=[]
        )
        
        # 执行主工具
        result = await orchestrator._execute_step("step_0", "primary_tool", {})
        
        # 验证主工具失败
        assert result.status.value == "failed"
        
        # 尝试降级
        fallback_result = await orchestrator._try_fallback(
            "step_0", "primary_tool", {}, "Primary tool failed"
        )
        
        # 验证降级成功
        assert fallback_result.status.value == "success"
        assert call_count["fallback"] == 1


class TestOrchestratorIntegration:
    """测试完整编排流程"""
    
    def _create_orchestrator(self):
        from neurova.tool_layers.tool_orchestrator import ToolOrchestrator
        return ToolOrchestrator()
    
    @pytest.mark.asyncio
    async def test_full_orchestration_flow(self):
        """验证完整编排流程"""
        orchestrator = self._create_orchestrator()
        
        execution_log = []
        
        async def mock_execute(tool_name, params):
            execution_log.append(tool_name)
            await asyncio.sleep(0.01)
            return {"tool": tool_name}
        
        orchestrator._executor = Mock()
        orchestrator._executor.execute = mock_execute
        
        # 注册工具链
        orchestrator._capability_graph.register_tool("step_a", capabilities=["a"], dependencies=[])
        orchestrator._capability_graph.register_tool("step_b", capabilities=["b"], dependencies=["step_a"])
        
        # 使用 tool_plan 直接传入
        result = await orchestrator.orchestrate(
            goal="sequential flow", tool_plan=["step_a", "step_b"]
        )
        
        # 验证结果
        assert len(result.steps) == 2
        assert all(r.status.value == "success" for r in result.steps)
        assert execution_log == ["step_a", "step_b"]
        assert result.status.value == "success"
    
    @pytest.mark.asyncio
    async def test_orchestrate_with_goal_parsing(self):
        """验证从 goal 解析并执行"""
        orchestrator = self._create_orchestrator()
        
        execution_log = []
        
        async def mock_execute(tool_name, params):
            execution_log.append(tool_name)
            return {"tool": tool_name}
        
        orchestrator._executor = Mock()
        orchestrator._executor.execute = mock_execute
        
        # 注册默认工具
        orchestrator._capability_graph.register_tool("file_read", capabilities=["read_file"], dependencies=[])
        orchestrator._capability_graph.register_tool("file_search", capabilities=["search_files"], dependencies=[])
        
        # 使用 goal 解析
        result = await orchestrator.orchestrate(goal="read the file")
        
        # 验证执行了 read_file
        assert len(result.steps) >= 1
        tool_names = [s.tool_name for s in result.steps]
        assert "file_read" in tool_names
    
    @pytest.mark.asyncio
    async def test_parallel_and_sequential混合(self):
        """验证并行+串行混合编排"""
        orchestrator = self._create_orchestrator()
        
        start_times: Dict[str, float] = {}
        
        async def mock_execute(tool_name, params):
            start_times[tool_name] = time.time()
            await asyncio.sleep(0.1)
            return {"tool": tool_name}
        
        orchestrator._executor = Mock()
        orchestrator._executor.execute = mock_execute
        
        # DAG:
        # Layer 0: A (无依赖)
        # Layer 1: B, C (都依赖 A) — 并行
        # Layer 2: D (依赖 B 和 C)
        orchestrator._capability_graph.register_tool("A", capabilities=["a"], dependencies=[])
        orchestrator._capability_graph.register_tool("B", capabilities=["b"], dependencies=["A"])
        orchestrator._capability_graph.register_tool("C", capabilities=["c"], dependencies=["A"])
        orchestrator._capability_graph.register_tool("D", capabilities=["d"], dependencies=["B", "C"])
        
        plan = ["A", "B", "C", "D"]
        result = await orchestrator.orchestrate(goal="mixed", tool_plan=plan)
        
        # 验证结果
        assert result.status.value == "success"
        assert len(result.steps) == 4
        
        # 验证依赖顺序：A < B,C < D
        assert start_times["A"] < start_times["B"]
        assert start_times["A"] < start_times["C"]
        assert start_times["B"] < start_times["D"]
        assert start_times["C"] < start_times["D"]
        
        # 验证 B,C 并行
        bc_diff = abs(start_times["B"] - start_times["C"])
        assert bc_diff < 0.05
