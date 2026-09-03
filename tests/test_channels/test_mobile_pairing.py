"""
移动设备配对系统测试

行为规格:
1. 生成配对码 - 6位随机码, 5分钟过期, 用户隔离
2. 确认配对 - 设备通过配对码完成认证握手
3. 二维码生成 - 编码 WS 连接 URL
4. 用户隔离 - 配对绑定 user_id, 不同用户不可交叉访问
5. 配对码过期 - 超时自动失效
6. 配对管理 - 列表/撤销
7. API 端点 - FastAPI 路由集成测试
"""

import time
import pytest
from unittest.mock import patch, MagicMock

from neurova.channels.mobile_pairing import (
    MobilePairingManager,
    PairingSession,
    PairingStatus,
)


# ============================================================
# Tracer Bullet: 生成配对码
# ============================================================


class TestGeneratePairingCode:
    """行为: 用户请求配对码, 系统返回有效 code + 过期时间 + 二维码 URL"""

    def test_returns_valid_pairing_session(self):
        mgr = MobilePairingManager()
        session = mgr.generate_pairing_code(user_id="user_A", agent_id="Yiling")

        assert isinstance(session, PairingSession)
        assert len(session.code) == 6
        assert session.code.isdigit()
        assert session.user_id == "user_A"
        assert session.agent_id == "Yiling"
        assert session.status == PairingStatus.PENDING

    def test_code_expires_in_5_minutes(self):
        mgr = MobilePairingManager()
        session = mgr.generate_pairing_code(user_id="user_A", agent_id="Yiling")

        assert session.expires_at > time.time() + 290  # 至少还有 290 秒
        assert session.expires_at <= time.time() + 310  # 最多 310 秒

    def test_qr_code_contains_ws_url(self):
        mgr = MobilePairingManager(ws_host="192.168.1.100", ws_port=9527)
        session = mgr.generate_pairing_code(user_id="user_A", agent_id="Yiling")

        assert "192.168.1.100" in session.qr_data
        assert "9527" in session.qr_data
        assert session.code in session.qr_data

    def test_different_calls_produce_different_codes(self):
        mgr = MobilePairingManager()
        s1 = mgr.generate_pairing_code(user_id="user_A", agent_id="Yiling")
        s2 = mgr.generate_pairing_code(user_id="user_A", agent_id="Yiling")

        assert s1.code != s2.code


# ============================================================
# 确认配对
# ============================================================


class TestConfirmPairing:
    """行为: 手机端使用配对码完成认证, 获得 WS 连接凭证"""

    def test_confirm_with_valid_code_succeeds(self):
        mgr = MobilePairingManager()
        session = mgr.generate_pairing_code(user_id="user_A", agent_id="Yiling")

        result = mgr.confirm_pairing(
            code=session.code,
            device_info={"device_name": "Pixel 8", "os": "Android 14"},
        )

        assert result.success is True
        assert result.pairing_id == session.pairing_id
        assert result.ws_token  # 返回 WS 连接 token
        assert result.user_id == "user_A"

    def test_confirm_with_invalid_code_fails(self):
        mgr = MobilePairingManager()
        result = mgr.confirm_pairing(
            code="000000",
            device_info={"device_name": "Pixel 8", "os": "Android 14"},
        )

        assert result.success is False
        assert "无效" in result.error_message or "not found" in result.error_message.lower()

    def test_confirm_twice_with_same_code_fails(self):
        mgr = MobilePairingManager()
        session = mgr.generate_pairing_code(user_id="user_A", agent_id="Yiling")

        r1 = mgr.confirm_pairing(code=session.code, device_info={"device_name": "Pixel 8"})
        r2 = mgr.confirm_pairing(code=session.code, device_info={"device_name": "iPhone 15"})

        assert r1.success is True
        assert r2.success is False


# ============================================================
# 配对码过期
# ============================================================


class TestPairingExpiration:
    """行为: 配对码超时后自动失效"""

    def test_expired_code_cannot_be_confirmed(self):
        mgr = MobilePairingManager(ttl_seconds=0.1)  # 0.1秒过期
        session = mgr.generate_pairing_code(user_id="user_A", agent_id="Yiling")

        time.sleep(0.2)  # 等待过期

        result = mgr.confirm_pairing(code=session.code, device_info={"device_name": "Pixel 8"})
        assert result.success is False
        assert "过期" in result.error_message or "expired" in result.error_message.lower()


