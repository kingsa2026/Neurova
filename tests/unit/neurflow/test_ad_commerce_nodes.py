"""
Neurflow 广告投放电商节点测试 — TDD 垂直切片

测试广告投放节点定义与执行器功能：
1. 广告流投放（ad-streaming）
2. 广告监控（ad-monitor）
3. 广告策略（ad-strategy）
4. 跨渠道广告投放（ad-cross）
"""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

# 导入待测模块（红灯阶段：预期导入失败，因为节点尚未实现）
from neurova.collaboration.neurflow.commerce_nodes import (
    COMMERCE_NODES,
    register_commerce_nodes,
    get_commerce_executors,
    # 执行器
    exec_ad_streaming,
    exec_ad_monitor,
    exec_ad_strategy,
    exec_ad_cross,
)

# 新增广告投放节点类型集合
EXPECTED_AD_TYPES = {
    "builtin:ad-streaming",  # 广告流投放
    "builtin:ad-monitor",    # 广告监控
    "builtin:ad-strategy",   # 广告策略
    "builtin:ad-cross",      # 跨渠道广告投放
}


class TestAdCommerceNodesDefinition:
    """测试广告投放节点定义"""

    def test_has_all_ad_commerce_nodes(self):
        """应包含所有广告投放节点"""
        types = [n["type"] for n in COMMERCE_NODES]
        for t in EXPECTED_AD_TYPES:
            assert t in types, f"缺少广告节点: {t}"

    def test_ad_nodes_commerce_category(self):
        """所有广告节点分类应为 commerce"""
        for node in COMMERCE_NODES:
            if node["type"] in EXPECTED_AD_TYPES:
                assert node["category"] == "commerce", f"广告节点分类错误: {node['type']}"

    def test_ad_nodes_have_required_fields(self):
        """每个广告节点应有必需字段"""
        for node in COMMERCE_NODES:
            if node["type"] in EXPECTED_AD_TYPES:
                assert "type" in node, f"节点缺少 type: {node}"
                assert "label" in node, f"节点缺少 label: {node}"
                assert "icon" in node, f"节点缺少 icon: {node}"
                assert "category" in node, f"节点缺少 category: {node}"
                assert "description" in node, f"节点缺少 description: {node}"
                assert "sub_blocks" in node, f"节点缺少 sub_blocks: {node}"
                assert "inputs" in node, f"节点缺少 inputs: {node}"
                assert "outputs" in node, f"节点缺少 outputs: {node}"

    def test_ad_node_type_format(self):
        """广告节点类型应以 builtin: 开头"""
        for node in COMMERCE_NODES:
            if node["type"] in EXPECTED_AD_TYPES:
                assert node["type"].startswith("builtin:"), f"节点类型格式错误: {node['type']}"

    def test_ad_streaming_definition(self):
        """广告流投放节点应包含平台、预算、定向等字段"""
        node = next(n for n in COMMERCE_NODES if n["type"] == "builtin:ad-streaming")
        assert node["label"] == "广告流投放"
        assert len(node["sub_blocks"]) >= 3
        block_ids = [b.get("id") or b.get("name") for b in node["sub_blocks"]]
        assert "platform" in block_ids, f"广告流投放缺少 platform 字段: {block_ids}"
        assert "budget" in block_ids, f"广告流投放缺少 budget 字段: {block_ids}"

    def test_ad_monitor_definition(self):
        """广告监控节点应包含平台、广告ID等字段"""
        node = next(n for n in COMMERCE_NODES if n["type"] == "builtin:ad-monitor")
        assert node["label"] == "广告监控"
        block_ids = [b.get("id") or b.get("name") for b in node["sub_blocks"]]
        assert "platform" in block_ids, f"广告监控缺少 platform 字段: {block_ids}"
        assert "ad_ids" in block_ids, f"广告监控缺少 ad_ids 字段: {block_ids}"

    def test_ad_strategy_definition(self):
        """广告策略节点应包含平台、目标等字段"""
        node = next(n for n in COMMERCE_NODES if n["type"] == "builtin:ad-strategy")
        assert node["label"] == "广告策略"
        block_ids = [b.get("id") or b.get("name") for b in node["sub_blocks"]]
        assert "platform" in block_ids, f"广告策略缺少 platform 字段: {block_ids}"
        assert "goal" in block_ids, f"广告策略缺少 goal 字段: {block_ids}"

    def test_ad_cross_definition(self):
        """跨渠道广告投放节点应包含平台列表、预算等字段"""
        node = next(n for n in COMMERCE_NODES if n["type"] == "builtin:ad-cross")
        assert node["label"] == "跨渠道广告投放"
        block_ids = [b.get("id") or b.get("name") for b in node["sub_blocks"]]
        assert "platforms" in block_ids, f"跨渠道投放缺少 platforms 字段: {block_ids}"
        assert "total_budget" in block_ids, f"跨渠道投放缺少 total_budget 字段: {block_ids}"

    def test_each_ad_node_has_at_least_one_output(self):
        """每个广告节点应至少有输出端口"""
        for node in COMMERCE_NODES:
            if node["type"] in EXPECTED_AD_TYPES:
                assert len(node["outputs"]) >= 1, f"广告节点缺少输出: {node['type']}"


