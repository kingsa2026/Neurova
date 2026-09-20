"""016 · 经验质量读数进入 RSI 阶段晋升判据（红绿灯 TDD）。

按 spec §4 的 D4，质量指标（008）与可信基准（009）先就位，本单才把它们接进
`evaluate_phase_transition` 的必证证据集。接错的形态有三种，本文件逐条钉住：

1. **把"没测到"读成"没问题"** —— 空库的 `unevidenced_ratio` 是 0.0、无采纳决策的
   `adoption_success_rate` 被指标面压成 0.0。判据面必须还原成"没有读数"，
   落 `unevidenced`（既不晋升也不否决），而不是"质量完美"或"质量全崩"。
2. **另算一套数** —— 判据面只吃 `EKB.quality_snapshot()` → `RSIMetrics` 这条链
   已有的读数，阈值只认 008 的 `ALERT_THRESHOLDS` 一张表。两处算同一个数必然漂移，
   漂移后没人能信读数（所以本文件有一条"告警面与判据面同步翻转"的漂移锁）。
3. **造第二个三态** —— 一律复用 `gate_verdict.GateVerdict`（D5），
   且新增必需性不得把原有必证证据（收敛结论 / roi / 无回滚天数）挤掉。

测试写法遵循 `tests/unit/evolution/conftest.py` 的三条约束：阶段经治理设置进入
（`rsi_probe_factory`）、闭环系统不用 MagicMock 顶替、期望值不由被测代码反算。
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from neurova.evolution.rsi.deployment_controller import RSIDeploymentController
from neurova.evolution.rsi.gate_verdict import GateVerdict
from neurova.evolution.rsi.metrics import RSIMetrics
from neurova.skills.experience_knowledge_base import (
    ExperienceRecord,
    get_experience_knowledge_base,
)

# ── 造读数：一律经 RSIMetrics（生产供值点），不在测试里手写判据吃的字段 ──


def _rec(text: str, success: bool = True) -> ExperienceRecord:
    return ExperienceRecord(
        skill_name="chat",
        context={"user_input": text},
        result={"reply_excerpt": "r"},
        success=success,
    )


def _readout(rows: int, decisions: int, rate) -> dict:
    """把规范指标面喂给唯一读数出口，得到判据面吃的那份读数。

    `rate=None` 复刻快照的"分母为零"；指标面存的是 float，只能记 0.0，
    还原成"没有读数"正是 `experience_quality_readout()` 的职责。
    """
    metrics = RSIMetrics()
    metrics.record_metric(RSIMetrics.EXPERIENCE_ROWS, rows)
    metrics.record_metric(RSIMetrics.EXPERIENCE_ADOPTION_DECISIONS, decisions)
    metrics.record_metric(RSIMetrics.EXPERIENCE_ADOPTION_SUCCESS_RATE, 0.0 if rate is None else rate)
    return metrics.experience_quality_readout()


def _promotion_metrics(quality) -> dict:
    """phase 2/3 的其余必证读数全部给定且全部满足，只让经验质量一个变量说话。"""
    metrics = {
        "convergence_status": "converging",
        "roi": 0.2,
        "days_without_rollback": 40,
    }
    if quality is not None:
        metrics["experience_quality"] = quality
    return metrics


def _evaluate(phase: int, quality, **overrides) -> GateVerdict:
    metrics = _promotion_metrics(quality)
    metrics.update(overrides)
    return RSIDeploymentController(initial_phase=phase).evaluate_phase_transition(metrics)


# ── 1. 供值点：None 语义必须还原，不得兜成 0.0 ─────────────────────


class TestPromotionFacingReadout:
    def test_empty_library_is_no_reading_not_perfect_quality(self):
        readout = _readout(rows=0, decisions=0, rate=None)

        assert readout["rows"] == 0
        assert readout["adoption_success_rate"] is None, (
            "指标面把「没有采纳决策」的成功率记成 0.0，判据面必须还原成「没读数」")

    def test_single_adoption_decision_is_not_a_reading(self):
        """一次成败是噪声不是趋势——008 的最小决策数门槛在判据面同样成立。"""
        readout = _readout(rows=9, decisions=1, rate=0.0)

        assert readout["adoption_success_rate"] is None

    def test_reading_appears_once_the_sample_floor_is_met(self):
        readout = _readout(rows=9, decisions=2, rate=0.5)

        assert readout["adoption_success_rate"] == pytest.approx(0.5)
        assert readout["adoption_decisions"] == 2


# ── 2. 三态：无据 / 质差 / 质好 ────────────────────────────────────


class TestThreeStates:
    def test_empty_experience_library_is_unevidenced_not_passed(self):
        verdict = _evaluate(2, _readout(rows=0, decisions=0, rate=None))

        assert verdict.state == "unevidenced", verdict
        assert bool(verdict) is False, "无经验质量读数绝不可被当成通过"
        assert "experience_quality" in verdict.reason, verdict.reason

    def test_empty_experience_library_is_not_a_veto_either(self):
        """无据与质差是两个态：没测到不得被读成「测出来是坏的」。"""
        verdict = _evaluate(2, _readout(rows=0, decisions=0, rate=None))

        assert verdict.state != "failed", verdict.reason

    def test_library_without_adoption_decisions_is_unevidenced(self):
        """有 5 条经验但从没被采纳过 ⇒ 质量无从判断，不是「质量完美」。"""
        verdict = _evaluate(2, _readout(rows=5, decisions=0, rate=None))

        assert verdict.state == "unevidenced", verdict
        assert bool(verdict) is False

    def test_missing_quality_key_entirely_is_unevidenced(self):
        """老调用方不传这个读数 ⇒ 落无据，不得落通过（缺键默认真是 002 的病根）。"""
        verdict = _evaluate(2, None)

        assert verdict.state == "unevidenced"
        assert "experience_quality" in verdict.reason

    def test_bad_quality_vetoes_promotion(self):
        """采纳率低于阈值且样本达最小决策数 ⇒ 有证据的否决。"""
        verdict = _evaluate(2, _readout(rows=9, decisions=5, rate=0.2))

        assert verdict.state == "failed", verdict
        assert bool(verdict) is False
        assert "经验" in verdict.reason, f"否决要说得出拦在质量上：{verdict.reason}"

    def test_good_quality_promotes(self):
        verdict = _evaluate(2, _readout(rows=9, decisions=5, rate=0.9))

        assert verdict.state == "passed", verdict.reason

    def test_the_two_verdicts_differ_only_in_the_quality_reading(self):
        """质差否决 / 质好放行：两份入参除这一个读数外必须逐键相同。"""
        good = _promotion_metrics(_readout(rows=9, decisions=5, rate=0.9))
        bad = dict(good)
        bad["experience_quality"] = _readout(rows=9, decisions=5, rate=0.2)

        def strip(metrics):
            return {k: v for k, v in metrics.items() if k != "experience_quality"}

        assert strip(good) == strip(bad), "两份入参除经验质量外必须相同"

        controller = RSIDeploymentController(initial_phase=2)
        assert bool(controller.evaluate_phase_transition(good)) is True
        assert bool(controller.evaluate_phase_transition(bad)) is False

    def test_every_branch_is_the_shared_gate_verdict(self):
        """D5 反向锁：本判据只复用 `GateVerdict`，不引入第二套三态表达。"""
        for quality in (
            _readout(rows=0, decisions=0, rate=None),
            _readout(rows=9, decisions=5, rate=0.2),
            _readout(rows=9, decisions=5, rate=0.9),
        ):
            verdict = _evaluate(2, quality)
            assert type(verdict) is GateVerdict, f"自造判据类型：{type(verdict)}"
            assert verdict.state in {
                GateVerdict.STATE_PASSED, GateVerdict.STATE_FAILED, GateVerdict.STATE_UNEVIDENCED
            }, verdict


# ── 3. 必需性按阶段声明：只在自动执行已在跑的阶段要求 ──────────────


class TestRequirednessPerPhase:
    @pytest.mark.parametrize("phase", [2, 3])
    def test_semi_auto_and_above_require_experience_quality(self, phase):
        verdict = _evaluate(phase, None)

        assert verdict.state == "unevidenced", f"phase {phase} 未要求经验质量证据"
        assert "experience_quality" in verdict.reason

    @pytest.mark.parametrize("phase", [0, 1])
    def test_phases_below_semi_auto_are_not_blocked_by_it(self, phase):
        """观察期/手动期压根没有「照经验做」的自动执行风险，不得为它锁死晋升链。

        与 008 对 roi/收敛读数的裁决同形：走到这一步之前该读数可能还不存在。
        """
        metrics = {"convergence_status": "converging", "days_without_rollback": 40}

        assert bool(RSIDeploymentController(initial_phase=phase).evaluate_phase_transition(
            metrics)) is True, f"phase {phase} 被经验质量挡住了"


# ── 4. 反向锁：新证据不得挤掉原有必证证据 ──────────────────────────


class TestExistingEvidenceStillBites:
    @pytest.mark.parametrize("missing", ["roi", "convergence_status", "days_without_rollback"])
    def test_good_quality_does_not_excuse_a_missing_required_reading(self, missing):
        metrics = _promotion_metrics(_readout(rows=9, decisions=5, rate=0.9))
        del metrics[missing]

        verdict = RSIDeploymentController(initial_phase=2).evaluate_phase_transition(metrics)

        assert verdict.state == "unevidenced", verdict
        assert missing in verdict.reason, f"reason 未列出 {missing}：{verdict.reason}"

    @pytest.mark.parametrize("status", ["diverging", "measurement_blind", "oscillating"])
    def test_convergence_veto_still_wins_over_good_quality(self, status):
        verdict = _evaluate(2, _readout(rows=9, decisions=5, rate=0.9), convergence_status=status)

        assert verdict.state == "failed", verdict
        assert status in verdict.reason

    def test_negative_roi_still_vetoes_over_good_quality(self):
        verdict = _evaluate(2, _readout(rows=9, decisions=5, rate=0.9), roi=-0.5)

        assert verdict.state == "failed"
        assert "roi" in verdict.reason

    def test_days_short_of_requirement_still_vetoes(self):
        verdict = _evaluate(2, _readout(rows=9, decisions=5, rate=0.9), days_without_rollback=1)

        assert verdict.state == "failed"
        assert "days_without_rollback" in verdict.reason

    def test_evidenced_bad_quality_beats_a_missing_roi(self):
        """有证据的质差是硬否决，不得被另一道「缺证据」稀释成 unevidenced。"""
        metrics = _promotion_metrics(_readout(rows=9, decisions=5, rate=0.2))
        del metrics["roi"]

        verdict = RSIDeploymentController(initial_phase=2).evaluate_phase_transition(metrics)

        assert verdict.state == "failed", verdict

    def test_all_four_readings_are_collected_in_the_reason(self):
        """空读数下 reason 一次列全四项，否则修一个又冒一个。"""
        verdict = RSIDeploymentController(initial_phase=3).evaluate_phase_transition({})

        assert verdict.state == "unevidenced"
        for key in ("convergence_status", "roi", "days_without_rollback", "experience_quality"):
            assert key in verdict.reason, f"reason 未列出 {key}：{verdict.reason}"


# ── 5. 阈值是活的旋钮（事实源改得动判据，不是幻影旋钮）─────────────


class TestThresholdKnobIsLive:
    def test_raising_the_floor_at_the_fact_source_flips_pass_to_veto(self, monkeypatch):
        controller = RSIDeploymentController(initial_phase=2)
        quality = _readout(rows=9, decisions=5, rate=0.9)
        assert bool(controller.evaluate_phase_transition(_promotion_metrics(quality))) is True

        # 同一个 controller 实例存续期间改事实源 ⇒ 结论必须跟着翻（构造期快照式实现必红）
        monkeypatch.setitem(
            RSIMetrics.ALERT_THRESHOLDS, "experience_adoption_success_rate_warning", 0.95
        )

        verdict = controller.evaluate_phase_transition(_promotion_metrics(quality))
        assert verdict.state == "failed", f"阈值是幻影旋钮：改事实源没动判据（{verdict}）"

    def test_lowering_the_floor_lets_the_same_reading_pass(self, monkeypatch):
        controller = RSIDeploymentController(initial_phase=2)
        quality = _readout(rows=9, decisions=5, rate=0.2)
        assert controller.evaluate_phase_transition(_promotion_metrics(quality)).state == "failed"

        monkeypatch.setitem(
            RSIMetrics.ALERT_THRESHOLDS, "experience_adoption_success_rate_warning", 0.1
        )

        assert bool(controller.evaluate_phase_transition(_promotion_metrics(quality))) is True

    def test_raising_the_sample_floor_turns_a_reading_into_unevidenced(self, monkeypatch):
        """最小决策数也是活旋钮：抬到 6，5 次决策就不算有读数了。

        而且是「无据」不是「否决」——样本不够与样本测出来是坏的两回事。
        """
        assert bool(RSIDeploymentController(initial_phase=2).evaluate_phase_transition(
            _promotion_metrics(_readout(rows=9, decisions=5, rate=0.9))))

        monkeypatch.setitem(RSIMetrics.ALERT_THRESHOLDS, "experience_adoption_min_decisions", 6)

        verdict = RSIDeploymentController(initial_phase=2).evaluate_phase_transition(
            _promotion_metrics(_readout(rows=9, decisions=5, rate=0.9)))
        assert verdict.state == "unevidenced", f"样本门槛未生效：{verdict}"

    def test_promotion_and_alert_flip_together(self, monkeypatch):
        """漂移锁：同一份读数下，「该有人看了」与「该不该给更多自主权」吃同一张表。

        两处各配一份阈值必然漂移，漂移后没人能信读数——所以两边必须同步翻转。
        """
        def alert_fires(rows, decisions, rate):
            m = RSIMetrics()
            m.record_metric(RSIMetrics.EXPERIENCE_ROWS, rows)
            m.record_metric(RSIMetrics.EXPERIENCE_ADOPTION_DECISIONS, decisions)
            m.record_metric(RSIMetrics.EXPERIENCE_ADOPTION_SUCCESS_RATE, rate)
            return bool([a for a in m.check_alerts()
                         if a.metric == RSIMetrics.EXPERIENCE_ADOPTION_SUCCESS_RATE])

        def promotion(rows, decisions, rate):
            verdict = RSIDeploymentController(initial_phase=2).evaluate_phase_transition(
                _promotion_metrics(_readout(rows=rows, decisions=decisions, rate=rate)))
            return verdict.state

        # 质差：告警出声，晋升否决
        assert alert_fires(9, 5, 0.2) is True and promotion(9, 5, 0.2) == "failed"
        # 质好：两边都不出声
        assert alert_fires(9, 5, 0.9) is False and promotion(9, 5, 0.9) == "passed"
        # 样本不足：都不下结论（一边不告警，另一边是无据不是否决）
        assert alert_fires(9, 1, 0.2) is False and promotion(9, 1, 0.2) == "unevidenced"

        monkeypatch.setitem(
            RSIMetrics.ALERT_THRESHOLDS, "experience_adoption_success_rate_warning", 0.1
        )
        assert alert_fires(9, 5, 0.2) is False and promotion(9, 5, 0.2) == "passed", (
            "改了表只动一边 ⇒ 另一边自带第二份阈值")


# ── 6. 生产装配无断点：真 EKB → 规范指标 → 编排器 → 判据 ───────────


def _age_the_install(probe, days: int = 8) -> None:
    """把 RSI 装配时刻推旧，让「7 天无回滚」这条判据可被满足。

    走 `rollback_manager.installed_at` 公开属性（工单 001 基线 A 的同款手法），
    不碰 `conftest` 规则 1 禁止的私赋部署阶段。
    """
    probe.orchestrator.rollback_manager.installed_at = (
        datetime.now(timezone.utc) - timedelta(days=days)
    )


class TestProductionWiring:
    def test_run_iteration_feeds_the_metrics_readout_into_the_guard(
            self, rsi_probe_factory, monkeypatch):
        """供值点只能是编排器的规范指标，判据面不得自己另取一份。"""
        probe = rsi_probe_factory(rsi_phase=2)
        captured = {}

        def _spy(metrics):
            captured.update(metrics)
            return False

        monkeypatch.setattr(probe.orchestrator.deployment_controller,
                            "evaluate_phase_transition", _spy)

        probe.orchestrator.run_iteration()

        assert "experience_quality" in captured, "编排器未把经验质量读数喂进晋升判据"
        assert captured["experience_quality"] == \
            probe.orchestrator.metrics.experience_quality_readout()

    def test_empty_library_end_to_end_leaves_phase_two(self, rsi_probe_factory):
        """真 EKB（conftest 已指向临时库）为空 ⇒ 判据无据，阶段既不推进也不否决。"""
        probe = rsi_probe_factory(rsi_phase=2)
        _age_the_install(probe)

        result = probe.orchestrator.run_iteration()

        assert probe.phase == 2, "无经验质量读数却推进了"
        verdict = result["phase_verdict"]
        assert verdict["state"] == "unevidenced", verdict
        assert "experience_quality" in verdict["reason"], verdict

    def test_good_library_end_to_end_promotes_to_phase_three(self, rsi_probe_factory):
        """质好 ⇒ 走满收敛窗口后真的推进到 phase 3：这条链从头到尾没有断点。"""
        ekb = get_experience_knowledge_base()
        for i in range(3):
            rid = ekb.add_experience_record("chat", _rec(f"导出 PDF 报告 甲乙丙{i}"), evidence=True)
            assert ekb.record_injection_adoption([rid], True) == 1
        snap = ekb.quality_snapshot()
        assert snap["adoption_decisions"] >= 2, f"前置失效：{snap}"
        assert snap["adoption_success_rate"] == pytest.approx(1.0), f"前置失效：{snap}"

        probe = rsi_probe_factory(rsi_phase=2)
        _age_the_install(probe)

        probe.run(probe.orchestrator.convergence_analyzer.window_size + 2)

        assert probe.phase == 3, (
            f"经验质量有证据且其余判据满足，却仍停在 {probe.phase}："
            f"{probe.results[-1]['phase_verdict']}")

    def test_the_same_run_without_a_library_does_not_promote(self, rsi_probe_factory):
        """上一条的反例：只差「经验库里有没有采纳证据」这一个条件。"""
        probe = rsi_probe_factory(rsi_phase=2)
        _age_the_install(probe)

        probe.run(probe.orchestrator.convergence_analyzer.window_size + 2)

        assert probe.phase == 2, "空库竟然推进了 ⇒ 判据没吃经验质量"
        assert "experience_quality" in probe.results[-1]["phase_verdict"]["reason"]


# ── 7. 观测面：无据要说得出，且必须看得见 ──────────────────────────


class TestObservationSurface:
    def test_phase_verdict_is_on_the_response_summary(self, rsi_probe_factory):
        """`unevidenced` 必须出现在观测面（CONTEXT.md 的三态铁规），不能只活在日志里。"""
        from neurova.evolution.rsi.result_summary import RSI_SUMMARY_FIELDS, summarize_rsi_result

        probe = rsi_probe_factory(rsi_phase=2)
        # 天数不足是硬否决，会先于"经验质量无据"返回；把装配时刻推旧才测得到本单那条边
        _age_the_install(probe)

        summary = summarize_rsi_result(probe.orchestrator.run_iteration())

        assert "phase_verdict" in RSI_SUMMARY_FIELDS, "新字段未进摘要契约"
        assert summary["phase_verdict"]["state"] == "unevidenced", summary
        assert "experience_quality" in summary["phase_verdict"]["reason"], summary

    def test_status_surface_shows_why_promotion_is_blocked(self, rsi_probe_factory):
        """被经验质量卡住要能在状态面读出来，否则运维只看见「停在 2 且没人知道为什么」。

        工单 012 把读点从 `push_rsi_result`（生产零调用方，已删）换成
        `orchestrator.get_status()` —— 断言强度不减：仍是"受阻原因必须可达人"。
        """
        probe = rsi_probe_factory(rsi_phase=2)
        _age_the_install(probe)
        probe.orchestrator.run_iteration()

        verdict = probe.orchestrator.get_status()["phase_verdict"]

        assert verdict["state"] == "unevidenced", verdict
        assert "experience_quality" in verdict["reason"], (
            f"晋升受阻原因未进状态面：{verdict['reason']!r}")
