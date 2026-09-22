"""工具↔经验↔再调用环路的只读取证入口（工单 001 的落点，现场排障用）。

回答三个问题，一条命令一次给全：

1. **产票了吗**：一轮工具调用后 `resolve_ticket_evidence(...).lookup` 与
   `ticket_reason`（`absent` = 服务端确实没这张票，`unreadable` = 取证面断了）；
2. **形状对不对**：本轮取证源里每条记录是否合形状契约（违规逐条点名）；
3. **经验有没有带对成败**：三态聚合 `outcome` 与 EKB 落库行数。

与 `tests/unit/agent/test_tool_loop_funnel_probes.py` 同口径、同判据，但**不依赖
pytest**：现场只装依赖也能跑。库一律落在临时目录（`--workspace`，默认 mkdtemp），
绝不指向 `data/` 生产库，也不触网——模型边界用一个只回预置 tool_call 的替身。

用法：
    python scripts/diagnostics/_tool_experience_loop_probe.py [--json]
        [--workspace DIR] [--tool NAME] [--arguments JSON]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_TOOL = "get_datetime"
DEFAULT_ARGUMENTS = "{}"


class ScriptedModel:
    """模型边界替身：按脚本吐 chunk，不参与任何执行链（与探针基座同款）。"""

    def __init__(self, config: Any, rounds: List[List[Any]]) -> None:
        self.config = config
        self._rounds = [list(round_) for round_ in rounds]
        self.stream_calls = 0
        self.normal_calls = 0

    def _next(self, index: int) -> List[Any]:
        return self._rounds[min(index, len(self._rounds) - 1)]

    async def chat_stream(self, messages, **kwargs):
        script = self._next(self.stream_calls)
        self.stream_calls += 1
        for chunk in script:
            yield chunk

    async def chat(self, messages, **kwargs):
        script = self._next(self.normal_calls)
        self.normal_calls += 1
        for chunk in script:
            if not isinstance(chunk, list):
                return chunk
        return script[-1] if script else None


def _shape_violations(records: List[Dict[str, Any]]) -> List[str]:
    """形状契约与探针基座 `shape_violations` 同口径（逐条点名，不静默过滤）。"""
    violations: List[str] = []
    for index, record in enumerate(records or []):
        if not isinstance(record, dict):
            violations.append(f"[{index}] 记录不是 dict：{type(record).__name__}")
            continue
        rtype = record.get("type")
        if rtype == "tool_call" and not str(record.get("tool_name") or "").strip():
            violations.append(f"[{index}] tool_call 缺 tool_name（键={sorted(record)}）")
        if rtype == "tool_result" and "success" not in record:
            violations.append(f"[{index}] tool_result 缺顶层 success（键={sorted(record)}）")
        if rtype not in ("tool_call", "tool_result"):
            violations.append(f"[{index}] 未知记录类型：{rtype!r}（键={sorted(record)}）")
    return violations


def _read_rows(columns: str = "id, skill_name, success, evidence_state") -> List[Dict[str, Any]]:
    import sqlite3

    path = os.environ.get("NEUROVA_EKB_DB", "")
    if not path or not os.path.exists(path):
        return []
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(
            f"select {columns} from experience_records order by id"
        )]
    finally:
        conn.close()


def run_probe(workspace: Path, tool_name: str, arguments: str) -> Dict[str, Any]:
    from neurova.llm_client import LLMResponse

    db_path = workspace / "experience_knowledge.db"
    os.environ["NEUROVA_EKB_DB"] = str(db_path)
    # 技能库路径在生产装配点里是**相对路径**（`SkillService` 的
    # `data/agents/<id>/skills`），因此取证期间把 cwd 切到临时目录：否则一次
    # 只读取证就会在仓库里长出 `data/agents/loop-probe-cli/skills`。
    # 仓库根已在 sys.path 上，模块导入不受影响（探针无 cwd 相对读取）。
    previous_cwd = os.getcwd()
    os.chdir(workspace)

    from neurova.skills.experience_knowledge_base import reset_experience_knowledge_base

    reset_experience_knowledge_base()

    from neurova.agent_core import Agent
    from neurova.agent.turn_state import resolve_tool_outcome
    from neurova.evolution.objective_evidence import resolve_ticket_evidence

    agent = Agent(
        name="LoopProbe",
        agent_id="loop-probe-cli",
        workspace_path=str(workspace / "ws"),
        enable_memory=False,
    )
    (workspace / "ws").mkdir(parents=True, exist_ok=True)

    rounds = [
        [LLMResponse(content="", tool_calls=[{
            "index": 0, "id": "call_probe", "type": "function",
            "function": {"name": tool_name, "arguments": arguments},
        }], finish_reason="tool_calls")],
        [LLMResponse(content="已完成", finish_reason="stop")],
    ]
    model = ScriptedModel(agent.llm_client.config, rounds)
    agent.llm_client = model
    agent.loop.llm_client = model

    async def _turn() -> Dict[str, Any]:
        await agent.chat("现在几点", session_id="probe-cli", stream=True)
        await agent.post_chat_pipeline.drain_background(timeout=60)
        records = agent.chat_pipeline._collect_tool_messages()
        ticket = resolve_ticket_evidence(agent, records)
        return {
            "records": records,
            "outcome": resolve_tool_outcome(records),
            "ticket_lookup": ticket.lookup,
            "ticket_reason": ticket.verdict.reason,
            "ticket_evidenced": ticket.lookup == "evidenced",
        }

    try:
        readings = asyncio.run(_turn())
    finally:
        os.chdir(previous_cwd)
    readings["shape_violations"] = _shape_violations(readings["records"])
    readings["record_count"] = len(readings["records"])
    rows = _read_rows()
    readings["evidence_rows"] = len(rows)
    readings["evidence_db"] = str(db_path)
    readings["workspace"] = str(workspace)
    readings.pop("records", None)
    return readings


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="工具↔经验↔再调用环路只读取证")
    parser.add_argument("--json", action="store_true", help="输出 JSON（默认人类可读）")
    parser.add_argument("--workspace", default="", help="取证库落点（默认 mkdtemp，绝不用 data/）")
    parser.add_argument("--tool", default=DEFAULT_TOOL, help="预置的工具名")
    parser.add_argument("--arguments", default=DEFAULT_ARGUMENTS, help="工具参数 JSON 串")
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))

    if args.workspace:
        workspace = Path(args.workspace)
        workspace.mkdir(parents=True, exist_ok=True)
        readings = run_probe(workspace, args.tool, args.arguments)
    else:
        with tempfile.TemporaryDirectory(prefix="loop-probe-") as scratch:
            readings = run_probe(Path(scratch), args.tool, args.arguments)

    if args.json:
        print(json.dumps(readings, ensure_ascii=False))
        return 0
    print(f"票据：lookup={readings['ticket_lookup']} reason={readings['ticket_reason']}")
    print(f"形状：违规 {len(readings['shape_violations'])} 条 {readings['shape_violations']}")
    print(f"成败三态：outcome={readings['outcome']}，EKB 落库 {readings['evidence_rows']} 行")
    print(f"取证库：{readings['evidence_db']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
