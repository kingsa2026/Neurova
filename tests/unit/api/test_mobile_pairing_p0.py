"""
移动配对 API 阻断性 BUG 修复测试

覆盖 4 个 P0 BUG:
1. BE-MOB-001: WS URL 硬编码 ws://localhost:8000 → 应从 Host header 推导
2. BE-MOB-002: JWT 鉴权占位 _get_current_user_id 永远返回 default-user
3. BE-MOB-003: WS_SECRET 默认弱密钥 → 生产环境强制配置
4. BE-MOB-004: channels/mobile_pairing.py 与 api/endpoints/mobile_pairing.py 双实现

TDD RED 阶段: 所有测试应先失败
"""

import os
import sys
import importlib
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

# 确保项目根目录在 sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


# ---------------------------------------------------------------------------
# BE-MOB-001: WS URL 硬编码
# ---------------------------------------------------------------------------


class TestWSUrlHardcoded:
    """BUG: WS URL 硬编码 ws://localhost:8000 → 应从 Host header 推导"""

    def test_ws_url_should_derive_from_host_header(self):
        """RED: ws_url 应从请求的 Host header 推导，而非硬编码 localhost:8000"""
        from neurova.api.endpoints import mobile_pairing as mp

        # 模拟请求带 Host header = example.com:9527
        mock_request = MagicMock()
        mock_request.headers = {"host": "example.com:9527"}
        mock_request.url.scheme = "http"

        ws_url = mp._build_ws_url(mock_request, code="123456")

        # 期望: ws://example.com:9527/mobile/ws?code=123456
        assert "localhost:8000" not in ws_url, "WS URL 不应硬编码 localhost:8000"
        assert "example.com:9527" in ws_url, "WS URL 应包含实际 host:port"
        assert ws_url.startswith("ws://"), "WS URL 应以 ws:// 开头"
        assert "code=123456" in ws_url

    def test_ws_url_should_use_https_when_request_is_https(self):
        """RED: HTTPS 请求应生成 wss:// URL"""
        from neurova.api.endpoints import mobile_pairing as mp

        mock_request = MagicMock()
        mock_request.headers = {"host": "secure.neurova.io"}
        mock_request.url.scheme = "https"

        ws_url = mp._build_ws_url(mock_request, code="abc")

        assert ws_url.startswith("wss://"), "HTTPS 请求应生成 wss:// URL"
        assert "secure.neurova.io" in ws_url

    def test_ws_url_for_token_endpoint(self):
        """RED: confirm_pairing 返回的 ws_url 也应从 Host 推导"""
        from neurova.api.endpoints import mobile_pairing as mp

        mock_request = MagicMock()
        mock_request.headers = {"host": "192.168.1.100:9527"}
        mock_request.url.scheme = "http"

        ws_url = mp._build_ws_url(mock_request, token="test-token")

        assert "localhost:8000" not in ws_url
        assert "192.168.1.100:9527" in ws_url
        assert "token=test-token" in ws_url


# ---------------------------------------------------------------------------
# BE-MOB-002: JWT 鉴权占位
# ---------------------------------------------------------------------------


class TestJWTAuthPlaceholder:
    """BUG: _get_current_user_id 永远返回 default-user → 应实现真正的 JWT 解析"""

    def test_get_current_user_id_should_extract_from_jwt(self):
        """RED: _get_current_user_id 应从 JWT 提取真实 user_id"""
        from neurova.api.endpoints import mobile_pairing as mp
        from neurova.api.auth import create_access_token

        # 创建真实 JWT token，sub=user-123
        token = create_access_token({"sub": "user-123", "username": "alice"})

        from fastapi.security import HTTPAuthorizationCredentials
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

        # 同步调用（_get_current_user_id 是 async）
        import asyncio
        user_id = asyncio.run(mp._get_current_user_id(creds))

        assert user_id == "user-123", f"应返回 JWT 中的 sub(user-123)，实际: {user_id}"
        assert user_id != "default-user", "不应返回占位符 default-user"

    def test_get_current_user_id_should_reject_invalid_token(self):
        """RED: 无效 JWT 应抛出 401"""
        from neurova.api.endpoints import mobile_pairing as mp
        from fastapi.security import HTTPAuthorizationCredentials
        from fastapi import HTTPException

        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="invalid.jwt.token")

        import asyncio
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(mp._get_current_user_id(creds))

        assert exc_info.value.status_code == 401, "无效 token 应返回 401"

    def test_get_current_user_id_should_reject_missing_credentials(self):
        """RED: 缺少 credentials 应抛出 401"""
        from neurova.api.endpoints import mobile_pairing as mp
        from fastapi import HTTPException

        import asyncio
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(mp._get_current_user_id(None))

        assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# BE-MOB-003: WS_SECRET 弱密钥
