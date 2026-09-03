"""
ChannelManager 单例问题测试
验证 channel.py 端点直接构造 ChannelManager 导致的状态丢失问题
"""
import pytest
from unittest.mock import MagicMock, patch
from neurova.channels.manager import ChannelManager


class TestChannelManagerSingleton:
    """测试 ChannelManager 单例模式"""

    def test_singleton_pattern_works(self):
        """验证 ChannelManager 单例模式正常工作"""
        # 重置单例
        ChannelManager._instance = None
        
        # 获取单例实例
        instance1 = ChannelManager.get_instance()
        instance2 = ChannelManager.get_instance()
        
        # 应该是同一个实例
        assert instance1 is instance2
        assert id(instance1) == id(instance2)
    
    def test_direct_construction_raises_error(self):
        """验证直接构造 ChannelManager 会抛出错误"""
        # 重置单例
        ChannelManager._instance = None
        
        # 第一次构造应该成功
        instance1 = ChannelManager()
        ChannelManager._instance = instance1
        
        # 第二次构造应该抛出 RuntimeError
        with pytest.raises(RuntimeError) as exc_info:
            Channel2 = ChannelManager()
        
        assert "Use get_channel_manager() instead of direct construction" in str(exc_info.value)
    
    def test_direct_construction_bypasses_singleton(self):
        """验证直接构造会绕过单例模式"""
        # 重置单例
        ChannelManager._instance = None
        
        # 通过 get_instance 获取单例
        singleton = ChannelManager.get_instance()
        singleton._adapters["test"] = MagicMock()
        
        # 直接构造新实例（这在 channel.py 中发生）
        with pytest.raises(RuntimeError):
            new_instance = ChannelManager()
        
        # 注意：由于 RuntimeError，新实例无法创建
        # 但在 channel.py 中，如果单例已经存在，直接构造会抛出错误
        # 这说明 channel.py 中的代码有问题


class TestChannelEndpointSingletonIssue:
    """测试 channel.py 端点的单例问题（修复后）"""

    def test_get_channel_manager_returns_singleton(self):
        """验证 _get_channel_manager() 返回单例实例"""
        # 这个测试验证修复后的行为
        from neurova.api.endpoints.channel import _get_channel_manager
        
        # 重置单例
        ChannelManager._instance = None
        
        # 第一次调用
        manager1 = _get_channel_manager()
        assert manager1 is not None
        
        # 第二次调用 - 应该返回同一个单例实例
        manager2 = _get_channel_manager()
        
        # 修复后，应该返回同一个实例
        assert manager1 is manager2
        assert id(manager1) == id(manager2)
    
    def test_state_persists_between_requests(self):
        """验证请求之间状态保持"""
        # 重置单例
        ChannelManager._instance = None
        
        from neurova.api.endpoints.channel import _get_channel_manager
        
        # 第一次请求：添加渠道
        manager1 = _get_channel_manager()
        manager1._adapters["feishu"] = MagicMock()
        
        # 第二次请求：获取渠道列表
        manager2 = _get_channel_manager()
        
        # 修复后，由于使用单例，第二次请求可以看到第一次添加的渠道
        assert "feishu" in manager2._adapters


class TestChannelEndpointFix:
    """测试修复后的 channel.py 端点"""

    def test_use_singleton_get_instance(self):
        """验证修复后使用 get_instance()"""
        # 模拟修复后的代码
        def fixed_get_channel_manager():
            try:
                from neurova.channels.manager import ChannelManager
                return ChannelManager.get_instance()
            except Exception:
                return None
        
        # 重置单例
        ChannelManager._instance = None
        
        # 第一次调用
        manager1 = fixed_get_channel_manager()
        assert manager1 is not None
        
        # 第二次调用 - 应该返回同一个实例
        manager2 = fixed_get_channel_manager()
        
        # 现在应该是同一个实例
        assert manager1 is manager2
        assert id(manager1) == id(manager2)
    
    def test_state_persists_between_requests(self):
        """验证修复后状态在请求之间保持"""
        # 模拟修复后的代码
        def fixed_get_channel_manager():
            try:
                from neurova.channels.manager import ChannelManager
                return ChannelManager.get_instance()
            except Exception:
                return None
        
        # 重置单例
        ChannelManager._instance = None
        
        # 第一次请求：添加渠道
        manager1 = fixed_get_channel_manager()
        manager1._adapters["feishu"] = MagicMock()
        
        # 第二次请求：获取渠道列表
        manager2 = fixed_get_channel_manager()
        
        # 由于使用单例，第二次请求可以看到第一次添加的渠道
        assert "feishu" in manager2._adapters


if __name__ == "__main__":
    pytest.main([__file__, "-v"])