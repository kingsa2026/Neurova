"""
Neurflow API 端点测试 — 垂直切片 8
测试所有 RESTful API 端点
"""
import pytest
import time
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.collaboration.neurflow.models import (
    WorkflowDefinition, WorkflowNode, WorkflowEdge, WorkflowVariable,
    WorkflowStatus, ExecutionInstance, NodeExecutionResult, AgentInfo
)
from neurova.collaboration.neurflow.storage import NeurflowStorage
from neurova.collaboration.neurflow.node_registry import NodeRegistry, get_node_registry
from neurova.collaboration.neurflow.execution_engine import WorkflowExecutor, get_workflow_executor


def _make_node_def(type, label, category="ai", source="builtin"):
    """创建节点定义 Mock"""
    return Mock(type=type, label=label, icon="", category=category,
                description="", source=source, version="1.0.0", tags=[],
                sub_blocks=[], inputs=[], outputs=[])


def _make_workflow(id="wf_001", name="测试工作流", template=False, status=WorkflowStatus.DRAFT):
    """创建工作流定义"""
    return WorkflowDefinition(
        id=id, name=name, description="测试描述", version="1.0.0",
        nodes=[
            WorkflowNode(id="n1", type="builtin:start", position={"x": 0, "y": 0}, config={}),
            WorkflowNode(id="n2", type="builtin:end", position={"x": 100, "y": 0}, config={})
        ],
        edges=[WorkflowEdge(id="e1", source="n1", target="n2")],
        variables=[], tags=["test"], category="general", author="test_user",
        created_at=time.time(), updated_at=time.time(),
        status=status, template=template
    )


# ==================== 节点 API ====================

