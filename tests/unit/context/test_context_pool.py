"""
上下文池单元测试

测试内容:
1. ContextSource 枚举
2. ContextInput 数据类
3. ContextCollector 收集器
4. ContextConverter 转换器
5. 视图层预算选取（draw）
6. ContextPool 上下文池
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from neurova.context_pool import (
    ContextSource,
    ContextInput,
    ContextCollector,
    ContextConverter,
    ContextPool,
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


class TestViewLayerBudgetSelection:
    """按预算取用是**视图层**（draw）职责，不是归档层。

    B6-10 批次 C：原 `TestContextCompressor` 锁 `ContextCompressor` 的按预算
    裁剪，而该类整模块退役（同契约第二份实现，唯一消费点
    `ContextPool.compress_context` 零消费）。契约搬到真面——视图层选取：
    预算内整条取用 + 高优先级先中选 + 归档不被改动。
    """

    def test_draw_respects_budget(self):
        pool = ContextPool(user_id="test_user", agent_id="test_agent")
        for source, content, priority in (
            (ContextSource.MEMORY, "记忆" * 50, 80),
            (ContextSource.CONVERSATION, "对话" * 50, 50),
            (ContextSource.USER_INPUT, "用户输入", 50),
        ):
            pool.add_context(ContextInput(source=source, content=content, priority=priority))

        drawn = pool.draw(budget_tokens=100)
        assert sum(ctx.tokens for ctx in drawn) <= 100

    def test_high_priority_selected_first(self):
        pool = ContextPool(user_id="test_user", agent_id="test_agent")
        for source, content, priority in (
            (ContextSource.MEMORY, "重要记忆" * 20, 100),
            (ContextSource.CONVERSATION, "普通对话" * 20, 50),
            (ContextSource.USER_INPUT, "用户输入", 50),
        ):
            pool.add_context(ContextInput(source=source, content=content, priority=priority))

        drawn = pool.draw(budget_tokens=100)
        assert any(ctx.priority == 100 for ctx in drawn), (
            "预算紧张时高优先级条目必须先被选中"
        )

    def test_draw_never_mutates_archive(self):
        pool = ContextPool(user_id="test_user", agent_id="test_agent")
        pool.add_context(ContextInput(
            source=ContextSource.CONVERSATION,
            content="很长的对话内容" * 10,
            priority=50,
        ))
        before = [c.content for c in pool.get_contexts()]
        pool.draw(budget_tokens=50)
        assert [c.content for c in pool.get_contexts()] == before, (
            "视图层取用不得改动归档（无损归档语义）"
        )


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
    
    def test_archive_not_trimmed_by_budget(self):
        """超预算不裁剪归档：池是无损归档，预算只作用于视图层取用。

        B6-10 批次 C：原用例调用 `pool.compress_context()` 把归档裁到预算内——
        那个出口零消费，且与"池是永久归档、永不丢失"的类契约**相反**
        （见 ADR-0015 的回收契约）。压缩真通路在 orchestrator 的
        信封+历史确定性淘汰（判据：test_envelope.py）。此处改锁归档无损。
        """
        pool = ContextPool(user_id="test_user", agent_id="test_agent", max_tokens=100)

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

        contexts = pool.get_contexts()
        assert len(contexts) == 2, "归档层不得按预算裁剪（永不丢失是硬约束）"
        # 视图层才按预算整条取用
        drawn = pool.draw(budget_tokens=100)
        assert sum(c.tokens for c in drawn) <= 100


