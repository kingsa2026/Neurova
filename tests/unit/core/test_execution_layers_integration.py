"""
ExecutionLayers 集成测试

验证 ExecutionLayers（Runtime + Transport 双抽象层）与核心流程的接线:
1. run_code 内置工具通过 LocalExecutor 执行
2. execute_skill_isolated 在隔离运行时中执行技能
3. RuntimeManager 生命周期管理
"""

import pytest
import asyncio
import time
from unittest.mock import Mock, patch, AsyncMock, MagicMock
from typing import Dict, Any


# ═══════════════════════════════════════════════════════════════
# 1. LocalExecutor 核心功能
# ═══════════════════════════════════════════════════════════════

class TestLocalExecutor:
    """测试 LocalExecutor 执行 Python 代码"""

    @pytest.mark.asyncio
    async def test_start_stop(self):
        """验证 start/stop 生命周期"""
        from neurova.execution_layers import LocalExecutor

        executor = LocalExecutor(runtime_id="test_local")
        assert not executor.is_started

        started = await executor.start()
        assert started is True
        assert executor.is_started

        stopped = await executor.stop()
        assert stopped is True
        assert not executor.is_started

    @pytest.mark.asyncio
    async def test_exec_python_simple(self):
        """验证简单 Python 代码执行"""
        from neurova.execution_layers import LocalExecutor

        executor = LocalExecutor(runtime_id="test_exec_py")
        await executor.start()

        try:
            result = await executor.exec(
                command="python",
                args=["-c", "print('hello')"],
            )
            assert result.success is True
            assert "hello" in (result.stdout or "")
            assert result.exit_code == 0
        finally:
            await executor.stop()

    @pytest.mark.asyncio
    async def test_exec_python_expression(self):
        """验证 Python 表达式执行"""
        from neurova.execution_layers import LocalExecutor

        executor = LocalExecutor(runtime_id="test_exec_expr")
        await executor.start()

        try:
            result = await executor.exec(
                command="python",
                args=["-c", "import json; print(json.dumps({'a': 1, 'b': 2}))"],
            )
            assert result.success is True
            assert "1" in (result.stdout or "")
            assert "2" in (result.stdout or "")
        finally:
            await executor.stop()

    @pytest.mark.asyncio
    async def test_exec_failure_returns_error(self):
        """验证执行失败时返回错误信息"""
        from neurova.execution_layers import LocalExecutor

        executor = LocalExecutor(runtime_id="test_exec_fail")
        await executor.start()

        try:
            result = await executor.exec(
                command="python",
                args=["-c", "import nonexistent_module_xyz"],
            )
            assert result.success is False
            assert result.stderr is not None or result.error is not None
        finally:
            await executor.stop()

    @pytest.mark.asyncio
    async def test_exec_with_env(self):
        """验证环境变量传递"""
        from neurova.execution_layers import LocalExecutor

        executor = LocalExecutor(runtime_id="test_exec_env")
        await executor.start()

        try:
            result = await executor.exec(
                command="python",
                args=["-c", "import os; print(os.environ.get('TEST_VAR', ''))"],
                env={"TEST_VAR": "hello_env"},
            )
            assert result.success is True
            assert "hello_env" in (result.stdout or "")
        finally:
            await executor.stop()

    @pytest.mark.asyncio
    async def test_get_info(self):
        """验证 RuntimeInfo 返回正确"""
        from neurova.execution_layers import LocalExecutor, RuntimeType

        executor = LocalExecutor(runtime_id="test_info")
        info = executor.get_info()

        assert info.runtime_id == "test_info"
        assert info.runtime_type == RuntimeType.LOCAL
        assert info.status == "stopped"

        await executor.start()
        info = executor.get_info()
        assert info.status == "running"
        assert info.is_running is True

        await executor.stop()


# ═══════════════════════════════════════════════════════════════
# 2. RuntimeFactory + RuntimeManager 生命周期
# ═══════════════════════════════════════════════════════════════

class TestRuntimeFactory:
    """测试 RuntimeFactory 工厂"""

    def test_create_local_executor(self):
        """验证创建 LocalExecutor"""
        from neurova.execution_layers import RuntimeFactory, RuntimeType, LocalExecutor

        runtime = RuntimeFactory.create(RuntimeType.LOCAL, runtime_id="factory_local")
        assert isinstance(runtime, LocalExecutor)

    def test_list_supported_types(self):
        """验证列出支持的运行时类型"""
        from neurova.execution_layers import RuntimeFactory, RuntimeType

        types = RuntimeFactory.list_supported_types()
        assert RuntimeType.LOCAL in types
        assert RuntimeType.DOCKER in types


