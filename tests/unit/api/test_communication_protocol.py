"""
测试通信协议

覆盖: neurova/api/communication_protocol.py
"""

import json
import time
from datetime import datetime, timezone
import pytest
from neurova.api.communication_protocol import (
    MessageType,
    ConnectionStatus,
    ProtocolMessage,
    HandshakeRequest,
    HandshakeResponse,
    CommunicationProtocol,
)

# ============================================================
# MessageType
# ============================================================

class TestMessageType:
    """消息类型枚举"""

    def test_basic_types(self):
        assert MessageType.HANDSHAKE.value == "handshake"
        assert MessageType.MESSAGE.value == "message"
        assert MessageType.MESSAGE_ACK.value == "message_ack"
        assert MessageType.HEARTBEAT.value == "heartbeat"
        assert MessageType.ERROR.value == "error"

    def test_from_string(self):
        assert MessageType("heartbeat") == MessageType.HEARTBEAT


# ============================================================
# ConnectionStatus
# ============================================================

class TestConnectionStatus:
    """连接状态枚举"""

    def test_values(self):
        assert ConnectionStatus.DISCONNECTED.value == "disconnected"
        assert ConnectionStatus.HANDSHAKING.value == "handshaking"
        assert ConnectionStatus.CONNECTED.value == "connected"
        assert ConnectionStatus.CLOSING.value == "closing"
        assert ConnectionStatus.ERROR.value == "error"

    def test_from_string(self):
        assert ConnectionStatus("disconnected") == ConnectionStatus.DISCONNECTED


# ============================================================
# ProtocolMessage
# ============================================================

class TestProtocolMessage:
    """协议消息"""

    def test_create_minimal(self):
        msg = ProtocolMessage(
            message_id="msg_001",
            message_type=MessageType.MESSAGE,
            sender_id="agent_1",
            receiver_id="server",
            timestamp=1000.0,
            payload={},
        )
        assert msg.message_id == "msg_001"
        assert msg.message_type == MessageType.MESSAGE
        assert msg.sender_id == "agent_1"
        assert msg.payload == {}
        assert msg.correlation_id is None

    def test_create_full(self):
        msg = ProtocolMessage(
            message_id="msg_002",
            message_type=MessageType.MESSAGE_ACK,
            sender_id="server",
            receiver_id="agent_1",
            timestamp=2000.0,
            payload={"status": "ok"},
            correlation_id="msg_001",
        )
        assert msg.correlation_id == "msg_001"
        assert msg.payload["status"] == "ok"

    def test_to_dict(self):
        msg = ProtocolMessage(
            message_id="m1",
            message_type=MessageType.HEARTBEAT,
            sender_id="a1",
            receiver_id="srv",
            timestamp=3000.0,
            payload={"seq": 1},
        )
        d = msg.to_dict()
        assert d["message_id"] == "m1"
        assert d["message_type"] == "heartbeat"
        assert d["sender_id"] == "a1"
        assert d["timestamp"] == 3000.0
        assert d["metadata"] == {}

    def test_from_dict(self):
        data = {
            "message_id": "m2",
            "message_type": "message",
            "sender_id": "agent_1",
            "receiver_id": "server",
            "timestamp": 4000.0,
            "payload": {"text": "hello"},
            "correlation_id": None,
        }
        msg = ProtocolMessage.from_dict(data)
        assert msg.message_id == "m2"
        assert msg.message_type == MessageType.MESSAGE
        assert msg.payload["text"] == "hello"

    def test_to_json_round_trip(self):
        original = ProtocolMessage(
            message_id="m3",
            message_type=MessageType.MESSAGE_ACK,
            sender_id="srv",
            receiver_id="a1",
            timestamp=5000.0,
            payload={"status": "received"},
            correlation_id="m1",
        )
        json_str = original.to_json()
        parsed = json.loads(json_str)
        assert parsed["message_id"] == "m3"
        assert parsed["message_type"] == "message_ack"

        restored = ProtocolMessage.from_json(json_str)
        assert restored.message_id == "m3"
        assert restored.correlation_id == "m1"

    def test_no_default_payload_mutation(self):
        """验证共享默认值不会跨实例污染"""
        msg1 = ProtocolMessage(
            message_id="m1", message_type=MessageType.MESSAGE,
            sender_id="a", receiver_id="b", timestamp=1.0,
            payload={},
        )
        msg2 = ProtocolMessage(
            message_id="m2", message_type=MessageType.MESSAGE,
            sender_id="a", receiver_id="b", timestamp=2.0,
            payload={},
        )
        msg1.metadata["custom"] = 1
        assert "custom" not in msg2.metadata