class TestNodesAPI:
    """节点发现 API 测试"""

    @pytest.fixture
    def client(self):
        from neurova.api.endpoints.neurflow_api import router
        app = FastAPI()
        app.include_router(router, prefix="/api/v1/neurflow")
        return TestClient(app)

    @pytest.fixture
    def mock_registry(self):
        with patch('neurova.api.endpoints.neurflow_api.get_node_registry') as mock:
            registry = Mock()
            llm = _make_node_def("builtin:llm", "LLM 调用")
            search = _make_node_def("tool:web_search", "网页搜索", "tools", "tool")
            registry.list_all.return_value = [llm, search]
            registry.list_by_category.return_value = [llm]
            registry.list_by_source.return_value = [search]
            registry.search.return_value = [llm]
            registry.get.return_value = llm
            registry.get_summary.return_value = {
                "total": 2, "by_category": {"ai": 1, "tools": 1},
                "by_source": {"builtin": 1, "tool": 1}
            }
            registry.sync_all.return_value = {"tools": 5, "skills": 3, "mcp": 2}
            mock.return_value = registry
            yield registry

    def test_get_nodes_success(self, client, mock_registry):
        response = client.get("/api/v1/neurflow/nodes")
        assert response.status_code == 200
        data = response.json()
        assert "nodes" in data
        assert len(data["nodes"]) == 2

    def test_get_nodes_with_category_filter(self, client, mock_registry):
        response = client.get("/api/v1/neurflow/nodes?category=ai")
        assert response.status_code == 200
        mock_registry.list_by_category.assert_called_once_with("ai")

    def test_get_nodes_with_source_filter(self, client, mock_registry):
        response = client.get("/api/v1/neurflow/nodes?source=tool")
        assert response.status_code == 200
        mock_registry.list_by_source.assert_called_once_with("tool")

    def test_get_nodes_with_search(self, client, mock_registry):
        response = client.get("/api/v1/neurflow/nodes/search/LLM")
        assert response.status_code == 200
        mock_registry.search.assert_called_once_with("LLM")

    def test_get_nodes_summary(self, client, mock_registry):
        response = client.get("/api/v1/neurflow/nodes/stats")
        assert response.status_code == 200
        data = response.json()
        assert data["summary"]["total"] == 2

    def test_sync_nodes_success(self, client, mock_registry):
        response = client.post("/api/v1/neurflow/nodes/sync")
        assert response.status_code == 200
        data = response.json()
        assert data["sync_result"]["tools"] == 5
        mock_registry.sync_all.assert_called_once()

    def test_sync_all_registers_drama_commerce(self):
        """NodeRegistry.sync_all() 必须注册 drama/commerce/comfyui 适配器节点"""
        registry = NodeRegistry()
        registry.ensure_builtin()
        result = registry.sync_all()

        assert result["commerce"] > 0, "电商节点未注册"
        assert result["drama"] > 0, "短剧视频节点未注册"
        assert result["comfyui"] > 0, "ComfyUI 节点未注册"

        # drama/commerce 节点 type 为 builtin:xxx，按 category 区分
        all_nodes = registry.list_all()
        media_nodes = [n for n in all_nodes if getattr(n, "category", "") == "media"]
        commerce_nodes = [n for n in all_nodes if getattr(n, "category", "") == "commerce"]
        assert len(media_nodes) >= 3, f"预期至少 3 个 media 节点，实际: {len(media_nodes)}"
        assert len(commerce_nodes) >= 3, f"预期至少 3 个 commerce 节点，实际: {len(commerce_nodes)}"

        # 具体节点可通过 get() 检索
        assert registry.get("builtin:short-drama-script") is not None, "短剧剧本节点缺失"
        assert registry.get("builtin:price-monitor") is not None, "价格监控节点缺失"

    def _make_rich_node(self):
        """创建一个带完整 sub_blocks 的节点（dict 格式，模拟 builtin/commerce/drama 节点）"""
        from neurova.collaboration.neurflow.models import NodeDefinition

        return NodeDefinition(
            type="builtin:short-drama-script",
            label="短剧剧本生成",
            icon="🎬",
            category="media",
            description="生成短剧剧本",
            sub_blocks=[
                {
                    "id": "genre", "title": "题材", "type": "select",
                    "default_value": "urban",
                    "options": [{"label": "都市逆袭", "value": "urban"}, {"label": "甜宠恋爱", "value": "romance"}],
                },
                {"id": "episodes", "title": "集数", "type": "slider", "default_value": 12, "min": 1, "max": 100},
                {"id": "logline", "title": "剧情核心", "type": "textarea", "placeholder": "输入梗概", "required": False},
            ],
            inputs=[{"id": "input", "label": "输入"}],
            outputs=[{"id": "output", "label": "输出"}],
        )

    def test_get_nodes_sub_blocks_include_full_fields(self, client, mock_registry):
        """list_nodes 必须返回完整 sub_blocks（default_value/options/min/max/placeholder），供前端画布渲染"""
        mock_registry.list_all.return_value = [self._make_rich_node()]

        response = client.get("/api/v1/neurflow/nodes")
        assert response.status_code == 200
        blocks = response.json()["nodes"][0]["sub_blocks"]
        assert len(blocks) == 3

        genre = next(b for b in blocks if b["id"] == "genre")
        assert genre["default_value"] == "urban"
        assert len(genre["options"]) == 2

        episodes = next(b for b in blocks if b["id"] == "episodes")
        assert episodes["default_value"] == 12
        assert episodes["min"] == 1
        assert episodes["max"] == 100

        logline = next(b for b in blocks if b["id"] == "logline")
        assert logline["placeholder"] == "输入梗概"

    def test_get_node_sub_blocks_include_full_fields(self, client, mock_registry):
        """get_node 对 dict 格式 sub_blocks 不应崩溃，且返回完整字段"""
        mock_registry.get.return_value = self._make_rich_node()

        response = client.get("/api/v1/neurflow/nodes/builtin:short-drama-script")
        assert response.status_code == 200
        node = response.json()["node"]
        blocks = node["sub_blocks"]
        assert len(blocks) == 3

        genre = next(b for b in blocks if b["id"] == "genre")
        assert genre["default_value"] == "urban"
        assert len(genre["options"]) == 2

        episodes = next(b for b in blocks if b["id"] == "episodes")
        assert episodes["min"] == 1
        assert episodes["max"] == 100


