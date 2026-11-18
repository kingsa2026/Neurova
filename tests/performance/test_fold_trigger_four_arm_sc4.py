# -*- coding: utf-8 -*-
"""SC-4 四臂折叠时机基准（真 build_context 管线，受控摘要桩，无真 LLM）。

契约（docs/08-research/reference_f_vs_neurova_context_compression_comparison_2026-11-17.md
§8.3 SC-4 / §9.4）：四臂对照，只动**触发政策**一维——

- 臂1 fixed_interval：固定间隔触发（NEUROVA_FOLD_FIXED_INTERVAL_MSGS=12，
  增长门关）——每积累 12 条未折消息即折（基准对照臂）；
- 臂2 growth_gate（基线）：现行默认增长门（相位抑制关，隔离对照维度）；
- 臂3 growth_gate+phase：臂2 + 相位抑制开 + 场景注入进行中 run 相位
  （SC-1 软抑制：折叠照常发生，推导边界锚点保留在视图）；
- 臂4 growth_gate+early：臂2 + 触发线前移（占用下限 0.6→0.3、增量门槛
  预算份额 0.25→0.08）——池形态激进臂（**实验臂，不据此改默认**，
  转正须另行拍板，见 §8.4 第 2 条）。

读数（每臂）：窗口峰值/均值 token、折叠次数与按因归并（SC-6 账本）、
折叠后 N 轮召回率（SC-6）、中途截断风险轮数（进窗时已超预算的轮数）、
可恢复保留率（B8 同款质量地板）、摘要调用数（成本代理）。

红灯断言（防"四臂同跑一个配置"的假基准）：
- 臂3 相位命中 > 0 且臂2 = 0（同一相位场景，唯一差异是抑制开关）；
- 臂4 首折回合早于臂2（触发线前移必须真的前移）；
- 臂1 fixed_interval 归因的折叠按 12 条消息恒定间隔出现，其余三臂该归因为 0
  （固定间隔机制必须真的存在且只在该臂生效）；
- 四臂召回率均 > 0（SC-6 读数在每臂上可用）。

运行命令：
  .venv/Scripts/python.exe -m pytest tests/performance/test_fold_trigger_four_arm_sc4.py -q -s
结果产物：tests/performance/sc4_four_arm_benchmark_results.json（随跑随写）。
"""
import json
import os
import sys
from typing import Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from neurova.context.orchestrator import ContextOrchestrator
from neurova.context.window_compactor import estimate_window_tokens
from tests.performance.test_retention_benchmark_b8 import build_marathon, markers_of, measure

ROUNDS = 24
BUDGET = 6000
FIXED_INTERVAL = 12
RECALL_QUERY = "事实F0 项目0 截止日期"
TURN_INPUT = "今天天气如何"  # 与事实内容零词元重叠（被动召回只由语义刻度决定）

SESSIONS = {
    "arm1_fixed_interval": "sess-sc4-arm1",
    "arm2_growth_gate": "sess-sc4-arm2",
    "arm3_growth_gate_phase": "sess-sc4-arm3",
    "arm4_growth_gate_early": "sess-sc4-arm4",
}

RESULT_PATH = os.path.join(os.path.dirname(__file__), "sc4_four_arm_benchmark_results.json")


def _mk_agent(agent_id: str, session: str):
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
    agent.user_id = "u-sc4"
    agent.agent_id = agent_id
    # 折叠缓存键与抽屉命中键同源（真 Agent 从 turn_context ContextVar 读；
    # 每臂独立会话身份，四臂账本互不串）
    agent.current_session_id = session
    return agent


def _phase(active: bool) -> dict:
    return {"active": active, "subtaskRuns": 1 if active else 0, "selfRun": False}


