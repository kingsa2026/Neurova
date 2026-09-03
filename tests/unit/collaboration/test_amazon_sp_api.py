"""
Amazon SP-API 客户端测试 — 基于亚马逊开放平台官方开发文档

文档来源（developer-docs.amazon.com/sp-api）：
1. 认证流程：LWA（Login with Amazon）令牌交换
   POST https://api.amazon.com/auth/o2/token
   grant_type=refresh_token & refresh_token & client_id & client_secret
   → access_token（expires_in=3600）
2. 调用头：x-amz-access-token / x-amz-date / user-agent（非 Authorization: Bearer）
3. 区域端点：NA/EU/FE 三个 sellingpartnerapi-*.amazon.com
4. MarketplaceId：US=ATVPDKIKX0DER 等（Store Identifiers 文档）
5. 价格监控 → Product Pricing API v0 getPricing
   GET /products/pricing/v0/pricing?MarketplaceId=&ItemType=Asin&Asins=
6. 库存 → FBA Inventory API v1 getInventorySummaries
   GET /fba/inventory/v1/summaries?granularityType=Marketplace&granularityId=&marketplaceIds=&sellerSkus=
7. 评论洞察 → Customer Feedback API v2024-06-01 getItemReviewTopics
   GET /customerFeedback/2024-06-01/items/{asin}/reviews/topics?marketplaceId=&sortBy=MENTIONS
   （SP-API 不提供原始评论拉取与回复提交，仅提供评论主题洞察）
8. 销售报表 → Reports API v2021-06-30
   POST /reports/2021-06-30/reports → getReport 轮询 → getReportDocument 下载
"""
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

MOD = "neurova.collaboration.neurflow.external_api"


def _creds_store(refresh="rt-test", client_id="cid-test", client_secret="cs-test"):
    """构造按 key 名返回 SP-API 三件套的 SecretStore mock"""
    mapping = {
        "NEUROVA_AMAZON_SP_REFRESH_TOKEN": refresh,
        "NEUROVA_AMAZON_SP_CLIENT_ID": client_id,
        "NEUROVA_AMAZON_SP_CLIENT_SECRET": client_secret,
    }
    store = MagicMock()
    store.get.side_effect = lambda name: mapping.get(name)
    return store


class TestAmazonSPAPIConstants:
    """官方文档中的区域端点与 MarketplaceId 常量"""

    def test_sp_regions_match_official_endpoints(self):
        from neurova.collaboration.neurflow.external_api import AMAZON_SP_REGIONS

        assert AMAZON_SP_REGIONS == {
            "na": "https://sellingpartnerapi-na.amazon.com",
            "eu": "https://sellingpartnerapi-eu.amazon.com",
            "fe": "https://sellingpartnerapi-fe.amazon.com",
        }

    def test_marketplace_ids_match_official_store_identifiers(self):
        from neurova.collaboration.neurflow.external_api import AMAZON_SP_MARKETPLACES

        assert AMAZON_SP_MARKETPLACES["US"] == "ATVPDKIKX0DER"
        assert AMAZON_SP_MARKETPLACES["CA"] == "A2EUQ1WTGCTBG2"
        assert AMAZON_SP_MARKETPLACES["MX"] == "A1AM78C64UM0Y8"
        assert AMAZON_SP_MARKETPLACES["BR"] == "A2Q3Y263D00KWC"
        assert AMAZON_SP_MARKETPLACES["UK"] == "A1F83G8C2ARO7P"
        assert AMAZON_SP_MARKETPLACES["DE"] == "A1PA6795UKMFR9"
        assert AMAZON_SP_MARKETPLACES["FR"] == "A13V1IB3VIYZZH"
        assert AMAZON_SP_MARKETPLACES["IT"] == "APJ6JRA9NG5V4"
        assert AMAZON_SP_MARKETPLACES["ES"] == "A1RKKUPIHCS9HS"
        assert AMAZON_SP_MARKETPLACES["JP"] == "A1VC38T7YXB528"
        assert AMAZON_SP_MARKETPLACES["SG"] == "A19VAU5U5O7RUS"
        assert AMAZON_SP_MARKETPLACES["AU"] == "A39IBJ37TRP1C6"

    def test_lwa_token_url(self):
        from neurova.collaboration.neurflow.external_api import AMAZON_LWA_TOKEN_URL

        assert AMAZON_LWA_TOKEN_URL == "https://api.amazon.com/auth/o2/token"

    def test_report_types_include_official_values(self):
        from neurova.collaboration.neurflow.external_api import AMAZON_SP_REPORT_TYPES

        values = [t["value"] for t in AMAZON_SP_REPORT_TYPES]
        assert "GET_FLAT_FILE_ALL_ORDERS_DATA_BY_ORDER_DATE_GENERAL" in values
        assert "GET_AMAZON_FULFILLED_SHIPMENTS_DATA_GENERAL" in values
        assert "GET_FBA_INVENTORY_RECEIPT_SUMMARY" in values
        assert "GET_MERCHANT_LISTINGS_ALL_DATA" in values