class TestRegisterAdCommerceNodes:
    """测试广告节点注册"""

    def test_register_returns_count(self):
        """注册函数应返回注册数量"""
        mock_registry = MagicMock()
        count = register_commerce_nodes(mock_registry)
        # 共计 8 个原有 + 4 个新增 = 12 个
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
            assert args[1] is not None or kwargs.get("executor") is not None, "执行器未附加"


class TestAdCommerceExecutors:
    """测试广告节点执行器"""

    def test_get_commerce_executors_returns_dict(self):
        """应返回执行器字典"""
        executors = get_commerce_executors()
        assert isinstance(executors, dict)
        assert len(executors) == len(COMMERCE_NODES)

    def test_executors_have_all_ad_types(self):
        """应包含所有广告节点类型的执行器"""
        executors = get_commerce_executors()
        for node in COMMERCE_NODES:
            if node["type"] in EXPECTED_AD_TYPES:
                assert node["type"] in executors, f"缺少执行器: {node['type']}"

    @pytest.mark.asyncio
    async def test_exec_ad_streaming_success(self):
        """广告流投放应返回投放计划"""
        config = {"platform": "amazon", "budget": "1000", "targeting": "自动定向"}
        ctx = {}
        result = await exec_ad_streaming(config, ctx)
        assert result["status"] == "success"
        assert "output" in result
        assert "campaign" in result["output"]

    @pytest.mark.asyncio
    async def test_exec_ad_streaming_agent_mode(self):
        """广告流投放有 Agent 时应调用 Agent 生成投放策略"""
        mock_agent = MagicMock()
        mock_agent.chat = AsyncMock(return_value='{"campaign_name": "春季大促", "daily_budget": 500}')
        with patch("neurova.collaboration.neurflow.commerce_nodes._get_agent", return_value=mock_agent):
            config = {"platform": "amazon", "budget": "2000", "targeting": "自动定向"}
            ctx = {}
            result = await exec_ad_streaming(config, ctx)
            assert result["status"] == "success"
            assert "output" in result

    @pytest.mark.asyncio
    async def test_exec_ad_monitor_success(self):
        """广告监控应返回监控指标"""
        config = {"platform": "amazon", "ad_ids": "ad_001, ad_002", "metrics": "impressions,clicks"}
        ctx = {}
        result = await exec_ad_monitor(config, ctx)
        assert result["status"] == "success"
        assert "output" in result
        assert "metrics" in result["output"]

    @pytest.mark.asyncio
    async def test_exec_ad_monitor_with_metrics(self):
        """广告监控应包含各项指标数据"""
        config = {"platform": "amazon", "ad_ids": "ad_001", "metrics": "impressions,clicks,conversions,spend"}
        ctx = {}
        result = await exec_ad_monitor(config, ctx)
        assert result["status"] == "success"
        output = result["output"]
        assert "metrics" in output
        assert len(output["metrics"]) >= 1
        first = output["metrics"][0]
        # 应包含所有请求的指标
        assert "impressions" in first
        assert "clicks" in first
        assert "conversions" in first
        assert "spend" in first

    @pytest.mark.asyncio
    async def test_exec_ad_strategy_success(self):
        """广告策略应返回策略建议"""
        config = {"platform": "amazon", "goal": "increase_sales", "budget": "5000"}
        ctx = {}
        result = await exec_ad_strategy(config, ctx)
        assert result["status"] == "success"
        assert "output" in result
        assert "strategy" in result["output"]

    @pytest.mark.asyncio
    async def test_exec_ad_strategy_agent_mode(self):
        """广告策略有 Agent 时应调用 Agent 生成策略"""
        mock_agent = MagicMock()
        mock_agent.chat = AsyncMock(return_value="建议采用动态出价策略，旺季提高预算30%")
        with patch("neurova.collaboration.neurflow.commerce_nodes._get_agent", return_value=mock_agent):
            config = {"platform": "amazon", "goal": "increase_sales", "budget": "5000"}
            ctx = {}
            result = await exec_ad_strategy(config, ctx)
            assert result["status"] == "success"
            assert "output" in result
            mock_agent.chat.assert_called_once()

    @pytest.mark.asyncio
    async def test_exec_ad_strategy_without_agent(self):
        """无 Agent 时广告策略应返回规则兜底策略"""
        with patch("neurova.collaboration.neurflow.commerce_nodes._get_agent", return_value=None):
            config = {"platform": "amazon", "goal": "increase_sales", "budget": "5000"}
            ctx = {}
            result = await exec_ad_strategy(config, ctx)
            assert result["status"] == "success"
            assert "strategy" in result["output"]

    @pytest.mark.asyncio
    async def test_exec_ad_cross_success(self):
        """跨渠道投放应返回多平台投放计划"""
        config = {"platforms": "amazon,taobao", "total_budget": "10000", "product": "智能手表"}
        ctx = {}
        result = await exec_ad_cross(config, ctx)
        assert result["status"] == "success"
        assert "output" in result
        assert "channels" in result["output"]

    @pytest.mark.asyncio
    async def test_exec_ad_cross_budget_distribution(self):
        """跨渠道投放应包含预算分配"""
        config = {"platforms": "amazon,taobao,jd", "total_budget": "15000", "product": "蓝牙耳机"}
        ctx = {}
        result = await exec_ad_cross(config, ctx)
        assert result["status"] == "success"
        output = result["output"]
        assert "channels" in output
        # 每个渠道应有预算分配
        total_allocated = sum(c.get("allocated_budget", 0) for c in output["channels"])
        assert total_allocated > 0

    @pytest.mark.asyncio
    async def test_exec_ad_cross_multiple_platforms(self):
        """跨渠道投放应支持多个平台"""
        config = {"platforms": "amazon,taobao,jd,pdd", "total_budget": "20000", "product": "运动鞋"}
        ctx = {}
        result = await exec_ad_cross(config, ctx)
        assert result["status"] == "success"
        output = result["output"]
        assert len(output["channels"]) >= 4


class TestAdCommerceTemplateIntegrity:
    """测试广告模板引用的节点完整性"""

    def test_template_referenced_ad_nodes_exist(self):
        """ecommerce 模板中引用的广告节点都应存在"""
        executors = get_commerce_executors()
        # 模板中可能引用的广告节点
        ad_refs = [
            "builtin:ad-streaming",
            "builtin:ad-monitor",
            "builtin:ad-strategy",
            "builtin:ad-cross",
        ]
        for ref in ad_refs:
            assert ref in executors, f"模板引用的广告节点未定义执行器: {ref}"