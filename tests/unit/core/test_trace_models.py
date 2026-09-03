"""
测试轨迹模型模块
"""
import pytest
from datetime import datetime, timezone
from neurova.core.trace_models import (
    TrajectoryEventType,
    TrajectoryEvent,
    TrajectorySpan,
    Trajectory,
)


class TestTrajectoryEventType:
    """测试TrajectoryEventType枚举"""
    
    def test_event_type_members(self):
        """测试事件类型成员"""
        assert TrajectoryEventType.SESSION_START.value == "session_start"
        assert TrajectoryEventType.USER_INPUT.value == "user_input"
        assert TrajectoryEventType.LLM_CALL_START.value == "llm_call_start"
        assert TrajectoryEventType.TOOL_CALL_ERROR.value == "tool_call_error"
        assert TrajectoryEventType.ERROR.value == "error"
    
    def test_event_type_iteration(self):
        """测试事件类型迭代"""
        event_types = list(TrajectoryEventType)
        assert len(event_types) > 0
        assert TrajectoryEventType.SESSION_START in event_types


class TestTrajectoryEvent:
    """测试TrajectoryEvent数据类"""
    
    def test_create_event_basic(self):
        """测试创建基本事件"""
        event = TrajectoryEvent(
            event_type=TrajectoryEventType.USER_INPUT,
            session_id="test-session",
            agent_id="test-agent",
            user_id="test-user",
        )
        
        assert event.event_type == TrajectoryEventType.USER_INPUT
        assert event.session_id == "test-session"
        assert event.agent_id == "test-agent"
        assert event.user_id == "test-user"
        assert event.timestamp != ""
        assert event.span_id != ""
    
    def test_create_event_with_data(self):
        """测试创建带数据的事件"""
        event = TrajectoryEvent(
            event_type=TrajectoryEventType.LLM_CALL_START,
            session_id="test-session",
            agent_id="test-agent",
            user_id="test-user",
            data={"prompt": "Hello", "model": "gpt-4"},
            duration_ms=100.5,
            status="success",
        )
        
        assert event.data == {"prompt": "Hello", "model": "gpt-4"}
        assert event.duration_ms == 100.5
        assert event.status == "success"
    
    def test_event_to_dict(self):
        """测试事件转换为字典"""
        event = TrajectoryEvent(
            event_type=TrajectoryEventType.TOOL_CALL_END,
            session_id="test-session",
            agent_id="test-agent",
            user_id="test-user",
            data={"result": "done"},
            duration_ms=50.0,
        )
        
        event_dict = event.to_dict()
        
        assert event_dict["event_type"] == "tool_call_end"
        assert event_dict["session_id"] == "test-session"
        assert event_dict["duration_ms"] == 50.0
    
    def test_event_from_dict(self):
        """测试从字典创建事件"""
        event_data = {
            "event_type": "session_end",
            "timestamp": "2024-01-01T00:00:00",
            "session_id": "test-session",
            "agent_id": "test-agent",
            "user_id": "test-user",
            "data": {"reason": "timeout"},
            "duration_ms": 0.0,
            "status": "error",
            "error_message": "Connection timeout",
        }
        
        event = TrajectoryEvent.from_dict(event_data)
        
        assert event.event_type == TrajectoryEventType.SESSION_END
        assert event.session_id == "test-session"
        assert event.error_message == "Connection timeout"