class TestAmazonSPAPIClientAvailability:
    """可用性检测：需同时具备 refresh_token / client_id / client_secret"""

    def test_unavailable_without_credentials(self):
        from neurova.collaboration.neurflow.external_api import AmazonSPAPIClient

        store = MagicMock()
        store.get.return_value = None
        with patch(f"{MOD}.get_secret_store", return_value=store):
            assert AmazonSPAPIClient().is_available() is False

    def test_unavailable_with_partial_credentials(self):
        from neurova.collaboration.neurflow.external_api import AmazonSPAPIClient

        store = _creds_store(client_secret=None)
        with patch(f"{MOD}.get_secret_store", return_value=store):
            assert AmazonSPAPIClient().is_available() is False

    def test_available_with_full_credentials_from_store(self):
        from neurova.collaboration.neurflow.external_api import AmazonSPAPIClient

        store = _creds_store()
        with patch(f"{MOD}.get_secret_store", return_value=store):
            assert AmazonSPAPIClient().is_available() is True

    def test_available_with_explicit_credentials(self):
        from neurova.collaboration.neurflow.external_api import AmazonSPAPIClient

        store = MagicMock()
        store.get.return_value = None
        with patch(f"{MOD}.get_secret_store", return_value=store):
            assert AmazonSPAPIClient().is_available(
                refresh_token="rt", client_id="cid", client_secret="cs"
            ) is True


class TestAmazonSPAPIClientAuth:
    """LWA 令牌交换流程"""

    @pytest.mark.asyncio
    async def test_get_access_token_posts_lwa_form(self):
        from neurova.collaboration.neurflow.external_api import AmazonSPAPIClient, AMAZON_LWA_TOKEN_URL

        mock_post = AsyncMock(return_value={"access_token": "Atza|tok", "token_type": "bearer", "expires_in": 3600})
        with patch(f"{MOD}._http_post", mock_post):
            token = await AmazonSPAPIClient().get_access_token(
                refresh_token="rt", client_id="cid", client_secret="cs"
            )
        assert token == "Atza|tok"
        args, kwargs = mock_post.call_args
        assert args[0] == AMAZON_LWA_TOKEN_URL
        data = kwargs.get("data") or {}
        assert data.get("grant_type") == "refresh_token"
        assert data.get("refresh_token") == "rt"
        assert data.get("client_id") == "cid"
        assert data.get("client_secret") == "cs"

    @pytest.mark.asyncio
    async def test_get_access_token_uses_secret_store(self):
        from neurova.collaboration.neurflow.external_api import AmazonSPAPIClient

        mock_post = AsyncMock(return_value={"access_token": "Atza|tok2", "expires_in": 3600})
        store = _creds_store()
        with patch(f"{MOD}._http_post", mock_post), \
             patch(f"{MOD}.get_secret_store", return_value=store):
            token = await AmazonSPAPIClient().get_access_token()
        assert token == "Atza|tok2"
        data = mock_post.call_args.kwargs.get("data") or {}
        assert data.get("refresh_token") == "rt-test"

    @pytest.mark.asyncio
    async def test_get_access_token_raises_without_credentials(self):
        from neurova.collaboration.neurflow.external_api import AmazonSPAPIClient, ExternalAPIError

        store = MagicMock()
        store.get.return_value = None
        with patch(f"{MOD}.get_secret_store", return_value=store):
            with pytest.raises(ExternalAPIError):
                await AmazonSPAPIClient().get_access_token()


