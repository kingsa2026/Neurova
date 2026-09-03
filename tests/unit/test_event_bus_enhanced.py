"""
EventBusEnhanced 深度模块测试

测试 EventBusEnhanced 作为增强事件总线深度模块的行为：
1. 事件过滤
2. 事件重播
3. 死信队列
4. 事件链
5. 统计信息
"""

import pytest
import time
from unittest.mock import Mock, MagicMock

from neurova.core.event_bus_enhanced import (
    EventBusEnhanced,
    EventFilter,
    DeadLetter,
    get_event_bus_enhanced,
    reset_event_bus_enhanced,
)
from neurova.core.event_bus import Event, EventPriority, Subscription


class TestEventBusEnhancedInterface:
    """测试 EventBusEnhanced 接口设计"""

    @pytest.fixture
    def bus(self):
        """创建 EventBusEnhanced 实例"""
        return EventBusEnhanced()

    def test_inherits_event_bus(self, bus):
        """验证继承自 EventBus"""
        from neurova.core.event_bus import EventBus
        assert isinstance(bus, EventBus)

    def test_enhanced_methods_exist(self, bus):
        """验证增强方法存在"""
        assert hasattr(bus, 'add_filter')
        assert hasattr(bus, 'remove_filter')
        assert hasattr(bus, 'add_event_chain')
        assert hasattr(bus, 'remove_event_chain')
        assert hasattr(bus, 'replay_events')
        assert hasattr(bus, 'add_dead_letter')
        assert hasattr(bus, 'get_dead_letters')
        assert hasattr(bus, 'clear_dead_letters')
        assert hasattr(bus, 'retry_dead_letter')
        assert hasattr(bus, 'set_event_timeout')
        assert hasattr(bus, 'get_event_history')
        assert hasattr(bus, 'get_statistics')


class TestEventFiltering:
    """测试事件过滤"""

    @pytest.fixture
    def bus(self):
        """创建 EventBusEnhanced 实例"""
        return EventBusEnhanced()

    def test_add_filter(self, bus):
        """测试添加过滤器"""
        filter_obj = EventFilter(
            name="test_filter",
            predicate=lambda event: event.data.get("type") == "important",
            description="过滤重要事件"
        )
        bus.add_filter("test_event", filter_obj)
        
        # 验证过滤器已添加
        assert "test_event" in bus._filters
        assert len(bus._filters["test_event"]) == 1

    def test_remove_filter(self, bus):
        """测试移除过滤器"""
        filter_obj = EventFilter(
            name="test_filter",
            predicate=lambda event: True
        )
        bus.add_filter("test_event", filter_obj)
        
        # 移除过滤器
        result = bus.remove_filter("test_event", "test_filter")
        assert result is True
        assert "test_event" not in bus._filters or len(bus._filters["test_event"]) == 0

    def test_filter_blocks_event(self, bus):
        """测试过滤器阻止事件"""
        # 添加过滤器：只允许 type=important 的事件
        filter_obj = EventFilter(
            name="important_only",
            predicate=lambda event: event.data.get("type") == "important" if isinstance(event.data, dict) else False
        )
        bus.add_filter("test_event", filter_obj)
        
        # 订阅事件
        handler = Mock()
        bus.subscribe("test_event", handler)
        
        # 发布被过滤的事件
        bus.publish("test_event", data={"type": "normal"})
        handler.assert_not_called()
        
        # 发布通过过滤的事件
        bus.publish("test_event", data={"type": "important"})
        handler.assert_called_once()

    def test_filter_exception_handling(self, bus):
        """测试过滤器异常处理"""
        # 添加会抛出异常的过滤器
        def bad_filter(event):
            raise ValueError("Filter error")
        
        filter_obj = EventFilter(
            name="bad_filter",
            predicate=bad_filter
        )
        bus.add_filter("test_event", filter_obj)
        
        # 订阅事件
        handler = Mock()
        bus.subscribe("test_event", handler)
        
        # 发布事件（过滤器异常不应阻止事件发布）
        bus.publish("test_event", data="test")
        # 由于过滤器异常，事件应该被阻止
        handler.assert_not_called()


class TestEventReplay:
    """测试事件重播"""

    @pytest.fixture
    def bus(self):
        """创建 EventBusEnhanced 实例"""
        return EventBusEnhanced()

    def test_replay_events(self, bus):
        """测试重播事件"""
        # 订阅事件
        handler = Mock()
        bus.subscribe("test_event", handler)
        
        # 发布几个事件
        bus.publish("test_event", data="event1")
        bus.publish("test_event", data="event2")
        bus.publish("other_event", data="other")
        
        # 重播 test_event（有2个历史记录）
        count = bus.replay_events(event_name="test_event")
        assert count == 2
        
        # 验证重播的事件被调用：原始2次 + 重播2次 = 4次
        assert handler.call_count == 4  # 原始2次 + 重播2次

    def test_replay_all_events(self, bus):
        """测试重播所有事件"""
        handler1 = Mock()
        handler2 = Mock()
        bus.subscribe("event1", handler1)
        bus.subscribe("event2", handler2)
        
        # 发布事件
        bus.publish("event1", data="data1")
        bus.publish("event2", data="data2")
        
        # 重播所有事件
        count = bus.replay_events()
        assert count == 2