# ============================================================
# HandshakeRequest
# ============================================================

class TestHandshakeRequest:
    """握手请求"""

    def test_create(self):
        req = HandshakeRequest(
            handshake_id="h1",
            agent_id="agent_1",
            api_key="sk-xxx",
            protocol_version="1.0",
            capabilities=[],
            timestamp=100.0,
        )
        assert req.handshake_id == "h1"
        assert req.agent_id == "agent_1"
        assert req.capabilities == []

    def test_custom_capabilities(self):
        req = HandshakeRequest(
            handshake_id="h2",
            agent_id="agent_2",
            api_key="sk-yyy",
            protocol_version="2.0",
            timestamp=200.0,
            capabilities=["streaming", "memory_access"],
        )
        assert "streaming" in req.capabilities
        assert "memory_access" in req.capabilities

    def test_to_dict(self):
        req = HandshakeRequest(
            handshake_id="h3",
            agent_id="a1",
            api_key="sk-key",
            protocol_version="1.0",
            capabilities=[],
            timestamp=300.0,
        )
        d = req.to_dict()
        assert d["handshake_id"] == "h3"
        assert d["protocol_version"] == "1.0"
        assert "api_key" in d
        assert d["metadata"] == {}

    def test_from_dict(self):
        data = {
            "handshake_id": "h4",
            "agent_id": "a2",
            "api_key": "sk-secret",
            "protocol_version": "1.5",
            "capabilities": ["streaming"],
            "timestamp": 400.0,
        }
        req = HandshakeRequest.from_dict(data)
        assert req.agent_id == "a2"
        assert "streaming" in req.capabilities
        assert req.protocol_version == "1.5"


# ============================================================
# HandshakeResponse
# ============================================================

class TestHandshakeResponse:
    """握手响应"""

    def test_create_success(self):
        resp = HandshakeResponse(
            handshake_id="h1",
            success=True,
            agent_id="agent_1",
            session_id="sess_001",
            protocol_version="1.0",
            server_capabilities=["message_routing"],
            heartbeat_interval=30,
            timeout=300,
            timestamp=100.0,
        )
        assert resp.success is True
        assert resp.session_id == "sess_001"
        assert resp.error_message is None
        assert resp.metadata == {}

    def test_create_failure(self):
        resp = HandshakeResponse(
            handshake_id="h2",
            success=False,
            agent_id="agent_1",
            session_id="",
            protocol_version="1.0",
            server_capabilities=[],
            heartbeat_interval=0,
            timeout=0,
            timestamp=200.0,
            error_message="Invalid API key",
        )
        assert resp.success is False
        assert resp.error_message == "Invalid API key"

    def test_to_dict(self):
        resp = HandshakeResponse(
            handshake_id="h3",
            success=True,
            agent_id="a1",
            session_id="sess_002",
            protocol_version="1.0",
            server_capabilities=["memory_access"],
            heartbeat_interval=30,
            timeout=300,
            timestamp=300.0,
            metadata={"server_version": "1.0.0"},
        )
        d = resp.to_dict()
        assert d["success"] is True
        assert d["session_id"] == "sess_002"
        assert d["metadata"]["server_version"] == "1.0.0"

    def test_from_dict(self):
        data = {
            "handshake_id": "h4",
            "success": False,
            "agent_id": "a1",
            "session_id": "",
            "protocol_version": "1.0",
            "server_capabilities": [],
            "heartbeat_interval": 0,
            "timeout": 0,
            "timestamp": 400.0,
            "error_message": "版本不兼容",
            "metadata": {},
        }
        resp = HandshakeResponse.from_dict(data)
        assert resp.success is False
        assert resp.error_message == "版本不兼容"


# ============================================================
# CommunicationProtocol
# ============================================================