class TestAmazonSPAPIClientPricing:
    """Product Pricing API v0 getPricing"""

    @pytest.mark.asyncio
    async def test_fetch_prices_calls_get_pricing_endpoint(self):
        from neurova.collaboration.neurflow.external_api import AmazonSPAPIClient

        sp_payload = {
            "payload": [
                {
                    "asin": "B0TEST",
                    "product": {
                        "offers": [
                            {"buyingPrice": {"amount": 99.0, "currencyCode": "USD"}, "listingPrice": {"amount": 109.0, "currencyCode": "USD"}}
                        ]
                    },
                }
            ]
        }
        mock_post = AsyncMock(return_value={"access_token": "Atza|tok", "expires_in": 3600})
        mock_get = AsyncMock(return_value=sp_payload)
        with patch(f"{MOD}._http_post", mock_post), patch(f"{MOD}._http_get", mock_get):
            result = await AmazonSPAPIClient().fetch_prices(
                ["B0TEST"], marketplace_id="ATVPDKIKX0DER", region="na",
                refresh_token="rt", client_id="cid", client_secret="cs",
            )
        assert result["status"] == "success"
        assert result["output"]["prices"]["B0TEST"]["price"] == 99.0
        assert result["output"]["prices"]["B0TEST"]["currency"] == "USD"

        url = mock_get.call_args.args[0]
        params = mock_get.call_args.kwargs.get("params") or {}
        assert url == "https://sellingpartnerapi-na.amazon.com/products/pricing/v0/pricing"
        assert params.get("MarketplaceId") == "ATVPDKIKX0DER"
        assert params.get("ItemType") == "Asin"
        assert params.get("Asins") == "B0TEST"

        headers = mock_get.call_args.kwargs.get("headers") or {}
        assert headers.get("x-amz-access-token") == "Atza|tok"
        assert "user-agent" in {k.lower() for k in headers}

    @pytest.mark.asyncio
    async def test_fetch_prices_uses_eu_endpoint(self):
        from neurova.collaboration.neurflow.external_api import AmazonSPAPIClient

        mock_post = AsyncMock(return_value={"access_token": "Atza|tok", "expires_in": 3600})
        mock_get = AsyncMock(return_value={"payload": []})
        with patch(f"{MOD}._http_post", mock_post), patch(f"{MOD}._http_get", mock_get):
            result = await AmazonSPAPIClient().fetch_prices(
                ["B0TEST"], marketplace_id="A1PA6795UKMFR9", region="eu",
                refresh_token="rt", client_id="cid", client_secret="cs",
            )
        assert result["status"] == "success"
        assert mock_get.call_args.args[0].startswith("https://sellingpartnerapi-eu.amazon.com")

    @pytest.mark.asyncio
    async def test_fetch_prices_accepts_country_code_as_marketplace(self):
        from neurova.collaboration.neurflow.external_api import AmazonSPAPIClient

        mock_post = AsyncMock(return_value={"access_token": "Atza|tok", "expires_in": 3600})
        mock_get = AsyncMock(return_value={"payload": []})
        with patch(f"{MOD}._http_post", mock_post), patch(f"{MOD}._http_get", mock_get):
            await AmazonSPAPIClient().fetch_prices(
                ["B0TEST"], marketplace_id="US", region="na",
                refresh_token="rt", client_id="cid", client_secret="cs",
            )
        params = mock_get.call_args.kwargs.get("params") or {}
        assert params.get("MarketplaceId") == "ATVPDKIKX0DER"

    @pytest.mark.asyncio
    async def test_fetch_prices_failed_without_credentials(self):
        from neurova.collaboration.neurflow.external_api import AmazonSPAPIClient

        store = MagicMock()
        store.get.return_value = None
        with patch(f"{MOD}.get_secret_store", return_value=store):
            result = await AmazonSPAPIClient().fetch_prices(["B0TEST"])
        assert result["status"] == "failed"
        assert result["output"] is None

    @pytest.mark.asyncio
    async def test_fetch_prices_network_error_isolated(self):
        from neurova.collaboration.neurflow.external_api import AmazonSPAPIClient, ExternalAPIError

        async def _boom(*a, **k):
            raise ExternalAPIError("connection refused")

        with patch(f"{MOD}._http_post", _boom):
            result = await AmazonSPAPIClient().fetch_prices(
                ["B0TEST"], refresh_token="rt", client_id="cid", client_secret="cs"
            )
        assert result["status"] == "failed"
        assert "connection refused" in result["error"]

    @pytest.mark.asyncio
    async def test_fetch_competitive_prices_calls_competitive_endpoint(self):
        from neurova.collaboration.neurflow.external_api import AmazonSPAPIClient

        sp_payload = {
            "payload": [
                {
                    "asin": "B0COMP",
                    "product": {
                        "competitivePricing": {
                            "competitivePrices": [
                                {"price": {"landedPrice": {"amount": 88.5, "currencyCode": "USD"}}}
                            ]
                        }
                    },
                }
            ]
        }
        mock_post = AsyncMock(return_value={"access_token": "Atza|tok", "expires_in": 3600})
        mock_get = AsyncMock(return_value=sp_payload)
        with patch(f"{MOD}._http_post", mock_post), patch(f"{MOD}._http_get", mock_get):
            result = await AmazonSPAPIClient().fetch_competitive_prices(
                ["B0COMP"], marketplace_id="ATVPDKIKX0DER",
                refresh_token="rt", client_id="cid", client_secret="cs",
            )
        assert result["status"] == "success"
        assert result["output"]["prices"]["B0COMP"]["price"] == 88.5
        assert "/products/pricing/v0/competitivePrice" in mock_get.call_args.args[0]