# ==================== 工作流 CRUD ====================

class TestWorkflowsCRUDAPI:
    """工作流 CRUD API 测试"""

    @pytest.fixture
    def client(self):
        from neurova.api.endpoints.neurflow_api import router
        app = FastAPI()
        app.include_router(router, prefix="/api/v1/neurflow")
        return TestClient(app)

    @pytest.fixture
    def mock_storage(self):
        with patch('neurova.api.endpoints.neurflow_api._get_storage') as mock:
            storage = Mock()
            test_workflow = _make_workflow()
            storage.list_workflows.return_value = [test_workflow]
            storage.get_workflow.return_value = test_workflow
            storage.save_workflow.return_value = test_workflow
            storage.delete_workflow.return_value = True
            mock.return_value = storage
            yield storage

    def test_list_workflows_success(self, client, mock_storage):
        response = client.get("/api/v1/neurflow/workflows")
        assert response.status_code == 200
        data = response.json()
        assert "workflows" in data
        assert len(data["workflows"]) == 1

    def test_list_workflows_with_pagination(self, client, mock_storage):
        response = client.get("/api/v1/neurflow/workflows?limit=10&offset=0")
        assert response.status_code == 200
        mock_storage.list_workflows.assert_called_once()

    def test_list_workflows_with_status_filter(self, client, mock_storage):
        response = client.get("/api/v1/neurflow/workflows?status=draft")
        assert response.status_code == 200

    def test_create_workflow_success(self, client, mock_storage):
        """测试创建工作流 — 提供完整数据"""
        workflow_data = _make_workflow().to_dict()
        response = client.post("/api/v1/neurflow/workflows", json=workflow_data)
        assert response.status_code == 200
        data = response.json()
        assert "workflow" in data
        assert data["message"] == "工作流创建成功"

    def test_get_workflow_success(self, client, mock_storage):
        response = client.get("/api/v1/neurflow/workflows/wf_001")
        assert response.status_code == 200
        data = response.json()
        assert "workflow" in data
        assert data["workflow"]["id"] == "wf_001"

    def test_get_workflow_not_found(self, client, mock_storage):
        mock_storage.get_workflow.return_value = None
        response = client.get("/api/v1/neurflow/workflows/nonexistent")
        assert response.status_code == 404

    def test_update_workflow_success(self, client, mock_storage):
        """测试更新工作流 — 提供完整数据"""
        update_data = _make_workflow().to_dict()
        update_data["name"] = "更新后的名称"
        response = client.put("/api/v1/neurflow/workflows/wf_001", json=update_data)
        assert response.status_code == 200
        mock_storage.save_workflow.assert_called()

    def test_delete_workflow_success(self, client, mock_storage):
        response = client.delete("/api/v1/neurflow/workflows/wf_001")
        assert response.status_code == 200
        mock_storage.delete_workflow.assert_called_once_with("wf_001")

    def test_delete_workflow_not_found(self, client, mock_storage):
        mock_storage.delete_workflow.return_value = False
        response = client.delete("/api/v1/neurflow/workflows/nonexistent")
        assert response.status_code == 404

    def test_duplicate_workflow_success(self, client, mock_storage):
        response = client.post("/api/v1/neurflow/workflows/wf_001/duplicate")
        assert response.status_code == 200
        mock_storage.save_workflow.assert_called()


# ==================== 工作流定义 ====================

