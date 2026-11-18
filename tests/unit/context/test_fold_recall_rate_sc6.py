# -*- coding: utf-8 -*-
"""SC-6 折叠后 N 轮召回率读数（红灯先行）。

契约（docs/08-research/reference_f_vs_neurova_context_compression_comparison_2026-11-17.md §8.2 时机质量反馈 / §8.3 SC-6）：
1. 折叠事件侧记区间指纹（covers hash 集，与归档侧同源 `_windowChunkHash`），
   召回侧（抽屉取水命中）记命中指纹；关联账本**单源**在 budget_report，
   不造第二套事件账；
2. 聚合读数 = "折叠后 N 轮内被召回的区间比率"，N 为具名常量
   （FOLD_RECALL_WINDOW_TURNS，env 可覆盖）；分子/分母可解释；
3. 无召回时比率 = 0（分母>0、分子=0）；
4. 跨重启 fail-open：内存账清零后经时间线重放恢复分母
   （restoreFoldIntervals，编排层 S6' 建槽时调用），读数不崩、空账返回合法形状；
5. 窗口语义：折叠**当轮**的命中不计（ht <= ft 排除；当轮防召回本就由
   `_last_folded_hashes` 在视图层管辖），折叠后第 1..N 轮命中计入。
"""
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from neurova.context.orchestrator import ContextOrchestrator
from neurova.context.window_compactor import estimate_window_tokens

SESSION = "sess-sc6"

LEDGER_EXPORTS = (
    "FOLD_RECALL_WINDOW_TURNS",
    "foldRecallWindowTurns",
    "noteContextTurn",
    "currentContextTurn",
    "recordFoldIntervals",
    "restoreFoldIntervals",
    "recordRecallHits",
    "foldRecallReadout",
    "resetFoldRecallLedger",
)


def _importLedger():
    from neurova.context import budget_report

    for name in LEDGER_EXPORTS:
        assert hasattr(budget_report, name), f"budget_report 缺少 SC-6 账本出口: {name}"
    return budget_report


@pytest.fixture(autouse=True)
def _cleanLedger(monkeypatch, tmp_path):
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("NEUROVA_CACHE_ADAPTIVE_FOLD", "0")
    monkeypatch.delenv("NEUROVA_FOLD_RECALL_WINDOW_TURNS", raising=False)
    monkeypatch.delenv("NEUROVA_FOLD_GROWTH_GATE", raising=False)
    ledger = _importLedger()
    ledger.resetFoldRecallLedger()
    yield
    ledger.resetFoldRecallLedger()


# ════════════════════════════════════════════════════════════════
# 账本级：聚合判据（显式回合，确定性）
# ════════════════════════════════════════════════════════════════


