"""移动配对端点级行为测试（自 tests/test_channels/test_mobile_pairing.py 迁入）。

背景：neurova/channels/mobile_pairing.py（零消费死实现）已删除，原 ad-hoc
文件中测死实现的类随之消亡；本文件保留测活实现（api/endpoints/mobile_pairing）
的端点级用例——按项目测试纪律归位 tests/unit/api/。
"""

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """创建测试客户端（对齐生产 API：路由挂载到 /mobile 前缀，全局存储按测试隔离）"""
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


class TestMobilePairingAPI:
    """行为: API 端点正确调用配对流程并强制用户隔离"""

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


class TestMobileConnectionManager:
    def test_mobile_connection_manager_tracks_connections(self):
        """MobileConnectionManager 正确追踪用户连接数（对齐生产单例 API）"""
        import asyncio

        from neurova.api.endpoints.mobile_pairing import MobileConnectionManager

        conn_mgr = MobileConnectionManager.get_instance()

        # 模拟 WebSocket 连接
        mock_ws_1 = AsyncMock()
        mock_ws_2 = AsyncMock()

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
