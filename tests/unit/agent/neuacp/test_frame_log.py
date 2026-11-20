# -*- coding: utf-8 -*-
"""F2 红灯：neuacp 帧账本（frame_log）契约测试（设计文档 §3.2）。

覆盖：record 形态、direction 校验、路径净化与 events 同规则、seq 与 events
账本独立单调、写盘前脱敏、游标回放（afterSeq/limit）、坏行容错、
执行体 frame_key 接线（start(ctx.metadata["subagent_id"]) → 帧落盘）。
"""

import asyncio
import sys
import threading
from pathlib import Path

import pytest

from neurova.agent.neuacp.frame_log import appendFrame, readFrames
from neurova.agent.swarm_event_log import appendRunEvent, readRunEvents
from neurova.core.data_root import dataPath

FAKE_AGENT = Path(__file__).with_name("fake_acp_agent.py")


class TestAppendFrameContract:
    def test_appendReadRoundtripRecordShape(self):
        seq = appendFrame("sw_frame1", "in", {"jsonrpc": "2.0", "method": "session/update"})
        assert seq == 1
        records = readFrames("sw_frame1")
        assert len(records) == 1
        rec = records[0]
        assert rec["seq"] == 1
        assert rec["subagent_id"] == "sw_frame1"
        assert rec["direction"] == "in"
        assert rec["frame"] == {"jsonrpc": "2.0", "method": "session/update"}
        assert rec["occurred_at"]

    def test_seqIncrementsPerFrame(self):
        first = appendFrame("sw_frame2", "out", {"n": 1})
        second = appendFrame("sw_frame2", "in", {"n": 2})
        third = appendFrame("sw_frame2", "observed", {"type": "exited"})
        assert (first, second, third) == (1, 2, 3)

    def test_seqIndependentFromEventsLedger(self):
        appendRunEvent("sw_frame3", "spawned", {})
        appendRunEvent("sw_frame3", "started", {})
        first_frame_seq = appendFrame("sw_frame3", "in", {"a": 1})
        assert first_frame_seq == 1, "帧账本 seq 独立起算，不随 events 账本续接"
        assert [e["seq"] for e in readRunEvents("sw_frame3")] == [1, 2]

    def test_directionMustBeInOutObserved(self):
        for direction in ("in", "out", "observed"):
            appendFrame("sw_frame4", direction, {"d": direction})
        with pytest.raises(ValueError):
            appendFrame("sw_frame4", "sideways", {"d": 1})
        with pytest.raises(ValueError):
            appendFrame("sw_frame4", "", {})

    def test_emptySubagentIdRejected(self):
        with pytest.raises(ValueError):
            appendFrame("", "in", {"a": 1})
        with pytest.raises(ValueError):
            appendFrame("   ", "in", {"a": 1})

    def test_pathSanitizedSameRuleAsEvents(self):
        # 与 swarm_event_log._eventsPath 同规则：只留字母数字与 ._-，净化后为空 → ValueError
        appendFrame("sw_frame5/../peek", "in", {"a": 1})
        with pytest.raises(ValueError):
            appendFrame("///", "in", {"a": 1})

    def test_frameRedactedBeforeWrite(self):
        appendFrame("sw_frame6", "in", {
            "method": "session/prompt",
            "params": {"api_key": "sk-abcdef1234567890", "text": "正文"},
        })
        rec = readFrames("sw_frame6")[0]
        assert rec["frame"]["params"]["api_key"] == "[redacted]"
        assert rec["frame"]["params"]["text"] == "正文"

    def test_lineageLandsInRecord(self):
        lineage = {"tenant_id": "t-9", "agent_path": ["p", "c"]}
        appendFrame("sw_frame7", "out", {"a": 1}, lineage=lineage)
        rec = readFrames("sw_frame7")[0]
        assert rec["lineage"] == lineage

    def test_concurrentAppendsSeqUnique(self):
        run_id = "sw_frame8"
        workers = 6
        per_worker = 4
        barrier = threading.Barrier(workers)
        failures = []

        def worker(index: int):
            barrier.wait()
            try:
                for i in range(per_worker):
                    appendFrame(run_id, "in", {"worker": index, "i": i})
            except Exception as exc:  # pragma: no cover
                failures.append(repr(exc))

        threads = [threading.Thread(target=worker, args=(n,)) for n in range(workers)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not failures
        seqs = [r["seq"] for r in readFrames(run_id)]
        assert len(seqs) == workers * per_worker
        assert len(set(seqs)) == workers * per_worker, "并发追加 seq 不得重复"
        assert seqs == sorted(seqs), "文件序与 seq 序一致"


class TestReadFrames:
    def test_unknownRunReturnsEmpty(self):
        assert readFrames("sw_frame_never") == []

    def test_afterSeqCursor(self):
        for i in range(3):
            appendFrame("sw_frame10", "out", {"i": i})
        records = readFrames("sw_frame10", afterSeq=1)
        assert [r["seq"] for r in records] == [2, 3]
        assert [r["frame"]["i"] for r in records] == [1, 2]

    def test_limit(self):
        for i in range(5):
            appendFrame("sw_frame11", "out", {"i": i})
        records = readFrames("sw_frame11", limit=2)
        assert [r["seq"] for r in records] == [1, 2]

    def test_corruptLineSkippedNotFatal(self):
        appendFrame("sw_frame12", "in", {"a": 1})
        path = Path(dataPath("swarm_runs")) / "sw_frame12.frames.jsonl"
        with open(path, "a", encoding="utf-8") as f:
            f.write("{这行不是 JSON}\n")
        appendFrame("sw_frame12", "in", {"a": 2})
        records = readFrames("sw_frame12")
        assert [r["frame"] for r in records] == [{"a": 1}, {"a": 2}]


class TestExecutorFrameKeyWiring:
    """任务 5：执行体 start(ctx) 从 ctx.metadata 取 subagent_id 接 frame_key。"""

    def _makeStdioExecutor(self, mode):
        from neurova.agent.neuacp.acp_executor import NeuacpStdioExecutor
        from neurova.agent.neuacp.executor import NeuacpSessionContext

        executor = NeuacpStdioExecutor(
            [sys.executable, str(FAKE_AGENT)],
            cwd=str(FAKE_AGENT.parent),
            env_extra={"FAKE_ACP_MODE": mode},
        )
        ctx = NeuacpSessionContext(
            member_session_id="m-1", task_text="写个登录页", cwd=str(FAKE_AGENT.parent),
        )
        return executor, ctx

    def test_stdioExecutorWiresFrameKeyFromMetadata(self):
        async def run():
            executor, ctx = self._makeStdioExecutor("acp_flow")
            ctx.metadata = {"subagent_id": "sw_frame_exec1"}
            await executor.start(ctx)
            result = await executor.prompt("写个登录页", lambda kind, text: None, None)
            await executor.close()
            return result

        result = asyncio.run(run())
        assert result.text == "你好 Neuacp"
        records = readFrames("sw_frame_exec1")
        directions = [r["direction"] for r in records]
        # 全序：initialize 往返 → session/new 往返 → session/prompt + 2×update + result → 退出观测
        assert directions == ["out", "in", "out", "in", "out", "in", "in", "in", "observed"], (
            f"帧序不符：{directions}"
        )
        # 时序：我们发出的 initialize 请求是流内第一帧
        assert records[0]["frame"]["method"] == "initialize"
        # 入站通知按序落盘（session/update 在 result 应答之前）
        in_methods = [r["frame"].get("method") for r in records if r["direction"] == "in"]
        assert in_methods.count("session/update") == 2
        # 退出观测：close 后 observed/exited 收尾，seq 严格递增
        assert records[-1]["direction"] == "observed"
        assert records[-1]["frame"]["type"] == "exited"
        seqs = [r["seq"] for r in records]
        assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)

    def test_stdioExecutorWithoutSubagentIdKeepsNoFrameLog(self):
        runs_dir = Path(dataPath("swarm_runs"))
        before = {p.name for p in runs_dir.glob("*.frames.jsonl")} if runs_dir.exists() else set()

        async def run():
            executor, ctx = self._makeStdioExecutor("ok")
            ctx.metadata = {}
            await executor.start(ctx)
            await executor.prompt("任务", lambda kind, text: None, None)
            await executor.close()

        asyncio.run(run())
        after = {p.name for p in runs_dir.glob("*.frames.jsonl")} if runs_dir.exists() else set()
        assert after == before, "metadata 无 subagent_id（无主会话）不得新增任何帧账本文件"