class TestFoldRecallLedgerAggregation:
    def test_ratio_positive_and_numerator_denominator_explainable(self):
        """折叠区间 X → N 轮内召回 X：比率>0，分子/分母可解释。"""
        ledger = _importLedger()
        ledger.recordFoldIntervals(SESSION, ["h1", "h2"], turn=2, foldSeq=1)
        ledger.recordFoldIntervals(SESSION, ["h3"], turn=6, foldSeq=2)
        # h1 在折叠后第 1 轮被召回（窗内）；h3 未被召回
        ledger.recordRecallHits(SESSION, ["h1"], turn=3)

        readout = ledger.foldRecallReadout(SESSION)
        assert readout["window_turns"] == ledger.FOLD_RECALL_WINDOW_TURNS
        assert readout["denominator"] == 3, "分母 = 去重后被折叠区间 hash 数"
        assert readout["numerator"] == 1, "分子 = N 轮内被召回的区间数"
        assert readout["unrecalled"] == 2
        assert 0.0 < readout["recall_rate"] <= 1.0
        assert abs(readout["recall_rate"] - 1 / 3) < 1e-3  # 读数按 4 位小数取整
        per = readout["per_event"]
        assert len(per) == 2
        first = next(e for e in per if e["fold_seq"] == 1)
        assert first["folded"] == 2 and first["recalled_in_window"] == 1

    def test_no_recall_ratio_zero(self):
        """无召回：分母>0、分子=0、比率=0。"""
        ledger = _importLedger()
        ledger.recordFoldIntervals(SESSION, ["h1", "h2"], turn=1, foldSeq=1)
        readout = ledger.foldRecallReadout(SESSION)
        assert readout["denominator"] == 2
        assert readout["numerator"] == 0
        assert readout["recall_rate"] == 0.0

    def test_empty_ledger_fail_open_shape(self):
        """空账读数不崩：返回合法零形状（fail-open）。"""
        ledger = _importLedger()
        readout = ledger.foldRecallReadout(SESSION)
        assert readout["denominator"] == 0
        assert readout["numerator"] == 0
        assert readout["recall_rate"] == 0.0
        assert readout["window_turns"] == ledger.foldRecallWindowTurns()

    def test_window_boundary_inclusive_and_same_turn_excluded(self):
        """窗口边界：折叠当轮不计；第 N 轮计入；第 N+1 轮不计。"""
        ledger = _importLedger()
        n = ledger.foldRecallWindowTurns()
        ledger.recordFoldIntervals(SESSION, ["a_in", "b_out", "c_same"], turn=5, foldSeq=1)
        ledger.recordRecallHits(SESSION, ["c_same"], turn=5)  # 折叠当轮：不计
        ledger.recordRecallHits(SESSION, ["a_in"], turn=5 + n)  # 恰第 N 轮：计入
        ledger.recordRecallHits(SESSION, ["b_out"], turn=5 + n + 1)  # 第 N+1 轮：不计
        readout = ledger.foldRecallReadout(SESSION)
        assert readout["numerator"] == 1, f"只有窗内命中计入: {readout}"
        assert readout["denominator"] == 3

    def test_window_env_override(self):
        """N 具名常量可被 env 覆盖，聚合按生效窗计算。"""
        monkeypatch = pytest.MonkeyPatch()
        try:
            monkeypatch.setenv("NEUROVA_FOLD_RECALL_WINDOW_TURNS", "2")
            ledger = _importLedger()
            assert ledger.foldRecallWindowTurns() == 2
            ledger.recordFoldIntervals(SESSION, ["h1", "h2"], turn=2, foldSeq=1)
            ledger.recordRecallHits(SESSION, ["h1"], turn=5)  # Δ3 > 2：窗外
            ledger.recordRecallHits(SESSION, ["h2"], turn=4)  # Δ2 = 2：窗内
            readout = ledger.foldRecallReadout(SESSION)
            assert readout["window_turns"] == 2
            assert readout["numerator"] == 1 and readout["denominator"] == 2
        finally:
            monkeypatch.undo()

    def test_cross_restart_fail_open(self):
        """跨重启：内存账清零（重启模拟）后，经时间线重放恢复分母，
        新进程的召回命中仍可计入分子；读数全程不崩。"""
        ledger = _importLedger()
        ledger.recordFoldIntervals(SESSION, ["h1", "h2"], turn=3, foldSeq=1)
        ledger.recordRecallHits(SESSION, ["h1"], turn=4)
        assert ledger.foldRecallReadout(SESSION)["recall_rate"] == 0.5

        # ── 重启：内存账全丢 ──
        ledger.resetFoldRecallLedger()
        readout = ledger.foldRecallReadout(SESSION)
        assert readout["recall_rate"] == 0.0 and readout["denominator"] == 0

        # S6' 建槽重放：折叠基线从时间线恢复 → 分母恢复（回合未知记 0）
        ledger.restoreFoldIntervals(SESSION, ["h1", "h2"])
        # 新进程回合轴从 1 重新起算
        ledger.noteContextTurn(SESSION)
        ledger.noteContextTurn(SESSION)
        ledger.recordRecallHits(SESSION, ["h2"])  # 新进程第 2 轮命中
        readout = ledger.foldRecallReadout(SESSION)
        assert readout["denominator"] == 2, "重放恢复的分母不得丢失"
        assert readout["numerator"] == 1, "重启后的召回命中计入分子（尽力而为）"
        assert readout["recall_rate"] == 0.5

    def test_aggregate_across_sessions(self):
        """sessionKey=None 聚合全部会话；分会话切片可解释。"""
        ledger = _importLedger()
        ledger.recordFoldIntervals("sess-a", ["ha"], turn=1, foldSeq=1)
        ledger.recordFoldIntervals("sess-b", ["hb1", "hb2"], turn=1, foldSeq=1)
        ledger.recordRecallHits("sess-b", ["hb1"], turn=2)
        readout = ledger.foldRecallReadout()
        assert readout["denominator"] == 3
        assert readout["numerator"] == 1
        assert readout["sessions"]["sess-a"]["denominator"] == 1
        assert readout["sessions"]["sess-b"]["numerator"] == 1

    def test_duplicate_fold_and_hit_dedup(self):
        """同一区间重复折叠/重复命中只计一次（去重）。"""
        ledger = _importLedger()
        ledger.recordFoldIntervals(SESSION, ["h1"], turn=1, foldSeq=1)
        ledger.recordFoldIntervals(SESSION, ["h1"], turn=2, foldSeq=2)  # 重复折叠
        ledger.recordRecallHits(SESSION, ["h1"], turn=3)
        ledger.recordRecallHits(SESSION, ["h1"], turn=4)  # 重复命中
        readout = ledger.foldRecallReadout(SESSION)
        assert readout["denominator"] == 1
        assert readout["numerator"] == 1


# ════════════════════════════════════════════════════════════════
# 管线级：真 build_context 折叠 → 召回 → 读数（B5/B8 同款受控摘要桩）
# ════════════════════════════════════════════════════════════════

ROUNDS = 24
BUDGET = 6000


