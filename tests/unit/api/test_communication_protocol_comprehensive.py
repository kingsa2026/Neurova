"""
全面单元测试 - communication_protocol 模块

测试 neurova/api/communication_protocol.py
覆盖所有公共类、方法、边界情况和错误处理。
"""

import pytest
import time
import uuid
from typing import Dict, Any, List


# 导入要测试的模块
from neurova.api.communication_protocol import (
    MessageType,
    ConnectionStatus,
    ProtocolMessage,
    HandshakeRequest,
    HandshakeResponse,
    CommunicationProtocol,
    get_communication_protocol,
)


class TestMessageType:
    """测试 MessageType 枚举"""
    
    def test_handshake(self):
        """测试 HANDSHAKE 枚举值"""
        assert MessageType.HANDSHAKE.value == "handshake"
    
    def test_handshake_response(self):
        """测试 HANDSHAKE_RESPONSE 枚举值"""
        assert MessageType.HANDSHAKE_RESPONSE.value == "handshake_response"
    
    def test_heartbeat(self):
        """测试 HEARTBEAT 枚举值"""
        assert MessageType.HEARTBEAT.value == "heartbeat"
    
    def test_heartbeat_response(self):
        """测试 HEARTBEAT_RESPONSE 枚举值"""
        assert MessageType.HEARTBEAT_RESPONSE.value == "heartbeat_response"
    
    def test_message(self):
        """测试 MESSAGE 枚举值"""
        assert MessageType.MESSAGE.value == "message"
    
    def test_message_ack(self):
        """测试 MESSAGE_ACK 枚举值"""
        assert MessageType.MESSAGE_ACK.value == "message_ack"
    
    def test_error(self):
        """测试 ERROR 枚举值"""
        assert MessageType.ERROR.value == "error"
    
    def test_close(self):
        """测试 CLOSE 枚举值"""
        assert MessageType.CLOSE.value == "close"
    
    def test_all_values_unique(self):
        """测试所有枚举值都是唯一的"""
        values = [e.value for e in MessageType]
        assert len(values) == len(set(values))


class TestConnectionStatus:
    """测试 ConnectionStatus 枚举"""
    
    def test_disconnected(self):
        """测试 DISCONNECTED 枚举值"""
        assert ConnectionStatus.DISCONNECTED.value == "disconnected"
    
    def test_handshaking(self):
        """测试 HANDSHAKING 枚举值"""
        assert ConnectionStatus.HANDSHAKING.value == "handshaking"
    
    def test_connected(self):
        """测试 CONNECTED 枚举值"""
        assert ConnectionStatus.CONNECTED.value == "connected"
    
    def test_closing(self):
        """测试 CLOSING 枚举值"""
        assert ConnectionStatus.CLOSING.value == "closing"
    
    def test_error(self):
        """测试 ERROR 枚举值"""
        assert ConnectionStatus.ERROR.value == "error"
    
    def test_all_values_unique(self):
        """测试所有枚举值都是唯一的"""
        values = [e.value for e in ConnectionStatus]
        assert len(values) == len(set(values))


