"""
Phase 2 RED — L1 声明式 / L2 组合式自定义节点

契约（由本测试定义）：
- neurova/collaboration/neurflow/custom_nodes.py
  - CustomNodeError(ValueError)，带 .code：invalid_spec | exists | not_found
  - TIER_DECLARATIVE="declarative"（L1：表单 + prompt 模板 → LLM）
  - TIER_COMPOSITE="composite"（L2：顺序执行已有节点/工具链）
  - render_template(template, values)：{{key}} / {{a.b}} 点路径；缺失→空串；
    dict/list → JSON(ensure_ascii=False)
  - CustomNodeService(storage, registry, llm_runner=None)
    - create_node(spec, *, created_by=None) -> NodeDefinition
      校验 → 落库（source="custom"）→ 注册执行器
    - update_node / delete_node / get_node / list_nodes / list_versions
    - load_into_registry() -> int（把库内 active 自定义节点批量注册）
    - build_executor(def) -> async (config, ctx) -> {"status","output",...}
- NodeDefinition 扩展字段：tier / executor_body / status / created_by
- NeurflowStorage：
  - node_definitions 新列 tier / executor_body_json / status / created_by，
    旧库自动 ALTER TABLE 迁移
  - custom_node_versions 版本快照表 + save_node_version / list_node_versions

运行：pytest tests/unit/collaboration/test_custom_nodes.py -v
"""

import asyncio
import json
import sqlite3

import pytest

from neurova.collaboration.neurflow.custom_nodes import (
    TIER_COMPOSITE,
    TIER_DECLARATIVE,
    CustomNodeError,
    CustomNodeService,
    render_template,
)
from neurova.collaboration.neurflow.models import NodeDefinition, NodePort, SubBlockConfig
from neurova.collaboration.neurflow.node_registry import NodeRegistry
from neurova.collaboration.neurflow.storage import NeurflowStorage


# ── 测试工具 ────────────────────────────────────────────────────
def make_def(node_type: str, **kw) -> NodeDefinition:
    """构造最小 NodeDefinition（用于往注册表塞假执行器）"""
    defaults = dict(
        type=node_type,
        label=node_type,
        icon="🧪",
        category="tools",
        description="test node",
        sub_blocks=[],
        inputs=[NodePort(id="input", label="输入")],
        outputs=[NodePort(id="output", label="输出")],
        source="builtin",
    )
    defaults.update(kw)
    return NodeDefinition(**defaults)


def make_llm_runner(result=None, capture=None):
    async def runner(config, ctx):
        if capture is not None:
            capture.append((config, ctx))
        if result is not None:
            return result
        return {"status": "success", "output": {"text": "ok"}}

    return runner


def declarative_spec(**kw):
    spec = {
        "type": "custom:poem_writer",
        "label": "写诗助手",
        "description": "按主题写诗",
        "tier": TIER_DECLARATIVE,
        "form_schema": [
            {"id": "topic", "title": "主题", "type": "input", "required": True},
        ],
        "executor_body": {"template": "请以「{{topic}}」为题写一首诗"},
    }
    spec.update(kw)
    return spec


def composite_spec(**kw):
    spec = {
        "type": "custom:search_summarize",
        "label": "搜索并总结",
        "tier": TIER_COMPOSITE,
        "executor_body": {
            "steps": [
                {"node_type": "tool:echo", "config": {"text": "hello"}},
                {"node_type": "tool:upper", "config": {"text": "{{prev}}"}},
            ]
        },
    }
    spec.update(kw)
    return spec


@pytest.fixture
def storage(tmp_path):
    st = NeurflowStorage(str(tmp_path / "test_neurflow.db"))
    yield st
    st.close()


@pytest.fixture
def registry():
    return NodeRegistry()


@pytest.fixture
def service(storage, registry):
    return CustomNodeService(storage=storage, registry=registry)


