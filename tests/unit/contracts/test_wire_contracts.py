# -*- coding: utf-8 -*-
"""E2 契约单源包自检：neurova.contracts.wire 派生层与代码事实源逐项咬合。

派生层纪律（教义第 6 条）：契约形状只从事实源现场派生——
- 工具目录 ← builtin_tools 声明位（经 neurova.tools.catalog 投影）；
- run 投影键集 ← SubAgentRun.to_dict 真实键集；
- 事件类型词值 ← swarm_event_log 全部写入调用点源码；
- continue_subagent mode 枚举 ← builtin_tools schema 的 mode.enum。
本文件钉三件事：与事实源咬合一致、重复调用稳定、fail-closed
（事实源不可达/形状缺失时显式抛错，不返回静默空表）。
"""
import pytest

from neurova.builtin_tools import (
    _BUILTIN_SCHEMAS,
    get_builtin_tool_params,
    get_registered_tool_names,
)
from neurova.contracts import wire


class TestToolCatalogEntries:
    def test_entries_derive_from_registered_tool_names(self):
        entries = wire.toolCatalogEntries()
        assert entries, "工具目录派生为空——fail-closed 失效"
        assert {e["name"] for e in entries} == set(get_registered_tool_names()), (
            "派生条目与 builtin_tools 注册名册不一致"
        )

    def test_entries_match_catalog_projection(self):
        """与 tools/catalog 投影同读数（wire 层是消费入口，不另造推导）。"""
        from neurova.tools.catalog import build_snapshot

        assert wire.toolCatalogEntries() == build_snapshot()["tools"]

    def test_entry_schema_matches_declaration(self):
        entries = {e["name"]: e for e in wire.toolCatalogEntries()}
        for name in ("continue_subagent", "dispatch_team", "cancel_subagent"):
            declared = get_builtin_tool_params(name) or {}
            assert entries[name]["args_schema"] == declared.get("parameters"), (
                f"{name} 派生 schema 与声明位不一致"
            )

    def test_entries_fail_closed_on_empty_projection(self, monkeypatch):
        from neurova.tools import catalog as catalogModule

        def _emptySnapshot():
            return {"schema": 1, "source": "test", "tool_count": 0, "tools": []}

        monkeypatch.setattr(catalogModule, "build_snapshot", _emptySnapshot)
        with pytest.raises(RuntimeError, match="工具目录派生为空"):
            wire.toolCatalogEntries()


class TestRunProjectionKeys:
    def test_keys_derive_from_real_to_dict(self):
        from neurova.agent.swarm_support import SubAgentRun

        probe = SubAgentRun(subagent_id="contract-probe", depth=1)
        assert wire.runProjectionKeys() == frozenset(probe.to_dict().keys()), (
            "派生键集与 SubAgentRun.to_dict 真实键集不一致"
        )

    def test_keys_are_non_empty_and_stable(self):
        keys = wire.runProjectionKeys()
        assert keys, "run 投影键集派生为空——fail-closed 失效"
        assert wire.runProjectionKeys() == keys

    def test_keys_fail_closed_on_empty_projection(self, monkeypatch):
        from neurova.agent import swarm_support as swarmSupport

        class _EmptyRun:
            def __init__(self, *args, **kwargs):
                pass

            @staticmethod
            def to_dict():
                return {}

        monkeypatch.setattr(swarmSupport, "SubAgentRun", _EmptyRun)
        with pytest.raises(RuntimeError, match="run 投影键集派生为空"):
            wire.runProjectionKeys()


class TestEventTypes:
    def test_types_derive_from_call_sites(self):
        types = wire.eventTypes()
        assert types, "事件类型派生为空——fail-closed 失效"
        # 已知写入账本的词值必须被调用点扫描覆盖；漏一个=扫描器漏了一种调用形态
        for known in (
            "spawned", "started", "terminal", "cancelled", "status_changed",
            "tool_call", "member_chunk", "permission_decided", "escalated",
            "result_submitted", "candidate_merged", "forked",
        ):
            assert known in types, f"事件类型扫描漏了已知词值 {known}"

    def test_types_are_sorted_unique_and_stable(self):
        first = wire.eventTypes()
        assert list(first) == sorted(set(first)), "事件类型必须去重且按名排序"
        assert wire.eventTypes() == first, "重复调用读数漂移"

    def test_types_fail_closed_when_call_sites_unreadable(self, monkeypatch):
        monkeypatch.setattr(wire, "_EVENT_CALL_SITE_MODULES", ("no/such/module.py",))
        with pytest.raises(RuntimeError, match="事件类型派生失败"):
            wire.eventTypes()


class TestContinueSubagentModes:
    def test_modes_derive_from_schema_enum(self):
        schema = get_builtin_tool_params("continue_subagent")
        assert schema is not None, "continue_subagent schema 缺失"
        enum = (schema.get("parameters") or {}).get("properties", {}).get("mode", {}).get("enum")
        assert wire.continueSubagentModes() == tuple(enum or ()), (
            "mode 枚举派生与 schema 声明不一致"
        )

    def test_modes_are_non_empty_and_stable(self):
        modes = wire.continueSubagentModes()
        assert modes, "mode 枚举派生为空——fail-closed 失效"
        assert wire.continueSubagentModes() == modes

    def test_modes_fail_closed_when_schema_missing(self, monkeypatch):
        monkeypatch.delitem(_BUILTIN_SCHEMAS, "continue_subagent")
        with pytest.raises(RuntimeError, match="continue_subagent"):
            wire.continueSubagentModes()
