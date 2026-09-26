# -*- coding: utf-8 -*-
"""live-verify（Issue #90 · T-10d）：工具轮视图的可观测计数、配对告警、400 归零判据。

链路：真 `ContextOrchestrator.build_context`（生产装配）→ 真 `repair_tool_turns`
→ 真 `get_context_health()["tool_turns"]` → 真 `/metrics` 抓取路径
（`get_metrics().observe_context_health()`）。

再叠一段真 provider 失败路径：真 `MultiModelLLMClient.chat()` 抛配对非法 400
→ 归零判据的计数 +1（证明埋点在生产路径上真的被调用，而不只是一个函数）。

判据（三条都要过）：
1. 视图内的 `assistant.tool_calls` 行数 / `tool` 行数 / 降级次数与真实视图咬合；
2. 孤儿 `tool` 行（无人声明 id）→ `declared_mismatch` 计数 + `last_error` 点名；
3. 回退开关关闭 → 视图与今天形状逐条相等；打开 → 工具轮在场。
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from prometheus_client import REGISTRY

from neurova.context.orchestrator import ContextOrchestrator

from tests.manual._liveVerifyIsolation import isolatedDataRoot  # noqa: E402
isolatedDataRoot()

PAIRING_400 = (
    "Error code: 400 - {'error': {'message': \"An assistant message with 'tool_calls' "
    "must be followed by tool messages responding to each 'tool_call_id'\"}}"
)


def _agent(session_manager=None):
    agent = MagicMock()
    agent.config = MagicMock()
    agent.config.name = "t"
    agent.config.agent_id = "a-live-t10d"
    agent.config.constitution = ""
    agent.config.behavior_rules = []
    agent.config.llm_model = "test-model"
    agent.memory_manager = MagicMock()
    agent.context_builder = MagicMock()
    agent.tool_router = None
    agent._skill_registry = None
    agent.soul = "测试助手"
    agent.personality = ""
    agent.conversation_history = []
    agent.growth_log_manager = MagicMock()
    agent.user_id = "u1"
    agent.agent_id = "a-live-t10d"
    agent.session_manager = session_manager
    return agent


def _paired(call_id: str) -> list:
    return [
        {
            "role": "assistant",
            "content": "已读取",
            "tool_calls": [{
                "id": call_id,
                "type": "function",
                "function": {"name": "read_file", "arguments": json.dumps({"path": "a.txt"})},
            }],
        },
        {"role": "tool", "tool_call_id": call_id, "name": "read_file", "content": "hello"},
    ]


async def _build(orch, session_context):
    return await orch.build_context(
        user_input="继续", experience_items=[], relevant_memories=[], session_context=session_context
    )


async def main() -> int:
    failures = []
    orch = ContextOrchestrator(_agent(), use_pool=True, auto_tag=False)
    orch._window_token_budget = 9600

    view = await _build(orch, [{"role": "user", "content": "读一下 a.txt"}] + _paired("call_lv_a") + _paired("call_lv_b"))
    readout = orch.get_context_health()["tool_turns"]
    actual_calls = sum(1 for m in view if m.get("role") == "assistant" and m.get("tool_calls"))
    actual_tools = sum(1 for m in view if m.get("role") == "tool")
    print(f"[1 计数] 视图 tool_calls 行={actual_calls} tool 行={actual_tools} | 读数={readout}")
    if readout["tool_call_rows"] != actual_calls or readout["tool_rows"] != actual_tools:
        failures.append("视图计数与真实视图不咬合")
    if actual_tools < 2:
        failures.append("本用例前置：工具轮必须真的进了视图")

    orphan = [
        {"role": "user", "content": "go"},
        {"role": "assistant", "content": "", "tool_calls": [{
            "id": "call_ok", "type": "function", "function": {"name": "read_file", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "call_ok", "name": "read_file", "content": "ok"},
        {"role": "tool", "tool_call_id": "call_ghost", "name": "read_file", "content": "无人声明的结果"},
    ]
    await _build(orch, orphan)
    readout = orch.get_context_health()["tool_turns"]
    print(f"[2 告警] declared_mismatch={readout['declared_mismatch']} last_error={str(readout['last_error'])[:70]}")
    if readout["declared_mismatch"] < 1 or not readout["last_error"]:
        failures.append("孤儿 tool 行未被计数/点名")

    from neurova.core.metrics import get_metrics, generate_metrics_text

    # `AppState` 在本判据上只被读一个字段（`agents` 字典），且 fastapi 缺失时
    # 起不了真 app —— 用一个同形容器顶替该字段，不伪造读面的行为。
    state = SimpleNamespace(agents={"a-live-t10d": SimpleNamespace(context_orchestrator=orch)})
    get_metrics().observe_context_health(state)
    text = generate_metrics_text()
    scrape = [ln for ln in text.splitlines() if ln.startswith("neurova_context_health_value{") and "tool_turns" in ln]
    print(f"[3 抓取] tool_turns 序列数={len(scrape)}；样例={scrape[0] if scrape else '（无）'}")
    if not scrape:
        failures.append("健康读数没有出现在 /metrics 文本里（仍无生产读者）")

    from neurova.llm.multi_model_client import MultiModelLLMClient

    class _PairingBoom(Exception):
        def __init__(self):
            super().__init__(PAIRING_400)
            self.status_code = 400

    class _Inner:
        def chat(self, messages, **kwargs):
            raise _PairingBoom()

    client = SimpleNamespace(
        client=_Inner(), model="test-model", provider=SimpleNamespace(id="p-live"),
        increment_request=MagicMock(),
    )
    mmc = MultiModelLLMClient.__new__(MultiModelLLMClient)
    mmc._get_client_for_request = lambda model=None, provider_id=None: client
    MultiModelLLMClient._retry_guards = {}
    before = _count()
    result = await mmc.chat([{"role": "user", "content": "hi"}])
    after = _count()
    print(f"[4 400 归零] success={result.get('success')} 计数 {before} → {after}")
    if result.get("success") is not False or after != before + 1:
        failures.append("真 chat 失败路径未接线到归零判据")

    import tempfile

    from neurova.session_manager import SessionManager

    manager = SessionManager()
    # 每次运行用独立目录：复用同目录会让上一次的落盘被本次读到（判据读数漂移）。
    manager._sessions_dir = Path(tempfile.mkdtemp(prefix="t10d_live_")) / "sessions"
    manager._sessions_dir.mkdir(parents=True, exist_ok=True)
    manager.save_message("a-live-t10d", "s-live", "user", "读一下 a.txt")
    manager.save_message(
        "a-live-t10d", "s-live", "assistant", "已读取",
        metadata={"tool_calls": [
            {"type": "tool_call", "tool_name": "read_file", "tool_call_id": "call_ks",
             "params": {"path": "a.txt"}, "arguments": json.dumps({"path": "a.txt"})},
            {"type": "tool_result", "tool_name": "read_file", "tool_call_id": "call_ks",
             "result": "hello", "success": True},
        ]},
    )
    os.environ["NEUROVA_TOOL_TURN_VIEW"] = "0"
    off = manager.get_recent_model_context(agent_id="a-live-t10d", session_id="s-live")
    stats_off = manager.get_model_context_stats()
    os.environ.pop("NEUROVA_TOOL_TURN_VIEW", None)
    on = manager.get_recent_model_context(agent_id="a-live-t10d", session_id="s-live")
    print(f"[5 回退开关] 关={[m['role'] for m in off]} killswitch_off={stats_off['killswitch_off']} | 开={[m['role'] for m in on]}")
    if any(m.get("role") == "tool" for m in off) or any(set(m.keys()) != {"role", "content"} for m in off):
        failures.append("回退开关关闭时视图不是今天形状")
    if stats_off["killswitch_off"] != 1:
        failures.append("回退开关被使用不可读")
    if not any(m.get("role") == "tool" for m in on):
        failures.append("开关默认未启用")

    if failures:
        print("LIVE-VERIFY FAILED")
        for item in failures:
            print("  -", item)
        return 1
    print("LIVE-VERIFY PASSED")
    return 0


def _count() -> float:
    return float(REGISTRY.get_sample_value(
        "neurova_tool_turn_provider_rejects_total", {"reason": "ToolPairingReject"}
    ) or 0.0)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