class TestWorkflowDefinitionAPI:
    """工作流定义 API 测试"""

    @pytest.fixture
    def client(self):
        from neurova.api.endpoints.neurflow_api import router
        app = FastAPI()
        app.include_router(router, prefix="/api/v1/neurflow")
        return TestClient(app)

    @pytest.fixture
    def mock_storage(self):
        with patch('neurova.api.endpoints.neurflow_api._get_storage') as mock:
            storage = Mock()
            storage.get_workflow.return_value = _make_workflow()
            mock.return_value = storage
            yield storage

    def test_get_definition_success(self, client, mock_storage):
        response = client.get("/api/v1/neurflow/workflows/wf_001/definition")
        assert response.status_code == 200
        data = response.json()
        assert "nodes" in data
        assert "edges" in data
        assert "variables" in data

    def test_update_definition_success(self, client, mock_storage):
        definition_data = {
            "nodes": [{"id": "n1", "type": "builtin:start", "position": {"x": 0, "y": 0}, "config": {}}],
            "edges": [{"id": "e1", "source": "n1", "target": "n2"}],
            "variables": []
        }
        response = client.put("/api/v1/neurflow/workflows/wf_001/definition", json=definition_data)
        assert response.status_code == 200
        mock_storage.save_workflow.assert_called()


# ==================== 执行 API ====================

class TestExecutionAPI:
    """执行 API 测试"""

    @pytest.fixture
    def client(self):
        from neurova.api.auth import get_current_user
        from neurova.api.endpoints.neurflow_api import router

        app = FastAPI()
        app.include_router(router, prefix="/api/v1/neurflow")
        # resume 走严格鉴权（58acbb3f 审计修复）——测试直接注入身份
        app.dependency_overrides[get_current_user] = lambda: {
            "user_id": "test_user",
            "username": "tester",
            "role": "user",
        }
        return TestClient(app)

    @pytest.fixture
    def mock_storage(self):
        with patch('neurova.api.endpoints.neurflow_api._get_storage') as mock:
            storage = Mock()
            test_execution = ExecutionInstance(
                id="exec_001", workflow_id="wf_001",
                status=WorkflowStatus.COMPLETED,
                inputs={"topic": "test"}, outputs={"result": "success"},
                node_results={}, variables={},
                started_at=time.time(), finished_at=time.time(), duration=1.5
            )
            storage.list_executions.return_value = [test_execution]
            storage.get_execution.return_value = test_execution
            storage.get_workflow.return_value = _make_workflow()
            mock.return_value = storage
            yield storage

    @pytest.fixture
    def mock_executor(self):
        with patch('neurova.api.endpoints.neurflow_api.get_workflow_executor') as mock:
            executor = Mock()
            executor.execute = AsyncMock(return_value=ExecutionInstance(
                id="exec_002", workflow_id="wf_001",
                status=WorkflowStatus.COMPLETED,
                inputs={}, outputs={"result": "done"}
            ))
            executor.cancel.return_value = True
            executor.resume.return_value = True
            mock.return_value = executor
            yield executor

    def test_execute_workflow_success(self, client, mock_storage, mock_executor):
        response = client.post("/api/v1/neurflow/workflows/wf_001/execute",
                               json={"inputs": {"topic": "test"}})
        assert response.status_code == 200
        data = response.json()
        assert "instance" in data
        assert data["instance"]["id"] == "exec_002"

    def test_list_executions_success(self, client, mock_storage):
        response = client.get("/api/v1/neurflow/executions")
        assert response.status_code == 200
        data = response.json()
        assert "executions" in data
        assert len(data["executions"]) == 1

    def test_list_executions_with_workflow_filter(self, client, mock_storage):
        response = client.get("/api/v1/neurflow/executions?workflow_id=wf_001")
        assert response.status_code == 200

    def test_get_execution_success(self, client, mock_storage):
        response = client.get("/api/v1/neurflow/executions/exec_001")
        assert response.status_code == 200
        data = response.json()
        assert "execution" in data
        assert data["execution"]["id"] == "exec_001"

    def test_cancel_execution_success(self, client, mock_storage, mock_executor):
        response = client.post("/api/v1/neurflow/executions/exec_001/cancel")
        assert response.status_code == 200
        mock_executor.cancel.assert_called_once_with("exec_001")

    def test_resume_execution_success(self, client, mock_storage, mock_executor):
        mock_storage.get_execution.return_value.status = WorkflowStatus.PAUSED
        response = client.post("/api/v1/neurflow/executions/exec_001/resume")
        assert response.status_code == 200
        mock_executor.resume.assert_called_once_with("exec_001")


