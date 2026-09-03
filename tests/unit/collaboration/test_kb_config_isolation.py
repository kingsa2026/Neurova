"""
远程知识库配置：用户隔离（fail-closed）与适配器参数对齐（TDD 红绿）。

背景（2026-09-01）：
- 隔离缺口：执行引擎节点 ctx 不带 user_id，exec_knowledge_base 引用
  kb_config_id 时属主检查写成 `if user_id and ...` —— 无用户上下文时被
  整体跳过，任意执行上下文可解密任意用户的配置密钥。违反"远程配置
  默认私有、按用户隔离"。修复后 fail-closed：无 user_id / 属主不匹配
  → 一律拒绝，错误信息如实说明原因。
- 参数断链：remote_config 组装缺 token/knowledge_base_id/search_type 等
  字段 —— ima 的 token 即使存进 settings 也到不了适配器。同时 feishu/ima
  的主凭据（app_secret/token）统一走 api_key 加密通道，消费端按
  source_type 注入对应字段（feishu→app_secret / ima→token / 其余→api_key）。

契约：
  1. 引用 kb_config_id 时 ctx 无 user_id → failed（fail-closed，不静默放行）
  2. ctx user_id 与配置属主不匹配 → failed
  3. 属主匹配 → 解密主凭据注入 + settings 参数注入适配器
     （ima: base_url/allow_local/knowledge_base_id；iflow: base_url/dataset_id）
  4. 节点 kb_type 未显式选择（空/画布默认 local）→ 跟随配置 source_type
  5. 节点手填字段优先于配置 settings（向后兼容）
  6. 执行引擎 ctx 透传 instance.user_id
"""

import asyncio

import pytest

from neurova.collaboration.neurflow import builtin as builtin_mod
from neurova.knowledge.storage import KnowledgeStorage


@pytest.fixture
def kb_storage(tmp_path, monkeypatch):
    """固定 Fernet 密钥 + 临时目录存储，替换单例入口。"""
    from cryptography.fernet import Fernet

    monkeypatch.setenv("NEUROVA_KB_SECRET", Fernet.generate_key().decode())
    st = KnowledgeStorage(str(tmp_path / "kb"))
    monkeypatch.setattr("neurova.knowledge.storage.get_knowledge_storage", lambda: st)
    return st


def _run(coro):
    return asyncio.run(coro)


# ============ 1. 隔离：fail-closed ============

def test_kb_config_ref_without_user_context_denied(kb_storage):
    """ctx 无 user_id 时引用 kb_config_id → 拒绝（不再静默解密任意配置）。"""
    cid = kb_storage.create_config(
        user_id="u-owner",
        name="ima-kb",
        source_type="ima",
        api_key="tok-secret",
        settings={"base_url": "http://localhost:9007/sse", "allow_local": True},
    )
    r = _run(
        builtin_mod.exec_knowledge_base(
            {"kb_type": "ima", "query": "x", "kb_config_id": cid}, {}
        )
    )
    assert r["status"] == "failed"
    assert r.get("error"), "必须给出诚实的拒绝原因"


def test_kb_config_ref_other_user_denied(kb_storage):
    """ctx user_id 与配置属主不匹配 → 拒绝。"""
    cid = kb_storage.create_config(
        user_id="u-owner", name="iflow-kb", source_type="iflow", api_key="sk-1"
    )
    r = _run(
        builtin_mod.exec_knowledge_base(
            {"kb_type": "iflow", "query": "x", "kb_config_id": cid},
            {"user_id": "u-attacker"},
        )
    )
    assert r["status"] == "failed"


def test_load_secret_without_user_context_returns_none(kb_storage):
    """_load_kb_config_secret 无 user_id → None（纵深防御，不依赖调用方检查）。"""
    cid = kb_storage.create_config(
        user_id="u-owner", name="iflow-kb", source_type="iflow", api_key="sk-1"
    )
    assert builtin_mod._load_kb_config_secret(cid, "") is None
    assert builtin_mod._load_kb_config_secret(cid, "u-owner") == "sk-1"


# ============ 2. 参数对齐：凭据注入 + settings 透传 ============