class TestTrajectorySpan:
    """测试TrajectorySpan数据类"""
    
    def test_create_span_basic(self):
        """测试创建基本span"""
        span = TrajectorySpan(
            operation_name="llm_call",
            operation_type="deepseek-chat",
            session_id="test-session",
            agent_id="test-agent",
            user_id="test-user",
        )
        
        assert span.operation_name == "llm_call"
        assert span.operation_type == "deepseek-chat"
        assert span.status == "running"
        assert span.start_time != ""
    
    def test_span_end(self):
        """测试结束span"""
        span = TrajectorySpan(
            operation_name="tool_execution",
            operation_type="file_read",
        )
        
        span.end(status="success")
        
        assert span.status == "success"
        assert span.end_time != ""
        assert span.duration_ms >= 0.0
    
    def test_span_add_event(self):
        """测试向span添加事件"""
        span = TrajectorySpan(
            operation_name="llm_call",
            operation_type="deepseek-chat",
        )
        
        event = TrajectoryEvent(
            event_type=TrajectoryEventType.LLM_CALL_STREAM_CHUNK,
            data={"chunk": "Hello"},
        )
        
        span.add_event(event)
        
        assert len(span.events) == 1
        assert span.events[0].event_type == TrajectoryEventType.LLM_CALL_STREAM_CHUNK
        assert span.events[0].span_id == span.span_id
    
    def test_span_to_dict(self):
        """测试span转换为字典"""
        span = TrajectorySpan(
            span_id="test-span-123",
            trace_id="test-trace-456",
            operation_name="test_operation",
            tags={"tag1": "value1"},
        )
        
        span_dict = span.to_dict()
        
        assert span_dict["span_id"] == "test-span-123"
        assert span_dict["trace_id"] == "test-trace-456"
        assert span_dict["tags"] == {"tag1": "value1"}
    
    def test_span_from_dict(self):
        """测试从字典创建span"""
        span_data = {
            "span_id": "test-span",
            "trace_id": "test-trace",
            "operation_name": "test_op",
            "operation_type": "test_type",
            "events": [
                {
                    "event_type": "session_start",
                    "timestamp": "2024-01-01T00:00:00",
                    "session_id": "test",
                    "agent_id": "test",
                    "user_id": "test",
                }
            ],
        }
        
        span = TrajectorySpan.from_dict(span_data)
        
        assert span.span_id == "test-span"
        assert span.trace_id == "test-trace"
        assert len(span.events) == 1


class TestTrajectory:
    """测试Trajectory数据类"""
    
    def test_create_trajectory_basic(self):
        """测试创建基本轨迹"""
        trajectory = Trajectory(
            trace_id="test-trace-123",
            session_id="test-session",
            agent_id="test-agent",
            user_id="test-user",
        )
        
        assert trajectory.trace_id == "test-trace-123"
        assert trajectory.session_id == "test-session"
        assert len(trajectory.spans) == 0
    
    def test_add_span(self):
        """测试向轨迹添加span"""
        trajectory = Trajectory(trace_id="test-trace")
        span1 = TrajectorySpan(span_id="span1", operation_name="op1")
        span2 = TrajectorySpan(span_id="span2", operation_name="op2", parent_span_id="span1")
        
        trajectory.add_span(span1)
        trajectory.add_span(span2)
        
        assert len(trajectory.spans) == 2
        assert "span1" in trajectory.spans
        assert "span2" in trajectory.spans
        assert "span2" in trajectory.spans["span1"].child_spans
    
    def test_get_span(self):
        """测试获取span"""
        trajectory = Trajectory(trace_id="test-trace")
        span = TrajectorySpan(span_id="test-span", operation_name="test_op")
        
        trajectory.add_span(span)
        
        retrieved = trajectory.get_span("test-span")
        assert retrieved is not None
        assert retrieved.span_id == "test-span"
        
        assert trajectory.get_span("non-existent") is None
    
    def test_end_trajectory(self):
        """测试结束轨迹"""
        trajectory = Trajectory(trace_id="test-trace")
        
        trajectory.end()
        
        assert trajectory.end_time != ""
        assert trajectory.total_duration_ms >= 0.0
    
    def test_trajectory_to_dict(self):
        """测试轨迹转换为字典"""
        trajectory = Trajectory(
            trace_id="test-trace",
            session_id="test-session",
            metadata={"key": "value"},
        )
        
        trajectory_dict = trajectory.to_dict()
        
        assert trajectory_dict["trace_id"] == "test-trace"
        assert trajectory_dict["session_id"] == "test-session"
        assert trajectory_dict["metadata"] == {"key": "value"}
    
    def test_trajectory_from_dict(self):
        """测试从字典创建轨迹"""
        traj_data = {
            "trace_id": "test-trace",
            "session_id": "test-session",
            "agent_id": "test-agent",
            "spans": {
                "span1": {
                    "span_id": "span1",
                    "operation_name": "op1",
                }
            },
        }
        
        trajectory = Trajectory.from_dict(traj_data)
        
        assert trajectory.trace_id == "test-trace"
        assert len(trajectory.spans) == 1
        assert "span1" in trajectory.spans
    
    def test_trajectory_json_conversion(self):
        """测试轨迹JSON转换"""
        trajectory = Trajectory(
            trace_id="test-trace",
            session_id="test-session",
        )
        
        json_str = trajectory.to_json()
        assert isinstance(json_str, str)
        
        restored = Trajectory.from_json(json_str)
        assert restored.trace_id == "test-trace"
