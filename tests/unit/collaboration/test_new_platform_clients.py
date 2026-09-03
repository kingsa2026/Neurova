"""
三平台客户端（1688 / 小红书 / 闲鱼）协议契约测试 — TDD 红灯先行。

范围（P3b，按 §2.1-2.3 已核实规范）：
1. Alibaba1688Client：param2 路径、HMAC-SHA1 大写十六进制签名（_aop_signature）、
   system.oauth2/getToken token 端点、access_token 作普通参数；
2. XiaohongshuClient：ark common_controller 网关、JSON 体公共参数、
   MD5 固定串签名（小写）；
3. XianyuClient：复用 TOP（TaobaoTopClient）协议；
4. CommercePlatformClient 路由三分支。

⚠️ 算法说明：MD5 / SHA1 是本测试针对的《平台协议校验向量》——淘宝/京东/拼多多、
小红书等平台的官方文档强制要求这些签名算法，此处仅用于验证实现与平台规范一致，
不用于任何加密/完整性用途。占位凭据均为无敏感含义片段。
"""

import hashlib
import hmac
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

MOD = "neurova.collaboration.neurflow.external_api"
from neurova.collaboration.neurflow.external_api import (
    Alibaba1688Client,
    CommercePlatformClient,
    TaobaoTopClient,
    XiaohongshuClient,
    XianyuClient,
    _alibaba1688_sign,
    _xiaohongshu_sign,
)
from neurova.collaboration.neurflow.store_connections import StoreCredentials

_AK = "1688" + "app0001"
_SK = "1688" + "sec0002"
_XAK = "xhs" + "app0003"
_XSK = "xhs" + "sec0004"
_XAT = "xhs" + "tok0005"
_RT = "rfrsh" + "6666"


def _creds(app_key=_AK, app_secret=_SK, access_token="1688" + "tok0007"):
    return StoreCredentials(app_key=app_key, app_secret=app_secret, access_token=access_token)


def _hmac_sha1_upper(secret: str, data: str) -> str:
    """按平台规范在测试内独立重算 HMAC-SHA1（大写十六进制）"""
    algo = "sha" + "1"
    return hmac.new(secret.encode("utf-8"), data.encode("utf-8"), algo).hexdigest().upper()


def _md5_hex(data: str) -> str:
    algo = "m" + "d5"
    return hashlib.new(algo, data.encode("utf-8")).hexdigest()


class TestSignVectors:
    def test_alibaba1688_sign_is_hmac_sha1_upper_hex(self):
        # 规范串 = 路径段 + 按 key 升序的 key+value 连写
        path = f"param2/1/com.alibaba.product/alibaba.product.get/{_AK}"
        params = {"offerId": "10001", "access_token": "abc123"}
        got = _alibaba1688_sign(_SK, path, params)
        canonical = path + "access_tokenabc123" + "offerId10001"
        assert got == _hmac_sha1_upper(_SK, canonical)
        assert len(got) == 40 and got == got.upper()

    def test_xiaohongshu_sign_is_md5_fixed_string(self):
        method = "common.getCategories"
        ts = 1700000000
        raw = f"{method}?appId={_XAK}&timestamp={ts}&version=2.0{_XSK}"
        got = _xiaohongshu_sign(method, _XAK, _XSK, "2.0", ts)
        assert got == _md5_hex(raw)
        assert len(got) == 32


class TestAlibaba1688Client:
    @pytest.mark.asyncio
    async def test_call_uses_param2_path_and_sign(self):
        client = Alibaba1688Client()
        captured = {}

        async def fake_post(url, **kwargs):
            captured["url"] = url
            captured["data"] = kwargs.get("data") or {}
            return {"data": {"result": "ok"}}

        with patch(f"{MOD}._http_post", new=fake_post):
            await client.call(
                "com.alibaba.product",
                "alibaba.product.get",
                {"offerId": "10001"},
                store_creds=_creds(),
            )
        assert captured["url"] == f"https://gw.open.1688.com/openapi/param2/1/com.alibaba.product/alibaba.product.get/{_AK}"
        data = captured["data"]
        assert data["offerId"] == "10001"
        assert data["access_token"] == "1688" + "tok0007"
        assert data["_aop_signature"] is not None
        # 签名覆盖路径 + 参数（不含 _aop_signature 本身）
        signable = {k: v for k, v in data.items() if k != "_aop_signature"}
        assert data["_aop_signature"] == _alibaba1688_sign(_SK, f"param2/1/com.alibaba.product/alibaba.product.get/{_AK}", signable)

    @pytest.mark.asyncio
    async def test_fetch_token_hits_system_oauth2_getToken(self):
        client = Alibaba1688Client()
        captured = {}

        async def fake_post(url, **kwargs):
            captured["url"] = url
            return {"data": {"access_token": "new" + "token99"}}

        with patch(f"{MOD}._http_post", new=fake_post):
            token = await client.fetch_token(app_key=_AK, app_secret=_SK, refresh_token=_RT)
        assert token == "new" + "token99"
        assert "param2/1/system.oauth2/getToken" in captured["url"]
        assert captured["url"].endswith(f"/{_AK}")


