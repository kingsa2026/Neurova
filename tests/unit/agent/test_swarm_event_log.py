# -*- coding: utf-8 -*-
"""H-4 蜂群事件因果链 + run 级事件归档单元测试（对照评测改进项）。

覆盖：
- 事件账本 append/read 往返（JSONL，逐行事件）；
- 因果链：同 run 内后一事件的 causation_id == 前一事件的 event_id；
- 真 spawn 链路：spawned → started → terminal 顺序落档，失败 run 的 terminal
  带失败成因；正文不进账本（信封同纪律）；
- fail-open：归档故障不阻断 spawn 主流程。
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from neurova.agent.swarm import (
    SUBAGENT_PENDING,
    get_swarm_manager,
    reset_swarm_manager,
)
from neurova.agent.swarm_event_log import appendRunEvent, readRunEvents


def make_agent(reply="任务完成报告"):
    agent = MagicMock()
    agent.config.name = "子Agent"
    agent.chat = AsyncMock(return_value={"text": reply})
    return agent


@pytest.fixture
def swarm():
    reset_swarm_manager()
    yield get_swarm_manager()
    reset_swarm_manager()


class TestEventLogStore:
    def test_append_read_roundtrip(self):
        eid = appendRunEvent("swarm_evt1", "spawned", {"task": "调研"}, causationId="tr-parent")
        events = readRunEvents("swarm_evt1")
        assert len(events) == 1
        assert events[0]["event_id"] == eid
        assert events[0]["type"] == "spawned"
        assert events[0]["causation_id"] == "tr-parent"
        assert events[0]["payload"] == {"task": "调研"}
        assert events[0]["occurred_at"]

    def test_multiple_events_append_in_order(self):
        appendRunEvent("swarm_evt2", "spawned", {})
        appendRunEvent("swarm_evt2", "started", {})
        events = readRunEvents("swarm_evt2")
        assert [e["type"] for e in events] == ["spawned", "started"]

    def test_read_unknown_run_returns_empty(self):
        assert readRunEvents("swarm_never_existed") == []

    def test_corrupt_line_skipped_not_fatal(self):
        from pathlib import Path

        from neurova.core.data_root import dataPath

        appendRunEvent("swarm_evt3", "spawned", {})
        p = Path(dataPath("swarm_runs")) / "swarm_evt3.events.jsonl"
        with open(p, "a", encoding="utf-8") as f:
            f.write("{这行不是 JSON}\n")
        assert len(readRunEvents("swarm_evt3")) == 1


class TestSpawnLifecycleEvents:
    @pytest.mark.asyncio
    async def test_lifecycle_events_chained(self, swarm):
        with patch("neurova.api.endpoints.get_agent_instance", return_value=make_agent()):
            result = await swarm.spawn(task="子任务内容", agent_id="researcher")
        events = readRunEvents(result["subagent_id"])
        types = [e["type"] for e in events]
        assert types[0] == "spawned"
        assert "started" in types
        assert types[-1] == "terminal"
        # 因果链：后一事的 causation_id 指向前一事
        for prev, cur in zip(events, events[1:]):
            assert cur["causation_id"] == prev["event_id"], (
                f"因果链断裂于 {prev['type']} → {cur['type']}"
            )
        terminal = events[-1]
        assert terminal["payload"]["status"] == "completed"
        # 正文不进账本（信封同纪律）：任务只留摘要位，报告正文不入 payload
        assert all("任务完成报告" not in json.dumps(e, ensure_ascii=False) for e in events)

    @pytest.mark.asyncio
    async def test_failed_run_terminal_carries_cause(self, swarm):
        agent = make_agent()
        agent.chat = AsyncMock(side_effect=RuntimeError("上游 503"))
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            result = await swarm.spawn(task="会失败", agent_id="researcher")
        events = readRunEvents(result["subagent_id"])
        terminal = events[-1]
        assert terminal["type"] == "terminal"
        assert terminal["payload"]["status"] == "failed"
        assert "503" in json.dumps(terminal["payload"], ensure_ascii=False)

    @pytest.mark.asyncio
    async def test_archive_failure_does_not_block_spawn(self, swarm):
        with patch("neurova.api.endpoints.get_agent_instance", return_value=make_agent()), \
             patch("neurova.agent.swarm_event_log.appendRunEvent",
                   side_effect=OSError("disk full")):
            result = await swarm.spawn(task="子任务", agent_id="researcher")
        assert result["status"] == "completed", "归档故障不得阻断蜂群主流程（fail-open）"


class TestStatusEventsView:
    """H-4 闭环读侧：subagent_status(view=events) 返回 run 事件账本（因果链完整）。"""

    @pytest.mark.asyncio
    async def test_status_view_events_returns_chained_events(self, swarm):
        from neurova.tool_executor import ToolExecutor

        with patch("neurova.api.endpoints.get_agent_instance", return_value=make_agent()):
            result = await swarm.spawn(task="子任务内容", agent_id="researcher")
        exe = ToolExecutor(MagicMock())
        view = await exe._execute_subagent_status(
            {"subagent_id": result["subagent_id"], "view": "events"}
        )
        assert view["subagent_id"] == result["subagent_id"]
        types = [e["type"] for e in view["events"]]
        assert types[0] == "spawned" and types[-1] == "terminal"
        for prev, cur in zip(view["events"], view["events"][1:]):
            assert cur["causation_id"] == prev["event_id"]

    @pytest.mark.asyncio
    async def test_status_view_events_requires_id(self):
        from neurova.tool_executor import ToolExecutor

        exe = ToolExecutor(MagicMock())
        result = await exe._execute_subagent_status({"view": "events"})
        assert "error" in result

    def test_swarm_run_events_method(self, swarm):
        appendRunEvent("swarm_evt9", "spawned", {"task": "t"})
        view = swarm.runEvents("swarm_evt9")
        assert view["subagent_id"] == "swarm_evt9"
        assert view["count"] == 1
        assert view["events"][0]["type"] == "spawned"