# ==================== 团队 Agent API ====================

class TestAgentsAPI:
    """团队 Agent API 测试"""

    @pytest.fixture
    def client(self):
        from neurova.api.endpoints.neurflow_api import router
        app = FastAPI()
        app.include_router(router, prefix="/api/v1/neurflow")
        return TestClient(app)

    @pytest.fixture
    def mock_agent_manager(self):
        # Agent manager is imported locally in neurflow_api.py
        with patch('neurova.collaboration.neurflow.agent_manager.get_agent_manager') as mock_get_manager:
            manager = Mock()
            test_agent = Mock(
                agent_id="agent_001", name="测试 Agent", role="coder",
                config={"model": "gpt-4"}, flow_id="wf_001",
                created_at=time.time(), status="active"
            )
            manager.list_agents.return_value = [test_agent]
            manager.create_agent.return_value = test_agent
            manager.archive_agent.return_value = True
            manager.restore_agent.return_value = True
            mock_get_manager.return_value = manager
            yield manager

    def test_list_agents_success(self, client, mock_agent_manager):
        response = client.get("/api/v1/neurflow/agents")
        assert response.status_code == 200
        data = response.json()
        assert "agents" in data
        assert len(data["agents"]) == 1

    def test_list_agents_with_flow_filter(self, client, mock_agent_manager):
        response = client.get("/api/v1/neurflow/agents?flow_id=wf_001")
        assert response.status_code == 200
        mock_agent_manager.list_agents.assert_called_with(flow_id="wf_001", include_archived=False)

    def test_create_agent_success(self, client, mock_agent_manager):
        agent_data = {
            "name": "新 Agent", "role": "reviewer",
            "config": {"model": "claude-3"}, "flow_id": "wf_001"
        }
        response = client.post("/api/v1/neurflow/agents", json=agent_data)
        assert response.status_code == 201
        data = response.json()
        assert "agent" in data

    def test_archive_agent_success(self, client, mock_agent_manager):
        response = client.post("/api/v1/neurflow/agents/agent_001/archive")
        assert response.status_code == 200
        mock_agent_manager.archive_agent.assert_called_once_with("agent_001")

    def test_restore_agent_success(self, client, mock_agent_manager):
        response = client.post("/api/v1/neurflow/agents/agent_001/restore")
        assert response.status_code == 200
        mock_agent_manager.restore_agent.assert_called_once_with("agent_001")


# ==================== 模板 API ====================