async def _runArm(arm: str) -> Dict:
    """跑一臂：逐轮 build_context（归档→折叠→被动召回）+ 末轮 targeted recall。"""
    from neurova.core.turn_context import set_turn_identity

    session = SESSIONS[arm]
    orch = ContextOrchestrator(_mk_agent(f"a-sc4-{arm}", session), use_pool=True, auto_tag=False)
    orch._window_token_budget = BUDGET
    orch._DELTA_RESUMMARY_MSGS = 0

    calls = {"n": 0}

    async def scripted_summarize(dropped_msgs, previous_summary=""):
        calls["n"] += 1
        heads = "；".join(
            str((m or {}).get("content", ""))[:60] for m in (dropped_msgs or [])[:12]
        )
        return f"第{calls['n']}代摘要：{heads}"

    orch._window_summarizer = scripted_summarize

    history = build_marathon(ROUNDS)
    markers = markers_of(ROUNDS)
    viewTokens: List[int] = []
    overflowTurns = 0
    viewOverflowTurns = 0
    finalView: List[dict] = []
    for end in range(len(history)):
        window = history[: end + 1]
        if estimate_window_tokens(window) > BUDGET:
            overflowTurns += 1  # 原始窗超预算（场景属性，四臂相同）
        set_turn_identity(TURN_INPUT, session)
        with patch.object(orch, "get_tools_description", new_callable=AsyncMock) as m:
            m.return_value = "工具描述占位"
            finalView = await orch.build_context(
                user_input=TURN_INPUT, session_context=window, relevant_memories=[]
            )
        viewTokens.append(estimate_window_tokens(finalView))
        if estimate_window_tokens(finalView) > BUDGET:
            viewOverflowTurns += 1  # 视图超预算：真实形态下即生成被截断的风险轮

    # targeted recall（pool_search 同一打分面）：召回被折叠的最早事实
    set_turn_identity(RECALL_QUERY, session)
    recalled = orch.context_pool.search(RECALL_QUERY, limit=5)

    joined = "".join(str(m.get("content", "")) for m in finalView)
    quality = measure(joined, orch.context_pool, markers)

    from neurova.context.budget_report import foldRecallReadout

    readout = foldRecallReadout(session)
    health = orch.get_context_health()
    foldReasons: Dict[str, int] = {}
    for event in readout.get("per_event", []):
        reason = str(event.get("reason") or "unknown")
        foldReasons[reason] = foldReasons.get(reason, 0) + 1
    foldTurns = [e["turn"] for e in readout.get("per_event", [])]
    intervalTurns = [
        e["turn"] for e in readout.get("per_event", []) if e.get("reason") == "fixed_interval"
    ]
    return {
        "session": session,
        "peak_view_tokens": max(viewTokens) if viewTokens else 0,
        "mean_view_tokens": int(sum(viewTokens) / len(viewTokens)) if viewTokens else 0,
        "fold_count": readout.get("fold_events", 0),
        "folds_by_reason": foldReasons,
        "first_fold_turn": foldTurns[0] if foldTurns else None,
        "fold_turns": foldTurns,
        "fixed_interval_turns": intervalTurns,
        # 中途截断次数 = 容量逼出的击穿折叠数（任务中途被硬水位切断的次数；
        # 相比之下主动政策（增长门/固定间隔）落在任务间隙）
        "mid_truncations": foldReasons.get("budget_breach", 0),
        "overflow_turns_raw": overflowTurns,
        "view_overflow_turns": viewOverflowTurns,
        "fold_recall_rate": readout.get("recall_rate", 0.0),
        "fold_recall_denominator": readout.get("denominator", 0),
        "fold_recall_numerator": readout.get("numerator", 0),
        "phase_hits": int(
            (health.get("fold_suppression", {}) or {}).get("phase_hits") or 0
        ),
        "summary_calls": calls["n"],
        "recoverable_retention": quality["recoverable_retention"],
        "view_retention": quality["view_retention"],
    }