# ---------------------------------------------------------------------------


class TestWSSecretWeakDefault:
    """BUG: WS_SECRET 默认弱密钥 → 生产环境强制配置"""

    def test_ws_secret_should_not_use_weak_default_in_production(self):
        """RED: 生产环境不应使用弱默认密钥"""
        from neurova.api.endpoints import mobile_pairing as mp
        from fastapi import HTTPException

        def mock_get(key, default=None):
            # NEUROVA_ENV=production, NEUROVA_WS_SECRET 未配置
            if key == "NEUROVA_ENV":
                return "production"
            if key == "NEUROVA_WS_SECRET":
                return None
            return default

        with patch("neurova.api.endpoints.mobile_pairing.config.get", side_effect=mock_get):
            # 在生产环境，未配置 WS_SECRET 应 fail-fast（抛出异常）
            # 这是安全设计：宁可拒绝服务，也不使用弱密钥
            with pytest.raises(HTTPException) as exc_info:
                mp._get_ws_secret()
            assert exc_info.value.status_code == 500, \
                "生产环境未配置 WS_SECRET 应返回 500"

    def test_ws_secret_should_allow_weak_default_in_development(self):
        """RED: 开发环境允许使用默认密钥（便于本地调试）"""
        from neurova.api.endpoints import mobile_pairing as mp

        with patch.dict(os.environ, {"NEUROVA_ENV": "development"}, clear=False):
            secret = mp._get_ws_secret()
            # 开发环境可以使用默认密钥
            assert secret is not None

    def test_ws_secret_should_use_env_var_when_configured(self):
        """RED: 配置了 NEUROVA_WS_SECRET 环境变量时应使用它"""
        from neurova.api.endpoints import mobile_pairing as mp

        custom_secret = "a-very-strong-production-secret-key-32bytes!"
        with patch.dict(os.environ, {"NEUROVA_WS_SECRET": custom_secret}, clear=False):
            secret = mp._get_ws_secret()
            assert secret == custom_secret, "应使用环境变量配置的 WS_SECRET"


# ---------------------------------------------------------------------------
# BE-MOB-004: 双实现未互通
# ---------------------------------------------------------------------------


class TestDuplicateImplementation:
    """BUG: channels/mobile_pairing.py 与 api/endpoints/mobile_pairing.py 双实现"""

    def test_channels_mobile_pairing_should_be_removed_or_unified(self):
        """RED: channels/mobile_pairing.py 应被删除（死代码）或与 api/endpoints 合并

        验证: channels/mobile_pairing.py 不应作为独立实现存在
        - 如果存在，它应该只是 api/endpoints/mobile_pairing.py 的 re-export
        - 或者完全删除
        """
        # 检查 channels/mobile_pairing.py 是否还存在独立的 MobilePairingManager 类
        try:
            from neurova.channels.mobile_pairing import MobilePairingManager as ChannelsManager
            from neurova.api.endpoints.mobile_pairing import _pairing_codes

            # 如果 channels 版本还存在独立的 Manager 类，说明双实现未合并
            # 修复后: channels 版本应要么删除，要么只是 re-export
            # 这里我们验证: channels 版本不应有独立的业务逻辑
            import inspect
            src = inspect.getsource(ChannelsManager)
            # 如果源码中包含 _sessions 字典（独立存储），说明是独立实现
            if "_sessions" in src and "_issue_ws_token" in src:
                pytest.fail(
                    "channels/mobile_pairing.py 仍包含独立的 MobilePairingManager 实现，"
                    "应删除或合并到 api/endpoints/mobile_pairing.py"
                )
        except ImportError:
            # channels/mobile_pairing.py 已删除 — 通过
            pass

    def test_no_business_code_imports_channels_mobile_pairing(self):
        """RED: 业务代码不应导入 channels/mobile_pairing.py"""
        # 验证: 没有业务代码导入 channels.mobile_pairing
        # 这个测试在修复前后都应通过（因为本来就是死代码）
        # 但它文档化了"channels/mobile_pairing.py 不应被使用"这一约束
        import ast
        from pathlib import Path

        project_root = Path(__file__).parent.parent.parent.parent
        channels_init = project_root / "neurova" / "channels" / "__init__.py"

        if channels_init.exists():
            content = channels_init.read_text(encoding="utf-8")
            # channels/__init__.py 不应导出 mobile_pairing
            assert "mobile_pairing" not in content, \
                "channels/__init__.py 不应导出 mobile_pairing（应使用 api/endpoints 版本）"