# ── A. render_template 纯函数 ───────────────────────────────────
class TestRenderTemplate:
    def test_replaces_simple_placeholder(self):
        assert render_template("你好 {{name}}", {"name": "世界"}) == "你好 世界"

    def test_dotted_path_resolves_nested(self):
        assert render_template("{{user.city}}", {"user": {"city": "杭州"}}) == "杭州"

    def test_missing_key_renders_empty(self):
        assert render_template("a{{nope}}b", {}) == "ab"

    def test_non_scalar_values_json_dumped(self):
        out = render_template("{{data}}", {"data": {"k": "中文"}})
        assert json.loads(out) == {"k": "中文"}


# ── B. create_node 规格校验 ─────────────────────────────────────
class TestCreateValidation:
    def test_missing_label_rejected(self, service):
        with pytest.raises(CustomNodeError) as ei:
            service.create_node(declarative_spec(label=""))
        assert ei.value.code == "invalid_spec"

    def test_unknown_tier_rejected(self, service):
        with pytest.raises(CustomNodeError) as ei:
            service.create_node(declarative_spec(tier="quantum"))
        assert ei.value.code == "invalid_spec"

    def test_declarative_requires_template(self, service):
        with pytest.raises(CustomNodeError) as ei:
            service.create_node(declarative_spec(executor_body={"template": ""}))
        assert ei.value.code == "invalid_spec"

    def test_composite_requires_nonempty_steps(self, service):
        with pytest.raises(CustomNodeError) as ei:
            service.create_node(composite_spec(executor_body={"steps": []}))
        assert ei.value.code == "invalid_spec"

    def test_composite_step_requires_node_type(self, service):
        with pytest.raises(CustomNodeError) as ei:
            service.create_node(composite_spec(executor_body={"steps": [{"config": {}}]}))
        assert ei.value.code == "invalid_spec"

    def test_type_without_custom_prefix_auto_prefixed(self, service):
        node = service.create_node(declarative_spec(type="poem_writer"))
        assert node.type == "custom:poem_writer"

    def test_invalid_type_chars_rejected(self, service):
        with pytest.raises(CustomNodeError) as ei:
            service.create_node(declarative_spec(type="bad type!"))
        assert ei.value.code == "invalid_spec"

    def test_duplicate_type_rejected(self, service):
        service.create_node(declarative_spec())
        with pytest.raises(CustomNodeError) as ei:
            service.create_node(declarative_spec())
        assert ei.value.code == "exists"