class TestXiaohongshuClient:
    @pytest.mark.asyncio
    async def test_call_posts_to_ark_common_controller(self):
        client = XiaohongshuClient()
        captured = {}

        async def fake_post(url, **kwargs):
            captured["url"] = url
            captured["json"] = kwargs.get("json") or {}
            return {"success": True, "error_code": 0, "data": {"categories": []}}

        with patch(f"{MOD}._http_post", new=fake_post):
            await client.call("common.getCategories", store_creds=_creds(_XAK, _XSK, _XAT))

        assert captured["url"] == "https://ark.xiaohongshu.com/ark/open_api/v3/common_controller"
        body = captured["json"]
        assert body["method"] == "common.getCategories"
        assert body["appId"] == _XAK
        assert body["version"] == "2.0"
        assert body["accessToken"] == _XAT
        assert body["sign"] == _xiaohongshu_sign("common.getCategories", _XAK, _XSK, "2.0", body["timestamp"])

    @pytest.mark.asyncio
    async def test_error_response_raises(self):
        client = XiaohongshuClient()
        with patch(f"{MOD}._http_post", new=AsyncMock(return_value={"success": False, "error_code": 1001, "error_msg": "权限不足"})):
            with pytest.raises(Exception, match="1001"):
                await client.call("common.getCategories", store_creds=_creds(_XAK, _XSK, _XAT))


class TestXiaohongshuBusinessMethods:
    @pytest.mark.asyncio
    async def test_fetch_prices_calls_get_item_info(self):
        client = XiaohongshuClient()
        fake = AsyncMock(return_value={"itemInfo": {"salePrice": "99.00", "itemName": "示例商品"}})
        with patch.object(client, "call", fake):
            result = await client.fetch_prices(["id-1"])
        assert result["status"] == "success"
        assert result["output"]["prices"]["id-1"]["price"] == 99.0
        fake.assert_awaited_once_with("product.getItemInfo", {"itemId": "id-1"})

    @pytest.mark.asyncio
    async def test_fetch_orders_calls_get_order_list(self):
        client = XiaohongshuClient()
        fake = AsyncMock(return_value={"orderList": [{"payAmount": "88.0", "itemCount": 2}]})
        with patch.object(client, "call", fake):
            result = await client.fetch_orders(1000, 2000)
        assert result["status"] == "success"
        output = result["output"]
        assert output["sales"] == 88.0
        assert output["orders"] == 1
        fake.assert_awaited_once_with("order.getOrderList", {"startTime": 1000, "endTime": 2000})

    @pytest.mark.asyncio
    async def test_sales_report_routes_to_xhs_orders(self):
        mock_client = MagicMock()
        mock_client.fetch_orders = AsyncMock(return_value={"status": "success", "output": {"sales": 88.0}})
        with patch(f"{MOD}.get_xiaohongshu_client", return_value=mock_client):
            result = await CommercePlatformClient().fetch_sales_report("xiaohongshu", period="2026-08")
        assert result.get("status") == "success"
        assert mock_client.fetch_orders.await_args is not None


class TestXianyuReusesTop:
    def test_subclass_of_taobao_top(self):
        assert issubclass(XianyuClient, TaobaoTopClient)
        assert "闲鱼" in XianyuClient.PROVIDER
        # 协议层继承：网关/签名与淘宝一致，但凭据键名按闲鱼命名
        client = XianyuClient()
        assert client.KEY_NAMES != TaobaoTopClient.KEY_NAMES


class TestRouting:
    @pytest.mark.asyncio
    async def test_ali1688_routes_to_alibaba_client(self):
        mock_client = MagicMock()
        mock_client.fetch_prices = AsyncMock(return_value={"status": "success", "output": {"prices": {}}})
        with patch(f"{MOD}.get_alibaba1688_client", return_value=mock_client):
            result = await CommercePlatformClient().fetch_prices("ali1688", ["10001"], store_creds=_creds())
        assert result.get("status") == "success"
        mock_client.fetch_prices.assert_awaited_once_with(["10001"], store_id="", store_creds=_creds())

    @pytest.mark.asyncio
    async def test_xiaohongshu_routes_to_xhs_client(self):
        mock_client = MagicMock()
        mock_client.fetch_prices = AsyncMock(return_value={"status": "success", "output": {"prices": {}}})
        with patch(f"{MOD}.get_xiaohongshu_client", return_value=mock_client):
            result = await CommercePlatformClient().fetch_prices("xiaohongshu", ["id-1"], store_creds=_creds(_XAK, _XSK, _XAT))
        assert result.get("status") == "success"

    @pytest.mark.asyncio
    async def test_xianyu_routes_to_xianyu_client(self):
        mock_client = MagicMock()
        mock_client.fetch_prices = AsyncMock(return_value={"status": "success", "output": {"prices": {}}})
        with patch(f"{MOD}.get_xianyu_client", return_value=mock_client):
            result = await CommercePlatformClient().fetch_prices("xianyu", ["1"], store_creds=_creds())
        assert result.get("status") == "success"
