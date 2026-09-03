"""
活水上下文池优化测试 - Tracer Bullet #7

测试目标：
1. 消息处理器连接验证
2. 上下文池大小与生命周期控制
3. 动态 Token 预算
4. 向量存储缓存预加载
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch, Mock
from datetime import datetime, timedelta
import sys
from neurova.channels.manager import ChannelManager
from neurova.context_pool import ContextPool, ContextInput, ContextSource


class TestChannelManagerMessageHandler:
    """消息处理器连接测试"""
    
    def test_set_message_handler_stores_handler(self):
        """测试 set_message_handler 正确存储处理器"""
        manager = ChannelManager()
        mock_handler = AsyncMock()
        
        manager.set_message_handler(mock_handler)
        
        assert manager._message_handler == mock_handler
    
    @pytest.mark.asyncio
    async def test_message_handler_called_on_event(self):
        """测试收到消息时正确调用处理器"""
        manager = ChannelManager()
        mock_handler = AsyncMock(return_value="回复内容")
        manager.set_message_handler(mock_handler)
        
        # 模拟渠道消息
        mock_message = MagicMock()
        mock_message.channel_type = "feishu"
        mock_message.chat_id = "test_chat"
        mock_message.sender_name = "test_user"
        
        # 模拟发送消息
        with patch.object(manager, 'send_message', new_callable=AsyncMock) as mock_send:
            mock_send.return_value = "msg_id"
            
            # 触发消息事件
            from neurova.channels.base import ChannelEventType
            await manager._on_channel_event(ChannelEventType.MESSAGE_RECEIVED, mock_message)
            
            # 验证处理器被调用
            mock_handler.assert_called_once_with(mock_message)
            
            # 验证回复被发送
            mock_send.assert_called_once_with(
                "feishu",
                "test_chat",
                "回复内容"
            )
    
    def test_message_handler_not_called_when_none(self):
        """测试处理器为 None 时不调用"""
        manager = ChannelManager()
        manager._message_handler = None
        
        # 模拟渠道消息
        mock_message = MagicMock()
        
        # 不应抛出异常
        from neurova.channels.base import ChannelEventType
        import asyncio
        asyncio.run(manager._on_channel_event(ChannelEventType.MESSAGE_RECEIVED, mock_message))


class TestContextPoolLifecycle:
    """上下文池生命周期控制测试"""
    
    def test_pool_max_size_limit(self):
        """测试池最大大小限制"""
        pool = ContextPool(
            user_id="test_user",
            agent_id="test_agent",
            max_tokens=1000,
            max_size=5  # 新增：最大大小限制
        )
        
        # 添加超过限制的上下文
        for i in range(10):
            pool.add_context(ContextInput(
                source=ContextSource.USER_INPUT,
                content=f"消息 {i}",
                priority=50
            ))

        # [无损归档] max_size 不再驱逐：全部条目保留（容量控制移至视图层 Drawer）
        contexts = pool.get_contexts()
        assert len(contexts) == 10, f"归档条目被驱逐：{len(contexts)}/10"
    
    def test_pool_ttl_expiration(self):
        """测试上下文过期时间"""
        pool = ContextPool(
            user_id="test_user",
            agent_id="test_agent",
            ttl_seconds=60  # 新增：过期时间
        )
        
        # 添加旧的上下文
        old_context = ContextInput(
            source=ContextSource.MEMORY,
            content="旧记忆",
            priority=50,
            created_at=datetime.now() - timedelta(seconds=120)  # 2分钟前
        )
        pool.add_context(old_context)
        
        # 添加新的上下文
        new_context = ContextInput(
            source=ContextSource.USER_INPUT,
            content="新输入",
            priority=50,
            created_at=datetime.now()
        )
        pool.add_context(new_context)
        
        # 获取上下文，应该只包含新的
        contexts = pool.get_contexts()
        contents = [c.content for c in contexts]
        assert "旧记忆" not in contents
        assert "新输入" in contents
    
    def test_pool_cleanup_expired(self):
        """测试清理过期上下文"""
        pool = ContextPool(
            user_id="test_user",
            agent_id="test_agent",
            ttl_seconds=60
        )
        
        # 添加混合上下文
        for i in range(5):
            created = datetime.now() - timedelta(seconds=30 * i)
            pool.add_context(ContextInput(
                source=ContextSource.MEMORY,
                content=f"记忆 {i}",
                priority=50,
                created_at=created
            ))
        
        # 清理过期上下文
        removed_count = pool.cleanup_expired()
        
        # 验证清理结果
        assert removed_count > 0
        contexts = pool.get_contexts()
        for ctx in contexts:
            age = (datetime.now() - ctx.created_at).total_seconds()
            assert age <= 60


class TestDynamicTokenBudget:
    """动态 Token 预算测试"""
    
    def test_get_token_budget_for_model(self):
        """测试根据模型获取 Token 预算"""
        pool = ContextPool(
            user_id="test_user",
            agent_id="test_agent"
        )
        
        # 测试不同模型的 Token 预算
        budget_gpt4 = pool.get_token_budget_for_model("gpt-4")
        budget_gpt35 = pool.get_token_budget_for_model("gpt-3.5-turbo")
        budget_claude = pool.get_token_budget_for_model("claude-3-opus")
        
        # GPT-4 应该有更大的预算
        assert budget_gpt4 > budget_gpt35
        assert budget_claude > budget_gpt35
    
    def test_dynamic_budget_based_on_capabilities(self):
        """测试根据模型能力动态调整预算"""
        pool = ContextPool(
            user_id="test_user",
            agent_id="test_agent"
        )
        
        # 模拟模型能力
        from neurova.llm.llm_router import ModelCapability
        
        # 视觉模型应该有更大的预算
        vision_budget = pool.get_token_budget_for_capabilities(
            [ModelCapability.VISION, ModelCapability.TEXT]
        )
        text_budget = pool.get_token_budget_for_capabilities(
            [ModelCapability.TEXT]
        )
        
        assert vision_budget > text_budget


class TestVectorStorePreload:
    """向量存储预加载测试"""
    
    def test_vector_store_preload(self):
        """测试向量存储预加载（Mock 用后恢复，不污染 sys.modules）"""
        from neurova.context_pool import SemanticMatchDrawer

        drawer = SemanticMatchDrawer(max_tokens=16000)

        # 验证预加载方法存在
        assert hasattr(drawer, "preload_vector_store")

        # 初始状态应该是 None
        assert drawer._vector_store is None

        import sys as _sys
        _key = "neurova.cognitive_layers.memory_layer.unified_vector_store"
        _real = _sys.modules.get(_key)
        try:
            with patch("neurova.context_pool.UnifiedVectorStore", create=True):
                drawer.preload_vector_store()
                assert drawer._vector_store is not None
        finally:
            if _real is not None:
                _sys.modules[_key] = _real
            else:
                _sys.modules.pop(_key, None)
    def test_vector_store_cache_hit(self):
        """测试向量存储缓存命中"""
        from neurova.context_pool import SemanticMatchDrawer
        
        drawer = SemanticMatchDrawer(max_tokens=16000)
        
        # 模拟预加载 - 设置一个 mock 对象
        drawer._vector_store = Mock()
        
        # 再次调用 preload_vector_store 应该不会重新创建（因为 _vector_store 不是 None）
        original_store = drawer._vector_store
        drawer.preload_vector_store()
        
        # 应该是同一个对象（缓存命中）
        assert drawer._vector_store is original_store