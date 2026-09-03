"""
Neurflow 存储层测试 — 垂直切片 2
测试 SQLite 持久化 CRUD 操作
"""
import pytest
import tempfile
import os
from neurova.collaboration.neurflow.models import (
    WorkflowDefinition, WorkflowNode, WorkflowEdge, WorkflowVariable,
    WorkflowStatus, NodeDefinition, SubBlockConfig, NodePort, NodeCategory,
    ExecutionInstance, NodeExecutionResult, AgentInfo
)
from neurova.collaboration.neurflow.storage import NeurflowStorage


class TestNeurflowStorage:
    """NeurflowStorage CRUD 测试"""

    @pytest.fixture
    def storage(self):
        """创建临时存储实例"""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            storage = NeurflowStorage(db_path)
            yield storage
        finally:
            storage.close()
            os.unlink(db_path)

    @pytest.fixture
    def sample_workflow(self):
        """示例工作流数据"""
        return WorkflowDefinition(
            id="wf_test_001",
            name="测试工作流",
            description="用于测试的工作流",
            version="1.0.0",
            nodes=[
                WorkflowNode(
                    id="start_1",
                    type="builtin:start",
                    position={"x": 0, "y": 0},
                    config={},
                    label="开始"
                ),
                WorkflowNode(
                    id="llm_1",
                    type="builtin:llm",
                    position={"x": 100, "y": 0},
                    config={"prompt": "Hello"},
                    label="LLM 节点"
                )
            ],
            edges=[
                WorkflowEdge(id="edge_1", source="start_1", target="llm_1")
            ],
            variables=[
                WorkflowVariable(name="topic", type="string", default_value="AI")
            ],
            tags=["test"],
            category="programming",
            author="test_user",
            created_at=1717833600.0,
            updated_at=1717833600.0,
            status=WorkflowStatus.DRAFT
        )

    @pytest.fixture
    def sample_node_definition(self):
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

    # ==================== 工作流 CRUD ====================

    def test_save_and_get_workflow(self, storage, sample_workflow):
        """测试保存和获取工作流"""
        # 保存
        result = storage.save_workflow(sample_workflow)
        assert result is True

        # 获取
        retrieved = storage.get_workflow("wf_test_001")
        assert retrieved is not None
        assert retrieved.id == "wf_test_001"
        assert retrieved.name == "测试工作流"
        assert retrieved.description == "用于测试的工作流"
        assert retrieved.version == "1.0.0"
        assert len(retrieved.nodes) == 2
        assert len(retrieved.edges) == 1
        assert len(retrieved.variables) == 1
        assert retrieved.status == WorkflowStatus.DRAFT

    def test_save_workflow_update(self, storage, sample_workflow):
        """测试更新工作流"""
        # 保存原始
        storage.save_workflow(sample_workflow)

        # 更新
        sample_workflow.name = "更新后的工作流"
        sample_workflow.status = WorkflowStatus.PUBLISHED
        sample_workflow.updated_at = 1717833700.0
        storage.save_workflow(sample_workflow)

        # 验证更新
        retrieved = storage.get_workflow("wf_test_001")
        assert retrieved.name == "更新后的工作流"
        assert retrieved.status == WorkflowStatus.PUBLISHED
        assert retrieved.updated_at == 1717833700.0

    def test_get_workflow_not_found(self, storage):
        """测试获取不存在的工作流"""
        result = storage.get_workflow("nonexistent")
        assert result is None

    def test_delete_workflow(self, storage, sample_workflow):
        """测试删除工作流"""
        # 保存
        storage.save_workflow(sample_workflow)
        assert storage.get_workflow("wf_test_001") is not None

        # 删除
        result = storage.delete_workflow("wf_test_001")
        assert result is True

        # 验证删除
        assert storage.get_workflow("wf_test_001") is None

    def test_delete_workflow_not_found(self, storage):
        """测试删除不存在的工作流"""
        result = storage.delete_workflow("nonexistent")
        assert result is False

    def test_list_workflows(self, storage, sample_workflow):
        """测试列出工作流"""
        # 保存多个工作流
        storage.save_workflow(sample_workflow)
        
        workflow2 = WorkflowDefinition(
            id="wf_test_002",
            name="第二个工作流",
            description="另一个测试工作流",
            version="1.0.0",
            nodes=[],
            edges=[],
            variables=[],
            tags=["test2"],
            category="data",
            author="test_user",
            created_at=1717833600.0,
            updated_at=1717833600.0,
            status=WorkflowStatus.PUBLISHED
        )
        storage.save_workflow(workflow2)

        # 列出所有
        workflows = storage.list_workflows()
        assert len(workflows) == 2

        # 按分类过滤
        programming_workflows = storage.list_workflows(category="programming")
        assert len(programming_workflows) == 1
        assert programming_workflows[0].id == "wf_test_001"

        # 按状态过滤
        published_workflows = storage.list_workflows(status=WorkflowStatus.PUBLISHED)
        assert len(published_workflows) == 1
        assert published_workflows[0].id == "wf_test_002"

        # 按作者过滤
        user_workflows = storage.list_workflows(author="test_user")
        assert len(user_workflows) == 2

    def test_list_workflows_pagination(self, storage):
        """测试工作流分页"""
        # 创建多个工作流
        for i in range(10):
            workflow = WorkflowDefinition(
                id=f"wf_page_{i}",
                name=f"工作流 {i}",
                description=f"测试工作流 {i}",
                version="1.0.0",
                nodes=[],
                edges=[],
                variables=[],
                tags=[],
                category="general",
                author="test_user",
                created_at=1717833600.0 + i,
                updated_at=1717833600.0 + i,
                status=WorkflowStatus.DRAFT
            )
            storage.save_workflow(workflow)

        # 测试分页
        page1 = storage.list_workflows(limit=3, offset=0)
        assert len(page1) == 3

        page2 = storage.list_workflows(limit=3, offset=3)
        assert len(page2) == 3

        page3 = storage.list_workflows(limit=3, offset=6)
        assert len(page3) == 3

        page4 = storage.list_workflows(limit=3, offset=9)
        assert len(page4) == 1

    def test_search_workflows(self, storage, sample_workflow):
        """测试搜索工作流"""
        storage.save_workflow(sample_workflow)

        # 按名称搜索
        results = storage.search_workflows("测试")
        assert len(results) == 1
        assert results[0].id == "wf_test_001"

        # 按描述搜索
        results = storage.search_workflows("用于测试")
        assert len(results) == 1

        # 按标签搜索
        results = storage.search_workflows("test")
        assert len(results) == 1

        # 无结果搜索
        results = storage.search_workflows("不存在")
        assert len(results) == 0

    # ==================== 节点定义 CRUD ====================

    def test_save_and_get_node_definition(self, storage, sample_node_definition):
        """测试保存和获取节点定义"""
        # 保存
        result = storage.save_node_definition(sample_node_definition)
        assert result is True

        # 获取
        retrieved = storage.get_node_definition("tool:web_search")
        assert retrieved is not None
        assert retrieved.type == "tool:web_search"
        assert retrieved.label == "网页搜索"
        assert retrieved.icon == "🔍"
        assert retrieved.category == "tools"
        assert retrieved.description == "搜索网页内容"
        assert len(retrieved.sub_blocks) == 1
        assert len(retrieved.inputs) == 1
        assert len(retrieved.outputs) == 2
        assert retrieved.source == "tool"
        assert retrieved.source_id == "web_search"

    def test_save_node_definition_update(self, storage, sample_node_definition):
        """测试更新节点定义"""
        # 保存原始
        storage.save_node_definition(sample_node_definition)

        # 更新
        sample_node_definition.label = "网页搜索（更新）"
        sample_node_definition.version = "1.1.0"
        storage.save_node_definition(sample_node_definition)

        # 验证更新
        retrieved = storage.get_node_definition("tool:web_search")
        assert retrieved.label == "网页搜索（更新）"
        assert retrieved.version == "1.1.0"

    def test_get_node_definition_not_found(self, storage):
        """测试获取不存在的节点定义"""
        result = storage.get_node_definition("nonexistent:tool")
        assert result is None

    def test_delete_node_definition(self, storage, sample_node_definition):
        """测试删除节点定义"""
        # 保存
        storage.save_node_definition(sample_node_definition)
        assert storage.get_node_definition("tool:web_search") is not None

        # 删除
        result = storage.delete_node_definition("tool:web_search")
        assert result is True

        # 验证删除
        assert storage.get_node_definition("tool:web_search") is None

    def test_delete_node_definition_not_found(self, storage):
        """测试删除不存在的节点定义"""
        result = storage.delete_node_definition("nonexistent:tool")
        assert result is False

    def test_list_node_definitions(self, storage, sample_node_definition):
        """测试列出节点定义"""
        # 保存多个节点定义
        storage.save_node_definition(sample_node_definition)
        
        node_def2 = NodeDefinition(
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
        storage.save_node_definition(node_def2)

        # 列出所有
        nodes = storage.list_node_definitions()
        assert len(nodes) == 2

        # 按分类过滤
        tool_nodes = storage.list_node_definitions(category="tools")
        assert len(tool_nodes) == 1
        assert tool_nodes[0].type == "tool:web_search"

        # 按来源过滤
        builtin_nodes = storage.list_node_definitions(source="builtin")
        assert len(builtin_nodes) == 1
        assert builtin_nodes[0].type == "builtin:condition"

    def test_search_node_definitions(self, storage, sample_node_definition):
        """测试搜索节点定义"""
        storage.save_node_definition(sample_node_definition)

        # 按标签搜索
        results = storage.search_node_definitions("search")
        assert len(results) == 1
        assert results[0].type == "tool:web_search"

        # 按描述搜索
        results = storage.search_node_definitions("搜索网页")
        assert len(results) == 1

        # 无结果搜索
        results = storage.search_node_definitions("不存在")
        assert len(results) == 0

    # ==================== 执行实例 CRUD ====================

    def test_save_and_get_execution(self, storage, sample_workflow):
        """测试保存和获取执行实例"""
        # 先创建工作流（满足外键约束）
        storage.save_workflow(sample_workflow)
        
        execution = ExecutionInstance(
            id="exec_001",
            workflow_id="wf_test_001",
            status=WorkflowStatus.RUNNING,
            inputs={"topic": "AI"},
            outputs=None,
            node_results={},
            variables={"style": "formal"},
            started_at=1717833600.0,
            agent_id="agent_1",
            user_id="user_1",
            metadata={"source": "api"}
        )

        # 保存
        result = storage.save_execution(execution)
        assert result is True

        # 获取
        retrieved = storage.get_execution("exec_001")
        assert retrieved is not None
        assert retrieved.id == "exec_001"
        assert retrieved.workflow_id == "wf_test_001"
        assert retrieved.status == WorkflowStatus.RUNNING
        assert retrieved.inputs == {"topic": "AI"}
        assert retrieved.outputs is None
        assert retrieved.variables == {"style": "formal"}
        assert retrieved.agent_id == "agent_1"
        assert retrieved.user_id == "user_1"

    def test_save_execution_update(self, storage, sample_workflow):
        """测试更新执行实例"""
        # 先创建工作流（满足外键约束）
        storage.save_workflow(sample_workflow)
        
        execution = ExecutionInstance(
            id="exec_002",
            workflow_id="wf_test_001",
            status=WorkflowStatus.RUNNING,
            inputs={"topic": "AI"}
        )

        # 保存原始
        storage.save_execution(execution)

        # 更新
        execution.status = WorkflowStatus.COMPLETED
        execution.outputs = {"result": "Hello"}
        execution.finished_at = 1717833700.0
        execution.duration = 100.0
        storage.save_execution(execution)

        # 验证更新
        retrieved = storage.get_execution("exec_002")
        assert retrieved.status == WorkflowStatus.COMPLETED
        assert retrieved.outputs == {"result": "Hello"}
        assert retrieved.finished_at == 1717833700.0
        assert retrieved.duration == 100.0

    def test_get_execution_not_found(self, storage):
        """测试获取不存在的执行实例"""
        result = storage.get_execution("nonexistent")
        assert result is None

    def test_list_executions(self, storage, sample_workflow):
        """测试列出执行实例"""
        # 先创建工作流（满足外键约束）
        storage.save_workflow(sample_workflow)
        
        # 创建多个执行实例
        for i in range(5):
            execution = ExecutionInstance(
                id=f"exec_list_{i}",
                workflow_id="wf_test_001",
                status=WorkflowStatus.COMPLETED if i % 2 == 0 else WorkflowStatus.FAILED,
                inputs={"topic": f"topic_{i}"},
                started_at=1717833600.0 + i,
                user_id="user_1"
            )
            storage.save_execution(execution)

        # 列出所有
        executions = storage.list_executions()
        assert len(executions) == 5

        # 按工作流过滤
        wf_executions = storage.list_executions(workflow_id="wf_test_001")
        assert len(wf_executions) == 5

        # 按状态过滤
        completed_executions = storage.list_executions(status=WorkflowStatus.COMPLETED)
        assert len(completed_executions) == 3  # 0, 2, 4

        # 按用户过滤
        user_executions = storage.list_executions(user_id="user_1")
        assert len(user_executions) == 5

    def test_list_executions_pagination(self, storage, sample_workflow):
        """测试执行实例分页"""
        # 先创建工作流（满足外键约束）
        storage.save_workflow(sample_workflow)
        
        # 创建多个执行实例
        for i in range(10):
            execution = ExecutionInstance(
                id=f"exec_page_{i}",
                workflow_id="wf_test_001",
                status=WorkflowStatus.COMPLETED,
                inputs={},
                started_at=1717833600.0 + i
            )
            storage.save_execution(execution)

        # 测试分页
        page1 = storage.list_executions(limit=3, offset=0)
        assert len(page1) == 3

        page2 = storage.list_executions(limit=3, offset=3)
        assert len(page2) == 3

        page3 = storage.list_executions(limit=3, offset=6)
        assert len(page3) == 3

        page4 = storage.list_executions(limit=3, offset=9)
        assert len(page4) == 1

    # ==================== Agent CRUD ====================

    def test_save_and_get_agent(self, storage):
        """测试保存和获取 Agent"""
        agent = AgentInfo(
            agent_id="neurflow_agent_001",
            name="编程助手",
            role="developer",
            config={"model": "gpt-4"},
            flow_id="wf_test_001",
            created_at=1717833600.0,
            status="active",
            capabilities=["coding", "testing"],
            metadata={"source": "workflow"}
        )

        # 保存
        result = storage.save_agent(agent)
        assert result is True

        # 获取
        retrieved = storage.get_agent("neurflow_agent_001")
        assert retrieved is not None
        assert retrieved.agent_id == "neurflow_agent_001"
        assert retrieved.name == "编程助手"
        assert retrieved.role == "developer"
        assert retrieved.config == {"model": "gpt-4"}
        assert retrieved.flow_id == "wf_test_001"
        assert retrieved.status == "active"
        assert retrieved.capabilities == ["coding", "testing"]

    def test_save_agent_update(self, storage):
        """测试更新 Agent"""
        agent = AgentInfo(
            agent_id="neurflow_agent_002",
            name="测试 Agent",
            role="tester"
        )

        # 保存原始
        storage.save_agent(agent)

        # 更新
        agent.status = "archived"
        agent.archived_at = 1717833700.0
        agent.metadata = {"archived_reason": "workflow_completed"}
        storage.save_agent(agent)

        # 验证更新
        retrieved = storage.get_agent("neurflow_agent_002")
        assert retrieved.status == "archived"
        assert retrieved.archived_at == 1717833700.0
        assert retrieved.metadata == {"archived_reason": "workflow_completed"}

    def test_get_agent_not_found(self, storage):
        """测试获取不存在的 Agent"""
        result = storage.get_agent("nonexistent")
        assert result is None

    def test_list_agents(self, storage):
        """测试列出 Agent"""
        # 创建多个 Agent（agents 表没有外键约束，可以直接创建）
        for i in range(3):
            agent = AgentInfo(
                agent_id=f"neurflow_agent_list_{i}",
                name=f"Agent {i}",
                role="developer" if i % 2 == 0 else "tester",
                flow_id="wf_test_001" if i < 2 else "wf_test_002",
                status="active" if i < 2 else "archived"
            )
            storage.save_agent(agent)

        # 列出所有（默认不包含归档）
        agents = storage.list_agents()
        assert len(agents) == 2  # 只有 active 的

        # 按工作流过滤
        wf_agents = storage.list_agents(flow_id="wf_test_001")
        assert len(wf_agents) == 2

        # 按状态过滤
        active_agents = storage.list_agents(status="active")
        assert len(active_agents) == 2

        # 包含归档
        all_agents = storage.list_agents(include_archived=True)
        assert len(all_agents) == 3

    def test_delete_agent(self, storage):
        """测试删除 Agent"""
        agent = AgentInfo(
            agent_id="neurflow_agent_delete",
            name="待删除 Agent",
            role="developer"
        )

        # 保存
        storage.save_agent(agent)
        assert storage.get_agent("neurflow_agent_delete") is not None

        # 删除
        result = storage.delete_agent("neurflow_agent_delete")
        assert result is True

        # 验证删除
        assert storage.get_agent("neurflow_agent_delete") is None

    def test_delete_agent_not_found(self, storage):
        """测试删除不存在的 Agent"""
        result = storage.delete_agent("nonexistent")
        assert result is False

    # ==================== 统计和清理 ====================

    def test_get_statistics(self, storage, sample_workflow, sample_node_definition):
        """测试获取统计信息"""
        # 添加一些数据
        storage.save_workflow(sample_workflow)
        storage.save_node_definition(sample_node_definition)
        
        execution = ExecutionInstance(
            id="exec_stats",
            workflow_id="wf_test_001",
            status=WorkflowStatus.COMPLETED,
            inputs={},
            started_at=1717833600.0
        )
        storage.save_execution(execution)

        agent = AgentInfo(
            agent_id="neurflow_agent_stats",
            name="统计 Agent",
            role="developer"
        )
        storage.save_agent(agent)

        # 获取统计
        stats = storage.get_statistics()
        assert stats["workflows"] == 1
        assert stats["node_definitions"] == 1
        assert stats["executions"] == 1
        assert stats["agents"] == 1

    def test_cleanup_old_executions(self, storage, sample_workflow):
        """测试清理旧执行记录"""
        import time
        
        # 先创建工作流（满足外键约束）
        storage.save_workflow(sample_workflow)
        
        # 创建新旧执行记录
        now = time.time()
        old_execution = ExecutionInstance(
            id="exec_old",
            workflow_id="wf_test_001",
            status=WorkflowStatus.COMPLETED,
            inputs={},
            started_at=now - 86400 * 31  # 31天前（确保超过30天）
        )
        storage.save_execution(old_execution)

        new_execution = ExecutionInstance(
            id="exec_new",
            workflow_id="wf_test_001",
            status=WorkflowStatus.COMPLETED,
            inputs={},
            started_at=now  # 现在
        )
        storage.save_execution(new_execution)

        # 清理30天前的记录
        deleted_count = storage.cleanup_old_executions(days=30)
        assert deleted_count == 1

        # 验证
        assert storage.get_execution("exec_old") is None
        assert storage.get_execution("exec_new") is not None

    # ==================== 错误处理 ====================

    def test_save_workflow_invalid_data(self, storage):
        """测试保存无效工作流数据"""
        # 创建一个没有 id 的工作流
        invalid_workflow = WorkflowDefinition(
            id="",  # 空 id
            name="无效工作流",
            description="",
            version="1.0.0",
            nodes=[],
            edges=[],
            variables=[],
            tags=[],
            category="general",
            author="test",
            created_at=0,
            updated_at=0,
            status=WorkflowStatus.DRAFT
        )

        # 应该抛出异常或返回 False
        with pytest.raises(ValueError):
            storage.save_workflow(invalid_workflow)

    def test_concurrent_access(self, storage):
        """测试并发访问（简单测试）"""
        import threading
        
        results = []
        errors = []
        
        def save_workflow(i):
            try:
                workflow = WorkflowDefinition(
                    id=f"wf_concurrent_{i}",
                    name=f"并发工作流 {i}",
                    description="",
                    version="1.0.0",
                    nodes=[],
                    edges=[],
                    variables=[],
                    tags=[],
                    category="general",
                    author="test",
                    created_at=0,
                    updated_at=0,
                    status=WorkflowStatus.DRAFT
                )
                storage.save_workflow(workflow)
                results.append(i)
            except Exception as e:
                errors.append(e)

        # 创建多个线程
        threads = []
        for i in range(5):
            thread = threading.Thread(target=save_workflow, args=(i,))
            threads.append(thread)
            thread.start()

        # 等待所有线程完成
        for thread in threads:
            thread.join()

        # 验证
        assert len(errors) == 0
        assert len(results) == 5
        
        # 验证所有工作流都保存成功
        for i in range(5):
            workflow = storage.get_workflow(f"wf_concurrent_{i}")
            assert workflow is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])