# ---------------------------------------------------------------------------
# 集成测试: 端到端验证
# ---------------------------------------------------------------------------


class TestMobilePairingIntegration:
    """集成测试: 验证修复后的端到端行为"""

    def test_generate_pairing_returns_correct_ws_url(self):
        """RED: generate_pairing 端点应返回基于 Host header 的 ws_url"""
        from neurova.api.endpoints.mobile_pairing import router

        app = FastAPI()
        app.include_router(router, prefix="/v1/mobile")

        # 模拟认证
        from neurova.api.endpoints.mobile_pairing import _get_current_user_id
        from neurova.api.auth import create_access_token

        token = create_access_token({"sub": "user-int-1", "username": "tester"})

        app.dependency_overrides[_get_current_user_id] = lambda: "user-int-1"

        client = TestClient(app)

        response = client.post(
            "/v1/mobile/pairing/generate",
            json={"device_name": "iPhone", "device_type": "mobile"},
            headers={
                "Authorization": f"Bearer {token}",
                "Host": "api.neurova.io:9527",
            },
        )

        assert response.status_code == 200
        data = response.json()
        # qr_code_url 中应包含正确的 ws_url
        assert "localhost:8000" not in data["qr_code_url"], \
            "qr_code_url 不应包含硬编码 localhost:8000"


# ---------------------------------------------------------------------------
# WS 消息处理测试（M0.5.2）: 验证 6 个消息处理函数
# ---------------------------------------------------------------------------


class TestWSMessageDispatcher:
    """WS 消息分发器 _handle_ws_message 测试"""

    @pytest.mark.asyncio
    async def test_handle_ws_message_unknown_type_returns_error(self):
        """未知消息类型应返回 {type: error, code: unknown_type}"""
        from neurova.api.endpoints import mobile_pairing as mp

        ws = MagicMock()
        ws.send_json = AsyncMock()

        await mp._handle_ws_message(ws, {"type": "unknown:cmd"}, "user-1", "pair-1")

        ws.send_json.assert_awaited_once()
        sent = ws.send_json.call_args.args[0]
        assert sent["type"] == "error"
        assert sent["code"] == "unknown_type"
        assert "unknown:cmd" in sent["message"]

    @pytest.mark.asyncio
    async def test_handle_ws_message_handler_error_returns_error(self):
        """handler 抛异常时应返回 {type: error, code: handler_error}"""
        from neurova.api.endpoints import mobile_pairing as mp

        ws = MagicMock()
        ws.send_json = AsyncMock()

        # mock _handle_chat_send 抛异常
        with patch.object(mp, "_handle_chat_send", side_effect=RuntimeError("boom")):
            await mp._handle_ws_message(
                ws, {"type": "chat:send", "content": "hi"}, "user-1", "pair-1"
            )

        sent = ws.send_json.call_args.args[0]
        assert sent["type"] == "error"
        assert sent["code"] == "handler_error"
        assert "boom" in sent["message"]