class TestProtocolMessage:
    """测试 ProtocolMessage 数据类"""
    
    def test_creation_minimal(self):
        """测试创建 ProtocolMessage（最小参数）"""
        msg = ProtocolMessage(
            message_id="msg_001",
            message_type=MessageType.MESSAGE,
            sender_id="agent_001",
            receiver_id="agent_002",
            timestamp=time.time(),
            payload={"content": "Hello"}
        )
        
        assert msg.message_id == "msg_001"
        assert msg.message_type == MessageType.MESSAGE
        assert msg.sender_id == "agent_001"
        assert msg.receiver_id == "agent_002"
        assert isinstance(msg.timestamp, float)
        assert msg.payload == {"content": "Hello"}
        assert msg.correlation_id is None
        assert msg.metadata == {}
    
    def test_creation_full(self):
        """测试创建 ProtocolMessage（全部参数）"""
        msg = ProtocolMessage(
            message_id="msg_001",
            message_type=MessageType.MESSAGE,
            sender_id="agent_001",
            receiver_id="agent_002",
            timestamp=time.time(),
            payload={"content": "Hello"},
            correlation_id="corr_001",
            metadata={"source": "test"}
        )
        
        assert msg.message_id == "msg_001"
        assert msg.correlation_id == "corr_001"
        assert msg.metadata == {"source": "test"}
    
    def test_to_dict(self):
        """测试 to_dict 方法"""
        msg = ProtocolMessage(
            message_id="msg_001",
            message_type=MessageType.MESSAGE,
            sender_id="agent_001",
            receiver_id="agent_002",
            timestamp=1234567890.123,
            payload={"content": "Hello"},
            correlation_id="corr_001",
            metadata={"source": "test"}
        )
        
        result = msg.to_dict()
        
        assert result["message_id"] == "msg_001"
        assert result["message_type"] == "message"
        assert result["sender_id"] == "agent_001"
        assert result["receiver_id"] == "agent_002"
        assert result["timestamp"] == 1234567890.123
        assert result["payload"] == {"content": "Hello"}
        assert result["correlation_id"] == "corr_001"
        assert result["metadata"] == {"source": "test"}
    
    def test_from_dict(self):
        """测试 from_dict 方法"""
        data = {
            "message_id": "msg_001",
            "message_type": "message",
            "sender_id": "agent_001",
            "receiver_id": "agent_002",
            "timestamp": 1234567890.123,
            "payload": {"content": "Hello"},
            "correlation_id": "corr_001",
            "metadata": {"source": "test"}
        }
        
        msg = ProtocolMessage.from_dict(data)
        
        assert msg.message_id == "msg_001"
        assert msg.message_type == MessageType.MESSAGE
        assert msg.sender_id == "agent_001"
        assert msg.receiver_id == "agent_002"
        assert msg.timestamp == 1234567890.123
        assert msg.payload == {"content": "Hello"}
        assert msg.correlation_id == "corr_001"
        assert msg.metadata == {"source": "test"}
    
    def test_from_dict_no_optional(self):
        """测试 from_dict 方法（无可选字段）"""
        data = {
            "message_id": "msg_001",
            "message_type": "message",
            "sender_id": "agent_001",
            "receiver_id": "agent_002",
            "timestamp": 1234567890.123,
            "payload": {"content": "Hello"}
        }
        
        msg = ProtocolMessage.from_dict(data)
        
        assert msg.message_id == "msg_001"
        assert msg.correlation_id is None
        assert msg.metadata == {}
    
    def test_to_json(self):
        """测试 to_json 方法"""
        msg = ProtocolMessage(
            message_id="msg_001",
            message_type=MessageType.MESSAGE,
            sender_id="agent_001",
            receiver_id="agent_002",
            timestamp=1234567890.123,
            payload={"content": "Hello"}
        )
        
        json_str = msg.to_json()
        
        assert isinstance(json_str, str)
        assert "msg_001" in json_str
        assert "message" in json_str
    
    def test_from_json(self):
        """测试 from_json 方法"""
        json_str = '{"message_id": "msg_001", "message_type": "message", "sender_id": "agent_001", "receiver_id": "agent_002", "timestamp": 1234567890.123, "payload": {"content": "Hello"}}'
        
        msg = ProtocolMessage.from_json(json_str)
        
        assert msg.message_id == "msg_001"
        assert msg.message_type == MessageType.MESSAGE
        assert msg.sender_id == "agent_001"
    
    def test_round_trip(self):
        """测试往返转换（to_dict → from_dict）"""
        msg1 = ProtocolMessage(
            message_id="msg_001",
            message_type=MessageType.MESSAGE,
            sender_id="agent_001",
            receiver_id="agent_002",
            timestamp=time.time(),
            payload={"content": "Hello"},
            correlation_id="corr_001",
            metadata={"source": "test"}
        )
        
        # to_dict → from_dict
        data = msg1.to_dict()
        msg2 = ProtocolMessage.from_dict(data)
        
        assert msg1.message_id == msg2.message_id
        assert msg1.message_type == msg2.message_type
        assert msg1.sender_id == msg2.sender_id
        assert msg1.receiver_id == msg2.receiver_id
        assert msg1.timestamp == msg2.timestamp
        assert msg1.payload == msg2.payload
        assert msg1.correlation_id == msg2.correlation_id
        assert msg1.metadata == msg2.metadata
    
    def test_round_trip_json(self):
        """测试往返转换（to_json → from_json）"""
        msg1 = ProtocolMessage(
            message_id="msg_001",
            message_type=MessageType.MESSAGE,
            sender_id="agent_001",
            receiver_id="agent_002",
            timestamp=time.time(),
            payload={"content": "Hello"}
        )
        
        # to_json → from_json
        json_str = msg1.to_json()
        msg2 = ProtocolMessage.from_json(json_str)
        
        assert msg1.message_id == msg2.message_id
        assert msg1.message_type == msg2.message_type
        assert msg1.sender_id == msg2.sender_id


