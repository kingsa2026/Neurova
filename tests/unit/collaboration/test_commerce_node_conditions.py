"""
电商节点 sub_block 条件可见性契约测试（TDD 红灯先行）。

需求：画布平台参数随「平台」下拉联动显示 —— 选亚马逊出现 SP-API 相关参数
（MarketplaceId / region / reportType / putListingsItem 载荷字段 / Amazon Ads profileId），
选淘宝出现淘宝相关参数（num_iid 等），其余平台同理。

契约（对齐 models.SubBlockConfig.condition: {field, operator, value}）：
1. 亚马逊专属字段必须携带 condition platform=amazon，仅亚马逊可见；
2. 平台商品 ID 字段（products/asin/skus/competitors）按平台提供同键变体，
   每个变体携带各自平台的 condition，且 id/default 一致；
3. 通用字段（platform/threshold/period 等）不带 condition，始终可见；
4. /neurflow/nodes 序列化（_sub_block_to_dict）必须透传 condition；
5. register_commerce_nodes 注册后 condition 不丢失。
"""

import pytest

from neurova.collaboration.neurflow import commerce_nodes
from neurova.collaboration.neurflow.commerce_nodes import (
    COMMERCE_NODES,
    register_commerce_nodes,
)

# 仅对亚马逊有意义的 SP-API / Amazon Ads 字段
AMAZON_ONLY_BLOCK_IDS = {
    "marketplace_id",
    "region",
    "report_type",
    "sku",
    "seller_id",
    "product_type",
    "requirements",
    "profile_id",
}

# 需要按平台联动的商品 ID 字段：节点 type → 字段 id
PLATFORM_SCOPED_ID_FIELDS = {
    "builtin:price-monitor": "products",
    "builtin:review-respond": "asin",
    "builtin:inventory-sync": "skus",
    "builtin:competitor-analysis": "competitors",
}

# 商品 ID 变体至少应覆盖的真实 API 平台（评论节点仅亚马逊/淘宝有评论 API）
REVIEW_API_PLATFORMS = {"amazon", "taobao"}
PRODUCT_API_PLATFORMS = {"amazon", "taobao", "jd", "pdd", "douyin-ecom", "tiktok"}


def _node(node_type: str) -> dict:
    for n in COMMERCE_NODES:
        if n["type"] == node_type:
            return n
    raise AssertionError(f"节点 {node_type} 不存在")


def _blocks(node_type: str) -> list:
    return _node(node_type).get("sub_blocks", [])


def _blocks_by_id(node_type: str, block_id: str) -> list:
    return [b for b in _blocks(node_type) if b.get("id") == block_id]


def _cond_platforms(block: dict) -> set:
    """提取 sub_block condition 限定的平台集合；无 condition 返回 None"""
    cond = block.get("condition")
    if not cond:
        return None
    assert cond.get("field") == "platform", f"condition.field 应为 platform: {cond}"
    op = cond.get("operator", "eq")
    value = cond.get("value")
    if op == "eq":
        return {value}
    if op == "in":
        assert isinstance(value, list), f"in 条件 value 应为列表: {cond}"
        return set(value)
    raise AssertionError(f"不支持的 operator: {op}")


class TestAmazonOnlyBlocks:
    @pytest.mark.parametrize(
        "node_type",
        [
            "builtin:price-monitor",
            "builtin:product-listing",
            "builtin:inventory-sync",
            "builtin:competitor-analysis",
            "builtin:sales-report",
            "builtin:ad-streaming",
            "builtin:ad-monitor",
            "builtin:review-respond",
        ],
    )
    def test_amazon_only_blocks_scoped_to_amazon(self, node_type):
        """所有出现的亚马逊专属字段必须仅在 platform=amazon 时可见"""
        for b in _blocks(node_type):
            if b.get("id") in AMAZON_ONLY_BLOCK_IDS:
                platforms = _cond_platforms(b)
                assert platforms == {"amazon"}, (
                    f"{node_type}.{b.get('id')} 为亚马逊专属字段，"
                    f"condition 应限定 platform=amazon，实际: {b.get('condition')}"
                )