class TestTemplatesAPI:
    """模板 API 测试"""

    @pytest.fixture
    def client(self):
        from neurova.api.endpoints.neurflow_api import router
        app = FastAPI()
        app.include_router(router, prefix="/api/v1/neurflow")
        return TestClient(app)

    @pytest.fixture
    def mock_storage(self):
        with patch('neurova.api.endpoints.neurflow_api._get_storage') as mock:
            storage = Mock()
            test_template = _make_workflow(id="tmpl_001", name="编程助手模板",
                                           template=True, status=WorkflowStatus.PUBLISHED)
            test_workflow = _make_workflow()
            storage.list_templates.return_value = [test_template]
            storage.get_workflow.return_value = test_workflow
            storage.save_workflow.return_value = test_template
            mock.return_value = storage
            yield storage

    def test_list_templates_success(self, client, mock_storage):
        response = client.get("/api/v1/neurflow/templates")
        assert response.status_code == 200
        data = response.json()
        assert "templates" in data
        assert len(data["templates"]) == 1

    def test_create_template_success(self, client, mock_storage):
        template_data = {
            "name": "新模板", "description": "测试模板",
            "category": "general", "workflow_id": "wf_001"
        }
        response = client.post("/api/v1/neurflow/templates", json=template_data)
        assert response.status_code == 201

    def test_instantiate_template_success(self, client, mock_storage):
        """模板实例化"""
        template = _make_workflow(id="tmpl_001", name="模板", template=True, status=WorkflowStatus.PUBLISHED)
        mock_storage.get_workflow.return_value = template
        instantiate_data = {"name": "从模板创建的工作流", "variables": {"style": "formal"}}
        response = client.post("/api/v1/neurflow/templates/tmpl_001/instantiate", json=instantiate_data)
        assert response.status_code == 201
        data = response.json()
        assert "workflow" in data


# ==================== 验证 ====================

class TestAPIValidation:
    """API 验证测试"""

    @pytest.fixture
    def client(self):
        from neurova.api.endpoints.neurflow_api import router
        app = FastAPI()
        app.include_router(router, prefix="/api/v1/neurflow")
        return TestClient(app)

    def test_nonexistent_workflow(self, client):
        """测试获取不存在的工作流"""
        with patch('neurova.api.endpoints.neurflow_api._get_storage') as mock:
            storage = Mock()
            storage.get_workflow.return_value = None
            mock.return_value = storage
            response = client.get("/api/v1/neurflow/workflows/nonexistent")
            assert response.status_code == 404

    def test_invalid_json_body(self, client):
        response = client.post(
            "/api/v1/neurflow/workflows",
            content="invalid json",
            headers={"Content-Type": "application/json"}
        )
        assert response.status_code == 422


# ==================== 生命周期 ====================

class TestAPILifecycle:
    """API 生命周期测试"""

    @pytest.fixture
    def client(self):
        from neurova.api.auth import get_current_user
        from neurova.api.endpoints.neurflow_api import router

        app = FastAPI()
        app.include_router(router, prefix="/api/v1/neurflow")
        # publish 走严格鉴权（58acbb3f 审计修复）——测试直接注入身份
        app.dependency_overrides[get_current_user] = lambda: {
            "user_id": "test_user",
            "username": "tester",
            "role": "user",
        }
        return TestClient(app)

    @pytest.fixture
    def mock_storage(self):
        with patch('neurova.api.endpoints.neurflow_api._get_storage') as mock:
            storage = Mock()
            mock.return_value = storage
            yield storage

    def test_publish_workflow_success(self, client, mock_storage):
        test_workflow = _make_workflow()
        mock_storage.get_workflow.return_value = test_workflow

        with patch('neurova.api.endpoints.neurflow_api.get_dag_validator') as mock_dag:
            validator = Mock()
            validator.validate.return_value = Mock(
                is_valid=True, has_cycle=False, has_start=True, has_end=True,
                errors=[], warnings=[]
            )
            mock_dag.return_value = validator

            response = client.post("/api/v1/neurflow/workflows/wf_001/publish")
            assert response.status_code == 200
            mock_storage.save_workflow.assert_called()

    def test_validate_workflow_success(self, client, mock_storage):
        with patch('neurova.api.endpoints.neurflow_api.get_dag_validator') as mock_dag:
            validator = Mock()
            validator.validate.return_value = Mock(
                is_valid=True, has_cycle=False, has_start=True, has_end=True,
                errors=[], warnings=[]
            )
            mock_dag.return_value = validator

            mock_storage.get_workflow.return_value = _make_workflow()
            response = client.post("/api/v1/neurflow/workflows/wf_001/validate")
            assert response.status_code == 200
            data = response.json()
            assert data["is_valid"] == True
