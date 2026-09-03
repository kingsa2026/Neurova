"""
Neurflow 电商运营节点测试 — TDD 垂直切片

测试电商运营节点定义与执行器功能：
1. 电商节点定义（亚马逊 / 抖音 / 淘宝等平台）
2. 节点注册到注册表
3. 节点执行器行为
4. 模板引用的节点完整性
"""
import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch

# 导入待测模块
from neurova.collaboration.neurflow.commerce_nodes import (
    COMMERCE_NODES,
    register_commerce_nodes,
    get_commerce_executors,
    # 执行器
    exec_price_monitor,
    exec_ad_copy,
    exec_review_respond,
    exec_product_listing,
    exec_inventory_sync,
    exec_competitor_analysis,
    exec_keyword_research,
    exec_sales_report,
)

# 电商节点类型集合
EXPECTED_COMMERCE_TYPES = {
    "builtin:price-monitor",       # 价格监控
    "builtin:ad-copy",             # 广告文案生成
    "builtin:review-respond",      # 评论自动回复
    "builtin:product-listing",     # 商品上架 / Listing 优化
    "builtin:inventory-sync",      # 库存同步
    "builtin:competitor-analysis", # 竞品分析
    "builtin:keyword-research",    # 关键词研究
    "builtin:sales-report",        # 销售报表
}


class TestCommerceNodesDefinition:
    """测试电商运营节点定义"""

    def test_has_all_commerce_nodes(self):
        """应包含所有电商运营节点"""
        types = [n["type"] for n in COMMERCE_NODES]
        for t in EXPECTED_COMMERCE_TYPES:
            assert t in types, f"缺少电商节点: {t}"

    def test_all_nodes_commerce_category(self):
        """所有节点分类应为 commerce"""
        for node in COMMERCE_NODES:
            assert node["category"] == "commerce", f"节点分类错误: {node['type']}"

    def test_node_has_required_fields(self):
        """每个节点应有必需字段"""
        for node in COMMERCE_NODES:
            assert "type" in node, f"节点缺少 type: {node}"
            assert "label" in node, f"节点缺少 label: {node}"
            assert "icon" in node, f"节点缺少 icon: {node}"
            assert "category" in node, f"节点缺少 category: {node}"
            assert "description" in node, f"节点缺少 description: {node}"
            assert "sub_blocks" in node, f"节点缺少 sub_blocks: {node}"
            assert "inputs" in node, f"节点缺少 inputs: {node}"
            assert "outputs" in node, f"节点缺少 outputs: {node}"

    def test_node_type_format(self):
        """节点类型应以 builtin: 开头"""
        for node in COMMERCE_NODES:
            assert node["type"].startswith("builtin:"), f"节点类型格式错误: {node['type']}"

    def test_price_monitor_definition(self):
        """价格监控节点应包含平台、商品、告警阈值等字段"""
        node = next(n for n in COMMERCE_NODES if n["type"] == "builtin:price-monitor")
        assert node["label"] == "价格监控"
        assert len(node["sub_blocks"]) >= 3
        # 应包含平台选择字段
        block_ids = [b.get("id") or b.get("name") for b in node["sub_blocks"]]
        assert "platform" in block_ids, f"价格监控缺少 platform 字段: {block_ids}"
        assert "products" in block_ids, f"价格监控缺少 products 字段: {block_ids}"

    def test_ad_copy_definition(self):
        """广告文案节点应包含平台、商品、风格等字段"""
        node = next(n for n in COMMERCE_NODES if n["type"] == "builtin:ad-copy")
        assert node["label"] == "广告文案生成"
        block_ids = [b.get("id") or b.get("name") for b in node["sub_blocks"]]
        assert "platform" in block_ids, f"广告文案缺少 platform 字段: {block_ids}"
        assert "product" in block_ids, f"广告文案缺少 product 字段: {block_ids}"

    def test_review_respond_definition(self):
        """评论回复节点应包含评论输入与回复语气字段"""
        node = next(n for n in COMMERCE_NODES if n["type"] == "builtin:review-respond")
        assert node["label"] == "评论自动回复"
        block_ids = [b.get("id") or b.get("name") for b in node["sub_blocks"]]
        assert "reviews" in block_ids, f"评论回复缺少 reviews 字段: {block_ids}"
        assert "tone" in block_ids, f"评论回复缺少 tone 字段: {block_ids}"

    def test_each_node_has_at_least_one_output(self):
        """每个节点应至少有输出端口"""
        for node in COMMERCE_NODES:
            assert len(node["outputs"]) >= 1, f"节点缺少输出: {node['type']}"


class TestRegisterCommerceNodes:
    """测试电商节点注册"""

    def test_register_returns_count(self):
        """注册函数应返回注册数量"""
        mock_registry = MagicMock()
        count = register_commerce_nodes(mock_registry)
        assert count == len(COMMERCE_NODES)

    def test_register_calls_registry_register(self):
        """应调用 registry.register 注册每个节点"""
        mock_registry = MagicMock()
        register_commerce_nodes(mock_registry)
        assert mock_registry.register.call_count == len(COMMERCE_NODES)

    def test_register_attaches_executors(self):
        """注册时应传递执行器"""
        mock_registry = MagicMock()
        register_commerce_nodes(mock_registry)
        for call in mock_registry.register.call_args_list:
            args, kwargs = call
            # executor 通过位置参数或 kwargs 传递
            assert args[1] is not None or kwargs.get("executor") is not None, "执行器未附加"