class TestDeadLetterQueue:
    """测试死信队列"""

    @pytest.fixture
    def bus(self):
        """创建 EventBusEnhanced 实例"""
        return EventBusEnhanced()

    def test_add_dead_letter(self, bus):
        """测试添加死信"""
        event = Event(name="test_event", data="test")
        subscription = Subscription(
            event_name="test_event",
            handler=Mock(side_effect=Exception("Handler error"))
        )
        error = Exception("Test error")
        
        bus.add_dead_letter(event, subscription, error)
        
        dead_letters = bus.get_dead_letters()
        assert len(dead_letters) == 1
        assert dead_letters[0].event.name == "test_event"

    def test_clear_dead_letters(self, bus):
        """测试清空死信队列"""
        # 添加几个死信
        for i in range(3):
            event = Event(name="test_event", data=f"test{i}")
            subscription = Subscription(
                event_name="test_event",
                handler=Mock()
            )
            error = Exception(f"Error {i}")
            bus.add_dead_letter(event, subscription, error)
        
        # 清空
        count = bus.clear_dead_letters()
        assert count == 3
        assert len(bus.get_dead_letters()) == 0

    def test_retry_dead_letter(self, bus):
        """测试重试死信"""
        handler = Mock()
        bus.subscribe("test_event", handler)
        
        # 创建死信
        event = Event(name="test_event", data="retry_test")
        subscription = Subscription(
            event_name="test_event",
            handler=handler
        )
        error = Exception("Original error")
        dead_letter = DeadLetter(event=event, subscription=subscription, error=error)
        
        # 重试
        result = bus.retry_dead_letter(dead_letter)
        assert result is True
        # 验证handler被调用（不比较source字段）
        assert handler.call_count == 1
        call_args = handler.call_args[0][0]
        assert call_args.name == "test_event"
        assert call_args.data == "retry_test"


class TestEventChains:
    """测试事件链"""

    @pytest.fixture
    def bus(self):
        """创建 EventBusEnhanced 实例"""
        return EventBusEnhanced()

    def test_add_event_chain(self, bus):
        """测试添加事件链"""
        bus.add_event_chain("trigger", ["target1", "target2"])
        
        assert "trigger" in bus._event_chains
        assert bus._event_chains["trigger"] == ["target1", "target2"]

    def test_remove_event_chain(self, bus):
        """测试移除事件链"""
        bus.add_event_chain("trigger", ["target1", "target2"])
        
        result = bus.remove_event_chain("trigger")
        assert result is True
        assert "trigger" not in bus._event_chains

    def test_event_chain_execution(self, bus):
        """测试事件链执行"""
        handler1 = Mock()
        handler2 = Mock()
        bus.subscribe("target1", handler1)
        bus.subscribe("target2", handler2)
        
        # 添加事件链
        bus.add_event_chain("trigger", ["target1", "target2"])
        
        # 发布触发事件
        bus.publish("trigger", data="chain_test")
        
        # 验证目标事件被触发
        handler1.assert_called_once()
        handler2.assert_called_once()


class TestEventBusEnhancedFactory:
    """测试工厂函数"""

    def test_get_event_bus_enhanced(self):
        """测试工厂函数创建实例"""
        reset_event_bus_enhanced()
        bus = get_event_bus_enhanced()
        assert isinstance(bus, EventBusEnhanced)
        assert bus.is_running()

    def test_reset_event_bus_enhanced(self):
        """测试重置函数"""
        bus1 = get_event_bus_enhanced()
        reset_event_bus_enhanced()
        bus2 = get_event_bus_enhanced()
        assert bus1 is not bus2


class TestEventBusEnhancedStatistics:
    """测试统计信息"""

    @pytest.fixture
    def bus(self):
        """创建 EventBusEnhanced 实例"""
        return EventBusEnhanced()

    def test_get_statistics(self, bus):
        """测试获取统计信息"""
        # 添加一些数据
        bus.subscribe("test_event", Mock())
        bus.add_event_chain("trigger", ["target"])
        filter_obj = EventFilter(name="filter", predicate=lambda e: True)
        bus.add_filter("test_event", filter_obj)
        
        # 发布事件
        bus.publish("test_event", data="test")
        
        stats = bus.get_statistics()
        assert "total_events" in stats
        assert "total_subscriptions" in stats
        assert "dead_letters" in stats
        assert "event_chains" in stats
        assert "filters" in stats