class TestHandleChatSend:
    """_handle_chat_send 测试 — 流式聊天核心"""

    @pytest.mark.asyncio
    async def test_handle_chat_send_stream_yields_chunks_then_done(self):
        """有 chat_stream 时应发送 chat:chunk → chat:done 序列"""
        from neurova.api.endpoints import mobile_pairing as mp

        ws = MagicMock()
        ws.send_json = AsyncMock()

        # mock Agent.chat_stream 为异步生成器，yield 3 个 chunk
        async def _fake_chat_stream(**kwargs):
            for c in ["Hello", " world", "!"]:
                yield c

        mock_agent = MagicMock()
        mock_agent.chat_stream = _fake_chat_stream

        with patch("neurova.api.endpoints.get_agent_instance", return_value=mock_agent):
            await mp._handle_chat_send(
                ws,
                {"type": "chat:send", "content": "hi", "session_id": "s1", "agent_id": "default"},
                "user-1",
            )

        # 应发送 3 个 chunk + 1 个 done
        assert ws.send_json.await_count == 4
        # 验证 chunk 消息
        for i in range(3):
            chunk_msg = ws.send_json.call_args_list[i].args[0]
            assert chunk_msg["type"] == "chat:chunk"
            assert chunk_msg["session_id"] == "s1"
            assert chunk_msg["index"] == i
        # 验证 done 消息
        done_msg = ws.send_json.call_args_list[3].args[0]
        assert done_msg["type"] == "chat:done"
        assert done_msg["session_id"] == "s1"
        assert "message_id" in done_msg

    @pytest.mark.asyncio
    async def test_handle_chat_send_fallback_to_chat_when_no_stream(self):
        """Agent 无 chat_stream 时应降级到 chat()，发送单 chunk + done"""
        from neurova.api.endpoints import mobile_pairing as mp

        ws = MagicMock()
        ws.send_json = AsyncMock()

        # mock Agent 无 chat_stream 属性，但有 chat 方法
        mock_agent = MagicMock(spec=["chat"])
        mock_agent.chat = AsyncMock(return_value={"text": "完整回复"})

        with patch("neurova.api.endpoints.get_agent_instance", return_value=mock_agent):
            await mp._handle_chat_send(
                ws,
                {"type": "chat:send", "content": "hi", "session_id": "s2"},
                "user-1",
            )

        # 应发送 1 个 chunk + 1 个 done
        assert ws.send_json.await_count == 2
        chunk_msg = ws.send_json.call_args_list[0].args[0]
        assert chunk_msg["type"] == "chat:chunk"
        assert chunk_msg["content"] == "完整回复"
        assert chunk_msg["index"] == 0
        done_msg = ws.send_json.call_args_list[1].args[0]
        assert done_msg["type"] == "chat:done"

    @pytest.mark.asyncio
    async def test_handle_chat_send_empty_content_returns_error(self):
        """空 content 应返回 {type: error, code: empty_content}"""
        from neurova.api.endpoints import mobile_pairing as mp

        ws = MagicMock()
        ws.send_json = AsyncMock()

        await mp._handle_chat_send(
            ws, {"type": "chat:send", "content": "", "session_id": "s3"}, "user-1"
        )

        sent = ws.send_json.call_args.args[0]
        assert sent["type"] == "error"
        assert sent["code"] == "empty_content"

    @pytest.mark.asyncio
    async def test_handle_chat_send_agent_not_found_returns_error(self):
        """Agent 不存在应返回 {type: error, code: agent_not_found}"""
        from neurova.api.endpoints import mobile_pairing as mp

        ws = MagicMock()
        ws.send_json = AsyncMock()

        with patch("neurova.api.endpoints.get_agent_instance", return_value=None):
            await mp._handle_chat_send(
                ws,
                {"type": "chat:send", "content": "hi", "agent_id": "ghost"},
                "user-1",
            )

        sent = ws.send_json.call_args.args[0]
        assert sent["type"] == "error"
        assert sent["code"] == "agent_not_found"
        assert "ghost" in sent["message"]


class TestHandleChatCancel:
    """_handle_chat_cancel 测试 — 取消机制"""

    @pytest.mark.asyncio
    async def test_handle_chat_cancel_marks_session(self):
        """chat:cancel 应在 _cancelled_sessions 中标记 session_id"""
        from neurova.api.endpoints import mobile_pairing as mp

        ws = MagicMock()
        ws.send_json = AsyncMock()

        # 清理状态
        mp._cancelled_sessions.pop("cancel-test", None)

        await mp._handle_chat_cancel(ws, {"type": "chat:cancel", "session_id": "cancel-test"})

        assert mp._cancelled_sessions.get("cancel-test") is True

        # 清理
        mp._cancelled_sessions.pop("cancel-test", None)

    @pytest.mark.asyncio
    async def test_handle_chat_cancel_empty_session_id_does_nothing(self):
        """空 session_id 不应标记"""
        from neurova.api.endpoints import mobile_pairing as mp

        ws = MagicMock()
        ws.send_json = AsyncMock()

        mp._cancelled_sessions.pop("", None)
        await mp._handle_chat_cancel(ws, {"type": "chat:cancel", "session_id": ""})

        assert "" not in mp._cancelled_sessions


