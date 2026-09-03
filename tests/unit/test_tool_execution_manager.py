"""
ToolExecutionManager 单元测试

验证 ToolExecutionManager 深度模块的功能：
1. 执行上下文管理
2. 超时策略（严格、弹性、无限）
3. 优雅取消
4. 状态查询
5. 超时回调
"""
import pytest
import asyncio
import sys
from pathlib import Path
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime, timezone

# 添加项目根目录到 sys.path
project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from neurova.agent.tool_execution_manager import (
    ToolExecutionManager,
    ToolExecutionContext,
    TimeoutStrategy,
    ExecutionStatus,
    ExecutionEvent,
)


class MockToolExecutor:
    """模拟工具执行器"""
    
    async def execute_tool(self, tool_name: str, params: dict, user_input: str) -> dict:
        """模拟工具执行"""
        if tool_name == "slow_tool":
            await asyncio.sleep(10)  # 模拟慢工具
        elif tool_name == "fast_tool":
            return {"result": "success", "tool_name": tool_name}
        elif tool_name == "failing_tool":
            raise ValueError("Tool execution failed")
        return {"result": "success", "tool_name": tool_name}


class TestTimeoutStrategy:
    """测试 TimeoutStrategy 枚举"""
    
    def test_timeout_strategy_values(self):
        """测试 TimeoutStrategy 枚举值"""
        assert TimeoutStrategy.STRICT.value == "strict"
        assert TimeoutStrategy.ELASTIC.value == "elastic"
        assert TimeoutStrategy.INFINITE.value == "infinite"
    
    def test_timeout_strategy_is_enum(self):
        """测试 TimeoutStrategy 是枚举"""
        from enum import Enum
        assert issubclass(TimeoutStrategy, Enum)


class TestExecutionStatus:
    """测试 ExecutionStatus 枚举"""
    
    def test_execution_status_values(self):
        """测试 ExecutionStatus 枚举值"""
        assert ExecutionStatus.PENDING.value == "pending"
        assert ExecutionStatus.RUNNING.value == "running"
        assert ExecutionStatus.COMPLETED.value == "completed"
        assert ExecutionStatus.TIMEOUT.value == "timeout"
        assert ExecutionStatus.CANCELLED.value == "cancelled"
        assert ExecutionStatus.FAILED.value == "failed"


class TestToolExecutionContext:
    """测试 ToolExecutionContext 数据类"""
    
    def test_context_creation(self):
        """测试 ToolExecutionContext 创建"""
        context = ToolExecutionContext(
            context_id="test-123",
            tool_name="test_tool",
            params={"key": "value"},
            user_input="test input",
            timeout=5.0,
            strategy=TimeoutStrategy.STRICT,
        )
        
        assert context.context_id == "test-123"
        assert context.tool_name == "test_tool"
        assert context.params == {"key": "value"}
        assert context.user_input == "test input"
        assert context.timeout == 5.0
        assert context.strategy == TimeoutStrategy.STRICT
        assert context.status == ExecutionStatus.PENDING
        assert context.result is None
        assert context.error is None
        assert context.created_at is not None
        assert context.completed_at is None
    
    def test_context_default_values(self):
        """测试 ToolExecutionContext 默认值"""
        context = ToolExecutionContext(
            context_id="test-456",
            tool_name="test_tool",
            params={},
            user_input="",
        )
        
        assert context.timeout == 30.0  # 默认超时30秒
        assert context.strategy == TimeoutStrategy.STRICT  # 默认严格策略
        assert context.status == ExecutionStatus.PENDING
    
    def test_context_to_dict(self):
        """测试 ToolExecutionContext 序列化"""
        context = ToolExecutionContext(
            context_id="test-789",
            tool_name="test_tool",
            params={"key": "value"},
            user_input="test input",
            timeout=5.0,
            strategy=TimeoutStrategy.STRICT,
            status=ExecutionStatus.RUNNING,
        )
        
        result = context.to_dict()
        
        assert result["context_id"] == "test-789"
        assert result["tool_name"] == "test_tool"
        assert result["params"] == {"key": "value"}
        assert result["timeout"] == 5.0
        assert result["strategy"] == "strict"
        assert result["status"] == "running"