class TestCommerceExecutors:
    """测试电商节点执行器"""

    def test_get_commerce_executors_returns_dict(self):
        """应返回执行器字典"""
        executors = get_commerce_executors()
        assert isinstance(executors, dict)
        assert len(executors) == len(COMMERCE_NODES)

    def test_executors_have_all_commerce_types(self):
        """应包含所有电商节点类型的执行器"""
        executors = get_commerce_executors()
        for node in COMMERCE_NODES:
            assert node["type"] in executors, f"缺少执行器: {node['type']}"

    @pytest.mark.asyncio
    async def test_exec_price_monitor_success(self):
        """价格监控应返回监控结果"""
        config = {"platform": "amazon", "products": "B0XXXXX", "alert_threshold": 10}
        ctx = {}
        result = await exec_price_monitor(config, ctx)
        assert result["status"] == "success"
        assert "output" in result
        assert "alerts" in result["output"]

    @pytest.mark.asyncio
    async def test_exec_price_monitor_alert_on_low_price(self):
        """价格低于阈值时应产生告警"""
        config = {"platform": "amazon", "products": "B0XXXXX", "alert_threshold": 100}
        ctx = {}
        result = await exec_price_monitor(config, ctx)
        assert result["status"] == "success"
        # 高阈值应触发告警
        assert len(result["output"]["alerts"]) >= 1

    @pytest.mark.asyncio
    async def test_exec_ad_copy_success(self):
        """广告文案应调用 Agent 生成"""
        mock_agent = MagicMock()
        mock_agent.chat = AsyncMock(return_value="🔥 限时特惠！")
        with patch("neurova.collaboration.neurflow.commerce_nodes._get_agent", return_value=mock_agent):
            config = {"platform": "amazon", "product": "智能手表", "style": "promotion", "language": "zh"}
            ctx = {}
            result = await exec_ad_copy(config, ctx)
            assert result["status"] == "success"
            assert "output" in result
            mock_agent.chat.assert_called_once()

    @pytest.mark.asyncio
    async def test_exec_ad_copy_without_agent(self):
        """无 Agent 时应返回错误"""
        with patch("neurova.collaboration.neurflow.commerce_nodes._get_agent", return_value=None):
            config = {"platform": "amazon", "product": "智能手表"}
            ctx = {}
            result = await exec_ad_copy(config, ctx)
            assert result["status"] == "failed"
            assert "error" in result

    @pytest.mark.asyncio
    async def test_exec_review_respond_success(self):
        """评论回复应生成回复与情感分析"""
        config = {"platform": "taobao", "reviews": "质量很好，发货快", "tone": "friendly"}
        ctx = {}
        result = await exec_review_respond(config, ctx)
        assert result["status"] == "success"
        assert "output" in result
        assert "sentiment" in result["output"]

    @pytest.mark.asyncio
    async def test_exec_product_listing_success(self):
        """商品上架应返回 Listing 优化结果"""
        config = {
            "platform": "amazon",
            "product_name": "智能手表",
            "features": "防水, 长续航, 心率监测",
            "keywords": "smartwatch",
        }
        ctx = {}
        result = await exec_product_listing(config, ctx)
        assert result["status"] == "success"
        assert "output" in result
        assert "title" in result["output"]

    @pytest.mark.asyncio
    async def test_exec_inventory_sync_success(self):
        """库存同步应返回库存状态"""
        config = {"platforms": "amazon,taobao", "low_stock_threshold": 10}
        ctx = {}
        result = await exec_inventory_sync(config, ctx)
        assert result["status"] == "success"
        assert "output" in result

    @pytest.mark.asyncio
    async def test_exec_competitor_analysis_success(self):
        """竞品分析应返回分析结果"""
        config = {"platform": "amazon", "competitors": "B0XXXXX, B0YYYYY"}
        ctx = {}
        result = await exec_competitor_analysis(config, ctx)
        assert result["status"] == "success"
        assert "output" in result

    @pytest.mark.asyncio
    async def test_exec_keyword_research_success(self):
        """关键词研究应返回关键词列表"""
        config = {"platform": "taobao", "seed_keywords": "智能手表", "language": "zh"}
        ctx = {}
        result = await exec_keyword_research(config, ctx)
        assert result["status"] == "success"
        assert "output" in result
        assert "keywords" in result["output"]

    @pytest.mark.asyncio
    async def test_exec_sales_report_success(self):
        """销售报表应返回报表结果"""
        config = {"platform": "amazon", "period": "2025-01", "metrics": "sales,orders"}
        ctx = {}
        result = await exec_sales_report(config, ctx)
        assert result["status"] == "success"
        assert "output" in result


class TestCommerceTemplateIntegrity:
    """测试电商模板引用的节点完整性"""

    def test_template_referenced_nodes_exist(self):
        """ecommerce 模板引用的节点都应存在"""
        executors = get_commerce_executors()
        # 模板中引用的节点
        template_refs = [
            "builtin:price-monitor",
            "builtin:ad-copy",
            "builtin:review-respond",
        ]
        for ref in template_refs:
            assert ref in executors, f"模板引用的节点未定义执行器: {ref}"

    def test_categories_include_amazon_tiktok_taobao(self):
        """价格监控与广告文案节点应支持主流电商平台"""
        # 检查平台选项字段是否包含亚马逊/抖音/淘宝
        for ntype in ("builtin:price-monitor", "builtin:ad-copy"):
            node = next(n for n in COMMERCE_NODES if n["type"] == ntype)
            platforms = []
            for block in node["sub_blocks"]:
                if (block.get("id") or block.get("name")) == "platform":
                    platforms = block.get("options", [])
            assert platforms, f"{ntype} 缺少平台选项"
            assert any("亚马逊" in str(p) or "Amazon" in str(p) for p in platforms), f"{ntype} 缺少亚马逊"
            assert any("抖音" in str(p) or "TikTok" in str(p) for p in platforms), f"{ntype} 缺少抖音"
            assert any("淘宝" in str(p) or "Taobao" in str(p) for p in platforms), f"{ntype} 缺少淘宝"