class TestAmazonSPAPIClientInventory:
    """FBA Inventory API v1 getInventorySummaries"""

    @pytest.mark.asyncio
    async def test_fetch_inventory_calls_summaries_endpoint(self):
        from neurova.collaboration.neurflow.external_api import AmazonSPAPIClient

        sp_payload = {
            "payload": {
                "inventorySummaries": [
                    {
                        "sellerSku": "SKU1",
                        "asin": "B0TEST",
                        "totalQuantity": 12,
                        "inventoryDetails": {"fulfillableQuantity": 10},
                    }
                ]
            }
        }
        mock_post = AsyncMock(return_value={"access_token": "Atza|tok", "expires_in": 3600})
        mock_get = AsyncMock(return_value=sp_payload)
        with patch(f"{MOD}._http_post", mock_post), patch(f"{MOD}._http_get", mock_get):
            result = await AmazonSPAPIClient().fetch_inventory(
                ["SKU1"], marketplace_id="ATVPDKIKX0DER", region="na",
                refresh_token="rt", client_id="cid", client_secret="cs",
            )
        assert result["status"] == "success"
        assert result["output"]["inventory"]["SKU1"]["totalQuantity"] == 12
        assert result["output"]["inventory"]["SKU1"]["fulfillableQuantity"] == 10

        url = mock_get.call_args.args[0]
        params = mock_get.call_args.kwargs.get("params") or {}
        assert url == "https://sellingpartnerapi-na.amazon.com/fba/inventory/v1/summaries"
        assert params.get("granularityType") == "Marketplace"
        assert params.get("granularityId") == "ATVPDKIKX0DER"
        assert params.get("marketplaceIds") == "ATVPDKIKX0DER"
        assert params.get("sellerSkus") == "SKU1"