def test_kb_config_ref_owner_injects_ima_token_and_settings(kb_storage, monkeypatch):
    """属主匹配：api_key 通道解密注入 ima.token，settings 参数进适配器。"""
    from neurova.knowledge.adapters import ImaKBAdapter

    cid = kb_storage.create_config(
        user_id="u-owner",
        name="ima-kb",
        source_type="ima",
        api_key="tok-1",
        settings={
            "base_url": "http://localhost:9007/sse",
            "allow_local": True,
            "knowledge_base_id": "kb-7",
        },
    )
    captured = {}

    async def fake_search(self, query, limit=5):
        captured.update(
            {
                "token": self.token,
                "base_url": self.base_url,
                "allow_local": self.allow_local,
                "knowledge_base_id": self._config.get("knowledge_base_id"),
            }
        )
        return {"status": "success", "results": []}

    monkeypatch.setattr(ImaKBAdapter, "search", fake_search)
    r = _run(
        builtin_mod.exec_knowledge_base(
            {"kb_type": "ima", "query": "x", "kb_config_id": cid},
            {"user_id": "u-owner"},
        )
    )
    assert r["status"] == "success"
    assert captured["token"] == "tok-1", "api_key 通道凭据必须注入 ima.token"
    assert captured["base_url"] == "http://localhost:9007/sse"
    assert captured["allow_local"] is True
    assert captured["knowledge_base_id"] == "kb-7"


def test_kb_config_ref_feishu_secret_injected_as_app_secret(kb_storage, monkeypatch):
    """feishu 配置的主凭据（app_secret 走 api_key 通道）注入 adapter.app_secret。"""
    from neurova.knowledge.adapters import FeishuKBAdapter

    cid = kb_storage.create_config(
        user_id="u-owner",
        name="feishu-kb",
        source_type="feishu",
        api_key="sh-app-secret",
        settings={"app_id": "cli_123"},
    )
    captured = {}

    async def fake_search(self, query, limit=5):
        captured.update({"app_id": self.app_id, "app_secret": self.app_secret})
        return {"status": "success", "results": []}

    monkeypatch.setattr(FeishuKBAdapter, "search", fake_search)
    r = _run(
        builtin_mod.exec_knowledge_base(
            {"kb_type": "feishu", "query": "x", "kb_config_id": cid},
            {"user_id": "u-owner"},
        )
    )
    assert r["status"] == "success"
    assert captured["app_id"] == "cli_123"
    assert captured["app_secret"] == "sh-app-secret"


def test_kb_config_ref_iflow_settings_flow(kb_storage, monkeypatch):
    """iflow：api_key 通道解密注入 api_key，base_url/dataset_id 走 settings。"""
    from neurova.knowledge.adapters import IflowKBAdapter

    cid = kb_storage.create_config(
        user_id="u-owner",
        name="iflow-kb",
        source_type="iflow",
        api_key="sk-iflow",
        settings={"base_url": "https://platform.iflow.cn", "dataset_id": "kb-9"},
    )
    captured = {}

    async def fake_search(self, query, limit=5):
        captured.update(
            {
                "api_key": self.api_key,
                "base_url": self.base_url,
                "dataset_id": self.dataset_id,
            }
        )
        return {"status": "success", "results": []}

    monkeypatch.setattr(IflowKBAdapter, "search", fake_search)
    r = _run(
        builtin_mod.exec_knowledge_base(
            {"kb_type": "iflow", "query": "x", "kb_config_id": cid},
            {"user_id": "u-owner"},
        )
    )
    assert r["status"] == "success"
    assert captured["api_key"] == "sk-iflow"
    assert captured["base_url"] == "https://platform.iflow.cn"
    assert captured["dataset_id"] == "kb-9"


def test_node_manual_fields_override_settings(kb_storage, monkeypatch):
    """节点手填字段优先于配置 settings（向后兼容 R-7 B 契约）。"""
    from neurova.knowledge.adapters import IflowKBAdapter

    cid = kb_storage.create_config(
        user_id="u-owner",
        name="iflow-kb",
        source_type="iflow",
        api_key="sk-cfg",
        settings={"dataset_id": "from-config"},
    )
    captured = {}

    async def fake_search(self, query, limit=5):
        captured["dataset_id"] = self.dataset_id
        return {"status": "success", "results": []}

    monkeypatch.setattr(IflowKBAdapter, "search", fake_search)
    r = _run(
        builtin_mod.exec_knowledge_base(
            {"kb_type": "iflow", "query": "x", "kb_config_id": cid, "dataset_id": "manual"},
            {"user_id": "u-owner"},
        )
    )
    assert r["status"] == "success"
    assert captured["dataset_id"] == "manual"


