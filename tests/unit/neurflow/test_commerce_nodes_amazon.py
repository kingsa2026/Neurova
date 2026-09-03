"""
Neurflow 画布电商节点 — 亚马逊 SP-API 实际流程字段测试

依据亚马逊开放平台（SP-API）官方文档调整画布节点：
1. 价格监控：marketplace_id（站点）+ region（NA/EU/FE 端点），商品为 ASIN
2. 库存同步：FBA Inventory API 需要 marketplaceId + sellerSkus（≤50）
3. 销售报表：Reports API 需要 reportType + marketplaceIds + 时间范围
4. 评论回复：Customer Feedback API 按 ASIN 拉取评论主题洞察（SP-API 不支持直接回复）
5. 商品上架：Listings Items API putListingsItem 需要 sellerId/sku/productType/requirements
6. 竞品分析：getCompetitivePricing 需要 marketplaceId
7. 广告节点：Amazon Ads 为独立开放平台，需要 profileId
"""
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from neurova.collaboration.neurflow.commerce_nodes import (  # noqa: E402
    COMMERCE_NODES,
    exec_price_monitor,
    exec_review_respond,
    exec_product_listing,
    exec_inventory_sync,
    exec_competitor_analysis,
    exec_sales_report,
)


def _node(node_type: str) -> dict:
    return next(n for n in COMMERCE_NODES if n["type"] == node_type)


def _block_ids(node: dict) -> list:
    return [b.get("id") or b.get("name") for b in node["sub_blocks"]]


def _block(node: dict, block_id: str) -> dict:
    return next(b for b in node["sub_blocks"] if (b.get("id") or b.get("name")) == block_id)


class TestAmazonNodeFields:
    """画布节点应提供亚马逊 SP-API 实际流程所需的字段"""

    def test_price_monitor_has_marketplace_and_region(self):
        node = _node("builtin:price-monitor")
        ids = _block_ids(node)
        assert "marketplace_id" in ids, f"价格监控缺少 marketplace_id: {ids}"
        assert "region" in ids, f"价格监控缺少 region: {ids}"

        marketplace_opts = [o.get("value") for o in _block(node, "marketplace_id").get("options", [])]
        assert "ATVPDKIKX0DER" in marketplace_opts, "marketplace 选项应包含美国站 ATVPDKIKX0DER"
        assert "A1VC38T7YXB528" in marketplace_opts, "marketplace 选项应包含日本站 A1VC38T7YXB528"

        region_opts = [o.get("value") for o in _block(node, "region").get("options", [])]
        assert set(region_opts) == {"na", "eu", "fe"}, f"region 应为 SP-API 三大区域端点: {region_opts}"

    def test_inventory_sync_has_sp_api_fields(self):
        node = _node("builtin:inventory-sync")
        ids = _block_ids(node)
        assert "skus" in ids, f"库存同步缺少 skus（FBA getInventorySummaries 按 sellerSkus 查询）: {ids}"
        assert "marketplace_id" in ids, f"库存同步缺少 marketplace_id: {ids}"
        assert "region" in ids, f"库存同步缺少 region: {ids}"
        assert "seller_id" in ids, f"库存同步缺少 seller_id: {ids}"

    def test_sales_report_has_report_type_field(self):
        node = _node("builtin:sales-report")
        ids = _block_ids(node)
        assert "report_type" in ids, f"销售报表缺少 report_type（Reports API createReport 必填）: {ids}"
        assert "marketplace_id" in ids, f"销售报表缺少 marketplace_id: {ids}"

        report_opts = [o.get("value") for o in _block(node, "report_type").get("options", [])]
        assert "GET_FLAT_FILE_ALL_ORDERS_DATA_BY_ORDER_DATE_GENERAL" in report_opts
        assert "GET_AMAZON_FULFILLED_SHIPMENTS_DATA_GENERAL" in report_opts

    def test_review_respond_has_asin_field(self):
        node = _node("builtin:review-respond")
        ids = _block_ids(node)
        assert "asin" in ids, f"评论回复缺少 asin（Customer Feedback API 按 ASIN 查询）: {ids}"
        assert "marketplace_id" in ids, f"评论回复缺少 marketplace_id: {ids}"
        assert "SP-API" in node["description"] or "Customer Feedback" in node["description"], \
            "评论回复描述应说明亚马逊经 Customer Feedback API 获取评论洞察"

    def test_product_listing_has_listings_api_fields(self):
        node = _node("builtin:product-listing")
        ids = _block_ids(node)
        for field in ("sku", "seller_id", "product_type", "requirements", "marketplace_id"):
            assert field in ids, f"商品上架缺少 {field}（putListingsItem 必填）: {ids}"

        req_opts = [o.get("value") for o in _block(node, "requirements").get("options", [])]
        assert "LISTING" in req_opts
        assert "LISTING_OFFER_ONLY" in req_opts

    def test_competitor_analysis_has_marketplace(self):
        node = _node("builtin:competitor-analysis")
        ids = _block_ids(node)
        assert "marketplace_id" in ids, f"竞品分析缺少 marketplace_id（getCompetitivePricing 必填）: {ids}"

    def test_ad_nodes_have_amazon_ads_profile_field(self):
        for node_type in ("builtin:ad-streaming", "builtin:ad-monitor"):
            node = _node(node_type)
            ids = _block_ids(node)
            assert "profile_id" in ids, f"{node_type} 缺少 profile_id（Amazon Ads API 需要 profileId）: {ids}"