class TestAmazonSPAPIClientReviews:
    """Customer Feedback API v2024-06-01 getItemReviewTopics"""

    @pytest.mark.asyncio
    async def test_fetch_review_topics_calls_official_path(self):
        from neurova.collaboration.neurflow.external_api import AmazonSPAPIClient

        sp_payload = {
            "asin": "B0TEST",
            "topics": {
                "positiveTopics": [{"topic": "Quality", "reviewSnippets": ["Great quality"]}],
                "negativeTopics": [{"topic": "Assembly", "reviewSnippets": ["Hard to assemble"]}],
            },
        }
        mock_post = AsyncMock(return_value={"access_token": "Atza|tok", "expires_in": 3600})
        mock_get = AsyncMock(return_value=sp_payload)
        with patch(f"{MOD}._http_post", mock_post), patch(f"{MOD}._http_get", mock_get):
            result = await AmazonSPAPIClient().fetch_review_topics(
                "B0TEST", marketplace_id="ATVPDKIKX0DER",
                refresh_token="rt", client_id="cid", client_secret="cs",
            )
        assert result["status"] == "success"
        assert result["output"]["positive_topics"][0]["topic"] == "Quality"
        assert result["output"]["negative_topics"][0]["topic"] == "Assembly"

        url = mock_get.call_args.args[0]
        params = mock_get.call_args.kwargs.get("params") or {}
        assert url == "https://sellingpartnerapi-na.amazon.com/customerFeedback/2024-06-01/items/B0TEST/reviews/topics"
        assert params.get("marketplaceId") == "ATVPDKIKX0DER"
        assert params.get("sortBy") == "MENTIONS"


class TestAmazonSPAPIClientReports:
    """Reports API v2021-06-30：createReport → getReport → getReportDocument"""

    @pytest.mark.asyncio
    async def test_create_report_posts_report_type(self):
        from neurova.collaboration.neurflow.external_api import AmazonSPAPIClient

        mock_post = AsyncMock(return_value={"access_token": "Atza|tok", "expires_in": 3600})
        mock_post_report = AsyncMock(return_value={"reportId": "REP1"})

        calls = []

        async def _post(url, headers=None, json=None, data=None, params=None, timeout=30.0):
            calls.append((url, json, data))
            if "auth/o2/token" in url:
                return {"access_token": "Atza|tok", "expires_in": 3600}
            return {"reportId": "REP1"}

        with patch(f"{MOD}._http_post", AsyncMock(side_effect=_post)):
            result = await AmazonSPAPIClient().create_report(
                report_type="GET_FLAT_FILE_ALL_ORDERS_DATA_BY_ORDER_DATE_GENERAL",
                marketplace_ids=["ATVPDKIKX0DER"],
                data_start_time="2025-01-01T00:00:00Z",
                data_end_time="2025-02-01T00:00:00Z",
                refresh_token="rt", client_id="cid", client_secret="cs",
            )
        assert result["status"] == "success"
        assert result["output"]["reportId"] == "REP1"
        report_calls = [c for c in calls if "reports/2021-06-30/reports" in c[0]]
        assert report_calls, "未调用 createReport 端点"
        body = report_calls[0][1]
        assert body["reportType"] == "GET_FLAT_FILE_ALL_ORDERS_DATA_BY_ORDER_DATE_GENERAL"
        assert body["marketplaceIds"] == ["ATVPDKIKX0DER"]
        assert body["dataStartTime"] == "2025-01-01T00:00:00Z"

    @pytest.mark.asyncio
    async def test_fetch_sales_report_full_flow(self):
        from neurova.collaboration.neurflow.external_api import AmazonSPAPIClient

        get_responses = [
            {"payload": {"reportId": "REP1", "processingStatus": "IN_PROGRESS"}},
            {"payload": {"reportId": "REP1", "processingStatus": "DONE", "reportDocumentId": "DOC1"}},
            {"payload": {"reportDocumentId": "DOC1", "url": "https://doc.example.com/r.gz"}},
        ]
        mock_get = AsyncMock(side_effect=get_responses)

        async def _post(url, headers=None, json=None, data=None, params=None, timeout=30.0):
            if "auth/o2/token" in url:
                return {"access_token": "Atza|tok", "expires_in": 3600}
            return {"reportId": "REP1"}

        with patch(f"{MOD}._http_post", AsyncMock(side_effect=_post)), \
             patch(f"{MOD}._http_get", mock_get), \
             patch(f"{MOD}._sleep", AsyncMock()):
            result = await AmazonSPAPIClient().fetch_sales_report(
                report_type="GET_FLAT_FILE_ALL_ORDERS_DATA_BY_ORDER_DATE_GENERAL",
                marketplace_ids=["ATVPDKIKX0DER"],
                data_start_time="2025-01-01T00:00:00Z",
                data_end_time="2025-02-01T00:00:00Z",
                refresh_token="rt", client_id="cid", client_secret="cs",
                max_polls=5,
            )
        assert result["status"] == "success"
        assert result["output"]["report_id"] == "REP1"
        assert result["output"]["report_document_id"] == "DOC1"
        assert result["output"]["document_url"] == "https://doc.example.com/r.gz"
        assert result["output"]["processing_status"] == "DONE"

    @pytest.mark.asyncio
    async def test_fetch_sales_report_fatal_status(self):
        from neurova.collaboration.neurflow.external_api import AmazonSPAPIClient

        async def _post(url, headers=None, json=None, data=None, params=None, timeout=30.0):
            if "auth/o2/token" in url:
                return {"access_token": "Atza|tok", "expires_in": 3600}
            return {"reportId": "REP1"}

        mock_get = AsyncMock(return_value={"payload": {"reportId": "REP1", "processingStatus": "CANCELLED"}})
        with patch(f"{MOD}._http_post", AsyncMock(side_effect=_post)), \
             patch(f"{MOD}._http_get", mock_get), \
             patch(f"{MOD}._sleep", AsyncMock()):
            result = await AmazonSPAPIClient().fetch_sales_report(
                report_type="GET_FLAT_FILE_ALL_ORDERS_DATA_BY_ORDER_DATE_GENERAL",
                marketplace_ids=["ATVPDKIKX0DER"],
                refresh_token="rt", client_id="cid", client_secret="cs",
                max_polls=3,
            )
        assert result["status"] == "failed"