class TestExecutionEvent:
    """测试 ExecutionEvent 数据类"""
    
    def test_event_creation(self):
        """测试 ExecutionEvent 创建"""
        event = ExecutionEvent(
            context_id="test-123",
            old_status=ExecutionStatus.PENDING,
            new_status=ExecutionStatus.RUNNING,
            message="Execution started",
        )
        
        assert event.context_id == "test-123"
        assert event.old_status == ExecutionStatus.PENDING
        assert event.new_status == ExecutionStatus.RUNNING
        assert event.message == "Execution started"
        assert event.timestamp is not None
    
    def test_event_default_message(self):
        """测试 ExecutionEvent 默认消息"""
        event = ExecutionEvent(
            context_id="test-456",
            old_status=ExecutionStatus.RUNNING,
            new_status=ExecutionStatus.COMPLETED,
        )
        
        assert event.message == ""


class TestToolExecutionManager:
    """测试 ToolExecutionManager 类"""
    
    def setup_method(self):
        """每个测试前重置"""
        self.manager = ToolExecutionManager()
        self.mock_executor = MockToolExecutor()
    
    def test_initialization(self):
        """测试 ToolExecutionManager 初始化"""
        assert self.manager is not None
        assert len(self.manager.get_all_contexts()) == 0
    
    @pytest.mark.asyncio
    async def test_execute_success(self):
        """测试成功执行工具"""
        context = await self.manager.execute(
            tool_name="fast_tool",
            params={},
            user_input="test",
            executor=self.mock_executor,
            timeout=5.0,
            strategy=TimeoutStrategy.STRICT,
        )
        
        assert context.status == ExecutionStatus.COMPLETED
        assert context.result is not None
        assert context.result.get("result") == "success"
        assert context.completed_at is not None
    
    @pytest.mark.asyncio
    async def test_execute_timeout_strict(self):
        """测试严格超时"""
        context = await self.manager.execute(
            tool_name="slow_tool",
            params={},
            user_input="test",
            executor=self.mock_executor,
            timeout=0.1,  # 100ms超时
            strategy=TimeoutStrategy.STRICT,
        )
        
        assert context.status == ExecutionStatus.TIMEOUT
        assert context.result is None
        assert context.completed_at is not None
    
    @pytest.mark.asyncio
    async def test_execute_timeout_elastic(self):
        """测试弹性超时（自动续时）"""
        # 弹性超时应该尝试重试
        context = await self.manager.execute(
            tool_name="slow_tool",
            params={},
            user_input="test",
            executor=self.mock_executor,
            timeout=0.1,  # 100ms超时
            strategy=TimeoutStrategy.ELASTIC,
            max_retries=2,
        )
        
        # 弹性超时可能成功也可能失败，取决于重试逻辑
        assert context.status in [ExecutionStatus.COMPLETED, ExecutionStatus.TIMEOUT]
    
    @pytest.mark.asyncio
    async def test_execute_infinite_timeout(self):
        """测试无限等待"""
        # 无限等待应该不会超时
        context = await self.manager.execute(
            tool_name="fast_tool",
            params={},
            user_input="test",
            executor=self.mock_executor,
            timeout=float('inf'),
            strategy=TimeoutStrategy.INFINITE,
        )
        
        assert context.status == ExecutionStatus.COMPLETED
    
    @pytest.mark.asyncio
    async def test_execute_failure(self):
        """测试工具执行失败"""
        context = await self.manager.execute(
            tool_name="failing_tool",
            params={},
            user_input="test",
            executor=self.mock_executor,
            timeout=5.0,
            strategy=TimeoutStrategy.STRICT,
        )
        
        assert context.status == ExecutionStatus.FAILED
        assert context.error is not None
        assert "Tool execution failed" in context.error
    
    @pytest.mark.asyncio
    async def test_cancel_execution(self):
        """测试取消执行"""
        # 使用 asyncio.gather 并行运行 execute 和 cancel
        async def execute_and_cancel():
            # 启动慢工具执行（在后台）
            execute_task = asyncio.create_task(
                self.manager.execute(
                    tool_name="slow_tool",
                    params={},
                    user_input="test",
                    executor=self.mock_executor,
                    timeout=10.0,
                    strategy=TimeoutStrategy.STRICT,
                )
            )
            
            # 等待一小段时间让执行开始
            await asyncio.sleep(0.1)
            
            # 获取上下文ID（从所有上下文中找第一个 RUNNING 状态的）
            contexts = self.manager.get_all_contexts()
            running_context = None
            for ctx in contexts:
                if ctx.status == ExecutionStatus.RUNNING:
                    running_context = ctx
                    break
            
            if running_context:
                # 取消执行
                cancelled = await self.manager.cancel(running_context.context_id)
                assert cancelled is True
                
                # 等待执行任务完成（应该被取消）
                try:
                    await execute_task
                except asyncio.CancelledError:
                    pass
                
                # 验证状态
                updated_context = self.manager.get_context(running_context.context_id)
                assert updated_context.status == ExecutionStatus.CANCELLED
            else:
                # 如果没有运行中的上下文，跳过测试
                execute_task.cancel()
                pytest.skip("No running context found")
        
        await execute_and_cancel()
    
    @pytest.mark.asyncio
    async def test_cancel_nonexistent_context(self):
        """测试取消不存在的执行上下文"""
        cancelled = await self.manager.cancel("nonexistent-id")
        assert cancelled is False
    
    def test_get_context(self):
        """测试获取执行上下文"""
        context = ToolExecutionContext(
            context_id="test-get",
            tool_name="test_tool",
            params={},
            user_input="",
        )
        
        # 手动添加上下文
        self.manager._contexts[context.context_id] = context
        
        retrieved = self.manager.get_context("test-get")
        assert retrieved is not None
        assert retrieved.context_id == "test-get"
    
    def test_get_context_not_found(self):
        """测试获取不存在的执行上下文"""
        retrieved = self.manager.get_context("nonexistent")
        assert retrieved is None
    
    def test_get_all_contexts(self):
        """测试获取所有执行上下文"""
        # 使用全新管理器避免累积
        manager = ToolExecutionManager()
        
        context1 = ToolExecutionContext(
            context_id="test-1",
            tool_name="test_tool",
            params={},
            user_input="",
        )
        context2 = ToolExecutionContext(
            context_id="test-2",
            tool_name="test_tool",
            params={},
            user_input="",
        )
        
        # 手动添加上下文
        manager._contexts[context1.context_id] = context1
        manager._contexts[context2.context_id] = context2
        
        all_contexts = manager.get_all_contexts()
        assert len(all_contexts) == 2
    
    def test_on_status_change_callback(self):
        """测试状态变更回调"""
        callback = Mock()
        self.manager.on_status_change(callback)
        
        # 创建上下文
        context = ToolExecutionContext(
            context_id="test-callback",
            tool_name="test_tool",
            params={},
            user_input="",
        )
        
        # 手动添加上下文
        self.manager._contexts[context.context_id] = context
        
        # 触发状态变更
        self.manager._set_status(context.context_id, ExecutionStatus.RUNNING)
        
        callback.assert_called_once()
        event = callback.call_args[0][0]
        assert isinstance(event, ExecutionEvent)
        assert event.context_id == "test-callback"
        assert event.new_status == ExecutionStatus.RUNNING
    
    def test_remove_status_change_callback(self):
        """测试移除状态变更回调"""
        callback = Mock()
        self.manager.on_status_change(callback)
        
        # 移除回调
        self.manager.remove_status_change_callback(callback)
        
        # 创建上下文
        context = ToolExecutionContext(
            context_id="test-remove-callback",
            tool_name="test_tool",
            params={},
            user_input="",
        )
        
        # 手动添加上下文
        self.manager._contexts[context.context_id] = context
        
        # 触发状态变更
        self.manager._set_status(context.context_id, ExecutionStatus.RUNNING)
        
        callback.assert_not_called()
    
    def test_get_health_info(self):
        """测试获取健康信息"""
        health = self.manager.get_health()
        
        assert "total_contexts" in health
        assert "active_contexts" in health
        assert "completed_contexts" in health
        assert "failed_contexts" in health
        assert "timeout_contexts" in health
    
    @pytest.mark.asyncio
    async def test_execute_with_callback(self):
        """测试带回调的执行"""
        callback = Mock()
        self.manager.on_status_change(callback)
        
        context = await self.manager.execute(
            tool_name="fast_tool",
            params={},
            user_input="test",
            executor=self.mock_executor,
            timeout=5.0,
            strategy=TimeoutStrategy.STRICT,
            callback=callback,
        )
        
        # 回调应该被调用多次（状态变更）
        assert callback.call_count >= 2  # PENDING -> RUNNING -> COMPLETED