# ── C. 持久化 + 注册表联动 ──────────────────────────────────────
class TestPersistence:
    def test_create_persists_custom_fields(self, service, storage):
        created = service.create_node(declarative_spec(), created_by="user1")
        loaded = storage.get_node_definition("custom:poem_writer")
        assert loaded is not None
        assert loaded.source == "custom"
        assert loaded.tier == TIER_DECLARATIVE
        assert loaded.executor_body == {"template": "请以「{{topic}}」为题写一首诗"}
        assert loaded.status == "active"
        assert loaded.created_by == "user1"
        assert created.type == loaded.type

    def test_form_schema_becomes_sub_blocks(self, service, storage):
        service.create_node(declarative_spec())
        loaded = storage.get_node_definition("custom:poem_writer")
        assert len(loaded.sub_blocks) == 1
        assert loaded.sub_blocks[0].id == "topic"
        assert loaded.sub_blocks[0].required is True

    def test_default_ports_when_unspecified(self, service, storage):
        service.create_node(declarative_spec())
        loaded = storage.get_node_definition("custom:poem_writer")
        assert [p.id for p in loaded.inputs] == ["input"]
        assert [p.id for p in loaded.outputs] == ["output"]

    def test_create_registers_executor(self, service, registry):
        service.create_node(declarative_spec())
        assert registry.get("custom:poem_writer") is not None
        assert callable(registry.get_executor("custom:poem_writer"))

    def test_list_nodes_returns_only_custom(self, service, storage):
        # 预置一个非 custom 节点
        storage.save_node_definition(make_def("tool:other"))
        service.create_node(declarative_spec())
        nodes = service.list_nodes()
        assert [n.type for n in nodes] == ["custom:poem_writer"]

    def test_update_snapshots_previous_version(self, service):
        service.create_node(declarative_spec())
        updated = service.update_node(
            "custom:poem_writer",
            {"executor_body": {"template": "新模板 {{topic}}"}},
        )
        assert updated.executor_body == {"template": "新模板 {{topic}}"}
        assert updated.version == "1.0.1"

        versions = service.list_versions("custom:poem_writer")
        assert len(versions) == 1
        snapshot = versions[0]["snapshot"]
        assert snapshot["executor_body"] == {"template": "请以「{{topic}}」为题写一首诗"}

    def test_update_missing_raises_not_found(self, service):
        with pytest.raises(CustomNodeError) as ei:
            service.update_node("custom:ghost", {"label": "x"})
        assert ei.value.code == "not_found"

    def test_delete_removes_from_storage_and_registry(self, service, storage, registry):
        service.create_node(declarative_spec())
        assert service.delete_node("custom:poem_writer") is True
        assert storage.get_node_definition("custom:poem_writer") is None
        assert registry.get("custom:poem_writer") is None
        assert service.delete_node("custom:poem_writer") is False

    def test_load_into_registry_registers_persisted_nodes(self, storage, registry):
        # 第一个 service 落库；第二个 service 模拟进程重启后加载
        CustomNodeService(storage=storage, registry=NodeRegistry()).create_node(
            declarative_spec()
        )
        fresh = CustomNodeService(storage=storage, registry=registry)
        count = fresh.load_into_registry()
        assert count == 1
        assert callable(registry.get_executor("custom:poem_writer"))


# ── D. L1 声明式执行器 ──────────────────────────────────────────
class TestDeclarativeExecutor:
    def test_renders_template_and_calls_llm(self, service, registry):
        calls = []
        svc = CustomNodeService(
            storage=service._storage,
            registry=registry,
            llm_runner=make_llm_runner(capture=calls),
        )
        node = svc.create_node(
            declarative_spec(
                executor_body={
                    "template": "请以「{{topic}}」为题写一首诗",
                    "model_provider": "p1",
                    "model_name": "m1",
                }
            )
        )
        executor = registry.get_executor(node.type)
        result = asyncio.run(executor({"topic": "春天"}, {}))

        assert result["status"] == "success"
        llm_config = calls[0][0]
        assert llm_config["prompt"] == "请以「春天」为题写一首诗"
        assert llm_config["model_provider"] == "p1"
        assert llm_config["model_name"] == "m1"

    def test_ctx_inputs_fill_missing_config_vars(self, service, registry):
        calls = []
        svc = CustomNodeService(
            storage=service._storage,
            registry=registry,
            llm_runner=make_llm_runner(capture=calls),
        )
        node = svc.create_node(
            declarative_spec(executor_body={"template": "{{topic}}-{{style}}"})
        )
        executor = registry.get_executor(node.type)
        # topic 来自节点配置，style 来自工作流输入；配置优先于输入
        asyncio.run(
            executor({"topic": "海", "style": "五言"}, {"inputs": {"topic": "山"}})
        )
        assert calls[0][0]["prompt"] == "海-五言"

    def test_llm_failure_propagates(self, service, registry):
        svc = CustomNodeService(
            storage=service._storage,
            registry=registry,
            llm_runner=make_llm_runner(
                result={"status": "failed", "error": "模型不可用", "output": None}
            ),
        )
        node = svc.create_node(declarative_spec())
        executor = registry.get_executor(node.type)
        result = asyncio.run(executor({"topic": "春天"}, {}))
        assert result["status"] == "failed"
        assert "模型不可用" in str(result.get("error"))


