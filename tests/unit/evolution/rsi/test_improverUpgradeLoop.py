# -*- coding: utf-8 -*-
"""A5 I_t 第一次真实升级——元优化闭环（survey §10.2）。

剪枝/步进策略**吃自己的失败史**（pruner 被拒史已在记、今天没人用它调策略）产
I_{t+1} 候选；升级走提案 gate（人工批准换版），换版后配对探针必须重跑并把 Γ_t
写进版本台账——"改进器变强"从此有据可查。台账即 policy_t 的事实源（构造期按
最新已批准+有证据的条目重建策略），无探针读数的换版被拒。
"""

import json

import pytest

from neurova.evolution.rsi.candidate_policy import (
    I_0_SUMMARY,
    CandidatePolicy,
    ImproverVersionLedger,
    resolve_improver_ledger,
)
from neurova.evolution.rsi.recursive_ratchet_pruner import (
    Candidate,
    RecursiveRatchetPruner,
)

DEPS = dict(
    setpoint_lookup=lambda s, n: 0.8,
    performance_extractor=lambda signals: 0.5,
    sealed_validator=None,
)


def _failure_history(kind="dominant_big"):
    """合成被拒史：dominant_big=0.20 档严格占多数（4:1:1）、dominant_small 反转、
    spread=四档分散（无占多数档 ⇒ 无升级候选）、empty=空史。"""
    counts = {
        "dominant_big": {0.20: 4, 0.05: 1, 0.10: 1},
        "dominant_small": {0.05: 4, 0.10: 1, 0.20: 1},
        "spread": {0.05: 2, 0.10: 2, 0.15: 1, 0.20: 1},
        "empty": {},
    }[kind]
    history = []
    i = 0
    for ratio, count in counts.items():
        for _ in range(count):
            c = Candidate(id=f"f{i}", name=f"f{i}",
                          parameters={"adjustment_ratio": ratio},
                          heuristic_score=0.5, quick_evaluation_score=0.5,
                          complexity=1.0,
                          metadata={"realized_cost": 2})
            history.append(c)
            i += 1
    return history


class TestDeriveUpgrade:
    def test_failure_history_changes_step_preference(self):
        """行为格：被拒史注入后，同题的步进选择确实改变（对照注入前后）。"""
        from neurova.evolution.rsi.improver_upgrade import deriveImproverUpgrade

        base = CandidatePolicy.I_0(**DEPS)
        derived = deriveImproverUpgrade(base, _failure_history())
        assert derived is not None, "失败史没产出 upgrade 候选"
        assert derived.version != base.version
        # 0.20 档被拒史压掉了该档：同输入下 I_{t+1} 不再提出 0.20 步进
        states = {"system": "tool_memory", "param": "p", "current": 0.85}
        base_ratios = {c.parameters["adjustment_ratio"]
                       for c in base.stepCandidates("tool_memory", "p", 0.85, signals={})}
        derived_ratios = {c.parameters["adjustment_ratio"]
                          for c in derived.stepCandidates("tool_memory", "p", 0.85, signals={})}
        assert 0.20 in base_ratios
        assert 0.20 not in derived_ratios, (
            f"被拒史没改变步进选择：derived_ratios={derived_ratios}")

    def test_clean_or_scattered_history_yields_no_upgrade(self):
        """空史或淘汰分散（无严格占多数档）⇒ 无升级候选——不硬造变更。"""
        from neurova.evolution.rsi.improver_upgrade import deriveImproverUpgrade

        base = CandidatePolicy.I_0(**DEPS)
        assert deriveImproverUpgrade(base, []) is None
        assert deriveImproverUpgrade(base, _failure_history("spread")) is None


