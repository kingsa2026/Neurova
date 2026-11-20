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


class TestSeqAndLineage:
    """F2/F5：H-4 账本补 per-run 单调 seq 与 lineage 谱系（设计文档 §3.2/§3.5）。

    seq 语义：同一路径（同一 run 的账本文件）内从 1 起单调递增；写入在既有
    全局锁内完成，文件序与 seq 序一致；旧文件无 seq 行容错，新事件从最大值续起。
    """

    def test_seqStrictlyIncreasesForSameRun(self):
        for _ in range(3):
            appendRunEvent("swarm_seq1", "member_chunk", {"n": 1})
        events = readRunEvents("swarm_seq1")
        seqs = [e["seq"] for e in events]
        assert len(seqs) == 3
        assert all(isinstance(s, int) for s in seqs)
        assert seqs == sorted(seqs), "账本文件序应与 seq 序一致"
        assert len(set(seqs)) == len(seqs), "seq 不得重复"
        assert seqs == [1, 2, 3], f"同 run 连续追加应从 1 严格递增，实际 {seqs}"

    def test_concurrentAppendsSeqUniqueAndIncreasing(self):
        import threading

        run_id = "swarm_seq2"
        workers = 8
        per_worker = 5
        barrier = threading.Barrier(workers)
        failures = []

        def worker(index: int):
            barrier.wait()
            try:
                for i in range(per_worker):
                    appendRunEvent(run_id, "member_chunk", {"worker": index, "i": i})
            except Exception as exc:  # pragma: no cover - 失败要显性化
                failures.append(repr(exc))

        threads = [threading.Thread(target=worker, args=(n,)) for n in range(workers)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not failures, f"并发追加抛错：{failures}"
        events = readRunEvents(run_id)
        assert len(events) == workers * per_worker
        seqs = [e["seq"] for e in events]
        assert len(set(seqs)) == workers * per_worker, "并发写入 seq 不得重复"
        assert seqs == sorted(seqs), "并发写入后文件序仍应与 seq 序一致（写入在全局锁内）"

    def test_lineageLandsInRecord(self):
        lineage = {"tenant_id": "t-1", "team_id": "team-9", "agent_path": ["p", "c"]}
        appendRunEvent("swarm_lin1", "spawned", {}, lineage=lineage)
        record = readRunEvents("swarm_lin1")[0]
        assert record["lineage"] == lineage

    def test_lineageOmittedWhenEmpty(self):
        appendRunEvent("swarm_lin2", "spawned", {})
        record = readRunEvents("swarm_lin2")[0]
        assert "lineage" not in record, "lineage 非空才放入 record"

    def test_seqContinuesAfterLegacyLinesWithoutSeq(self):
        from pathlib import Path

        from neurova.core.data_root import dataPath

        run_id = "swarm_seq3"
        path = Path(dataPath("swarm_runs")) / f"{run_id}.events.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        # 旧形态行：无 seq 字段。先于本进程任何 append 落盘，命中"首次扫描"路径。
        legacy = {
            "event_id": "evt_legacy",
            "type": "started",
            "subagent_id": run_id,
            "causation_id": "",
            "payload": {},
            "occurred_at": "2026-01-01T00:00:00+00:00",
        }
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(legacy, ensure_ascii=False) + "\n")
        appendRunEvent(run_id, "spawned", {})
        appendRunEvent(run_id, "terminal", {})
        events = readRunEvents(run_id)
        assert len(events) == 3
        assert "seq" not in events[0], "旧文件无 seq 行须容错（原样读出）"
        assert events[1]["seq"] == 1 and events[2]["seq"] == 2, "新事件从扫描到的最大 seq 续起"