class TestHandshakeRequest:
    """测试 HandshakeRequest 数据类"""
    
    def test_creation_minimal(self):
        """测试创建 HandshakeRequest（最小参数）"""
        req = HandshakeRequest(
            handshake_id="hs_001",
            agent_id="agent_001",
            api_key="a" * 36,  # 36位
            protocol_version="1.0",
            capabilities=[],
            timestamp=time.time()
        )
        
        assert req.handshake_id == "hs_001"
        assert req.agent_id == "agent_001"
        assert req.api_key == "a" * 36
        assert req.protocol_version == "1.0"
        assert req.capabilities == []
        assert isinstance(req.timestamp, float)
        assert req.metadata == {}
    
    def test_creation_full(self):
        """测试创建 HandshakeRequest（全部参数）"""
        req = HandshakeRequest(
            handshake_id="hs_001",
            agent_id="agent_001",
            api_key="a" * 36,
            protocol_version="1.0",
            capabilities=["memory_access", "streaming"],
            timestamp=time.time(),
            metadata={"source": "test"}
        )
        
        assert req.capabilities == ["memory_access", "streaming"]
        assert req.metadata == {"source": "test"}
    
    def test_to_dict(self):
        """测试 to_dict 方法"""
        req = HandshakeRequest(
            handshake_id="hs_001",
            agent_id="agent_001",
            api_key="a" * 36,
            protocol_version="1.0",
            capabilities=["memory_access"],
            timestamp=1234567890.123,
            metadata={"source": "test"}
        )
        
        result = req.to_dict()
        
        assert result["handshake_id"] == "hs_001"
        assert result["agent_id"] == "agent_001"
        assert result["api_key"] == "a" * 36
        assert result["protocol_version"] == "1.0"
        assert result["capabilities"] == ["memory_access"]
        assert result["timestamp"] == 1234567890.123
        assert result["metadata"] == {"source": "test"}
    
    def test_from_dict(self):
        """测试 from_dict 方法"""
        data = {
            "handshake_id": "hs_001",
            "agent_id": "agent_001",
            "api_key": "a" * 36,
            "protocol_version": "1.0",
            "capabilities": ["memory_access"],
            "timestamp": 1234567890.123,
            "metadata": {"source": "test"}
        }
        
        req = HandshakeRequest.from_dict(data)
        
        assert req.handshake_id == "hs_001"
        assert req.agent_id == "agent_001"
        assert req.api_key == "a" * 36
        assert req.protocol_version == "1.0"
        assert req.capabilities == ["memory_access"]
        assert req.timestamp == 1234567890.123
        assert req.metadata == {"source": "test"}
    
    def test_from_dict_no_optional(self):
        """测试 from_dict 方法（无可选字段）"""
        data = {
            "handshake_id": "hs_001",
            "agent_id": "agent_001",
            "api_key": "a" * 36,
            "protocol_version": "1.0",
            "capabilities": [],
            "timestamp": 1234567890.123
        }
        
        req = HandshakeRequest.from_dict(data)
        
        assert req.handshake_id == "hs_001"
        assert req.metadata == {}


