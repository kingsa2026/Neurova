"""
Neurflow 画布电商节点 — 淘宝/京东/拼多多/抖店/TikTok Shop 开放平台适配测试

依据各平台开放平台开发文档完善画布节点：
1. 商品 ID 语义按平台区分：淘宝 num_iid / 京东 skuId / 拼多多 goods_id /
   抖店 product_id / TikTok Shop product_id（亚马逊 ASIN）
2. 评论回复：仅淘宝 TOP 提供 traderates.get 评论拉取；京东/拼多多/抖店/TikTok Shop
   开放平台无评论 API，节点描述需说明手工粘贴降级
3. 销售报表：五平台均经各自订单 API 拉取真实订单并聚合
   （taobao.trades.sold.get / jingdong.pop.order.search / pdd.order.list.get /
   order.searchList / POST /order/202309/orders/search）
4. 竞品分析：五平台开放 API 均不提供竞品数据，描述需说明 LLM 兜底
"""
import os
import sys
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from neurova.collaboration.neurflow.commerce_nodes import (  # noqa: E402
    COMMERCE_NODES,
    exec_price_monitor,
    exec_review_respond,
    exec_sales_report,
)


def _node(node_type: str) -> dict:
    return next(n for n in COMMERCE_NODES if n["type"] == node_type)


def _block(node: dict, block_id: str) -> dict:
    return next(b for b in node["sub_blocks"] if (b.get("id") or b.get("name")) == block_id)


def _blocks(node: dict, block_id: str) -> list:
    """同键变体：联动下拉后商品 ID 字段按平台提供多个同 id 变体"""
    return [b for b in node["sub_blocks"] if (b.get("id") or b.get("name")) == block_id]


def _variant_labels(node: dict, block_id: str) -> str:
    """拼接同键变体的全部标题，用于断言平台 ID 命名在画布上可见"""
    return " | ".join(str(b.get("label", "")) for b in _blocks(node, block_id))


class TestCnNodeFields:
    def test_price_monitor_products_placeholder_covers_cn_platform_ids(self):
        node = _node("builtin:price-monitor")
        # 联动下拉：商品列表按平台拆分为同键变体，各平台 ID 命名体现在变体标题中
        labels = _variant_labels(node, "products")
        for token in ("num_iid", "skuId", "goods_id", "product_id"):
            assert token in labels, f"价格监控商品变体标题应说明 {token}: {labels}"
        desc = node["description"]
        assert "taobao.item.get" in desc, "描述应说明淘宝经 taobao.item.get 拉取价格"
        assert "pdd.goods.information.get" in desc, "描述应说明拼多多经 pdd.goods.information.get"

    def test_review_respond_supports_taobao_num_iid(self):
        node = _node("builtin:review-respond")
        # 淘宝变体（condition platform=taobao）标题须体现 num_iid
        taobao_variants = [
            b for b in _blocks(node, "asin")
            if (b.get("condition") or {}).get("value") == "taobao"
        ]
        assert taobao_variants, "评论回复应提供淘宝联动的商品 ID 变体"
        assert any("num_iid" in str(b.get("label", "")) for b in taobao_variants), \
            "评论回复淘宝变体标题应体现 num_iid"
        desc = node["description"]
        assert "traderates" in desc, "描述应说明淘宝经 traderates.get 拉取真实评论"
        assert "手工粘贴" in desc or "手动粘贴" in desc, "描述应说明无评论 API 平台的手工降级"

    def test_inventory_sync_skus_placeholder_covers_cn_platform_ids(self):
        node = _node("builtin:inventory-sync")
        labels = _variant_labels(node, "skus")
        for token in ("num_iid", "skuId", "goods_id"):
            assert token in labels, f"库存同步 SKU 变体标题应说明 {token}: {labels}"

    def test_sales_report_description_covers_cn_order_apis(self):
        desc = _node("builtin:sales-report")["description"]
        for token in ("trades.sold.get", "pop.order.search", "order.list.get", "order.searchList", "orders/search"):
            assert token in desc, f"销售报表描述应说明订单 API {token}"

    def test_competitor_analysis_description_notes_cn_limitation(self):
        desc = _node("builtin:competitor-analysis")["description"]
        assert "不提供" in desc and "竞品" in desc, "竞品分析描述应说明国内平台开放 API 不提供竞品数据"


class TestCnExecutors:
    @pytest.mark.asyncio
    async def test_review_respond_taobao_passes_num_iid(self):
        api_result = {
            "status": "success",
            "output": {"items": [{"id": 1, "content": "发货太慢了", "sentiment": "negative"}]},
            "error": None,
            "provider": "taobao",
        }
        with patch(
            "neurova.collaboration.neurflow.commerce_nodes.CommercePlatformClient.fetch_reviews",
            AsyncMock(return_value=api_result),
        ) as mock_fr:
            result = await exec_review_respond(
                {"platform": "taobao", "asin": "667788", "tone": "友好专业"}, {}
            )
        assert result["status"] == "success"
        _, kwargs = mock_fr.call_args
        assert kwargs.get("platform") == "taobao"
        assert kwargs.get("product_id") == "667788"
        assert result["output"]["source"] == "platform_api"
        assert result["output"]["replies"][0]["sentiment"] == "negative"

    @pytest.mark.asyncio
    async def test_price_monitor_taobao_uses_platform_api(self):
        api_result = {
            "status": "success",
            "output": {"prices": {"667788": {"price": 29.9, "currency": "CNY"}}},
            "error": None,
            "provider": "taobao",
        }
        with patch(
            "neurova.collaboration.neurflow.commerce_nodes.CommercePlatformClient.fetch_prices",
            AsyncMock(return_value=api_result),
        ) as mock_fp:
            result = await exec_price_monitor(
                {"platform": "taobao", "products": "667788", "alert_threshold": 50}, {}
            )
        assert result["status"] == "success"
        _, kwargs = mock_fp.call_args
        assert kwargs.get("platform") == "taobao"
        assert kwargs.get("product_ids") == ["667788"]
        assert result["output"]["prices"][0]["price"] == 29.9
        assert result["output"]["source"] == "platform_api"

    @pytest.mark.asyncio
    async def test_sales_report_taobao_aggregated_orders(self):
        api_result = {
            "status": "success",
            "output": {
                "sales": 15000.0, "orders": 120, "units": 150,
                "avg_order_value": 125.0, "order_items": [], "currency": "CNY",
            },
            "error": None,
            "provider": "taobao",
        }
        with patch(
            "neurova.collaboration.neurflow.commerce_nodes.CommercePlatformClient.fetch_sales_report",
            AsyncMock(return_value=api_result),
        ) as mock_fs:
            result = await exec_sales_report(
                {"platform": "taobao", "period": "2025-01", "metrics": "sales,orders"}, {}
            )
        assert result["status"] == "success"
        _, kwargs = mock_fs.call_args
        assert kwargs.get("platform") == "taobao"
        assert kwargs.get("period") == "2025-01"
        report = result["output"]["report"]
        assert report["sales"] == 15000.0
        assert report["orders"] == 120
        assert result["output"]["source"] == "platform_api"