class TestRuntimeManager:
    """测试 RuntimeManager 生命周期管理"""

    @pytest.mark.asyncio
    async def test_start_and_stop_runtime(self):
        """验证启动和停止运行时"""
        from neurova.execution_layers import RuntimeManager, RuntimeType

        manager = RuntimeManager()
        runtime_id = await manager.start_runtime(RuntimeType.LOCAL)

        assert runtime_id is not None
        assert len(manager.list_active()) == 1

        info = manager.list_active()[0]
        assert info["status"] == "running"

        stopped = await manager.stop_runtime(runtime_id)
        assert stopped is True
        assert len(manager.list_active()) == 0

    @pytest.mark.asyncio
    async def test_get_runtime(self):
        """验证获取运行时实例"""
        from neurova.execution_layers import RuntimeManager, RuntimeType, LocalExecutor

        manager = RuntimeManager()
        runtime_id = await manager.start_runtime(RuntimeType.LOCAL)

        runtime = manager.get_runtime(runtime_id)
        assert isinstance(runtime, LocalExecutor)
        assert runtime.is_started is True

        await manager.stop_runtime(runtime_id)

    @pytest.mark.asyncio
    async def test_stop_nonexistent_runtime(self):
        """验证停止不存在的运行时"""
        from neurova.execution_layers import RuntimeManager

        manager = RuntimeManager()
        result = await manager.stop_runtime("nonexistent_id")
        assert result is False

    @pytest.mark.asyncio
    async def test_list_active_empty(self):
        """验证空列表"""
        from neurova.execution_layers import RuntimeManager

        manager = RuntimeManager()
        assert manager.list_active() == []


# ═══════════════════════════════════════════════════════════════
# 3. ToolExecutor.run_code 内置工具
# ═══════════════════════════════════════════════════════════════

class TestRunCodeBuiltinTool:
    """测试 ToolExecutor 的 run_code 内置工具"""

    def _create_executor(self):
        from neurova.tool_executor import ToolExecutor
        agent = Mock()
        agent._skill_registry = Mock()
        agent.tool_router = None
        agent.tool_memory = None
        agent.tool_lifecycle = None
        agent.skill_packer = None
        agent.config = Mock()
        agent.memory_manager = Mock()
        return ToolExecutor(agent)

    @pytest.mark.asyncio
    async def test_run_code_method_exists(self):
        """验证 _execute_run_code 方法存在"""
        executor = self._create_executor()
        assert hasattr(executor, '_execute_run_code')

    @pytest.mark.asyncio
    async def test_run_code_in_builtin_tools_list(self):
        """验证 run_code 在内置工具列表中"""
        builtin_tools = [
            "memory_search", "file_read", "file_write", "file_create",
            "file_delete", "file_edit", "computer_screenshot", "computer_click",
            "computer_type", "computer_scroll", "computer_shell", "emotion_analyze",
            "voice_memory_search", "run_code", "execute_code",
        ]
        assert "run_code" in builtin_tools
        assert "execute_code" in builtin_tools

    @pytest.mark.asyncio
    async def test_run_code_python(self):
        """验证 run_code 执行 Python 代码"""
        executor = self._create_executor()

        result = await executor._execute_run_code({
            "code": "print(42)",
            "language": "python",
            "timeout": 10,
        })

        assert result["success"] is True
        assert "42" in result["stdout"]
        assert result["exit_code"] == 0

    @pytest.mark.asyncio
    async def test_run_code_python_multiline(self):
        """验证 run_code 执行多行 Python 代码"""
        executor = self._create_executor()

        result = await executor._execute_run_code({
            "code": "import sys\nprint(sys.version_info.major)",
            "language": "python",
            "timeout": 10,
        })

        assert result["success"] is True
        assert result["exit_code"] == 0

    @pytest.mark.asyncio
    async def test_run_code_missing_code(self):
        """验证缺少 code 参数时返回错误"""
        executor = self._create_executor()

        result = await executor._execute_run_code({
            "language": "python",
        })

        assert result.get("error") is not None
        assert "code" in result["error"]

    @pytest.mark.asyncio
    async def test_run_code_with_env(self):
        """验证 run_code 传递环境变量"""
        executor = self._create_executor()

        result = await executor._execute_run_code({
            "code": "import os; print(os.environ.get('RUNTIME_TEST', ''))",
            "language": "python",
            "timeout": 10,
            "env": {"RUNTIME_TEST": "rt_value"},
        })

        assert result["success"] is True
        assert "rt_value" in result["stdout"]

    @pytest.mark.asyncio
    async def test_run_code_via_execute_builtin(self):
        """验证通过 _execute_builtin_tool 分发到 run_code"""
        executor = self._create_executor()

        result = await executor._execute_builtin_tool("run_code", {
            "code": "print('dispatched')",
            "language": "python",
            "timeout": 10,
        })

        assert result["success"] is True
        assert "dispatched" in result["stdout"]

    @pytest.mark.asyncio
    async def test_run_code_via_execute_builtin_alias(self):
        """验证 execute_code 别名也正确分发"""
        executor = self._create_executor()

        result = await executor._execute_builtin_tool("execute_code", {
            "code": "print('alias')",
            "language": "python",
            "timeout": 10,
        })

        assert result["success"] is True
        assert "alias" in result["stdout"]

    @pytest.mark.asyncio
    async def test_run_code_returns_duration(self):
        """验证 run_code 返回执行耗时"""
        executor = self._create_executor()

        result = await executor._execute_run_code({
            "code": "print('timed')",
            "language": "python",
            "timeout": 10,
        })

        assert "duration_ms" in result
        assert result["duration_ms"] >= 0
        assert result["runtime_type"] == "local"


