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


"""通信协议全面测试 — 对齐 neurova/api/communication_protocol.py 真实 API。

2026-09-07 重写：原文件按旧口径（HANDSHAKE/CLOSE 枚举、handshake_id 签名、
active_sessions 属性等）整篇失效；以实现为单一事实源重写。
"""

import asyncio
import json
import uuid

import pytest

from neurova.api.communication_protocol import (
    ConnectionStatus,
    CommunicationProtocol,
    HandshakeRequest,
    HandshakeResponse,
    MessageType,
    ProtocolMessage,
)


# ============================================================
# MessageType
# ============================================================

class TestMessageType:
    def test_handshake(self):
        assert MessageType.HANDSHAKE_REQUEST.value == "handshake_request"
        assert MessageType.HANDSHAKE_RESPONSE.value == "handshake_response"

    def test_heartbeat(self):
        assert MessageType.HEARTBEAT.value == "heartbeat"
        assert MessageType.HEARTBEAT_ACK.value == "heartbeat_ack"

    def test_message(self):
        assert MessageType.MESSAGE.value == "message"
        assert MessageType.MESSAGE_ACK.value == "message_ack"

    def test_error_disconnect(self):
        assert MessageType.ERROR.value == "error"
        assert MessageType.DISCONNECT.value == "disconnect"

    def test_all_values_unique(self):
        values = [m.value for m in MessageType]
        assert len(values) == len(set(values))

    def test_from_string(self):
        assert MessageType("heartbeat") == MessageType.HEARTBEAT


# ============================================================
# ConnectionStatus
# ============================================================

class TestConnectionStatus:
    def test_values(self):
        assert ConnectionStatus.DISCONNECTED.value == "disconnected"
        assert ConnectionStatus.CONNECTING.value == "connecting"
        assert ConnectionStatus.HANDSHAKING.value == "handshaking"
        assert ConnectionStatus.CONNECTED.value == "connected"
        assert ConnectionStatus.AUTHENTICATED.value == "authenticated"
        assert ConnectionStatus.ERROR.value == "error"

    def test_from_string(self):
        assert ConnectionStatus("connected") == ConnectionStatus.CONNECTED


# ============================================================
# ProtocolMessage
# ============================================================

class TestProtocolMessage:
    def _make(self, **kw):
        base = dict(
            message_id="m1",
            message_type=MessageType.MESSAGE,
            sender_id="agent_1",
            receiver_id="server",
            timestamp=1000.0,
            payload={"text": "hello"},
        )
        base.update(kw)
        return ProtocolMessage(**base)

    def test_create_defaults(self):
        msg = self._make()
        assert msg.version == "1.0"
        assert msg.priority == 0
        assert msg.correlation_id is None
        assert msg.metadata is None

    def test_to_dict_round_trip(self):
        msg = self._make()
        d = msg.to_dict()
        assert d["message_id"] == "m1"
        assert d["message_type"] == MessageType.MESSAGE or d["message_type"] == "message"
        restored = ProtocolMessage.from_dict(d)
        assert restored.message_id == "m1"
        assert restored.payload["text"] == "hello"

    def test_to_json_round_trip(self):
        msg = self._make(
            message_type=MessageType.MESSAGE_ACK,
            correlation_id="m0",
        )
        parsed = json.loads(msg.to_json())
        assert parsed["message_type"] == "message_ack"
        restored = ProtocolMessage.from_json(msg.to_json())
        assert restored.message_id == "m3".replace("m3", "m1")
        assert restored.correlation_id == "m0"

    def test_metadata_no_default_mutation(self):
        msg1 = self._make()
        msg2 = self._make(message_id="m2", timestamp=2.0)
        if msg1.metadata is None:
            msg1.metadata = {}
        msg1.metadata["custom"] = 1
        assert not msg2.metadata or "custom" not in msg2.metadata


# ============================================================
# HandshakeRequest
# ============================================================