class TestHandshakeResponse:
    """测试 HandshakeResponse 数据类"""
    
    def test_creation_success(self):
        """测试创建 HandshakeResponse（成功）"""
        resp = HandshakeResponse(
            handshake_id="hs_001",
            success=True,
            agent_id="agent_001",
            session_id="sess_001",
            protocol_version="1.0",
            server_capabilities=["message_routing", "memory_access"],
            heartbeat_interval=30,
            timeout=300,
            timestamp=time.time()
        )
        
        assert resp.handshake_id == "hs_001"
        assert resp.success == True
        assert resp.agent_id == "agent_001"
        assert resp.session_id == "sess_001"
        assert resp.protocol_version == "1.0"
        assert resp.server_capabilities == ["message_routing", "memory_access"]
        assert resp.heartbeat_interval == 30
        assert resp.timeout == 300
        assert isinstance(resp.timestamp, float)
        assert resp.error_message is None
        assert resp.metadata == {}
    
    def test_creation_failure(self):
        """测试创建 HandshakeResponse（失败）"""
        resp = HandshakeResponse(
            handshake_id="hs_001",
            success=False,
            agent_id="",
            session_id="",
            protocol_version="1.0",
            server_capabilities=[],
            heartbeat_interval=30,
            timeout=300,
            timestamp=time.time(),
            error_message="API key invalid"
        )
        
        assert resp.success == False
        assert resp.agent_id == ""
        assert resp.session_id == ""
        assert resp.error_message == "API key invalid"
    
    def test_to_dict(self):
        """测试 to_dict 方法"""
        resp = HandshakeResponse(
            handshake_id="hs_001",
            success=True,
            agent_id="agent_001",
            session_id="sess_001",
            protocol_version="1.0",
            server_capabilities=["message_routing"],
            heartbeat_interval=30,
            timeout=300,
            timestamp=1234567890.123,
            error_message=None,
            metadata={"source": "test"}
        )
        
        result = resp.to_dict()
        
        assert result["handshake_id"] == "hs_001"
        assert result["success"] == True
        assert result["agent_id"] == "agent_001"
        assert result["session_id"] == "sess_001"
        assert result["protocol_version"] == "1.0"
        assert result["server_capabilities"] == ["message_routing"]
        assert result["heartbeat_interval"] == 30
        assert result["timeout"] == 300
        assert result["timestamp"] == 1234567890.123
        assert result["error_message"] is None
        assert result["metadata"] == {"source": "test"}
    
    def test_from_dict(self):
        """测试 from_dict 方法"""
        data = {
            "handshake_id": "hs_001",
            "success": True,
            "agent_id": "agent_001",
            "session_id": "sess_001",
            "protocol_version": "1.0",
            "server_capabilities": ["message_routing"],
            "heartbeat_interval": 30,
            "timeout": 300,
            "timestamp": 1234567890.123,
            "error_message": None,
            "metadata": {"source": "test"}
        }
        
        resp = HandshakeResponse.from_dict(data)
        
        assert resp.handshake_id == "hs_001"
        assert resp.success == True
        assert resp.agent_id == "agent_001"
        assert resp.session_id == "sess_001"
        assert resp.protocol_version == "1.0"
        assert resp.server_capabilities == ["message_routing"]
        assert resp.heartbeat_interval == 30
        assert resp.timeout == 300
        assert resp.timestamp == 1234567890.123
        assert resp.error_message is None
        assert resp.metadata == {"source": "test"}
    
    def test_from_dict_no_optional(self):
        """测试 from_dict 方法（无可选字段）"""
        data = {
            "handshake_id": "hs_001",
            "success": False,
            "agent_id": "",
            "session_id": "",
            "protocol_version": "1.0",
            "server_capabilities": [],
            "heartbeat_interval": 30,
            "timeout": 300,
            "timestamp": 1234567890.123
        }
        
        resp = HandshakeResponse.from_dict(data)
        
        assert resp.handshake_id == "hs_001"
        assert resp.error_message is None
        assert resp.metadata == {}