class TestAmazonAdsClient:
    """Amazon Ads API — 独立于 SP-API 的广告开放平台

    - 端点：advertising-api.amazon.com（NA）/ -eu / -fe
    - 认证：LWA client_credentials，scope=advertising::campaign_management
    - 请求头：Authorization Bearer + Amazon-Advertising-API-ClientId + Amazon-Advertising-API-Scope(profileId)
    """

    def test_ads_regions(self):
        from neurova.collaboration.neurflow.external_api import AMAZON_ADS_REGIONS

        assert AMAZON_ADS_REGIONS == {
            "na": "https://advertising-api.amazon.com",
            "eu": "https://advertising-api-eu.amazon.com",
            "fe": "https://advertising-api-fe.amazon.com",
        }

    def test_is_available_requires_client_credentials(self):
        from neurova.collaboration.neurflow.external_api import AmazonAdsClient

        assert AmazonAdsClient().is_available(client_id="cid", client_secret="cs") is True
        store = MagicMock()
        store.get.return_value = None
        with patch(f"{MOD}.get_secret_store", return_value=store):
            assert AmazonAdsClient().is_available() is False

    @pytest.mark.asyncio
    async def test_get_access_token_uses_client_credentials_scope(self):
        from neurova.collaboration.neurflow.external_api import AmazonAdsClient

        mock_post = AsyncMock(return_value={"access_token": "Atza|ads", "expires_in": 3600})
        with patch(f"{MOD}._http_post", mock_post):
            token = await AmazonAdsClient().get_access_token(client_id="cid", client_secret="cs")
        assert token == "Atza|ads"
        data = mock_post.call_args.kwargs.get("data") or {}
        assert data.get("grant_type") == "client_credentials"
        assert data.get("scope") == "advertising::campaign_management"

    @pytest.mark.asyncio
    async def test_fetch_campaign_metrics_reporting_flow(self):
        from neurova.collaboration.neurflow.external_api import AmazonAdsClient

        ndjson = (
            '{"campaignId":"123","campaignName":"Camp1","impressions":100,"clicks":5,"spend":10.5}\n'
            '{"campaignId":"123","campaignName":"Camp1","impressions":50,"clicks":2,"spend":4.5}\n'
        )

        async def _post(url, headers=None, json=None, data=None, params=None, timeout=30.0):
            if "auth/o2/token" in url:
                return {"access_token": "Atza|ads", "expires_in": 3600}
            return {"reportId": "ADSREP1", "status": "PROCESSING"}

        async def _get(url, headers=None, params=None, timeout=30.0):
            return {"reportId": "ADSREP1", "status": "COMPLETED", "url": "https://report.example.com/r.json.gz"}

        async def _get_text(url, headers=None, timeout=60.0):
            return ndjson

        with patch(f"{MOD}._http_post", AsyncMock(side_effect=_post)), \
             patch(f"{MOD}._http_get", AsyncMock(side_effect=_get)), \
             patch(f"{MOD}._http_get_text", AsyncMock(side_effect=_get_text)), \
             patch(f"{MOD}._sleep", AsyncMock()):
            result = await AmazonAdsClient().fetch_campaign_metrics(
                campaign_ids=["123"],
                metrics=["impressions", "clicks", "spend"],
                start_date="2025-01-01",
                end_date="2025-01-31",
                profile_id="999",
                client_id="cid",
                client_secret="cs",
            )
        assert result["status"] == "success"
        items = result["output"]["items"]
        assert items[0]["campaign_id"] == "123"
        assert items[0]["impressions"] == 150
        assert items[0]["clicks"] == 7
        assert items[0]["spend"] == 15.0

    @pytest.mark.asyncio
    async def test_fetch_campaign_metrics_unconfigured(self):
        from neurova.collaboration.neurflow.external_api import AmazonAdsClient

        store = MagicMock()
        store.get.return_value = None
        with patch(f"{MOD}.get_secret_store", return_value=store):
            result = await AmazonAdsClient().fetch_campaign_metrics(
                campaign_ids=["123"], metrics=["impressions"],
                start_date="2025-01-01", end_date="2025-01-31", profile_id="999",
            )
        assert result["status"] == "failed"