# ── E. L2 组合式执行器 ──────────────────────────────────────────
class TestCompositeExecutor:
    def _register_step_nodes(self, registry, executed=None):
        async def echo_exec(config, ctx):
            if executed is not None:
                executed.append(("tool:echo", dict(config)))
            return {"status": "success", "output": str(config.get("text", ""))}

        async def upper_exec(config, ctx):
            if executed is not None:
                executed.append(("tool:upper", dict(config)))
            return {"status": "success", "output": str(config.get("text", "")).upper()}

        registry.register(make_def("tool:echo"), executor=echo_exec)
        registry.register(make_def("tool:upper"), executor=upper_exec)

    def test_steps_run_in_order_passing_prev_output(self, service, registry):
        executed = []
        self._register_step_nodes(registry, executed)
        node = service.create_node(composite_spec())
        executor = registry.get_executor(node.type)
        result = asyncio.run(executor({}, {}))

        assert result["status"] == "success"
        assert result["output"] == "HELLO"
        # 第二步的 {{prev}} 被解析为第一步输出
        assert executed[1] == ("tool:upper", {"text": "hello"})

    def test_unknown_step_node_type_fails(self, service, registry):
        spec = composite_spec(
            executor_body={"steps": [{"node_type": "tool:ghost", "config": {}}]}
        )
        node = service.create_node(spec)
        executor = registry.get_executor(node.type)
        result = asyncio.run(executor({}, {}))
        assert result["status"] == "failed"
        assert "tool:ghost" in str(result.get("error"))

    def test_step_failure_short_circuits(self, service, registry):
        executed = []

        async def boom_exec(config, ctx):
            executed.append("boom")
            return {"status": "failed", "error": "炸了", "output": None}

        async def never_exec(config, ctx):
            executed.append("never")
            return {"status": "success", "output": None}

        registry.register(make_def("tool:boom"), executor=boom_exec)
        registry.register(make_def("tool:never"), executor=never_exec)

        node = service.create_node(
            composite_spec(
                executor_body={
                    "steps": [
                        {"node_type": "tool:boom", "config": {}},
                        {"node_type": "tool:never", "config": {}},
                    ]
                }
            )
        )
        executor = registry.get_executor(node.type)
        result = asyncio.run(executor({}, {}))
        assert result["status"] == "failed"
        assert executed == ["boom"]


# ── F. 存储迁移 + 版本表 ────────────────────────────────────────
class TestStorageMigration:
    def test_legacy_db_migrated_on_open(self, tmp_path):
        """旧库（无新列）打开时自动 ALTER TABLE 补齐，读写正常"""
        db_path = str(tmp_path / "legacy.db")
        st = NeurflowStorage(db_path)
        st.close()

        # 模拟旧版本库：删掉新增列
        conn = sqlite3.connect(db_path)
        conn.execute("ALTER TABLE node_definitions DROP COLUMN tier")
        conn.execute("ALTER TABLE node_definitions DROP COLUMN executor_body_json")
        conn.execute("ALTER TABLE node_definitions DROP COLUMN status")
        conn.execute("ALTER TABLE node_definitions DROP COLUMN created_by")
        conn.commit()
        conn.close()

        st = NeurflowStorage(db_path)
        try:
            node = make_def(
                "custom:legacy_ok",
                source="custom",
                tier=TIER_DECLARATIVE,
                executor_body={"template": "hi"},
                status="active",
                created_by="u9",
            )
            assert st.save_node_definition(node) is True
            loaded = st.get_node_definition("custom:legacy_ok")
            assert loaded.tier == TIER_DECLARATIVE
            assert loaded.executor_body == {"template": "hi"}
            assert loaded.created_by == "u9"
        finally:
            st.close()

    def test_version_table_roundtrip(self, storage):
        storage.save_node_version(
            "custom:x", 1, {"label": "v1"}, created_by="u1"
        )
        storage.save_node_version("custom:x", 2, {"label": "v2"}, created_by="u1")
        versions = storage.list_node_versions("custom:x")
        # 新版本在前
        assert [v["version"] for v in versions] == [2, 1]
        assert versions[0]["snapshot"] == {"label": "v2"}