class TestHandshakeRequest:
    def test_creation_minimal(self):
        req = HandshakeRequest(
            client_id="agent_001",
            client_type="hermes",
            client_version="1.0",
            capabilities=[],
        )
        assert req.client_id == "agent_001"
        assert req.capabilities == []
        assert req.supported_versions == ["1.0"]

    def test_creation_full(self):
        req = HandshakeRequest(
            client_id="agent_001",
            client_type="hermes",
            client_version="1.0",
            capabilities=["memory_access", "streaming"],
            metadata={"source": "test"},
        )
        assert req.capabilities == ["memory_access", "streaming"]
        assert req.metadata == {"source": "test"}

    def test_to_dict(self):
        req = HandshakeRequest(
            client_id="agent_001",
            client_type="hermes",
            client_version="1.0",
            capabilities=["memory_access"],
            metadata={"source": "test"},
        )
        d = req.to_dict()
        assert d["client_id"] == "agent_001"
        assert d["metadata"] == {"source": "test"}

    def test_from_dict(self):
        data = {
            "client_id": "agent_002",
            "client_type": "openclaw",
            "client_version": "2.0",
            "capabilities": ["streaming"],
        }
        req = HandshakeRequest.from_dict(data)
        assert req.client_id == "agent_002"
        assert req.client_version == "2.0"

    def test_from_json(self):
        req = HandshakeRequest.from_json(
            '{"client_id": "x", "client_type": "hermes", "client_version": "1.0", "capabilities": []}'
        )
        assert req.client_id == "x"


# ============================================================
# HandshakeResponse
# ============================================================

class TestHandshakeResponse:
    def _make(self, **kw):
        base = dict(
            server_id="srv",
            server_version="1.0.0",
            accepted=True,
            session_id="sess_001",
        )
        base.update(kw)
        return HandshakeResponse(**base)

    def test_creation_minimal(self):
        resp = self._make()
        assert resp.accepted is True
        assert resp.heartbeat_interval == 30.0
        assert resp.error_message is None

    def test_creation_failure(self):
        resp = self._make(accepted=False, error_message="认证失败")
        assert resp.accepted is False
        assert resp.error_message == "认证失败"

    def test_to_dict(self):
        d = self._make(metadata={"k": "v"}).to_dict()
        assert d["accepted"] is True
        assert d["metadata"] == {"k": "v"}

    def test_from_dict(self):
        resp = HandshakeResponse.from_dict(
            {"server_id": "srv", "server_version": "1.0.0", "accepted": False,
             "error_message": "denied"}
        )
        assert resp.accepted is False
        assert resp.error_message == "denied"


# ============================================================
# CommunicationProtocol
# ============================================================