# ============================================================
# 用户隔离
# ============================================================


class TestUserIsolation:
    """行为: 不同用户的配对数据完全隔离"""

    def test_user_cannot_see_others_pairings(self):
        mgr = MobilePairingManager()
        s1 = mgr.generate_pairing_code(user_id="user_A", agent_id="Yiling")
        mgr.confirm_pairing(code=s1.code, device_info={"device_name": "Pixel 8"})

        s2 = mgr.generate_pairing_code(user_id="user_B", agent_id="Yiling")
        mgr.confirm_pairing(code=s2.code, device_info={"device_name": "iPhone 15"})

        user_a_pairings = mgr.list_user_pairings(user_id="user_A")
        user_b_pairings = mgr.list_user_pairings(user_id="user_B")

        assert len(user_a_pairings) == 1
        assert user_a_pairings[0].user_id == "user_A"
        assert len(user_b_pairings) == 1
        assert user_b_pairings[0].user_id == "user_B"

    def test_user_cannot_revoke_others_pairing(self):
        mgr = MobilePairingManager()
        s1 = mgr.generate_pairing_code(user_id="user_A", agent_id="Yiling")
        result = mgr.confirm_pairing(code=s1.code, device_info={"device_name": "Pixel 8"})
        pairing_id = result.pairing_id

        # user_B 尝试撤销 user_A 的配对
        revoked = mgr.revoke_pairing(pairing_id=pairing_id, user_id="user_B")
        assert revoked is False

        # user_A 可以撤销自己的配对
        revoked = mgr.revoke_pairing(pairing_id=pairing_id, user_id="user_A")
        assert revoked is True


# ============================================================
# 配对状态查询
# ============================================================


class TestPairingStatus:
    """行为: 生成方轮询配对状态, 检测是否已被扫码确认"""

    def test_initial_status_is_pending(self):
        mgr = MobilePairingManager()
        session = mgr.generate_pairing_code(user_id="user_A", agent_id="Yiling")

        retrieved = mgr.get_pairing_by_code(session.code)
        assert retrieved is not None
        assert retrieved.status == PairingStatus.PENDING

    def test_status_changes_to_confirmed_after_confirm(self):
        mgr = MobilePairingManager()
        session = mgr.generate_pairing_code(user_id="user_A", agent_id="Yiling")

        mgr.confirm_pairing(code=session.code, device_info={"device_name": "Pixel 8"})

        retrieved = mgr.get_pairing_by_code(session.code)
        assert retrieved is not None
        assert retrieved.status == PairingStatus.CONFIRMED

    def test_nonexistent_code_returns_none(self):
        mgr = MobilePairingManager()
        assert mgr.get_pairing_by_code("999999") is None


# ============================================================
# WS Token 包含用户身份
# ============================================================


class TestWsTokenIdentity:
    """行为: 确认配对后生成的 ws_token 携带 user_id, 用于后续 WS 认证"""

    def test_ws_token_contains_user_id(self):
        mgr = MobilePairingManager()
        session = mgr.generate_pairing_code(user_id="user_A", agent_id="Yiling")
        result = mgr.confirm_pairing(code=session.code, device_info={"device_name": "Pixel 8"})

        # ws_token 应该可以通过 verify_ws_token 解析出 user_id
        identity = mgr.verify_ws_token(result.ws_token)
        assert identity is not None
        assert identity["user_id"] == "user_A"
        assert identity["agent_id"] == "Yiling"

    def test_invalid_ws_token_returns_none(self):
        mgr = MobilePairingManager()
        assert mgr.verify_ws_token("invalid_token") is None

    def test_revoked_pairing_ws_token_is_invalid(self):
        mgr = MobilePairingManager()
        session = mgr.generate_pairing_code(user_id="user_A", agent_id="Yiling")
        result = mgr.confirm_pairing(code=session.code, device_info={"device_name": "Pixel 8"})

        # 撤销配对后，ws_token 应该失效
        mgr.revoke_pairing(pairing_id=result.pairing_id, user_id="user_A")

        identity = mgr.verify_ws_token(result.ws_token)
        assert identity is None


