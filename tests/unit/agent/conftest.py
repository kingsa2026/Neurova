"""工具↔经验↔再调用三环路探针的共享基座（工单 001）。

设计约束（后续各票都靠它取证，破坏任一条探针就失去意义）：

1. **必须经生产构造点**：Agent 用真 `Agent(...)` 构造，技能面是真 `SkillRegistry`、
   执行面是真 `ToolExecutor`、后处理是真 `PostChatPipeline`。禁止 `ChatPipeline.__new__`
   + 测试自喂 `_collect_tool_messages` 的构造方式——那正是本条链路的盲区来源。
2. **替身只放在模型边界**：`ScriptedModel` 只实现 `chat_stream` / `chat` 两个 LLM 客户端
   契约方法，按脚本吐 chunk。执行链（工具选择、参数解析、治理、票据、经验写入）
   全部走真代码。
3. **写验证一律落 tmp**：EKB 经 `NEUROVA_EKB_DB`，技能证据库经 conftest 的
   `SkillService` 隔离夹具；禁止指向 `data/` 生产库。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from neurova.llm_client import LLMResponse


class ScriptedModel:
    """模型边界替身：按脚本产出 chunk，不参与任何执行链。"""

    def __init__(self, config: Any, rounds: List[List[Any]]) -> None:
        self.config = config
        self._rounds = [list(round_) for round_ in rounds]
        self.stream_calls = 0
        self.normal_calls = 0

    def _next_round(self, index: int) -> List[Any]:
        return self._rounds[min(index, len(self._rounds) - 1)]

    async def chat_stream(self, messages, **kwargs):
        script = self._next_round(self.stream_calls)
        self.stream_calls += 1
        for chunk in script:
            yield chunk

    async def chat(self, messages, **kwargs):
        script = self._next_round(self.normal_calls)
        self.normal_calls += 1
        for chunk in script:
            if isinstance(chunk, LLMResponse):
                return chunk
        return LLMResponse(content="", finish_reason="stop")


def tool_call_chunk(call_id: str, tool_name: str, arguments: str) -> LLMResponse:
    """模型返回的一条 function-calling 调用（流式合并后的完整形态）。"""
    return LLMResponse(
        content="",
        tool_calls=[{
            "index": 0,
            "id": call_id,
            "type": "function",
            "function": {"name": tool_name, "arguments": arguments},
        }],
        finish_reason="tool_calls",
    )


def text_chunk(text: str) -> LLMResponse:
    return LLMResponse(content=text, finish_reason="stop")


def shape_violations(records: List[Dict[str, Any]]) -> List[str]:
    """取证源的形状契约（P-b 判据）：逐条点名违规，不静默过滤。"""
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


@pytest.fixture
def loop_probe(tmp_path, monkeypatch):
    """以生产构造点拉起一个 agent，并把模型替换成脚本化替身。

    返回 (agent, rounds)：`rounds` 由调用方填脚本，构造完 agent 后调
    `loop_probe.bind()` 生效。
    """
    monkeypatch.setenv("NEUROVA_EKB_DB", str(tmp_path / "experience_knowledge.db"))
    from neurova.skills.experience_knowledge_base import reset_experience_knowledge_base

    reset_experience_knowledge_base()

    from neurova.agent_core import Agent

    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    agent = Agent(
        name="LoopProbe",
        agent_id="loop-probe-01",
        workspace_path=str(workspace),
        enable_memory=False,
    )

    def bind(rounds: List[List[Any]]) -> ScriptedModel:
        model = ScriptedModel(agent.llm_client.config, rounds)
        agent.llm_client = model
        agent.loop.llm_client = model
        return model

    probe = SimpleNamespace(agent=agent, bind=bind)
    try:
        yield probe
    finally:
        reset_experience_knowledge_base()


def read_experience_rows(columns: str = "id, skill_name, success, evidence_state") -> List[Dict[str, Any]]:
    """读探针库当前落下的经验行（`NEUROVA_EKB_DB` 指向的 tmp 库，只读打开）。"""
    import os
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


def attach_tool_executor(agent: Any) -> Any:
    """给替身 agent 装一个真 `ToolExecutor`（原生链唯一执行咽喉）。

    工单 003 之后，原生链的工具执行一律经咽喉；用替身 agent 驱动
    `handle_tool_calls` 的用例，必须让替身带上真执行器，否则测的就是
    一条已经退役的旁路。接口替身只放在更下层（`tool_router` / `skill_registry`）。
    """
    from neurova.tool_executor import ToolExecutor

    executor = ToolExecutor(agent)
    agent.tool_executor = executor
    return executor