class TestCommunicationProtocolInit:
    """测试 CommunicationProtocol 初始化"""
    
    def test_init(self):
        """测试初始化"""
        protocol = CommunicationProtocol()
        
        assert protocol.PROTOCOL_VERSION == "1.0"
        assert protocol.DEFAULT_HEARTBEAT_INTERVAL == 30
        assert protocol.DEFAULT_TIMEOUT == 300
        assert protocol.MAX_MESSAGE_RATE == 100
        assert protocol.active_sessions == {}
        assert protocol.message_counters == {}
        assert protocol.handshake_handlers == []
        assert protocol.message_handlers == []


class TestCreateHandshakeRequest:
    """测试 create_handshake_request 方法"""
    
    def test_create(self):
        """测试创建握手请求"""
        protocol = CommunicationProtocol()
        
        req = protocol.create_handshake_request(
            agent_id="agent_001",
            api_key="a" * 36,
            capabilities=["memory_access", "streaming"]
        )
        
        assert isinstance(req, HandshakeRequest)
        assert req.agent_id == "agent_001"
        assert req.api_key == "a" * 36
        assert req.protocol_version == "1.0"
        assert req.capabilities == ["memory_access", "streaming"]
        assert isinstance(req.handshake_id, str)
        assert len(req.handshake_id) > 0
        assert isinstance(req.timestamp, float)
    
    def test_create_no_capabilities(self):
        """测试创建握手请求（无 capabilities）"""
        protocol = CommunicationProtocol()
        
        req = protocol.create_handshake_request(
            agent_id="agent_001",
            api_key="a" * 36
        )
        
        assert req.capabilities == []
    
    def test_create_unique_handshake_id(self):
        """测试创建的握手请求有唯一的 handshake_id"""
        protocol = CommunicationProtocol()
        
        req1 = protocol.create_handshake_request(agent_id="agent_001", api_key="a" * 36)
        req2 = protocol.create_handshake_request(agent_id="agent_001", api_key="a" * 36)
        
        assert req1.handshake_id != req2.handshake_id


class TestCreateHandshakeResponse:
    """测试 create_handshake_response 方法"""
    
    def test_create_success(self):
        """测试创建握手响应（成功）"""
        protocol = CommunicationProtocol()
        
        resp = protocol.create_handshake_response(
            handshake_id="hs_001",
            success=True,
            agent_id="agent_001"
        )
        
        assert isinstance(resp, HandshakeResponse)
        assert resp.handshake_id == "hs_001"
        assert resp.success == True
        assert resp.agent_id == "agent_001"
        assert resp.session_id != ""  # 成功时应该生成 session_id
        assert resp.protocol_version == "1.0"
        assert resp.server_capabilities == ["message_routing", "memory_access", "streaming"]
        assert resp.heartbeat_interval == 30
        assert resp.timeout == 300
        assert isinstance(resp.timestamp, float)
        assert resp.error_message is None
    
    def test_create_failure(self):
        """测试创建握手响应（失败）"""
        protocol = CommunicationProtocol()
        
        resp = protocol.create_handshake_response(
            handshake_id="hs_001",
            success=False,
            agent_id="agent_001",
            error_message="API key invalid"
        )
        
        assert resp.success == False
        assert resp.session_id == ""  # 失败时 session_id 为空
        assert resp.error_message == "API key invalid"
    
    def test_create_with_metadata(self):
        """测试创建握手响应（带 metadata）"""
        protocol = CommunicationProtocol()
        
        resp = protocol.create_handshake_response(
            handshake_id="hs_001",
            success=True,
            agent_id="agent_001",
            metadata={"source": "test"}
        )
        
        assert resp.metadata == {"source": "test"}