# ============================================================
# API 端点集成测试
# ============================================================


class TestMobilePairingAPI:
    """行为: API 端点正确调用 MobilePairingManager 并强制用户隔离"""

    @pytest.fixture
    def client(self):
        """创建测试客户端（对齐生产 API：路由挂载到 /mobile 前缀，全局存储按测试隔离）"""
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from neurova.api.endpoints.mobile_pairing import router as mobile_router
        from neurova.api.endpoints.mobile_pairing import _get_current_user_id as get_current_user_id

        # 生产 API 使用模块级全局存储，清理以保证测试隔离
        import neurova.api.endpoints.mobile_pairing as mp_module
        mp_module._pairing_codes.clear()
        mp_module._paired_devices.clear()
        mp_module._user_devices.clear()

        app = FastAPI()
        app.include_router(mobile_router, prefix="/mobile")

        # 用 dependency_overrides 替换认证
        async def _mock_user_id():
            return "user_A"

        app.dependency_overrides[get_current_user_id] = _mock_user_id

        return TestClient(app)

    def test_generate_pairing_endpoint(self, client):
        """POST /mobile/pairing/generate 返回配对码和二维码"""
        resp = client.post(
            "/mobile/pairing/generate",
            json={"device_name": "Web Console", "device_type": "web"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["code"]) == 6
        assert data["qr_code_url"]
        assert data["expires_in"] == 300

    def test_confirm_pairing_endpoint(self, client):
        """POST /mobile/pairing/confirm 使用配对码确认"""
        gen_resp = client.post(
            "/mobile/pairing/generate",
            json={"agent_id": "Yiling"},
        )
        code = gen_resp.json()["code"]

        # 确认配对（无需认证，手机端还没登录）
        confirm_resp = client.post(
            "/mobile/pairing/confirm",
            json={"code": code, "device_name": "Pixel 8", "device_os": "Android 14"},
        )

        assert confirm_resp.status_code == 200
        data = confirm_resp.json()
        assert data["success"] is True
        assert data["ws_token"]

    def test_status_polling_endpoint(self, client):
        """GET /mobile/pairing/status/{code} 返回配对状态"""
        gen_resp = client.post(
            "/mobile/pairing/generate",
            json={"agent_id": "Yiling"},
        )
        code = gen_resp.json()["code"]

        # 未确认时状态为 pending
        status_resp = client.get(f"/mobile/pairing/status/{code}")
        assert status_resp.status_code == 200
        assert status_resp.json()["status"] == "pending"

    def test_status_404_for_unknown_code(self, client):
        """GET /mobile/pairing/status/{code} 对不存在的码返回 404"""
        resp = client.get("/mobile/pairing/status/999999")
        assert resp.status_code == 404

    def test_list_paired_devices_endpoint(self, client):
        """GET /mobile/pairing/list 返回当前用户的已配对设备"""
        gen_resp = client.post(
            "/mobile/pairing/generate",
            json={"agent_id": "Yiling"},
        )
        code = gen_resp.json()["code"]

        client.post(
            "/mobile/pairing/confirm",
            json={"code": code, "device_name": "Pixel 8", "device_os": "Android 14"},
        )

        list_resp = client.get("/mobile/pairing/list")

        assert list_resp.status_code == 200
        body = list_resp.json()
        devices = body["data"]["devices"]
        assert len(devices) == 1
        assert devices[0]["device_name"] == "Pixel 8"

    def test_revoke_pairing_endpoint(self, client):
        """DELETE /mobile/pairing/{pairing_id} 解除配对"""
        gen_resp = client.post(
            "/mobile/pairing/generate",
            json={"agent_id": "Yiling"},
        )
        code = gen_resp.json()["code"]

        confirm_resp = client.post(
            "/mobile/pairing/confirm",
            json={"code": code, "device_name": "Pixel 8", "device_os": "Android 14"},
        )
        pairing_id = confirm_resp.json()["pairing_id"]

        del_resp = client.delete(f"/mobile/pairing/{pairing_id}")
        assert del_resp.status_code == 200

    def test_revoke_others_pairing_returns_403(self, client):
        """DELETE 其他用户的配对返回 403（用户隔离）"""
        gen_resp = client.post(
            "/mobile/pairing/generate",
            json={"device_name": "Web Console", "device_type": "web"},
        )
        code = gen_resp.json()["code"]

        confirm_resp = client.post(
            "/mobile/pairing/confirm",
            json={"code": code, "device_name": "Pixel 8", "device_os": "Android 14"},
        )
        pairing_id = confirm_resp.json()["pairing_id"]

        # 临时切换 override 到 user_B，模拟越权删除
        from neurova.api.endpoints.mobile_pairing import _get_current_user_id as get_current_user_id

        async def _mock_user_b_id():
            return "user_B"

        client.app.dependency_overrides[get_current_user_id] = _mock_user_b_id
        del_resp = client.delete(f"/mobile/pairing/{pairing_id}")

        assert del_resp.status_code == 403


# ============================================================
# 移动设备 WebSocket 连接测试
# ============================================================


class TestMobileWebSocket:
    """行为: 已配对设备通过 WS Token 认证后建立持久连接"""

    def test_ws_token_verification_after_pairing(self):
        """配对成功后 ws_token 可通过 verify_ws_token 验证，包含完整身份信息"""
        mgr = MobilePairingManager(ws_host="test.local", ws_port=9527)
        session = mgr.generate_pairing_code(user_id="user_A", agent_id="Yiling")
        result = mgr.confirm_pairing(code=session.code, device_info={"device_name": "Pixel 8"})

        # 验证 ws_token 包含完整身份
        identity = mgr.verify_ws_token(result.ws_token)
        assert identity is not None
        assert identity["user_id"] == "user_A"
        assert identity["agent_id"] == "Yiling"
        assert identity["pairing_id"] == result.pairing_id

    def test_ws_token_for_revoked_pairing_is_invalid(self):
        """撤销配对后 ws_token 失效"""
        mgr = MobilePairingManager(ws_host="test.local", ws_port=9527)
        session = mgr.generate_pairing_code(user_id="user_A", agent_id="Yiling")
        result = mgr.confirm_pairing(code=session.code, device_info={"device_name": "Pixel 8"})

        # 先验证 token 有效
        assert mgr.verify_ws_token(result.ws_token) is not None

        # 撤销配对
        mgr.revoke_pairing(pairing_id=result.pairing_id, user_id="user_A")

        # token 应该失效
        assert mgr.verify_ws_token(result.ws_token) is None

    def test_ws_token_isolation(self):
        """不同用户的 ws_token 不可交叉使用"""
        mgr = MobilePairingManager(ws_host="test.local", ws_port=9527)

        s1 = mgr.generate_pairing_code(user_id="user_A", agent_id="Yiling")
        r1 = mgr.confirm_pairing(code=s1.code, device_info={"device_name": "Pixel 8"})

        s2 = mgr.generate_pairing_code(user_id="user_B", agent_id="Yiling")
        r2 = mgr.confirm_pairing(code=s2.code, device_info={"device_name": "iPhone 15"})

        id1 = mgr.verify_ws_token(r1.ws_token)
        id2 = mgr.verify_ws_token(r2.ws_token)

        assert id1["user_id"] == "user_A"
        assert id2["user_id"] == "user_B"
        assert id1["pairing_id"] != id2["pairing_id"]

    def test_mobile_connection_manager_tracks_connections(self):
        """MobileConnectionManager 正确追踪用户连接数（对齐生产单例 API）"""
        from neurova.api.endpoints.mobile_pairing import MobileConnectionManager
        from unittest.mock import AsyncMock

        conn_mgr = MobileConnectionManager.get_instance()

        # 模拟 WebSocket 连接
        mock_ws_1 = AsyncMock()
        mock_ws_2 = AsyncMock()

        import asyncio
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(conn_mgr.connect(mock_ws_1, "user_A", "conn-1"))
            loop.run_until_complete(conn_mgr.connect(mock_ws_2, "user_A", "conn-2"))

            assert conn_mgr.get_online_count() == 2

            conn_mgr.disconnect("conn-1", "user_A")
            assert conn_mgr.get_online_count() == 1
        finally:
            conn_mgr.disconnect("conn-2", "user_A")
            loop.close()
