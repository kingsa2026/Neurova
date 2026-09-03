"""
淘宝 / 京东 / 拼多多 / 抖店 / TikTok Shop 开放平台客户端测试

依据各平台开放平台开发文档的网关协议：

1. 淘宝开放平台（open.taobao.com，TOP 协议）
   - 网关：POST https://eco.taobao.com/router/rest（表单）
   - 公共参数：method / app_key / session(access_token) / timestamp(yyyy-MM-dd HH:mm:ss)
     / format=json / v=2.0 / sign_method=md5 / sign
   - 签名：MD5(secret + 按 key 升序 key+value 拼接 + secret)，十六进制大写
   - 令牌刷新：POST https://oauth.taobao.com/token（grant_type=refresh_token）
   - 商品/价格/库存：taobao.item.get（num_iid，price 单位元，num 为库存）
   - 订单：taobao.trades.sold.get（start_created/end_created，payment 单位元）
   - 评论：taobao.traderates.get（result=好评/中评/差评）

2. 京东开放平台（open.jd.com）
   - 网关：POST https://api.jd.com/routerjson（表单）
   - 公共参数：method / app_key / access_token / timestamp(yyyy-MM-dd HH:mm:ss)
     / v=1.0 / format=json / 360buy_param_json(业务参数 JSON) / sign
   - 签名：MD5(secret + 按 key 升序 key+value 拼接 + secret)，十六进制大写
   - 订单：jingdong.pop.order.search（startDate/endDate）
   - 商品：jingdong.ware.read.findSkuListPage（skuId/jdPrice/stockNum）
   - 响应包装：{method 点换下划线}_responce（京东历史拼写，兼容 _response）

3. 拼多多开放平台（open.pinduoduo.com）
   - 网关：POST https://gw-api.pinduoduo.com/api/router（表单）
   - 公共参数：type(API 名) / client_id / access_token / timestamp(unix 秒)
     / data_type=JSON / sign；业务参数平铺为顶层表单字段
   - 签名：MD5(client_secret + 按 key 升序 key+value 拼接 + client_secret)，大写
   - 订单：pdd.order.list.get（start_updated_at/end_updated_at unix 秒，pay_amount 单位分）
   - 商品：pdd.goods.information.get（goods_id，min_group_price 单位分，goods_quantity 库存）

4. 抖店开放平台（op.jinritemai.com）
   - 网关：POST https://openapi-fxg.jinritemai.com（表单）
   - 公共参数：app_key / method / param_json(业务参数紧凑 JSON) / timestamp(unix 秒)
     / v=2 / sign_method=md5 / access_token / sign
   - 签名：MD5(secret + app_key{v}method{v}param_json{v}timestamp{v}v{v} + secret)
     （仅 app_key/method/param_json/timestamp/v 五个 key 按字母序参与签名）
   - 订单：order.searchList（create_time_start/create_time_end unix 秒，pay_amount 单位分）
   - 商品：product.listV2（product_id/discount_price 单位分）
   - 响应包装：{err_no, message, data}，err_no != 0 为失败

5. TikTok Shop Partner（partner.tiktokshop.com）
   - 网关：REST https://open-api.tiktokglobalshop.com，版本在路径（/product/202309/...）
   - 公共查询参数：app_key / access_token / timestamp(unix 秒) / sign
   - 签名：SHA256(secret + 按 key 升序 key+value 拼接 + secret)，十六进制小写；
     POST 请求体字段一并参与签名
   - 商品：GET /product/202309/products（price.sale_price.amount 为最小货币单位分）
   - 订单：POST /order/202309/orders/search（create_time_ge/create_time_lt unix 秒）
   - 响应包装：{code, message, data}，code != 0 为失败

说明：京东/拼多多/抖店/TikTok Shop 开放平台均不提供商品评论拉取 API，
评论回复节点对这些平台降级为手工粘贴；仅淘宝 TOP 提供 traderates.get。
"""
import hashlib
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

MOD = "neurova.collaboration.neurflow.external_api"


def _store_with(mapping: dict):
    store = MagicMock()
    store.get.side_effect = lambda name: mapping.get(name)
    return store