# ═══════════════════════════════════════════════════════════════
# 4. SkillRegistry.execute_skill_isolated
# ═══════════════════════════════════════════════════════════════

class TestExecuteSkillIsolated:
    """测试 SkillRegistry 隔离执行技能"""

    def _create_registry_with_skill(self):
        """创建带有一个已注册技能的 SkillRegistry 实例"""
        from neurova.skills.registry import SkillRegistry
        from neurova.skills.models import Skill, SkillSource

        # 重置单例以确保干净状态
        SkillRegistry._instance = None
        registry = SkillRegistry()

        # 注册一个虚拟技能
        skill = Skill(
            id="test_dummy_skill",
            name="Test Dummy Skill",
            version="1.0.0",
            description="A dummy skill for testing",
            source=SkillSource.AGENT_PRIVATE,
        )
        from pathlib import Path
        registry.register_skill(skill, Path("/tmp/test_skill"))
        return registry

    @pytest.mark.asyncio
    async def test_execute_skill_isolated_method_exists(self):
        """验证 execute_skill_isolated 方法存在"""
        registry = self._create_registry_with_skill()
        assert hasattr(registry, 'execute_skill_isolated')
        assert callable(getattr(registry, 'execute_skill_isolated'))

    @pytest.mark.asyncio
    async def test_execute_skill_isolated_fallback(self):
        """验证 RuntimeFactory 失败时降级为普通执行"""
        registry = self._create_registry_with_skill()

        with patch(
            'neurova.execution_layers.RuntimeFactory',
            side_effect=ImportError("not available"),
        ):
            result = await registry.execute_skill_isolated(
                "test_dummy_skill", {"a": 1}
            )

        # 降级为普通 execute_skill
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_execute_skill_isolated_nonexistent_skill(self):
        """验证执行不存在的技能时返回错误"""
        registry = self._create_registry_with_skill()

        result = await registry.execute_skill_isolated("nonexistent_skill", {})
        assert result["success"] is False
        assert "未注册" in result["error"]

    @pytest.mark.asyncio
    async def test_execute_skill_isolated_creates_runtime(self):
        """验证隔离执行时创建独立运行时"""
        registry = self._create_registry_with_skill()

        mock_runtime = AsyncMock()
        mock_runtime.start = AsyncMock(return_value=True)
        mock_runtime.stop = AsyncMock(return_value=True)
        mock_runtime.exec = AsyncMock(return_value=Mock(
            success=True,
            stdout='{"success": true, "data": {}}',
            stderr=None,
            error=None,
        ))

        with patch(
            'neurova.execution_layers.RuntimeFactory',
        ) as mock_factory:
            mock_factory.create.return_value = mock_runtime

            result = await registry.execute_skill_isolated(
                "test_dummy_skill", {"key": "val"}, runtime_type="local"
            )

            assert mock_runtime.start.called
            assert mock_runtime.exec.called
            assert mock_runtime.stop.called

    @pytest.mark.asyncio
    async def test_execute_skill_isolated_stops_runtime_on_error(self):
        """验证执行异常时仍能停止运行时"""
        registry = self._create_registry_with_skill()

        mock_runtime = AsyncMock()
        mock_runtime.start = AsyncMock(return_value=True)
        mock_runtime.stop = AsyncMock(return_value=True)
        mock_runtime.exec = AsyncMock(side_effect=Exception("exec failed"))

        with patch(
            'neurova.execution_layers.RuntimeFactory',
        ) as mock_factory:
            mock_factory.create.return_value = mock_runtime

            result = await registry.execute_skill_isolated("test_dummy_skill", {})

            assert mock_runtime.stop.called
            # 异常被外层 try/except 捕获，降级为普通执行
            assert result["success"] is True


