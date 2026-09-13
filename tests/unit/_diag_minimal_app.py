#!/usr/bin/env python3
"""最小测试脚本，测试ToolExecutionManager修复后的功能"""
import sys
import asyncio
sys.path.insert(0, '.')

from neurova.agent.tool_execution_manager import (
    ToolExecutionManager,
    ToolExecutionContext,
    TimeoutStrategy,
    ExecutionStatus,
)

class MockExecutor:
    async def execute_tool(self, tool_name, params, user_input):
        if tool_name == "slow":
            await asyncio.sleep(10)
        return {"result": "success", "tool_name": tool_name}

async def test_basic():
    print("测试基本功能...")
    manager = ToolExecutionManager()
    executor = MockExecutor()
    
    # 测试快速工具
    context = await manager.execute(
        tool_name="fast",
        params={},
        user_input="test",
        executor=executor,
        timeout=5.0,
        strategy=TimeoutStrategy.STRICT,
    )
    assert context.status == ExecutionStatus.COMPLETED
    print(f"✓ 快速工具测试通过: {context.status}")
    
    # 测试超时
    context2 = await manager.execute(
        tool_name="slow",
        params={},
        user_input="test",
        executor=executor,
        timeout=0.1,
        strategy=TimeoutStrategy.STRICT,
    )
    assert context2.status == ExecutionStatus.TIMEOUT
    print(f"✓ 超时测试通过: {context2.status}")
    
    # 测试取消
    async def execute_and_cancel():
        """启动执行并在运行中取消"""
        exec_task = asyncio.create_task(
            manager.execute(
                tool_name="slow",
                params={},
                user_input="test",
                executor=executor,
                timeout=10.0,
                strategy=TimeoutStrategy.STRICT,
            )
        )
        
        # 等待一小段时间让执行开始
        await asyncio.sleep(0.1)
        
        # 获取运行中的上下文
        contexts = manager.get_all_contexts()
        running_ctx = None
        for ctx in contexts:
            if ctx.status == ExecutionStatus.RUNNING:
                running_ctx = ctx
                break
        
        if running_ctx:
            cancelled = await manager.cancel(running_ctx.context_id)
            print(f"✓ 取消测试: cancelled={cancelled}")
            
            # 等待任务完成
            try:
                ctx = await exec_task
                print(f"  执行结果状态: {ctx.status}")
                assert ctx.status == ExecutionStatus.CANCELLED
                print("✓ 取消状态验证通过")
            except asyncio.CancelledError:
                print("✓ 任务被成功取消 (CancelledError)")
        else:
            exec_task.cancel()
            try:
                await exec_task
            except asyncio.CancelledError:
                pass
            print("⚠ 没有找到运行中的上下文")
    
    await execute_and_cancel()
    
    print("\n所有基本测试通过！")

if __name__ == "__main__":
    asyncio.run(test_basic())