def _armEnv(arm: str) -> Dict[str, str]:
    """各臂环境差异（只动触发政策一维；抽屉动态门槛四臂一致全开）。"""
    if arm == "arm1_fixed_interval":
        return {
            "NEUROVA_FOLD_GROWTH_GATE": "0",
            "NEUROVA_FOLD_FIXED_INTERVAL_MSGS": str(FIXED_INTERVAL),
        }
    if arm == "arm2_growth_gate":
        return {
            "NEUROVA_FOLD_GROWTH_GATE": "1",
            "NEUROVA_FOLD_PHASE_SUPPRESS": "0",
        }
    if arm == "arm3_growth_gate_phase":
        return {
            "NEUROVA_FOLD_GROWTH_GATE": "1",
            "NEUROVA_FOLD_PHASE_SUPPRESS": "1",
        }
    if arm == "arm4_growth_gate_early":
        return {
            "NEUROVA_FOLD_GROWTH_GATE": "1",
            "NEUROVA_FOLD_PHASE_SUPPRESS": "0",
            "NEUROVA_FOLD_GROWTH_FLOOR": "0.3",
            "NEUROVA_FOLD_GROWTH_BUDGET_SHARE": "0.08",
            "NEUROVA_FOLD_GROWTH_MIN_TOKENS": "600",
        }
    raise ValueError(arm)


async def _runAllArms() -> Dict[str, Dict]:
    results: Dict[str, Dict] = {}
    for arm in SESSIONS:
        envs = _armEnv(arm)
        saved = {k: os.environ.get(k) for k in envs}
        try:
            os.environ.update(envs)
            if arm == "arm3_growth_gate_phase":
                # 相位场景：本会话存在进行中的子任务 run（SC-1 信号源，只读）
                with patch(
                    "neurova.core.agent_run_ledger.activeRunPhaseSignal",
                    return_value=_phase(True),
                ):
                    results[arm] = await _runArm(arm)
            else:
                results[arm] = await _runArm(arm)
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
    return results


def _writeArtifact(results: Dict[str, Dict]) -> None:
    payload = {
        "benchmark": "SC-4 四臂折叠时机基准（固定间隔 / 增长门 / 增长门+相位抑制 / 增长门+前移触发）",
        "run_command": ".venv/Scripts/python.exe -m pytest tests/performance/test_fold_trigger_four_arm_sc4.py -q -s",
        "meta": {
            "rounds": ROUNDS,
            "budget_tokens": BUDGET,
            "fixed_interval_msgs": FIXED_INTERVAL,
            "recall_window_turns": os.environ.get(
                "NEUROVA_FOLD_RECALL_WINDOW_TURNS", "8(默认，本基准跑时设 50)"
            ),
            "recall_query": RECALL_QUERY,
            "turn_input": TURN_INPUT,
            "note": "激进臂（臂4）为实验臂，读数只描述不据此改默认配置（转正须另行拍板）。",
        },
        "arms": results,
    }
    with open(RESULT_PATH, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=False)


