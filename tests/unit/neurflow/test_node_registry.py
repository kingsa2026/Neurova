"""
Neurflow 节点注册表测试 — 垂直切片 3
测试节点注册、查询、自动发现功能
"""
import pytest
from unittest.mock import Mock, patch
from neurova.collaboration.neurflow.models import (
    NodeDefinition, SubBlockConfig, NodePort, NodeCategory
)
from neurova.collaboration.neurflow.node_registry import (
    NodeRegistry, get_node_registry, reset_node_registry
)


class TestNodeRegistry:
    """NodeRegistry 核心功能测试"""

    @pytest.fixture(autouse=True)
    def setup(self):
        """每个测试前重置注册表"""
        reset_node_registry()
        yield
        reset_node_registry()

    @pytest.fixture
    def sample_node(self):
        """示例节点定义"""
        return NodeDefinition(
            type="tool:web_search",
            label="网页搜索",
            icon="🔍",
            category="tools",
            description="搜索网页内容",
            sub_blocks=[
                SubBlockConfig(id="query", title="搜索词", type="input", required=True)
            ],
            inputs=[NodePort(id="input", label="输入")],
            outputs=[NodePort(id="output", label="输出"), NodePort(id="error", label="错误")],
            source="tool",
            source_id="web_search",
            version="1.0.0",
            tags=["search", "web"]
        )

    @pytest.fixture
    def sample_executor(self):
        """示例执行器"""
        async def executor(config, context):
            return {"result": "search result"}
        return executor

    # ==================== 单例模式 ====================

    def test_singleton_pattern(self):
        """测试单例模式"""
        registry1 = get_node_registry()
        registry2 = get_node_registry()
        assert registry1 is registry2

    def test_reset_singleton(self):
        """测试重置单例"""
        registry1 = get_node_registry()
        reset_node_registry()
        registry2 = get_node_registry()
        assert registry1 is not registry2

    # ==================== 注册功能 ====================

    def test_register_node(self, sample_node, sample_executor):
        """测试注册节点"""
        registry = get_node_registry()
        
        # 注册
        registry.register(sample_node, sample_executor)
        
        # 验证注册成功
        retrieved = registry.get("tool:web_search")
        assert retrieved is not None
        assert retrieved.type == "tool:web_search"
        assert retrieved.label == "网页搜索"

    def test_register_node_without_executor(self, sample_node):
        """测试注册节点（无执行器）"""
        registry = get_node_registry()
        
        # 注册
        registry.register(sample_node)
        
        # 验证注册成功
        retrieved = registry.get("tool:web_search")
        assert retrieved is not None
        
        # 验证执行器为 None
        executor = registry.get_executor("tool:web_search")
        assert executor is None

    def test_register_duplicate_node(self, sample_node, sample_executor):
        """测试注册重复节点（覆盖）"""
        registry = get_node_registry()
        
        # 第一次注册
        registry.register(sample_node, sample_executor)
        
        # 修改节点
        sample_node.label = "网页搜索（更新）"
        sample_node.version = "1.1.0"
        
        # 第二次注册（覆盖）
        registry.register(sample_node, sample_executor)
        
        # 验证更新成功
        retrieved = registry.get("tool:web_search")
        assert retrieved.label == "网页搜索（更新）"
        assert retrieved.version == "1.1.0"

    def test_unregister_node(self, sample_node, sample_executor):
        """测试注销节点"""
        registry = get_node_registry()
        
        # 注册
        registry.register(sample_node, sample_executor)
        assert registry.get("tool:web_search") is not None
        
        # 注销
        result = registry.unregister("tool:web_search")
        assert result is True
        
        # 验证注销成功
        assert registry.get("tool:web_search") is None

    def test_unregister_nonexistent_node(self):
        """测试注销不存在的节点"""
        registry = get_node_registry()
        
        result = registry.unregister("nonexistent:tool")
        assert result is False

    # ==================== 查询功能 ====================

    def test_get_node(self, sample_node, sample_executor):
        """测试获取节点"""
        registry = get_node_registry()
        registry.register(sample_node, sample_executor)
        
        # 获取存在的节点
        retrieved = registry.get("tool:web_search")
        assert retrieved is not None
        assert retrieved.type == "tool:web_search"
        
        # 获取不存在的节点
        not_found = registry.get("nonexistent:tool")
        assert not_found is None

    def test_list_all_nodes(self, sample_node, sample_executor):
        """测试列出所有节点"""
        registry = get_node_registry()
        
        # 注册多个节点
        registry.register(sample_node, sample_executor)
        
        node2 = NodeDefinition(
            type="builtin:condition",
            label="条件分支",
            icon="🔀",
            category="flow",
            description="根据条件选择分支",
            sub_blocks=[],
            inputs=[NodePort(id="input", label="输入")],
            outputs=[NodePort(id="true", label="真"), NodePort(id="false", label="假")],
            source="builtin"
        )
        registry.register(node2)
        
        # 列出所有
        all_nodes = registry.list_all()
        assert len(all_nodes) == 2

    def test_list_by_category(self, sample_node, sample_executor):
        """测试按分类列出节点"""
        registry = get_node_registry()
        
        # 注册多个节点
        registry.register(sample_node, sample_executor)
        
        node2 = NodeDefinition(
            type="builtin:condition",
            label="条件分支",
            icon="🔀",
            category="flow",
            description="根据条件选择分支",
            sub_blocks=[],
            inputs=[NodePort(id="input", label="输入")],
            outputs=[NodePort(id="true", label="真"), NodePort(id="false", label="假")],
            source="builtin"
        )
        registry.register(node2)
        
        # 按分类过滤
        tool_nodes = registry.list_by_category("tools")
        assert len(tool_nodes) == 1
        assert tool_nodes[0].type == "tool:web_search"
        
        flow_nodes = registry.list_by_category("flow")
        assert len(flow_nodes) == 1
        assert flow_nodes[0].type == "builtin:condition"
        
        # 不存在的分类
        empty_nodes = registry.list_by_category("nonexistent")
        assert len(empty_nodes) == 0

    def test_list_by_source(self, sample_node, sample_executor):
        """测试按来源列出节点"""
        registry = get_node_registry()
        
        # 注册多个节点
        registry.register(sample_node, sample_executor)
        
        node2 = NodeDefinition(
            type="builtin:condition",
            label="条件分支",
            icon="🔀",
            category="flow",
            description="根据条件选择分支",
            sub_blocks=[],
            inputs=[NodePort(id="input", label="输入")],
            outputs=[NodePort(id="true", label="真"), NodePort(id="false", label="假")],
            source="builtin"
        )
        registry.register(node2)
        
        # 按来源过滤
        tool_nodes = registry.list_by_source("tool")
        assert len(tool_nodes) == 1
        assert tool_nodes[0].type == "tool:web_search"
        
        builtin_nodes = registry.list_by_source("builtin")
        assert len(builtin_nodes) == 1
        assert builtin_nodes[0].type == "builtin:condition"
        
        # 不存在的来源
        empty_nodes = registry.list_by_source("nonexistent")
        assert len(empty_nodes) == 0

    def test_search_nodes(self, sample_node, sample_executor):
        """测试搜索节点"""
        registry = get_node_registry()
        
        # 注册多个节点
        registry.register(sample_node, sample_executor)
        
        node2 = NodeDefinition(
            type="builtin:llm",
            label="LLM 调用",
            icon="🤖",
            category="ai",
            description="调用大语言模型",
            sub_blocks=[],
            inputs=[NodePort(id="input", label="输入")],
            outputs=[NodePort(id="output", label="输出")],
            source="builtin"
        )
        registry.register(node2)
        
        # 搜索
        results = registry.search("搜索")
        assert len(results) == 1
        assert results[0].type == "tool:web_search"
        
        results = registry.search("LLM")
        assert len(results) == 1
        assert results[0].type == "builtin:llm"
        
        # 无结果搜索
        results = registry.search("不存在")
        assert len(results) == 0

    # ==================== 执行器功能 ====================

    def test_get_executor(self, sample_node, sample_executor):
        """测试获取执行器"""
        registry = get_node_registry()
        registry.register(sample_node, sample_executor)
        
        # 获取存在的执行器
        executor = registry.get_executor("tool:web_search")
        assert executor is not None
        assert executor is sample_executor
        
        # 获取不存在的执行器
        not_found = registry.get_executor("nonexistent:tool")
        assert not_found is None

    def test_executor_execution(self, sample_node, sample_executor):
        """测试执行器执行"""
        import asyncio
        
        registry = get_node_registry()
        registry.register(sample_node, sample_executor)
        
        executor = registry.get_executor("tool:web_search")
        
        # 执行
        result = asyncio.run(
            executor({"query": "test"}, {"context": "test"})
        )
        assert result == {"result": "search result"}

    # ==================== 统计功能 ====================

    def test_get_summary(self, sample_node, sample_executor):
        """测试获取统计信息"""
        registry = get_node_registry()
        
        # 注册多个节点
        registry.register(sample_node, sample_executor)
        
        node2 = NodeDefinition(
            type="builtin:condition",
            label="条件分支",
            icon="🔀",
            category="flow",
            description="根据条件选择分支",
            sub_blocks=[],
            inputs=[NodePort(id="input", label="输入")],
            outputs=[NodePort(id="true", label="真"), NodePort(id="false", label="假")],
            source="builtin"
        )
        registry.register(node2)
        
        # 获取统计
        summary = registry.get_summary()
        assert summary["total"] == 2
        assert summary["by_category"]["tools"] == 1
        assert summary["by_category"]["flow"] == 1
        assert summary["by_source"]["tool"] == 1
        assert summary["by_source"]["builtin"] == 1

    # ==================== 自动发现 ====================

    def test_ensure_builtin(self):
        """测试确保内置节点已注册"""
        registry = get_node_registry()
        
        # 初始状态应该为空
        assert len(registry.list_all()) == 0
        
        # 确保内置节点
        registry.ensure_builtin()
        
        # 应该有内置节点
        builtin_nodes = registry.list_by_source("builtin")
        assert len(builtin_nodes) > 0
        
        # 验证一些关键内置节点
        assert registry.get("builtin:start") is not None
        assert registry.get("builtin:end") is not None
        assert registry.get("builtin:condition") is not None
        assert registry.get("builtin:loop") is not None
        assert registry.get("builtin:llm") is not None

    def test_ensure_builtin_idempotent(self):
        """测试 ensure_builtin 幂等性"""
        registry = get_node_registry()
        
        # 第一次调用
        registry.ensure_builtin()
        count1 = len(registry.list_all())
        
        # 第二次调用（应该幂等）
        registry.ensure_builtin()
        count2 = len(registry.list_all())
        
        assert count1 == count2

    @patch('neurova.collaboration.neurflow.node_registry._sync_tools_from_engine')
    def test_sync_tools(self, mock_sync_tools):
        """测试同步工具"""
        # 模拟同步函数
        mock_sync_tools.return_value = 5
        
        registry = get_node_registry()
        
        # 同步工具
        count = registry.sync_tools()
        
        # 验证调用
        mock_sync_tools.assert_called_once_with(registry)
        assert count == 5

    @patch('neurova.collaboration.neurflow.node_registry._sync_skills_from_registry')
    def test_sync_skills(self, mock_sync_skills):
        """测试同步技能"""
        # 模拟同步函数
        mock_sync_skills.return_value = 3
        
        registry = get_node_registry()
        
        # 同步技能
        count = registry.sync_skills()
        
        # 验证调用
        mock_sync_skills.assert_called_once_with(registry)
        assert count == 3

    @patch('neurova.collaboration.neurflow.node_registry._sync_mcp_tools')
    def test_sync_mcp(self, mock_sync_mcp):
        """测试同步 MCP 工具"""
        # 模拟同步函数
        mock_sync_mcp.return_value = 2
        
        registry = get_node_registry()
        
        # 同步 MCP
        count = registry.sync_mcp()
        
        # 验证调用
        mock_sync_mcp.assert_called_once_with(registry)
        assert count == 2

    @patch('neurova.collaboration.neurflow.adapters.sync_all')
    def test_sync_all(self, mock_sync_all):
        """测试同步所有（委托给 adapters.sync_all）"""
        mock_sync_all.return_value = {
            "tools": 5, "skills": 3, "mcp": 2,
            "comfyui": 12, "commerce": 8, "drama": 8,
        }
        registry = get_node_registry()

        result = registry.sync_all()

        mock_sync_all.assert_called_once_with(registry)
        assert result["tools"] == 5
        assert result["skills"] == 3
        assert result["mcp"] == 2
        assert result["comfyui"] == 12
        assert result["commerce"] == 8
        assert result["drama"] == 8

    # ==================== 边界情况 ====================

    def test_register_empty_type(self):
        """测试注册空类型节点"""
        registry = get_node_registry()
        
        node = NodeDefinition(
            type="",  # 空类型
            label="空类型节点",
            icon="❌",
            category="flow",
            description="空类型节点",
            sub_blocks=[],
            inputs=[],
            outputs=[]
        )
        
        with pytest.raises(ValueError):
            registry.register(node)

    def test_register_none_type(self):
        """测试注册 None 类型节点"""
        registry = get_node_registry()
        
        node = NodeDefinition(
            type=None,  # None 类型
            label="None 类型节点",
            icon="❌",
            category="flow",
            description="None 类型节点",
            sub_blocks=[],
            inputs=[],
            outputs=[]
        )
        
        with pytest.raises(ValueError):
            registry.register(node)

    def test_concurrent_registration(self, sample_node, sample_executor):
        """测试并发注册"""
        import threading
        
        registry = get_node_registry()
        errors = []
        
        def register_node(i):
            try:
                node = NodeDefinition(
                    type=f"tool:concurrent_{i}",
                    label=f"并发工具 {i}",
                    icon="🔧",
                    category="tools",
                    description=f"并发工具 {i}",
                    sub_blocks=[],
                    inputs=[NodePort(id="input", label="输入")],
                    outputs=[NodePort(id="output", label="输出")],
                    source="tool"
                )
                registry.register(node)
            except Exception as e:
                errors.append(e)

        # 创建多个线程
        threads = []
        for i in range(10):
            thread = threading.Thread(target=register_node, args=(i,))
            threads.append(thread)
            thread.start()

        # 等待所有线程完成
        for thread in threads:
            thread.join()

        # 验证
        assert len(errors) == 0
        assert len(registry.list_all()) == 10


if __name__ == "__main__":
    pytest.main([__file__, "-v"])