class TestHandleAgentSwitch:
    """_handle_agent_switch 测试"""

    @pytest.mark.asyncio
    async def test_handle_agent_switch_returns_switched(self):
        """agent:switch 应返回 {type: agent:switched, config}"""
        from neurova.api.endpoints import mobile_pairing as mp

        ws = MagicMock()
        ws.send_json = AsyncMock()

        mock_agent = MagicMock()
        mock_agent.agent_id = "agent-007"
        mock_agent.name = "Bond"

        with patch("neurova.api.endpoints.get_agent_instance", return_value=mock_agent):
            await mp._handle_agent_switch(
                ws, {"type": "agent:switch", "agent_id": "agent-007"}
            )

        sent = ws.send_json.call_args.args[0]
        assert sent["type"] == "agent:switched"
        assert sent["agent_id"] == "agent-007"
        assert sent["config"]["agent_id"] == "agent-007"
        assert sent["config"]["name"] == "Bond"

    @pytest.mark.asyncio
    async def test_handle_agent_switch_not_found_returns_error(self):
        """Agent 不存在应返回 error"""
        from neurova.api.endpoints import mobile_pairing as mp

        ws = MagicMock()
        ws.send_json = AsyncMock()

        with patch("neurova.api.endpoints.get_agent_instance", return_value=None):
            await mp._handle_agent_switch(
                ws, {"type": "agent:switch", "agent_id": "missing"}
            )

        sent = ws.send_json.call_args.args[0]
        assert sent["type"] == "error"
        assert sent["code"] == "agent_not_found"


class TestHandleSessionList:
    """_handle_session_list 测试"""

    @pytest.mark.asyncio
    async def test_handle_session_list_returns_sessions(self):
        """session:list 应返回 {type: session:list, sessions}，且按 WS 用户过滤

        审计修复 (P0-4): 原实现调 get_sessions(agent_id) 返回全员完整会话,
        现改为 list_sessions(agent_id, user_id) 只返回本用户摘要。
        """
        from neurova.api.endpoints import mobile_pairing as mp

        ws = MagicMock()
        ws.send_json = AsyncMock()

        mock_sm = MagicMock()
        mock_sm.list_sessions = MagicMock(
            return_value=[{"session_id": "s1", "user_id": "user_42"}]
        )

        with patch("neurova.session_manager.get_session_manager", return_value=mock_sm):
            await mp._handle_session_list(
                ws, {"type": "session:list", "agent_id": "default"}, "user_42"
            )

        sent = ws.send_json.call_args.args[0]
        assert sent["type"] == "session:list"
        assert len(sent["sessions"]) == 1
        mock_sm.list_sessions.assert_called_once_with(agent_id="default", user_id="user_42")

    @pytest.mark.asyncio
    async def test_handle_session_list_error_returns_error(self):
        """session_manager 异常应返回 error"""
        from neurova.api.endpoints import mobile_pairing as mp

        ws = MagicMock()
        ws.send_json = AsyncMock()

        mock_sm = MagicMock()
        mock_sm.list_sessions = MagicMock(side_effect=RuntimeError("DB down"))

        with patch("neurova.session_manager.get_session_manager", return_value=mock_sm):
            await mp._handle_session_list(
                ws, {"type": "session:list", "agent_id": "default"}, "user_42"
            )

        sent = ws.send_json.call_args.args[0]
        assert sent["type"] == "error"
        assert sent["code"] == "session_list_failed"
        assert "DB down" in sent["message"]


class TestHandleSessionCreate:
    """_handle_session_create 测试"""

    @pytest.mark.asyncio
    async def test_handle_session_create_returns_created(self):
        """session:create 应返回 {type: session:created, session}，并绑定创建者 user_id"""
        from neurova.api.endpoints import mobile_pairing as mp

        ws = MagicMock()
        ws.send_json = AsyncMock()

        mock_sm = MagicMock()
        mock_sm.create_session = MagicMock(return_value="new-session-id")

        with patch("neurova.session_manager.get_session_manager", return_value=mock_sm):
            await mp._handle_session_create(
                ws, {"type": "session:create", "agent_id": "default"}, "user_42"
            )

        sent = ws.send_json.call_args.args[0]
        assert sent["type"] == "session:created"
        assert sent["session"]["session_id"] == "new-session-id"
        assert sent["session"]["agent_id"] == "default"
        mock_sm.create_session.assert_called_once_with("default", user_id="user_42")

    @pytest.mark.asyncio
    async def test_handle_session_create_error_returns_error(self):
        """session_manager 异常应返回 error"""
        from neurova.api.endpoints import mobile_pairing as mp

        ws = MagicMock()
        ws.send_json = AsyncMock()

        mock_sm = MagicMock()
        mock_sm.create_session = MagicMock(side_effect=RuntimeError("quota exceeded"))

        with patch("neurova.session_manager.get_session_manager", return_value=mock_sm):
            await mp._handle_session_create(
                ws, {"type": "session:create", "agent_id": "default"}, "user_42"
            )

        sent = ws.send_json.call_args.args[0]
        assert sent["type"] == "error"
        assert sent["code"] == "session_create_failed"
        assert "quota exceeded" in sent["message"]
