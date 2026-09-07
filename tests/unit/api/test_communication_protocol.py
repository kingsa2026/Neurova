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
        assert MessageType.HANDSHAKE_REQUEST.value == "handshake_request"
        assert MessageType.HANDSHAKE_RESPONSE.value == "handshake_response"
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
        assert ConnectionStatus.AUTHENTICATED.value == "authenticated"
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
        assert d["metadata"] is None

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
        if msg1.metadata is None:
            msg1.metadata = {}
        msg1.metadata["custom"] = 1
        assert not msg2.metadata or "custom" not in msg2.metadata


# ============================================================
# HandshakeRequest
# ============================================================

class TestHandshakeRequest:
    """握手请求"""

    def test_create(self):
        req = HandshakeRequest(
            client_id="h1",
            client_type="agent",
            client_version="1.0",
            capabilities=[],
        )
        assert req.client_id == "h1"
        assert req.client_type == "agent"
        assert req.capabilities == []

    def test_custom_capabilities(self):
        req = HandshakeRequest(
            client_id="h2",
            client_type="agent",
            client_version="2.0",
            capabilities=["streaming", "memory_access"],
        )
        assert "streaming" in req.capabilities
        assert "memory_access" in req.capabilities

    def test_to_dict(self):
        req = HandshakeRequest(
            client_id="h3",
            client_type="agent",
            client_version="1.0",
            capabilities=[],
        )
        d = req.to_dict()
        assert d["client_id"] == "h3"
        assert d["metadata"] is None

    def test_from_dict(self):
        data = {
            "client_id": "h4",
            "client_type": "cloud_code",
            "client_version": "1.5",
            "capabilities": ["streaming"],
        }
        req = HandshakeRequest.from_dict(data)
        assert req.client_id == "h4"
        assert "streaming" in req.capabilities
        assert req.client_version == "1.5"


# ============================================================
# HandshakeResponse
# ============================================================

class TestHandshakeResponse:
    """握手响应"""

    def test_create_success(self):
        resp = HandshakeResponse(
            server_id="srv",
            server_version="1.0.0",
            accepted=True,
            session_id="sess_001",
        )
        assert resp.accepted is True
        assert resp.session_id == "sess_001"
        assert resp.error_message is None

    def test_create_failure(self):
        resp = HandshakeResponse(
            server_id="srv",
            server_version="1.0.0",
            accepted=False,
            error_message="Invalid API key",
        )
        assert resp.accepted is False
        assert resp.error_message == "Invalid API key"

    def test_to_dict(self):
        resp = HandshakeResponse(
            server_id="a1",
            server_version="1.0.0",
            accepted=True,
            session_id="sess_002",
            metadata={"server_version": "1.0.0"},
        )
        d = resp.to_dict()
        assert d["accepted"] is True
        assert d["session_id"] == "sess_002"
        assert d["metadata"]["server_version"] == "1.0.0"

    def test_from_dict(self):
        data = {
            "server_id": "a1",
            "server_version": "1.0.0",
            "accepted": False,
            "error_message": "版本不兼容",
        }
        resp = HandshakeResponse.from_dict(data)
        assert resp.accepted is False
        assert resp.error_message == "版本不兼容"


# ============================================================
# CommunicationProtocol
# ============================================================

