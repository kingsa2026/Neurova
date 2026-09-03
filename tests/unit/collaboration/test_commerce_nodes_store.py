"""
电商节点 store-select 契约测试 — TDD 红灯先行。

范围（P5 节点集成，§5.4）：
1. 5 个真实调用平台 API 的节点含 store-select 子块（9 平台 condition）；
   product-listing 无店铺字段；
2. 三平台专属商品 ID 标签（1688 offer ID / 小红书 item_id / 闲鱼）；
3. 执行器透传 store_id/store_creds；失败降级输出携带显性 note；
4. 未选店铺走环境变量通道（不带 store_creds）。

占位凭据均为无敏感含义片段。
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from neurova.collaboration.neurflow import commerce_nodes
from neurova.collaboration.neurflow.commerce_nodes import COMMERCE_NODES, exec_price_monitor
from neurova.collaboration.neurflow.store_connections import StoreCredentials

STORE_SELECT_NODES = (
    "builtin:price-monitor",
    "builtin:review-respond",
    "builtin:inventory-sync",
    "builtin:competitor-analysis",
    "builtin:sales-report",
)

PLATFORM_9 = ["amazon", "taobao", "jd", "pdd", "douyin-ecom", "tiktok", "ali1688", "xiaohongshu", "xianyu"]


def _node(node_type: str) -> dict:
    return next(n for n in COMMERCE_NODES if n["type"] == node_type)


def _sub_block(node_type: str, block_id: str):
    return next(b for b in _node(node_type)["sub_blocks"] if b["id"] == block_id)


class TestStoreSelectSubBlock:
    @pytest.mark.parametrize("node_type", STORE_SELECT_NODES)
    def test_node_has_store_select_block(self, node_type):
        sb = _sub_block(node_type, "store_id")
        assert sb["type"] == "store-select"
        assert sb["default"] == ""
        assert sb["condition"] == {"field": "platform", "operator": "in", "value": PLATFORM_9}

    def test_product_listing_has_no_store_select(self):
        node = _node("builtin:product-listing")
        assert all(b.get("type") != "store-select" for b in node["sub_blocks"])

    def test_condition_serializes_through_sub_block_dict(self):
        # register 后 /neurflow/nodes 序列化（_sub_block_to_dict）须透传 type/condition
        from neurova.api.endpoints.neurflow_api import _sub_block_to_dict

        sb = _sub_block("builtin:price-monitor", "store_id")
        out = _sub_block_to_dict(sb)
        assert out["type"] == "store-select"
        assert out["condition"]["operator"] == "in"
        assert "ali1688" in out["condition"]["value"]
        assert "xianyu" in out["condition"]["value"]


class TestPlatformScopedLabels:
    @pytest.mark.parametrize(
        "node_type,block_id",
        [
            ("builtin:price-monitor", "products"),
            ("builtin:inventory-sync", "skus"),
            ("builtin:competitor-analysis", "competitors"),
        ],
    )
    def test_new_platform_labels_present(self, node_type, block_id):
        variants = [b for b in _node(node_type)["sub_blocks"] if b["id"] == block_id]

        def label_for(platform: str) -> str:
            for b in variants:
                if b.get("condition") and b["condition"].get("value") == platform:
                    return str(b["label"])
            return ""

        assert "offer" in label_for("ali1688")
        assert "item_id" in label_for("xiaohongshu")
        assert "闲鱼" in label_for("xianyu")


class TestStoreAuthNode:
    """店铺授权节点（店铺管理页作为节点，店铺为其下属对象）"""

    def test_store_auth_node_exists_with_store_select(self):
        node = _node("builtin:store-auth")
        assert node["category"] == "commerce"
        sb = next(b for b in node["sub_blocks"] if b["id"] == "store_id")
        assert sb["type"] == "store-select"
        # 无平台上下文：store-select 不带 platform 条件（始终可见）
        assert sb.get("condition") is None

    @pytest.mark.asyncio
    async def test_exec_reports_store_status(self):
        from neurova.collaboration.neurflow import commerce_nodes as cn
        from neurova.collaboration.neurflow.commerce_nodes import exec_store_auth
        from neurova.collaboration.neurflow.models import StoreConnection

        store = StoreConnection(store_id="store_000001", platform="taobao", store_name="淘宝A", user_id="user_a", status="active")
        sm = MagicMock()
        sm.get_store = MagicMock(return_value=store)
        sm.test_connection = AsyncMock(return_value={"status": "active", "detail": "令牌刷新成功"})
        with patch.object(cn, "get_store_connection_manager", return_value=sm):
            result = await exec_store_auth(
                {"store_id": "store_000001"},
                {"resolution_context": type("RC", (), {"user_id": "user_a"})()},
            )
        assert result["status"] == "success"
        out = result["output"]
        assert out["store_id"] == "store_000001"
        assert out["store_name"] == "淘宝A"
        assert out["status"] == "active"
        assert out["test"]["status"] == "active"
        sm.test_connection.assert_awaited_once_with("store_000001", user_id="user_a")

    @pytest.mark.asyncio
    async def test_exec_without_store_returns_pending_guidance(self):
        from neurova.collaboration.neurflow.commerce_nodes import exec_store_auth

        result = await exec_store_auth({}, {"timestamp": "2026-08-29"})
        assert result["status"] == "success"
        assert result["output"]["status"] == "pending"
        assert "店铺管理页" in result["output"]["note"]


class TestExecutorStoreForwarding:
    @pytest.mark.asyncio
    async def test_price_monitor_forwards_store_creds(self):
        creds = StoreCredentials(app_key="aaaa" + "1111", app_secret="bbbb" + "2222", access_token="cccc" + "3333")
        fake_client = AsyncMock(return_value={"status": "success", "output": {"prices": {"B0XXX": {"price": "9.9", "currency": "CNY"}}}})
        with patch("neurova.collaboration.neurflow.commerce_nodes.CommercePlatformClient") as cpc_cls, patch(
            "neurova.collaboration.neurflow.commerce_nodes.get_store_connection_manager"
        ) as sm:
            cpc_cls.return_value.fetch_prices = fake_client
            sm.return_value.resolve_credentials = AsyncMock(return_value=creds)
            result = await exec_price_monitor(
                {"platform": "taobao", "products": "B0XXX", "alert_threshold": "50", "store_id": "store_000001"},
                {"timestamp": "2026-08-29"},
            )
        assert result["status"] == "success"
        assert result["output"]["source"] == "platform_api"
        fake_client.assert_awaited_once_with(
            platform="taobao",
            product_ids=["B0XXX"],
            marketplace_id="",
            region="na",
            store_id="store_000001",
            store_creds=creds,
        )

    @pytest.mark.asyncio
    async def test_price_monitor_without_store_skips_creds(self):
        fake_client = AsyncMock(return_value={"status": "success", "output": {"prices": {"B0XXX": {"price": "9.9"}}}})
        with patch("neurova.collaboration.neurflow.commerce_nodes.CommercePlatformClient") as cpc_cls:
            cpc_cls.return_value.fetch_prices = fake_client
            result = await exec_price_monitor(
                {"platform": "taobao", "products": "B0XXX", "alert_threshold": "50"},
                {"timestamp": "2026-08-29"},
            )
        assert result["status"] == "success"
        kwargs = fake_client.await_args.kwargs
        assert kwargs["store_creds"] is None
        assert kwargs["store_id"] == ""

    @pytest.mark.asyncio
    async def test_price_monitor_fallback_carries_explicit_note(self):
        fake_client = AsyncMock(return_value={"status": "failed", "error": "淘宝 TOP 未配置", "output": None})
        with patch("neurova.collaboration.neurflow.commerce_nodes.CommercePlatformClient") as cpc_cls:
            cpc_cls.return_value.fetch_prices = fake_client
            result = await exec_price_monitor(
                {"platform": "taobao", "products": "B0XXX", "alert_threshold": "50"},
                {"timestamp": "2026-08-29"},
            )
        assert result["status"] == "success"  # 行为不变：工作流不中断
        assert result["output"]["fallback"] is True
        note = result["output"]["note"]
        assert "本地模拟数据" in note
        assert "淘宝 TOP 未配置" in note

    @pytest.mark.asyncio
    async def test_price_monitor_invalid_store_degrades_with_note(self):
        fake_client = AsyncMock(return_value={"status": "failed", "error": "店铺不存在: store_ghost", "output": None})
        with patch("neurova.collaboration.neurflow.commerce_nodes.CommercePlatformClient") as cpc_cls, patch(
            "neurova.collaboration.neurflow.commerce_nodes.get_store_connection_manager"
        ) as sm:
            # 店铺解析失败（默认单例下即失败）→ 仍走降级
            from neurova.collaboration.neurflow.external_api import ExternalAPIError

            sm.return_value.resolve_credentials = AsyncMock(side_effect=ExternalAPIError("店铺不存在: store_ghost"))
            cpc_cls.return_value.fetch_prices = fake_client
            result = await exec_price_monitor(
                {"platform": "taobao", "products": "B0XXX", "alert_threshold": "50", "store_id": "store_ghost"},
                {"timestamp": "2026-08-29"},
            )
        assert result["output"].get("fallback") is True
        assert "本地模拟数据" in result["output"]["note"]
