"""
上下文池单元测试

测试内容:
1. ContextSource 枚举
2. ContextInput 数据类
3. ContextCollector 收集器
4. ContextConverter 转换器
5. ContextCompressor 压缩器
6. ContextPool 上下文池
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from neurova.context_pool import (
    ContextSource,
    ContextInput,
    ContextCollector,
    ContextConverter,
    ContextCompressor,
    ContextPool,
    ContextPoolUtils,
)


class TestContextSource:
    """ContextSource 枚举测试"""
    
    def test_source_values(self):
        """测试 ContextSource 枚举值"""
        assert ContextSource.SYSTEM_INSTRUCTION.value == "system_instruction"
        assert ContextSource.DEVELOPER_INSTRUCTION.value == "developer_instruction"
        assert ContextSource.MEMORY.value == "memory"
        assert ContextSource.CONVERSATION.value == "conversation"
        assert ContextSource.EXPERIENCE.value == "experience"
        assert ContextSource.EMOTION.value == "emotion"
        assert ContextSource.REFLECTION.value == "reflection"
        assert ContextSource.TOOL_CALL.value == "tool_call"
        assert ContextSource.MULTIMODAL.value == "multimodal"
        assert ContextSource.USER_INPUT.value == "user_input"
    
    def test_source_members(self):
        """测试 ContextSource 枚举成员数量"""
        # P1-1③：+SUMMARY（溢出折叠摘要源）
        assert len(ContextSource) == 11
        assert ContextSource.SUMMARY.value == "summary"


class TestContextInput:
    """ContextInput 数据类测试"""
    
    def test_creation(self):
        """测试创建 ContextInput"""
        context_input = ContextInput(
            source=ContextSource.MEMORY,
            content="这是一条记忆",
            priority=80,
            metadata={"importance": 0.9, "emotion": "happy"}
        )
        
        assert context_input.source == ContextSource.MEMORY
        assert context_input.content == "这是一条记忆"
        assert context_input.priority == 80
        assert context_input.metadata["importance"] == 0.9
        assert context_input.metadata["emotion"] == "happy"
    
    def test_default_values(self):
        """测试默认值"""
        context_input = ContextInput(
            source=ContextSource.USER_INPUT,
            content="用户输入"
        )
        
        assert context_input.priority == 50
        assert context_input.metadata == {}
        assert context_input.tokens == 0
    
    def test_to_dict(self):
        """测试转换为字典"""
        context_input = ContextInput(
            source=ContextSource.MEMORY,
            content="记忆内容",
            priority=80
        )
        
        data = context_input.to_dict()
        assert data["source"] == "memory"
        assert data["content"] == "记忆内容"
        assert data["priority"] == 80


class TestContextCollector:
    """ContextCollector 收集器测试"""
    
    def test_creation(self):
        """测试创建 ContextCollector"""
        collector = ContextCollector(max_tokens=16000)
        assert collector.max_tokens == 16000
        assert len(collector.collect()) == 0
    
    def test_add_context(self):
        """测试添加上下文"""
        collector = ContextCollector()
        
        # 添加系统指令
        collector.add_context(ContextInput(
            source=ContextSource.SYSTEM_INSTRUCTION,
            content="你是一个AI助手",
            priority=100
        ))
        
        # 添加用户输入
        collector.add_context(ContextInput(
            source=ContextSource.USER_INPUT,
            content="你好",
            priority=50
        ))
        
        contexts = collector.collect()
        assert len(contexts) == 2
        assert contexts[0].source == ContextSource.SYSTEM_INSTRUCTION
        assert contexts[1].source == ContextSource.USER_INPUT
    
    def test_priority_sorting(self):
        """测试优先级排序"""
        collector = ContextCollector()
        
        # 添加不同优先级的上下文
        collector.add_context(ContextInput(
            source=ContextSource.USER_INPUT,
            content="用户输入",
            priority=50
        ))
        
        collector.add_context(ContextInput(
            source=ContextSource.SYSTEM_INSTRUCTION,
            content="系统指令",
            priority=100
        ))
        
        collector.add_context(ContextInput(
            source=ContextSource.MEMORY,
            content="记忆",
            priority=80
        ))
        
        contexts = collector.collect()
        # 应该按优先级降序排列
        assert contexts[0].priority >= contexts[1].priority >= contexts[2].priority
    
    def test_token_budget(self):
        """测试归档完整性：collect() 不做预算截断（预算裁剪是视图层 Drawer 的职责）"""
        collector = ContextCollector(max_tokens=100)

        # 添加超过预算的上下文
        collector.add_context(ContextInput(
            source=ContextSource.SYSTEM_INSTRUCTION,
            content="系统指令" * 50,  # 约200 tokens
            priority=100
        ))

        collector.add_context(ContextInput(
            source=ContextSource.USER_INPUT,
            content="用户输入",
            priority=50
        ))

        contexts = collector.collect()
        # [归档完整性] collect() 返回全部条目且内容无损，绝不因预算截断
        assert len(contexts) == 2
        assert contexts[0].source == ContextSource.SYSTEM_INSTRUCTION
        assert contexts[0].content == "系统指令" * 50
        assert contexts[1].source == ContextSource.USER_INPUT
    
    def test_collect_by_source(self):
        """测试按来源收集"""
        collector = ContextCollector()
        
        # 添加不同来源的上下文
        collector.add_context(ContextInput(
            source=ContextSource.MEMORY,
            content="记忆1",
            priority=80
        ))
        
        collector.add_context(ContextInput(
            source=ContextSource.MEMORY,
            content="记忆2",
            priority=70
        ))
        
        collector.add_context(ContextInput(
            source=ContextSource.CONVERSATION,
            content="对话",
            priority=50
        ))
        
        memory_contexts = collector.collect_by_source(ContextSource.MEMORY)
        assert len(memory_contexts) == 2
        
        conversation_contexts = collector.collect_by_source(ContextSource.CONVERSATION)
        assert len(conversation_contexts) == 1


class TestContextConverter:
    """ContextConverter 转换器测试"""
    
    def test_convert_to_openai_format(self):
        """测试转换为 OpenAI 格式"""
        converter = ContextConverter()
        
        context_input = ContextInput(
            source=ContextSource.USER_INPUT,
            content="你好",
            priority=50
        )
        
        openai_msg = converter.to_openai_format(context_input)
        
        assert openai_msg["role"] == "user"
        assert openai_msg["content"] == "你好"
    
    def test_convert_to_anthropic_format(self):
        """测试转换为 Anthropic 格式"""
        converter = ContextConverter()
        
        context_input = ContextInput(
            source=ContextSource.USER_INPUT,
            content="你好",
            priority=50
        )
        
        anthropic_msg = converter.to_anthropic_format(context_input)
        
        assert anthropic_msg["role"] == "user"
        assert anthropic_msg["content"][0]["type"] == "text"
        assert anthropic_msg["content"][0]["text"] == "你好"
    
    def test_convert_multimodal_to_openai(self):
        """测试多模态转换为 OpenAI 格式"""
        converter = ContextConverter()
        
        context_input = ContextInput(
            source=ContextSource.MULTIMODAL,
            content="[用户发送了一张图片: test.jpg]",
            priority=50,
            metadata={"media_type": "image", "media_url": "http://example.com/image.jpg"}
        )
        
        openai_msg = converter.to_openai_format(context_input)
        
        assert openai_msg["role"] == "user"
        assert isinstance(openai_msg["content"], list)
        # 应该包含文本和图片
        assert len(openai_msg["content"]) == 2
        assert openai_msg["content"][0]["type"] == "text"
        assert openai_msg["content"][1]["type"] == "image_url"
    
    def test_convert_for_model(self):
        """测试根据模型名称转换格式"""
        converter = ContextConverter()
        
        context_input = ContextInput(
            source=ContextSource.USER_INPUT,
            content="你好",
            priority=50
        )
        
        # OpenAI 模型
        openai_msg = converter.convert_for_model(context_input, "gpt-4o")
        assert openai_msg["role"] == "user"
        assert isinstance(openai_msg["content"], str)
        
        # Anthropic 模型
        anthropic_msg = converter.convert_for_model(context_input, "claude-3-opus")
        assert anthropic_msg["role"] == "user"
        assert isinstance(anthropic_msg["content"], list)


class TestContextCompressor:
    """ContextCompressor 压缩器测试"""
    
    def test_creation(self):
        """测试创建 ContextCompressor"""
        compressor = ContextCompressor(max_tokens=1000)
        assert compressor.max_tokens == 1000
    
    def test_compress_by_truncation(self):
        """测试截断压缩"""
        compressor = ContextCompressor(max_tokens=100)
        
        contexts = [
            ContextInput(source=ContextSource.MEMORY, content="记忆" * 50, priority=80),
            ContextInput(source=ContextSource.CONVERSATION, content="对话" * 50, priority=50),
            ContextInput(source=ContextSource.USER_INPUT, content="用户输入", priority=50),
        ]
        
        compressed = compressor.compress(contexts)
        
        # 应该压缩到预算内
        total_tokens = sum(len(ctx.content) for ctx in compressed)
        assert total_tokens <= 100
    
    def test_compress_by_priority(self):
        """测试优先级压缩"""
        compressor = ContextCompressor(max_tokens=100)
        
        contexts = [
            ContextInput(source=ContextSource.MEMORY, content="重要记忆" * 20, priority=100),
            ContextInput(source=ContextSource.CONVERSATION, content="普通对话" * 20, priority=50),
            ContextInput(source=ContextSource.USER_INPUT, content="用户输入", priority=50),
        ]
        
        compressed = compressor.compress(contexts)
        
        # 应该保留高优先级内容
        assert any(ctx.priority == 100 for ctx in compressed)
    
    def test_compress_with_summarization(self):
        """测试摘要压缩"""
        compressor = ContextCompressor(max_tokens=50, enable_summarization=True)
        
        contexts = [
            ContextInput(source=ContextSource.CONVERSATION, content="很长的对话内容" * 10, priority=50),
        ]
        
        compressed = compressor.compress(contexts)
        
        # 应该生成摘要
        assert len(compressed) == 1
        assert "摘要" in compressed[0].content or len(compressed[0].content) < len(contexts[0].content)


class TestContextPool:
    """ContextPool 上下文池测试"""
    
    def test_creation(self):
        """测试创建 ContextPool"""
        pool = ContextPool(user_id="test_user", agent_id="test_agent", max_tokens=16000)
        assert pool.max_tokens == 16000
        assert len(pool.get_contexts()) == 0
    
    def test_add_context(self):
        """测试添加上下文"""
        pool = ContextPool(user_id="test_user", agent_id="test_agent")
        
        pool.add_context(ContextInput(
            source=ContextSource.SYSTEM_INSTRUCTION,
            content="系统指令",
            priority=100
        ))
        
        contexts = pool.get_contexts()
        assert len(contexts) == 1
        assert contexts[0].source == ContextSource.SYSTEM_INSTRUCTION
    
    def test_build_context_for_chat(self):
        """测试构建聊天上下文"""
        pool = ContextPool(user_id="test_user", agent_id="test_agent")
        
        # 添加各种上下文
        pool.add_context(ContextInput(
            source=ContextSource.SYSTEM_INSTRUCTION,
            content="你是一个AI助手",
            priority=100
        ))
        
        pool.add_context(ContextInput(
            source=ContextSource.USER_INPUT,
            content="你好",
            priority=50
        ))
        
        # 构建 OpenAI 格式上下文
        messages = pool.build_context_for_model("gpt-4o")
        
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
    
    def test_build_context_for_multimodal(self):
        """测试构建多模态上下文"""
        pool = ContextPool(user_id="test_user", agent_id="test_agent")
        
        # 添加多模态上下文
        pool.add_context(ContextInput(
            source=ContextSource.MULTIMODAL,
            content="[用户发送了一张图片]",
            priority=50,
            metadata={"media_type": "image", "media_url": "http://example.com/image.jpg"}
        ))
        
        # 构建 OpenAI 格式上下文
        messages = pool.build_context_for_model("gpt-4o")
        
        assert len(messages) == 1
        assert isinstance(messages[0]["content"], list)
    
    def test_convert_context_for_model(self):
        """测试转换上下文格式"""
        pool = ContextPool(user_id="test_user", agent_id="test_agent")
        
        pool.add_context(ContextInput(
            source=ContextSource.USER_INPUT,
            content="你好",
            priority=50
        ))
        
        # 转换为 OpenAI 格式
        openai_messages = pool.convert_context_for_model("gpt-4o")
        assert openai_messages[0]["role"] == "user"
        assert isinstance(openai_messages[0]["content"], str)
        
        # 转换为 Anthropic 格式
        anthropic_messages = pool.convert_context_for_model("claude-3-opus")
        assert anthropic_messages[0]["role"] == "user"
        assert isinstance(anthropic_messages[0]["content"], list)
    
    def test_compress_context(self):
        """测试压缩上下文"""
        pool = ContextPool(user_id="test_user", agent_id="test_agent", max_tokens=100)
        
        # 添加超过预算的上下文
        pool.add_context(ContextInput(
            source=ContextSource.CONVERSATION,
            content="很长的对话" * 50,
            priority=50
        ))
        
        pool.add_context(ContextInput(
            source=ContextSource.USER_INPUT,
            content="用户输入",
            priority=50
        ))
        
        # 压缩上下文
        pool.compress_context()
        
        contexts = pool.get_contexts()
        total_tokens = sum(ctx.tokens for ctx in contexts)
        assert total_tokens <= 100


class TestContextPoolUtils:
    """ContextPoolUtils 工具函数测试"""
    
    def test_estimate_tokens(self):
        """测试 Token 估算"""
        # 英文
        tokens = ContextPoolUtils.estimate_tokens("Hello world")
        assert tokens > 0
        
        # 中文
        tokens = ContextPoolUtils.estimate_tokens("你好世界")
        assert tokens > 0
    
    def test_merge_contexts(self):
        """测试合并上下文"""
        contexts1 = [
            ContextInput(source=ContextSource.MEMORY, content="记忆1", priority=80),
            ContextInput(source=ContextSource.MEMORY, content="记忆2", priority=70),
        ]
        
        contexts2 = [
            ContextInput(source=ContextSource.CONVERSATION, content="对话1", priority=50),
            ContextInput(source=ContextSource.CONVERSATION, content="对话2", priority=40),
        ]
        
        merged = ContextPoolUtils.merge_contexts(contexts1, contexts2)
        
        assert len(merged) == 4
        # 应该按优先级排序
        assert merged[0].priority >= merged[1].priority >= merged[2].priority >= merged[3].priority
    
    def test_filter_by_source(self):
        """测试按来源过滤"""
        contexts = [
            ContextInput(source=ContextSource.MEMORY, content="记忆", priority=80),
            ContextInput(source=ContextSource.CONVERSATION, content="对话", priority=50),
            ContextInput(source=ContextSource.MEMORY, content="记忆2", priority=70),
        ]
        
        filtered = ContextPoolUtils.filter_by_source(contexts, ContextSource.MEMORY)
        
        assert len(filtered) == 2
        assert all(ctx.source == ContextSource.MEMORY for ctx in filtered)