class TestCommunicationProtocol:
    """通信协议处理器（对齐实现 API）"""

    def setup_method(self):
        self.proto = CommunicationProtocol()

    def test_initial_state(self):
        assert self.proto.server_version == "1.0.0"
        assert self.proto.heartbeat_interval == 30.0
        assert self.proto._sessions == {}
        assert self.proto._rate_limits == {}

    def test_create_handshake_request(self):
        req = self.proto.create_handshake_request(
            client_id="agent_1",
            client_type="hermes",
            client_version="1.0",
            capabilities=["streaming"],
        )
        assert req.client_id == "agent_1"
        assert req.client_type == "hermes"
        assert "streaming" in req.capabilities
        assert req.supported_versions == ["1.0"]

    def test_create_handshake_request_no_capabilities(self):
        req = self.proto.create_handshake_request(
            client_id="agent_1",
            client_type="hermes",
            client_version="1.0",
            capabilities=[],
        )
        assert req.capabilities == []

    def test_create_handshake_response_success(self):
        resp = self.proto.create_handshake_response(
            accepted=True, session_id="sess_001",
        )
        assert resp.accepted is True
        assert resp.session_id == "sess_001"
        assert resp.error_message is None
        assert resp.heartbeat_interval == 30.0

    def test_create_handshake_response_failure(self):
        resp = self.proto.create_handshake_response(
            accepted=False, error_message="认证失败",
        )
        assert resp.accepted is False
        assert resp.error_message == "认证失败"

    def test_validate_handshake_version_mismatch(self):
        req = HandshakeRequest(
            client_id="a1",
            client_type="hermes",
            client_version="0.5",
            capabilities=[],
            supported_versions=["0.5"],
        )
        success, error = self.proto.validate_handshake(req)
        assert success is False
        assert "协议版本" in error

    def test_validate_handshake_unknown_client_type_warns_but_passes(self):
        """未知客户端类型仅告警不拒绝（实现口径）"""
        req = HandshakeRequest(
            client_id="a1",
            client_type="unknown_type",
            client_version="1.0",
            capabilities=[],
        )
        success, error = self.proto.validate_handshake(req)
        assert success is True

    def test_validate_handshake_success(self):
        req = HandshakeRequest(
            client_id="a1",
            client_type="hermes",
            client_version="1.0",
            capabilities=[],
        )
        success, error = self.proto.validate_handshake(req)
        assert success is True, f"expected True, got error: {error}"
        assert error is None

    def test_create_message(self):
        msg = self.proto.create_message(
            sender_id="agent_1",
            receiver_id="server",
            message_type=MessageType.MESSAGE,
            payload={"text": "hello"},
        )
        assert msg.message_type == MessageType.MESSAGE
        assert msg.sender_id == "agent_1"
        assert msg.receiver_id == "server"
        assert msg.payload["text"] == "hello"
        assert msg.message_id != ""
        assert msg.timestamp > 0

    def test_check_rate_limit_first_request(self):
        assert self.proto.check_rate_limit("session_1") is True

    def test_check_rate_limit_under_limit(self):
        for _ in range(50):
            self.proto.check_rate_limit("session_2")
        assert self.proto.check_rate_limit("session_2") is True

    def test_create_heartbeat(self):
        msg = self.proto.create_heartbeat("session_1", "agent_1")
        assert msg.message_type == MessageType.HEARTBEAT
        assert msg.sender_id == "session_1"
        assert msg.receiver_id == "agent_1"

    def test_register_handshake_handler(self):
        def dummy_handler(req):
            return True, ""

        self.proto.register_handshake_handler(dummy_handler)
        assert len(self.proto._handshake_handlers) == 1

    def test_register_message_handler(self):
        def collector(msg):
            pass

        self.proto.register_message_handler("message", collector)
        assert "message" in self.proto._message_handlers

    def test_process_heartbeat_returns_ack(self):
        """心跳 → HEARTBEAT_ACK（HEHeartbeat 拼写修复后语义生效）"""
        msg = self.proto.create_heartbeat("session_1", "agent_1")
        import asyncio

        response = asyncio.run(self.proto.process_message(msg))
        assert response is not None
        assert response.message_type == MessageType.HEARTBEAT_ACK
        assert response.correlation_id == msg.message_id

    def test_cleanup_session(self):
        self.proto._sessions["session_1"] = {
            "client_id": "agent_1",
            "created_at": 100.0,
        }
        self.proto.cleanup_session("session_1")
        assert "session_1" not in self.proto._sessions
