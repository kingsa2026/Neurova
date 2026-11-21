# -*- coding: utf-8 -*-
"""E2 契约兼容守卫（参照系 ac 借鉴）：wire 契约"历史样例/既有键集"解码回归。

纪律：改 schema 必须照顾存量消费方——本守卫钉住三类既有 wire 面：
1. SubAgentRun.to_dict() 的历史键集只增不减（前端/台账/档案投影消费）；
2. runEvents 读侧结构稳定（事件账本消费面）；
3. 蜂群三工具 schema 的 required/既有参数不缩水（新增只许可选增量，
   如批一的 command_id/replayed——新增字段对旧调用方透明）。
配套登记表：docs/09-dev-progress/contract-change-log.md（破坏性变更须先登记迁移路径）。
"""
import pytest

from neurova.agent.swarm_support import SubAgentRun
from neurova.builtin_tools import (
    get_builtin_tool_params,
    get_registered_tool_names,
)

# 2026-11-21 冻结读数：SubAgentRun.to_dict 历史键集（批一前既有全集）。
# 只许增（新增可选字段），不许删/改名——消费方（前端 run 卡、台账、
# 协作档案、候选投影）按这些键取数。
HISTORICAL_RUN_KEYS = {
    "subagent_id", "agent_id", "agent_name", "task", "model", "origin",
    "depth", "session_id", "member_session_id", "subagent_type",
    "task_unit", "acceptance", "review", "approvals", "parent_trace_id",
    "trace_id", "data_fence", "escalation", "submitted_result",
    "tool_allowlist_size", "status", "report", "error", "started_at",
    "finished_at", "duration", "node_id", "execution_id", "resumed_from",
    "room_id", "project_id", "team_id", "team_role",
}

# 2026-11-21 冻结读数：蜂群核心工具名（历史名册子集，只增不减）。
HISTORICAL_TOOL_NAMES = {
    "spawn_subagent", "subagent_status", "continue_subagent",
    "cancel_subagent", "list_teams", "dispatch_team", "propose_team",
    "request_approval", "decide_subagent_approval",
}

# 事件账本 record 的历史键集（H-4/F2 消费面）。
HISTORICAL_EVENT_KEYS = {
    "event_id", "type", "subagent_id", "causation_id", "payload",
    "occurred_at", "seq",
}


def _makeRun() -> SubAgentRun:
    return SubAgentRun(
        subagent_id="run-e2e", depth=1, agent_id="agent-x", agent_name="X",
        task="契约样例任务", origin="chat", session_id="sess-e2e",
        subagent_type="general", team_id="t-e2e", team_role="coder",
        report="样例产出", status="completed",
    )


class TestRunDictBackwardCompat:
    def test_run_dict_keeps_historical_keys(self):
        run = _makeRun()
        keys = set(run.to_dict().keys())
        missing = HISTORICAL_RUN_KEYS - keys
        assert missing == set(), f"to_dict 丢失历史键：{sorted(missing)}——wire 契约缩水"

    def test_run_dict_accepts_legacy_shape(self):
        """历史调用形态（只传早期字段）仍可构造且 to_dict 可用。"""
        legacy = SubAgentRun(
            subagent_id="run-legacy", depth=1, agent_id="agent-y",
            agent_name="Y", task="旧形态任务", origin="chat",
        )
        payload = legacy.to_dict()
        assert payload["subagent_id"] == "run-legacy"
        assert payload["task"] == "旧形态任务"
        assert set(HISTORICAL_RUN_KEYS) <= set(payload.keys())


class TestRunEventsShape:
    def test_run_events_structure_stable(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path))
        from neurova.agent.swarm_event_log import appendRunEvent, readRunEvents

        event_id = appendRunEvent("run-e2e-ev", "spawned", {"task": "样例"})
        events = readRunEvents("run-e2e-ev")
        assert len(events) == 1
        record = events[0]
        missing = HISTORICAL_EVENT_KEYS - set(record.keys())
        assert missing == set(), f"事件 record 丢失历史键：{sorted(missing)}"
        assert record["event_id"] == event_id
        assert isinstance(record["seq"], int) and record["seq"] >= 1

    def test_run_events_unknown_id_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path))
        from neurova.agent.swarm_event_log import readRunEvents

        assert readRunEvents("no-such-run") == []


class TestSwarmToolSchemas:
    def test_historical_tool_names_present(self):
        names = set(get_registered_tool_names())
        missing = HISTORICAL_TOOL_NAMES - names
        assert missing == set(), f"工具名册丢失历史工具：{sorted(missing)}"

    @pytest.mark.parametrize("tool,required", [
        ("dispatch_team", ["team_id", "task"]),
        ("continue_subagent", ["subagent_id", "message"]),
        ("cancel_subagent", ["subagent_id"]),
    ])
    def test_swarm_tool_required_stable(self, tool, required):
        schema = get_builtin_tool_params(tool)
        assert schema is not None, f"{tool} schema 缺失"
        params = schema.get("parameters") or {}
        assert sorted(params.get("required") or []) == sorted(required), (
            f"{tool} required 集合变化——破坏性变更须先登记 "
            "docs/09-dev-progress/contract-change-log.md"
        )

    @pytest.mark.parametrize("tool,legacy_param", [
        ("dispatch_team", "task_unit"),
        ("dispatch_team", "background"),
        ("continue_subagent", "mode"),
        ("continue_subagent", "background"),
        ("cancel_subagent", "reason"),
    ])
    def test_swarm_tool_legacy_params_survive(self, tool, legacy_param):
        schema = get_builtin_tool_params(tool)
        props = (schema.get("parameters") or {}).get("properties") or {}
        assert legacy_param in props, f"{tool}.{legacy_param} 既有参数被移除"

    def test_new_optional_params_are_additive(self):
        """批一新增的 command_id 必须是可选增量（不出现在 required）。"""
        for tool in ("dispatch_team", "continue_subagent", "cancel_subagent"):
            schema = get_builtin_tool_params(tool)
            props = (schema.get("parameters") or {}).get("properties") or {}
            required = set((schema.get("parameters") or {}).get("required") or [])
            assert "command_id" in props, f"{tool} 缺 command_id 增量参数"
            assert "command_id" not in required