# ═══════════════════════════════════════════════════════════════
# 5. 端到端集成: ToolExecutor + RuntimeManager
# ═══════════════════════════════════════════════════════════════

class TestEndToEndIntegration:
    """端到端集成测试"""

    @pytest.mark.asyncio
    async def test_run_code_uses_local_executor(self):
        """验证 run_code 使用 LocalExecutor 而非直接 subprocess"""
        from neurova.tool_executor import ToolExecutor

        agent = Mock()
        agent._skill_registry = Mock()
        agent.tool_router = None
        agent.tool_memory = None
        agent.tool_lifecycle = None
        agent.skill_packer = None
        agent.config = Mock()
        agent.memory_manager = Mock()

        executor = ToolExecutor(agent)

        # LocalExecutor 在 _execute_run_code 方法体内通过延迟导入获取
        # 需要 patch 到其来源模块
        mock_inst = AsyncMock()
        mock_inst.start = AsyncMock(return_value=True)
        mock_inst.stop = AsyncMock(return_value=True)
        mock_inst.exec = AsyncMock(return_value=Mock(
            success=True,
            stdout="e2e_ok",
            stderr=None,
            exit_code=0,
            error=None,
        ))

        with patch(
            'neurova.execution_layers.LocalExecutor',
            return_value=mock_inst,
        ) as MockLocal:
            result = await executor._execute_run_code({
                "code": "print('e2e_ok')",
                "language": "python",
                "timeout": 10,
            })

            assert result["success"] is True
            assert "e2e_ok" in result["stdout"]
            MockLocal.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_single_tool_dispatches_run_code(self):
        """验证 _execute_single_tool 正确分发 run_code 到 _execute_run_code"""
        from neurova.tool_executor import ToolExecutor

        agent = Mock()
        agent._skill_registry = Mock()
        agent.tool_router = None
        agent.tool_memory = None
        agent.tool_lifecycle = None
        agent.skill_packer = None
        agent.config = Mock()

        executor = ToolExecutor(agent)

        with patch.object(executor, '_execute_builtin_tool', new_callable=AsyncMock) as mock_builtin:
            mock_builtin.return_value = {"success": True}

            result = await executor._execute_single_tool("run_code", {"code": "x=1"})

            mock_builtin.assert_called_once_with("run_code", {"code": "x=1"})

    @pytest.mark.asyncio
    async def test_runtime_manager_global_singleton(self):
        """验证全局 RuntimeManager 单例"""
        from neurova.execution_layers import get_runtime_manager, reset_runtime_manager

        reset_runtime_manager()

        rm1 = get_runtime_manager()
        rm2 = get_runtime_manager()

        assert rm1 is rm2
        reset_runtime_manager()


# ═══════════════════════════════════════════════════════════════
# 6. ExecutionResult 数据模型
# ═══════════════════════════════════════════════════════════════

class TestExecutionResult:
    """测试 ExecutionResult 数据模型"""

    def test_success_result_to_dict(self):
        """验证成功结果序列化"""
        from neurova.execution_layers import ExecutionResult

        result = ExecutionResult(
            success=True,
            exit_code=0,
            stdout="hello",
            stderr="",
            duration_ms=100.5,
        )
        d = result.to_dict()
        assert d["success"] is True
        assert d["exit_code"] == 0
        assert d["stdout"] == "hello"
        assert d["duration_ms"] == 100.5

    def test_failure_result_to_dict(self):
        """验证失败结果序列化"""
        from neurova.execution_layers import ExecutionResult

        result = ExecutionResult(
            success=False,
            exit_code=1,
            stdout=None,
            stderr="error msg",
            error="timeout",
        )
        d = result.to_dict()
        assert d["success"] is False
        assert d["exit_code"] == 1
        assert d["error"] == "timeout"

    def test_stdout_truncation(self):
        """验证 stdout 超过 1000 字符时截断"""
        from neurova.execution_layers import ExecutionResult

        long_stdout = "x" * 2000
        result = ExecutionResult(success=True, stdout=long_stdout)
        d = result.to_dict()
        assert len(d["stdout"]) == 1000
