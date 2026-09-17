"""benchmark 回归门 — 把 RSI 端到端评测集接成文本进化的 GATE。

核心纪律:benchmark 是 GATE 不是 fitness——
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


#: 无 apply_fn 时的显式中性 gain（区别于"真测出来 0 增益"）
NEUTRAL_GAIN = 0.0
#: 中性通过的原因标签——审计时必须能看出"这道门没咬合"
NEUTRAL_REASON_NO_APPLY_FN = "no_apply_fn"


def make_eval_harness_gate(
    orchestrator: Any = None,
    live_params_provider: Optional[Callable[[], dict]] = None,
    apply_fn: Optional[Callable[[str], Any]] = None,
) -> Callable[[str, str], float]:
    """构造 bench_gate: `(baseline_text, candidate_text) -> gain`。

    apply_fn(candidate_text) -> restore:把候选暂挂进系统后返回恢复函数。

    诚实边界（P0 复核，2026-09-17）：无 apply_fn 时纯文本候选**不触及**
    eval_harness 度量的四族参数 → 返回中性 `NEUTRAL_GAIN`，并在返回函数上
    挂 `neutral`/`neutral_reason` 供审计取证。**绝不假称测过**：文本候选在
    四族参数上本来就是 0 位移，"跑一遍参数快照"得到 0 也不是证据。

    默认 apply_fn（真实接线）：用技能注册表临时挂载候选正文，度量后再恢复——
    否则 `make_skill_evolution_runner()` 走的是这条恒中性分支，`bench_tolerance`
    形同不存在（复核发现"参数族进化的门"从未咬合过技能文本进化）。
    """
    from neurova.evolution.rsi.eval_harness import RSIEvalHarness

    harness = RSIEvalHarness()

    if apply_fn is None and orchestrator is not None:
        apply_fn = _registry_apply_fn(orchestrator)

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
            # 纯文本候选不触及参数族——**中性**（非"测得 0"）。基线度量确实
            # 跑了一遍，但那不是"候选的增益"。理由随函数外挂供审计取证。
            logger.debug("bench gate(无 apply_fn): before=%.4f, 纯文本候选中性通过", before)
            return NEUTRAL_GAIN
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

    gate.neutral = apply_fn is None
    gate.neutral_reason = NEUTRAL_REASON_NO_APPLY_FN if apply_fn is None else ""
    return gate


def _registry_apply_fn(orchestrator: Any) -> Optional[Callable[[str], Any]]:
    """从编排器/agent 取技能注册表，构造"挂候选 → 度量 → 恢复"的真实 apply_fn。

    拿不到注册表就返回 None（门保持显式中性，不假装咬合）。
    """
    agent = getattr(orchestrator, "agent", None) or getattr(orchestrator, "_agent", None)
    registry = getattr(agent, "_skill_registry", None)
    if registry is None:
        return None

    def apply_fn(candidate_text: str) -> Callable[[], None]:
        entries = getattr(registry, "_skills", None)
        if not isinstance(entries, dict):
            return lambda: None
        snapshot = dict(entries)
        # 候选正文挂到所有技能上（参数族度量的是"这套系统在用哪份正文"）
        for entry in entries.values():
            config = getattr(entry, "config", None)
            if isinstance(config, dict):
                config["context_template"] = candidate_text
        return lambda: entries.update(snapshot)

    return apply_fn