@pytest.fixture(autouse=True)
def _isolatedDataRoot(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("NEUROVA_CACHE_ADAPTIVE_FOLD", "0")
    # SC-6 观察窗放宽到 50：马拉松折叠发生在中段，末轮 targeted recall 的
    # 命中要落在窗内（窗口语义本身的边界由 unit 层用例钉住）
    monkeypatch.setenv("NEUROVA_FOLD_RECALL_WINDOW_TURNS", "50")
    monkeypatch.delenv("NEUROVA_FOLD_FIXED_INTERVAL_MSGS", raising=False)
    monkeypatch.delenv("NEUROVA_FOLD_PHASE_SUPPRESS", raising=False)
    monkeypatch.delenv("NEUROVA_FOLD_GROWTH_FLOOR", raising=False)
    monkeypatch.delenv("NEUROVA_FOLD_GROWTH_BUDGET_SHARE", raising=False)
    monkeypatch.delenv("NEUROVA_FOLD_GROWTH_MIN_TOKENS", raising=False)
    from neurova.context.budget_report import resetFoldRecallLedger

    resetFoldRecallLedger()
    yield
    resetFoldRecallLedger()


@pytest.mark.asyncio
async def test_four_arm_benchmark():
    """四臂对照：读数进产物，臂间差异可断言（假基准防护）。"""
    results = await _runAllArms()
    _writeArtifact(results)

    for arm, r in results.items():
        print(f"\n[SC-4] {arm}: " + json.dumps(r, ensure_ascii=False))

    # ── 质量地板（四臂共同守住）：池无损归档，可恢复保留率恒 1.0 ──
    for arm, r in results.items():
        assert r["recoverable_retention"] == 1.0, f"{arm} 可恢复保留率破地板: {r}"
        assert r["fold_count"] >= 1, f"{arm} 应发生折叠: {r}"

    # ── 红灯判据一：臂间配置差异必须真的生效 ──
    # 臂3 相位抑制命中（同场景注入进行中相位），臂2 关闭抑制恒 0
    assert results["arm3_growth_gate_phase"]["phase_hits"] > 0, (
        f"臂3 相位抑制应命中: {results['arm3_growth_gate_phase']}"
    )
    assert results["arm2_growth_gate"]["phase_hits"] == 0, (
        f"臂2 未开相位抑制，命中必须为 0: {results['arm2_growth_gate']}"
    )
    # 臂4 触发线前移：首折回合必须早于基线臂2
    assert results["arm4_growth_gate_early"]["first_fold_turn"] is not None
    assert results["arm2_growth_gate"]["first_fold_turn"] is not None
    assert results["arm4_growth_gate_early"]["first_fold_turn"] < results["arm2_growth_gate"]["first_fold_turn"], (
        f"臂4 首折应早于臂2: arm4={results['arm4_growth_gate_early']['first_fold_turn']} "
        f"arm2={results['arm2_growth_gate']['first_fold_turn']}"
    )
    # 臂1 固定间隔：fixed_interval 归因的折叠按间隔出现（12 条消息一步）。
    # 后段原始窗越过预算后判定被击穿合法抢占（安全线优先），故只断言
    # interval 归因的折叠节奏，不断言全部折叠的间隔。
    arm1IntervalTurns = results["arm1_fixed_interval"]["fixed_interval_turns"]
    assert len(arm1IntervalTurns) >= 2, f"臂1 应有多次固定间隔折叠: {results['arm1_fixed_interval']}"
    arm1Gaps = {b - a for a, b in zip(arm1IntervalTurns, arm1IntervalTurns[1:])}
    assert arm1Gaps == {FIXED_INTERVAL}, f"臂1 固定间隔必须恒定 {FIXED_INTERVAL}: {arm1IntervalTurns}"
    assert results["arm1_fixed_interval"]["folds_by_reason"].get("fixed_interval", 0) == len(arm1IntervalTurns)
    # 其余三臂不得出现 fixed_interval 归因（它们不是间隔政策）
    for other in ("arm2_growth_gate", "arm3_growth_gate_phase", "arm4_growth_gate_early"):
        assert results[other]["folds_by_reason"].get("fixed_interval", 0) == 0, (
            f"{other} 不应有固定间隔折叠: {results[other]}"
        )

    # ── 红灯判据二：SC-6 折叠后召回率读数在每臂上都可用（>0，分母≥分子≥1）──
    for arm, r in results.items():
        assert r["fold_recall_rate"] > 0.0, f"{arm} 折叠后召回率应>0: {r}"
        assert 0 < r["fold_recall_numerator"] <= r["fold_recall_denominator"], f"{arm} 分子分母不可解释: {r}"

    # ── 方向性读数（不钉死数值，只钉方向）：前移触发压低窗口峰值 ──
    assert results["arm4_growth_gate_early"]["peak_view_tokens"] <= results["arm2_growth_gate"]["peak_view_tokens"], (
        f"臂4 更早折叠应压低峰值: arm4={results['arm4_growth_gate_early']['peak_view_tokens']} "
        f"arm2={results['arm2_growth_gate']['peak_view_tokens']}"
    )