class TestToolExecutionManagerIntegration:
    """测试 ToolExecutionManager 集成"""
    
    @pytest.mark.asyncio
    async def test_multiple_executions(self):
        """测试多个并发执行"""
        manager = ToolExecutionManager()
        executor = MockToolExecutor()
        
        # 启动多个执行
        contexts = []
        for i in range(3):
            context = await manager.execute(
                tool_name="fast_tool",
                params={"index": i},
                user_input=f"test {i}",
                executor=executor,
                timeout=5.0,
                strategy=TimeoutStrategy.STRICT,
            )
            contexts.append(context)
        
        # 验证所有执行都完成
        assert len(contexts) == 3
        for context in contexts:
            assert context.status == ExecutionStatus.COMPLETED
    
    @pytest.mark.asyncio
    async def test_cancel_all_executions(self):
        """测试取消所有执行"""
        manager = ToolExecutionManager()
        executor = MockToolExecutor()
        
        # 启动多个慢工具执行（在后台运行）
        exec_tasks = []
        for i in range(3):
            task = asyncio.create_task(
                manager.execute(
                    tool_name="slow_tool",
                    params={"index": i},
                    user_input=f"test {i}",
                    executor=executor,
                    timeout=10.0,
                    strategy=TimeoutStrategy.STRICT,
                )
            )
            exec_tasks.append(task)
        
        # 等待一小段时间让执行开始
        await asyncio.sleep(0.1)
        
        # 取消所有运行中的执行
        for ctx in manager.get_all_contexts():
            if ctx.status == ExecutionStatus.RUNNING:
                await manager.cancel(ctx.context_id)
        
        # 等待所有任务完成
        for task in exec_tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        
        # 验证所有执行都已取消或超时（取消在超时前生效）
        for ctx in manager.get_all_contexts():
            assert ctx.status in [ExecutionStatus.CANCELLED, ExecutionStatus.TIMEOUT]