class TestPlatformScopedIdFields:
    @pytest.mark.parametrize(
        "node_type,field_id,expected_platforms",
        [
            ("builtin:price-monitor", "products", PRODUCT_API_PLATFORMS),
            ("builtin:review-respond", "asin", REVIEW_API_PLATFORMS),
            ("builtin:inventory-sync", "skus", PRODUCT_API_PLATFORMS),
            ("builtin:competitor-analysis", "competitors", PRODUCT_API_PLATFORMS),
        ],
    )
    def test_id_field_has_per_platform_variants(self, node_type, field_id, expected_platforms):
        """商品 ID 字段必须按平台提供联动变体，覆盖全部有真实 API 的平台"""
        variants = _blocks_by_id(node_type, field_id)
        assert variants, f"{node_type} 缺少 {field_id} 字段"
        covered = set()
        for v in variants:
            platforms = _cond_platforms(v)
            assert platforms is not None, (
                f"{node_type}.{field_id} 变体必须携带平台 condition，否则无法联动显示"
            )
            covered |= platforms
        missing = expected_platforms - covered
        assert not missing, f"{node_type}.{field_id} 缺少平台变体: {missing}"

    @pytest.mark.parametrize(
        "node_type,field_id",
        [
            ("builtin:price-monitor", "products"),
            ("builtin:review-respond", "asin"),
            ("builtin:inventory-sync", "skus"),
            ("builtin:competitor-analysis", "competitors"),
        ],
    )
    def test_variants_share_id_and_default(self, node_type, field_id):
        """同键变体的 default 必须一致（config 键唯一，避免默认值歧义）"""
        variants = _blocks_by_id(node_type, field_id)
        defaults = {str(v.get("default")) for v in variants}
        assert len(defaults) == 1, f"{node_type}.{field_id} 变体 default 不一致: {defaults}"

    def test_variant_labels_mention_platform_id_naming(self):
        """变体标题应体现平台 ID 命名（如 ASIN / num_iid），保证联动后语义清晰"""
        variants = _blocks_by_id("builtin:price-monitor", "products")
        labels_by_platform = {}
        for v in variants:
            for p in _cond_platforms(v) or ():
                labels_by_platform[p] = v.get("label", "")
        assert "ASIN" in labels_by_platform.get("amazon", ""), "亚马逊变体标题应含 ASIN"
        assert "num_iid" in labels_by_platform.get("taobao", ""), "淘宝变体标题应含 num_iid"


class TestGenericBlocksAlwaysVisible:
    @pytest.mark.parametrize(
        "node_type,field_id",
        [
            ("builtin:price-monitor", "platform"),
            ("builtin:price-monitor", "alert_threshold"),
            ("builtin:price-monitor", "check_interval"),
            ("builtin:review-respond", "reviews"),
            ("builtin:review-respond", "tone"),
            ("builtin:sales-report", "period"),
            ("builtin:sales-report", "metrics"),
            ("builtin:ad-cross", "platforms"),
        ],
    )
    def test_generic_block_has_no_condition(self, node_type, field_id):
        blocks = _blocks_by_id(node_type, field_id)
        assert blocks, f"{node_type} 缺少 {field_id}"
        for b in blocks:
            assert not b.get("condition"), (
                f"{node_type}.{field_id} 为通用字段，不应携带 condition: {b.get('condition')}"
            )


class TestSerializationContract:
    def test_sub_block_to_dict_passes_condition_through(self):
        """/neurflow/nodes 序列化必须透传 condition，前端才能联动"""
        from neurova.api.endpoints.neurflow_api import _sub_block_to_dict

        raw = {
            "id": "marketplace_id",
            "label": "亚马逊站点",
            "type": "select",
            "default": "ATVPDKIKX0DER",
            "condition": {"field": "platform", "operator": "eq", "value": "amazon"},
        }
        out = _sub_block_to_dict(raw)
        assert out["condition"] == raw["condition"]

    def test_sub_block_to_dict_condition_absent_is_none(self):
        from neurova.api.endpoints.neurflow_api import _sub_block_to_dict

        out = _sub_block_to_dict({"id": "platform", "label": "平台", "type": "select"})
        assert out.get("condition") is None


class TestRegistrationPreservesCondition:
    def test_register_commerce_nodes_keeps_condition(self):
        """注册到 NodeRegistry 后 sub_blocks 的 condition 不丢失"""

        class _FakeRegistry:
            def __init__(self):
                self.definitions = []

            def register(self, definition, executor=None):
                self.definitions.append(definition)

        registry = _FakeRegistry()
        count = register_commerce_nodes(registry)
        assert count == len(COMMERCE_NODES) == 13

        by_type = {d.type: d for d in registry.definitions}
        listing = by_type["builtin:product-listing"]
        mp = [b for b in listing.sub_blocks if (b.get("id") if isinstance(b, dict) else b.id) == "marketplace_id"]
        assert mp, "product-listing 注册后丢失 marketplace_id"
        b = mp[0]
        cond = b.get("condition") if isinstance(b, dict) else getattr(b, "condition", None)
        assert cond and cond.get("field") == "platform" and cond.get("value") == "amazon"


class TestExecutorsUnaffected:
    """联动仅影响可见性，config 仍携带隐藏键 —— 执行器行为不变"""

    def test_price_monitor_ignores_hidden_amazon_keys_for_taobao(self):
        import asyncio

        config = {
            "platform": "taobao",
            "products": "123456",
            # 以下键在淘宝下被联动隐藏，但旧快照仍可能携带
            "marketplace_id": "ATVPDKIKX0DER",
            "region": "na",
            "alert_threshold": "50",
        }
        result = asyncio.run(commerce_nodes.exec_price_monitor(config, {}))
        assert result["status"] == "success"
        assert result["output"]["platform"] == "taobao"
