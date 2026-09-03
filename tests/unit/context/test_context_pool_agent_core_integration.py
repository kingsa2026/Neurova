"""
ContextPool 与 agent_core.py 集成测试 - Tracer Bullet #4

测试目标：
1. ContextPool 与 Agent 类的集成
2. 替换 ContextOrchestrator 为 ContextPool
3. 保持向后兼容性
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from neurova.context_pool import (
    ContextSource,
    ContextInput,
    ContextPool,
)


class TestContextPoolAgentCoreIntegration:
    """ContextPool 与 Agent 核心集成测试"""
    
    def test_agent_can_use_context_pool(self):
        """测试 Agent 可以使用 ContextPool"""
        # 创建 ContextPool
        pool = ContextPool(
            user_id="test_user",
            agent_id="test_agent",
            max_tokens=16000,
            auto_tag=True
        )
        
        # 模拟 Agent 的上下文构建过程
        pool.add_context(ContextInput(
            source=ContextSource.SYSTEM_INSTRUCTION,
            content="你是一个AI助手",
            priority=100
        ))
        
        pool.add_context(ContextInput(
            source=ContextSource.USER_INPUT,
            content="帮我写一个Python函数",
            priority=90
        ))
        
        pool.add_context(ContextInput(
            source=ContextSource.MEMORY,
            content="用户之前问过类似问题",
            priority=70
        ))
        
        # 验证能获取上下文
        contexts = pool.get_contexts()
        assert len(contexts) == 3
        
        # 验证能构建模型格式
        messages = pool.build_context_for_model("gpt-4")
        assert len(messages) == 3
        
        # 验证自动标签
        for ctx in contexts:
            assert len(ctx.tags) > 0
    
    def test_context_pool_draw_for_agent(self):
        """测试 Agent 使用 ContextPool.draw() 获取相关上下文"""
        # 创建 ContextPool
        pool = ContextPool(
            user_id="test_user",
            agent_id="test_agent",
            max_tokens=16000,
            auto_tag=True
        )
        
        # 添加各种上下文
        pool.add_context(ContextInput(
            source=ContextSource.MEMORY,
            content="Python 代码优化技巧",
            priority=80,
            tags=["代码", "Python", "优化"]
        ))
        
        pool.add_context(ContextInput(
            source=ContextSource.EMOTION,
            content="用户今天心情很好",
            priority=50,
            tags=["情感", "心情"]
        ))
        
        pool.add_context(ContextInput(
            source=ContextSource.CONVERSATION,
            content="之前讨论过算法问题",
            priority=60,
            tags=["对话", "算法"]
        ))
        
        # 按需取水
        result = pool.draw(need="编程 代码")
        
        # 应该返回列表
        assert isinstance(result, list)
        assert len(result) > 0
        
        # 验证返回了相关上下文
        assert any("Python" in ctx.content for ctx in result)
    
    def test_context_pool_with_tool_calls(self):
        """测试 ContextPool 处理工具调用上下文"""
        # 创建 ContextPool
        pool = ContextPool(
            user_id="test_user",
            agent_id="test_agent",
            max_tokens=16000,
            auto_tag=True
        )
        
        # 添加工具调用上下文
        pool.add_context(ContextInput(
            source=ContextSource.TOOL_CALL,
            content="调用了 file_read 工具读取文件",
            priority=70,
            metadata={"tool_name": "file_read", "result": "success"}
        ))
        
        pool.add_context(ContextInput(
            source=ContextSource.TOOL_CALL,
            content="调用了 web_search 工具搜索信息",
            priority=70,
            metadata={"tool_name": "web_search", "result": "success"}
        ))
        
        # 验证工具调用上下文
        contexts = pool.get_contexts()
        assert len(contexts) == 2
        
        # 验证工具调用标签
        for ctx in contexts:
            assert "工具" in ctx.tags
            assert "调用" in ctx.tags
    
    def test_context_pool_with_multimodal(self):
        """测试 ContextPool 处理多模态上下文"""
        # 创建 ContextPool
        pool = ContextPool(
            user_id="test_user",
            agent_id="test_agent",
            max_tokens=16000,
            auto_tag=True
        )
        
        # 添加多模态上下文
        pool.add_context(ContextInput(
            source=ContextSource.MULTIMODAL,
            content="用户上传了一张图片",
            priority=80,
            metadata={"media_type": "image", "media_url": "http://example.com/image.jpg"}
        ))
        
        # 验证多模态上下文
        contexts = pool.get_contexts()
        assert len(contexts) == 1
        
        # 验证多模态标签
        assert "多模态" in contexts[0].tags
        assert "媒体" in contexts[0].tags
        
        # 验证能构建 OpenAI 格式
        messages = pool.build_context_for_model("gpt-4-vision-preview")
        assert len(messages) == 1
        
        # 验证多模态格式
        msg = messages[0]
        assert "content" in msg
        assert isinstance(msg["content"], list)
        assert any(item.get("type") == "image_url" for item in msg["content"])


class TestContextPoolCompatibility:
    """ContextPool 兼容性测试"""
    
    def test_context_pool_compatible_with_existing_code(self):
        """测试 ContextPool 与现有代码兼容"""
        # 创建 ContextPool
        pool = ContextPool(
            user_id="test_user",
            agent_id="test_agent",
            max_tokens=16000
        )
        
        # 测试现有方法
        pool.add_context(ContextInput(
            source=ContextSource.USER_INPUT,
            content="用户输入",
            priority=50
        ))
        
        # 测试 get_contexts()
        contexts = pool.get_contexts()
        assert len(contexts) == 1
        
        # 测试 build_context_for_model()
        messages = pool.build_context_for_model("gpt-3.5-turbo")
        assert len(messages) == 1
        
        # 测试 compress_context()
        pool.compress_context()
        
        # 测试 merge_with()
        other_pool = ContextPool(
            user_id="other_user",
            agent_id="other_agent",
            max_tokens=8000
        )
        other_pool.add_context(ContextInput(
            source=ContextSource.MEMORY,
            content="其他记忆",
            priority=60
        ))
        
        pool.merge_with(other_pool)
        
        # 验证合并后有两个上下文
        contexts = pool.get_contexts()
        assert len(contexts) == 2
    
    def test_context_pool_isolation(self):
        """测试 ContextPool 隔离机制"""
        # 创建两个不同用户的 ContextPool
        pool1 = ContextPool(
            user_id="user1",
            agent_id="agent1",
            max_tokens=16000
        )
        
        pool2 = ContextPool(
            user_id="user2",
            agent_id="agent2",
            max_tokens=16000
        )
        
        # 添加上下文
        pool1.add_context(ContextInput(
            source=ContextSource.USER_INPUT,
            content="用户1的输入",
            priority=50
        ))
        
        pool2.add_context(ContextInput(
            source=ContextSource.USER_INPUT,
            content="用户2的输入",
            priority=50
        ))
        
        # 验证隔离
        contexts1 = pool1.get_contexts()
        contexts2 = pool2.get_contexts()
        
        assert len(contexts1) == 1
        assert len(contexts2) == 1
        assert contexts1[0].content == "用户1的输入"
        assert contexts2[0].content == "用户2的输入"
        
        # 验证隔离键不同
        assert pool1.isolation_key != pool2.isolation_key


class TestContextPoolPerformance:
    """ContextPool 性能测试"""
    
    def test_context_pool_large_context(self):
        """测试 ContextPool 处理大量上下文"""
        # 创建 ContextPool
        pool = ContextPool(
            user_id="test_user",
            agent_id="test_agent",
            max_tokens=16000
        )
        
        # 添加大量上下文
        for i in range(100):
            pool.add_context(ContextInput(
                source=ContextSource.MEMORY,
                content=f"记忆内容 {i}",
                priority=50 + (i % 50)
            ))
        
        # 验证能处理大量上下文
        contexts = pool.get_contexts()
        assert len(contexts) > 0
        
        # 验证 Token 预算限制
        total_tokens = sum(ctx.tokens for ctx in contexts)
        assert total_tokens <= 16000
    
    def test_context_pool_draw_performance(self):
        """测试 ContextPool.draw() 性能"""
        # 创建 ContextPool
        pool = ContextPool(
            user_id="test_user",
            agent_id="test_agent",
            max_tokens=16000
        )
        
        # 添加上下文
        for i in range(50):
            pool.add_context(ContextInput(
                source=ContextSource.MEMORY,
                content=f"记忆内容 {i}",
                priority=50 + (i % 50),
                tags=[f"标签{i}", "记忆"]
            ))
        
        # 测试 draw() 性能
        import time
        start_time = time.time()
        
        result = pool.draw(need="记忆 内容")
        
        end_time = time.time()
        duration = end_time - start_time
        
        # 验证性能（应该在1秒内完成）
        assert duration < 1.0
        
        # 验证结果
        assert isinstance(result, list)
        assert len(result) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])