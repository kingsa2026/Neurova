"""benchmark 回归门 — 把 RSI 端到端评测集接成文本进化的 GATE。

核心纪律(Hermes 对比 2026-09-13):benchmark 是 GATE 不是 fitness——
变体在评测集上再好,系统基准回退即拒绝。

接线说明(诚实边界,勿超读):
  - eval_harness 度量的是四族可优化参数(AdaptiveToolWeights/Sleep/
    Emotion/Experience)的**行为地板**;纯文本候选(技能/提示词正文)不触及
    这些参数 → 门对该类候选中性通过(0),这是诚实降级,不假装测过;
  - 门咬合的接线点在 apply_fn:调用方提供"应用候选 → 度量 → 恢复"的
    通道(如把进化产物暂挂到系统参数/注册表),门即获得
    "先量基线 → 应用候选 → 再量 → 恢复 → 回传 gain"的完整语义;
  - harness.run() 真实执行(确定性、零 LLM、毫秒级),不是假调用。
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)


def _params_from_orchestrator(orchestrator: Any) -> dict:
    """从 RSI 编排器取活参数(与 orchestrator._measure_performance 同口径)。"""
    return {
        system: {
            p.name: p.current_value for p in params if p.current_value is not None
        }
        for system, params in orchestrator.integration_manager.get_optimizable_parameters().items()
    }


def make_eval_harness_gate(
    orchestrator: Any = None,
    live_params_provider: Optional[Callable[[], dict]] = None,
    apply_fn: Optional[Callable[[str], Any]] = None,
) -> Callable[[str, str], float]:
    """构造 bench_gate: `(baseline_text, candidate_text) -> gain`。

    apply_fn(candidate_text) -> restore:把候选暂挂进系统后返回恢复函数。
    无 apply_fn 时纯文本候选 → gain 恒 0(中性通过,真实度量仍执行)。
    """
    from neurova.evolution.rsi.eval_harness import RSIEvalHarness

    harness = RSIEvalHarness()

    def _live_params() -> dict:
        if live_params_provider is not None:
            try:
                return live_params_provider() or {}
            except Exception as e:  # noqa: BLE001
                logger.debug("live_params_provider 失败, 空参数评测: %s", e)
                return {}
        if orchestrator is not None:
            try:
                return _params_from_orchestrator(orchestrator)
            except Exception as e:  # noqa: BLE001
                logger.debug("从编排器取活参数失败, 空参数评测: %s", e)
                return {}
        return {}

    def gate(baseline_text: str, candidate_text: str) -> float:
        before = float(harness.run(_live_params())["score"])
        if apply_fn is None:
            # 纯文本候选不触及参数族——中性通过,但基线度量是真实跑出来的
            logger.debug("bench gate(无 apply_fn): before=%.4f, 纯文本候选中性通过", before)
            return 0.0
        restore: Any = None
        try:
            restore = apply_fn(candidate_text)
            after = float(harness.run(_live_params())["score"])
        finally:
            if restore is not None:
                try:
                    restore()
                except Exception as e:  # noqa: BLE001 - 恢复失败必须暴露,不能吞
                    logger.error("bench gate 恢复系统状态失败: %s", e)
        gain = after - before
        logger.debug("bench gate: before=%.4f after=%.4f gain=%.4f", before, after, gain)
        return gain

    return gate
