"""单一控制器与阶段回写（工单 005）。

两处 split-brain 各自致命，且互相掩护：

1. **双控制器**：编排器按治理设置建 phase=N 的控制器，但 `SelfImprovementProposer`
   在 `__init__` 里 `deployment_controller or RSIDeploymentController(initial_phase=0)`
   悄悄自建第二个。后果：medium/high 风险提案的门禁永远看 phase=0，
   管理员在前端调 `rsi_phase` 对这条通道完全无效——通道看起来"有判据"，实为死码。
2. **晋升不落盘**：`advance_phase()` 只改内存 `_current_phase`，而编排器每次都按
   盘上的 `rsi_phase` 重建 ⇒ 自动晋升重启即归零，阶段永远是人工设定的那个值。

本文件的断言方向：第二个控制器**不可能被悄悄造出来**（构造即报错），
晋升的结论**必须落在盘上**，落不了盘就必须**显式可见**（不允许"内存已晋升、
盘上没晋升"的静默两态）。

阶段一律经工单 001 的 `rsi_probe_factory` 由治理设置注入，不私赋 `_current_phase`。
重启语义经 `_bare_orchestrator()` 走"读盘上现有设置"这条生产同构路径。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from neurova.evolution.rsi import self_improvement_proposer as sip_module
from neurova.evolution.rsi.deployment_controller import RSIDeploymentController
from neurova.evolution.rsi.orchestrator import RSIOrchestrator
from neurova.evolution.rsi.result_summary import RSI_SUMMARY_FIELDS, summarize_rsi_result
from neurova.evolution.rsi.rollback_manager import RSIRollbackManager
from neurova.evolution.rsi.self_improvement_proposer import SelfImprovementProposer
from neurova.security.governance_settings import load_governance_settings

# 满 8 天：phase 1→2 要求"无回滚 ≥7 天"（deployment_controller.py:83）
_AGED_DAYS = 8


class _StubSystem:
    """只供反馈、不暴露可优化参数的系统桩（重启构造口用，不参与判据方向）。"""

    def get_feedback(self):
        return {"success_rate": 0.5}


def _bare_orchestrator() -> RSIOrchestrator:
    """模拟"进程重启"：不改写治理设置，只按盘上现值装配。"""
    return RSIOrchestrator(
        sleep_system=_StubSystem(),
        emotion_system=_StubSystem(),
        experience_system=_StubSystem(),
        tool_memory_system=_StubSystem(),
    )


def _age_rollback_install_time(rollback_path, days: int = _AGED_DAYS) -> None:
    """把已落盘的装配时刻改写为 N 天前（真实日历时间，不私赋阶段）。"""
    stored = json.loads(rollback_path.read_text(encoding="utf-8"))
    stored["installed_at"] = (
        datetime.now(timezone.utc) - timedelta(days=days)
    ).isoformat()
    rollback_path.write_text(json.dumps(stored), encoding="utf-8")


# ── 1. 双控制器：proposer 不得自建第二个 ─────────────────────────


def test_proposer_uses_the_orchestrators_deployment_controller(rsi_probe_factory):
    """整条 RSI 链路上"当前第几阶段"只能有一个答案。"""
    probe = rsi_probe_factory(rsi_phase=1)
    orchestrator = probe.orchestrator

    assert orchestrator.self_improvement_proposer.deployment_controller \
        is orchestrator.deployment_controller, (
        "proposer 自带第二个控制器：管理员调 rsi_phase 对提案门禁完全无效")


def test_proposer_uses_the_orchestrators_rollback_manager(rsi_probe_factory):
    """回滚历史与快照也必须同一份，否则提案快照不进跨重启留痕。"""
    probe = rsi_probe_factory(rsi_phase=1)
    orchestrator = probe.orchestrator

    assert orchestrator.self_improvement_proposer.rollback_manager \
        is orchestrator.rollback_manager, (
        "proposer 自带第二个回滚管理器：提案回滚不留痕、装配时刻两分")


def test_proposer_requires_both_collaborators(tmp_path):
    """未注入即构造失败 —— 把"悄悄自建"从可能变成不可能。"""
    with pytest.raises(TypeError) as exc:
        SelfImprovementProposer(proposals_dir=tmp_path / "proposals")

    message = str(exc.value)
    # 工单 010 之后必填项是三个：agent 归属、部署控制器、回滚管理器
    for name in ("agent_id", "deployment_controller", "rollback_manager"):
        assert name in message, f"报错须指名缺哪个注入点，实际：{message}"


def test_injected_collaborators_are_used_verbatim(tmp_path):
    """注入语义不得被"顺手补一个默认"稀释（工单 005 验收 4）。"""
    controller = RSIDeploymentController(initial_phase=2)
    manager = RSIRollbackManager()
    proposer = SelfImprovementProposer(
        agent_id="probe",
        proposals_dir=tmp_path / "proposals",
        deployment_controller=controller,
        rollback_manager=manager,
    )

    assert proposer.deployment_controller is controller
    assert proposer.rollback_manager is manager


def test_zero_injection_proposer_factories_are_gone():
    """零参工厂必然自带第二个控制器，留着它就等于留着 split-brain 的入口。"""
    for name in ("get_self_improvement_proposer", "reset_self_improvement_proposer",
                 "create_self_improvement_proposer"):
        assert not hasattr(sip_module, name), (
            f"`{name}` 无调用方且必然自建 phase=0 控制器，应随本单删除")
    source = Path(sip_module.__file__).read_text(encoding="utf-8")
    assert "deployment_controller or RSIDeploymentController(" not in source, (
        "proposer 侧仍存在自建默认")
    assert "rollback_manager or RSIRollbackManager(" not in source


# ── 2. 晋升回写治理设置（重启语义）──────────────────────────────


def test_promotion_is_written_back_to_governance_settings(
        rsi_probe_factory, tmp_path, monkeypatch):
    """集成：以 phase=1 起、攒满无回滚窗口晋升到 2 后，重启必须读到 2。"""
    rollback_path = tmp_path / "rsi_rollback.json"
    monkeypatch.setenv("NEUROVA_EVOLUTION_ROLLBACK", str(rollback_path))

    rsi_probe_factory(rsi_phase=1)
    _age_rollback_install_time(rollback_path)

    running = rsi_probe_factory(rsi_phase=1)
    assert running.orchestrator._compute_days_without_rollback() >= 7, (
        "前置：无回滚窗口已填满，判据不该因缺证据卡住")

    result = running.orchestrator.run_iteration()

    assert result["phase_advanced"] is True, (
        f"前置：本轮应发生晋升，实际判据 {result['phase_verdict']}")
    assert running.phase == 2, "内存阶段未推进"
    assert load_governance_settings()["rsi_phase"] == 2, (
        "晋升未回写治理设置：重启即归零，阶段永远是人工设定的那个")
    assert result["phase_persisted"] is True, "已落盘却报未落盘同样是假读数"

    restarted = _bare_orchestrator()
    assert restarted.deployment_controller.get_current_phase() == 2, (
        "重启后阶段归零：自动晋升从未真正生效过")


def test_unpersisted_promotion_is_reported_not_silent(
        rsi_probe_factory, tmp_path, monkeypatch, caplog):
    """写盘失败必须显式可见 —— 不允许"内存已晋升、盘上没晋升"的静默两态。"""
    rollback_path = tmp_path / "rsi_rollback.json"
    monkeypatch.setenv("NEUROVA_EVOLUTION_ROLLBACK", str(rollback_path))
    monkeypatch.setattr(
        "neurova.evolution.rsi.orchestrator.save_governance_settings",
        lambda data, path=None: False,
        raising=False,
    )

    rsi_probe_factory(rsi_phase=1)
    _age_rollback_install_time(rollback_path)
    running = rsi_probe_factory(rsi_phase=1)

    with caplog.at_level(logging.WARNING, logger="neurova.evolution.rsi.orchestrator"):
        result = running.orchestrator.run_iteration()

    assert result["phase_advanced"] is True, "前置：判据已通过并推进了内存阶段"
    assert result["phase_persisted"] is False, "写盘失败被吞：观测面把本轮晋升读成已存活"
    assert load_governance_settings()["rsi_phase"] == 1, "写失败却盘上已变，那是另一回事"
    assert any("rsi_phase" in rec.getMessage() for rec in caplog.records), (
        "晋升落盘失败只留 debug 级痕迹 ⇒ 与工单 005 要拆的静默两态同形")


def test_non_promotion_iteration_reports_persisted_false(rsi_probe_factory):
    """没晋升时 `phase_persisted` 必须是 False 且在场，不能缺席成"未置"。"""
    probe = rsi_probe_factory(rsi_phase=1)

    result = probe.orchestrator.run_iteration()

    assert result["phase_advanced"] is False, "前置：刚装配（0 天）不该晋升"
    assert result["phase_persisted"] is False
    assert probe.orchestrator.deployment_controller.get_current_phase() == 1


# ── 3. 观测面：两态必须可读 ─────────────────────────────────────


def test_summary_surface_carries_phase_persisted():
    """响应面只报 `phase_advanced` 会把"落盘失败"读成"已晋升"。"""
    assert "phase_persisted" in RSI_SUMMARY_FIELDS, "规范字段未登记 = 定义了没人写/没人读"

    summary = summarize_rsi_result({
        "convergence": {"status": "converged"},
        "applied_count": 0,
        "gain": 0.0,
        "phase_advanced": True,
        "phase_persisted": False,
    })

    assert summary["phase_advanced"] is True
    assert summary["phase_persisted"] is False, "摘要把落盘失败抹成了晋升成功"
    assert set(summary) == set(RSI_SUMMARY_FIELDS)
