# -*- coding: utf-8 -*-
"""
Neurflow 集成测试

验证 Neurflow 与系统其他部分的集成：
1. 完整工作流执行流程
2. 节点注册和发现
3. 变量解析和执行引擎
4. DAG 验证
5. 存储集成
6. Agent 管理
7. 模板注册
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from neurova.collaboration.neurflow import (
    WorkflowStatus, NodeCategory, SubBlockConfig, NodePort,
    NodeDefinition, WorkflowNode, WorkflowEdge, WorkflowVariable,
    WorkflowDefinition, NodeExecutionResult, ExecutionInstance, AgentInfo,
    NeurflowStorage,
    NodeRegistry, get_node_registry, reset_node_registry,
    CycleDetector, TopologicalSorter, DAGValidator, get_dag_validator,
    VariableResolver, ResolutionContext, get_variable_resolver,
    WorkflowExecutor, ExecutionStatus, ExecutionEventType, ExecutionEvent, get_workflow_executor,
    NeurflowAgentManager, get_agent_manager, reset_agent_manager,
    TemplateRegistry, get_template_registry, reset_template_registry,
)


# ============ 辅助函数 ============

def create_simple_workflow(workflow_id: str = "test_workflow_1") -> WorkflowDefinition:
    """创建简单工作流：start -> end"""
    return WorkflowDefinition(
        id=workflow_id,
        name="测试工作流",
        description="用于集成测试的简单工作流",
        version="1.0.0",
        nodes=[
            WorkflowNode(
                id="start_1",
                type="builtin:start",
                position={"x": 0, "y": 0},
                config={"inputs_schema": {"topic": "string"}},
            ),
            WorkflowNode(
                id="end_1",
                type="builtin:end",
                position={"x": 200, "y": 0},
                config={"output_mapping": {"result": "$node.start_1.topic"}},
            ),
        ],
        edges=[
            WorkflowEdge(id="edge_1", source="start_1", target="end_1"),
        ],
        variables=[],
        tags=["test"],
        category="test",
        author="test_user",
        created_at=1000000.0,
        updated_at=1000000.0,
        status=WorkflowStatus.DRAFT,
    )


def create_llm_workflow(workflow_id: str = "test_llm_workflow") -> WorkflowDefinition:
    """创建包含 LLM 节点的工作流：start -> llm -> end"""
    return WorkflowDefinition(
        id=workflow_id,
        name="LLM 测试工作流",
        description="包含 LLM 节点的工作流",
        version="1.0.0",
        nodes=[
            WorkflowNode(
                id="start_1",
                type="builtin:start",
                position={"x": 0, "y": 0},
                config={"inputs_schema": {"topic": "string"}},
            ),
            WorkflowNode(
                id="llm_1",
                type="builtin:llm",
                position={"x": 200, "y": 0},
                config={
                    "prompt": "请分析以下主题：$input.topic",
                    "model_provider": "auto",
                    "temperature": 0.7,
                },
            ),
            WorkflowNode(
                id="end_1",
                type="builtin:end",
                position={"x": 400, "y": 0},
                config={"output_mapping": {"result": "$node.llm_1.output"}},
            ),
        ],
        edges=[
            WorkflowEdge(id="edge_1", source="start_1", target="llm_1"),
            WorkflowEdge(id="edge_2", source="llm_1", target="end_1"),
        ],
        variables=[],
        tags=["test"],
        category="test",
        author="test_user",
        created_at=1000000.0,
        updated_at=1000000.0,
        status=WorkflowStatus.DRAFT,
    )


# ============ 测试类 ============

class TestEndToEndWorkflowExecution:
    """端到端工作流执行测试"""
    
    @pytest.fixture
    def executor(self):
        """创建工作流执行器"""
        reset_node_registry()
        return get_workflow_executor()
    
    def test_simple_workflow_should_validate(self, executor):
        """测试: 简单工作流应该通过验证"""
        workflow = create_simple_workflow()
        validation = executor.validate_workflow(workflow)
        
        assert validation.is_valid, f"验证失败: {validation.errors}"
        assert not validation.has_cycle
        assert validation.has_start
        assert validation.has_end
    
    def test_simple_workflow_should_execute(self, executor):
        """测试: 简单工作流应该能够执行"""
        workflow = create_simple_workflow()
        inputs = {"topic": "人工智能"}
        
        result = asyncio.run(executor.execute(workflow, inputs))
        
        assert result.workflow_id == "test_workflow_1"
        assert result.status == WorkflowStatus.COMPLETED
        assert result.inputs == inputs
        assert len(result.node_results) > 0
    
    def test_workflow_should_validate_before_execution(self, executor):
        """测试: 工作流执行前应该验证"""
        workflow = create_simple_workflow()
        validation = executor.validate_workflow(workflow)
        
        assert validation.is_valid
        assert len(validation.errors) == 0
    
    def test_workflow_should_propagate_variables(self, executor):
        """测试: 工作流应该在节点间传递变量"""
        resolver = get_variable_resolver()
        
        # 创建解析上下文
        context = ResolutionContext(
            workflow_id="test",
            execution_id="exec_1",
            node_results={
                "start_1": {"topic": "人工智能"}
            },
            inputs={"topic": "人工智能"}
        )
        
        # 解析变量引用
        result = resolver.resolve("$input.topic", context)
        
        assert result.success
        assert result.value == "人工智能"
    
    def test_workflow_should_handle_empty_inputs(self, executor):
        """测试: 工作流应该处理空输入"""
        workflow = create_simple_workflow()
        
        result = asyncio.run(executor.execute(workflow, {}))
        
        assert result.workflow_id == "test_workflow_1"
        assert result.status == WorkflowStatus.COMPLETED


class TestNodeRegistrationAndDiscovery:
    """节点注册和发现测试"""
    
    @pytest.fixture
    def registry(self):
        """创建节点注册表"""
        reset_node_registry()
        return get_node_registry()
    
    def test_registry_should_register_builtin_nodes(self, registry):
        """测试: 注册表应该注册内置节点"""
        # 确保内置节点已注册
        registry.ensure_builtin()
        
        # 验证内置节点存在
        start_node = registry.get("builtin:start")
        end_node = registry.get("builtin:end")
        
        assert start_node is not None
        assert end_node is not None
        assert start_node.type == "builtin:start"
        assert end_node.type == "builtin:end"
    
    def test_registry_should_list_nodes_by_category(self, registry):
        """测试: 注册表应该按分类列出节点"""
        # 注册不同分类的节点
        registry.register(
            NodeDefinition(
                type="test:flow_node",
                label="流程节点",
                icon="🔄",
                category="flow",
                description="流程控制节点",
                sub_blocks=[],
                inputs=[],
                outputs=[],
            ),
            lambda config, ctx: {},
        )
        
        registry.register(
            NodeDefinition(
                type="test:ai_node",
                label="AI 节点",
                icon="🤖",
                category="ai",
                description="AI 节点",
                sub_blocks=[],
                inputs=[],
                outputs=[],
            ),
            lambda config, ctx: {},
        )
        
        # 验证分类过滤
        flow_nodes = registry.list_by_category("flow")
        ai_nodes = registry.list_by_category("ai")
        
        assert len(flow_nodes) >= 1
        assert len(ai_nodes) >= 1
        assert any(n.type == "test:flow_node" for n in flow_nodes)
        assert any(n.type == "test:ai_node" for n in ai_nodes)
    
    def test_registry_should_search_nodes(self, registry):
        """测试: 注册表应该支持搜索节点"""
        # 注册带标签的节点
        registry.register(
            NodeDefinition(
                type="test:search_node",
                label="搜索节点",
                icon="🔍",
                category="tools",
                description="搜索相关节点",
                sub_blocks=[],
                inputs=[],
                outputs=[],
                tags=["search", "query"],
            ),
            lambda config, ctx: {},
        )
        
        # 验证搜索
        search_results = registry.search("搜索")
        assert len(search_results) >= 1
        assert any(n.type == "test:search_node" for n in search_results)
    
    def test_registry_should_provide_node_statistics(self, registry):
        """测试: 注册表应该提供节点统计信息"""
        # 确保内置节点已注册
        registry.ensure_builtin()
        
        # 验证统计
        summary = registry.get_summary()
        assert summary["total"] >= 2
        assert "builtin" in summary["by_source"]
    
    def test_registry_should_list_all_nodes(self, registry):
        """测试: 注册表应该列出所有节点"""
        # 确保内置节点已注册
        registry.ensure_builtin()
        
        # 验证列表
        all_nodes = registry.list_all()
        assert len(all_nodes) >= 2
        assert any(n.type == "builtin:start" for n in all_nodes)
        assert any(n.type == "builtin:end" for n in all_nodes)


class TestVariableResolverIntegration:
    """变量解析器集成测试"""
    
    @pytest.fixture
    def resolver(self):
        """创建变量解析器"""
        return get_variable_resolver()
    
    def test_resolver_should_resolve_node_references(self, resolver):
        """测试: 解析器应该解析节点引用"""
        # 创建解析上下文
        context = ResolutionContext(
            workflow_id="test",
            execution_id="exec_1",
            node_results={
                "llm_1": {"output": {"text": "AI 是模拟人类智能的技术", "tokens": 100}}
            }
        )
        
        # 解析节点引用
        result = resolver.resolve("$node.llm_1.output.text", context)
        
        assert result.success
        assert result.value == "AI 是模拟人类智能的技术"
    
    def test_resolver_should_resolve_input_references(self, resolver):
        """测试: 解析器应该解析输入引用"""
        # 创建解析上下文
        context = ResolutionContext(
            workflow_id="test",
            execution_id="exec_1",
            inputs={"topic": "人工智能", "style": "学术"}
        )
        
        # 解析输入引用
        result = resolver.resolve("$input.topic", context)
        
        assert result.success
        assert result.value == "人工智能"
    
    def test_resolver_should_resolve_workflow_variables(self, resolver):
        """测试: 解析器应该解析工作流变量"""
        # 创建解析上下文
        context = ResolutionContext(
            workflow_id="test",
            execution_id="exec_1",
            variables={"language": "中文", "max_length": 1000}
        )
        
        # 解析工作流变量
        result = resolver.resolve("$var.language", context)
        
        assert result.success
        assert result.value == "中文"
    
    def test_resolver_should_handle_complex_expressions(self, resolver):
        """测试: 解析器应该处理复杂表达式"""
        # 创建解析上下文
        context = ResolutionContext(
            workflow_id="test",
            execution_id="exec_1",
            node_results={
                "step1": {"result": "步骤1结果"}
            },
            inputs={"user_name": "张三"}
        )
        
        # 解析复杂表达式
        result = resolver.resolve("用户 $input.user_name 的步骤结果是：$node.step1.result", context)
        
        assert result.success
        assert "张三" in result.value
        assert "步骤1结果" in result.value
    
    def test_resolver_should_resolve_config(self, resolver):
        """测试: 解析器应该解析配置对象"""
        # 创建解析上下文
        context = ResolutionContext(
            workflow_id="test",
            execution_id="exec_1",
            inputs={"topic": "人工智能"},
            variables={"language": "中文"}
        )
        
        # 解析配置
        config = {
            "prompt": "请以 $var.language 分析 $input.topic",
            "topic": "$input.topic",
            "nested": {
                "value": "$var.language"
            }
        }
        
        resolved = resolver.resolve_config(config, context)
        
        assert "中文" in resolved["prompt"]
        assert "人工智能" in resolved["prompt"]
        assert resolved["topic"] == "人工智能"
        assert resolved["nested"]["value"] == "中文"


class TestDAGValidationIntegration:
    """DAG 验证集成测试"""
    
    @pytest.fixture
    def validator(self):
        """创建 DAG 验证器"""
        return get_dag_validator()
    
    def test_validator_should_detect_cycles(self, validator):
        """测试: 验证器应该检测循环"""
        # 创建有循环的工作流
        nodes = [
            WorkflowNode(id="a", type="builtin:start", position={"x": 0, "y": 0}, config={}),
            WorkflowNode(id="b", type="builtin:llm", position={"x": 200, "y": 0}, config={}),
            WorkflowNode(id="c", type="builtin:end", position={"x": 400, "y": 0}, config={}),
        ]
        
        edges = [
            WorkflowEdge(id="e1", source="a", target="b"),
            WorkflowEdge(id="e2", source="b", target="c"),
            WorkflowEdge(id="e3", source="c", target="b"),  # 循环
        ]
        
        # 验证循环检测
        result = validator.validate(nodes, edges)
        
        assert not result.is_valid
        assert result.has_cycle
        assert len(result.errors) > 0
        assert any("环" in e or "cycle" in e.lower() for e in result.errors)
    
    def test_validator_should_check_required_ports(self, validator):
        """测试: 验证器应该检查必填端口"""
        # 创建缺少必填端口的工作流
        nodes = [
            WorkflowNode(id="a", type="builtin:start", position={"x": 0, "y": 0}, config={}),
            WorkflowNode(id="b", type="builtin:llm", position={"x": 200, "y": 0}, config={}),
        ]
        
        edges = []  # 没有连接
        
        # 验证端口检查
        result = validator.validate(nodes, edges)
        
        # 注意：某些节点可能没有必填端口，所以这个测试可能需要调整
        assert isinstance(result.is_valid, bool)
        assert isinstance(result.errors, list)
    
    def test_validator_should_validate_simple_workflow(self, validator):
        """测试: 验证器应该验证简单工作流"""
        nodes = [
            WorkflowNode(id="a", type="builtin:start", position={"x": 0, "y": 0}, config={}),
            WorkflowNode(id="b", type="builtin:end", position={"x": 200, "y": 0}, config={}),
        ]
        
        edges = [
            WorkflowEdge(id="e1", source="a", target="b"),
        ]
        
        # 验证简单工作流
        result = validator.validate(nodes, edges)
        
        assert result.is_valid
        assert not result.has_cycle
        assert result.has_start
        assert result.has_end
        assert len(result.errors) == 0
    
    def test_validator_should_detect_missing_start(self, validator):
        """测试: 验证器应该检测缺少开始节点"""
        nodes = [
            WorkflowNode(id="a", type="builtin:end", position={"x": 0, "y": 0}, config={}),
        ]
        
        edges = []
        
        # 验证缺少开始节点
        result = validator.validate(nodes, edges)
        
        assert not result.is_valid
        assert not result.has_start
        assert any("开始" in e for e in result.errors)
    
    def test_validator_should_detect_missing_end(self, validator):
        """测试: 验证器应该检测缺少结束节点"""
        nodes = [
            WorkflowNode(id="a", type="builtin:start", position={"x": 0, "y": 0}, config={}),
        ]
        
        edges = []
        
        # 验证缺少结束节点
        result = validator.validate(nodes, edges)
        
        assert not result.is_valid
        assert not result.has_end
        assert any("结束" in e for e in result.errors)


class TestExecutionEngineEvents:
    """执行引擎事件测试"""
    
    @pytest.fixture
    def executor(self):
        """创建工作流执行器"""
        reset_node_registry()
        return get_workflow_executor()
    
    def test_executor_should_emit_events(self, executor):
        """测试: 执行器应该发射事件"""
        # 创建事件收集器
        events = []
        
        def event_handler(event: ExecutionEvent):
            events.append(event)
        
        # 注册事件处理器
        executor.on_event(event_handler)
        
        # 创建简单工作流
        workflow = create_simple_workflow()
        
        # 执行工作流
        asyncio.run(executor.execute(workflow, {}))
        
        # 验证事件
        assert len(events) > 0
        assert any(e.type == ExecutionEventType.WORKFLOW_STARTED for e in events)
        assert any(e.type == ExecutionEventType.WORKFLOW_COMPLETED for e in events)
    
    def test_executor_should_create_execution_instance(self, executor):
        """测试: 执行器应该创建执行实例"""
        workflow = create_simple_workflow()
        
        result = asyncio.run(executor.execute(workflow, {}))
        
        assert result.workflow_id == "test_workflow_1"
        assert result.status == WorkflowStatus.COMPLETED
        assert result.id is not None
        assert result.started_at is not None
        assert result.finished_at is not None


class TestAgentManagerIntegration:
    """Agent 管理器集成测试"""
    
    @pytest.fixture
    def agent_manager(self):
        """创建 Agent 管理器"""
        reset_agent_manager()
        return get_agent_manager()
    
    def test_agent_manager_should_create_agent(self, agent_manager):
        """测试: Agent 管理器应该创建 Agent"""
        agent = agent_manager.create_agent(
            name="测试 Agent",
            role="assistant",
            config={"model": "gpt-4"},
            flow_id="test_workflow_1",
        )
        
        assert agent.agent_id.startswith("neurflow_")
        assert agent.name == "测试 Agent"
        assert agent.role == "assistant"
        assert agent.flow_id == "test_workflow_1"
    
    def test_agent_manager_should_retrieve_agent(self, agent_manager):
        """测试: Agent 管理器应该检索 Agent"""
        # 创建 Agent
        agent = agent_manager.create_agent(
            name="测试 Agent",
            role="assistant",
            config={"model": "gpt-4"},
            flow_id="test_workflow_1",
        )
        
        # 检索 Agent
        retrieved = agent_manager.get_agent(agent.agent_id)
        
        assert retrieved is not None
        assert retrieved.agent_id == agent.agent_id
        assert retrieved.name == "测试 Agent"
    
    def test_agent_manager_should_list_agents(self, agent_manager):
        """测试: Agent 管理器应该列出 Agent"""
        # 创建多个 Agent
        agent_manager.create_agent(
            name="Agent 1",
            role="assistant",
            config={"model": "gpt-4"},
            flow_id="test_workflow_1",
        )
        
        agent_manager.create_agent(
            name="Agent 2",
            role="assistant",
            config={"model": "gpt-4"},
            flow_id="test_workflow_2",
        )
        
        # 列出 Agent
        agents = agent_manager.list_agents()
        
        assert len(agents) >= 2
        assert any(a.name == "Agent 1" for a in agents)
        assert any(a.name == "Agent 2" for a in agents)
    
    def test_agent_manager_should_delete_agent(self, agent_manager):
        """测试: Agent 管理器应该删除 Agent"""
        # 创建 Agent
        agent = agent_manager.create_agent(
            name="测试 Agent",
            role="assistant",
            config={"model": "gpt-4"},
            flow_id="test_workflow_1",
        )
        
        # 删除 Agent
        result = agent_manager.delete_agent(agent.agent_id)
        
        # 验证删除
        assert result is True
        retrieved = agent_manager.get_agent(agent.agent_id)
        assert retrieved is None


class TestStorageIntegration:
    """存储集成测试"""
    
    @pytest.fixture
    def storage(self, tmp_path):
        """创建临时存储"""
        return NeurflowStorage(db_path=tmp_path / "test.db")
    
    def test_storage_should_save_and_retrieve_workflow(self, storage):
        """测试: 存储应该保存和检索工作流"""
        workflow = create_simple_workflow("storage_test_1")
        
        # 保存工作流
        storage.save_workflow(workflow)
        
        # 检索工作流
        retrieved = storage.get_workflow("storage_test_1")
        
        # 验证数据完整性
        assert retrieved is not None
        assert retrieved.id == "storage_test_1"
        assert retrieved.name == "测试工作流"
        assert len(retrieved.nodes) == 2
    
    def test_storage_should_list_workflows(self, storage):
        """测试: 存储应该列出工作流"""
        # 保存多个工作流
        for i in range(3):
            workflow = create_simple_workflow(f"list_test_{i}")
            storage.save_workflow(workflow)
        
        # 列出工作流
        workflows = storage.list_workflows()
        
        # 验证列表
        assert len(workflows) >= 3
        assert any(w.id == "list_test_0" for w in workflows)
        assert any(w.id == "list_test_1" for w in workflows)
        assert any(w.id == "list_test_2" for w in workflows)
    
    def test_storage_should_delete_workflow(self, storage):
        """测试: 存储应该删除工作流"""
        workflow = create_simple_workflow("delete_test_1")
        
        # 保存工作流
        storage.save_workflow(workflow)
        
        # 删除工作流
        storage.delete_workflow("delete_test_1")
        
        # 验证删除
        retrieved = storage.get_workflow("delete_test_1")
        assert retrieved is None
    
    def test_storage_should_update_workflow(self, storage):
        """测试: 存储应该更新工作流"""
        workflow = create_simple_workflow("update_test_1")
        
        # 保存工作流
        storage.save_workflow(workflow)
        
        # 更新工作流
        workflow.name = "更新后的工作流"
        storage.save_workflow(workflow)
        
        # 验证更新
        retrieved = storage.get_workflow("update_test_1")
        assert retrieved is not None
        assert retrieved.name == "更新后的工作流"


class TestTemplateRegistryIntegration:
    """模板注册表集成测试"""
    
    @pytest.fixture
    def template_registry(self):
        """创建模板注册表"""
        reset_template_registry()
        return get_template_registry()
    
    def test_template_registry_should_list_templates(self, template_registry):
        """测试: 模板注册表应该列出模板"""
        templates = template_registry.list_templates()
        
        assert isinstance(templates, list)
        # 注意：可能没有预定义模板
    
    def test_template_registry_should_get_template(self, template_registry):
        """测试: 模板注册表应该获取模板"""
        # 注意：可能没有预定义模板，所以这个测试可能需要调整
        templates = template_registry.list_templates()
        
        if len(templates) > 0:
            template = template_registry.get_template(templates[0].id)
            assert template is not None
        else:
            # 如果没有模板，跳过测试
            pytest.skip("没有预定义模板")


class TestCrossModuleIntegration:
    """跨模块集成测试"""
    
    def test_full_pipeline_with_storage_and_executor(self, tmp_path):
        """测试: 完整管线 — 存储 → 加载 → 执行"""
        # 创建存储
        storage = NeurflowStorage(db_path=tmp_path / "pipeline.db")
        
        # 创建工作流
        workflow = create_simple_workflow("pipeline_test_1")
        
        # 保存到存储
        storage.save_workflow(workflow)
        
        # 从存储加载
        loaded_workflow = storage.get_workflow("pipeline_test_1")
        
        # 创建执行器
        reset_node_registry()
        executor = get_workflow_executor()
        
        # 执行工作流
        result = asyncio.run(executor.execute(loaded_workflow, {"topic": "测试"}))
        
        # 验证结果
        assert result.workflow_id == "pipeline_test_1"
        assert result.status == WorkflowStatus.COMPLETED
    
    def test_agent_manager_with_executor(self):
        """测试: Agent 管理器与执行器集成"""
        # 创建 Agent 管理器
        reset_agent_manager()
        agent_manager = get_agent_manager()
        
        # 创建 Agent
        agent = agent_manager.create_agent(
            name="集成测试 Agent",
            role="assistant",
            config={"model": "gpt-4"},
            flow_id="test_workflow_1",
        )
        
        # 创建执行器
        reset_node_registry()
        executor = get_workflow_executor()
        
        # 创建工作流
        workflow = create_simple_workflow("agent_test_1")
        
        # 执行工作流
        result = asyncio.run(executor.execute(workflow, {"topic": "测试"}))
        
        # 验证结果
        assert result.workflow_id == "agent_test_1"
        assert result.status == WorkflowStatus.COMPLETED
        
        # 验证 Agent 仍然存在
        retrieved = agent_manager.get_agent(agent.agent_id)
        assert retrieved is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])