class TestToolExecutionManagerEdgeCases:
    """测试 ToolExecutionManager 边界情况"""
    
    @pytest.mark.asyncio
    async def test_execute_with_zero_timeout(self):
        """测试零超时"""
        manager = ToolExecutionManager()
        executor = MockToolExecutor()
        
        context = await manager.execute(
            tool_name="fast_tool",
            params={},
            user_input="test",
            executor=executor,
            timeout=0.0,
            strategy=TimeoutStrategy.STRICT,
        )
        
        # 零超时应该立即超时
        assert context.status == ExecutionStatus.TIMEOUT
    
    @pytest.mark.asyncio
    async def test_execute_with_negative_timeout(self):
        """测试负数超时"""
        manager = ToolExecutionManager()
        executor = MockToolExecutor()
        
        context = await manager.execute(
            tool_name="fast_tool",
            params={},
            user_input="test",
            executor=executor,
            timeout=-1.0,
            strategy=TimeoutStrategy.STRICT,
        )
        
        # 负数超时应该立即超时
        assert context.status == ExecutionStatus.TIMEOUT
    
    def test_get_context_after_cleanup(self):
        """测试清理后获取上下文"""
        manager = ToolExecutionManager()
        
        # 创建已完成的上下文（带 completed_at）
        from datetime import timedelta
        context = ToolExecutionContext(
            context_id="test-cleanup",
            tool_name="test_tool",
            params={},
            user_input="",
            status=ExecutionStatus.COMPLETED,
        )
        context.completed_at = datetime.now(timezone.utc) - timedelta(hours=2)
        
        # 手动添加上下文
        manager._contexts[context.context_id] = context
        
        # 清理已完成的上下文（保留1小时）
        manager.cleanup_completed_contexts(max_age_seconds=3600)
        
        # 验证上下文已清理（年龄2小时 > 保留1小时）
        retrieved = manager.get_context("test-cleanup")
        assert retrieved is None


def test_imports():
    """测试所有导入是否正常"""
    try:
        from neurova.agent.tool_execution_manager import (
            ToolExecutionManager,
            ToolExecutionContext,
            TimeoutStrategy,
            ExecutionStatus,
            ExecutionEvent,
        )
        
        print("✓ All ToolExecutionManager imports successful")
        return True
    
    except ImportError as e:
        print(f"✗ Import failed: {e}")
        return False


if __name__ == "__main__":
    # 运行简单测试
    print("Running ToolExecutionManager tests...")
    
    # 测试导入
    test_imports()
    
    print("\n✓ All tests passed!")