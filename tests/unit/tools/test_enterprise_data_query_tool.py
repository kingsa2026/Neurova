# -*- coding: utf-8 -*-
"""P2-2 车道D：成员工具面 ``enterprise_data_query`` 判据（先红后绿）。

- schema 单源注册 + 分派表执行体（TestSchemaDispatchConsistency 同款不变量）；
- 总闸 ``NEUROVA_NL2SQL_ENABLED``：开→走既有 nl2sql 管线（目录 grounding →
  生成 → 只读校验 → 连接器只读执行）；关→结构化 ``capability_disabled``
  工具错误（转译为工具错误，不抛裸异常）；
- 只读硬闸在连接器层（``assertReadonlySelect``）：DROP/INSERT 意图点名拒绝；
- 租户隔离：他租户 source_id 拒绝（源配置 loadConfig 本租户查无即拒）；
- 成员白名单：explore 型成员拿得到（capability.readOnly 声明 + 不进
  ``MAIN_AGENT_ONLY_TOOLS``）；面外成员被执行咽喉拦截（subagent_tool_not_allowed）；
- 工具描述附数据源 schema 摘要（目录读面，序列化时求值，不新造元数据）。
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from neurova.builtin_tools import (
    MAIN_AGENT_ONLY_TOOLS,
    _BUILTIN_SCHEMAS,
    get_builtin_tool_params,
)

TOOL = "enterprise_data_query"
SQL_OK = json.dumps({"sql": "SELECT id, customer_id, amount FROM orders"
                            " ORDER BY id DESC LIMIT 10",
                     "explanation": "最近 10 笔订单"})
SQL_DROP = json.dumps({"sql": "DROP TABLE orders", "explanation": "删表"})
SQL_INSERT = json.dumps({"sql": "INSERT INTO orders VALUES (9, 1, 1.0)",
                         "explanation": "插行"})


class _FakeLlmClient:
    """nl2sql 生成桩：固定回一段 JSON SQL（async chat，经 run_async_safely 桥）。"""

    def __init__(self, payload: str):
        self.payload = payload
        self.prompts: list = []

    async def chat(self, messages):
        self.prompts.append(messages[-1]["content"] if messages else "")
        return SimpleNamespace(content=self.payload)


def _make_executor(llm_client=None):
    from neurova.tool_executor import ToolExecutor

    agent = Mock()
    agent._skill_registry = Mock()
    agent.tool_router = Mock()
    agent.tool_memory = Mock()
    agent.tool_lifecycle = Mock()
    agent.skill_packer = Mock()
    agent.config = Mock()
    agent.config.agent_id = "agent-a"
    agent._current_user_id = "u1"
    agent.agent_id = "agent-a"
    agent.llm_client = llm_client
    agent.memory_manager = Mock()
    agent.asr_manager = None
    agent.tts_manager = None
    return ToolExecutor(agent)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture
def store(tmp_path, monkeypatch):
    from neurova.knowledge.foundation import knowledge_facts as kf

    s = kf.KnowledgeFactStore(str(tmp_path / "knowledge_facts.db"))
    monkeypatch.setattr(
        "neurova.knowledge.foundation.get_knowledge_fact_store", lambda: s)
    yield s
    s.close()


@pytest.fixture
def sideDb(tmp_path):
    path = tmp_path / "side.db"
    conn = sqlite3.connect(str(path))
    conn.executescript("""
        CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE orders (id INTEGER PRIMARY KEY, customer_id INTEGER
            REFERENCES customers(id), amount NUMERIC);
        INSERT INTO customers VALUES (1, 'kowloon');
        INSERT INTO orders VALUES (1, 1, 99.5), (2, 1, 100.5), (3, 1, 42.0);
    """)
    conn.commit()
    conn.close()
    return path


@pytest.fixture
def seededSource(store, sideDb):
    """企业源 schema 目录 + 源配置（default/erp），另配一个他租户源供越权断言。"""
    from neurova.knowledge.enterprise.connectors_sql import SqlDirectAdapter
    from neurova.knowledge.enterprise.registry import EnterpriseIngestor
    from neurova.knowledge.enterprise.schema_catalog import SchemaCatalogStore
    from neurova.knowledge.ontology.term_registry import OntologyTermRegistry

    adapter = SqlDirectAdapter({"driver": "sqlite", "database": str(sideDb),
                                "table": "orders", "cursorColumn": "id"}, "erp")
    cat = SchemaCatalogStore(store)
    schema = _run(adapter.describeSchema())
    relations = _run(adapter.describeRelations())
    cat.ingestSchema("default", "erp", "sql", schema, relations=relations)

    registry = OntologyTermRegistry(store)
    registry.register("Order", "concept", label="订单", tenantId="default")
    registry.register("Order", "concept", label="订单", tenantId="other-tenant")
    ingestor = EnterpriseIngestor(store, registry=registry)
    descriptor = {"sourceType": "sql", "driver": "sqlite",
                  "database": str(sideDb), "table": "orders",
                  "cursorColumn": "id", "columns": ["id"],
                  "subject": {"template": "order:{id}"},
                  "predicate": {"termId": "Order"},
                  "object": {"kind": "column", "column": "id"}}
    ingestor.saveConfig("default", "erp", descriptor, enabled=True)
    ingestor.saveConfig("other-tenant", "erp-other", dict(descriptor), enabled=True)
    return {"store": store, "side_db": str(sideDb)}


@pytest.fixture
def gateOn(monkeypatch):
    monkeypatch.setenv("NEUROVA_NL2SQL_ENABLED", "1")


@pytest.fixture
def tenantDefault(monkeypatch):
    monkeypatch.setattr("neurova.auth.user_group_model.currentUserTenantId",
                        lambda: "default")


class TestRegistration:
    def test_toolInSchemaSingleSource(self):
        """总闸开、工具必须已注册——未注册时调用只会得到未知工具（红灯起点）。"""
        entry = get_builtin_tool_params(TOOL)
        assert entry is not None, "enterprise_data_query 必须进 schema 单源"
        assert entry["parameters"]["required"] == ["question"]
        assert "question" in entry["parameters"]["properties"]
        assert "source_id" in entry["parameters"]["properties"]

    def test_dispatchRowPointsToRealMethod(self):
        from neurova.tool_executor import ToolExecutor

        assert ToolExecutor._builtin_dispatch.get(TOOL) == "_execute_enterprise_data_query"
        assert callable(getattr(ToolExecutor, "_execute_enterprise_data_query", None))

    def test_notInMainAgentOnlySet(self):
        """成员可用：不进 MAIN_AGENT_ONLY_TOOLS（成员剔除集）。"""
        assert TOOL not in MAIN_AGENT_ONLY_TOOLS

    def test_capabilityDeclaredReadOnly(self):
        from neurova.builtin_tools import get_builtin_tool_capability

        cap = get_builtin_tool_capability(TOOL)
        assert cap is not None and cap.readOnly is True

    def test_exploreMemberAllowlistContainsTool(self):
        """explore 型成员（只读白名单）能拿到该工具。"""
        from neurova.agent.swarm import computeSubagentToolAllowlist

        assert TOOL in computeSubagentToolAllowlist("explore")
        assert TOOL in computeSubagentToolAllowlist("general")


class TestGate:
    def test_gateOffStructuredCapabilityDisabled(self, store, monkeypatch, tenantDefault):
        """总闸关 → 结构化「能力未开启」工具错误，不抛裸异常。"""
        monkeypatch.delenv("NEUROVA_NL2SQL_ENABLED", raising=False)
        executor = _make_executor(llm_client=None)
        result = _run(executor.execute(TOOL, {"question": "最近 10 笔订单"}))
        assert result.get("success") is False
        assert result.get("code") == "capability_disabled"
        assert "NEUROVA_NL2SQL_ENABLED" in str(result.get("error", ""))

    def test_gateOnUnknownQuestionParam(self, store, gateOn, tenantDefault):
        executor = _make_executor(llm_client=None)
        result = _run(executor.execute(TOOL, {}))
        assert result.get("success") is False
        assert "question" in str(result.get("error", ""))


class TestReadonlyQuery:
    def test_recentOrdersReturnsRows(self, store, sideDb, seededSource, gateOn,
                                     tenantDefault):
        """开闸 + 内存 SQLite 数据源：『最近 N 笔订单』返回行数据。"""
        executor = _make_executor(llm_client=_FakeLlmClient(SQL_OK))
        result = _run(executor.execute(TOOL, {"question": "最近 10 笔订单"}))
        assert result.get("error") is None or result.get("status") == "ok", result
        assert result["status"] == "ok"
        assert result["answerable"] is True
        assert result["row_count"] >= 1
        assert result["rows"][0]["customer_id"] == 1
        assert "SELECT" in result["sql"].upper()
        assert result["source_id"] == "erp"

    def test_dropTableIntentRejectedAndNamed(self, store, sideDb, seededSource,
                                             gateOn, tenantDefault):
        """DROP 意图被只读断言拒绝并点名（管线校验层 + 连接器层双断言）。"""
        from neurova.knowledge.enterprise.connectors_sql import assertReadonlySelect
        from neurova.knowledge.enterprise.schema_mapping import MappingError

        with pytest.raises(MappingError, match="只读"):
            assertReadonlySelect("DROP TABLE orders")
        executor = _make_executor(llm_client=_FakeLlmClient(SQL_DROP))
        result = _run(executor.execute(TOOL, {"question": "把订单表删了"}))
        assert result.get("status") == "refused", result
        assert result.get("answerable") is False
        assert "只读" in str(result.get("reason", ""))

    def test_insertIntentRejectedAndNamed(self, store, sideDb, seededSource,
                                          gateOn, tenantDefault):
        from neurova.knowledge.enterprise.connectors_sql import assertReadonlySelect
        from neurova.knowledge.enterprise.schema_mapping import MappingError

        with pytest.raises(MappingError, match="写意图"):
            assertReadonlySelect("INSERT INTO orders VALUES (9, 1, 1.0)")
        executor = _make_executor(llm_client=_FakeLlmClient(SQL_INSERT))
        result = _run(executor.execute(TOOL, {"question": "塞一条假订单"}))
        assert result.get("status") == "refused", result
        assert "只读" in str(result.get("reason", ""))

    def test_otherTenantSourceRejected(self, store, sideDb, seededSource,
                                       gateOn, tenantDefault):
        """他租户 source_id：本租户查无配置 → 结构化拒绝。"""
        executor = _make_executor(llm_client=_FakeLlmClient(SQL_OK))
        result = _run(executor.execute(TOOL, {"question": "最近订单",
                                              "source_id": "erp-other"}))
        assert result.get("success") is False, result
        assert result.get("code") == "source_not_found"

    def test_unknownSourceRejected(self, store, sideDb, seededSource,
                                   gateOn, tenantDefault):
        executor = _make_executor(llm_client=_FakeLlmClient(SQL_OK))
        result = _run(executor.execute(TOOL, {"question": "最近订单",
                                              "source_id": "ghost"}))
        assert result.get("success") is False
        assert result.get("code") == "source_not_found"


class TestMemberThroat:
    def test_toolOutsideMemberAllowlistBlocked(self, store, gateOn, tenantDefault):
        """面外成员：执行咽喉强制拦截（subagent_tool_not_allowed），不可 bypass。"""
        from neurova.core.turn_context import set_subagent_tool_allowlist

        executor = _make_executor(llm_client=None)
        set_subagent_tool_allowlist(frozenset({"memory_search"}))
        try:
            result = _run(executor.execute(TOOL, {"question": "最近订单"}))
        finally:
            set_subagent_tool_allowlist(None)
        assert result.get("success") is False
        assert result.get("code") == "subagent_tool_not_allowed"


class TestDescriptionSchemaSummary:
    def test_descriptionCarriesCatalogSchemaSummary(self, store, sideDb,
                                                    seededSource, tenantDefault):
        """工具描述附数据源 schema 摘要（目录读面，不新造元数据）。"""
        from neurova.builtin_tools import BuiltinToolRegistry

        tool = BuiltinToolRegistry().get_tool(TOOL)
        desc = tool.to_openai_format()["function"]["description"]
        assert "orders" in desc
        assert "erp" in desc

    def test_descriptionFallsBackToBaseWithoutCatalog(self, store, tenantDefault):
        """目录为空（未摄取任何源）时回退基础描述（fail-soft，不炸暴露面）。"""
        from neurova.builtin_tools import BuiltinToolRegistry

        tool = BuiltinToolRegistry().get_tool(TOOL)
        desc = tool.to_openai_format()["function"]["description"]
        assert "企业数据" in desc
        assert "orders" not in desc