class TestValidateHandshake:
    """测试 validate_handshake 方法"""
    
    def test_validate_success(self):
        """测试验证握手请求（成功）"""
        protocol = CommunicationProtocol()
        
        req = protocol.create_handshake_request(
            agent_id="agent_001",
            api_key="a" * 36
        )
        
        success, error = protocol.validate_handshake(req)
        
        assert success == True
        assert error is None
    
    def test_validate_wrong_protocol_version(self):
        """测试验证握手请求（协议版本错误）"""
        protocol = CommunicationProtocol()
        
        req = protocol.create_handshake_request(
            agent_id="agent_001",
            api_key="a" * 36
        )
        req.protocol_version = "2.0"  # 错误的协议版本
        
        success, error = protocol.validate_handshake(req)
        
        assert success == False
        assert "不支持的协议版本" in error
    
    def test_validate_timestamp_too_old(self):
        """测试验证握手请求（时间戳太旧）"""
        protocol = CommunicationProtocol()
        
        req = protocol.create_handshake_request(
            agent_id="agent_001",
            api_key="a" * 36
        )
        req.timestamp = time.time() - 120  # 120秒前（超过60秒偏差）
        
        success, error = protocol.validate_handshake(req)
        
        assert success == False
        assert "时间戳异常" in error
    
    def test_validate_timestamp_too_new(self):
        """测试验证握手请求（时间戳太新）"""
        protocol = CommunicationProtocol()
        
        req = protocol.create_handshake_request(
            agent_id="agent_001",
            api_key="a" * 36
        )
        req.timestamp = time.time() + 120  # 120秒后（超过60秒偏差）
        
        success, error = protocol.validate_handshake(req)
        
        assert success == False
        assert "时间戳异常" in error
    
    def test_validate_api_key_wrong_length(self):
        """测试验证握手请求（API密钥长度错误）"""
        protocol = CommunicationProtocol()
        
        req = protocol.create_handshake_request(
            agent_id="agent_001",
            api_key="short"  # 长度不是36
        )
        
        success, error = protocol.validate_handshake(req)
        
        assert success == False
        assert "API密钥格式错误" in error
    
    def test_validate_with_custom_handler(self):
        """测试验证握手请求（带自定义处理器）"""
        protocol = CommunicationProtocol()
        
        def custom_handler(request):
            return False, "Custom handler rejected"
        
        protocol.register_handshake_handler(custom_handler)
        
        req = protocol.create_handshake_request(
            agent_id="agent_001",
            api_key="a" * 36
        )
        
        success, error = protocol.validate_handshake(req)
        
        assert success == False
        assert "Custom handler rejected" in error


