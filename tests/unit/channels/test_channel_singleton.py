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


# 说明（2026-09-13 死壳清理）：原 TestChannelEndpointSingletonIssue/TestChannelEndpointFix
# 测 neurova/api/endpoints/channel.py 的 _get_channel_manager——该端点为 ChannelManager
# 假桥死壳（方法不存在、GET 恒 []、POST 假成功），渠道唯一真集为
# channel_config.py(/v1/channel-configs)，死壳连同前端 AgentChannelPage/channels.ts 一并移除；
# ChannelManager 单例语义由上方 TestChannelManagerSingleton 直接钉住，覆盖无损失。
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