class TestCommunicationProtocol:
    """通信协议处理器"""

    def setup_method(self):
        self.proto = CommunicationProtocol()

    def test_initial_state(self):
        assert self.proto.PROTOCOL_VERSION == "1.0"
        assert self.proto.DEFAULT_HEARTBEAT_INTERVAL == 30
        assert self.proto.active_sessions == {}
        assert self.proto.message_counters == {}

    def test_create_handshake_request(self):
        req = self.proto.create_handshake_request(
            agent_id="agent_1",
            api_key="sk-xxx",
            capabilities=["streaming"],
        )
        assert req.agent_id == "agent_1"
        assert req.api_key == "sk-xxx"
        assert "streaming" in req.capabilities
        assert req.protocol_version == "1.0"
        assert req.handshake_id != ""
        assert req.timestamp > 0

    def test_create_handshake_request_no_capabilities(self):
        req = self.proto.create_handshake_request("agent_1", "sk-xxx")
        assert req.capabilities == []

    def test_create_handshake_response_success(self):
        req = self.proto.create_handshake_request("agent_1", "sk-xxx")
        resp = self.proto.create_handshake_response(req.handshake_id, True, "agent_1")
        assert resp.success is True
        assert resp.agent_id == "agent_1"
        assert resp.handshake_id == req.handshake_id
        assert resp.session_id != ""
        assert resp.protocol_version == "1.0"
        assert resp.heartbeat_interval == 30
        assert resp.timeout == 300
        assert "message_routing" in resp.server_capabilities
        assert resp.error_message is None

    def test_create_handshake_response_failure(self):
        resp = self.proto.create_handshake_response(
            handshake_id="h1",
            success=False,
            agent_id="agent_1",
            error_message="认证失败",
        )
        assert resp.success is False
        assert resp.session_id == ""
        assert resp.error_message == "认证失败"

    def test_validate_handshake_version_mismatch(self):
        req = HandshakeRequest(
            handshake_id="h1",
            agent_id="a1",
            api_key="sk-xxx",
            protocol_version="0.5",
            capabilities=[],
            timestamp=time.time(),
        )
        success, error = self.proto.validate_handshake(req)
        assert success is False
        assert "协议版本" in error

    def test_validate_handshake_wrong_api_key_length(self):
        """API 密钥必须是 36 位"""
        req = self.proto.create_handshake_request("agent_1", "too-short")
        success, error = self.proto.validate_handshake(req)
        assert success is False
        assert "API密钥格式" in error or "36位" in error

    def test_validate_handshake_success(self):
        # 36 字符的 API 密钥
        api_key = "sk-" + "a" * 33  # 3 + 33 = 36
        req = self.proto.create_handshake_request("agent_1", api_key)
        success, error = self.proto.validate_handshake(req)
        assert success is True, f"expected True, got error: {error}"
        assert error is None

    def test_create_message(self):
        msg = self.proto.create_message(
            sender_id="agent_1",
            receiver_id="server",
            payload={"text": "hello"},
        )
        assert msg.message_type == MessageType.MESSAGE
        assert msg.sender_id == "agent_1"
        assert msg.receiver_id == "server"
        assert msg.payload["text"] == "hello"
        assert msg.message_id != ""
        assert msg.timestamp > 0

    def test_check_rate_limit_first_request(self):
        allowed, wait = self.proto.check_rate_limit("session_1")
        assert allowed is True
        assert wait is None

    def test_check_rate_limit_under_limit(self):
        for _ in range(50):
            self.proto.check_rate_limit("session_2")
        allowed, wait = self.proto.check_rate_limit("session_2")
        assert allowed is True
        assert wait is None

    def test_create_heartbeat(self):
        msg = self.proto.create_heartbeat("session_1", "agent_1")
        assert msg.message_type == MessageType.HEARTBEAT
        assert msg.sender_id == "agent_1"
        assert msg.receiver_id == "server"
        assert msg.payload["session_id"] == "session_1"

    def test_register_handshake_handler(self):
        handler_called = False

        def dummy_handler(req):
            nonlocal handler_called
            handler_called = True
            return True, ""

        self.proto.register_handshake_handler(dummy_handler)
        assert len(self.proto.handshake_handlers) == 1

    def test_register_message_handler(self):
        messages = []

        def collector(msg):
            messages.append(msg)

        self.proto.register_message_handler(collector)
        assert len(self.proto.message_handlers) == 1

        msg = self.proto.create_message("a1", "srv", {"text": "hi"})
        self.proto.process_message(msg)
        assert len(messages) == 1
        assert messages[0].message_id == msg.message_id

    def test_process_message_returns_ack(self):
        msg = self.proto.create_message("agent_1", "server", {"text": "ping"})
        response = self.proto.process_message(msg)
        assert response is not None
        assert response.message_type == MessageType.MESSAGE_ACK
        assert response.correlation_id == msg.message_id
        assert response.payload["status"] == "received"

    def test_process_heartbeat_returns_none(self):
        msg = self.proto.create_heartbeat("session_1", "agent_1")
        response = self.proto.process_message(msg)
        assert response is None

    def test_cleanup_session(self):
        # 先建立会话
        req = self.proto.create_handshake_request("agent_1", "sk-key")
        # 手动注册会话
        self.proto.active_sessions["session_1"] = {
            "agent_id": "agent_1",
            "created_at": 100.0,
        }
        self.proto.message_counters["session_1"] = [100.0, 200.0]

        self.proto.cleanup_session("session_1")
        assert "session_1" not in self.proto.active_sessions
        assert "session_1" not in self.proto.message_counters