class TestCreateMessage:
    """测试 create_message 方法"""
    
    def test_create(self):
        """测试创建协议消息"""
        protocol = CommunicationProtocol()
        
        msg = protocol.create_message(
            sender_id="agent_001",
            receiver_id="agent_002",
            payload={"content": "Hello"}
        )
        
        assert isinstance(msg, ProtocolMessage)
        assert msg.message_type == MessageType.MESSAGE
        assert msg.sender_id == "agent_001"
        assert msg.receiver_id == "agent_002"
        assert msg.payload == {"content": "Hello"}
        assert isinstance(msg.message_id, str)
        assert len(msg.message_id) > 0
        assert isinstance(msg.timestamp, float)
        assert msg.correlation_id is None
        assert msg.metadata == {}
    
    def test_create_with_correlation_id(self):
        """测试创建协议消息（带 correlation_id）"""
        protocol = CommunicationProtocol()
        
        msg = protocol.create_message(
            sender_id="agent_001",
            receiver_id="agent_002",
            payload={"content": "Hello"},
            correlation_id="corr_001"
        )
        
        assert msg.correlation_id == "corr_001"
    
    def test_create_with_metadata(self):
        """测试创建协议消息（带 metadata）"""
        protocol = CommunicationProtocol()
        
        msg = protocol.create_message(
            sender_id="agent_001",
            receiver_id="agent_002",
            payload={"content": "Hello"},
            metadata={"source": "test"}
        )
        
        assert msg.metadata == {"source": "test"}
    
    def test_create_unique_message_id(self):
        """测试创建的消息有唯一的 message_id"""
        protocol = CommunicationProtocol()
        
        msg1 = protocol.create_message(
            sender_id="agent_001",
            receiver_id="agent_002",
            payload={"content": "Hello"}
        )
        msg2 = protocol.create_message(
            sender_id="agent_001",
            receiver_id="agent_002",
            payload={"content": "World"}
        )
        
        assert msg1.message_id != msg2.message_id


class TestCheckRateLimit:
    """测试 check_rate_limit 方法"""
    
    def test_check_within_limit(self):
        """测试检查速率限制（在限制内）"""
        protocol = CommunicationProtocol()
        session_id = "sess_001"
        
        # 发送 10 条消息（远低于 100 条/分钟）
        for i in range(10):
            success, error = protocol.check_rate_limit(session_id)
            assert success == True
            assert error is None
    
    def test_check_exceed_limit(self):
        """测试检查速率限制（超过限制）"""
        protocol = CommunicationProtocol()
        session_id = "sess_002"
        
        # 发送 101 条消息（超过 100 条/分钟）
        for i in range(protocol.MAX_MESSAGE_RATE):
            success, error = protocol.check_rate_limit(session_id)
            assert success == True
        
        # 第 101 条消息应该被限制
        success, error = protocol.check_rate_limit(session_id)
        assert success == False
        assert "速率超限" in error
    
    def test_check_multiple_sessions(self):
        """测试检查速率限制（多个会话）"""
        protocol = CommunicationProtocol()
        
        # 会话1发送 50 条消息
        for i in range(50):
            success, error = protocol.check_rate_limit("sess_001")
            assert success == True
        
        # 会话2发送 50 条消息
        for i in range(50):
            success, error = protocol.check_rate_limit("sess_002")
            assert success == True
        
        # 会话1应该还能发送 50 条
        for i in range(50):
            success, error = protocol.check_rate_limit("sess_001")
            assert success == True
        
        # 会话1现在应该被限制
        success, error = protocol.check_rate_limit("sess_001")
        assert success == False


class TestCreateHeartbeat:
    """测试 create_heartbeat 方法"""
    
    def test_create(self):
        """测试创建心跳消息"""
        protocol = CommunicationProtocol()
        
        msg = protocol.create_heartbeat(
            session_id="sess_001",
            agent_id="agent_001"
        )
        
        assert isinstance(msg, ProtocolMessage)
        assert msg.message_type == MessageType.HEARTBEAT
        assert msg.sender_id == "agent_001"
        assert msg.receiver_id == "server"
        assert msg.payload == {"session_id": "sess_001"}
        assert isinstance(msg.message_id, str)
        assert isinstance(msg.timestamp, float)
    
    def test_create_unique_message_id(self):
        """测试创建的心跳消息有唯一的 message_id"""
        protocol = CommunicationProtocol()
        
        msg1 = protocol.create_heartbeat(session_id="sess_001", agent_id="agent_001")
        msg2 = protocol.create_heartbeat(session_id="sess_001", agent_id="agent_001")
        
        assert msg1.message_id != msg2.message_id


