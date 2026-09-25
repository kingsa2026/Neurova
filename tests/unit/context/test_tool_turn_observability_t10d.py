# -*- coding: utf-8 -*-
"""T-10d（工单 §11.5/§11.6）：工具轮视图的可观测计数、配对不匹配告警、回退开关等式。

工单 §11.5 要求三件事，本文件逐条钉住（此前**完全不可见**）：

1. **每轮视图内的计数**：`assistant.tool_calls` 数、`tool` 行数、旧数据降级次数。
   读数落在 `get_context_health()["tool_turns"]`（与 `ledger`/`summarizer`/
   `fold_integrity`/`turn_identity`/`microcompact` 同一份空形状单源）；
2. **`declared_ids` 不匹配即告警**：`assistant.tool_calls` 声明的 id 与实际
   `role="tool"` 行的 `tool_call_id` 对不上（孤儿 tool 行）时，计数 + 首次 warning
   + 点名原因，不得只留日志；
3. **灰度期 provider 400 归零**：配对非法导致的 provider 400 是唯一硬失败信号，
   其计数必须可读、且合法视图下恒为 0。

另有 §11.7 第 3 条：**回退开关必须有等式测试** —— 关闭时的视图必须与今天的形状
（只含 `user`/`assistant`，且每条仅 `{role, content}`）逐条相等。

断点形态（§21.4.1）：`get_context_health()` 此前**没有任何生产读者**，读数写在
内存里没人看。本批一并接线到既有观测面 `/metrics`（不新开端点）——本文件同时钉住
「写入 → 读取」这一环。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

prometheus_client = pytest.importorskip("prometheus_client")

from neurova.context.orchestrator import ContextOrchestrator  # noqa: E402

PAIRING_400_MESSAGE = (
    "Error code: 400 - {error: {message: \"An assistant message with "
    "tool_calls must be followed by tool messages responding to each "
    "tool_call_id\", type: invalid_request_error}}"
)


def _agent(session_manager=None):
    agent = MagicMock()
    agent.config = MagicMock()
    agent.config.name = "t"
    agent.config.agent_id = "a-t10d"
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
    agent.agent_id = "a-t10d"
    agent.session_manager = session_manager
    return agent


def _orchestrator(session_manager=None, budget_tokens: int = 9600) -> ContextOrchestrator:
    orch = ContextOrchestrator(_agent(session_manager), use_pool=True, auto_tag=False)
    orch._window_token_budget = budget_tokens
    return orch


def _tool_pair(call_id: str, chars: int = 200) -> list:
    return [
        {
            "role": "assistant",
            "content": "已读取",
            "tool_calls": [
                {
                    "id": call_id,
                    "type": "function",
                    "function": {"name": "read_file", "arguments": json.dumps({"path": "a.txt"})},
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": call_id,
            "name": "read_file",
            "content": "结果数据" * max(1, chars // 4),
        },
    ]


async def _build(orch: ContextOrchestrator, session_context: list):
    return await orch.build_context(
        user_input="继续",
        experience_items=[],
        relevant_memories=[],
        session_context=session_context,
    )


# ── 1. 每轮视图内的计数必须可读 ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_observability_counters_exposed():
    """视图内 `assistant.tool_calls` 数 / `tool` 行数必须与真实视图逐条咬合。"""
    orch = _orchestrator()
    session = [{"role": "user", "content": "读一下 a.txt"}] + _tool_pair("call_a") + _tool_pair("call_b")

    context = await _build(orch, session)

    readout = orch.get_context_health()["tool_turns"]
    assert readout["turns"] >= 1, f"视图轮次计数未上报：{readout}"
    assert readout["tool_rows"] == sum(1 for m in context if m.get("role") == "tool"), (
        "计数与真实视图的 tool 行数不咬合（读数必须是视图的实测，不是另算一份）"
    )
    assert readout["tool_call_rows"] == sum(
        1 for m in context if m.get("role") == "assistant" and m.get("tool_calls")
    ), "assistant.tool_calls 行数未按真实视图上报"
    assert readout["tool_rows"] >= 2 and readout["tool_call_rows"] >= 2


@pytest.mark.asyncio
async def test_degraded_turns_are_read_from_the_single_source(tmp_path):
    """旧数据降级次数走 `SessionManager` 的计数器本体（不复制一份平行账）。"""
    from neurova.session_manager import SessionManager

    manager = SessionManager()
    manager._sessions_dir = Path(tmp_path) / "sessions"
    manager._sessions_dir.mkdir(parents=True, exist_ok=True)
    manager.save_message("a-t10d", "s-t10d", "user", "读一下 a.txt")
    manager.save_message(
        "a-t10d",
        "s-t10d",
        "assistant",
        "已读取",
        metadata={"tool_calls": [{"type": "tool_call", "tool_name": "read_file", "params": {"path": "a.txt"}}]},
    )
    degraded_view = manager.get_recent_model_context(agent_id="a-t10d", session_id="s-t10d")
    assert manager.get_model_context_stats()["degraded_turns"] == 1, "本用例前置：旧记录必须降级"

    orch = _orchestrator(session_manager=manager)
    await _build(orch, degraded_view)

    readout = orch.get_context_health()["tool_turns"]
    assert readout["degraded_turns"] == 1, (
        f"降级次数没有接到健康面（读数应来自 SessionManager 计数器本体）：{readout}"
    )


@pytest.mark.asyncio
async def test_rebuild_stats_are_read_from_the_single_source(tmp_path):
    """重建配对数与回退开关使用次数同走 `SessionManager` 计数器本体。"""
    from neurova.session_manager import SessionManager

    manager = SessionManager()
    manager._sessions_dir = Path(tmp_path) / "sessions"
    manager._sessions_dir.mkdir(parents=True, exist_ok=True)
    manager.save_message("a-t10d", "s-stats", "user", "读一下 a.txt")
    manager.save_message(
        "a-t10d", "s-stats", "assistant", "已读取", metadata={"tool_calls": _entries_with_id()}
    )
    rebuilt = manager.get_recent_model_context(agent_id="a-t10d", session_id="s-stats")

    orch = _orchestrator(session_manager=manager)
    await _build(orch, rebuilt)

    readout = orch.get_context_health()["tool_turns"]
    assert readout["rebuilt_pairs"] == 1, f"重建配对数未接到健康面：{readout}"
    assert readout["degraded_turns"] == 0
    assert readout["killswitch_off"] == 0, "开关默认开，使用次数不得虚增"


# ── 2. declared_ids 不匹配即告警 ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_declared_ids_mismatch_is_alerted():
    """孤儿 `tool` 行（无人声明其 id）必须计数 + 点名原因，不得只留日志。"""
    orch = _orchestrator()
    orphaned = [
        {"role": "user", "content": "go"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "call_ok", "type": "function", "function": {"name": "read_file", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "call_ok", "name": "read_file", "content": "ok"},
        {"role": "tool", "tool_call_id": "call_ghost", "name": "read_file", "content": "无人声明的结果"},
    ]

    await _build(orch, orphaned)

    readout = orch.get_context_health()["tool_turns"]
    assert readout["declared_mismatch"] >= 1, (
        f"declared_ids 与实际 tool_call_id 不匹配却无告警计数：{readout}"
    )
    assert readout["last_error"], "不匹配必须点名原因（诚实形态），不得静默"


@pytest.mark.asyncio
async def test_paired_view_reports_no_mismatch():
    """配对完整的视图：不匹配计数为 0（告警不得恒真）。"""
    orch = _orchestrator()

    await _build(orch, [{"role": "user", "content": "go"}] + _tool_pair("call_ok"))

    readout = orch.get_context_health()["tool_turns"]
    assert readout["declared_mismatch"] == 0, f"配对完整却报不匹配（告警恒真）：{readout}"
    assert readout["last_error"] is None


# ── 3. 回退开关等式测试（§11.7 第 3 条）──────────────────────────────────

def _legacy_projection(sessions: list, max_messages: int) -> list:
    """今天（T-10b 之前）的形状：按时间升序取最近 N 条，只含 user/assistant，仅 {role, content}。"""
    ordered = sorted(sessions, key=lambda s: s.get("session_date", ""))
    rows = []
    for session in ordered:
        for msg in session.get("messages", []):
            if not isinstance(msg, dict):
                continue
            if msg.get("role") in ("user", "assistant"):
                rows.append({"role": msg["role"], "content": msg.get("content", "")})
    return rows[-max_messages:]


def test_killswitch_equals_today_view_shape(tmp_path, monkeypatch):
    """开关关闭 → 视图与今天的形状逐条相等（只含 user/assistant）。"""
    from neurova.session_manager import SessionManager

    manager = SessionManager()
    manager._sessions_dir = Path(tmp_path) / "sessions"
    manager._sessions_dir.mkdir(parents=True, exist_ok=True)
    manager.save_message("a-t10d", "s-ks", "user", "读一下 a.txt")
    manager.save_message(
        "a-t10d", "s-ks", "assistant", "已读取", metadata={"tool_calls": _entries_with_id()}
    )
    sessions = manager._get_session_data_list("a-t10d", "s-ks")

    monkeypatch.setenv("NEUROVA_TOOL_TURN_VIEW", "0")
    off = manager.get_recent_model_context(agent_id="a-t10d", session_id="s-ks")

    assert off == _legacy_projection(sessions, 20), (
        "回退开关关闭时的视图与今天的形状不逐条相等（§11.7 第 3 条的等式测试）"
    )
    assert all(set(m.keys()) == {"role", "content"} for m in off), "关闭时不得残留 tool 相关字段"
    assert not any(m.get("role") == "tool" for m in off), "关闭时不得出现 role=tool 行"
    stats = manager.get_model_context_stats()
    assert stats["killswitch_off"] == 1, f"回退开关被使用必须可读：{stats}"

    monkeypatch.delenv("NEUROVA_TOOL_TURN_VIEW", raising=False)
    on = manager.get_recent_model_context(agent_id="a-t10d", session_id="s-ks")
    assert any(m.get("role") == "tool" for m in on), "开关默认必须开（关闭才是例外）"
    assert manager.get_model_context_stats()["killswitch_off"] == 0


def _entries_with_id():
    return [
        {
            "type": "tool_call",
            "tool_name": "read_file",
            "tool_call_id": "call_ks",
            "params": {"path": "a.txt"},
            "arguments": json.dumps({"path": "a.txt"}),
        },
        {
            "type": "tool_result",
            "tool_name": "read_file",
            "tool_call_id": "call_ks",
            "result": "hello",
            "success": True,
        },
    ]


# ── 4. 灰度期 provider 400 归零判据 ─────────────────────────────────────

def test_pairing_reject_is_detected_and_counted():
    """配对非法导致的 provider 400 必须被识别并计入可读计数（唯一硬失败信号）。"""
    from prometheus_client import REGISTRY

    from neurova.core.metrics import get_metrics, record_tool_turn_provider_reject
    from neurova.llm.model_error_policy import toolPairingRejectReason

    reason = toolPairingRejectReason(PAIRING_400_MESSAGE)
    assert reason, "配对非法的 provider 400 未被识别 —— 归零判据无从成立"

    before = _counter_value("neurova_tool_turn_provider_rejects_total", {"reason": reason})
    record_tool_turn_provider_reject(reason)
    after = _counter_value("neurova_tool_turn_provider_rejects_total", {"reason": reason})
    assert after == before + 1, "计数没有落在可读的指标上"
    assert "neurova_tool_turn_provider_rejects_total" in _metrics_text()
    assert get_metrics() is not None
    assert REGISTRY.get_sample_value(
        "neurova_tool_turn_provider_rejects_total", {"reason": reason}
    ) == after


def test_reject_is_counted_on_the_real_chat_failure_path():
    """接线自证：真 `MultiModelLLMClient.chat()` 失败路径上必须真的计数一次。

    只测 `record_tool_turn_provider_reject()` 是测埋点函数，不是测接线 ——
    生产路径上没人调用它的话，判据照样是空的。
    """
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from neurova.llm.multi_model_client import MultiModelLLMClient

    class PairingBoom(Exception):
        def __init__(self):
            super().__init__(PAIRING_400_MESSAGE)
            self.status_code = 400

    class _Inner:
        def chat(self, messages, **kwargs):
            raise PairingBoom()

    client = SimpleNamespace(
        client=_Inner(),
        model="test-model",
        provider=SimpleNamespace(id="p-pairing"),
        increment_request=MagicMock(),
    )
    mmc = MultiModelLLMClient.__new__(MultiModelLLMClient)
    mmc._get_client_for_request = lambda model=None, provider_id=None: client
    MultiModelLLMClient._retry_guards = {}

    before = _counter_value("neurova_tool_turn_provider_rejects_total", {"reason": "ToolPairingReject"})
    result = asyncio.run(mmc.chat([{"role": "user", "content": "hi"}]))

    assert result.get("success") is False, "本用例前置：该请求必须失败（错误不得被吞）"
    assert PAIRING_400_MESSAGE.split(" - ")[0] in str(result.get("error")), "原始错误正文不得被改写"
    after = _counter_value("neurova_tool_turn_provider_rejects_total", {"reason": "ToolPairingReject"})
    assert after == before + 1, "真 chat 失败路径没有接线到归零判据的计数"


def test_pairing_reject_judgment_is_zero_for_legal_view(tmp_path):
    """判据咬合：合法视图（配对完整）下，该计数恒为 0。"""
    from neurova.llm.model_error_policy import toolPairingRejectReason

    for benign in (
        "Error code: 400 - invalid_request_error: unknown field foo",
        "Error code: 429 - rate limit exceeded",
    ):
        assert toolPairingRejectReason(benign) is None, f"非配对错误被误判：{benign}"


# ── 5. 健康面必须有生产读者（§21.4.1 断点接线）──────────────────────────

def test_health_face_is_read_by_the_scrape_path():
    """读数接线到既有观测面 `/metrics` 抓取路径（不新开端点，不懒建对象）。"""
    from neurova.core.metrics import get_metrics, generate_metrics_text

    src = Path("neurova/api/app.py").read_text(encoding="utf-8")
    assert "observe_context_health(" in src, (
        "get_context_health() 仍无生产读者 —— /metrics 抓取路径没有刷新这份读数"
    )

    orch = _orchestrator()
    get_metrics().observe_context_health()
    text = generate_metrics_text()
    assert "neurova_context_health" in text, "上下文健康读数没有出现在 /metrics 文本里"
    assert orch is not None


def _counter_value(name: str, labels: dict) -> float:
    from prometheus_client import REGISTRY

    value = REGISTRY.get_sample_value(name, labels)
    return float(value or 0.0)


def _metrics_text() -> str:
    from neurova.core.metrics import generate_metrics_text

    return generate_metrics_text()
