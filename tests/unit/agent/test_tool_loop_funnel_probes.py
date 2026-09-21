"""001 · 三链路探针基座：工具调用 → 经验记忆 → 再调用，当前必须全红。

本文件只交付探针与红灯基线，**不修任何生产代码**。后面每张票都以
"某条探针转绿"为收工判据：

- P-a 产票：一轮原生工具调用后 `resolve_ticket_evidence(...).lookup == "evidenced"`
- P-b 形状：`_collect_tool_messages()` 里每条记录都合形状契约（tool_call 有
  `tool_name`、tool_result 有顶层 `success`）
- P-c 传导：EKB 新行 `skill_name` 不含 `unknown`，`success` 位与本轮客观回执一致

三条探针各配一条**反向锁**：证明拦阻者确实是根因、探针本身没写错。
反向锁只准在 tmp 库/内存态上造，不得成为生产通路——否则后续票的收编会被它假装满足。

取证必须在**同一个 asyncio 任务**内完成：轮次工具记录与票据上下文都挂在 ContextVar 上，
`asyncio.run` 返回后外层读到的是干净副本，拿不到本轮值。
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List

import pytest

from neurova.agent.turn_state import resolve_tool_outcome
from neurova.evolution.objective_evidence import (
    TICKET_ABSENT,
    TICKET_EVIDENCED,
    resolve_ticket_evidence,
)
from neurova.skills.creation_governance import (
    begin_task,
    flush_task,
    record_tool_execution,
)
from neurova.skills.skill_service import SkillService

from .conftest import read_experience_rows, shape_violations, text_chunk, tool_call_chunk

TOOL_NAME = "get_datetime"
ANSWER = "现在是 2026 年"


def run_turn(probe, rounds: List[List[Any]], user_input: str = "现在几点了",
             stream: bool = True) -> Dict[str, Any]:
    """经 `Agent.chat` 生产入口跑一轮，并在同一任务内取全部读数。"""
    probe.bind(rounds)
    agent = probe.agent

    async def _go() -> Dict[str, Any]:
        result = await agent.chat(user_input, session_id="probe-session", stream=stream)
        await agent.post_chat_pipeline.drain_background(timeout=60)
        records = agent.chat_pipeline._collect_tool_messages()
        return {
            "reply": result.get("text") if isinstance(result, dict) else str(result),
            "records": records,
            "outcome": resolve_tool_outcome(records),
            "ticket": resolve_ticket_evidence(agent, records),
        }

    readings = asyncio.run(_go())
    readings["experience_rows"] = read_experience_rows()
    return readings


def tool_round(tool_name: str = TOOL_NAME, arguments: str = "{}") -> List[List[Any]]:
    return [[tool_call_chunk("call_probe", tool_name, arguments)], [text_chunk(ANSWER)]]


class TestProbeShape:
    """P-b：取证源只有一个形状。"""

    def test_native_tool_records_are_flat(self, loop_probe):
        readings = run_turn(loop_probe, tool_round())
        assert readings["records"], "本轮没有任何工具记录，探针失去取证对象"
        assert shape_violations(readings["records"]) == [], (
            "原生链把包装事件（{type,data}）写进了取证源："
            f"{shape_violations(readings['records'])}"
        )

    def test_reverse_lock_flat_records_pass_shape_contract(self):
        """反向锁：形状正确即放行，违规即点名——证明拦的是形状。"""
        flat = [
            {"type": "tool_call", "tool_name": TOOL_NAME, "params": {}},
            {"type": "tool_result", "tool_name": TOOL_NAME, "success": True, "result": "ok"},
        ]
        assert shape_violations(flat) == []
        assert shape_violations([{"type": "tool_call", "data": {}}]) != []


class TestProbeTicket:
    """P-a：一轮原生工具调用必须产出服务端票据。"""

    def test_native_round_reaches_evidenced_ticket(self, loop_probe):
        readings = run_turn(loop_probe, tool_round())
        ticket = readings["ticket"]
        assert ticket.lookup == TICKET_EVIDENCED, (
            f"原生链不产票：lookup={ticket.lookup}，reason={ticket.verdict.reason}"
        )

    def test_reverse_lock_ticket_is_readable_through_production_store(self, loop_probe):
        """反向锁：走生产写入路径造一张票 ⇒ 探针读得到。

        只证"探针能读"，不证"生产通路已接线"——后者由上面那条用例判。
        """
        service = SkillService(agent_id=loop_probe.agent.config.agent_id)
        begin_task()
        record_tool_execution(TOOL_NAME, {}, True, {"datetime": "2026-09-21"})
        assert flush_task(service, "现在几点了", completed=True) is not None
        stored = service.creation_evidence.task_results([{"tool": TOOL_NAME, "params": {}}])
        assert stored, "生产写入路径没落下票据，反向锁无法成立"
        records = [{"type": "tool_call", "tool_name": TOOL_NAME, "params": {}}]
        evidence = resolve_ticket_evidence(loop_probe.agent, records)
        assert evidence.lookup == TICKET_EVIDENCED, (
            f"写入的票据读不回来：lookup={evidence.lookup}"
        )


class TestProbePropagation:
    """P-c：经验位必须带着正确的成败与工具名。"""

    def test_ekb_row_carries_tool_name_and_objective_success(self, loop_probe):
        readings = run_turn(loop_probe, tool_round())
        rows = readings["experience_rows"]
        assert rows, "本轮没有 EKB 落库行，传导链断在写入侧"
        for row in rows:
            assert "unknown" not in str(row["skill_name"]), (
                f"EKB 行 skill_name 含 unknown（包装事件被当工具名读）：{row['skill_name']}"
            )
        assert readings["outcome"] is True, "本轮工具回执为成功，三态聚合却没给出 True"

    def test_reverse_lock_outcome_reads_only_tool_result(self):
        """反向锁：成败只由 tool_result 携带；tool_call 不携带 success。"""
        assert resolve_tool_outcome([{"type": "tool_call", "tool_name": TOOL_NAME}]) is None
        assert resolve_tool_outcome(
            [{"type": "tool_result", "tool_name": TOOL_NAME, "success": True}]
        ) is True


class TestProbeExperienceMetrics:
    """009：度量要真的落到生产写侧的库行上（不以"传了参"代替）。"""

    def test_turn_writes_elapsed_and_structure_key(self, loop_probe):
        import json

        readings = run_turn(loop_probe, tool_round())
        rows = read_experience_rows(
            columns="id, skill_name, context, success, execution_time, confidence_score"
        )
        assert rows, "本轮没有落库行"
        row = rows[-1]
        assert row["execution_time"] is not None and row["execution_time"] > 0, (
            f"耗时列仍为空（咽喉没把 elapsed 交出来）：{row}"
        )
        context = row["context"]
        context = json.loads(context) if isinstance(context, str) else context
        assert context.get("structure_key"), f"结构指纹没有落库：{context}"
        assert '"params"' not in json.dumps(context), "结构身份只存指纹，不得存参数明文"

    def test_structure_key_matches_the_choke_single_source(self, loop_probe):
        """指纹必须与咽喉票据同函数产出（单源），不许另写一份算法。"""
        from neurova.skills.creation_governance import structure_key

        readings = run_turn(loop_probe, tool_round())
        assert readings["ticket"].steps, "本轮票据没有 steps，无法比对结构身份"
        expected = structure_key([dict(step) for step in readings["ticket"].steps])
        rows = read_experience_rows(columns="id, context")
        import json

        context = rows[-1]["context"]
        context = json.loads(context) if isinstance(context, str) else context
        assert context.get("structure_key") == expected