class TestAmazonExecutors:
    """执行器应按 SP-API 实际流程传递字段并解析响应"""

    @pytest.mark.asyncio
    async def test_price_monitor_passes_marketplace_and_region(self):
        api_result = {
            "status": "success",
            "output": {"prices": {"B0TEST": {"price": 39.9, "currency": "USD"}}},
            "error": None,
            "provider": "amazon",
        }
        with patch(
            "neurova.collaboration.neurflow.commerce_nodes.CommercePlatformClient.fetch_prices",
            AsyncMock(return_value=api_result),
        ) as mock_fp:
            config = {
                "platform": "amazon",
                "products": "B0TEST",
                "alert_threshold": 50,
                "marketplace_id": "A1PA6795UKMFR9",
                "region": "eu",
            }
            result = await exec_price_monitor(config, {})
        assert result["status"] == "success"
        _, kwargs = mock_fp.call_args
        assert kwargs.get("marketplace_id") == "A1PA6795UKMFR9"
        assert kwargs.get("region") == "eu"
        prices = result["output"]["prices"]
        assert prices[0]["price"] == 39.9
        assert result["output"]["marketplace_id"] == "A1PA6795UKMFR9"
        assert len(result["output"]["alerts"]) == 1

    @pytest.mark.asyncio
    async def test_price_monitor_sp_api_dict_price_shape(self):
        """SP-API 返回 {asin: {price, currency}} 结构时应正确解析"""
        api_result = {
            "status": "success",
            "output": {"prices": {"B0TEST": {"price": 120.0, "currency": "USD"}}},
            "error": None,
            "provider": "amazon",
        }
        with patch(
            "neurova.collaboration.neurflow.commerce_nodes.CommercePlatformClient.fetch_prices",
            AsyncMock(return_value=api_result),
        ):
            config = {"platform": "amazon", "products": "B0TEST", "alert_threshold": 50, "marketplace_id": "ATVPDKIKX0DER"}
            result = await exec_price_monitor(config, {})
        assert result["output"]["prices"][0]["price"] == 120.0
        assert result["output"]["prices"][0]["currency"] == "USD"
        assert result["output"]["alerts"] == []

    @pytest.mark.asyncio
    async def test_inventory_sync_parses_sp_api_inventory_shape(self):
        api_result = {
            "status": "success",
            "output": {"inventory": {"SKU1": {"totalQuantity": 3, "fulfillableQuantity": 2}}},
            "error": None,
            "provider": "amazon",
        }
        with patch(
            "neurova.collaboration.neurflow.commerce_nodes.CommercePlatformClient.fetch_inventory",
            AsyncMock(return_value=api_result),
        ) as mock_fi:
            config = {
                "platform": "amazon",
                "skus": "SKU1",
                "low_stock_threshold": 10,
                "marketplace_id": "ATVPDKIKX0DER",
                "seller_id": "A1SELLER",
            }
            result = await exec_inventory_sync(config, {})
        assert result["status"] == "success"
        _, kwargs = mock_fi.call_args
        assert kwargs.get("marketplace_id") == "ATVPDKIKX0DER"
        assert kwargs.get("seller_id") == "A1SELLER"
        synced = result["output"]["synced"]
        assert synced[0]["stock"] == 3
        assert synced[0]["status"] == "low"
        assert len(result["output"]["alerts"]) == 1

    @pytest.mark.asyncio
    async def test_sales_report_amazon_uses_reports_api_flow(self):
        api_result = {
            "status": "success",
            "output": {
                "report_id": "REP1",
                "report_document_id": "DOC1",
                "document_url": "https://doc.example.com/r.gz",
                "processing_status": "DONE",
            },
            "error": None,
            "provider": "amazon",
        }
        with patch(
            "neurova.collaboration.neurflow.commerce_nodes.CommercePlatformClient.fetch_sales_report",
            AsyncMock(return_value=api_result),
        ) as mock_fs:
            config = {
                "platform": "amazon",
                "period": "2025-01",
                "metrics": "sales,orders",
                "report_type": "GET_FLAT_FILE_ALL_ORDERS_DATA_BY_ORDER_DATE_GENERAL",
                "marketplace_id": "ATVPDKIKX0DER",
            }
            result = await exec_sales_report(config, {})
        assert result["status"] == "success"
        _, kwargs = mock_fs.call_args
        assert kwargs.get("report_type") == "GET_FLAT_FILE_ALL_ORDERS_DATA_BY_ORDER_DATE_GENERAL"
        assert kwargs.get("marketplace_id") == "ATVPDKIKX0DER"
        report = result["output"]["report"]
        assert report.get("report_id") == "REP1"
        assert report.get("document_url") == "https://doc.example.com/r.gz"

    @pytest.mark.asyncio
    async def test_review_respond_amazon_uses_feedback_insights(self):
        api_result = {
            "status": "success",
            "output": {
                "items": [
                    {"topic": "Assembly", "content": "Hard to assemble", "sentiment": "negative", "rating": None, "id": "topic-1"},
                    {"topic": "Quality", "content": "Great quality", "sentiment": "positive", "rating": None, "id": "topic-2"},
                ],
            },
            "error": None,
            "provider": "amazon",
        }
        with patch(
            "neurova.collaboration.neurflow.commerce_nodes.CommercePlatformClient.fetch_reviews",
            AsyncMock(return_value=api_result),
        ) as mock_fr:
            config = {
                "platform": "amazon",
                "asin": "B0TEST",
                "marketplace_id": "ATVPDKIKX0DER",
                "tone": "friendly",
            }
            result = await exec_review_respond(config, {})
        assert result["status"] == "success"
        _, kwargs = mock_fr.call_args
        assert kwargs.get("marketplace_id") == "ATVPDKIKX0DER"
        output = result["output"]
        assert any(r.get("sentiment") == "negative" for r in output["replies"])
        assert output.get("source") == "platform_api"

    @pytest.mark.asyncio
    async def test_product_listing_builds_put_listings_payload(self):
        config = {
            "platform": "amazon",
            "product_name": "无线蓝牙耳机",
            "features": "降噪, 长续航",
            "keywords": "wireless earbuds",
            "sku": "SKU-EARBUDS",
            "seller_id": "A1SELLER",
            "product_type": "HEADPHONES",
            "requirements": "LISTING",
            "marketplace_id": "ATVPDKIKX0DER",
        }
        result = await exec_product_listing(config, {})
        assert result["status"] == "success"
        submission = result["output"].get("sp_api_submission")
        assert submission is not None, "亚马逊平台应输出 putListingsItem 提交载荷"
        assert submission["seller_id"] == "A1SELLER"
        assert submission["sku"] == "SKU-EARBUDS"
        assert submission["product_type"] == "HEADPHONES"
        assert submission["requirements"] == "LISTING"
        assert submission["marketplace_ids"] == ["ATVPDKIKX0DER"]
        attrs = submission["attributes"]
        assert attrs["item_name"] == "无线蓝牙耳机"
        assert "降噪" in attrs["bullet_points"]
        assert attrs["search_keywords"] == ["wireless earbuds"]

    @pytest.mark.asyncio
    async def test_product_listing_non_amazon_has_no_submission(self):
        config = {"platform": "taobao", "product_name": "智能手表", "features": "防水"}
        result = await exec_product_listing(config, {})
        assert result["status"] == "success"
        assert result["output"].get("sp_api_submission") is None

    @pytest.mark.asyncio
    async def test_competitor_analysis_passes_marketplace(self):
        api_result = {
            "status": "success",
            "output": {"prices": {"B0A": {"price": 10.0, "currency": "USD"}}},
            "error": None,
            "provider": "amazon",
        }
        with patch(
            "neurova.collaboration.neurflow.commerce_nodes.CommercePlatformClient.fetch_competitors",
            AsyncMock(return_value=api_result),
        ) as mock_fc:
            config = {"platform": "amazon", "competitors": "B0A", "marketplace_id": "ATVPDKIKX0DER"}
            result = await exec_competitor_analysis(config, {})
        assert result["status"] == "success"
        _, kwargs = mock_fc.call_args
        assert kwargs.get("marketplace_id") == "ATVPDKIKX0DER"
