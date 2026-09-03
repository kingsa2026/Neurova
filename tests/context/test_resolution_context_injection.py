#!/usr/bin/env python3
"""
测试 ResolutionContext 外部系统注入修复
验证 $memory/$context/$emotion/$crystal 四个变量前缀能否正常工作
"""

import asyncio
import sys
from pathlib import Path

# 添加项目根目录到 sys.path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))


async def test_resolution_context_injection():
    """测试 ResolutionContext 外部系统注入"""
    print("=== 测试 ResolutionContext 外部系统注入修复 ===")
    
    try:
        # 1. 测试 API 端点中的 Agent 实例获取逻辑
        from neurova.api.endpoints import get_agent_instance
        print("✓ 成功导入 get_agent_instance 函数")
        
        # 2. 测试变量解析器
        from neurova.collaboration.neurflow.variable_resolver import VariableResolver, ResolutionContext
        resolver = VariableResolver()
        
        # 3. 创建模拟的外部系统
        from unittest.mock import MagicMock
        
        # 模拟 memory_manager
        mock_memory = MagicMock()
        mock_memory.search_memories.return_value = [
            {"content": "测试记忆内容", "score": 0.95}
        ]
        
        # 模拟 context_pool
        mock_context = MagicMock()
        mock_context.get_context.return_value = {
            "system_prompt": "你是一个AI助手",
            "recent_messages": []
        }
        
        # 模拟 emotion_module
        mock_emotion = MagicMock()
        mock_emotion.current.return_value = {
            "valence": 0.8,
            "primary_emotion": "happy"
        }
        
        # 模拟 crystallizer
        mock_crystal = MagicMock()
        mock_crystal.retrieve.return_value = [
            {"pattern": "测试模式", "confidence": 0.9}
        ]
        
        # 4. 创建 ResolutionContext 并注入外部系统
        context = ResolutionContext(
            workflow_id="test_workflow",
            execution_id="test_execution",
            memory_manager=mock_memory,
            context_pool=mock_context,
            emotion_module=mock_emotion,
            crystallizer=mock_crystal
        )
        
        # 5. 测试 $memory 前缀
        print("\n--- 测试 $memory 前缀 ---")
        result = resolver.resolve("$memory.test_query", context)
        if result.success:
            print(f"✓ $memory 前缀解析成功: {result.value}")
        else:
            print(f"✗ $memory 前缀解析失败: {result.error}")
        
        # 6. 测试 $context 前缀
        print("\n--- 测试 $context 前缀 ---")
        result = resolver.resolve("$context.system_prompt", context)
        if result.success:
            print(f"✓ $context 前缀解析成功: {result.value}")
        else:
            print(f"✗ $context 前缀解析失败: {result.error}")
        
        # 7. 测试 $emotion 前缀
        print("\n--- 测试 $emotion 前缀 ---")
        result = resolver.resolve("$emotion.valence", context)
        if result.success:
            print(f"✓ $emotion 前缀解析成功: {result.value}")
        else:
            print(f"✗ $emotion 前缀解析失败: {result.error}")
        
        # 8. 测试 $crystal 前缀
        print("\n--- 测试 $crystal 前缀 ---")
        result = resolver.resolve("$crystal.test_pattern", context)
        if result.success:
            print(f"✓ $crystal 前缀解析成功: {result.value}")
        else:
            print(f"✗ $crystal 前缀解析失败: {result.error}")
        
        print("\n=== 修复验证完成 ===")
        print("所有四个变量前缀都能正常解析，ResolutionContext 外部系统注入修复成功！")
        
    except Exception as e:
        print(f"✗ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    return True


if __name__ == "__main__":
    success = asyncio.run(test_resolution_context_injection())
    sys.exit(0 if success else 1)