class TestCommunicationProtocol:
    def setup_method(self):
        self.proto = CommunicationProtocol()

    def test_initial_state(self):
        assert self.proto.server_version == "1.0.0"
        assert self.proto.heartbeat_interval == 30.0
        assert self.proto._sessions == {}
        assert self.proto._rate_limits == {}
        stats = self.proto.get_stats()
        assert stats["total_messages"] == 0

    def test_create_handshake_request(self):
        req = self.proto.create_handshake_request(
            client_id="agent_1",
            client_type="hermes",
            client_version="1.0",
            capabilities=["streaming"],
            auth_token="sk-xxx",
        )
        assert req.client_id == "agent_1"
        assert req.auth_token == "sk-xxx"
        assert "streaming" in req.capabilities

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

    def test_create_handshake_response_failure(self):
        resp = self.proto.create_handshake_response(
            accepted=False, error_message="认证失败",
        )
        assert resp.accepted is False
        assert resp.error_message == "认证失败"

    def test_validate_handshake_version_mismatch(self):
        req = HandshakeRequest(
            client_id="a1", client_type="hermes", client_version="0.5",
            capabilities=[], supported_versions=["0.5"],
        )
        success, error = self.proto.validate_handshake(req)
        assert success is False
        assert "协议版本" in error

    def test_validate_handshake_unknown_client_type_warns_but_passes(self):
        req = HandshakeRequest(
            client_id="a1", client_type="unknown_type", client_version="1.0",
            capabilities=[],
        )
        success, error = self.proto.validate_handshake(req)
        assert success is True

    def test_validate_handshake_success(self):
        req = HandshakeRequest(
            client_id="a1", client_type="hermes", client_version="1.0",
            capabilities=[],
        )
        success, error = self.proto.validate_handshake(req)
        assert success is True, f"expected True, got error: {error}"

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

    def test_check_rate_limit_over_limit(self):
        proto = CommunicationProtocol(rate_limit=3)
        for _ in range(3):
            assert proto.check_rate_limit("burst") is True
        assert proto.check_rate_limit("burst") is False

    def test_create_heartbeat(self):
        msg = self.proto.create_heartbeat("session_1", "agent_1")
        assert msg.message_type == MessageType.HEARTBEAT
        assert msg.sender_id == "session_1"
        assert msg.receiver_id == "agent_1"

    def test_register_handshake_handler(self):
        self.proto.register_handshake_handler(lambda req: (True, ""))
        assert len(self.proto._handshake_handlers) == 1

    def test_register_message_handler(self):
        self.proto.register_message_handler("message", lambda msg: None)
        assert "message" in self.proto._message_handlers

    def test_process_message_returns_ack_via_handler(self):
        """注册 handler 且 handler 返回消息 → process_message 转发该结果"""
        msg = self.proto.create_message(
            sender_id="agent_1", receiver_id="server",
            message_type=MessageType.MESSAGE, payload={"text": "ping"},
        )
        ack = self.proto.create_message(
            sender_id="server", receiver_id="agent_1",
            message_type=MessageType.MESSAGE_ACK,
            payload={"status": "received"},
            correlation_id=msg.message_id,
        )
        async def ack_handler(m):
            return ack

        self.proto.register_message_handler("message", ack_handler)
        response = asyncio.run(self.proto.process_message(msg))
        assert response is not None
        assert response.message_type == MessageType.MESSAGE_ACK
        assert response.correlation_id == msg.message_id

    def test_process_message_no_handler_returns_none(self):
        """未注册 handler → None（实现口径）"""
        msg = self.proto.create_message(
            sender_id="agent_1", receiver_id="server",
            message_type=MessageType.MESSAGE, payload={"text": "ping"},
        )
        response = asyncio.run(self.proto.process_message(msg))
        assert response is None

    def test_process_heartbeat_returns_ack(self):
        msg = self.proto.create_heartbeat("session_1", "agent_1")
        response = asyncio.run(self.proto.process_message(msg))
        assert response is not None
        assert response.message_type == MessageType.HEARTBEAT_ACK
        assert response.correlation_id == msg.message_id

    def test_process_handshake_accepted(self):
        req = self.proto.create_handshake_request(
            client_id="agent_1", client_type="hermes",
            client_version="1.0", capabilities=["streaming"],
        )
        msg = self.proto.create_message(
            sender_id="agent_1", receiver_id="server",
            message_type=MessageType.HANDSHAKE_REQUEST, payload=req.to_dict(),
        )
        response = asyncio.run(self.proto.process_message(msg))
        assert response is not None
        assert response.message_type == MessageType.HANDSHAKE_RESPONSE
        assert response.payload["accepted"] is True
        assert response.payload.get("session_id")

    def test_cleanup_session(self):
        self.proto._sessions["session_1"] = {"client_id": "agent_1", "created_at": 100.0}
        self.proto.cleanup_session("session_1")
        assert self.proto.get_session("session_1") is None

    def test_get_stats_after_traffic(self):
        msg = self.proto.create_message(
            sender_id="a1", receiver_id="srv",
            message_type=MessageType.MESSAGE, payload={"x": 1},
        )
        asyncio.run(self.proto.process_message(msg))
        stats = self.proto.get_stats()
        assert stats["total_messages"] >= 1
        assert "active_sessions" in stats