class TestCommerceClientAmazonRouting:
    """CommercePlatformClient 亚马逊分支路由到 AmazonSPAPIClient"""

    def test_is_available_amazon_requires_sp_credentials(self):
        from neurova.collaboration.neurflow.external_api import CommercePlatformClient

        store = _creds_store()
        with patch(f"{MOD}.get_secret_store", return_value=store):
            assert CommercePlatformClient().is_available("amazon") is True
        empty = MagicMock()
        empty.get.return_value = None
        with patch(f"{MOD}.get_secret_store", return_value=empty):
            assert CommercePlatformClient().is_available("amazon") is False

    @pytest.mark.asyncio
    async def test_fetch_prices_amazon_delegates_to_sp_client(self):
        from neurova.collaboration.neurflow.external_api import CommercePlatformClient

        sp_result = {"status": "success", "output": {"prices": {"B0TEST": {"price": 99.0, "currency": "USD"}}}, "error": None, "provider": "amazon"}
        with patch(f"{MOD}.AmazonSPAPIClient.fetch_prices", AsyncMock(return_value=sp_result)) as mock_fp:
            result = await CommercePlatformClient().fetch_prices(
                "amazon", ["B0TEST"], marketplace_id="ATVPDKIKX0DER", region="eu"
            )
        assert result["status"] == "success"
        assert result["output"]["prices"]["B0TEST"]["price"] == 99.0
        mock_fp.assert_called_once()
        _, kwargs = mock_fp.call_args
        assert kwargs.get("marketplace_id") == "ATVPDKIKX0DER"
        assert kwargs.get("region") == "eu"

    @pytest.mark.asyncio
    async def test_fetch_inventory_amazon_delegates_to_sp_client(self):
        from neurova.collaboration.neurflow.external_api import CommercePlatformClient

        sp_result = {"status": "success", "output": {"inventory": {"SKU1": {"totalQuantity": 12, "fulfillableQuantity": 10}}}, "error": None, "provider": "amazon"}
        with patch(f"{MOD}.AmazonSPAPIClient.fetch_inventory", AsyncMock(return_value=sp_result)) as mock_fi:
            result = await CommercePlatformClient().fetch_inventory(
                "amazon", ["SKU1"], marketplace_id="ATVPDKIKX0DER", seller_id="A1SELLER"
            )
        assert result["status"] == "success"
        assert result["output"]["inventory"]["SKU1"]["totalQuantity"] == 12
        _, kwargs = mock_fi.call_args
        assert kwargs.get("seller_id") == "A1SELLER"

    @pytest.mark.asyncio
    async def test_fetch_reviews_amazon_maps_topics_to_items(self):
        from neurova.collaboration.neurflow.external_api import CommercePlatformClient

        sp_result = {
            "status": "success",
            "output": {
                "asin": "B0TEST",
                "positive_topics": [{"topic": "Quality", "reviewSnippets": ["Great quality"]}],
                "negative_topics": [{"topic": "Assembly", "reviewSnippets": ["Hard to assemble"]}],
            },
            "error": None,
            "provider": "amazon",
        }
        with patch(f"{MOD}.AmazonSPAPIClient.fetch_review_topics", AsyncMock(return_value=sp_result)):
            result = await CommercePlatformClient().fetch_reviews(
                "amazon", "B0TEST", marketplace_id="ATVPDKIKX0DER"
            )
        assert result["status"] == "success"
        items = result["output"]["items"]
        assert any(i.get("sentiment") == "negative" and i.get("topic") == "Assembly" for i in items)
        assert any(i.get("sentiment") == "positive" and i.get("topic") == "Quality" for i in items)

    @pytest.mark.asyncio
    async def test_fetch_sales_report_amazon_delegates_report_flow(self):
        from neurova.collaboration.neurflow.external_api import CommercePlatformClient

        sp_result = {
            "status": "success",
            "output": {"report_id": "REP1", "report_document_id": "DOC1", "document_url": "https://doc.example.com/r.gz", "processing_status": "DONE"},
            "error": None,
            "provider": "amazon",
        }
        with patch(f"{MOD}.AmazonSPAPIClient.fetch_sales_report", AsyncMock(return_value=sp_result)) as mock_fs:
            result = await CommercePlatformClient().fetch_sales_report(
                "amazon",
                period="2025-01",
                report_type="GET_FLAT_FILE_ALL_ORDERS_DATA_BY_ORDER_DATE_GENERAL",
                marketplace_id="ATVPDKIKX0DER",
            )
        assert result["status"] == "success"
        assert result["output"]["report_id"] == "REP1"
        _, kwargs = mock_fs.call_args
        assert kwargs.get("report_type") == "GET_FLAT_FILE_ALL_ORDERS_DATA_BY_ORDER_DATE_GENERAL"
        assert kwargs.get("marketplace_ids") == ["ATVPDKIKX0DER"]
        assert kwargs.get("data_start_time", "").startswith("2025-01-01")

    @pytest.mark.asyncio
    async def test_fetch_competitors_amazon_uses_competitive_pricing(self):
        from neurova.collaboration.neurflow.external_api import CommercePlatformClient

        sp_result = {"status": "success", "output": {"prices": {"B0A": {"price": 10.0, "currency": "USD"}}}, "error": None, "provider": "amazon"}
        with patch(f"{MOD}.AmazonSPAPIClient.fetch_competitive_prices", AsyncMock(return_value=sp_result)) as mock_fc:
            result = await CommercePlatformClient().fetch_competitors(
                "amazon", "B0A, B0B", marketplace_id="ATVPDKIKX0DER"
            )
        assert result["status"] == "success"
        args, kwargs = mock_fc.call_args
        asins = args[0] if args else kwargs.get("asins")
        assert asins == ["B0A", "B0B"]