# ============ 3. kb_type 跟随配置 source_type ============

def test_kb_type_follows_config_source_type(kb_storage, monkeypatch):
    """节点 kb_type 未显式选择（画布默认 local）→ 引用配置时跟随其 source_type。"""
    from neurova.knowledge.adapters import IflowKBAdapter

    cid = kb_storage.create_config(
        user_id="u-owner", name="iflow-kb", source_type="iflow", api_key="sk-1"
    )
    captured = {}

    async def fake_search(self, query, limit=5):
        captured["called"] = True
        return {"status": "success", "results": []}

    monkeypatch.setattr(IflowKBAdapter, "search", fake_search)
    r = _run(
        builtin_mod.exec_knowledge_base(
            {"query": "x", "kb_config_id": cid},  # 无 kb_type → 画布默认 local
            {"user_id": "u-owner"},
        )
    )
    assert captured.get("called"), "必须按配置 source_type 分派到 IflowKBAdapter"
    assert r["status"] == "success"
    assert r["output"]["kb_type"] == "iflow"


def test_kb_type_explicit_wins_over_config(kb_storage, monkeypatch):
    """节点显式选择的 kb_type 优先于配置 source_type。"""
    from neurova.knowledge.adapters import GenericRESTAdapter

    cid = kb_storage.create_config(
        user_id="u-owner",
        name="iflow-kb",
        source_type="iflow",
        api_key="sk-1",
        settings={"api_url": "https://kb.example/r"},
    )
    captured = {}

    async def fake_search(self, query, limit=5):
        captured["called"] = True
        return {"status": "success", "results": []}

    monkeypatch.setattr(GenericRESTAdapter, "search", fake_search)
    r = _run(
        builtin_mod.exec_knowledge_base(
            {"kb_type": "custom", "query": "x", "kb_config_id": cid},
            {"user_id": "u-owner"},
        )
    )
    assert captured.get("called"), "显式 custom 必须仍走 GenericRESTAdapter"
    assert r["status"] == "success"
    assert r["output"]["kb_type"] == "custom"


# ============ 4. 执行引擎 ctx 透传 user_id ============

def _make_workflow(node_type: str, config: dict):
    import time as _time

    from neurova.collaboration.neurflow.models import (
        WorkflowDefinition,
        WorkflowEdge,
        WorkflowNode,
        WorkflowStatus,
    )

    return WorkflowDefinition(
        id="wf-iso-test",
        name="iso-test",
        description="",
        version="1.0.0",
        nodes=[
            WorkflowNode(id="s", type="builtin:start", position={"x": 0, "y": 0}, config={}),
            WorkflowNode(id="n1", type=node_type, position={"x": 1, "y": 0}, config=config),
            WorkflowNode(id="e", type="builtin:end", position={"x": 2, "y": 0}, config={}),
        ],
        edges=[
            WorkflowEdge(id="e1", source="s", target="n1"),
            WorkflowEdge(id="e2", source="n1", target="e"),
        ],
        variables=[],
        tags=[],
        category="test",
        author="test",
        created_at=_time.time(),
        updated_at=_time.time(),
        status=WorkflowStatus.DRAFT,
    )


def test_engine_ctx_carries_user_id(monkeypatch):
    """引擎把 instance.user_id 透传进节点 ctx（隔离检查的数据源）。"""
    import neurova.knowledge.adapters as kb_adapters
    from neurova.collaboration.neurflow.execution_engine import get_workflow_executor
    from neurova.knowledge.adapters import KBAdapter

    captured = {}

    class _Cap(KBAdapter):
        async def search(self, query, limit=5):
            return {"status": "success", "results": []}

    def fake_get_adapter(kb_type, config, ctx=None):
        captured["ctx"] = ctx
        return _Cap({})

    monkeypatch.setattr(kb_adapters, "get_adapter", fake_get_adapter)

    from neurova.collaboration.neurflow.node_registry import get_node_registry

    get_node_registry().ensure_builtin()

    wf = _make_workflow(
        "builtin:knowledge_base", {"kb_type": "local", "query": "q"}
    )
    executor = get_workflow_executor()
    instance = _run(
        executor.execute(wf, inputs={}, user_id="u9", memory_manager=None)
    )
    assert captured["ctx"] is not None
    assert captured["ctx"].get("user_id") == "u9", (
        "节点 ctx 必须携带执行实例的 user_id，否则配置属主检查无从谈起"
    )