def _md5_upper(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest().upper()


class TestGatewayConstants:
    """各平台官方网关地址与 SecretStore 密钥约定"""

    def test_gateway_urls(self):
        from neurova.collaboration.neurflow import external_api as ea

        assert ea.TAOBAO_GATEWAY_URL == "https://eco.taobao.com/router/rest"
        assert ea.TAOBAO_OAUTH_TOKEN_URL == "https://oauth.taobao.com/token"
        assert ea.JD_GATEWAY_URL == "https://api.jd.com/routerjson"
        assert ea.PDD_GATEWAY_URL == "https://gw-api.pinduoduo.com/api/router"
        assert ea.PDD_OAUTH_TOKEN_URL == "https://open-api.pinduoduo.com/oauth/token"
        assert ea.DOUYIN_ECOM_GATEWAY_URL == "https://openapi-fxg.jinritemai.com"
        assert ea.TIKTOK_SHOP_GATEWAY_URL == "https://open-api.tiktokglobalshop.com"

    def test_key_names_follow_secret_store_convention(self):
        from neurova.collaboration.neurflow import external_api as ea

        assert ea.TAOBAO_KEY_NAMES["app_key"] == ["NEUROVA_TAOBAO_APP_KEY"]
        assert ea.TAOBAO_KEY_NAMES["app_secret"] == ["NEUROVA_TAOBAO_APP_SECRET"]
        assert ea.TAOBAO_KEY_NAMES["access_token"] == ["NEUROVA_TAOBAO_ACCESS_TOKEN"]
        assert ea.JD_KEY_NAMES["app_key"] == ["NEUROVA_JD_APP_KEY"]
        assert ea.JD_KEY_NAMES["app_secret"] == ["NEUROVA_JD_APP_SECRET"]
        assert ea.PDD_KEY_NAMES["client_id"] == ["NEUROVA_PDD_CLIENT_ID"]
        assert ea.PDD_KEY_NAMES["client_secret"] == ["NEUROVA_PDD_CLIENT_SECRET"]
        assert ea.DOUYIN_ECOM_KEY_NAMES["app_key"] == ["NEUROVA_DOUYIN_ECOM_APP_KEY"]
        assert ea.TIKTOK_SHOP_KEY_NAMES["app_key"] == ["NEUROVA_TIKTOK_SHOP_APP_KEY"]
        assert ea.TIKTOK_SHOP_KEY_NAMES["app_secret"] == ["NEUROVA_TIKTOK_SHOP_APP_SECRET"]


class TestRouterSign:
    """TOP/京东/拼多多 通用 MD5 签名：secret + 升序 key+value 拼接 + secret"""

    def test_md5_sign_sorts_keys_and_uppercases(self):
        from neurova.collaboration.neurflow.external_api import _router_sign_md5

        expected = _md5_upper("S" + "a1" + "b2" + "S")
        assert _router_sign_md5("S", {"b": "2", "a": "1"}) == expected

    def test_md5_sign_includes_all_params(self):
        from neurova.collaboration.neurflow.external_api import _router_sign_md5

        params = {"method": "taobao.item.get", "app_key": "k", "timestamp": "2025-01-01 00:00:00"}
        base = "sec" + "".join(f"{k}{params[k]}" for k in sorted(params)) + "sec"
        assert _router_sign_md5("sec", params) == _md5_upper(base)

    def test_tiktok_sha256_sign(self):
        from neurova.collaboration.neurflow.external_api import _tiktok_sign_sha256

        params = {"timestamp": "1700000000", "app_key": "k", "access_token": "t"}
        base = "sec" + "".join(f"{k}{params[k]}" for k in sorted(params)) + "sec"
        assert _tiktok_sign_sha256("sec", params) == hashlib.sha256(base.encode("utf-8")).hexdigest()

    def test_douyin_sign_only_five_sorted_keys(self):
        from neurova.collaboration.neurflow.external_api import _douyin_sign_md5

        params = {
            "app_key": "k",
            "method": "order.searchList",
            "param_json": '{"a":1}',
            "timestamp": "1700000000",
            "v": "2",
        }
        base = (
            "sec"
            + f"app_key{params['app_key']}"
            + f"method{params['method']}"
            + f"param_json{params['param_json']}"
            + f"timestamp{params['timestamp']}"
            + f"v{params['v']}"
            + "sec"
        )
        assert _douyin_sign_md5("sec", params) == _md5_upper(base)


class TestPeriodHelpers:
    def test_period_to_date_range_month(self):
        from neurova.collaboration.neurflow.external_api import _period_to_date_range

        assert _period_to_date_range("2025-01") == ("2025-01-01", "2025-01-31")
        assert _period_to_date_range("2024-02") == ("2024-02-01", "2024-02-29")

    def test_period_to_date_range_day_and_range(self):
        from neurova.collaboration.neurflow.external_api import _period_to_date_range

        assert _period_to_date_range("2025-01-15") == ("2025-01-15", "2025-01-15")
        assert _period_to_date_range("2025-01-01~2025-01-10") == ("2025-01-01", "2025-01-10")

    def test_period_to_date_range_defaults_last_30_days(self):
        from datetime import date, timedelta

        from neurova.collaboration.neurflow.external_api import _period_to_date_range

        start, end = _period_to_date_range("")
        today = date.today()
        assert end == today.isoformat()
        assert start == (today - timedelta(days=29)).isoformat()


# ==================== 淘宝 TOP ====================


def _taobao_creds(**over):
    mapping = {
        "NEUROVA_TAOBAO_APP_KEY": "tb-key",
        "NEUROVA_TAOBAO_APP_SECRET": "tb-secret",
        "NEUROVA_TAOBAO_ACCESS_TOKEN": "tb-token",
        "NEUROVA_TAOBAO_REFRESH_TOKEN": None,
    }
    mapping.update(over)
    return _store_with(mapping)


class TestTaobaoTopClient:
    def test_is_available_requires_key_secret_and_token(self):
        from neurova.collaboration.neurflow.external_api import TaobaoTopClient

        with patch(f"{MOD}.get_secret_store", return_value=_taobao_creds()):
            assert TaobaoTopClient().is_available() is True
        with patch(f"{MOD}.get_secret_store", return_value=_taobao_creds(**{"NEUROVA_TAOBAO_ACCESS_TOKEN": None})):
            assert TaobaoTopClient().is_available() is False
        assert TaobaoTopClient().is_available(
            app_key="k", app_secret="s", access_token="t"
        ) is True

    @pytest.mark.asyncio
    async def test_call_posts_top_protocol_form(self):
        from neurova.collaboration.neurflow.external_api import TaobaoTopClient, _router_sign_md5

        mock_post = AsyncMock(return_value={"taobao_item_get_response": {"item": {"num_iid": 1, "price": "99.00"}}})
        with patch(f"{MOD}._http_post", mock_post):
            result = await TaobaoTopClient().call(
                "taobao.item.get", {"num_iid": "1", "fields": "price"},
                app_key="k", app_secret="sec", access_token="tok",
            )
        assert result["item"]["price"] == "99.00"

        args, kwargs = mock_post.call_args
        assert args[0] == "https://eco.taobao.com/router/rest"
        data = kwargs.get("data") or {}
        assert data["method"] == "taobao.item.get"
        assert data["app_key"] == "k"
        assert data["session"] == "tok"
        assert data["format"] == "json"
        assert data["v"] == "2.0"
        assert data["sign_method"] == "md5"
        assert data["num_iid"] == "1"
        assert data["fields"] == "price"
        import re

        assert re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$", data["timestamp"])
        sign = data.pop("sign")
        assert sign == _router_sign_md5("sec", data)

    @pytest.mark.asyncio
    async def test_call_raises_on_error_response(self):
        from neurova.collaboration.neurflow.external_api import ExternalAPIError, TaobaoTopClient

        mock_post = AsyncMock(return_value={
            "error_response": {"code": 15, "msg": "Remote service error", "sub_msg": "item not found"}
        })
        with patch(f"{MOD}._http_post", mock_post):
            with pytest.raises(ExternalAPIError) as exc:
                await TaobaoTopClient().call(
                    "taobao.item.get", {"num_iid": "1"},
                    app_key="k", app_secret="sec", access_token="tok",
                )
        assert "item not found" in str(exc.value)

    @pytest.mark.asyncio
    async def test_fetch_prices_uses_item_get(self):
        from neurova.collaboration.neurflow.external_api import TaobaoTopClient

        mock_post = AsyncMock(return_value={
            "taobao_item_get_response": {"item": {"num_iid": 123, "title": "测试商品", "price": "39.90", "num": 50}}
        })
        with patch(f"{MOD}._http_post", mock_post):
            result = await TaobaoTopClient().fetch_prices(
                ["123"], app_key="k", app_secret="sec", access_token="tok"
            )
        assert result["status"] == "success"
        assert result["output"]["prices"]["123"]["price"] == 39.9
        assert result["output"]["prices"]["123"]["currency"] == "CNY"
        data = mock_post.call_args.kwargs.get("data") or {}
        assert data["method"] == "taobao.item.get"
        assert data["num_iid"] == "123"

    @pytest.mark.asyncio
    async def test_fetch_inventory_uses_item_get_num(self):
        from neurova.collaboration.neurflow.external_api import TaobaoTopClient

        mock_post = AsyncMock(return_value={
            "taobao_item_get_response": {"item": {"num_iid": 123, "num": 7}}
        })
        with patch(f"{MOD}._http_post", mock_post):
            result = await TaobaoTopClient().fetch_inventory(
                ["123"], app_key="k", app_secret="sec", access_token="tok"
            )
        assert result["status"] == "success"
        assert result["output"]["inventory"]["123"]["totalQuantity"] == 7

    @pytest.mark.asyncio
    async def test_fetch_sold_trades_aggregates_payment(self):
        from neurova.collaboration.neurflow.external_api import TaobaoTopClient

        mock_post = AsyncMock(return_value={
            "taobao_trades_sold_get_response": {
                "total_results": 2,
                "trades": {"trade": [
                    {"tid": 1, "payment": "100.00", "num": 2},
                    {"tid": 2, "payment": "50.50", "num": 1},
                ]},
            }
        })
        with patch(f"{MOD}._http_post", mock_post):
            result = await TaobaoTopClient().fetch_sold_trades(
                start_created="2025-01-01 00:00:00", end_created="2025-01-31 23:59:59",
                app_key="k", app_secret="sec", access_token="tok",
            )
        assert result["status"] == "success"
        out = result["output"]
        assert out["orders"] == 2
        assert out["sales"] == pytest.approx(150.5)
        assert out["units"] == 3
        data = mock_post.call_args.kwargs.get("data") or {}
        assert data["method"] == "taobao.trades.sold.get"
        assert data["start_created"] == "2025-01-01 00:00:00"
        assert data["end_created"] == "2025-01-31 23:59:59"

    @pytest.mark.asyncio
    async def test_fetch_rates_maps_result_to_sentiment(self):
        from neurova.collaboration.neurflow.external_api import TaobaoTopClient

        mock_post = AsyncMock(return_value={
            "taobao_traderates_get_response": {
                "total": 2,
                "rates": {"rate": [
                    {"id": 1, "content": "质量很差", "result": "差评"},
                    {"id": 2, "content": "很好", "result": "好评"},
                ]},
            }
        })
        with patch(f"{MOD}._http_post", mock_post):
            result = await TaobaoTopClient().fetch_rates(
                "123", app_key="k", app_secret="sec", access_token="tok"
            )
        assert result["status"] == "success"
        items = result["output"]["items"]
        assert items[0]["sentiment"] == "negative"
        assert items[1]["sentiment"] == "positive"
        data = mock_post.call_args.kwargs.get("data") or {}
        assert data["method"] == "taobao.traderates.get"
        assert data["num_iid"] == "123"

    @pytest.mark.asyncio
    async def test_get_access_token_refresh_flow(self):
        from neurova.collaboration.neurflow.external_api import TAOBAO_OAUTH_TOKEN_URL, TaobaoTopClient

        mock_post = AsyncMock(return_value={"access_token": "new-tok", "expires_in": 86400})
        with patch(f"{MOD}._http_post", mock_post):
            token = await TaobaoTopClient().get_access_token(
                app_key="k", app_secret="sec", refresh_token="rt"
            )
        assert token == "new-tok"
        args, kwargs = mock_post.call_args
        assert args[0] == TAOBAO_OAUTH_TOKEN_URL
        data = kwargs.get("data") or {}
        assert data["grant_type"] == "refresh_token"
        assert data["client_id"] == "k"
        assert data["client_secret"] == "sec"
        assert data["refresh_token"] == "rt"


# ==================== 京东 ====================


class TestJdOpenClient:
    def test_is_available(self):
        from neurova.collaboration.neurflow.external_api import JdOpenClient

        assert JdOpenClient().is_available(app_key="k", app_secret="s", access_token="t") is True
        store = MagicMock()
        store.get.return_value = None
        with patch(f"{MOD}.get_secret_store", return_value=store):
            assert JdOpenClient().is_available() is False

    @pytest.mark.asyncio
    async def test_call_posts_jd_protocol_with_param_json(self):
        from neurova.collaboration.neurflow.external_api import JdOpenClient, _router_sign_md5

        mock_post = AsyncMock(return_value={
            "jingdong_pop_order_search_responce": {"totalCount": 0, "orderInfoList": {"orderInfo": []}}
        })
        with patch(f"{MOD}._http_post", mock_post):
            await JdOpenClient().call(
                "jingdong.pop.order.search", {"startDate": "2025-01-01 00:00:00"},
                app_key="k", app_secret="sec", access_token="tok",
            )
        args, kwargs = mock_post.call_args
        assert args[0] == "https://api.jd.com/routerjson"
        data = kwargs.get("data") or {}
        assert data["method"] == "jingdong.pop.order.search"
        assert data["app_key"] == "k"
        assert data["access_token"] == "tok"
        assert data["v"] == "1.0"
        assert data["format"] == "json"
        import json

        assert json.loads(data["360buy_param_json"]) == {"startDate": "2025-01-01 00:00:00"}
        sign = data.pop("sign")
        assert sign == _router_sign_md5("sec", data)

    @pytest.mark.asyncio
    async def test_call_accepts_response_and_responce_spelling(self):
        from neurova.collaboration.neurflow.external_api import JdOpenClient

        mock_post = AsyncMock(return_value={
            "jingdong_pop_order_search_response": {"totalCount": 1}
        })
        with patch(f"{MOD}._http_post", mock_post):
            result = await JdOpenClient().call(
                "jingdong.pop.order.search", {},
                app_key="k", app_secret="sec", access_token="tok",
            )
        assert result["totalCount"] == 1

    @pytest.mark.asyncio
    async def test_fetch_orders_aggregates_payment(self):
        from neurova.collaboration.neurflow.external_api import JdOpenClient

        mock_post = AsyncMock(return_value={
            "jingdong_pop_order_search_responce": {
                "totalCount": 2,
                "orderInfoList": {"orderInfo": [
                    {"orderId": 1, "orderPayment": "88.00", "itemTotal": 2},
                    {"orderId": 2, "orderPayment": "12.00", "itemTotal": 1},
                ]},
            }
        })
        with patch(f"{MOD}._http_post", mock_post):
            result = await JdOpenClient().fetch_orders(
                start_date="2025-01-01 00:00:00", end_date="2025-01-31 23:59:59",
                app_key="k", app_secret="sec", access_token="tok",
            )
        assert result["status"] == "success"
        assert result["output"]["orders"] == 2
        assert result["output"]["sales"] == pytest.approx(100.0)
        data = mock_post.call_args.kwargs.get("data") or {}
        import json

        params = json.loads(data["360buy_param_json"])
        assert params["startDate"] == "2025-01-01 00:00:00"
        assert params["endDate"] == "2025-01-31 23:59:59"

    @pytest.mark.asyncio
    async def test_fetch_skus_extracts_price_and_stock(self):
        from neurova.collaboration.neurflow.external_api import JdOpenClient

        mock_post = AsyncMock(return_value={
            "jingdong_ware_read_findSkuListPage_responce": {
                "skuList": {"sku": [
                    {"skuId": 1001, "title": "商品A", "jdPrice": 59.9, "stockNum": 30},
                ]}
            }
        })
        with patch(f"{MOD}._http_post", mock_post):
            result = await JdOpenClient().fetch_skus(
                app_key="k", app_secret="sec", access_token="tok"
            )
        assert result["status"] == "success"
        skus = result["output"]["skus"]
        assert skus["1001"]["price"] == 59.9
        assert skus["1001"]["stock"] == 30


# ==================== 拼多多 ====================


class TestPddOpenClient:
    def test_is_available(self):
        from neurova.collaboration.neurflow.external_api import PddOpenClient

        assert PddOpenClient().is_available(client_id="c", client_secret="s", access_token="t") is True
        assert PddOpenClient().is_available(client_id="c", client_secret="s") is False

    @pytest.mark.asyncio
    async def test_call_posts_pdd_protocol_flat_params(self):
        from neurova.collaboration.neurflow.external_api import PddOpenClient, _router_sign_md5

        mock_post = AsyncMock(return_value={
            "pdd_order_list_get_response": {"total_count": 0, "order_list": []}
        })
        with patch(f"{MOD}._http_post", mock_post):
            await PddOpenClient().call(
                "pdd.order.list.get", {"page": 1, "page_size": 50},
                client_id="cid", client_secret="sec", access_token="tok",
            )
        args, kwargs = mock_post.call_args
        assert args[0] == "https://gw-api.pinduoduo.com/api/router"
        data = kwargs.get("data") or {}
        assert data["type"] == "pdd.order.list.get"
        assert data["client_id"] == "cid"
        assert data["access_token"] == "tok"
        assert data["data_type"] == "JSON"
        assert data["timestamp"].isdigit(), "拼多多 timestamp 应为 unix 秒"
        assert data["page"] == "1"
        assert data["page_size"] == "50"
        sign = data.pop("sign")
        assert sign == _router_sign_md5("sec", data)

    @pytest.mark.asyncio
    async def test_fetch_orders_converts_fen_to_yuan(self):
        from neurova.collaboration.neurflow.external_api import PddOpenClient

        mock_post = AsyncMock(return_value={
            "pdd_order_list_get_response": {
                "total_count": 1,
                "order_list": [{"order_sn": "PDD1", "pay_amount": 9900, "goods_amount": 2}],
            }
        })
        with patch(f"{MOD}._http_post", mock_post):
            result = await PddOpenClient().fetch_orders(
                start_updated_at=1735689600, end_updated_at=1738367999,
                client_id="cid", client_secret="sec", access_token="tok",
            )
        assert result["status"] == "success"
        assert result["output"]["orders"] == 1
        assert result["output"]["sales"] == pytest.approx(99.0)
        data = mock_post.call_args.kwargs.get("data") or {}
        assert data["type"] == "pdd.order.list.get"
        assert data["start_updated_at"] == "1735689600"
        assert data["end_updated_at"] == "1738367999"

    @pytest.mark.asyncio
    async def test_fetch_goods_price_and_quantity(self):
        from neurova.collaboration.neurflow.external_api import PddOpenClient

        mock_post = AsyncMock(return_value={
            "pdd_goods_information_get_response": {
                "goods_details": [{
                    "goods_id": 555, "goods_name": "商品P",
                    "min_group_price": 1990, "goods_quantity": 42,
                }]
            }
        })
        with patch(f"{MOD}._http_post", mock_post):
            result = await PddOpenClient().fetch_goods(
                ["555"], client_id="cid", client_secret="sec", access_token="tok"
            )
        assert result["status"] == "success"
        assert result["output"]["prices"]["555"]["price"] == pytest.approx(19.9)
        assert result["output"]["inventory"]["555"]["totalQuantity"] == 42


# ==================== 抖店 ====================


class TestDouyinEcomClient:
    def test_is_available(self):
        from neurova.collaboration.neurflow.external_api import DouyinEcomClient

        assert DouyinEcomClient().is_available(app_key="k", app_secret="s", access_token="t") is True
        assert DouyinEcomClient().is_available(app_key="k", app_secret="s") is False

    @pytest.mark.asyncio
    async def test_call_posts_douyin_protocol(self):
        from neurova.collaboration.neurflow.external_api import DouyinEcomClient, _douyin_sign_md5

        mock_post = AsyncMock(return_value={"err_no": 0, "message": "success", "data": {"total": 0}})
        with patch(f"{MOD}._http_post", mock_post):
            await DouyinEcomClient().call(
                "order.searchList", {"page": 0, "size": 10},
                app_key="k", app_secret="sec", access_token="tok",
            )
        args, kwargs = mock_post.call_args
        assert args[0] == "https://openapi-fxg.jinritemai.com"
        data = kwargs.get("data") or {}
        assert data["app_key"] == "k"
        assert data["method"] == "order.searchList"
        assert data["v"] == "2"
        assert data["sign_method"] == "md5"
        assert data["access_token"] == "tok"
        assert data["timestamp"].isdigit()
        import json

        assert json.loads(data["param_json"]) == {"page": 0, "size": 10}
        sign = data.pop("sign")
        signable = {k: data[k] for k in ("app_key", "method", "param_json", "timestamp", "v")}
        assert sign == _douyin_sign_md5("sec", signable)

    @pytest.mark.asyncio
    async def test_call_raises_on_err_no(self):
        from neurova.collaboration.neurflow.external_api import DouyinEcomClient, ExternalAPIError

        mock_post = AsyncMock(return_value={"err_no": 10001, "message": "access_token 无效", "data": None})
        with patch(f"{MOD}._http_post", mock_post):
            with pytest.raises(ExternalAPIError) as exc:
                await DouyinEcomClient().call(
                    "order.searchList", {}, app_key="k", app_secret="sec", access_token="tok"
                )
        assert "access_token" in str(exc.value)

    @pytest.mark.asyncio
    async def test_fetch_orders_converts_fen(self):
        from neurova.collaboration.neurflow.external_api import DouyinEcomClient

        mock_post = AsyncMock(return_value={
            "err_no": 0, "message": "success",
            "data": {
                "total": 1,
                "shop_order_list": [{"order_id": "D1", "pay_amount": 12345, "total_amount": 13000}],
            },
        })
        with patch(f"{MOD}._http_post", mock_post):
            result = await DouyinEcomClient().fetch_orders(
                create_time_start=1735689600, create_time_end=1738367999,
                app_key="k", app_secret="sec", access_token="tok",
            )
        assert result["status"] == "success"
        assert result["output"]["orders"] == 1
        assert result["output"]["sales"] == pytest.approx(123.45)
        import json

        data = mock_post.call_args.kwargs.get("data") or {}
        assert data["method"] == "order.searchList"
        params = json.loads(data["param_json"])
        assert params["create_time_start"] == 1735689600
        assert params["create_time_end"] == 1738367999

    @pytest.mark.asyncio
    async def test_fetch_products_price_in_fen(self):
        from neurova.collaboration.neurflow.external_api import DouyinEcomClient

        mock_post = AsyncMock(return_value={
            "err_no": 0, "message": "success",
            "data": {
                "total": 1,
                "data": [{"product_id": "9001", "name": "抖店商品", "discount_price": 2990, "stock_num": 15}],
            },
        })
        with patch(f"{MOD}._http_post", mock_post):
            result = await DouyinEcomClient().fetch_products(
                app_key="k", app_secret="sec", access_token="tok"
            )
        assert result["status"] == "success"
        assert result["output"]["prices"]["9001"]["price"] == pytest.approx(29.9)
        assert result["output"]["inventory"]["9001"]["totalQuantity"] == 15


# ==================== TikTok Shop ====================


class TestTikTokShopClient:
    def test_is_available(self):
        from neurova.collaboration.neurflow.external_api import TikTokShopClient

        assert TikTokShopClient().is_available(app_key="k", app_secret="s", access_token="t") is True
        assert TikTokShopClient().is_available(app_key="k", app_secret="s") is False

    @pytest.mark.asyncio
    async def test_fetch_products_get_with_sha256_sign(self):
        from neurova.collaboration.neurflow.external_api import TikTokShopClient, _tiktok_sign_sha256

        mock_get = AsyncMock(return_value={
            "code": 0, "message": "success",
            "data": {
                "total_count": 1,
                "products": [{
                    "id": "7001",
                    "title": "TikTok product",
                    "price": {"sale_price": {"amount": "1500", "currency_code": "USD"}},
                    "skus": [{"stock_infos": [{"available_stock": 9}]}],
                }],
            },
        })
        with patch(f"{MOD}._http_get", mock_get):
            result = await TikTokShopClient().fetch_products(
                app_key="k", app_secret="sec", access_token="tok"
            )
        assert result["status"] == "success"
        assert result["output"]["prices"]["7001"]["price"] == pytest.approx(15.0)
        assert result["output"]["prices"]["7001"]["currency"] == "USD"
        assert result["output"]["inventory"]["7001"]["totalQuantity"] == 9

        args, kwargs = mock_get.call_args
        assert args[0] == "https://open-api.tiktokglobalshop.com/product/202309/products"
        params = kwargs.get("params") or {}
        assert params["app_key"] == "k"
        assert params["access_token"] == "tok"
        assert str(params["timestamp"]).isdigit()
        sign = params.pop("sign")
        assert sign == _tiktok_sign_sha256("sec", params)

    @pytest.mark.asyncio
    async def test_search_orders_post_includes_body_in_sign(self):
        from neurova.collaboration.neurflow.external_api import TikTokShopClient, _tiktok_sign_sha256

        mock_post = AsyncMock(return_value={
            "code": 0, "message": "success",
            "data": {
                "total_count": 1,
                "orders": [{"id": "O1", "payment_amount": {"amount": "8800", "currency_code": "USD"}}],
            },
        })
        with patch(f"{MOD}._http_post", mock_post):
            result = await TikTokShopClient().search_orders(
                create_time_ge=1735689600, create_time_lt=1738368000,
                app_key="k", app_secret="sec", access_token="tok",
            )
        assert result["status"] == "success"
        assert result["output"]["orders"] == 1
        assert result["output"]["sales"] == pytest.approx(88.0)

        args, kwargs = mock_post.call_args
        assert args[0] == "https://open-api.tiktokglobalshop.com/order/202309/orders/search"
        params = kwargs.get("params") or {}
        body = kwargs.get("json") or {}
        assert body["create_time_ge"] == 1735689600
        sign = params.pop("sign")
        signable = dict(params)
        signable.update({k: v for k, v in body.items()})
        assert sign == _tiktok_sign_sha256("sec", signable)

    @pytest.mark.asyncio
    async def test_call_raises_on_nonzero_code(self):
        from neurova.collaboration.neurflow.external_api import ExternalAPIError, TikTokShopClient

        mock_get = AsyncMock(return_value={"code": 30001, "message": "invalid app_key", "data": None})
        with patch(f"{MOD}._http_get", mock_get):
            with pytest.raises(ExternalAPIError):
                await TikTokShopClient()._request(
                    "GET", "/product/202309/products",
                    app_key="k", app_secret="sec", access_token="tok",
                )

    @pytest.mark.asyncio
    async def test_fetch_products_failed_returns_fail_status(self):
        from neurova.collaboration.neurflow.external_api import TikTokShopClient

        mock_get = AsyncMock(return_value={"code": 30001, "message": "invalid app_key", "data": None})
        with patch(f"{MOD}._http_get", mock_get):
            result = await TikTokShopClient().fetch_products(
                app_key="k", app_secret="sec", access_token="tok"
            )
        assert result["status"] == "failed"
        assert "invalid app_key" in result["error"]


# ==================== CommercePlatformClient 路由 ====================


class TestCommerceClientCnRouting:
    """五个平台路由到各自的开放平台客户端"""

    @pytest.mark.asyncio
    async def test_fetch_prices_routes_to_platform_clients(self):
        from neurova.collaboration.neurflow.external_api import CommercePlatformClient

        ok = {"status": "success", "output": {"prices": {}}, "error": None, "provider": ""}
        cases = [
            ("taobao", "TaobaoTopClient"),
            ("jd", "JdOpenClient"),
            ("pdd", "PddOpenClient"),
            ("douyin-ecom", "DouyinEcomClient"),
            ("tiktok", "TikTokShopClient"),
        ]
        for platform, cls_name in cases:
            with patch(f"{MOD}.{cls_name}.fetch_prices", AsyncMock(return_value=ok)) as mock_fp:
                result = await CommercePlatformClient().fetch_prices(platform, ["ID1"])
            assert result["status"] == "success", platform
            mock_fp.assert_called_once()

    @pytest.mark.asyncio
    async def test_fetch_sales_report_taobao_converts_period(self):
        from neurova.collaboration.neurflow.external_api import CommercePlatformClient

        ok = {"status": "success", "output": {"sales": 1.0, "orders": 1, "units": 1}, "error": None, "provider": "taobao"}
        with patch(f"{MOD}.TaobaoTopClient.fetch_sold_trades", AsyncMock(return_value=ok)) as mock_ft:
            result = await CommercePlatformClient().fetch_sales_report("taobao", period="2025-01")
        assert result["status"] == "success"
        _, kwargs = mock_ft.call_args
        assert kwargs.get("start_created") == "2025-01-01 00:00:00"
        assert kwargs.get("end_created") == "2025-01-31 23:59:59"

    @pytest.mark.asyncio
    async def test_fetch_sales_report_pdd_uses_unix_range(self):
        from neurova.collaboration.neurflow.external_api import CommercePlatformClient

        ok = {"status": "success", "output": {"sales": 1.0, "orders": 1}, "error": None, "provider": "pdd"}
        with patch(f"{MOD}.PddOpenClient.fetch_orders", AsyncMock(return_value=ok)) as mock_fo:
            await CommercePlatformClient().fetch_sales_report("pdd", period="2025-01-01~2025-01-10")
        _, kwargs = mock_fo.call_args
        assert isinstance(kwargs.get("start_updated_at"), int)
        assert isinstance(kwargs.get("end_updated_at"), int)
        assert kwargs["end_updated_at"] > kwargs["start_updated_at"]

    @pytest.mark.asyncio
    async def test_fetch_reviews_taobao_uses_traderates(self):
        from neurova.collaboration.neurflow.external_api import CommercePlatformClient

        ok = {"status": "success", "output": {"items": [{"id": 1, "content": "差评内容", "sentiment": "negative"}]}, "error": None, "provider": "taobao"}
        with patch(f"{MOD}.TaobaoTopClient.fetch_rates", AsyncMock(return_value=ok)) as mock_fr:
            result = await CommercePlatformClient().fetch_reviews("taobao", "123")
        assert result["status"] == "success"
        args, kwargs = mock_fr.call_args
        assert (args[0] if args else kwargs.get("num_iid")) == "123"

    @pytest.mark.asyncio
    async def test_fetch_reviews_unsupported_platforms_fail_with_note(self):
        from neurova.collaboration.neurflow.external_api import CommercePlatformClient

        for platform in ("jd", "pdd", "douyin-ecom", "tiktok"):
            result = await CommercePlatformClient().fetch_reviews(platform, "ID1")
            assert result["status"] == "failed", platform
            assert "评论" in result["error"]

    @pytest.mark.asyncio
    async def test_fetch_competitors_cn_platforms_not_supported(self):
        from neurova.collaboration.neurflow.external_api import CommercePlatformClient

        for platform in ("taobao", "jd", "pdd", "douyin-ecom", "tiktok"):
            result = await CommercePlatformClient().fetch_competitors(platform, "蓝牙耳机")
            assert result["status"] == "failed", platform
            assert "竞品" in result["error"]

    @pytest.mark.asyncio
    async def test_fetch_ad_metrics_points_to_separate_ad_platforms(self):
        from neurova.collaboration.neurflow.external_api import CommercePlatformClient

        expected_hint = {
            "taobao": "阿里妈妈",
            "jd": "京准通",
            "pdd": "多多",
            "douyin-ecom": "千川",
            "tiktok": "TikTok Ads",
        }
        for platform, hint in expected_hint.items():
            result = await CommercePlatformClient().fetch_ad_metrics(platform, ["ad1"], ["clicks"])
            assert result["status"] == "failed", platform
            assert hint in result["error"], f"{platform} 应提示其独立广告平台 {hint}"

    def test_is_available_delegates_to_clients(self):
        from neurova.collaboration.neurflow.external_api import CommercePlatformClient

        with patch(f"{MOD}.TaobaoTopClient.is_available", return_value=True):
            assert CommercePlatformClient().is_available("taobao") is True
        with patch(f"{MOD}.TikTokShopClient.is_available", return_value=False):
            assert CommercePlatformClient().is_available("tiktok") is False