class TestRegisterHandlers:
    """测试注册处理器方法"""
    
    def test_register_handshake_handler(self):
        """测试注册握手处理器"""
        protocol = CommunicationProtocol()
        
        assert len(protocol.handshake_handlers) == 0
        
        def handler(request):
            return True, None
        
        protocol.register_handshake_handler(handler)
        
        assert len(protocol.handshake_handlers) == 1
    
    def test_register_message_handler(self):
        """测试注册消息处理器"""
        protocol = CommunicationProtocol()
        
        assert len(protocol.message_handlers) == 0
        
        def handler(message):
            pass
        
        protocol.register_message_handler(handler)
        
        assert len(protocol.message_handlers) == 1


class TestProcessMessage:
    """测试 process_message 方法"""
    
    def test_process_message_type_message(self):
        """测试处理消息（类型为 MESSAGE）"""
        protocol = CommunicationProtocol()
        
        msg = protocol.create_message(
            sender_id="agent_001",
            receiver_id="agent_002",
            payload={"content": "Hello"}
        )
        
        response = protocol.process_message(msg)
        
        assert response is not None
        assert response.message_type == MessageType.MESSAGE_ACK
        assert response.correlation_id == msg.message_id
    
    def test_process_message_type_other(self):
        """测试处理消息（类型非 MESSAGE）"""
        protocol = CommunicationProtocol()
        
        msg = ProtocolMessage(
            message_id="msg_001",
            message_type=MessageType.HEARTBEAT,
            sender_id="agent_001",
            receiver_id="server",
            timestamp=time.time(),
            payload={"session_id": "sess_001"}
        )
        
        response = protocol.process_message(msg)
        
        assert response is None
    
    def test_process_message_with_handlers(self):
        """测试处理消息（带处理器）"""
        protocol = CommunicationProtocol()
        
        handled_messages = []
        
        def handler(message):
            handled_messages.append(message)
        
        protocol.register_message_handler(handler)
        
        msg = protocol.create_message(
            sender_id="agent_001",
            receiver_id="agent_002",
            payload={"content": "Hello"}
        )
        
        protocol.process_message(msg)
        
        assert len(handled_messages) == 1
        assert handled_messages[0].message_id == msg.message_id


class TestCleanupSession:
    """测试 cleanup_session 方法"""
    
    def test_cleanup_existing_session(self):
        """测试清理已存在的会话"""
        protocol = CommunicationProtocol()
        session_id = "sess_001"
        
        # 模拟会话存在
        protocol.active_sessions[session_id] = {"agent_id": "agent_001"}
        protocol.message_counters[session_id] = [time.time()]
        
        assert session_id in protocol.active_sessions
        assert session_id in protocol.message_counters
        
        protocol.cleanup_session(session_id)
        
        assert session_id not in protocol.active_sessions
        assert session_id not in protocol.message_counters
    
    def test_cleanup_non_existent_session(self):
        """测试清理不存在的会话"""
        protocol = CommunicationProtocol()
        session_id = "sess_999"
        
        # 会话不存在
        assert session_id not in protocol.active_sessions
        assert session_id not in protocol.message_counters
        
        # 清理不应该报错
        protocol.cleanup_session(session_id)
        
        assert session_id not in protocol.active_sessions
        assert session_id not in protocol.message_counters


class TestGetCommunicationProtocol:
    """测试 get_communication_protocol 函数（单例模式）"""
    
    def test_singleton(self):
        """测试单例模式"""
        protocol1 = get_communication_protocol()
        protocol2 = get_communication_protocol()
        
        assert protocol1 is protocol2
    
    def test_multiple_calls(self):
        """测试多次调用返回同一个实例"""
        p1 = get_communication_protocol()
        p2 = get_communication_protocol()
        p3 = get_communication_protocol()
        
        assert p1 is p2
        assert p2 is p3
        assert p1 is p3