def _mk_agent(agent_id: str):
    agent = MagicMock()
    agent.config = MagicMock()
    agent.config.name = "bench"
    agent.config.constitution = ""
    agent.config.behavior_rules = []
    agent.config.llm_model = "test-model"
    agent.config.agent_id = agent_id
    agent.memory_manager = MagicMock()
    agent.context_builder = MagicMock()
    agent.tool_router = None
    agent._skill_registry = None
    agent.soul = "基准助手"
    agent.personality = ""
    agent.conversation_history = []
    agent.growth_log_manager = MagicMock()
    agent.user_id = "u-sc6"
    agent.agent_id = agent_id
    # 折叠缓存键与抽屉命中键同源（真 Agent 从 turn_context ContextVar 读）
    agent.current_session_id = SESSION
    return agent


def _mk_orchestrator(agent_id: str) -> ContextOrchestrator:
    orch = ContextOrchestrator(_mk_agent(agent_id), use_pool=True, auto_tag=False)
    orch._window_token_budget = BUDGET
    orch._DELTA_RESUMMARY_MSGS = 0
    return orch


async def _driveTurns(
    orch: ContextOrchestrator, rounds: int, recallInput: str, turnInput: str = "今天天气如何"
):
    """逐轮推进真 build_context（归档→折叠→被动召回），末轮后返回。

    轮次输入默认与事实内容**零词元重叠**（"今天天气如何"）——被动召回是否
    命中被折叠区间完全由语义刻度决定，不因输入与内容的字面巧合而误命中
    （"继续第 N 步"的 "N" 会撞上事实 F<N 正文里的 "第 N 轮"，污染零召回对照）。
    """
    from neurova.core.turn_context import set_turn_identity
    from tests.performance.test_retention_benchmark_b8 import build_marathon

    history = build_marathon(rounds)
    calls = {"n": 0}

    async def scripted_summarize(dropped_msgs, previous_summary=""):
        calls["n"] += 1
        heads = "；".join(
            str((m or {}).get("content", ""))[:60] for m in (dropped_msgs or [])[:12]
        )
        return f"第{calls['n']}代摘要：{heads}"

    orch._window_summarizer = scripted_summarize
    for end in range(len(history)):
        window = history[: end + 1]
        # 轮次身份写进 ContextVar（与 chat_pipeline 的请求边界同源）
        set_turn_identity(turnInput, SESSION)
        with patch.object(orch, "get_tools_description", new_callable=AsyncMock) as m:
            m.return_value = "工具描述占位"
            await orch.build_context(
                user_input=turnInput, session_context=window, relevant_memories=[]
            )
    #  targeted recall（pool_search 同一打分面）
    set_turn_identity(recallInput, SESSION)
    return orch.context_pool.search(recallInput, limit=5)


class TestFoldRecallPipeline:
    @pytest.mark.asyncio
    async def test_fold_then_recall_ratio_positive(self):
        """折叠区间 X（事实F0）→ 之后召回 X：比率>0 且分母/分子可解释。"""
        ledger = _importLedger()
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setenv("NEUROVA_FOLD_RECALL_WINDOW_TURNS", "50")
        try:
            orch = _mk_orchestrator("a-sc6-hit")
            # 召回查询带足判别词（实测 best≈0.86，越过同质池在线基线门槛 0.76）
            drops = await _driveTurns(orch, ROUNDS, "事实F0 项目0 截止日期")

            readout = ledger.foldRecallReadout(SESSION)
            assert readout["fold_events"] >= 1, f"马拉松应发生折叠: {readout}"
            assert readout["denominator"] >= 1, "折叠事件必须携带 covers 区间指纹"
            assert all(e["folded"] > 0 for e in readout["per_event"]), "折叠事件 folds>0"
            # targeted recall 命中被折叠的早期事实 → 分子≥1
            hitContents = [str(getattr(d, "content", "")) for d in drops]
            assert any("事实F0" in c for c in hitContents), f"检索应取回 F0: {hitContents[:2]}"
            assert readout["numerator"] >= 1, f"召回命中应进分子: {readout}"
            assert 0.0 < readout["recall_rate"] <= 1.0
            assert readout["numerator"] <= readout["denominator"]
        finally:
            monkeypatch.undo()

    @pytest.mark.asyncio
    async def test_no_recall_ratio_zero(self):
        """折叠发生但无召回（泛化输入，语义不相关）：比率=0。"""
        ledger = _importLedger()
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setenv("NEUROVA_FOLD_RECALL_WINDOW_TURNS", "50")
        try:
            orch = _mk_orchestrator("a-sc6-zero")
            drops = await _driveTurns(orch, ROUNDS, "今天天气如何")

            readout = ledger.foldRecallReadout(SESSION)
            assert readout["denominator"] >= 1, "马拉松应发生折叠（分母>0）"
            assert drops == [] or all(
                "事实F" not in str(getattr(d, "content", "")) for d in drops
            ), "无关输入不应取回事实条目"
            assert readout["numerator"] == 0, f"无召回时分子必须为 0: {readout}"
            assert readout["recall_rate"] == 0.0
        finally:
            monkeypatch.undo()