class TestApprovalGate:
    def test_registration_without_probe_readout_rejected(self, tmp_path, monkeypatch):
        """台账格：无探针读数的换版被拒——"升级了但没证据"不许入账。"""
        monkeypatch.setenv("NEUROVA_RSI_IMPROVER_LEDGER", str(tmp_path / "ledger.json"))
        ledger = resolve_improver_ledger()
        ledger.register("I_0", I_0_SUMMARY)

        with pytest.raises(Exception):
            ledger.register_upgraded_version(
                version="I_1", summary="derived", derived_from="I_0",
                derivation={"ratios_excluded": [0.2]},
                probe_readout=None,  # 无证据
            )
        # 带证据的换版入账，且 Γ 读数落账可读回
        ledger.register_upgraded_version(
            version="I_1", summary="derived", derived_from="I_0",
            derivation={"ratios_excluded": [0.2]},
            probe_readout={"state": "measured", "score": 0.012},
        )
        entries = ledger.readAll()
        upgraded = [e for e in entries if e["version"] == "I_1"]
        assert upgraded and upgraded[0]["probe_gamma"] == 0.012
        assert upgraded[0]["derivation"]["ratios_excluded"] == [0.2]

    def test_unknown_derived_from_rejected(self, tmp_path, monkeypatch):
        """换版的派生来源必须是已注册版本（伪造来源被拒）。"""
        monkeypatch.setenv("NEUROVA_RSI_IMPROVER_LEDGER", str(tmp_path / "ledger.json"))
        ledger = resolve_improver_ledger()
        with pytest.raises(Exception):
            ledger.register_upgraded_version(
                version="I_9", summary="x", derived_from="I_ghost",
                derivation={}, probe_readout={"state": "measured", "score": 0.0},
            )

    def test_probe_insufficient_blocks_registration(self, tmp_path, monkeypatch):
        """探针 insufficient_data（无证据形态）同样拒绝入账。"""
        monkeypatch.setenv("NEUROVA_RSI_IMPROVER_LEDGER", str(tmp_path / "ledger.json"))
        ledger = resolve_improver_ledger()
        ledger.register("I_0", I_0_SUMMARY)
        with pytest.raises(Exception):
            ledger.register_upgraded_version(
                version="I_1", summary="d", derived_from="I_0", derivation={},
                probe_readout={"state": "insufficient_data", "score": None},
            )


class TestPolicyRebuildFromLedger:
    def test_orchestrator_rebuilds_policy_t_from_ledger(self, tmp_path, monkeypatch):
        """台账即 policy_t 事实源：已批准+有证据的换版条目在构造期重建策略。"""
        ledger_path = tmp_path / "ledger.json"
        monkeypatch.setenv("NEUROVA_RSI_IMPROVER_LEDGER", str(ledger_path))
        ledger = resolve_improver_ledger()
        ledger.register("I_0", I_0_SUMMARY)
        ledger.register_upgraded_version(
            version="I_1", summary="drop 0.20 tier", derived_from="I_0",
            derivation={"ratios_excluded": [0.2]},
            probe_readout={"state": "measured", "score": 0.01},
        )

        from unittest.mock import MagicMock

        from neurova.evolution.rsi.orchestrator import RSIOrchestrator

        orch = RSIOrchestrator(
            sleep_system=MagicMock(), emotion_system=MagicMock(),
            experience_system=MagicMock(), tool_memory_system=MagicMock(),
        )
        assert orch._candidate_policy.version == "I_1", (
            f"构造期没按台账重建 I_t：{orch._candidate_policy.version}")
        ratios = {c.parameters["adjustment_ratio"]
                  for c in orch._candidate_policy.stepCandidates(
                      "tool_memory", "p", 0.85, signals={})}
        assert 0.20 not in ratios

    def test_no_upgrade_entry_falls_back_to_I0(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NEUROVA_RSI_IMPROVER_LEDGER", str(tmp_path / "l.json"))
        from unittest.mock import MagicMock

        from neurova.evolution.rsi.orchestrator import RSIOrchestrator

        orch = RSIOrchestrator(
            sleep_system=MagicMock(), emotion_system=MagicMock(),
            experience_system=MagicMock(), tool_memory_system=MagicMock(),
        )
        assert orch._candidate_policy.version == "I_0"


def test_upgrade_flow_end_to_end(tmp_path, monkeypatch):
    """全链：失败史→派生→提案 gate（探针重跑）→台账入账→构造期重建→探针读 Γ。"""
    ledger_path = tmp_path / "ledger.json"
    monkeypatch.setenv("NEUROVA_RSI_IMPROVER_LEDGER", str(ledger_path))
    from neurova.evolution.rsi.improver_upgrade import deriveImproverUpgrade

    base = CandidatePolicy.I_0(**DEPS)
    derived = deriveImproverUpgrade(base, _failure_history())
    assert derived is not None

    ledger = resolve_improver_ledger()
    ledger.register("I_0", base.summary)
    # 换版走探针重跑（受控结局流：派生策略更好 → Γ>0），证据随条目落账
    from neurova.evolution.rsi.improver_paired_probe import ImproverPairedProbe

    states = [{"system": "tool_memory", "param": f"p{i}",
               "current": 0.85 + i * 0.001, "setpoint": 0.8} for i in range(12)]
    probe = ImproverPairedProbe(
        policy_t=derived, policy_0=base,
        starting_states=lambda: states,
        outcome_evaluator=lambda s, c: (
            0.5 if c is None else 1.0 - abs(
                c.metadata["optimization"]["new_value"] - s["setpoint"])),
    )
    readout = probe.run()
    assert readout["state"] == "measured"

    ledger.register_upgraded_version(
        version=derived.version, summary=derived.summary, derived_from=base.version,
        derivation={"ratios_excluded": derived.excludedRatios()},
        probe_readout=readout,
    )
    entries = [e for e in ledger.readAll() if e["version"] == derived.version]
    assert entries and entries[0]["probe_gamma"] is not None
